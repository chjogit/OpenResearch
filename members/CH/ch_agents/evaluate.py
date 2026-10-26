"""여러 종목 일괄 점검과 교차 검증.

- data_scorecard: LLM 없이 데이터 단계만 돌려 종목·관점별 숫자 수, 무자료 수, 판정 수, 오류를 표로 만듭니다.
- llm_scorecard: LLM까지 돌려 상태 분포(완료·수정·대체), 검사 위반, 제외 문장, 소요 시간을 집계합니다.
- cross_check: 파이썬 계산값 몇 개를 SQL로 따로 다시 계산해 서로 맞는지 확인합니다.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from . import db
from .agents import fetch_agent_data, today_kst
from .llm import run_agent

DEFAULT_TICKERS = ["005930", "000660", "035420", "105560", "005380", "051910", "068270", "017670"]


def kospi200_tickers(limit: int | None = None) -> list[str]:
    rows = db.q("SELECT ticker FROM core.company WHERE market = 'KR' AND 'KOSPI200' = ANY(index_tags) "
                "ORDER BY ticker")
    return [r["ticker"] for r in rows][:limit]


def data_scorecard(tickers: list[str] | None = None, agent_ids=(1, 2, 4), as_of: str | None = None) -> list[dict]:
    as_of = as_of or today_kst()
    out = []
    for t in tickers or DEFAULT_TICKERS:
        try:
            co = db.company(t)
        except Exception as e:  # noqa: BLE001
            out.append({"ticker": t, "error": str(e)})
            continue
        for a in agent_ids:
            t0 = time.monotonic()
            try:
                d = fetch_agent_data(a, t, as_of, co=co)
                out.append({"ticker": t, "name": co["name"], "agent": f"A{a}", "facts": len(d.facts.items),
                            "gaps": len(d.facts.gaps), "flags": len(d.facts.flags),
                            "seconds": round(time.monotonic() - t0, 1), "error": ""})
            except Exception as e:  # noqa: BLE001
                out.append({"ticker": t, "name": co["name"], "agent": f"A{a}", "error": f"{type(e).__name__}: {e}"})
    return out


def llm_scorecard(tickers: list[str] | None = None, agent_ids=(1, 2, 4), mode: str = "expert",
                  save_to: str | None = "eval_results.json", llm=None) -> dict:
    results = []
    for t in tickers or DEFAULT_TICKERS[:3]:
        for a in agent_ids:
            res = run_agent(a, t, mode=mode, llm=llm)
            res.pop("analysis", None)
            results.append({"ticker": t, **res})
    status = Counter(r["status"].split(" (")[0] for r in results)
    summary = {
        "runs": len(results),
        "status": dict(status),
        "repaired": sum(1 for r in results if len(r.get("attempts", [])) > 1),
        "removed_sentences": sum(len(r.get("removed", [])) for r in results),
        "check_violations_last_attempt": dict(Counter(k for r in results for k in (r.get("checks") or {}))),
        "avg_seconds": round(sum(r.get("seconds", 0) for r in results) / max(len(results), 1), 1),
        "avg_claims": round(sum(len(r["result"].get("주장", [])) for r in results) / max(len(results), 1), 1),
    }
    if save_to:
        Path(save_to).write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1,
                                            default=str), encoding="utf-8")
    return summary


# ---------------------------------------------------------------- 교차 검증

SQL_XCHECK = """
WITH px AS (
    SELECT trade_date, close / LAG(close) OVER (ORDER BY trade_date) - 1 AS r
    FROM core.price_daily WHERE company_id = %(cid)s AND trade_date <= %(as_of)s::date
      AND trade_date > %(as_of)s::date - INTERVAL '400 days'
), ks AS (
    SELECT trade_date, close / LAG(close) OVER (ORDER BY trade_date) - 1 AS r
    FROM core.market_index_daily WHERE symbol = '^KS11' AND trade_date <= %(as_of)s::date
      AND trade_date > %(as_of)s::date - INTERVAL '400 days'
), pair AS (
    SELECT px.r AS y, ks.r AS x FROM px JOIN ks USING (trade_date)
    WHERE px.r IS NOT NULL AND ks.r IS NOT NULL AND abs(px.r) <= 0.35
    ORDER BY trade_date DESC LIMIT 250
), fl AS (
    SELECT foreign_net_qty FROM core.investor_flow_daily
    WHERE company_id = %(cid)s AND trade_date <= %(as_of)s::date ORDER BY trade_date DESC LIMIT 20
)
SELECT (SELECT corr(y, x) FROM pair) AS kospi_corr_250,
       (SELECT regr_slope(y, x) FROM pair) AS kospi_beta_250,
       (SELECT sum(foreign_net_qty) FROM fl) AS foreign_20d,
       (SELECT per_ttm FROM core.v_ttm t JOIN core.company c ON c.market = t.market AND c.ticker = t.ticker
        WHERE c.company_id = %(cid)s) AS per_ttm
"""


def cross_check(ticker: str, as_of: str | None = None) -> list[dict]:
    """파이썬 계산값과 SQL 재계산값 비교. 다르면 계산 로직이나 정렬 기준을 의심합니다."""
    as_of = as_of or today_kst()
    co = db.company(ticker)
    sql = db.q(SQL_XCHECK, {"cid": co["company_id"], "as_of": as_of})[0]
    a1 = fetch_agent_data(1, ticker, as_of, co=co).facts
    a2 = fetch_agent_data(2, ticker, as_of, co=co).facts
    a4 = fetch_agent_data(4, ticker, as_of, co=co).facts

    def val(f, label):
        k = f.key_of(label)
        return f.items[k]["value"] if k else None

    pairs = [
        ("코스피 상관(250일)", val(a1, "주가-코스피 상관(250일)"), sql["kospi_corr_250"], 0.02),
        ("코스피 베타(250일)", val(a1, "주가-코스피 베타(250일)"), sql["kospi_beta_250"], 0.03),
        ("외국인 20일 순매수 수량", val(a4, "외국인 20일 순매수 수량"), sql["foreign_20d"], 0.5),
        ("PER: 밴드 현재값 vs v_ttm", val(a2, "PER 밴드 현재값(시가총액 ÷ 최근 TTM 순이익)"), sql["per_ttm"], 0.3),
    ]
    out = []
    for name, py, sq, tol in pairs:
        ok = None if py is None or sq is None else abs(float(py) - float(sq)) <= tol
        out.append({"항목": name, "파이썬": py, "SQL": sq, "허용 오차": tol,
                    "판정": "일치" if ok else "불일치" if ok is False else "비교 불가"})
    return out
