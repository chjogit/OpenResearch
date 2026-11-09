"""문서 검색 방식 비교(#67): 키워드만 vs 임베딩 중심(질문 포함 질의 → 독립 벡터 검색 → 키워드와 합침) + 임베딩 보유율.

사용: python scripts\rag_compare.py [기준일=2026-11-04]   → demo\rag_compare.json (시연 성능 탭이 읽음)
읽기 전용(DB 조회·임베딩 API 호출만). 개인 작성 글(블로그·카페·유튜브)은 문서 번호·점수만 남기고 제목·내용은 기록하지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from ch_agents import db, rag_hybrid  # noqa: E402
from qa import agent  # noqa: E402

OUT = HERE / "demo" / "rag_compare.json"
PRIVATE = ("naver_blog", "naver_cafe", "youtube_comment")
QUESTIONS = (
    ("005930", "삼성전자 최근 외국인 수급은 어때?"), ("005930", "삼성전자 최근 이슈가 뭐야?"), ("005930", "삼성전자 반도체 실적 전망 기사 있어?"),
    ("000660", "SK하이닉스 기관 순매수 흐름 알려줘"), ("000660", "SK하이닉스 HBM 관련 최근 소식은?"), ("005380", "현대차는 금리 변화에 얼마나 민감해?"),
    ("005380", "현대차 관세 영향 뉴스가 있어?"), ("005380", "현대차 지금 사도 될까?"), ("105560", "KB금융 최근 뉴스 분위기는?"),
    ("105560", "KB금융 배당·주주환원 관련 소식은?"), ("105560", "KB금융 환율 영향은?"), ("005930", "삼성전자 지금 팔아야 할까?"),
    ("005380", "현대차 노조 파업 소식 있어?"), ("005930", "삼성전자 노조 파업 소식 있어?"), ("000660", "SK하이닉스 우주 탐사 계획은?"), ("105560", "KB금융 반도체 수출 영향은?"),   # #70
)


def coverage() -> tuple[list[dict], str]:
    rows = db.q("""SELECT d.source, count(DISTINCT d.doc_id) AS docs,
                          count(DISTINCT d.doc_id) FILTER (WHERE c.embedding IS NOT NULL) AS embedded,
                          min(d.published_at)::text AS first, max(d.published_at)::text AS last
                   FROM rag.document d LEFT JOIN rag.chunk c USING (doc_id) GROUP BY d.source ORDER BY 2 DESC""")
    out = [{"source": r["source"], "docs": r["docs"], "embedded": r["embedded"], "first": r["first"], "last": r["last"], "db": "메인"} for r in rows]
    if db.opinion_enabled():
        for r in db.q_opinion("SELECT source, count(*) AS docs, min(published_at)::text AS first, max(published_at)::text AS last FROM rag.document GROUP BY source ORDER BY 2 DESC"):
            out.append({"source": r["source"], "docs": r["docs"], "embedded": 0, "first": r["first"], "last": r["last"], "db": "kic-opinion(청크·임베딩 테이블 없음)"})
    size = db.q("SELECT pg_size_pretty(pg_database_size(current_database())) AS s")[0]["s"]
    return out, size


def one(co: dict, as_of: str, question: str, mode: str) -> dict:
    os.environ["CH_RAG_HYBRID"] = mode
    t = time.monotonic()
    docs, info = agent.retrieve_docs(co, as_of, question)
    sec = round(time.monotonic() - t, 2)
    top = []
    for d in docs[:5]:
        private = str(d.get("source")) in PRIVATE
        top.append({"docNo": d.get("doc_id"), "source": "개인 작성 글" if private else str(d.get("source") or ""), "title": "" if private else str(d.get("title") or "")[:60],
                    "origin": d.get("origin") or "키워드", "score": d.get("score"), "sim": d.get("sim"), "chunks": len(d.get("chunks") or [])})
    return {"seconds": sec, "mode": info["mode"], "fallback": info.get("fallback"), "vectorHits": info.get("vectorHits"), "docs": len(docs),
            "relevance": info.get("relevance") or {}, "chunks": sum(len(d.get("chunks") or []) for d in docs), "ids": [d.get("doc_id") for d in docs], "top5": top}


def main(as_of: str = "2026-11-04") -> int:
    cov, size = coverage()
    items = []
    for ticker, q in QUESTIONS:
        co = db.company(ticker)
        items.append({"question": q, "company": co.get("name"), "keyword": one(co, as_of, q, "off"), "embedding": one(co, as_of, q, "on")})
        print(q, items[-1]["keyword"]["seconds"], items[-1]["embedding"]["seconds"], flush=True)
    k = [i["keyword"] for i in items]
    e = [i["embedding"] for i in items]
    summary = {"questions": len(items), "keywordSeconds": round(sum(x["seconds"] for x in k) / len(k), 2), "embeddingSeconds": round(sum(x["seconds"] for x in e) / len(e), 2),
               "embeddingChunks": round(sum(x["chunks"] for x in e) / len(e), 1), "changedDocs": round(sum(len(set(a["ids"]) - set(b["ids"])) for a, b in zip(e, k)) / len(items), 1),
               "fallbacks": sum(1 for x in e if x["mode"] != "hybrid"),
               "notFound": sum(1 for x in e if x["relevance"].get("notFound")), "checked": sum(1 for x in e if x["relevance"].get("checked")),
               "droppedAvg": round(sum(x["relevance"].get("dropped") or 0 for x in e) / len(e), 1)}
    out = {"asOf": as_of, "ranAt": time.strftime("%Y-%m-%d %H:%M"), "model": rag_hybrid.QUERY_MODEL, "dim": rag_hybrid.EMBED_DIM, "index": "정확 검색(종목·출처·기준일로 거른 뒤 코사인 거리 정렬, HNSW 인덱스 삭제 #69)",
           "vectorShare": rag_hybrid.VECTOR_SHARE, "candidates": rag_hybrid.N_CANDIDATES, "strongSim": rag_hybrid.STRONG_SIM, "dbSize": size, "dbLimit": "800MB", "coverage": cov, "summary": summary, "items": items}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("저장:", OUT, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:2] or [])))
