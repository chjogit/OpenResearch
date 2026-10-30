"""하이브리드 검색(R3): 키워드 점수에 벡터 유사도를 더해 상위 K 를 고릅니다. 리랭킹은 쓰지 않습니다(사용자 결정 10-30).

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

from . import rag

N_CANDIDATES = 20            # 후보 상위 N
W_KEYWORD, W_VECTOR = 0.5, 0.5
UPSTAGE_EMBED_URL = "https://api.upstage.ai/v1/embeddings"
QUERY_MODEL = os.getenv("UPSTAGE_QUERY_MODEL", "solar-embedding-2-passage")  # 적재와 같은 passage 모델 (1024차원)
EMBED_DIM = 1024

VECTOR_SQL = """
SELECT c.chunk_id, c.doc_id, d.source, d.title, left(coalesce(d.summary, ''), 240) AS summary,
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
