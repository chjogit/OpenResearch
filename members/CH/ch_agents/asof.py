"""기준일(as_of_date) 가드 (엔지니어링 E3, 11/2): 기준일 이후 자료가 분석에 섞이지 않게 데이터 조회 도구 계층에서 막습니다.

- 모든 조회 도구는 as_of 를 필수로 받습니다. 비었거나 날짜가 아니면 ValueError (조용히 '오늘'로 대체하지 않음).
- 규칙: **기준일과 같은 날짜는 포함, 다음 날부터 제거.** 공시일·뉴스 게시일·거래일을 날짜 단위로 비교합니다.
  한계: 뉴스 `published_at` 은 날짜 단위라 같은 날 장중/장후를 구분하지 못합니다(기준일 당일 기사는 모두 포함).
- SQL 이 이미 기준일로 거르지만(`published_at <= as_of`), 도구 계층에서 한 번 더 제거해 질의 실수·모의 데이터·캐시 스냅샷에 섞인
  미래 행도 분석에 들어가지 않게 합니다. 제거한 건수는 호출 쪽이 확인할 수 있게 돌려줍니다.
"""
from __future__ import annotations

from datetime import date, datetime

# 자료 종류별로 기준일과 비교할 날짜 열 (앞에서부터 처음 값이 있는 열을 씁니다)
DATE_KEYS = ("published_at", "published", "rcept_dt", "trade_date", "date", "base_date")


def require_as_of(as_of) -> str:
    """as_of 를 'YYYY-MM-DD' 로. 비었거나 형식이 틀리면 ValueError."""
    if as_of is None or as_of == "":
        raise ValueError("as_of_date 는 필수입니다 (미래 시점 자료 참조 방지).")
    if isinstance(as_of, datetime):
        return as_of.date().isoformat()
    if isinstance(as_of, date):
        return as_of.isoformat()
    try:
        return date.fromisoformat(str(as_of)[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"as_of_date 형식이 날짜가 아닙니다: {as_of!r}") from exc


def row_date(row: dict, keys: tuple[str, ...] = DATE_KEYS) -> str | None:
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return str(v)[:10]
    return None


def is_future(row: dict, as_of: str, keys: tuple[str, ...] = DATE_KEYS) -> bool:
    """기준일 다음 날 이후 자료인가 (같은 날짜는 False). 날짜를 알 수 없는 행은 거르지 않습니다."""
    d = row_date(row, keys)
    return d is not None and d > as_of


def cut_future(rows, as_of, keys: tuple[str, ...] = DATE_KEYS) -> tuple[list, int]:
    """(기준일 이전·당일 행, 제거한 건수). rows 가 None 이면 ([], 0)."""
    as_of = require_as_of(as_of)
    kept = [r for r in rows or [] if not is_future(r, as_of, keys)]
    return kept, len(rows or []) - len(kept)


def guard_bundle(bundle: dict, as_of, tables: tuple[str, ...] = ("news", "disclosures")) -> dict:
    """SQL 묶음(dict)의 표들에서 미래 행을 제거. 제거가 있었을 때만 `asof_removed` 를 남겨 정상 결과는 그대로 둡니다."""
    as_of = require_as_of(as_of)
    removed = {}
    for t in tables:
        if isinstance(bundle.get(t), list):
            bundle[t], n = cut_future(bundle[t], as_of)
            if n:
                removed[t] = n
    if removed:
        bundle["asof_removed"] = removed
    return bundle
