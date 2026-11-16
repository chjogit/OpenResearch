"""v0.39.3: 가격 사본의 KIS 보충 행(kis) — 스위치·같은 날 금융위 우선·출처 표시. 네트워크 없음."""
import hashlib, json, os, tempfile, unittest
from unittest import mock

from mrn import market, price_src as PS


def _h(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def snap(root, rows, name='20261115T180000+0900'):
    d = os.path.join(root, name); os.makedirs(d)
    tables = {}
    for t, recs in (('price_daily', rows), ('company', [{'ticker': '005930', 'name': '삼성전자'}])):
        p = os.path.join(d, t + '.jsonl')
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
        tables[t] = {'file': t + '.jsonl', 'rows': len(recs), 'sha256': _h(p), 'source_grade': 'public:fsc', 'query': 'test', 'note': ''}
    mp = os.path.join(d, 'manifest.json')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write(json.dumps({'asof_kst': name, 'tables': tables}))
    with open(os.path.join(d, 'manifest.sha256'), 'w', encoding='utf-8') as f:
        f.write(_h(mp) + '  manifest.json\n')
    with open(os.path.join(root, 'LATEST.txt'), 'w', encoding='utf-8') as f:
        f.write(name + '\n')


def row(day, close, src):
    return {'ticker': '005930', 'trade_date': day, 'open': str(close), 'high': str(close), 'low': str(close), 'close': str(close),
            'volume': '10', 'trade_value': '1', 'market_cap': '1', 'source': src, 'collected_at': '2026-11-15T09:00:00+00:00'}


class Rules(unittest.TestCase):
    def test_ok_and_switch(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MODU_PRICE_KIS', None)
            self.assertTrue(PS.ok('fsc')); self.assertTrue(PS.ok('kis')); self.assertFalse(PS.ok('yfinance')); self.assertFalse(PS.ok(None))
        with mock.patch.dict(os.environ, {'MODU_PRICE_KIS': '0'}):
            self.assertTrue(PS.ok('fsc')); self.assertFalse(PS.ok('kis'))

    def test_pick_prefers_fsc_and_sorts(self):
        rows = [row('2026-11-07', 3, 'kis'), row('2026-11-06', 2, 'kis'), row('2026-11-06', 1, 'fsc'), row('2026-11-05', 9, 'yfinance')]
        got = PS.pick(rows)
        self.assertEqual([(r['trade_date'], r['source'], r['close']) for r in got], [('2026-11-06', 'fsc', '1'), ('2026-11-07', 'kis', '3')])


class Series(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'MODU_NODES_NEON_DIR': self.tmp.name}); self.env.start()
        days = ['2026-11-03', '2026-11-04', '2026-11-05']
        snap(self.tmp.name, [row(d, 200000 + i, 'fsc') for i, d in enumerate(days)] + [row('2026-11-06', 210000, 'kis'), row('2026-11-13', 215000, 'kis')])

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def test_kis_rows_used_and_labelled(self):
        os.environ.pop('MODU_PRICE_KIS', None)
        s = market.price_series('005930', '2026-11-14T16:00:00+09:00')
        self.assertEqual(s['rows'][-1]['trade_date'], '2026-11-13'); self.assertEqual(s['rows'][-1]['close'], '215000')
        self.assertEqual(s['source']['kis_rows'], 2); self.assertIn('한국투자증권 일별 시세(kis) 2거래일 보충', s['source']['origin'])
        s2 = market.price_series('005930', '2026-11-10T16:00:00+09:00')   # 기준 날짜 뒤 KIS 행은 안 씀
        self.assertEqual(s2['rows'][-1]['trade_date'], '2026-11-06'); self.assertEqual(s2['source']['kis_rows'], 1)

    def test_switch_off_uses_fsc_only(self):
        with mock.patch.dict(os.environ, {'MODU_PRICE_KIS': '0'}):
            s = market.price_series('005930', '2026-11-14T16:00:00+09:00')
        self.assertEqual(s['rows'][-1]['trade_date'], '2026-11-05'); self.assertEqual(s['source']['kis_rows'], 0)
        self.assertNotIn('kis', s['source']['origin'])


if __name__ == '__main__':
    unittest.main()
