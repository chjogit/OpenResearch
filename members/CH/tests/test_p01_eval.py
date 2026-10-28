"""P01 실험 E02 도구 시험: 합성 패널에서 거시가 정답에 들어 있으면 M1 이 B2 보다 낫고, 없으면 개선 미확정."""
import math
import random

from ch_agents import p01_eval as ev

ENDS = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31", "2024-06-30", "2024-09-30",
        "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"]


def _world(macro_effect: float, seed=1, n=60):
    rng = random.Random(seed)
    fx, rt, d = [], [], __import__("datetime").date(2022, 1, 1)
    lvl, r = 1200.0, 3.0
    while d.isoformat() <= "2026-10-28":
        lvl *= 1 + rng.gauss(0, 0.004)
        r += rng.gauss(0, 0.01)
        fx.append([d.isoformat(), lvl])
        rt.append([d.isoformat(), r])
        d += __import__("datetime").timedelta(days=1)
    macro = {"ECOS_USDKRW": fx, "ECOS_KTB3Y": rt}
    panel, export = [], {}
    for c in range(1, n + 1):
        ex = rng.uniform(0, 90)
        export[str(c)] = ex
        v = [1e12 * (1 + c / 50)] * 4
        for i in range(4, len(ENDS)):
            e1, e5 = ev._d(ENDS[i - 1]), ev._d(ENDS[i - 5]) if i >= 5 else ev._d(ENDS[0])
            dfx = (ev._value_at(fx, e1) / ev._value_at(fx, e5) - 1) * 100
            g = 0.03 + macro_effect * dfx * ex / 100 / 100 + rng.gauss(0, 0.03)
            v.append(v[i - 4] * math.exp(g))
        for i, pe in enumerate(ENDS):
            panel.append({"c": c, "pe": pe, "fq": i % 4 + 1, "v": v[i]})
    return panel, macro, export


def test_e02_detects_planted_macro_effect():
    panel, macro, export = _world(macro_effect=3.0)
    out = ev.run(panel, macro, export, "2026-10-28")
    assert out["n_eval"] > 0 and out["rel_mae_M1"] < out["rel_mae_B2"]


def test_e02_no_macro_effect_is_not_claimed():
    panel, macro, export = _world(macro_effect=0.0, seed=2)
    out = ev.run(panel, macro, export, "2026-10-28")
    assert out["verdict"].startswith("개선 미확정")


def test_e02_uses_only_published_training_rows():
    panel, macro, export = _world(macro_effect=0.0)
    S = ev.samples(panel, macro, export)
    for s in S:
        assert s["origin"] < s["known"]                  # 예측 시점에는 그 목표의 실제를 모름


def test_quarter_key_groups_52_53_week_ends():
    assert ev.quarter_key("2025-09-28") == ev.quarter_key("2025-10-03") == ev.quarter_key("2025-09-30") == "2025Q3"
    assert ev.quarter_key("2025-12-27") == "2025Q4" and ev.quarter_key("2026-02-01") == "2025Q4"  # 1월 결산 4분기
