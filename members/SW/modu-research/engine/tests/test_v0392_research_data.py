"""v0.39.2 연구용 데이터: KIS 현재가 보여 주기(스위치·캐시·키 없음) · 컨센서스(보고서 집계 + 정식 데이터 파일). 네트워크 없음."""
import os, tempfile, unittest
from pathlib import Path
from unittest import mock

from mrn import research_data as RD


class FakeKis:
    def __init__(self, price=271000, pct='1.20', fail=False):
        self.n, self.p, self.pct, self.fail = 0, price, pct, fail

    def price(self, t):
        self.n += 1
        if self.fail:
            raise RuntimeError('KIS 조회 실패(HTTP 500 EGW00201)')
        return {'price': self.p, 'pct': float(self.pct), 'market': 'KOSPI'}


class Quote(unittest.TestCase):
    def setUp(self):
        RD._cache.clear()

    def test_off_by_default_and_never_calls_kis(self):
        k = FakeKis()
        r = RD.quote('005930', env={}, kis=k)
        self.assertEqual((r['enabled'], k.n), (False, 0))

    def test_on_with_label_and_cache(self):
        k, env = FakeKis(), {'MODU_SHOW_QUOTES': '1'}
        a = RD.quote('005930', env=env, kis=k, clock=lambda: 1000.0)
        b = RD.quote('005930', env=env, kis=k, clock=lambda: 1020.0)   # 30초 안: 다시 부르지 않음
        c = RD.quote('005930', env=env, kis=k, clock=lambda: 1031.0)
        self.assertEqual((a['price'], a['pct'], a['available']), (271000, 1.2, True))
        self.assertIn('연구용', a['label']); self.assertIn('답 카드', a['note'])
        self.assertTrue(b['cached']); self.assertEqual(k.n, 2); self.assertFalse(c['cached'])

    def test_no_key_bad_ticker_and_failure(self):
        env = {'MODU_SHOW_QUOTES': '1'}
        self.assertFalse(RD.quote('005930', env=env)['available'])            # 키 없음 → KIS 안 부름
        self.assertIn('6자리', RD.quote('AAPL', env=env, kis=FakeKis())['note'])
        r = RD.quote('000660', env=env, kis=FakeKis(fail=True))
        self.assertFalse(r['available']); self.assertIn('KIS 조회 실패', r['note'])


HEAD = 'provider,ticker,fiscal_year,metric,value_mn,n_estimates,as_of\n'


class Consensus(unittest.TestCase):
    def folder(self, text, name='a.csv'):
        d = tempfile.mkdtemp(); Path(d, name).write_text(text, encoding='utf-8'); return d

    def test_read_files_validates_and_keeps_latest(self):
        d = self.folder(HEAD + 'P사,5930,2026,operatingProfit,"369,300,000",12,2026-10-30\n'
                               'P사,005930,2026,operatingProfit,370000000,13,2026-11-10\n'
                               'P사,005930,2026,revenue,abc,1,2026-11-10\n'
                               'P사,005930,2026,eps,1,1,2026-11-10\n'
                               'P사,000660,2026,revenue,90000000,8,2026-11-01\n')
        rows, problems, files = RD.read_files(d, '005930')
        self.assertEqual(files, ['a.csv'])
        self.assertEqual(len(rows), 1); self.assertEqual((rows[0]['value_mn'], rows[0]['n_estimates'], rows[0]['as_of']), ('370000000', 13, '2026-11-10'))
        self.assertEqual(len(problems), 2)
        rows, _, _ = RD.read_files(d, '005930', until='2026-11-01')            # 기준 날짜 뒤 줄은 안 씀
        self.assertEqual(rows[0]['value_mn'], '369300000')

    def test_missing_columns_and_no_folder(self):
        d = self.folder('ticker,value\n005930,1\n')
        self.assertIn('빠진 칸', RD.read_files(d)[1][0])
        self.assertEqual(RD.read_files('/no/such/folder'), ([], [], []))

    def test_broker_summary_uses_existing_trend(self):
        fs = [{'broker': b, 'report_date': '2026-10-%02d' % (i + 1), 'metric': 'operatingProfit', 'fiscal_year': 2026, 'value': v}
              for i, (b, v) in enumerate([('A', '360000000'), ('B', '370000000'), ('C', '380000000')])]
        s = RD.broker_summary(fs)
        self.assertEqual(len(s), 1)
        self.assertEqual((s[0]['n'], s[0]['median_mn'], s[0]['min_mn'], s[0]['max_mn'], s[0]['thin']), (3, '370000000', '360000000', '380000000', False))
        self.assertEqual(RD.broker_summary(fs, until='2026-10-01')[0]['n'], 1)

    def test_switch_and_notice(self):
        self.assertFalse(RD.consensus('005930', [], env={'MODU_SHOW_CONSENSUS': '0'})['enabled'])
        r = RD.consensus('005930', [], env={'MODU_NODES_CONSENSUS_DIR': '/no/such'})
        self.assertTrue(r['enabled']); self.assertIn('공식 시장 예상치', r['note']); self.assertEqual(r['provider'], [])


class Api(unittest.TestCase):
    def test_endpoints(self):
        from fastapi.testclient import TestClient
        from mrn.server import create_app
        cdir = tempfile.mkdtemp(); Path(cdir, 'f.csv').write_text(HEAD + '정식사,005930,2026,revenue,333000000,20,2026-11-01\n', encoding='utf-8')
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'MODU_SHOW_QUOTES': '0', 'MODU_NODES_CONSENSUS_DIR': cdir}):
            with TestClient(create_app(data_dir=d)) as c:
                self.assertEqual(c.get('/api/research/flags').json(), {'quotes': False, 'consensus': True})
                self.assertFalse(c.get('/api/quote/005930').json()['enabled'])
                j = c.get('/api/consensus/005930').json()
                self.assertEqual(j['provider'][0]['provider'], '정식사'); self.assertEqual(j['model_calls'], 0)
                self.assertEqual(c.get('/api/consensus/005930?cutoff=2026-10-01T16:00:00+09:00').json()['provider'], [])


if __name__ == '__main__':
    unittest.main()
