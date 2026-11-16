"""v0.17 B: 관계 기록 조사(N15)·관계 지도. 안전장치 다섯 가지를 먼저 시험으로 고정한다.

1 최소 표본 · 2 여러 시차 시험 보정 · 3 기간 나눔 재확인 · 4 과거 맞히기 시험 · 5 「인과 아님」 문구(+ 쉬운 화면 별도 관계 지도)
"""
import math, os, random, unittest
from mrn import relations as R
from mrn.easy import plan, answer, CARDS
from mrn.workflow import WorkflowDoc, validate, blocking
from mrn import nodes as N
from tests.test_kit2_events import Base, nd, ed
from tests.test_universe import CUT

REAL = os.environ.get('MODU_NODES_NEON_DIR')      # 장치 시험: 실제 사본(20261107…)이 있으면 실제 값으로도 확인


def months(n, start=(2021, 1)):
    y, m = start
    out = []
    for _ in range(n):
        out.append(f'{y:04d}-{m:02d}')
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def series(ms, vals):
    return dict(zip(ms, vals))


class Safeguards(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)

    def noise(self, n, s=1.0):
        return [self.rng.gauss(0, s) for _ in range(n)]

    # 1) 최소 표본
    def test_too_few_months_is_not_computed(self):
        ms = months(20)
        x = self.noise(20); y = [a + 0.1 * b for a, b in zip(x, self.noise(20))]   # 매우 강한 관계라도
        rec = R.record(series(ms, y), series(ms, x))
        self.assertEqual(rec['grade'], 'too_few')
        self.assertNotIn('r', rec)

    def test_min_months_cannot_be_lowered_in_node(self):
        self.assertEqual(R.MIN_MONTHS, 24)

    # 2) 여러 시차를 시험한 만큼 넓힌 범위로 판정
    def test_adjusted_range_is_wider_and_used(self):
        ms = months(60)
        x = self.noise(60); y = [0.35 * a + b for a, b in zip(x, self.noise(60))]
        rec = R.record(series(ms, y), series(ms, x))
        self.assertEqual(rec['lags_tested'], 4)
        self.assertAlmostEqual(rec['z_adjusted'], 2.50)
        w95 = rec['ci95'][1] - rec['ci95'][0]; wadj = rec['ci_adjusted'][1] - rec['ci_adjusted'][0]
        self.assertGreater(wadj, w95)

    def test_pure_noise_is_indistinct(self):
        hits = 0
        for seed in range(20):
            rng = random.Random(seed)
            ms = months(48)
            rec = R.record(series(ms, [rng.gauss(0, 1) for _ in ms]), series(ms, [rng.gauss(0, 1) for _ in ms]))
            hits += rec['grade'] != 'indistinct'
        self.assertLessEqual(hits, 2)          # 아무 관계 없는 자료에서 「기록 있음」이 거의 나오지 않아야 한다

    # 3) 기간 나눔 재확인
    def test_sign_flip_between_halves_is_unstable(self):
        ms = months(60)
        x = self.noise(60)
        y = [(1.5 if i < 30 else -0.15) * a + 0.4 * b for i, (a, b) in enumerate(zip(x, self.noise(60)))]
        rec = R.record(series(ms, y), series(ms, x), max_lag=0)
        self.assertEqual(rec['grade'], 'unstable', rec['halves'])
        self.assertFalse(rec['halves']['stable'])

    def test_same_month_record(self):
        ms = months(60)
        x = self.noise(60); y = [a + 0.5 * b for a, b in zip(x, self.noise(60))]
        rec = R.record(series(ms, y), series(ms, x))
        self.assertEqual(rec['best_lag'], 0)
        self.assertEqual(rec['grade'], 'same_month')
        self.assertIsNone(rec['oos'])                      # 같은 달은 맞히기 시험 대상이 아님

    # 4) 과거 맞히기 시험 (앞선 시차, 공개 시차 반영)
    def test_lead_relation_passes_backtest(self):
        ms = months(61)
        x = self.noise(61)
        y = [0.0] + [x[i - 1] + 0.4 * e for i, e in zip(range(1, 61), self.noise(60))]      # 1개월 앞선 지표
        rec = R.record(series(ms[1:], y[1:]), series(ms, x))
        self.assertEqual(rec['best_lag'], 1)
        self.assertTrue(rec['known_before'])
        self.assertEqual(rec['grade'], 'lead', rec['oos'])
        self.assertGreaterEqual(rec['oos']['hit'], rec['oos']['baseline'] + R.OOS_MARGIN)

    def test_publication_lag_blocks_lead(self):
        """관세청 수출(다음 달 1일 공개)처럼 공개가 늦으면, 공개 전 시차는 「미리 알 수 있던 값」이 아니다."""
        ms = months(61)
        x = self.noise(61)
        y = [0.0] + [x[i - 1] + 0.4 * e for i, e in zip(range(1, 61), self.noise(60))]
        rec = R.record(series(ms[1:], y[1:]), series(ms, x), pub_lag=2)
        self.assertEqual(rec['best_lag'], 1)
        self.assertFalse(rec['known_before'])
        self.assertIsNone(rec['oos'])
        self.assertNotEqual(rec['grade'], 'lead')

    def test_backtest_uses_only_past_for_direction(self):
        xs = list(range(1, 31)); ys = [v if i < 20 else -v for i, v in enumerate(xs)]
        o = R.oos_hit(xs, ys)
        self.assertEqual(o['train_months'], 20)
        self.assertGreater(o['train_r'], 0)               # 방향은 앞 기간에서만 정함
        self.assertEqual(o['hit'], 0.0)                   # 뒤 기간에 방향이 바뀌면 그대로 실패로 기록

    # 5) 문구
    def test_notice_says_not_causal(self):
        self.assertIn('인과가 아닙니다', R.NOTICE)
        for g, lab in R.GRADE_LABEL.items():
            for w in ('원인', '때문', '매수', '매도', '오를', '내릴', '추천'):
                self.assertNotIn(w, lab, (g, lab))


