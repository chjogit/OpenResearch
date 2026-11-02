"""#18 청크 인용 보강 반복 비교: 종목 × 에이전트(1·3) × 리랭킹(끔=chunk/켬=on) × 보강(off/boost) × 반복.

    python members/CH/scripts/citation_boost_compare.py [기준일] [반복 수] [종목코드 ...]

- 데이터(검색·리랭킹)는 종목·에이전트·리랭킹 조합마다 한 번만 가져오고, 같은 입력으로 보강 전/후 LLM 을 반복 실행합니다.
  그래서 반복 간 차이는 LLM 편차, 보강 전/후 차이는 프롬프트 차이입니다.
- '리랭킹 끔' = CH_RAG_RERANK=chunk (청크 근거·합산 순위, Cohere 0회). '켬' = on (Cohere 조합당 1회).
- 계획 상한: Cohere = 종목 × 에이전트 × 반복 × 2(보강 전/후) (36회) 이내. 실제로는 조합당 1회(6회).
- 결과는 members/CH/citation_boost_compare.json (이미 있으면 덮어쓰지 않고 멈춤). DB 는 읽기만, 비밀값은 출력하지 않음.
"""
from __future__ import annotations

import copy
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ch_agents import db, rerank  # noqa: E402
from ch_agents.agents import fetch_agent_data  # noqa: E402
from ch_agents.llm import run_agent  # noqa: E402
from ch_agents.prompts import CHUNK_BOOST_MISSING  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "citation_boost_compare.json"
RERANK_MODES = (("off", "chunk"), ("on", "on"))     # (표 이름, CH_RAG_RERANK 값)
BOOST_MODES = ("off", "boost")
METRICS = ("chunk_ratio", "claims_with_chunk", "claims_total", "removed", "completed", "seconds_llm")


def run_one(data, ticker: str, agent_id: int, rr: str, boost: str, rep: int, fetch_s: float) -> dict:
    os.environ["CH_CHUNK_CITE"] = boost
    out = run_agent(agent_id, data=copy.deepcopy(data))
    res = out["result"]
    claims = (res.get("주장") or []) + (res.get("반대근거") or [])
    n_chunk = sum(1 for c in claims if c.get("chunkId"))
    first = out["attempts"][0].get("checks") if out["attempts"] else None
    rc = out.get("rag_chunks") or {}
    return {
        "ticker": ticker, "agent": agent_id, "rerank": rr, "boost": boost, "rep": rep,
        "status": out["status"], "completed": int(out["status"].startswith("완료")),
        "seconds_fetch": round(fetch_s, 1), "seconds_llm": out["seconds"],
        "llm_calls": sum(1 for a in out["attempts"] if "raw" in a or "error" in a),
        "claims": len(res.get("주장") or []), "counters": len(res.get("반대근거") or []),
        "claims_total": len(claims), "claims_with_chunk": n_chunk,
        "chunk_ratio": round(n_chunk / len(claims), 3) if claims else 0.0,
        "removed": len(out["removed"]), "trimmed": out["claim_stats"]["trimmed"],
        "missing_check_first": bool(first and CHUNK_BOOST_MISSING in (first.get("근거") or [])),
        "removed_texts": out["removed"], "checks_first": first,
        "chunk_ids_in_prompt": [d["chunk_id"] for d in data.docs if d.get("excerpt") is not None],
        "rag_mode": rc.get("mode"), "rerank_fallback": rc.get("rerank_fallback"), "rag_error": data.extra.get("rag_error"),
    }


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["agent"], r["rerank"], r["boost"]), []).append(r)
    out = []
    for (a, rr, b), rs in sorted(groups.items()):
        s = {"agent": a, "rerank": rr, "boost": b, "n": len(rs)}
        for m in METRICS:
            v = [float(r[m]) for r in rs]
            s[m] = {"mean": round(statistics.mean(v), 3), "min": min(v), "max": max(v)}
        out.append(s)
    return out


def main():
    as_of = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    tickers = sys.argv[3:] or ["005930", "000660", "005380"]
    if OUT.exists():
        sys.exit(f"{OUT.name} 이 이미 있음 — 덮어쓰지 않음")
    cohere_cap = len(tickers) * 2 * reps * len(BOOST_MODES)
    rows, fetches = [], 0
    for t in tickers:
        co = db.company(t)
        for a in (1, 3):
            for rr, env in RERANK_MODES:
                os.environ["CH_RAG_RERANK"] = env
                if rerank.CALLS["total"] >= cohere_cap:
                    sys.exit(f"Cohere 계획 상한 {cohere_cap}회 도달 — 멈춤")
                t0 = time.perf_counter()
                data = fetch_agent_data(a, t, as_of, co=co)
                fetch_s = time.perf_counter() - t0
                fetches += 1
                for boost in BOOST_MODES:
                    for rep in range(1, reps + 1):
                        r = run_one(data, t, a, rr, boost, rep, fetch_s)
                        rows.append(r)
                        print(f"{t} A{a} 리랭킹 {rr:3} 보강 {boost:5} #{rep} {r['status'][:12]:12} LLM {r['seconds_llm']:>5}s "
                              f"주장 {r['claims_total']} 청크인용 {r['claims_with_chunk']} 제거 {r['removed']}", flush=True)
                os.environ["CH_RAG_RERANK"] = "off"
                os.environ["CH_CHUNK_CITE"] = "off"
    calls = {"cohere": rerank.CALLS["total"], "cohere_cap": cohere_cap, "fetches": fetches,
             "embedding": fetches, "llm": sum(r["llm_calls"] for r in rows)}
    OUT.write_text(json.dumps({"as_of": as_of, "reps": reps, "tickers": tickers, "model": rerank.model_name(),
                               "calls": calls, "summary": summarize(rows), "runs": rows},
                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"호출 {calls} · 저장 {OUT.name}")


if __name__ == "__main__":
    main()
