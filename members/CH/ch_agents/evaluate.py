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
from .agents import AGENTS, MY_AGENTS, build_agent_data, fetch_agent_data, fetch_bundle, normalize_as_of
from .llm import run_agent

DEFAULT_TICKERS = ["005930", "000660", "035420", "105560", "005380", "051910", "068270", "017670"]


def kospi200_tickers(limit: int | None = None) -> list[str]:
    rows = db.q("SELECT ticker FROM core.company WHERE market = 'KR' AND 'KOSPI200' = ANY(index_tags) "
                "ORDER BY ticker")
    return [r["ticker"] for r in rows][:limit]


def data_scorecard(tickers: list[str] | None = None, agent_ids=MY_AGENTS, as_of: str | None = None) -> list[dict]:
    as_of = normalize_as_of(as_of)
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
                out.append({"ticker": t, "name": co["name"], "agent": f"에이전트 {a}", "facts": len(d.facts.items),
                            "gaps": len(d.facts.gaps), "flags": len(d.facts.flags),
                            "seconds": round(time.monotonic() - t0, 1), "error": ""})
            except Exception as e:  # noqa: BLE001
                out.append({"ticker": t, "name": co["name"], "agent": f"에이전트 {a}", "error": f"{type(e).__name__}: {e}"})
    return out


def llm_scorecard(tickers: list[str] | None = None, agent_ids=MY_AGENTS, mode: str = "expert",
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
        # LLM 호출 자체가 실패한 경우의 오류 (같은 오류는 묶어서 횟수)
        "llm_errors": dict(Counter(a["error"][:200] for r in results for a in r.get("attempts", []) if "error" in a)),
    }
    if save_to:
        Path(save_to).write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1,
                                            default=str), encoding="utf-8")
    return summary


NODE_AGENT_IDS = (3, 4, 6)
BASELINE_FILE = "eval_results.json"          # 분리 전(10/30, 에이전트 1·3) 기록. 덮어쓰지 않음


def summarize_runs(results: list[dict]) -> dict:
    """성적표 요약 (llm_scorecard 와 같은 항목)."""
    status = Counter(r["status"].split(" (")[0] for r in results)
    n = max(len(results), 1)
    return {
        "runs": len(results), "status": dict(status),
        "repaired": sum(1 for r in results if len(r.get("attempts", [])) > 1),
        "removed_sentences": sum(len(r.get("removed", [])) for r in results),
        "check_violations_last_attempt": dict(Counter(k for r in results for k in (r.get("checks") or {}))),
        "avg_seconds": round(sum(r.get("seconds", 0) for r in results) / n, 1),
        "avg_claims": round(sum(len(r["result"].get("주장", [])) for r in results) / n, 1),
        "llm_errors": dict(Counter(a["error"][:200] for r in results for a in r.get("attempts", []) if "error" in a)),
    }


def node_scorecard(tickers: list[str] | None = None, agent_nos=NODE_AGENT_IDS, mode: str = "expert", extension: bool = True,
                   scenario: str | None = "환율 5% 상승", as_of: str | None = None, save_to: str | None = None,
                   llm=None, baseline: str | None = BASELINE_FILE) -> dict:
    """노드 기반 에이전트 3·4·6 의 LLM 성적표 (#25). 결과 파일은 새 이름(기본 eval_results_nodes_<기준일>.json)이고
    baseline(분리 전 기록)이 있으면 요약을 나란히 둔다. 기존 eval_results.json 은 건드리지 않는다."""
    from .llm import run_node_agent

    as_of = normalize_as_of(as_of)
    save_to = save_to if save_to is not None else f"eval_results_nodes_{as_of}.json"
    if save_to == baseline:
        raise ValueError("분리 전 기록(eval_results.json)을 덮어쓸 수 없습니다. 다른 파일 이름을 쓰세요.")
    results = []
    for t in tickers or DEFAULT_TICKERS:
        co = db.company(t)
        for a in agent_nos:
            try:
                res = run_node_agent(a, t, mode=mode, llm=llm, as_of=as_of, extension=extension,
                                     scenario=scenario if a == 3 else None)
            except Exception as e:  # noqa: BLE001  한 종목의 오류가 전체를 멈추지 않게
                results.append({"ticker": t, "agent_id": a, "status": "실행 오류", "attempts": [{"error": f"{type(e).__name__}: {e}"}],
                                "result": {}, "seconds": 0})
                continue
            res.pop("analysis", None)
            res["node_states"] = [(n["nodeId"], n["state"], n["status"]) for n in res.get("node_report", {}).get("nodes", [])]
            results.append({"ticker": t, "name": co["name"], **res})
    out = {"as_of": as_of, "extension": extension, "summary": summarize_runs(results), "by_agent": {
        str(a): summarize_runs([r for r in results if r.get("agent_id") == a]) for a in agent_nos}}
    if baseline and Path(baseline).exists():
        old = json.loads(Path(baseline).read_text(encoding="utf-8"))
        out["before_split"] = {"file": baseline, "summary": old.get("summary"),
                               "by_agent": {str(a): summarize_runs([r for r in old["results"] if r.get("agent_id") == a])
                                            for a in (1, 3)}}
    if save_to:
        Path(save_to).write_text(json.dumps({**out, "results": results}, ensure_ascii=False, indent=1, default=str),
                                 encoding="utf-8")
    return out


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
    as_of = normalize_as_of(as_of)
    co = db.company(ticker)
    sql = db.q(SQL_XCHECK, {"cid": co["company_id"], "as_of": as_of})[0]
    a1 = fetch_agent_data(1, ticker, as_of, co=co).facts
    a2 = fetch_agent_data(7, ticker, as_of, co=co).facts
    a4 = fetch_agent_data(3, ticker, as_of, co=co).facts

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


# ---------------------------------------------------------------- 스냅샷 (DB 없이 재현)

def capture_snapshot(ticker: str, path: str | None = None, as_of: str | None = None, agent_ids=MY_AGENTS) -> str:
    """실제 DB 묶음을 JSON 파일로 저장합니다. 회귀 테스트나 DB 접속이 어려운 데모에서 재현용으로 씁니다."""
    as_of = normalize_as_of(as_of)
    co = db.company(ticker)
    snap = {"as_of": as_of, "company": co, "bundles": {str(a): fetch_bundle(a, co, as_of) for a in agent_ids}}
    path = path or f"snapshot_{ticker}_{as_of}.json"
    Path(path).write_text(json.dumps(snap, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def load_snapshot(path: str) -> dict:
    """저장한 스냅샷에서 관점별 AgentData 를 만듭니다: {1: AgentData, 3: AgentData}"""
    snap = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(a): build_agent_data(int(a), snap["company"], b, snap["as_of"])
            for a, b in snap["bundles"].items() if int(a) in AGENTS}
