"""dart_sec_risk_examiner (P0): 공시 검색과 객관적 부실 징후 4종 진단.

부실 징후: 이자보상배율 1 미만, 자본잠식, 감사의견 비적정, 관리종목.
판정은 SQL 결과로만 하고 LLM 은 결과를 서술만 합니다.
"""
from agent.db import ToolResult, query

TOOL = "dart_sec_risk_examiner"

RECENT_DISCLOSURE_SQL = """
SELECT d.rcept_no, d.rcept_dt, d.report_nm, d.filer
FROM core.disclosure d
JOIN core.company c ON c.company_id = d.company_id
WHERE c.market = %(market)s AND c.ticker = %(ticker)s
ORDER BY d.rcept_dt DESC
LIMIT %(limit)s
"""

CAPITAL_IMPAIRMENT_SQL = """
SELECT ticker, name, bs_end, equity
FROM core.v_ttm
WHERE market = %(market)s AND ticker = %(ticker)s
"""


def recent_disclosures(ticker: str, market: str = "KR", limit: int = 20) -> ToolResult:
    return query(TOOL, RECENT_DISCLOSURE_SQL, {"market": market, "ticker": ticker, "limit": limit}, source="DART")


def capital_impairment(ticker: str, market: str = "KR") -> ToolResult:
    """자기자본(equity)이 0 이하이면 완전 자본잠식. 부분 잠식은 자본금 데이터가 필요(TODO)."""
    return query(TOOL, CAPITAL_IMPAIRMENT_SQL, {"market": market, "ticker": ticker})

# TODO: 이자보상배율(영업이익/이자비용), 감사의견(공시 본문), 관리종목 여부, rag.chunk 공시 청크 검색
