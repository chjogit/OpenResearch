"""v0.37.5: 사업부 매출 관문 넓히기 — 줄 이름 점검(관문 ③) · 공시 재무 대조 자료 · 꼬리말만 다른 이름 · 표시 없는 누적."""
import unittest
from mrn import segments as S


class Gate3(unittest.TestCase):
    def test_name_issues(self):
        self.assertEqual(S.name_issues('segment', ['DS 부문', 'DX 부문', 'SDC']), [])
        self.assertTrue(S.name_issues('segment', ['방산 부문', '고객1', '고객2']))                      # 주요 고객 표를 사업부로 읽은 경우
        self.assertTrue(S.name_issues('segment', ['택배', '내부매출액', '총 매출액']))
        self.assertTrue(S.name_issues('segment', ['섬유', 'HS Hyosung Vietnam Co., Ltd.']))
        self.assertTrue(S.name_issues('segment', ['LG에너지솔루션'], 'LG에너지솔루션'))                 # 구분 1개 + 회사 이름
        self.assertTrue(S.name_issues('segment', ['A', 'B'], dup=True))
        self.assertEqual(S.name_issues('region', ['국내', '미주', '기타 국가', '대만']), [])
        self.assertTrue(S.name_issues('region', ['한국', '북미', '엘지전자']))                          # 지역 표에 고객사가 섞임
        self.assertTrue(S.name_issues('region', ['A사', '미주']))

    def test_key_ignores_only_the_suffix(self):
        self.assertEqual(S.key_of('x', '물류사업부문'), S.key_of('x', '물류'))
        self.assertEqual(S.key_of('x', 'DS 부문'), S.key_of('x', 'DS'))
        self.assertNotEqual(S.key_of('x', '방산'), S.key_of('x', '철도'))
        self.assertEqual(S.key_of('x', '부문'), '부문')                                                 # 이름 전체가 꼬리말이면 지우지 않음

    def test_revenue_from_facts(self):
        f = lambda y, rc, a, ytd=None, fs='CFS', acc='ifrs-full_Revenue': {'fiscal_year': y, 'report_code': rc, 'amount': str(a), 'amount_ytd': None if ytd is None else str(ytd), 'fs_div': fs, 'account_id': acc}
        r = S.revenue_from_facts([f(2025, '11013', 10, 10), f(2025, '11012', 12, 22), f(2025, '11014', 13, 35), f(2025, '11011', 50), f(2025, '11013', 999, 999, fs='OFS'),
                                  f(2025, '11013', 7, 7, acc='dart_OperatingIncomeLoss'), f(2024, '11011', 40)])
        self.assertEqual(r, {'2025-03-31': 10, '2025-06-30': 12, '2025-09-30': 13, '2025-12-31': 15})   # 연결만, 4분기 = 연간 − 3분기 누적, 3분기 누적이 없으면 만들지 않음

    def test_unmarked_interim_table_is_cumulative(self):
        self.assertEqual(S._slot((2026, 'H1'), 'current', None), (2026, 'H1'))
        self.assertEqual(S._slot((2026, 'Q3'), 'prior', None), (2025, '9M'))
        self.assertEqual(S._slot((2026, 'H1'), 'current', '3m'), (2026, 'Q2'))
        self.assertEqual(S._slot((2026, 'Q1'), 'current', None), (2026, 'Q1'))


if __name__ == '__main__':
    unittest.main()
