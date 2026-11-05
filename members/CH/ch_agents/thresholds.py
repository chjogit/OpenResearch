"""검사가 '키 밖 숫자'로 막지 않을 판단 기준값(#63). 코드 상수에서 모은다(손으로 쓴 목록 아님).

장부 값처럼 보이는 숫자(기준값과 다른 값, 예: '1.3배')는 계속 막힌다. 기준값은 값이 아니라 '이 선을 넘으면'이라는 규칙이다.
- 거래대금 배율: 비교 기준 1배(REFERENCE_RATIO), 급증·급감 기준(TV_JUMP 와 그 역수)
- 전망 규칙(outlook.RULES): 방향 신호 기준 % · %p
- 가격 변동 이상 기준(facts.MAX_DAILY_MOVE)
창 길이(5일·20일·60일)는 단위 '일' 이 숫자 점검 대상이 아니라 따로 허용 목록이 필요 없다.
"""
from __future__ import annotations

from functools import lru_cache

REFERENCE_RATIO = 1.0      # 배율 비교의 기준선: 1배보다 크면 많음, 작으면 적음


def _forms(value: float, unit: str) -> set[str]:
    """한 기준값이 문장에 나올 수 있는 표기: 1, 1.0, 1.00 → '1배', '1.0배', '1.00배'."""
    v = float(value)
    out = {f"{v:g}{unit}"}
    for digits in (1, 2):
        if round(v, digits) == v:           # 반올림하면 다른 값이 되는 표기(0.25 → 0.2)는 만들지 않음
            out.add(f"{v:.{digits}f}{unit}")
    if v == int(v):
        out.add(f"{int(v)}{unit}")
    return out


@lru_cache(maxsize=1)
def threshold_terms() -> frozenset[str]:
    from . import agent3_sentiment_flow as flow
    from . import facts, outlook

    terms: set[str] = set()
    for r in (REFERENCE_RATIO, flow.TV_JUMP, 1 / flow.TV_JUMP):
        terms |= _forms(r, "배")
    for rules in outlook.RULES.values():
        for rule in rules:
            if rule.get("unit") in ("%", "%p"):
                terms |= _forms(rule["threshold"], rule["unit"])
    terms |= _forms(facts.MAX_DAILY_MOVE * 100, "%")
    return frozenset(terms | {t.lstrip("+-") for t in terms})
