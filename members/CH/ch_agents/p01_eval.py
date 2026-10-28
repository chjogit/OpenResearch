"""P01 비교 실험 E02: 거시 변수의 추가 가치 (P01 문서 10.2·14·15장). 오프라인 연구용, 서비스 답변에 쓰지 않음.

질문: 재무 전용 규제 회귀(B2)에 공개된 거시 변화(M1: 원/달러·국고채 3년 변화와 수출 비중 상호작용)를 넣으면
다음 분기 매출 예측 오차가 줄어드는가.

설계 (사전 고정)
- 정답: 단독분기 매출의 전년 동기 대비 로그 성장 y = log(Y_q / Y_{q-4}). 매출 예측 = Y_{q-4} × exp(ŷ).
- 예측 시점(origin): 직전 분기 q-1 이 공시된 날(분기 45일, 4분기 90일). 그때 공시된 분기·거시만 입력.
- B0: ŷ=0 (전년 동기 유지). B2: [상수, 직전 분기 전년비 로그 성장]. M1: B2 + [원/달러 전년비 변화(%), 국고채 3년
  전년비 변화(%p), 원/달러 변화 × 수출 비중]. 거시는 origin 까지 공개된 일별 관측의 q-1 분기말 값과 q-5 분기말 값.
- 학습: origin 마다 그때까지 실제가 공시된 표본만으로 릿지(λ=1, 표준화) 재적합. 학습 표본 100개·3개 분기 미만이면 그 origin 은 평가 제외.
- 지표: 기업 균등 상대 MAE |Ŷ/Y−1|. M1 vs B2 차이는 목표 분기 단위 블록 부트스트랩(같은 분기 기업들은 같은 거시 충격을 공유).
- 채택 기준(문서 15.2 제안): M1 이 B2 대비 3% 이상 개선이고 차이 구간이 악화를 배제할 때만 '거시 추가 가치 있음'.
한계: 분기 이력이 약 10개뿐이라 평가 가능한 목표 분기가 몇 개 안 됨 → 대부분 '개선 미확정'. 사후 정정값(빈티지 없음) 기준 D1.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, timedelta

LAMBDA = 1.0
MIN_TRAIN, MIN_TRAIN_PERIODS = 100, 3
BOOT = 2000

DATA_SQL = """
SELECT json_build_object(
  'panel', (SELECT json_agg(json_build_object('c', company_id, 'pe', period_end, 'fq', fiscal_q, 'v', amount)
                             ORDER BY company_id, period_end)
            FROM core.financial_quarter WHERE metric = 'revenue' AND amount > 0 AND period_end <= %(as_of)s::date),
  'macro', (SELECT json_object_agg(series_id, obs) FROM (
              SELECT series_id, json_agg(json_build_array(obs_date, value) ORDER BY obs_date) AS obs
              FROM core.macro_obs WHERE series_id IN ('ECOS_USDKRW', 'ECOS_KTB3Y') AND obs_date <= %(as_of)s::date
              GROUP BY series_id) m),
  'export', (SELECT json_object_agg(company_id, v) FROM (
               SELECT DISTINCT ON (company_id) company_id, value AS v FROM core.report_exposure
               WHERE metric = 'export_share' AND value IS NOT NULL ORDER BY company_id, fiscal_year DESC) e)
) AS bundle
"""


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def avail(pe, fq) -> date:
    return _d(pe) + timedelta(days=90 if int(fq) == 4 else 45)


def quarter_key(pe) -> str:
    """가장 가까운 달력 분기말로 묶은 이름 (예: 2025-09-28·2025-10-03 → 2025Q3). 52/53주 회계연도 해외 기업용."""
    d = _d(pe)
    best = None
    for y in (d.year - 1, d.year, d.year + 1):
        for q, (m, dd) in enumerate(((3, 31), (6, 30), (9, 30), (12, 31)), start=1):
            gap = abs((date(y, m, dd) - d).days)
            if best is None or gap < best[0]:
                best = (gap, f"{y}Q{q}")
    return best[1]


def _value_at(series: list, day: date):
    """day 이전(포함) 마지막 관측 값. 일별 자료라 공표 지연 0일 (vintage.RULES 와 같음)."""
    last = None
    for d, v in series:
        if _d(d) > day:
            break
        last = float(v)
    return last


def samples(panel: list[dict], macro: dict, export: dict) -> list[dict]:
    by = defaultdict(list)
    for r in panel or []:
        by[r["c"]].append(r)
    fx, rt = macro.get("ECOS_USDKRW") or [], macro.get("ECOS_KTB3Y") or []
    out = []
    for c, hist in by.items():
        hist.sort(key=lambda r: str(r["pe"]))
        for i in range(5, len(hist)):
            chain = hist[i - 5:i + 1]
            if not all(80 <= (_d(b["pe"]) - _d(a["pe"])).days <= 100 for a, b in zip(chain, chain[1:])):
                continue
            y4, y1, y5, y = (float(hist[i - 4]["v"]), float(hist[i - 1]["v"]), float(hist[i - 5]["v"]),
                             float(hist[i]["v"]))
            origin = avail(hist[i - 1]["pe"], hist[i - 1]["fq"])
            e1, e5 = _d(hist[i - 1]["pe"]), _d(hist[i - 5]["pe"])
            f1, f5, r1, r5 = _value_at(fx, e1), _value_at(fx, e5), _value_at(rt, e1), _value_at(rt, e5)
            if None in (f1, f5, r1, r5):
                continue
            dfx = (f1 / f5 - 1) * 100
            exp_share = float(export.get(str(c), export.get(c, 0)) or 0) / 100
            out.append({"c": c, "target": str(hist[i]["pe"])[:10], "tq": quarter_key(hist[i]["pe"]),
                        "origin": origin.isoformat(),
                        "known": avail(hist[i]["pe"], hist[i]["fq"]).isoformat(),
                        "y": math.log(y / y4), "base": y4, "actual": y,
                        "x_b2": [math.log(y1 / y5)], "x_m1": [math.log(y1 / y5), dfx, r1 - r5, dfx * exp_share]})
    return out


def ridge_fit(X: list[list[float]], y: list[float], lam: float = LAMBDA):
    """표준화 + 절편 무벌점 릿지. 작은 차원이라 가우스 소거로 풉니다."""
    k = len(X[0])
    mu = [sum(r[j] for r in X) / len(X) for j in range(k)]
    sd = [max((sum((r[j] - mu[j]) ** 2 for r in X) / len(X)) ** 0.5, 1e-12) for j in range(k)]
    Z = [[(r[j] - mu[j]) / sd[j] for j in range(k)] for r in X]
    ym = sum(y) / len(y)
    A = [[sum(z[a] * z[b] for z in Z) + (lam if a == b else 0) for b in range(k)] for a in range(k)]
    bvec = [sum(z[a] * (t - ym) for z, t in zip(Z, y)) for a in range(k)]
    w = _solve(A, bvec)
    return lambda x: ym + sum(w[j] * (x[j] - mu[j]) / sd[j] for j in range(k))


def _solve(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(n):
            if r != i and M[i][i]:
                f = M[r][i] / M[i][i]
                M[r] = [a - f * c for a, c in zip(M[r], M[i])]
    return [M[i][n] / M[i][i] if M[i][i] else 0.0 for i in range(n)]


def run(panel, macro, export, as_of: str, seed: int = 7) -> dict:
    S = samples(panel, macro, export)
    preds = []
    for origin in sorted({s["origin"] for s in S}):
        test = [s for s in S if s["origin"] == origin and s["known"] <= as_of]
        train = [s for s in S if s["known"] <= origin]
        if not test or len(train) < MIN_TRAIN or len({s["tq"] for s in train}) < MIN_TRAIN_PERIODS:
            continue
        fb2 = ridge_fit([s["x_b2"] for s in train], [s["y"] for s in train])
        fm1 = ridge_fit([s["x_m1"] for s in train], [s["y"] for s in train])
        for s in test:
            preds.append({**s, "B0": s["base"], "B2": s["base"] * math.exp(fb2(s["x_b2"])),
                          "M1": s["base"] * math.exp(fm1(s["x_m1"])), "n_train": len(train)})
    out = {"n_samples": len(S), "n_eval": len(preds), "targets": sorted({p["tq"] for p in preds}),
           "companies": len({p["c"] for p in preds})}
    if not preds:
        out["verdict"] = "평가 불가: 학습 가능한 origin 없음 (분기 이력 부족)"
        return out
    for m in ("B0", "B2", "M1"):
        out[f"rel_mae_{m}"] = equal_weight_mae(preds, m)
    out["m1_vs_b2_pct"] = (1 - out["rel_mae_M1"] / out["rel_mae_B2"]) * 100 if out["rel_mae_B2"] else None
    lo, hi = block_bootstrap(preds, "M1", "B2", seed)
    out["m1_minus_b2_ci90"] = [lo, hi]
    ok = out["m1_vs_b2_pct"] is not None and out["m1_vs_b2_pct"] >= 3 and hi is not None and hi < 0
    out["verdict"] = ("거시 추가 가치 있음 (사전 기준 충족)" if ok else
                      "개선 미확정 → '거시 영향 예측 개선'을 주장하지 않음 (문서 15.2-3)")
    out["note"] = (f"목표 분기 {len(out['targets'])}개뿐이라 독립 시간축이 짧음. 사후 정정값 기준(D1). "
                   "릿지 계수는 인과효과가 아님")
    return out


def equal_weight_mae(preds, m) -> float:
    per = defaultdict(list)
    for p in preds:
        per[p["c"]].append(abs(p[m] / p["actual"] - 1))
    return sum(sum(v) / len(v) for v in per.values()) / len(per) * 100


def block_bootstrap(preds, a, b, seed=7):
    """목표 분기 단위로 다시 뽑아 (a 오차 − b 오차) 평균의 90% 구간 (%p)."""
    blocks = defaultdict(list)
    for p in preds:
        blocks[p["tq"]].append(abs(p[a] / p["actual"] - 1) - abs(p[b] / p["actual"] - 1))
    keys = sorted(blocks)
    if len(keys) < 2:
        return None, None
    rng = random.Random(seed)
    stats = []
    for _ in range(BOOT):
        xs = [x for k in (rng.choice(keys) for _ in keys) for x in blocks[k]]
        stats.append(sum(xs) / len(xs) * 100)
    stats.sort()
    return stats[int(0.05 * BOOT)], stats[int(0.95 * BOOT) - 1]


def fetch_and_run(as_of: str) -> dict:
    from . import db

    b = db.bundle(DATA_SQL, {"as_of": as_of})
    return run(b.get("panel"), b.get("macro") or {}, b.get("export") or {}, as_of)
