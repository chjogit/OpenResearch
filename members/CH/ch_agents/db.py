"""Neon 읽기 전용 조회.

관점 에이전트마다 SQL 한 번으로 필요한 데이터를 JSON 묶음(bundle)으로 받습니다.
계산은 파이썬 순수 함수가 하므로, 같은 묶음을 넣으면 언제나 같은 숫자가 나옵니다(테스트 가능).
"""
from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Any

try:  # 노트북에서 .env 를 읽어 둠 (없어도 동작)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL 이 비어 있습니다. .env 를 확인하세요 (docs/DB_READONLY.md).")
    return url


OPINION_SOURCES = ("naver_blog", "naver_cafe")   # kic-opinion 프로젝트에 두는 출처 (kic-agent-data 10번)


def opinion_url() -> str:
    return os.getenv("OPINION_DATABASE_URL", "")


def opinion_enabled() -> bool:
    """블로그·카페를 별도 프로젝트(kic-opinion)에서 읽는지. 접속 정보가 없으면 메인 DB 하나로 동작합니다."""
    return bool(opinion_url())


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, date):
        return v.isoformat()
    return v


def q(sql: str, params: dict | None = None, url: str | None = None) -> list[dict]:
    """SELECT/WITH 하나를 읽기 전용 세션에서 실행합니다 (url 이 없으면 메인 DB)."""
    if not sql.lstrip().lower().startswith(("select", "with")):
        raise ValueError("SELECT/WITH 질의만 허용합니다.")
    if "%(as_of)s" in sql:   # E3: 기준일을 쓰는 질의는 as_of 를 반드시 넘겨야 함 (비면 오류, 오늘로 대체하지 않음)
        from .asof import require_as_of

        require_as_of((params or {}).get("as_of"))
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(url or database_url(), row_factory=dict_row, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '20s'")
        rows = conn.execute(sql, params or {}).fetchall()
    return [_plain(dict(r)) for r in rows]


def q_opinion(sql: str, params: dict | None = None) -> list[dict]:
    """블로그·카페 질의. kic-opinion 이 설정돼 있어야 합니다 (opinion_enabled() 로 먼저 확인)."""
    if not opinion_enabled():
        raise RuntimeError("OPINION_DATABASE_URL 이 비어 있습니다.")
    return q(sql, params, opinion_url())


def bundle(sql: str, params: dict) -> dict:
    """`SELECT json_build_object(...) AS bundle` 형태 질의의 결과 dict 를 돌려줍니다."""
    rows = q(sql, params)
    return (rows[0].get("bundle") if rows else None) or {}


SQL_COMPANY = """
    SELECT company_id, market, ticker, name, krx_sector, sector, index_tags,
           (SELECT g.method FROM core.peer_group g WHERE g.base_company_id = c.company_id
            ORDER BY g.created_at DESC LIMIT 1) AS peer_method
    FROM core.company c
    WHERE market = 'KR' AND ticker = %(ticker)s
"""


def company(ticker: str) -> dict:
    rows = q(SQL_COMPANY, {"ticker": ticker})
    if not rows:
        raise ValueError(f"core.company 에 KR {ticker} 가 없습니다.")
    return rows[0]
