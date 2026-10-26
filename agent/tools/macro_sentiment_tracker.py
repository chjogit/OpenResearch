"""macro_sentiment_tracker (P1): ECOS/FRED 거시 변수와 2시간 단위 감성·언급량 스냅샷."""
from agent.db import ToolResult, query

TOOL = "macro_sentiment_tracker"

MACRO_SQL = """
SELECT s.series_id, s.name, s.unit, o.obs_date, o.value
FROM core.macro_obs o
JOIN core.macro_series s USING (series_id)
WHERE o.series_id = %(series_id)s
ORDER BY o.obs_date DESC
LIMIT %(limit)s
"""

PULSE_SQL = """
SELECT p.captured_at, p.trade_date, p.n_today, p.n_positive, p.n_negative, p.sentiment, p.mentions_vs_30d
FROM core.reaction_pulse p
JOIN core.company c ON c.company_id = p.company_id
WHERE c.market = %(market)s AND c.ticker = %(ticker)s
ORDER BY p.captured_at DESC
LIMIT %(limit)s
"""


def macro_series(series_id: str, limit: int = 12) -> ToolResult:
    return query(TOOL, MACRO_SQL, {"series_id": series_id, "limit": limit}, source="Neon core (ECOS/FRED)")


def reaction_pulse(ticker: str, market: str = "KR", limit: int = 12) -> ToolResult:
    return query(TOOL, PULSE_SQL, {"market": market, "ticker": ticker, "limit": limit})
