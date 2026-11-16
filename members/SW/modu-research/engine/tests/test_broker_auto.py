"""v0.21 일괄 등록·자동 승인 규칙 v1."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mrn import broker, broker_auto as ba

LO, HI = '2026-08-08', '2026-11-08'
T = {'006400', '005930'}


def rep(**kw):
    r = {'file': 'a.pdf', 'status': 'ok', 'manifest_sha_match': True, 'ticker': '006400', 'report_date': '2026-10-30', 'past_check': 'match'}
    r.update(kw)
    return r


def cands(rev='18000000', op='900000', fys=(2026, 2027)):
    out = []
    for fy in fys:
        out += [{'fiscal_year': fy, 'metric': 'revenue', 'value_mn': rev}, {'fiscal_year': fy, 'metric': 'operatingProfit', 'value_mn': op}]
    return out


class Rule(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(ba.judge(rep(), cands(), T, LO, HI), (True, []))

    def test_each_rule(self):
        cases = {'R1': (rep(manifest_sha_match=None), cands()), 'R2': (rep(ticker='999999'), cands()),
                 'R3': (rep(report_date='2026-07-31'), cands()), 'R4': (rep(past_check='not_available'), cands()),
                 'R5': (rep(), cands(op='19000000')), 'R6': (rep(), cands(fys=(2026, 2031)))}
        for rule, (r, c) in cases.items():
            ok, miss = ba.judge(r, c, T, LO, HI)
            self.assertFalse(ok, rule)
            self.assertIn(rule, miss, rule)

    def test_compact_date_and_no_candidates(self):
        self.assertTrue(ba.judge(rep(report_date='20261030'), cands(), T, LO, HI)[0])
        self.assertIn('R5', ba.judge(rep(), [], T, LO, HI)[1])

    def test_mismatch_never_auto(self):
        self.assertIn('R4', ba.judge(rep(past_check='mismatch'), cands(), T, LO, HI)[1])


class RegisterBulk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        (self.d / 'inbox').mkdir()
        self.env = mock.patch.dict(os.environ, {'MODU_NODES_BROKER_DIR': str(self.d)})
        self.env.start()
        (self.d / 'inbox' / 'x_하나증권.pdf').write_bytes(b'%PDF-1.4 test one')
        (self.d / 'inbox' / 'y_대신증권.pdf').write_bytes(b'%PDF-1.4 test two')
        meta = {'files': {
            'x_하나증권.pdf': {'ticker': '006400', 'broker': '하나증권', 'date': '2026-10-30', 'title': 't', 'opinion': 'Buy',
                            'target_price': '500000', 'research_url': 'https://m.stock.naver.com/research/company/97374'},
            'y_대신증권.pdf': {'ticker': '123456', 'broker': '대신증권', 'date': '2026-10-30'}}}
        (self.d / 'inbox' / '_bulk_meta.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_register_with_source(self):
        out = ba.register_bulk(ba.load_meta(), T, LO, HI)
        self.assertEqual((out['registered'], out['skipped']), (1, 1))      # 유니버스 밖은 건너뜀
        man = json.loads((self.d / 'manifest.json').read_text(encoding='utf-8'))
        f = man['files'][0]
        self.assertEqual(f['원문주소'], 'https://m.stock.naver.com/research/company/97374')
        self.assertTrue(f['확인 근거'].startswith('자동 등록'))
        self.assertTrue((self.d / f['파일명']).exists())
        again = ba.register_bulk(ba.load_meta(), T, LO, HI)
        self.assertEqual((again['registered'], again['already']), (0, 1))  # 같은 해시는 다시 등록하지 않음

    def test_alnum_ticker(self):
        rec = broker.register({'file': 'x_하나증권.pdf', 'ticker': '0126Z0', 'report_date': '2026-10-29', 'broker': '하나증권'})
        self.assertEqual(broker.report_ticker(rec), '0126Z0')
        with self.assertRaises(ValueError):
            broker.register({'file': 'y_대신증권.pdf', 'ticker': 'ABCDEF', 'report_date': '2026-10-29', 'broker': '대신증권'})

    def test_manual_register_unchanged(self):
        rec = broker.register({'file': 'x_하나증권.pdf', 'ticker': '006400', 'report_date': '2026-10-30', 'broker': '하나증권'})
        self.assertEqual((rec['원문주소'], rec['확인 근거']), ('', '사용자 등록(받은 편지함)'))


class Revert(unittest.TestCase):
    def test_revert_only_auto(self):
        from mrn.store import Store
        tmp = tempfile.mkdtemp()
        try:
            st = Store(tmp)
            c = [{'id': f'k{i}', 'file': 'a.pdf', 'sha256': 's', 'value_mn': '1'} for i in range(3)]
            st.broker_upsert('t', [{'file': 'a.pdf', 'sha256': 's'}], c)
            st.broker_review(ba.RULE, 'k0', 'approve')
            st.broker_review(ba.RULE, 'k1', 'approve')
            st.broker_review('human', 'k2', 'approve')
            with mock.patch.object(ba, 'store', lambda: st):
                self.assertEqual(ba.revert(), {'reverted': 2})
            _, cs = st.broker_reports()
            self.assertEqual({x['id']: x['state'] for x in cs}, {'k0': 'proposed', 'k1': 'proposed', 'k2': 'approved'})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()


class ExtractorV2(unittest.TestCase):
    def test_comparison_table_skipped(self):
        page = '(십억원) 변경 전 변경 후 2026F 2027F 2026F 2027F 매출액 2,844.5 3,157.4 2,792.7 3,090.6 영업이익 308.7 315.6 302.0 303.8'
        self.assertEqual(broker.find_tables([page]), [])

    def test_exact_label_preferred(self):
        page = ('(십억원) 2025 2026F 2027F 2028F 매출액 3,696 5,398 6,691 7,581 조정영업이익 269 339 582 821 '
                '영업이익 236 4,514 3,853 2,844')
        t = broker.find_tables([page])[0]
        self.assertEqual(t['labels']['operatingProfit'], '영업이익')
        self.assertTrue(t['label_exact'])
        self.assertEqual(t['rows']['operatingProfit']['2027F'][1], '3,853')

    def test_loose_label_flagged(self):
        page = '(십억원) 2025 2026F 2027F 2028F 매출액 3,696 5,398 6,691 7,581 조정영업이익 269 339 582 821'
        t = broker.find_tables([page])[0]
        self.assertEqual(t['labels']['operatingProfit'], '조정영업이익')
        self.assertFalse(t['label_exact'])
        self.assertIn('R7', ba.judge(rep(label_exact=False), cands(), T, LO, HI)[1])

    def test_net_sales_is_exact(self):
        page = '(십억원) 2025 2026E 2027E 순매출액 13,738.4 14,232.0 14,726.1 영업이익 500 520 540'
        t = broker.find_tables([page])[0]
        self.assertEqual((t['labels']['revenue'], t['label_exact']), ('순매출액', True))


class Filenames(unittest.TestCase):
    def test_format(self):
        self.assertEqual(broker.report_filename('2026-10-30', '033780', 'KT&G', '하나증권', 'abcdef1234'),
                         '20261030_033780_KTG_하나증권_abcdef12.pdf')
        self.assertEqual(broker.report_filename('2026-10-30', '0126Z0', '0126Z0', 'DB증권', 'abcdef1234'),
                         '20261030_0126Z0_DB증권_abcdef12.pdf')

    def test_rename_plan_and_apply(self):
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name)
        (d / 'old.pdf').write_bytes(b'%PDF x')
        man = {'files': [{'파일명': 'old.pdf', '보고서일': '2026-10-30', '증권사': '하나증권', '종목': '삼성SDI(006400)', 'sha256': 'deadbeef99'}]}
        (d / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False), encoding='utf-8')
        with mock.patch.dict(os.environ, {'MODU_NODES_BROKER_DIR': str(d), 'MODU_NODES_DATA_DIR': str(d / 'data')}), \
                mock.patch('mrn.market.company_name', lambda t, *a: '삼성SDI'):
            plan = ba.rename(apply=False)
            self.assertEqual((plan['planned'], plan['applied']), (1, False))
            self.assertTrue((d / 'old.pdf').exists())
            res = ba.rename(apply=True)
        new = '20261030_006400_삼성SDI_하나증권_deadbeef.pdf'
        self.assertEqual(res['renamed'], 1)
        self.assertTrue((d / new).exists() and not (d / 'old.pdf').exists())
        f = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))['files'][0]
        self.assertEqual((f['파일명'], f['이전 파일명']), (new, 'old.pdf'))
        with mock.patch.dict(os.environ, {'MODU_NODES_BROKER_DIR': str(d)}):
            self.assertEqual(broker.current_name('old.pdf'), new)          # 저장된 워크플로의 옛 이름
            self.assertEqual(broker.current_name('other.pdf'), 'other.pdf')
        tmp.cleanup()
