"""숫자 장부와 계산 도구.

에이전트가 인용할 수 있는 숫자는 모두 여기 등록됩니다. 값마다 단위·기준일·출처·구분을 붙이고,
LLM 은 `{M1}` 처럼 키만 씁니다. 데이터가 없으면 gap() 으로 '무자료' 사유를 남깁니다.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Iterable
from itertools import pairwise
from typing import Any

KIND_LABEL = {"report": "회사 공시", "obs": "실측", "calc": "계산", "proxy": "대용치", "forecast": "예측(기준선)"}


def fmt(value: float | None, unit: str) -> str:
    """단위별 표기. 값 자체는 바꾸지 않고 보기만 정리합니다."""
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return "무자료"
    v = float(value)
    if unit == "%":
        return f"{v:,.2f}%"
    if unit == "%p":
        return f"{v:+.2f}%p"
    if unit == "%chg":
        return f"{v:+.2f}%"
    if unit == "배":
        return f"{v:,.2f}배"
    if unit in ("KRW", "KRW±"):
        sign = "+" if unit == "KRW±" and v > 0 else ""
        if abs(v) >= 1e12:
            return f"{sign}{v / 1e12:,.2f}조원"
        if abs(v) >= 1e8:
            return f"{sign}{v / 1e8:,.0f}억원"
        return f"{sign}{v:,.0f}원" if abs(v) >= 100 else f"{sign}{v:,.2f}원"  # 주가·평균 가격은 원 단위
    if unit == "USD":
        return f"{v / 1e8:,.2f}억달러" if abs(v) >= 1e8 else f"{v:,.0f}달러"
    if unit == "주":  # 순매수처럼 방향이 있는 수량
        return f"{v:+,.0f}주"
    if unit == "주수":  # 잔고처럼 크기만 있는 수량
        return f"{v:,.0f}주"
    if unit == "일":
        return f"{v:,.0f}일"
    if unit == "개":
        return f"{v:,.0f}개"
    if unit == "score":
        return f"{v:+.3f}"
    if unit == "coef":
        return f"{v:+.2f}"
    if unit == "pos":
        return f"{v:,.0f}/100"
    if unit == "pctile":
        return f"{v:,.0f}백분위"
    if unit == "USD/bbl":
        return f"{v:,.2f}달러/배럴"
    if unit == "idx":
        return f"{v:,.2f}"
    return f"{v:,.4g}{unit}"


class Facts:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.items: dict[str, dict[str, Any]] = {}
        self.gaps: list[dict[str, str]] = []
        self.flags: list[str] = []      # 코드 규칙이 낸 판정 (예: "부채비율 200% 초과 {F6}")
        self.notes: list[str] = []      # 해석 가이드(숫자 없음)

    def add(self, label: str, value: Any, unit: str, as_of: Any = None, source: str = "",
            kind: str = "obs", note: str = "", group: str = "") -> str | None:
        if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
            self.gap(label, "DB 값 없음")
            return None
        key = f"{self.prefix}{len(self.items) + 1}"
        self.items[key] = {
            "label": label, "value": float(value), "unit": unit, "text": fmt(value, unit),
            "as_of": str(as_of) if as_of is not None else None, "source": source,
            "kind": KIND_LABEL.get(kind, kind), "note": note, "group": group,
        }
        return key

    def gap(self, label: str, reason: str) -> None:
        if not any(g["label"] == label for g in self.gaps):
            self.gaps.append({"label": label, "reason": reason})

    def flag(self, text: str) -> None:
        self.flags.append(text)

    def note(self, text: str) -> None:
        self.notes.append(text)

    def key_of(self, label: str) -> str | None:
        for k, v in self.items.items():
            if v["label"] == label:
                return k
        return None

    def for_prompt(self) -> str:
        lines = []
        group = None
        for k, v in self.items.items():
            if v["group"] and v["group"] != group:
                group = v["group"]
                ref = " · 참고용(제작 기준 밖): 핵심 진단·주장의 유일한 근거로 쓰지 말 것" if v.get("tier") == "reference" else ""
                lines.append(f"[{group}{ref}]")
            extra = f" ※{v['note']}" if v["note"] else ""
            lines.append(f"- {k}: {v['label']} = {v['text']} (기준 {v['as_of']}, {v['kind']}){extra}")
        if self.gaps:
            lines.append("[무자료]")
            lines += [f"- {g['label']}: {g['reason']}" for g in self.gaps]
        return "\n".join(lines)

    def table_md(self, evidence: dict[str, str] | None = None) -> str:
        """evidence: 장부 키 → 근거 ID (데이터 계약). 주면 첫 열에 'E03·M3' 처럼 함께 표시."""
        if not self.items:
            return "_인용 가능한 숫자가 없습니다._"
        rows = ["| 키 | 항목 | 값 | 기준일 | 구분 | 출처 |", "| --- | --- | --- | --- | --- | --- |"]
        rows += [f"| {(evidence[k] + '·') if evidence and k in evidence else ''}{k} | {v['label']} | {v['text']} | "
                 f"{v['as_of'] or '-'} | {v['kind']} | {v['source']} |"
                 for k, v in self.items.items() if v["unit"] != "doc"]
        return "\n".join(rows)


# ---------------------------------------------------------------- 계산 도구

def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    if old < 0:  # 음수 기준값의 증감률은 오해를 부르므로 계산하지 않음
        return None
    return (new / old - 1) * 100


def series_points(obs: Iterable[dict] | None) -> list[tuple[str, float]]:
    """[{'d': 날짜, 'v': 값}] → 날짜순 [(날짜, 값)] (None 제외)."""
    pts = [(str(o["d"])[:10], float(o["v"])) for o in (obs or []) if o.get("v") is not None]
    return sorted(pts)


def value_on_or_before(points: list[tuple[str, float]], day: str) -> tuple[str, float] | None:
    i = bisect_right([d for d, _ in points], day)
    return points[i - 1] if i else None


def shift_months(day: str, months: int) -> str:
    y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
    m -= months
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}-{min(d, 28 if m == 2 else 30 if m in (4, 6, 9, 11) else 31):02d}"


MAX_DAILY_MOVE = 0.35  # 국내 가격제한폭(30%)을 넘는 하루 변화는 액면분할 등 데이터 이상으로 보고 제외


def daily_returns(points: list[tuple[str, float]], cap: float | None = MAX_DAILY_MOVE) -> dict[str, float]:
    out = {}
    for (_, p0), (d1, p1) in pairwise(points):
        if p0:
            r = p1 / p0 - 1
            if cap is None or abs(r) <= cap:
                out[d1] = r
    return out


def daily_diffs(points: list[tuple[str, float]]) -> dict[str, float]:
    return {d1: p1 - p0 for (_, p0), (d1, p1) in pairwise(points)}


def corr_beta(xs: list[float], ys: list[float]) -> tuple[float | None, float | None, int]:
    """상관계수와 베타(y를 x로 단순회귀한 기울기). 표본이 30개 미만이면 None."""
    n = len(xs)
    if n < 30 or n != len(ys):
        return None, None, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0 or syy == 0:
        return None, None, n
    return sxy / math.sqrt(sxx * syy), sxy / sxx, n


def significant(r: float | None, n: int) -> bool:
    """|r| 이 대략 95% 유의 기준(2/√n)을 넘는지. 정밀한 검정이 아닌 거친 걸러내기."""
    return r is not None and n > 0 and abs(r) > 2 / math.sqrt(n)


CORR_BANDS = ((0.4, "강함"), (0.2, "보통"))  # |r| 이 이 값 이상이면 해당 크기, 나머지는 '약함'


def corr_size(r: float | None) -> str | None:
    """상관의 '크기' 등급. 유의성(significant)과는 별개입니다.

    표본이 250일이면 |r|=0.17 도 통계적으로 유의하지만 크기는 약합니다. 둘을 한 단어('뚜렷')로
    합치면 -0.17 은 '뚜렷', 60일 -0.16 은 '약함'처럼 읽혀 기준이 섞이므로 따로 표시합니다."""
    if r is None:
        return None
    for th, name in CORR_BANDS:
        if abs(r) >= th:
            return name
    return "약함"


def corr_label(r: float | None, n: int) -> str:
    """판정 문구: '상관 약함·유의함' 처럼 크기와 유의성을 함께."""
    return f"상관 {corr_size(r)}·{'유의함' if significant(r, n) else '유의하지 않음'}"


def percentile_rank(values: list[float], x: float) -> float | None:
    """x 가 values 안에서 몇 백분위인지 (0~100). 값이 5개 미만이면 None."""
    vals = [v for v in values if v is not None]
    if len(vals) < 5:
        return None
    below = sum(1 for v in vals if v < x)
    equal = sum(1 for v in vals if v == x)
    return (below + 0.5 * equal) / len(vals) * 100


def median(values: list[float]) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def streak(values: list[float]) -> int:
    """최신값부터 같은 부호가 몇 번 이어지는지. 양수면 +, 음수면 -, 0 이면 0. values 는 최신순."""
    if not values or not values[0]:
        return 0
    sign = 1 if values[0] > 0 else -1
    n = 0
    for v in values:
        if v and (v > 0) == (sign > 0):
            n += 1
        else:
            break
    return sign * n


def days_between(a: str, b: str) -> int:
    from datetime import date

    return (date.fromisoformat(str(b)[:10]) - date.fromisoformat(str(a)[:10])).days


def check_freshness(f: Facts, label: str, last_day: str | None, as_of: str, max_days: int) -> None:
    """자료의 마지막 날짜가 기준일보다 max_days 넘게 오래되면 판정으로 남깁니다."""
    if not last_day:
        return
    gap = days_between(last_day, as_of)
    if gap > max_days:
        f.flag(f"자료 지연: {label} 마지막 자료가 {str(last_day)[:10]} (기준일보다 오래됨, 해석 주의)")
