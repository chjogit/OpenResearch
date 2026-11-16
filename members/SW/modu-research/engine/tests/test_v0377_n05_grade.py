"""v0.37.7: N05 노출 등급(철현 N05 이식) — 철현 예시 숫자 재현 · 기준값 경계 · 금융업·외화 재무·적자 보류 · 판단 표현 없음."""
import json, unittest
from mrn import nodes as N
from mrn.easy import plan


def fp(**kw):
    base = {'company': '005930', 'name': '삼성전자', 'krx_sector': '전기·전자',
            'exposures': [
                {'fiscal_year': 2025, 'metric': 'fx_sens', 'currency': 'USD', 'value': '435059000000', 'change_pct': '5', 'basis': '당기손익', 'rcept_no': '20260310002820'},
                {'fiscal_year': 2025, 'metric': 'fx_sens', 'currency': 'EUR', 'value': '62325000000', 'change_pct': '5', 'basis': '당기손익', 'rcept_no': '20260310002820'},
                {'fiscal_year': 2025, 'metric': 'export_share', 'currency': 'ALL', 'value': '90.9024840049907', 'change_pct': None, 'basis': None, 'rcept_no': '20260310002820'},
                {'fiscal_year': 2024, 'metric': 'fx_sens', 'currency': 'USD', 'value': '999999000000', 'change_pct': '5', 'basis': '당기손익', 'rcept_no': '1'}],
            'facts': [{'year': 2025, 'metric': 'operatingProfit', 'amount': '43601051000000', 'currency': 'KRW'},
                      {'year': 2025, 'metric': 'liabilities', 'amount': '130621773000000', 'currency': 'KRW'},
                      {'year': 2025, 'metric': 'equity', 'amount': '436320337000000', 'currency': 'KRW'}],
            'quarter_actuals': [{'fiscal_year': y, 'quarter': q, 'metric': 'operatingProfit', 'value_mn': v} for y, q, v in
                                ((2025, 3, '12166062'), (2025, 4, '20073660'), (2026, 1, '57232797'), (2026, 2, '89492412'))]}
    base.update(kw); return base


def by(F):
    return {f['name']: f for f in F}


class Grade(unittest.TestCase):
    def test_reproduces_submission_example(self):
        F, H, T = N._exposure_grade(fp())
        d = by(F)
        ref = next(r for r in T['rows'] if r[0] == '환율 · 참고'); self.assertIn('2.28%', ref[1]); self.assertIn('등급에 쓰지 않음', ref[3])   # 철현 예시 2.28% (USD+EUR, 통화 합 가정) — 표에만
        self.assertAlmostEqual(d['환율 10% 변동 시 손익 ÷ 영업이익 (USD, 2025년)']['value'], 1.9956, places=3)   # 엔진 기준(USD만)
        self.assertIn('「낮음」', d['환율 노출 (규칙 분류)']['claim'])
        self.assertIn('「높음」', d['수출·경기 노출 (규칙 분류)']['claim']); self.assertIn('90.90%', d['수출·경기 노출 (규칙 분류)']['claim'])
        self.assertAlmostEqual(d['부채비율 (2025년 말)']['value'], 29.9371, places=3); self.assertIn('낮춰 볼 조건', d['부채비율 (2025년 말)']['claim'])
        self.assertIn('2025년 3분기~2026년 2분기', d['같은 값 ÷ 최근 4개 분기 영업이익 (USD)']['claim'])
        self.assertNotIn('estimate', {f['kind'] for f in F})
        self.assertEqual([r[0] for r in T['rows']], ['환율', '환율 · 참고', '수출·경기', '금리'])
        self.assertIn('rcpNo=20260310002820', d['환율 10% 변동 시 손익 ÷ 영업이익 (USD, 2025년)']['source']['url'])
        txt = json.dumps(F, ensure_ascii=False)
        for bad in ('위험하다', '안전', '유리', '불리', '매수', '매도', '좋다', '나쁘다'):
            self.assertNotIn(bad, txt)

    def test_boundaries(self):
        self.assertEqual([N._grade3(x, 10, 3) for x in (10.0, 9.99, 3.0, 2.99)], ['높음', '중간', '중간', '낮음'])
        self.assertEqual([N._grade3(x, 60, 30) for x in (60.0, 59.9, 30.0, 29.9)], ['높음', '중간', '중간', '낮음'])

    def test_held_cases(self):
        F, H, T = N._exposure_grade(fp(krx_sector='기타금융', name='신한지주'))
        self.assertEqual((F, T), ([], None)); self.assertIn('금융업', H[0])
        F, H, T = N._exposure_grade(fp(krx_sector='기타금융', name='LG'))                       # 일반 지주사는 금융업이 아님
        self.assertTrue(F)
        F, H, T = N._exposure_grade(fp(facts=[{'year': 2025, 'metric': 'operatingProfit', 'amount': '500000000', 'currency': 'USD'}]))
        self.assertEqual(F, []); self.assertIn('원화가 아니어서', H[0])
        F, H, _ = N._exposure_grade(fp(facts=[{'year': 2025, 'metric': 'operatingProfit', 'amount': '-1', 'currency': 'KRW'}]))
        self.assertFalse(any(f['name'].startswith('환율') for f in F)); self.assertTrue(any('0 이하' in h for h in H))
        q = fp()['quarter_actuals']; q[1] = {**q[1], 'quarter': 1, 'fiscal_year': 2024}           # 끊긴 분기 → 4개 분기 값 없음
        F, H, _ = N._exposure_grade(fp(quarter_actuals=sorted(q, key=lambda x: (x['fiscal_year'], x['quarter']))))
        self.assertNotIn('같은 값 ÷ 최근 4개 분기 영업이익 (USD)', by(F))
        F, H, T = N._exposure_grade(fp(exposures=[]))
        self.assertEqual((F, T), ([], None))

    def test_macro_card_wires_t11_for_base(self):
        d = plan('macro', '005930', '2026-11-11T13:00:00+09:00')
        self.assertTrue({'t01', 't11', 'n05'} <= {n['id'] for n in d['nodes']})
        self.assertIn(('t11', 'n05'), {(e['from_node'], e['to_node']) for e in d['edges']})
        import mrn.mycards as M
        tpl, probs = M.to_template(d)
        self.assertEqual(probs, [])
        with self.assertRaises(ValueError):                                       # 기준 회사 원문(T01)이 든 카드를 다른 회사에 끼우지 않음
            M.fill(tpl, '005380')
        M.fill(tpl, '000660')


if __name__ == '__main__':
    unittest.main()
