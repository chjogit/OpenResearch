"""core_finance_peer_analyst (P0): TTM 재무와 KOSPI 200 내 Peer 멀티플.

뷰 정의는 kic-agent-data/sql/005_quarterly.sql (core.v_ttm) 참고.
"""
from agent.db import ToolResult, query

TOOL = "core_finance_peer_analyst"

TTM_SQL = """
SELECT market, ticker, name, ttm_end, revenue_ttm, operating_income_ttm, net_income_ttm,
       equity, per_ttm, pbr, op_margin_ttm, roe_ttm, debt_ratio, currency
FROM core.v_ttm
WHERE market = %(market)s AND ticker = %(ticker)s
"""

PEER_SQL = """
SELECT m.rank, m.reason, v.ticker, v.name, v.per_ttm, v.pbr, v.op_margin_ttm, v.roe_ttm, v.debt_ratio
FROM core.company b
JOIN core.peer_group g ON g.base_company_id = b.company_id
JOIN core.peer_member m ON m.peer_group_id = g.peer_group_id
JOIN core.company c ON c.company_id = m.company_id
JOIN core.v_ttm v ON v.market = c.market AND v.ticker = c.ticker
WHERE b.market = %(market)s AND b.ticker = %(ticker)s
ORDER BY m.rank NULLS LAST
"""


def get_ttm(ticker: str, market: str = "KR") -> ToolResult:
    """종목 하나의 TTM 실적과 밸류에이션."""
    return query(TOOL, TTM_SQL, {"market": market, "ticker": ticker})


def get_peer_table(ticker: str, market: str = "KR") -> ToolResult:
    """기준 종목의 Peer 그룹과 각 Peer 의 TTM 멀티플."""
    return query(TOOL, PEER_SQL, {"market": market, "ticker": ticker})

# TODO: Peer 중앙값·평균 멀티플(SQL 집계), 업종(KRX 26개) 기준 Peer 자동 선정, Text-to-SQL 질의
