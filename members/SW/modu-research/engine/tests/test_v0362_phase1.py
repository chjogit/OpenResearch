"""v0.36.2: N08 순매수 강도·손바꿈 · N06 내 가정·외삽 금지 · N11 제목 묶음 · 답 카드 held[]·보류 번호·short."""
import json, unittest
from mrn import nodes as N, easy, learn
from tests.test_flow import Base, build, doc
from tests.test_v0361_obs import rewrite_prices

EXP = [{'name': '가', 'fx_struct': {'shock': 5.0, 'impact_mn': 1000.0}, 'rate_struct': {'shock': 1.0, 'impact_mn': -200.0}},
       {'name': '나', 'fx_scenario': '환율 ±10%, USD 세전손익 ±3,000백만원', 'rate_scenario': '읽을 수 없음'}]


class Scenario(unittest.TestCase):
    def test_linear_inside_disclosed_range_with_opposite(self):
        F, H = N._my_scenario('환율 3% 상승, 금리 50bp 인하', EXP)
        got = {f['name']: f for f in F}
        self.assertEqual(got['가 환율 영향 (내 가정이라면)']['value'], 600)            # 1000 × 3/5
        self.assertIn('반대 조건(-3%) → 약 -600백만원', got['가 환율 영향 (내 가정이라면)']['claim'])
        self.assertEqual(got['나 환율 영향 (내 가정이라면)']['value'], 900)            # 3000 × 3/10
        self.assertEqual(got['가 금리 영향 (내 가정이라면)']['value'], 100)            # −200 × (−0.5)/1
        self.assertTrue(any('나 내 가정(금리)' in h and '보류' in h for h in H))

    def test_no_extrapolation_and_units(self):
        F, H = N._my_scenario('환율 8% 상승', EXP)
        self.assertEqual([f['name'] for f in F], ['나 환율 영향 (내 가정이라면)'])       # 가(5%)는 범위 밖, 나(10%)는 안
        self.assertTrue(any(h.startswith('가 내 가정(환율 +8%)') and '충격폭(5%)' in h for h in H))
        F, H = N._my_scenario('금리 1% 인상', EXP)
        self.assertEqual(F, []); self.assertTrue(any('%p 또는 bp' in h for h in H))
        self.assertEqual(N._my_scenario('', EXP), ([], []))
        for h in N._my_scenario('환율 8% 상승, 금리 1% 인상', EXP)[1]:
            self.assertNotIn('하지 않음', h)                                           # 답 카드에서 「모르는 것」으로 보이게

    def test_title_groups(self):
        news = [{'date': '2026-11-01', 'title': '삼성전자 3분기 영업이익 발표'}, {'date': '2026-11-02', 'title': '삼성전자, 3분기 영업이익 발표'},
                {'date': '2026-11-03', 'title': '삼성전자 3분기 영업이익 발표…'}, {'date': '2026-11-03', 'title': '전혀 다른 이야기의 기사 제목'},
                {'date': '2026-09-01', 'title': '삼성전자 3분기 영업이익 발표'}]
        G = N._title_groups(news, '2026-11-05')
        self.assertEqual([(g['first'], g['n']) for g in G], [('2026-11-01', 3)])

    def test_hold_id_and_short(self):
        a = easy.hold_id('005930', 'T06', '공백 1곳'); self.assertRegex(a, r'^H-005930-[0-9a-f]{8}$')
        self.assertEqual(a, easy.hold_id('005930', 'T06', '공백 1곳')); self.assertNotEqual(a, easy.hold_id('000660', 'T06', '공백 1곳'))
        self.assertEqual(set(easy.SHORT), {c['id'] for c in easy.CARDS} | {'attention', 'reaction'})
        self.assertTrue(set(learn.SHORT) <= {t['id'] for t in learn.TASKS})


class Flow(Base):
    def test_n08_strength_and_direction_change(self):
        fnet = [10] * 195 + [-40] * 5                       # 외국인: 직전 20일 +200 → 최근 5일 −200
        d, days = build(self.neon, [100.0] * 200, fnet)
        def fn(rows):
            for r in rows:
                r['trade_value'] = '100000'                 # 하루 거래대금 10만원 → 20일 200만원
            return rows
        rewrite_prices(d, fn)
        run, n = self.run_doc(doc())
        P = self.pay(n['n08']); F = {f['name']: f for f in P['findings']}
        # 외국인 20일 수량 = 15×10 − 5×40 = −50주 × 100원 = −5,000원 → −0.25%
        self.assertEqual(F['20거래일 순매수 강도 (금액은 근사)']['value']['외국인'], -0.25)
        self.assertIn('어림', F['20거래일 순매수 강도 (금액은 근사)']['formula'])
        self.assertEqual(F['외국인 매매 방향 바뀜']['claim'], '그 직전 20거래일 +200주 → 최근 5거래일 -200주')
        self.assertIn('외국인 20일 누적 방향 전환 (최근 120거래일)', F)                 # 기존 항목 유지
        a = easy.answer(run, self.store.get_packet)
        self.assertIn('held', a); self.assertTrue(all(u['id'].startswith('H-') for u in a['unknown']))
        for h in a['held']:
            self.assertEqual(set(h), {'id', 'node', 'node_type', 'node_name', 'status', 'code', 'text'})


if __name__ == '__main__':
    unittest.main()
