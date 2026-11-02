"""R4-2 비교 실행: 종목 × 에이전트(1·3) × 리랭킹 끔/켬. 실제 DB(읽기 전용)·Upstage LLM·Cohere 를 씁니다.

    python members/CH/scripts/rerank_compare.py [기준일] [종목코드 ...]

Cohere 호출은 '켬' 실행마다 최대 1회(트라이얼 월 1,000회). 결과는 members/CH/rerank_compare_results.json
(기존 eval_results.json 은 건드리지 않음). 비밀값은 출력하지 않습니다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch_agents import db, rerank  # noqa: E402
from ch_agents.agents import fetch_agent_data  # noqa: E402
from ch_agents.llm import run_agent  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "rerank_compare_results.json"


def _doc(d: dict) -> dict:
    return {k: d.get(k) for k in ("kind", "source", "published", "doc_id", "chunk_id", "score", "rerank_score")} | \
        {"title": str(d.get("title") or "")[:50]}


def run_one(ticker: str, co: dict, agent_id: int, as_of: str, mode: str) -> dict:
    os.environ["CH_RAG_RERANK"] = mode
    t0 = time.perf_counter()
    data = fetch_agent_data(agent_id, ticker, as_of, co=co)
    t_fetch = time.perf_counter() - t0
    out = run_agent(agent_id, data=data)
    total = time.perf_counter() - t0
    claims = (out["result"].get("주장") or []) + (out["result"].get("반대근거") or [])
    return {
        "ticker": ticker, "agent": agent_id, "rerank": mode, "status": out["status"],
        "seconds_fetch": round(t_fetch, 1), "seconds_llm": out["seconds"], "seconds_total": round(total, 1),
        "llm_attempts": len(out["attempts"]), "claims": len(out["result"].get("주장") or []),
        "counters": len(out["result"].get("반대근거") or []), "removed": len(out["removed"]),
        "trimmed": out["claim_stats"]["trimmed"], "claims_with_chunk": sum(1 for c in claims if c.get("chunkId")),
        "removed_texts": out["removed"], "checks_first": out["attempts"][0].get("checks") if out["attempts"] else None,
        "docs": [_doc(d) for d in data.docs], "rag_chunks": out.get("rag_chunks"),
        "rag_error": data.extra.get("rag_error"),
    }


def main():
    as_of = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    tickers = sys.argv[2:] or ["005930", "000660", "005380"]
    rows = []
    for t in tickers:
        co = db.company(t)
        for a in (1, 3):
            for mode in ("off", "on"):
                r = run_one(t, co, a, as_of, mode)
                rows.append(r)
                print(f"{t} A{a} {mode:3} {r['status'][:12]:12} 총 {r['seconds_total']:>5}s (검색 {r['seconds_fetch']}s) "
                      f"주장 {r['claims']} 반대 {r['counters']} 제거 {r['removed']} 청크인용 {r['claims_with_chunk']}", flush=True)
    os.environ["CH_RAG_RERANK"] = "off"
    OUT.write_text(json.dumps({"as_of": as_of, "cohere_calls": rerank.CALLS["total"], "model": rerank.model_name(),
                               "runs": rows}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Cohere 호출 {rerank.CALLS['total']}회 · 저장 {OUT.name}")


if __name__ == "__main__":
    main()
