"""거시 입력의 통계적 이상 점검 (P01 기준 문서 13장, 기능 P01-F08 의 1단계: 규칙 기준선).

'최근 공개된 거시 변화가 과거 정상 범위를 벗어났는가' 만 알립니다. 경제위기·손실 확률로 해석하지 않습니다.

- 검사: 최근 5개 관측의 변화(환율은 %, 금리는 %p)를 과거 창(직전 250개 관측, 최근 5개 제외)의 같은 길이 변화
  분포의 중앙값·MAD 로 표준화한 robust z. |z| ≥ 3.5 이면 '통계적 이상'.
- 정상 범위는 기준일 이전 관측으로만 추정합니다 (미래 포함 금지). MAD 가 0 이거나 이력이 짧으면 보류.
- 같은 계열의 연속 경보는 한 건으로 봅니다 (가장 최근 값만 판정).
"""
from __future__ import annotations

from .facts import Facts, median

POLICY_VERSION = "p01-anomaly-rule-v1"
WINDOW = 250
STEP = 5
THRESHOLD = 3.5
MIN_HISTORY = 120
# series_id: (이름, 변화 방식)
CHECKS = {
    "ECOS_USDKRW": ("원/달러 환율", "pct"),
    "ECOS_KTB3Y": ("국고채 3년 금리", "pp"),
    "DGS10": ("미국 10년 국채금리", "pp"),
}


def _chg(a: float, b: float, how: str) -> float | None:
    if how == "pct":
        return (b / a - 1) * 100 if a else None
    return b - a


def robust_z(points: list[tuple[str, float]], how: str) -> dict | None:
    """마지막 STEP 개 관측 변화의 robust z. 이력이 부족하거나 MAD=0 이면 None 과 사유."""
    vals = [v for _, v in points]
    if len(vals) < MIN_HISTORY + STEP:
        return {"held": f"관측 {len(vals)}개, 최소 {MIN_HISTORY + STEP}개 필요"}
    now = _chg(vals[-1 - STEP], vals[-1], how)
    hist_vals = vals[-(WINDOW + 2 * STEP):-STEP]
    past = [c for i in range(STEP, len(hist_vals)) if (c := _chg(hist_vals[i - STEP], hist_vals[i], how)) is not None]
    med = median(past)
    mad = median([abs(x - med) for x in past]) if med is not None else None
    if now is None or not mad:
        return {"held": "MAD 0 또는 변화 계산 불가"}
    return {"change": now, "z": (now - med) / (1.4826 * mad), "n": len(past), "from": points[-1 - STEP][0],
            "to": points[-1][0]}


def check(f: Facts, series: dict[str, list[tuple[str, float]]], group: str = "거시 이상 점검") -> list[dict]:
    out = []
    for sid, (name, how) in CHECKS.items():
        pts = series.get(sid) or []
        r = robust_z(pts, how)
        if r is None or "held" in r:
            f.gap(f"{name} 이상 점검", (r or {}).get("held", "시계열 없음"))
            continue
        k = f.add(f"{name} 최근 {STEP}개 관측 변화의 robust z", r["z"], "coef", r["to"], f"core.macro_obs {sid}",
                  kind="calc", group=group,
                  note=f"과거 {r['n']}개 같은 길이 변화의 중앙값·MAD 기준, {POLICY_VERSION}. 위기 확률 아님")
        state = "abnormal" if abs(r["z"]) >= THRESHOLD else "normal"
        if k and state == "abnormal":
            f.flag(f"거시 이상: {name} 최근 변화가 과거 정상 범위 밖 ({{{k}}}). 예측·노출 해석 전 자료와 사건을 확인")
        out.append({"series": sid, "name": name, "state": state, "key": k, **r})
    return out
