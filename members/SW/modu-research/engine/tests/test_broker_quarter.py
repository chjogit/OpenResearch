"""v0.24 분기·순이익 전망 추출과 분기 전망 성적표."""
import os
import tempfile
import unittest
from decimal import Decimal
from mrn import broker_quarter as Q

PAGE = ("(십억원) 1Q25 2Q25 3Q25 4Q25 1Q26 2Q26 3Q26P 4Q26F 2025 2026F 2027F "
        "매출액 1,000.0 1,100.0 1,200.0 1,300.0 1,400.0 1,500.0 1,600.0 1,700.0 4,600.0 6,200.0 7,000.0 "
        "영업이익 100.0 110.0 120.0 130.0 140.0 150.0 160.0 170.0 460.0 620.0 700.0")


class Extract(unittest.TestCase):
    def test_qparse_tags(self):
        self.assertEqual(Q.qparse('3Q26E'), (2026, 3, 'E'))
        self.assertEqual(Q.qparse('2Q26P'), (2026, 2, 'P'))
        self.assertIsNone(Q.qparse('2026E'))

    def test_quarter_table_first_columns_and_tags(self):
        t = Q.find_q_tables([PAGE])
        self.assertEqual(len(t), 1)
        self.assertEqual(t[0]['rows']['revenue']['4Q26F'][0], Decimal('1700.0'))
        self.assertEqual(t[0]['rows']['operatingProfit']['1Q25'][0], Decimal('100.0'))
        act = {(2025, 1, 'revenue'): Decimal(1000000), (2025, 2, 'revenue'): Decimal(1100000), (2026, 1, 'operatingProfit'): Decimal(140000)}
        tb, unit, ch, st = Q.choose_q(t, act)
        self.assertEqual((unit, st), ('십억원', 'match'))
        self.assertFalse(any(c['col'] == '3Q26P' for c in ch))           # 잠정(P)은 실적 대조에도 전망에도 쓰지 않음

    def test_comparison_table_skipped(self):
        cmp = "3Q26E 4Q26E 1Q27E 2Q27E 3Q26E 4Q26E 1Q27E 2Q27E 매출액 1 2 3 4 5 6 7 8 영업이익 1 2 3 4 5 6 7 8"
        self.assertEqual(Q.find_q_tables([cmp]), [])

    def test_missing_cells_not_shifted(self):
        short = "1Q26 2Q26 3Q26E 4Q26E 매출액 10 20 30 영업이익 1 2 3 4"
        t = Q.find_q_tables([short])
        self.assertTrue(t and 'revenue' not in t[0]['rows'])               # 칸이 모자라면 열이 밀리므로 쓰지 않음

    def test_net_income_prefers_explicit_label(self):
        pages = ["2025 2026F 2027F 순이익 280 558 874", "2024A 2025A 2026F 당기순이익 242 284 559"]
        t = Q.find_ni(pages, Q.NI_SETS['netIncome'])
        best = Q.choose_ni(t, {2025: Decimal(284000)})
        self.assertEqual(best[0]['label'], '당기순이익')


class Actuals(unittest.TestCase):
    def test_q4_is_annual_minus_q3_ytd(self):
        rows = [{'report_code': '11014', 'fiscal_year': 2025, 'account_id': 'ifrs-full_Revenue', 'fs_div': 'CFS', 'amount': '300000000', 'amount_ytd': '900000000', 'rcept_no': '20251114000001'},
                {'report_code': '11011', 'fiscal_year': 2025, 'account_id': 'ifrs-full_Revenue', 'fs_div': 'CFS', 'amount': '1300000000', 'rcept_no': '20260310000001'}]
        act, ni, filed = Q.dart_actuals(rows)
        self.assertEqual(act[(2025, 4, 'revenue')], Decimal(400))
        self.assertEqual(filed[(2025, 3)], '2025-11-14')

    def test_known_date_uses_first_prelim_after_quarter(self):
        self.assertEqual(Q.known_date(2026, 3, ['2026-07-28', '2026-10-30'], {(2026, 3): '2026-11-14'}), '2026-10-30')
        self.assertEqual(Q.known_date(2026, 3, [], {}), None)


class Scorecard(unittest.TestCase):
    def test_reports_after_known_date_not_scored(self):
        f = [{'ticker': 'X', 'broker': 'A', 'report_date': '2026-10-01', 'fiscal_year': 2026, 'quarter': 3, 'metric': 'revenue', 'value_mn': '100'},
             {'ticker': 'X', 'broker': 'A', 'report_date': '2026-11-01', 'fiscal_year': 2026, 'quarter': 3, 'metric': 'revenue', 'value_mn': '105'},
             {'ticker': 'X', 'broker': 'B', 'report_date': '2026-10-20', 'fiscal_year': 2026, 'quarter': 3, 'metric': 'revenue', 'value_mn': '90'}]
        rows = Q.scorecard(f, {('X', 2026, 3, 'revenue'): Decimal(104)}, {('X', 2026, 3): '2026-10-30'})
        a = next(r for r in rows if r['broker'] == 'A')
        self.assertEqual(a['report_date'], '2026-10-01')                    # 잠정실적 뒤(11-01) 보고서는 전망이 아님
        self.assertEqual(a['status'], 'scored')
        self.assertEqual(a['error_pct'], '-3.8')

    def test_awaiting_without_actual(self):
        rows = Q.scorecard([{'ticker': 'X', 'broker': 'A', 'report_date': '2026-10-01', 'fiscal_year': 2026, 'quarter': 4, 'metric': 'revenue', 'value_mn': '1'}], {}, {})
        self.assertEqual(rows[0]['status'], 'awaiting')


class StoreV2(unittest.TestCase):
    def test_put_is_idempotent_and_revertable(self):
        from mrn.store import Store
        with tempfile.TemporaryDirectory() as d:
            st = Store(d)
            r = {'file': 'a.pdf', 'sha256': 'f' * 64, 'ticker': 'X', 'metric': 'revenue', 'fiscal_year': '2026', 'quarter': '3', 'auto_ok': True,
                 'broker': 'A', 'report_date': '2026-10-01', 'value_mn': '100'}
            p = dict(r, fiscal_year='2027', quarter='1', auto_ok=False)
            self.assertEqual(st.v2_forecasts_put('t', [r, p], 'auto-rule-q1'), 2)
            self.assertEqual(st.v2_forecasts_put('t', [r, p], 'auto-rule-q1'), 0)
            self.assertEqual(len(st.v2_forecasts('X')), 1)
            self.assertEqual(len(st.v2_forecasts('X', 'proposed')), 1)
            self.assertEqual(st.v2_forecasts_revert('t', 'auto-rule-q1'), 1)
            self.assertEqual(len(st.v2_forecasts('X', 'proposed')), 1)      # 사람 확인 대기분은 되돌리기에서 지우지 않음


if __name__ == '__main__':
    unittest.main()
