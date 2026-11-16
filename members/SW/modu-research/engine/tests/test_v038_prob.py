"""v0.38 T2-3 공용 확률 모듈: 시점 규율 · 난수 없음 · 분할 구간 제외 · 보이는 단위 · 실제 사본으로 한 해씩 빼고 맞춰 보기."""
import math, unittest
from datetime import date, timedelta
from mrn import prob as PB


def fake(n_co=120, days=420, seed=7):
    """결정적 가짜 시세: 회사마다 다른 변동성, 공통 시장 요인. 난수는 선형합동식(시험 재현용)."""
    x = seed

    def rnd():
        nonlocal x
        x = (1103515245 * x + 12345) % (2 ** 31)
        u = sum(((1103515245 * (x + k) + 12345) % (2 ** 31)) / 2 ** 31 for k in range(12)) - 6       # 대략 표준정규
        return u
    d0 = date(2022, 1, 3); ds = []
    while len(ds) < days:
        if d0.weekday() < 5:
            ds.append(d0.isoformat())
        d0 += timedelta(days=1)
    mk = [0.008 * rnd() for _ in ds]
    out = {}
    for c in range(n_co):
        sg = 0.01 + 0.0002 * c; p = 10000.0; s = []
        for i, d in enumerate(ds):
            p *= math.exp(mk[i] + sg * rnd()); s.append((d, round(p, 2)))
        out[f'{c:06d}'] = s
    return out, ds


class Prob(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S, cls.D = fake()

    def test_sigma_is_market_relative_and_point_in_time(self):
        sg = PB.sigma(self.S, '000000', self.D[200])
        self.assertTrue(0.007 < sg < 0.014, sg)                                  # 회사 고유 변동성 0.01 근처(시장 요인 0.008은 빠짐)
        self.assertEqual(sg, PB.sigma({t: [x for x in s if x[0] <= self.D[200]] for t, s in self.S.items()}, '000000', self.D[200]))   # 기준 날짜 뒤 자료가 있어도 값이 같음
        self.assertIsNone(PB.sigma(self.S, '000000', self.D[30]))                # 60거래일이 안 됨
        self.assertIsNone(PB.sigma(self.S, '999999', self.D[200]))

    def test_split_jump_excluded(self):
        S = dict(self.S); s = list(S['000001']); s[180] = (s[180][0], s[180][1] / 5); S['000001'] = s[:181] + [(d, p / 5) for d, p in s[181:]]   # 5대1 분할
        self.assertIsNone(PB.sigma(S, '000001', self.D[200]))
        self.assertIsNotNone(PB.sigma(S, '000001', self.D[300]))                 # 분할 뒤 60거래일이 지나면 다시 구함
        W = PB.windows(S, self.D[-1], 20)
        self.assertFalse(any(t == '000001' and self.D[160] <= d <= self.D[239] for d, t, _ in W))    # 분할일이 앞 60일이나 뒤 20일에 걸치는 경로는 쓰지 않음
        self.assertTrue(any(t == '000001' and d < self.D[160] for d, t, _ in W) and any(t == '000001' and d > self.D[239] for d, t, _ in W))

    def test_library_deterministic_and_cutoff(self):
        a = PB.library(self.S, self.D[300], 40); b = PB.library(self.S, self.D[300], 40)
        self.assertTrue((a['u'] == b['u']).all()); self.assertEqual(a['n'], PB.N_PATHS); self.assertLessEqual(a['to'], self.D[300 - 40])
        self.assertIsNone(PB.library(self.S, self.D[70], 40))                    # 경로가 500개가 안 되면 만들지 않음

    def test_paths_and_market_scenario(self):
        lib = PB.library(self.S, self.D[400], 60)
        sg = PB.sigma(self.S, '000010', self.D[400])
        flat = PB.paths(lib, sg, 20, 0.0); down = PB.paths(lib, sg, 20, math.log(0.9))
        self.assertEqual(flat.shape, (PB.N_PATHS, 20))
        self.assertTrue(abs(float((down - flat)[:, -1].mean()) - math.log(0.9)) < 1e-9)       # 시장 −10% 시나리오는 모든 경로를 그만큼 내림
        p0 = PB.share(flat[:, -1], lambda v: v <= 0.0); p1 = PB.share(down[:, -1], lambda v: v <= 0.0)
        self.assertTrue(0.35 < p0 < 0.65, p0); self.assertGreater(p1, p0)
        self.assertIsNone(PB.paths(lib, sg, 61)); self.assertIsNone(PB.paths(lib, None, 20)); self.assertIsNone(PB.paths(None, sg, 20))

    def test_shown_units(self):
        self.assertEqual(PB.shown(0.34, 20), '약 30%'); self.assertEqual(PB.shown(0.36, 20), '약 40%')
        self.assertEqual(PB.shown(0.34, 60), '약 40%'); self.assertEqual(PB.shown(0.28, 60), '약 20%')
        self.assertEqual(PB.shown(0.03, 20), '5% 미만'); self.assertEqual(PB.shown(0.97, 20), '95% 넘음')
        self.assertEqual(PB.shown(0.06, 100), '10% 미만'); self.assertEqual(PB.shown(0.95, 100), '90% 넘음')
        self.assertIsNone(PB.shown(0.5, 121)); self.assertIsNone(PB.shown(None, 20))
        self.assertIn('20거래일 뒤 기준 최대 5.2%p', PB.evidence(15)); self.assertIsNone(PB.evidence(200))

    def test_backtest_on_fake_market_is_calibrated(self):                       # 만든 대로 움직이는 가짜 시장에서는 잘 맞아야 한다(계산 경로 검증)
        r = PB.backtest(self.S, horizons=(5, 20), every=6, hmax=20)
        self.assertTrue(r); self.assertLess(max(v['max_err'] for v in r.values()), 8.0, r)


def _real():
    try:
        return PB.series_from_snapshot()
    except Exception:
        return None, None


@unittest.skipUnless(_real()[0] and len(_real()[0]) >= 150, '이 PC에 시세 사본(150개사 이상)이 있을 때만')
class RealSnapshot(unittest.TestCase):
    def test_leave_one_year_out_within_recorded_error(self):                     # 실제 사본으로 다시: 20거래일 종가·기준주가의 오차가 기록한 값(+여유 1.5%p) 안
        S, _ = _real()
        r = PB.backtest(S, horizons=(20,), every=8, hmax=20)
        full = {k: v for k, v in r.items() if v['n'] >= 500}
        self.assertGreaterEqual(len(full), 6)
        worst = max(v['max_err'] for v in full.values())
        self.assertLessEqual(worst, PB.EVIDENCE[20] + 1.5, {k: v['max_err'] for k, v in full.items()})


if __name__ == '__main__':
    unittest.main()