class Node(Base):
    def test_short_prices_held_with_repair(self):
        r = self.run_doc([nd('t06', 'T06', company='005930', lookback=260), nd('t10', 'T10'), nd('n15', 'N15')],
                         [ed('t06', 'prices', 'n15', 'prices'), ed('t10', 'macro', 'n15', 'macro')])
        st, p, why = r['n15']
        self.assertEqual(st, 'held', why)
        self.assertIn('최소 24개월', why)
        from mrn.repair import suggest
        run = {'doc': {'nodes': [nd('t06', 'T06', company='005930', lookback=260), nd('t10', 'T10'), nd('n15', 'N15')],
                       'edges': [ed('t06', 'prices', 'n15', 'prices'), ed('t10', 'macro', 'n15', 'macro')]},
               'nodes': [{'node_id': 'n15', 'node_type': 'N15', 'status': 'held', 'error_code': 'too_short', 'output_packet': None, 'reason': why}]}
        props = suggest(run, lambda x: None)
        self.assertTrue(any(p['patch'].get('value') == 1300 for p in props))

    def test_min_months_config_cannot_go_below_24(self):
        r = self.run_doc([nd('t06', 'T06', company='005930', lookback=1300), nd('t10', 'T10'), nd('n15', 'N15', min_months=6)],
                         [ed('t06', 'prices', 'n15', 'prices'), ed('t10', 'macro', 'n15', 'macro')])
        self.assertEqual(r['n15'][0], 'held')               # 합성 사본은 17개월 → 6으로 낮춰도 계산하지 않음


class Card(unittest.TestCase):
    def test_card_and_plan(self):
        c = next(c for c in CARDS if c['id'] == 'relations')
        self.assertEqual(c['view'], 'relmap')
        d = WorkflowDoc.model_validate(plan('relations', '042700', CUT))
        self.assertEqual(blocking(validate(d, N.check_assumptions)), [])
        t06 = next(n for n in d.nodes if n.type == 'T06')
        self.assertEqual(t06.config['lookback'], 1300)

    def test_assembler_routes_correlation_question(self):
        from mrn.assembler import assemble
        o = assemble('한미반도체 주가는 환율과 상관관계가 있어?', None, CUT)
        types = [n['type'] for n in o['doc']['nodes']]
        self.assertIn('N15', types)
        t06 = [n for n in o['doc']['nodes'] if n['type'] == 'T06']
        self.assertTrue(t06 and all(n['config']['lookback'] == 1300 for n in t06))


@unittest.skipUnless(REAL and os.path.isdir(os.path.join(REAL, '20261107T005213+0900')), '실제 Neon 사본이 있을 때만')
class Real(unittest.TestCase):
    def test_skhynix_relation_map(self):
        import tempfile
        from mrn.engine import Engine
        from mrn.store import Store
        from mrn.workflow import topo_order
        from mrn import market
        os.environ['MODU_NODES_NEON_DIR'] = REAL
        market._UNI.clear()
        with tempfile.TemporaryDirectory() as tmp:
            st = Store(tmp)
            w = WorkflowDoc.model_validate(plan('relations', '000660', '2026-11-07T09:00:00+09:00'))
            rid = Engine(st).start('o', w.model_dump(), topo_order(w), background=False)
            run = st.get_run('o', rid)
            n15 = next(n for n in run['nodes'] if n['node_type'] == 'N15')
            self.assertEqual(n15['status'], 'succeeded', n15['reason'])
            p = st.get_packet(n15['output_packet'])['payload']
            g = {r['factor']: r for r in p['relations']}
            self.assertEqual(g['^KS11']['grade'], 'same_month')       # 시장과 같은 달에 함께 움직인 기록
            self.assertGreater(g['^KS11']['r'], 0.7)
            self.assertEqual(g['ECOS_USDKRW']['grade'], 'indistinct')  # 「환율 따라 움직인다」는 이 기록으로는 구분되지 않음
            self.assertEqual(p['months']['n'], 60)
            a = answer({**run, 'doc': w.model_dump()}, st.get_packet)
            self.assertEqual(a['view'], 'relmap')
            self.assertIn('인과가 아닙니다', a['relmap']['notice'])
            from mrn.easy import receipt, verify                       # 근거 확인서: 다시 계산해도 같은가
            rc = receipt(run, st.get_packet)

            def rerun(doc):
                w2 = WorkflowDoc.model_validate(doc)
                r2 = st.get_run('o', Engine(st).start('o', w2.model_dump(), topo_order(w2), background=False))
                return {n['node_id']: st.get_packet(n['output_packet'])['header']['payload_digest'] for n in r2['nodes'] if n['output_packet']}
            self.assertTrue(verify(rc, rerun)['ok'])
