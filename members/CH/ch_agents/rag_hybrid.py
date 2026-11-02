"""하이브리드 검색(R3) + 청크 근거·리랭킹(R4-2): 키워드 점수에 벡터 유사도를 더해 상위 K 를 고릅니다.

리랭킹 결정 변경(11/2 사용자 지시서, 10-30 '리랭킹 쓰지 않음'을 대체): CH_RAG_RERANK=on 이면 후보를 문서가 아닌
청크 단위(문서당 최대 2개, 키워드 점수는 문서→청크 상속)로 모으고, 합산 상위 20 청크를 Cohere Rerank 로 다시 매깁니다
(rerank.py). 기본은 꺼짐(CH_RAG_RERANK=off)이며, 꺼져 있으면 청크 검색·리랭킹을 하지 않아 지금 결과와 완전히 같습니다.

- 켜기: 환경변수 CH_RAG_HYBRID=on (기본 꺼짐 → rag.py 의 키워드 RAG 와 완전히 같은 결과, R7).
- 질의 임베딩은 DB 가 아니라 Upstage API 입니다. 키는 UPSTAGE_API_KEY, 로그에 남기지 않음.
- 네트워크 호출(fetch_hybrid)과 순수 선별(select_hybrid)을 나눠, 호출 결과를 스냅샷(bundle['rag']['hybrid'])에
  저장하면 같은 입력으로 같은 결과가 나옵니다.
- 임베딩이 실패하거나 청크가 없으면 rag.select 결과로 대체하고, 이유를 status 에 남깁니다 (에이전트는 멈추지 않음).
"""
from __future__ import annotations

import os
from dataclasses import replace
from difflib import SequenceMatcher

import time

from . import rag, rerank

N_CANDIDATES = 20            # 후보 상위 N
W_KEYWORD, W_VECTOR = 0.5, 0.5
UPSTAGE_EMBED_URL = "https://api.upstage.ai/v1/embeddings"
QUERY_MODEL = os.getenv("UPSTAGE_QUERY_MODEL", "solar-embedding-2-passage")  # 적재와 같은 passage 모델 (1024차원)
EMBED_DIM = 1024

VECTOR_SQL = """
SELECT c.chunk_id, c.doc_id, c.chunk_idx, left(c.content, 400) AS content,
       d.source, d.title, left(coalesce(d.summary, ''), 240) AS summary,
       d.published_at::date AS published, d.published_at AS published_at, d.url,
       1 - (c.embedding <=> %(qv)s::halfvec) AS sim
FROM rag.chunk c JOIN rag.document d USING (doc_id)
WHERE d.company_id = %(cid)s AND d.source = ANY(%(sources)s::text[])
  AND d.published_at <= %(as_of)s::date
  AND d.published_at > %(as_of)s::date - CASE WHEN d.source = ANY(%(long_src)s::text[]) THEN %(long_days)s::int
                                              ELSE %(days)s::int END
ORDER BY c.embedding <=> %(qv)s::halfvec
LIMIT %(n)s
"""

# 키워드로 찾은 문서의 청크 (R4-2: 키워드 점수를 청크에 상속하려면 키워드 문서의 청크도 후보여야 함). 읽기 전용
DOC_CHUNK_SQL = """
SELECT c.chunk_id, c.doc_id, c.chunk_idx, left(c.content, 400) AS content,
       d.source, d.title, left(coalesce(d.summary, ''), 240) AS summary,
       d.published_at::date AS published, d.published_at AS published_at, d.url,
       1 - (c.embedding <=> %(qv)s::halfvec) AS sim
FROM rag.chunk c JOIN rag.document d USING (doc_id)
WHERE d.company_id = %(cid)s AND d.source = ANY(%(sources)s::text[]) AND c.doc_id = ANY(%(ids)s::bigint[])
ORDER BY c.doc_id, c.chunk_idx
"""
PER_DOC = 2                  # 문서당 최대 청크 수


def enabled() -> bool:
    return os.getenv("CH_RAG_HYBRID", "off").lower() == "on"


def query_text(agent_id: int, co: dict) -> str:
    p = rag.PRESETS[agent_id]
    top = sorted(p.terms, key=lambda t: -p.terms[t])[:5]
    return f"{co.get('name') or co.get('ticker')} {p.name} {' '.join(top)}"


