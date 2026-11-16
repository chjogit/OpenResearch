"""v0.19: 기대 부채 지수(EDI, N17). 원칙을 시험으로 고정한다.

- 그때 알 수 있던 분기만 (분기 말 + 45일)
- V가 0 이하가 되는 경우는 0으로 채우지 않고 보류
- 결과 문장에 적정주가·목표주가·매수·매도 판단을 만들지 않는다
- 세 가지 V를 나란히, 가정은 모두 문장에 드러낸다
"""
import json, math, os, tempfile, unittest
from mrn import market, edi as E
from mrn import nodes as N
from mrn.easy import plan, CARD, card_status, answer
from mrn.engine import Engine
from mrn.store import Store
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order
from tests.test_universe import make_v3, _w, _h, CUT

CO = '005930'
SHARES = 10


def build(root, ni_q=25.0, late_ni=9999.0):
    d = make_v3(root, days=370)
    mp = os.path.join(d, 'manifest.json')
    with open(mp, encoding='utf-8') as fh:
        man = json.load(fh)
    T = man['tables']
    # 가격: 시가총액 = 종가 × 10주
    f = T['price_daily']['parts'][CO]['file']
    with open(os.path.join(d, f), encoding='utf-8') as fh:
        rows = [json.loads(l) for l in fh]
    for r in rows:
        r['market_cap'] = str(int(r['close']) * SHARES)
    h, n = _w(os.path.join(d, f), rows)
    T['price_daily']['parts'][CO].update({'sha256': h, 'rows': n})
    # 분기: 자본 1000, 분기 순이익 ni_q (ROE = 4·ni_q/1000). 2026-09-30 분기는 기준시점에 아직 공개 전 → 쓰면 안 됨
    q = []
    for y in (2024, 2025, 2026):
        for m in (3, 6, 9, 12):
            end = f'{y}-{m:02d}-{30 if m in (6, 9) else 31}'
            if end > '2026-09-30':
                break
            ni = late_ni if end == '2026-09-30' else ni_q
            q += [{'ticker': CO, 'period_end': end, 'fiscal_year': y, 'fiscal_q': m // 3, 'metric': 'equity', 'amount': '1000', 'currency': 'KRW', 'source': 'dart'},
                  {'ticker': CO, 'period_end': end, 'fiscal_year': y, 'fiscal_q': m // 3, 'metric': 'net_income', 'amount': str(ni), 'currency': 'KRW', 'source': 'dart'},
                  {'ticker': CO, 'period_end': end, 'fiscal_year': y, 'fiscal_q': m // 3, 'metric': 'operating_income', 'amount': str(ni * 1.25), 'currency': 'KRW', 'source': 'dart'}]
    h, n = _w(os.path.join(d, 'financial_quarter.jsonl'), q)
    T['financial_quarter'] = {'file': 'financial_quarter.jsonl', 'rows': n, 'sha256': h, 'source_grade': 'test', 'query': 't', 'note': ''}
    ff = [{'ticker': CO, 'fiscal_year': 2025, 'report_code': '11011', 'fs_div': 'CFS', 'sj_div': 'IS', 'account_id': 'ifrs-full_Revenue', 'account_nm': '매출액',
           'amount': '400', 'currency': 'KRW', 'rcept_no': '20260310000001', 'period_end': '2025-12-31'}]
    h, n = _w(os.path.join(d, 'financial_fact', CO + '.jsonl'), ff)
    T['financial_fact'] = {'partitioned': True, 'parts': {CO: {'file': f'financial_fact/{CO}.jsonl', 'rows': n, 'sha256': h}}, 'rows': n, 'source_grade': 'test', 'query': 't', 'note': ''}
    with open(mp, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(man))
    with open(os.path.join(d, 'manifest.sha256'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(_h(mp) + '  manifest.json\n')
    return rows


class Base(unittest.TestCase):
    ni_q = 25.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_NEON_DIR'] = self.tmp.name
        market._UNI.clear()
        self.prices = build(self.tmp.name, self.ni_q)
        self.store = Store(os.path.join(self.tmp.name, 'db'))

    def tearDown(self):
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        market._UNI.clear()
        self.tmp.cleanup()

    def run_card(self, **cfg):
        doc = plan('edi', CO, CUT)
        for n in doc['nodes']:
            if n['type'] == 'N17':
                n['config'].update(cfg)
        w = WorkflowDoc.model_validate(doc)
        self.assertEqual(blocking(validate(w, N.check_assumptions)), [])
        rid = Engine(self.store).start('o', w.model_dump(), topo_order(w), background=False)
        run = self.store.get_run('o', rid)
        n17 = next(n for n in run['nodes'] if n['node_id'] == 'n17')
        p = self.store.get_packet(n17['output_packet'])['payload'] if n17['output_packet'] else None
        return n17['status'], p, n17['reason'], run


class Formula(unittest.TestCase):
    def test_edi_is_years_of_growth(self):
        self.assertAlmostEqual(E.edi(1.08 ** 5 * 100, 100, 0.08), 5.0)
        self.assertAlmostEqual(E.edi(100, 100, 0.08), 0.0)
        self.assertLess(E.edi(90, 100, 0.08), 0)

    def test_rim_out_of_range_is_none_not_zero(self):
        self.assertIsNone(E.value(1000, 0.02, 0.09, 0.02))
        self.assertIsNone(E.value(1000, -0.1, 0.09, 0.02))
        self.assertIsNone(E.edi(100, None, 0.08))

    def test_required_roe_makes_v_equal_price(self):
        B, sh, r, g = 1000.0, 10.0, 0.09, 0.02
        roe = E.required_roe(150.0, sh, B, r, g)
        self.assertAlmostEqual(E.value(B, roe, r, g) / sh, 150.0)

    def test_repayment_split(self):
        pts = [{'date': '2026-01-01', 'P': 300.0, 'V_norm': 100.0, 'EDI_norm': E.edi(300, 100, 0.08)},
               {'date': '2026-06-01', 'P': 200.0, 'V_norm': 200.0, 'EDI_norm': 0.0}]
        rp = E.repayment(pts)
        dP, dV = math.log(200 / 300), math.log(200 / 100)
        self.assertAlmostEqual(rp['share_V'], dV / (dV - dP))
        self.assertAlmostEqual(rp['share_V'] + rp['share_P'], 1.0)
        self.assertGreater(rp['share_V'], rp['share_P'])

    def test_point_in_time_lag(self):
        qt = E.quarter_table([{'period_end': e, 'metric': m, 'amount': '10' if m == 'net_income' else '100'}
                              for e in ('2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31', '2026-03-31') for m in ('equity', 'net_income')])
        self.assertIsNone(E.fundamentals_at(qt, '2026-02-13'))                         # 2025-12-31 분기는 2/14부터
        self.assertEqual(E.fundamentals_at(qt, '2026-02-14')['end'], '2025-12-31')
        self.assertEqual(E.fundamentals_at(qt, '2026-05-14')['end'], '2025-12-31')
        self.assertEqual(E.fundamentals_at(qt, '2026-05-15')['end'], '2026-03-31')


class Node(Base):
    def test_values_and_point_in_time(self):
        st, p, why, _ = self.run_card()
        self.assertIn(st, ('succeeded', 'partial'), why)
        last = p['series'][-1]
        self.assertEqual(last['basis_q'], '2026-06-30')                              # 9월 분기(순이익 9999)는 아직 공개 전
        roe = 0.1                                                                     # 25 × 4 / 1000
        V = 1000 * (roe - 0.02) / (0.09 - 0.02) / SHARES
        P = float(p['series'][-1]['P'])
        self.assertAlmostEqual(last['V_norm'], round(V, 4), places=3)
        self.assertAlmostEqual(last['EDI_norm'], round(math.log(P / V) / math.log(1.08), 4), places=3)
        self.assertAlmostEqual(last['V_book'], 100.0, places=3)
        names = [f['name'] for f in p['findings']]
        for _, lab in E.METHODS:
            self.assertIn(f'주가가 실적보다 앞선 햇수 — {lab}', names)                          # 세 가지 V를 나란히

    def test_no_target_price_or_advice_in_claims(self):
        st, p, why, run = self.run_card()
        for f in p['findings']:
            for w in ('목표주가', '적정주가', '매수', '매도', '저평가', '고평가'):
                self.assertNotIn(w, f['claim'], f['name'])
        self.assertIn('적정주가·목표주가', p['notice'])
        self.assertTrue(any('목표주가' in h and '않습니다' in h for h in p['held']))
        a = answer(run, self.store.get_packet)
        self.assertTrue(any('목표주가' in x for x in a['limits']))               # 「일부러 하지 않는 것」으로 분류

    def test_assumptions_are_visible_and_orange(self):
        st, p, why, _ = self.run_card(cost_of_equity='10', long_growth='1')
        e = next(f for f in p['findings'] if f['name'].startswith('주가가 실적보다 앞선 햇수 — 정규화'))
        self.assertEqual(e['kind'], 'assumption_illustrative')
        self.assertIn('r 10%', e['formula']); self.assertIn('장기성장 1%', e['formula'])
        self.assertEqual(p['assumptions']['cost_of_equity'], 0.1)

    def test_bad_config_held(self):
        st, p, why, _ = self.run_card(cost_of_equity='3', long_growth='4')
        self.assertEqual(st, 'held')
        st, p, why, _ = self.run_card(extra_shares='-5')
        self.assertEqual(st, 'held')

    def test_extra_shares_lower_v(self):
        _, a, _, _ = self.run_card()
        _, b, _, _ = self.run_card(extra_shares='10')
        self.assertAlmostEqual(b['series'][-1]['V_book'], a['series'][-1]['V_book'] / 2, places=3)
        self.assertFalse(any('보통주 외 주식' in h for h in b['held']))

    def test_card(self):
        self.assertIn('edi', CARD)
        ok, why = card_status(CARD['edi'], '042700', {'price_fsc': {'n': 5}, 'fin_annual': {'n': 0}})
        self.assertFalse(ok)
        self.assertIn('연간 재무', why)


class Unstable(unittest.TestCase):
    def test_near_growth_roe_excluded_from_peak(self):
        pts = [{'date': '2026-01-01', 'P': 300.0, 'V_norm': 1.0, 'EDI_norm': 70.0, 'unstable_norm': True},
               {'date': '2026-03-01', 'P': 300.0, 'V_norm': 100.0, 'EDI_norm': E.edi(300, 100, 0.08), 'unstable_norm': False},
               {'date': '2026-06-01', 'P': 200.0, 'V_norm': 200.0, 'EDI_norm': 0.0, 'unstable_norm': False}]
        rp = E.repayment(pts)
        self.assertEqual(rp['peak']['date'], '2026-03-01')


class LowRoe(Base):
    ni_q = 4.0                                                                        # ROE 1.6% < 장기성장 2%

    def test_held_not_zero(self):
        st, p, why, _ = self.run_card()
        names = [f['name'] for f in p['findings']]
        self.assertNotIn('주가가 실적보다 앞선 햇수 — 정규화 RIM (최근 3년 평균 ROE)', names)
        self.assertIn('주가가 실적보다 앞선 햇수 — 장부가 (순자산)', names)
        self.assertTrue(any('보류' in h for h in p['held']))
        self.assertIsNone(p['series'][-1]['V_norm'])


if __name__ == '__main__':
    unittest.main()


# ================================================================ v0.20 국면 판정 (C)
def _ff(fy, rc, acc, amt, ytd=None, fs='CFS', rcept='20260101000001', sj='IS'):
    return {'fiscal_year': fy, 'report_code': rc, 'account_id': acc, 'amount': str(amt), 'amount_ytd': None if ytd is None else str(ytd),
            'fs_div': fs, 'sj_div': sj, 'rcept_no': rcept}


class Dart(unittest.TestCase):
    def test_q4_is_annual_minus_q3_ytd_and_filed_date(self):
        rows = [_ff(2025, '11014', 'ifrs-full_ProfitLoss', 30, ytd=70, rcept='20251114000001'),
                _ff(2025, '11014', 'ifrs-full_Equity', 500, sj='BS', rcept='20251114000001'),
                _ff(2025, '11011', 'ifrs-full_ProfitLoss', 100, rcept='20260310000001'),
                _ff(2025, '11011', 'ifrs-full_Equity', 520, sj='BS', rcept='20260310000001')]
        q = {x['end']: x for x in E.dart_quarters(rows)}
        self.assertEqual(q['2025-12-31']['ni'], 30.0)                        # 100 − 70
        self.assertEqual(q['2025-12-31']['filed'], '2026-03-10')
        self.assertEqual(q['2025-09-30']['ni'], 30.0)

    def test_same_statement_within_quarter(self):
        rows = [_ff(2025, '11013', 'ifrs-full_ProfitLoss', 10, fs='OFS'), _ff(2025, '11013', 'ifrs-full_Equity', 100, fs='OFS', sj='BS'),
                _ff(2025, '11013', 'ifrs-full_ProfitLoss', 12, fs='CFS')]           # 연결은 자본이 없음 → 별도로 둘 다
        q = E.dart_quarters(rows)[0]
        self.assertEqual((q['fs'], q['ni'], q['equity']), ('OFS', 10.0, 100.0))

    def test_filed_date_is_availability(self):
        qt = [{'end': e, 'equity': 100.0, 'ni': 5.0, 'op': None, 'filed': f}
              for e, f in (('2025-03-31', '2025-05-15'), ('2025-06-30', '2025-08-14'), ('2025-09-30', '2025-11-14'), ('2025-12-31', '2026-03-10'))]
        self.assertIsNone(E.fundamentals_at(qt, '2026-03-09'))
        self.assertEqual(E.fundamentals_at(qt, '2026-03-10')['end'], '2025-12-31')


class Classify(unittest.TestCase):
    g = 0.08

    def test_rules(self):
        c = lambda a, b, e0=5.0: E.classify(a, b, e0, self.g)[0]
        self.assertEqual(c(0.5, 0.1), 'price_ahead')
        self.assertEqual(c(-0.02, 0.5), 'earn_led')
        self.assertEqual(c(-0.5, 0.02), 'price_led')
        self.assertEqual(c(-0.25, 0.25), 'mixed')
        self.assertEqual(c(-0.3, -0.1), 'both_down')
        self.assertEqual(c(0.03, 0.0), 'small')
        self.assertEqual(c(0.10, 0.08), 'in_step')
        self.assertEqual(c(-0.3, 0.1, e0=-1.0), 'deeper')

    def test_threshold_is_one_year(self):
        y = math.log(1.08)
        self.assertEqual(E.classify(0.99 * y, 0, 5, self.g)[0], 'small')
        self.assertEqual(E.classify(1.01 * y, 0, 5, self.g)[0], 'price_ahead')

    def test_driver_same_conclusion_not_split(self):
        self.assertEqual(E.driver('earn_led', 0.9), E.driver('deeper', 0.95))
        self.assertNotEqual(E.driver('earn_led', 0.9), E.driver('price_led', 0.1))

    def test_windows_one_v_change_each_and_open_last(self):
        def pt(d, P, V, key, age=60):
            e = E.edi(P, V, self.g)
            return {'date': d, 'P': P, 'V_norm': V, 'V_ttm': V, 'EDI_norm': e, 'EDI_ttm': e, 'basis_q': key, 'fkey': key, 'age': age,
                    'unstable_norm': False, 'unstable_ttm': False}
        pts = [pt('2026-01-02', 100, 100, 'q1'), pt('2026-02-01', 150, 100, 'q1'), pt('2026-03-10', 150, 110, 'q2'),
               pt('2026-04-01', 160, 110, 'q2'), pt('2026-05-15', 100, 110, 'q3', age=200)]
        W = E.windows(pts, self.g)
        self.assertEqual([w['phase'] for w in W], ['price_ahead', 'held', 'open'])      # 2구간은 끝 재무가 135일 넘음
        self.assertEqual(W[0]['end'], '2026-03-10')


class PhaseNode(Base):
    def test_n18_runs_and_uses_neutral_names(self):
        st, p, why, run = self.run_card()
        n18 = next(n for n in run['nodes'] if n['node_id'] == 'n18')
        self.assertIn(n18['status'], ('succeeded', 'partial'), n18['reason'])
        q = self.store.get_packet(n18['output_packet'])['payload']
        for pl in (p, q):
            for f in pl['findings']:
                for w in ('건강한', '강제', '기대 차입', '저평가', '목표주가', '매수', '매도', '당겨', '기대 부채'):
                    self.assertNotIn(w, f['claim'], f['name'])
                    self.assertNotIn(w, f['name'], f['name'])          # v0.22: 앱 화면은 쉬운 말(「앞서 있나」)만
        self.assertTrue(any('판단을 하지 않습니다' in h for h in q['held']))
        self.assertEqual(q['windows'][-1]['phase'], 'open')


class MarketGate(unittest.TestCase):
    def test_weighted_median(self):
        from mrn.edi_market import _wmedian
        self.assertEqual(_wmedian([(1, 1), (2, 1), (10, 5)]), 10)          # 시가총액이 큰 쪽이 중앙값을 정한다
        self.assertEqual(_wmedian([(1, 1), (2, 1), (3, 1)]), 2)
        self.assertIsNone(_wmedian([(None, 3)]))

    def test_gate_needs_both_halves(self):
        from mrn.edi_market import _gate
        per = [(f'q{i}', -1.0) for i in range(8)] + [(f'r{i}', 1.0) for i in range(4)]   # 앞쪽만 맞고 뒤쪽 절반은 과반 미달
        g = _gate(per, -1)
        self.assertGreaterEqual(g['share'], 2 / 3)
        self.assertFalse(g['pass'])
        self.assertTrue(_gate([(f'q{i}', -1.0) for i in range(8)], -1)['pass'])
        self.assertFalse(_gate([(f'q{i}', -1.0) for i in range(5)], -1)['pass'])          # 6분기 미만은 판단하지 않음

    def test_caveats_are_written(self):
        from mrn.edi_market import CAVEATS
        txt = ' '.join(CAVEATS)
        for w in ('생존 편향', '정정', '우선주', '금융업', '매매 신호가 아닙니다'):
            self.assertIn(w, txt)


class NiOpRatio(unittest.TestCase):
    """v0.22: 증권사 영업이익 전망 → 순이익 환산 비율 (적자 기업 포함)."""
    def test_order(self):
        from mrn import edi as E
        r, b = E.ni_op_ratio({'op_ttm': 100, 'ni_ttm': 80, 'op_w': 300, 'ni_w': 200})
        self.assertEqual((round(r, 2), b.startswith('최근 4분기')), (0.8, True))
        r, b = E.ni_op_ratio({'op_ttm': -50, 'ni_ttm': -70, 'op_w': 300, 'ni_w': 210, 'n_norm': 12})
        self.assertEqual((round(r, 2), b.startswith('최근 12분기')), (0.7, True))
        r, b = E.ni_op_ratio({'op_ttm': -50, 'ni_ttm': -70, 'op_w': -10, 'ni_w': -40})
        self.assertEqual((r, b.startswith('기본 가정')), (E.NI_OP_DEFAULT, True))


class CardWording(unittest.TestCase):
    def test_edi_card_title(self):
        from mrn.easy import CARD
        c = CARD['edi']
        self.assertEqual(c['title'], '주가가 실적보다 몇 년 앞서 있나?')
        self.assertIn('8%', c['sub']); self.assertIn('적정주가 아님', c['sub'])
        for w in ('당겨', '기대 부채'):
            self.assertNotIn(w, c['title'] + c['sub'])
