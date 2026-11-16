"""v0.37.8: 기업가치제고계획 문장 · 소각 목표 대조 · 자본배분 연표 · 약속–실행에서 자회사 공시 제외."""
import os, tempfile, unittest
from mrn import capital as C, promise as P
from tests.test_v0364_promise import store, decision, retire, cells


def plan(*lines):
    return '<DOCUMENT>' + cells('기업가치 제고 계획(자율공시)', '1. 계획서 명칭', '시험 밸류업', '2. 주요 내용', *lines,
                                 '3. 조세특례제한법 제104조의27에 따른 고배당기업 여부', '해당', '배당성향(%)', '25.1', '4. 결정일자', '2026-03-01') + '</DOCUMENT>'


def sale(qty, amount, purpose):
    return '<DOCUMENT>' + cells('자기주식 처분 결정', '1. 처분예정주식(주)', '보통주식', f'{qty:,}', '기타주식', '-', '3. 처분예정금액(원)', '보통주식', f'{amount:,}', '기타주식', '-',
                                 '5. 처분목적', purpose, '7. 처분상대방', '임직원') + '</DOCUMENT>'


class Plan(unittest.TestCase):
    def test_items_modes_join_and_end(self):
        items, err = C.plan_items(plan('&lt;목표 설정&gt;', '- ROE : \'27년 10% 달성 목표', '□ 시설 투자를 위해', "'26년에 총 110조원 R&amp;D 투자 계획",
                                       '2. 이행 현황', '- 배당 2.6조원 지급을 완료하였습니다', '3. 목표 대응 계획', '- 자기주식 50만주 소각 예정', '- 2025년 매출 1조원 시현'))
        self.assertIsNone(err)
        self.assertEqual([(i['mode'], i['category']) for i in items], [('target', '수익성'), ('target', '기타'), ('self', '환원'), ('target', '환원'), ('self', '성장')])
        self.assertIn("□ 시설 투자를 위해 '26년에 총 110조원 R&D 투자 계획", [i['text'] for i in items])     # 잘린 줄 잇기 · &amp; 풀기
        self.assertFalse(any('25.1' in i['text'] or '고배당' in i['text'] for i in items))                  # 「3. 조세특례…」 뒤는 읽지 않음
        self.assertEqual(C.retire_targets(items), [{'text': '- 자기주식 50만주 소각 예정', 'qty': 500_000}])
        self.assertEqual(C.plan_items('<DOCUMENT>' + cells('아무 것') + '</DOCUMENT>')[0], [])

    def test_retire_target_rules(self):
        T = lambda t, mode='target': C.retire_targets([{'text': t, 'mode': mode}])
        self.assertEqual(T('- 기 보유 자기주식 70만주 소각 예정 (약 2,000억원)')[0]['qty'], 700_000)
        self.assertEqual(T('기보유 자기주식 87.4만주(3차년도) 소각예정')[0]['qty'], 874_000)
        self.assertEqual(T('③ 주주환원: 911만주 자기주식 소각(1.7조원 규모), 30% 목표로 배당 증가')[0]['qty'], 9_110_000)
        self.assertEqual(T('기보유 자기주식 87.5만주(2차년도) 소각완료, 주주환원율 41% 달성'), [])     # 지난 일
        self.assertEqual(T("발행주식 1억 주 이상 소각: '30년 목표 대비 28% 이행"), [])                  # 이행 문장
        self.assertEqual(T('자사주 전량 즉시 소각(보통주 약 445만주) 추진'), [])                          # 수가 소각 뒤에 오면 읽지 않음(보수적)
        self.assertEqual(T('70만주 소각 예정', mode='self'), [])

    def test_own_filter(self):
        docs = [{'report_nm': '주식소각결정'}, {'report_nm': '주식소각결정(자회사의 주요경영사항)'}, {'report_nm': '[기재정정]주식소각결정(자회사의 주요경영사항)(메리츠증권)'}]
        keep, n = C.own(docs)
        self.assertEqual((len(keep), n), (1, 2))


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = os.path.join(self.tmp.name, 'dart_docs')
        store(self.root, [
            ('20260101000001', 'buyback_decision', '주요사항보고서(자기주식취득결정)', '2026-01-01', decision(1000, 100_000_000, '2026-01-02', '2026-03-31', purpose='주주가치 제고')),
            ('20260102000001', 'buyback_decision', '주요사항보고서(자기주식취득결정)', '2026-01-02', decision(500, 50_000_000, '2026-01-03', '2026-02-28', purpose='임직원 주식보상')),
            ('20260103800001', 'retire', '주식소각결정(자회사의 주요경영사항)', '2026-01-03', retire(77_777, 100000, 1, '2026-01-10')),
            ('20260301800001', 'valueup', '기업가치제고계획(자율공시)', '2026-03-01', plan('3. 목표', '- 자기주식 1,000주 소각 예정')),
            ('20260310800001', 'retire', '주식소각결정', '2026-03-10', retire(990, 100000, 99_000_000, '2026-03-20')),
            ('20260401000001', 'treasury_sale', '주요사항보고서(자기주식처분결정)', '2026-04-01', sale(300, 30_000_000, '2026년 단체교섭에 따른 회사주식 지급')),
            ('20260402000001', 'treasury_sale', '주요사항보고서(자기주식처분결정)(자회사의 주요경영사항)', '2026-04-02', sale(9, 9, '임원 보상')),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_valueup_timeline(self):
        cut = '2026-11-01T16:00:00+09:00'
        pr = P.build('000001', cut, self.root)
        self.assertEqual(len(pr['retires']), 1); self.assertTrue(any('자회사 주식 소각 결정 1건' in h for h in pr['held']))     # 자회사 소각은 빠짐
        v = C.valueup('000001', cut, pr['retires'], self.root)
        t = v['latest']['retire_targets'][0]
        self.assertEqual((t['qty'], t['retired_qty'], t['pct']), (1000, 990, 99.0))
        dis = [{'rcept_no': '20260415000001', 'rcept_dt': '2026-04-15', 'report_nm': '현금ㆍ현물배당결정', 'url': 'u1'},
               {'rcept_no': '20260416000001', 'rcept_dt': '2026-04-16', 'report_nm': '[기재정정]현금ㆍ현물배당결정', 'url': 'u2'},
               {'rcept_no': '20260417000001', 'rcept_dt': '2026-04-17', 'report_nm': '타법인주식및출자증권취득결정(자회사의 주요경영사항)', 'url': 'u3'},
               {'rcept_no': '20260418000001', 'rcept_dt': '2026-04-18', 'report_nm': '신규시설투자등', 'url': 'u4'},
               {'rcept_no': '20261201000001', 'rcept_dt': '2026-12-01', 'report_nm': '회사합병결정', 'url': 'u5'}]
        c = C.timeline('000001', cut, pr, dis, self.root)
        got = [(r['date'], r['kind'], r['group'], r['corrected']) for r in c['rows']]
        self.assertEqual(got, [('2026-01-01', '자기주식 취득 결정', '환원', False), ('2026-01-02', '자기주식 취득 결정', '보상', False), ('2026-03-10', '주식 소각 결정', '환원', False),
                               ('2026-04-01', '자기주식 처분 결정', '보상', False), ('2026-04-15', '배당', '환원', True), ('2026-04-18', '시설투자', '투자', False)])
        self.assertTrue(any('자회사 자기주식 처분 결정 1건' in h for h in c['held'])); self.assertTrue(any('배당·투자·재편 공시 1건' in h for h in c['held']))


if __name__ == '__main__':
    unittest.main()