def embed_query(text: str, session=None) -> list[float]:
    key = os.getenv("UPSTAGE_API_KEY")
    if not key:
        raise RuntimeError("UPSTAGE_API_KEY 가 비어 있습니다")
    if session is None:
        import requests as session  # noqa: N812
    r = session.post(UPSTAGE_EMBED_URL, json={"model": QUERY_MODEL, "input": [text]},
                     headers={"Authorization": f"Bearer {key}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"임베딩 HTTP {r.status_code}")
    vec = [float(x) for x in r.json()["data"][0]["embedding"]]
    if len(vec) != EMBED_DIM:
        raise RuntimeError(f"질의 임베딩 차원 {len(vec)} != {EMBED_DIM}")
    return vec


# ---------------------------------------------------------------- 후보 병합 (순수 함수)

def _doc_from_vector(r: dict) -> dict:
    return {"kind": rag.SOURCE_LABEL.get(r["source"], r["source"]), "source": r["source"],
            "published": str(r.get("published"))[:10], "published_at": str(r.get("published_at") or r.get("published")),
            "title": rag._clean(r.get("title")), "summary": rag._clean(r.get("summary"), 110), "url": r.get("url"),
            "terms": [], "score": 0.0, "doc_id": r["doc_id"]}


def merge_candidates(agent_id: int, raw: dict, co: dict, as_of: str, hits: list[dict], n: int = N_CANDIDATES) -> list[dict]:
    """키워드 점수(0~1 로 정규화)와 벡터 유사도를 가중 합산해 상위 n개 문서. 벡터로 찾은 문서에 chunk_id 를 붙임."""
    p = rag.PRESETS[agent_id]
    kw = rag.select_docs(raw.get("news"), replace(p, k_docs=n * 3), co, as_of)
    top = max((d["score"] for d in kw), default=0.0) or 1.0
    pool = {d["doc_id"]: {**d, "kw": d["score"] / top, "sim": 0.0} for d in kw}
    for h in hits:
        if h["source"] not in p.sources:
            continue
        cur = pool.setdefault(h["doc_id"], {**_doc_from_vector(h), "kw": 0.0, "sim": 0.0})
        if "chunk_id" not in cur or float(h["sim"]) > cur["sim"]:
            cur["sim"], cur["chunk_id"] = float(h["sim"]), h["chunk_id"]
    ranked = sorted(pool.values(), key=lambda d: (W_KEYWORD * d["kw"] + W_VECTOR * max(d["sim"], 0.0),
                                                  d["published"], str(d["doc_id"])), reverse=True)
    out, norms, per_src = [], [], {}
    for d in ranked:
        nt = rag._norm_title(d["title"])
        src = d["source"]
        cap = p.per_source.get(src)
        if not nt or any(nt == m or SequenceMatcher(None, nt, m).ratio() >= rag.DEDUP_RATIO for m in norms):
            continue
        if cap is not None and per_src.get(src, 0) >= cap:
            continue
        norms.append(nt)
        per_src[src] = per_src.get(src, 0) + 1
        d["score"] = round(W_KEYWORD * d.pop("kw") + W_VECTOR * max(d.pop("sim"), 0.0), 3)
        out.append(d)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- 호출 (네트워크·DB 읽기)

def fetch_hybrid(agent_id: int, co: dict, as_of: str, raw: dict, embed=None, run_sql=None) -> dict:
    """질의 임베딩 → 벡터 검색. 결과는 bundle['rag']['hybrid'] 에 저장할 dict. 실패는 error 로 기록."""
    out: dict = {}
    try:
        qv = (embed or embed_query)(query_text(agent_id, co))
        if run_sql is None:
            from . import db
            run_sql = db.q
        vec = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
        out["hits"] = run_sql(VECTOR_SQL, {**rag.params(agent_id, co, as_of), "qv": vec, "n": N_CANDIDATES * 2})
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    if not out["hits"]:
        return {"error": "청크 없음"}
    return out


def select_hybrid(agent_id: int, raw: dict, co: dict, as_of: str) -> tuple[list[dict], dict]:
    """(문서 목록, status). hybrid 결과가 없거나 실패면 rag.select 와 같은 결과 + status['fallback'] 에 이유."""
    raw = raw or {}
    h = raw.get("hybrid")
    if not h or h.get("error"):
        why = (h or {}).get("error") or "하이브리드 결과 없음"
        return rag.select(agent_id, raw, co, as_of), {"mode": "keyword", "fallback": why}
    p = rag.PRESETS[agent_id]
    cands = merge_candidates(agent_id, raw, co, as_of, h["hits"])
    return rag.select_disclosures(raw.get("disclosures"), p) + cands[: p.k_docs], {"mode": "hybrid", "fallback": None}


# ---------------------------------------------------------------- 청크 근거·리랭킹 (R4-2, CH_RAG_RERANK=on 일 때만)

def _main_keyword_docs(agent_id: int, raw: dict, co: dict, as_of: str, n: int) -> list[dict]:
    """키워드 점수 문서 (메인 DB 문서만). 블로그·카페는 kic-opinion 에 있어 doc_id 가 메인 청크와 겹칠 수 있으므로 뺌."""
    from .db import OPINION_SOURCES

    p = rag.PRESETS[agent_id]
    return [d for d in rag.select_docs(raw.get("news"), replace(p, k_docs=n * 3), co, as_of)
            if d["source"] not in OPINION_SOURCES]


def chunk_candidates(agent_id: int, raw: dict, co: dict, as_of: str, hits: list[dict], n: int = N_CANDIDATES) -> list[dict]:
    """청크 단위 후보 상위 n개 (순수 함수).

    점수 = (W_KEYWORD × 문서 키워드 점수(0~1, 문서→청크 상속) + W_VECTOR × 청크 유사도) × 관점 출처 가중치
    (rag.PRESETS sources: 에이전트 1 은 사업보고서, 에이전트 3 은 뉴스·영문 뉴스가 앞). 문서당 최대 PER_DOC 개,
    다른 문서끼리 거의 같은 제목은 하나만, 출처별 개수 제한은 문서 수로 셈."""
    p = rag.PRESETS[agent_id]
    kw = {d["doc_id"]: d for d in _main_keyword_docs(agent_id, raw, co, as_of, n)}
    top = max((d["score"] for d in kw.values()), default=0.0) or 1.0
    rows, seen = [], set()
    for h in hits:
        if h["source"] not in p.sources or h["chunk_id"] in seen:
            continue
        seen.add(h["chunk_id"])
        base = kw.get(h["doc_id"])
        doc = {k: v for k, v in (base or _doc_from_vector(h)).items() if k != "score"}
        k_score = base["score"] / top if base else 0.0
        score = (W_KEYWORD * k_score + W_VECTOR * max(float(h["sim"]), 0.0)) * p.sources[h["source"]]
        rows.append({**doc, "score": round(score, 4), "chunk_id": h["chunk_id"], "chunk_idx": h.get("chunk_idx"),
                     "excerpt": rag._clean(h.get("content"), 400)})
    rows.sort(key=lambda d: (-d["score"], -int(str(d["published"]).replace("-", "") or 0), -int(d["doc_id"]),
                             d.get("chunk_idx") or 0, d["chunk_id"]))
    out, per_doc, norms, per_src = [], {}, {}, {}
    for d in rows:
        did, src = d["doc_id"], d["source"]
        if did not in per_doc:   # 새 문서: 제목 중복·출처 제한 검사
            nt = rag._norm_title(d["title"])
            cap = p.per_source.get(src)
            if not nt or any(nt == m or SequenceMatcher(None, nt, m).ratio() >= rag.DEDUP_RATIO for m in norms.values()):
                continue
            if cap is not None and per_src.get(src, 0) >= cap:
                continue
            norms[did] = nt
            per_src[src] = per_src.get(src, 0) + 1
            per_doc[did] = 0
        if per_doc[did] >= PER_DOC:
            continue
        per_doc[did] += 1
        out.append(d)
        if len(out) >= n:
            break
    return out


def fetch_chunks(agent_id: int, co: dict, as_of: str, raw: dict, embed=None, run_sql=None) -> dict:
    """질의 임베딩 → 청크 벡터 검색 + 키워드 문서의 청크. 결과는 bundle['rag']['chunks']. 실패는 error 로 기록."""
    try:
        qv = (embed or embed_query)(query_text(agent_id, co))
        if run_sql is None:
            from . import db
            run_sql = db.q
        vec = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
        prm = {**rag.params(agent_id, co, as_of), "qv": vec}
        hits = list(run_sql(VECTOR_SQL, {**prm, "n": N_CANDIDATES * 2}) or [])
        ids = [d["doc_id"] for d in _main_keyword_docs(agent_id, raw or {}, co, as_of, N_CANDIDATES)]
        if ids:
            hits += run_sql(DOC_CHUNK_SQL, {**prm, "ids": ids}) or []
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    if not hits:
        return {"error": "청크 없음"}
    uniq = {h["chunk_id"]: h for h in hits}
    return {"hits": sorted(uniq.values(), key=lambda h: h["chunk_id"])}


def fetch_rerank(agent_id: int, co: dict, as_of: str, raw: dict, hits: list[dict], reranker=None) -> dict:
    """합산 상위 20 청크를 리랭커로 매긴 점수. 결과는 bundle['rag']['rerank'] (같은 스냅샷 = 같은 순위).
    실패·한도 초과·키 없음이면 error 에 이유를 남기고 점수는 없음 → select_chunks 가 합산 순위를 씀."""
    rr = reranker or rerank.get_reranker()
    query = query_text(agent_id, co)
    cands = chunk_candidates(agent_id, raw, co, as_of, hits)[: rerank.TOP_N]
    info: dict = {"provider": rr.name, "model": rr.model, "query": query, "n": len(cands), "calls": 0}
    if not cands:
        return {**info, "error": "후보 청크 없음"}
    before = rerank.CALLS["total"]
    t0 = time.perf_counter()
    try:
        scores = rr.score(query, [rerank.doc_text(d) for d in cands])
        if len(scores) != len(cands):
            raise RuntimeError(f"점수 수 {len(scores)} != 후보 {len(cands)}")
    except Exception as e:  # noqa: BLE001  키 없음·한도·네트워크·미구현 모두 합산 순위로 대체
        return {**info, "calls": rerank.CALLS["total"] - before, "error": f"{type(e).__name__}: {e}"}
    return {**info, "calls": rerank.CALLS["total"] - before, "seconds": round(time.perf_counter() - t0, 2),
            "scores": {str(d["chunk_id"]): round(float(s), 6) for d, s in zip(cands, scores)}}


def select_chunks(agent_id: int, raw: dict, co: dict, as_of: str) -> tuple[list[dict], dict]:
    """(문서 목록, status). 청크 결과가 없거나 실패면 rag.select 와 같은 결과 + fallback 이유.
    리랭킹 점수가 있으면 그 순서(동점은 합산 순위), 없으면 합산 순위 + rerank_fallback 이유."""
    raw = raw or {}
    c = raw.get("chunks")
    rr = raw.get("rerank") or {}
    if not c or c.get("error"):
        why = (c or {}).get("error") or "청크 결과 없음"
        return rag.select(agent_id, raw, co, as_of), {"mode": "keyword", "fallback": why, "calls": rr.get("calls", 0)}
    p = rag.PRESETS[agent_id]
    cands = chunk_candidates(agent_id, raw, co, as_of, c["hits"])
    status: dict = {"mode": "chunk", "fallback": None, "calls": rr.get("calls", 0)}
    scores = rr.get("scores")
    if scores:
        pos = {d["chunk_id"]: i for i, d in enumerate(cands)}
        scored = [d for d in cands if str(d["chunk_id"]) in scores]
        rest = [d for d in cands if str(d["chunk_id"]) not in scores]
        order = sorted(scored, key=lambda d: (-scores[str(d["chunk_id"])], pos[d["chunk_id"]]))
        for d in order:
            d["rerank_score"] = scores[str(d["chunk_id"])]
        status["rerank"] = {"provider": rr.get("provider"), "model": rr.get("model"), "seconds": rr.get("seconds"),
                            "before": [d["chunk_id"] for d in scored], "after": [d["chunk_id"] for d in order]}
        cands = order + rest
    else:
        status["rerank_fallback"] = rr.get("error") or "리랭킹 결과 없음"   # 합산 점수 순서 그대로
    return rag.select_disclosures(raw.get("disclosures"), p) + cands[: p.k_docs], status
