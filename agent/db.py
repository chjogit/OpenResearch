"""Neon 읽기 전용 조회. Agent 는 DB 에 쓰지 않습니다.

접속 계정 자체가 읽기 전용(agent_reader)이어야 하고, 여기서도 세션을 read only 로 한 번 더 막습니다.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row

from agent import config


@dataclass
class ToolResult:
    """도구 한 번 실행한 기록. Verifier 가 초안 수치를 이 기록과 대조합니다."""
    tool: str
    source: str                      # 출처 태그에 들어갈 이름 (예: "Neon core", "DART 2026.Q3")
    sql: str
    params: dict
    rows: list[dict]
    ran_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def connect() -> psycopg.Connection:
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL 이 비어 있습니다. .env 를 확인하세요 (docs/DB_READONLY.md).")
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True)
    conn.execute("SET default_transaction_read_only = on")
    conn.execute("SET statement_timeout = '15s'")
    return conn


def query(tool: str, sql: str, params: dict | None = None, source: str = "Neon core") -> ToolResult:
    """SELECT 하나를 실행하고 ToolResult 로 돌려줍니다."""
    if not sql.lstrip().lower().startswith(("select", "with")):
        raise ValueError("SELECT/WITH 질의만 허용합니다.")
    params = params or {}
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return ToolResult(tool=tool, source=source, sql=sql, params=params, rows=rows)
