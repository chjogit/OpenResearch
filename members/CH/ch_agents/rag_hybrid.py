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
import re
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
VECTOR_SHARE = 0.5           # 최종 문서 자리 중 벡터 유사도 순으로 먼저 보장하는 몫(#67). 나머지는 키워드·벡터 합산 점수 순
EVIDENCE_PER_DOC = 2         # 문서마다 근거 청크(번호·유사도·발췌) 최대 개수


def enabled() -> bool:
    return os.getenv("CH_RAG_HYBRID", "on").lower() == "on"      # #67: 기본 켬(에이전트 3·4·6 24회 켬/끔 측정 — 제거 39→26문장, 근거 없는 주장 0→0). 끄려면 CH_RAG_HYBRID=off


def query_text(agent_id: int, co: dict, question: str | None = None) -> str:
    """질의 문장 = (질문) + 종목명 + 관점 이름 + 관점 키워드 상위 5개. 질문이 있으면 앞에 붙여 질문마다 다른 청크를 찾게 한다(#67)."""
    p = rag.PRESETS[agent_id]
    top = sorted(p.terms, key=lambda t: -p.terms[t])[:5]
    base = f"{co.get('name') or co.get('ticker')} {p.name} {' '.join(top)}"
    q = " ".join(str(question or "").split())[:300]
    return f"{q} | {base}" if q else base


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
            "title": rag._clean(r.get("title")), "summary": rag._clean(r.get("summary"), 110), "full": rag._clean(r.get("summary"), 400), "url": r.get("url"),
            "terms": [], "score": 0.0, "doc_id": r["doc_id"]}


def merge_candidates(agent_id: int, raw: dict, co: dict, as_of: str, hits: list[dict], n: int = N_CANDIDATES) -> list[dict]:
    """키워드 점수(0~1 로 정규화)와 벡터 유사도를 합쳐 상위 n개 문서 (#67 합치는 규칙):
    ① 벡터 검색이 독립적으로 찾은 문서 중 유사도 상위 ceil(k_docs × VECTOR_SHARE)개를 **유사도 순으로 먼저** 둔다(키워드 점수에 밀려 빠지지 않게).
    ② 나머지 자리는 0.5×키워드(0~1) + 0.5×유사도 합산 점수 순. ③ 같은 제목·출처별 개수 제한은 그대로.
    각 문서에 origin(벡터·키워드·둘 다), sim, 근거 청크(chunks: 번호·유사도·발췌)를 붙인다."""
    p = rag.PRESETS[agent_id]
    kw = rag.select_docs(raw.get("news"), replace(p, k_docs=n * 3), co, as_of)
    top = max((d["score"] for d in kw), default=0.0) or 1.0
    pool = {d["doc_id"]: {**d, "kw": d["score"] / top, "sim": 0.0, "chunks": []} for d in kw}
    for h in sorted(hits, key=lambda x: -float(x["sim"])):
        if h["source"] not in p.sources:
            continue
        cur = pool.setdefault(h["doc_id"], {**_doc_from_vector(h), "kw": 0.0, "sim": 0.0, "chunks": []})
        if "chunk_id" not in cur or float(h["sim"]) > cur["sim"]:
            cur["sim"], cur["chunk_id"] = float(h["sim"]), h["chunk_id"]
        if len(cur["chunks"]) < EVIDENCE_PER_DOC:
            cur["chunks"].append({"chunkId": h["chunk_id"], "chunkIdx": h.get("chunk_idx"), "sim": round(float(h["sim"]), 3),
                                  "excerpt": rag._clean(h.get("content"), 400) if h.get("content") else ""})
    for d in pool.values():
        d["origin"] = "둘 다" if d["kw"] and d["sim"] else "벡터" if d["sim"] else "키워드"
    ranked = sorted(pool.values(), key=lambda d: (W_KEYWORD * d["kw"] + W_VECTOR * max(d["sim"], 0.0),
                                                  d["published"], str(d["doc_id"])), reverse=True)
    reserve = -(-int(p.k_docs * VECTOR_SHARE * 100) // 100)      # ceil(k_docs × 몫)
    first = sorted((d for d in pool.values() if d["sim"] > 0), key=lambda d: (-d["sim"], str(d["doc_id"])))[:reserve]
    ranked = first + [d for d in ranked if d not in first]
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
        d["score"] = round(W_KEYWORD * d.pop("kw") + W_VECTOR * max(d["sim"], 0.0), 3)
        d["sim"] = round(d["sim"], 3)
        out.append(d)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- 호출 (네트워크·DB 읽기)

def fetch_hybrid(agent_id: int, co: dict, as_of: str, raw: dict, embed=None, run_sql=None, question: str | None = None) -> dict:
    """질의 임베딩 → 벡터 검색. 결과는 bundle['rag']['hybrid'] 에 저장할 dict. 실패는 error 로 기록. question 이 있으면 질의 문장에 포함(#67)."""
    from .asof import cut_future, require_as_of

    as_of = require_as_of(as_of)
    out: dict = {}
    try:
        out["query"] = query_text(agent_id, co, question)
        qv = (embed or embed_query)(out["query"])
        if run_sql is None:
            from . import db
            run_sql = db.q
        vec = "[" + ",".join(f"{x:.6f}" for x in qv) + "]"
        base = {**rag.params(agent_id, co, as_of), "qv": vec}
        public = [s for s in base["sources"] if s not in PRIVATE_SOURCES]
        private = [s for s in base["sources"] if s in PRIVATE_SOURCES]
        # 개인 작성 글(유튜브 댓글 임베딩, #69)이 후보 40건을 채워 뉴스·공시가 밀리지 않게 출처 묶음별로 따로 검색(#70)
        rows = run_sql(VECTOR_SQL, {**base, "sources": public, "n": N_CANDIDATES * 2}) if public else []
        if private:
            rows = list(rows) + list(run_sql(VECTOR_SQL, {**base, "sources": private, "n": PRIVATE_CANDIDATES}))
        out["hits"], _ = cut_future(rows, as_of)   # E3
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    if not out["hits"]:
        return {"error": "청크 없음"}
    return out


def select_hybrid(agent_id: int, raw: dict, co: dict, as_of: str, keep=None) -> tuple[list[dict], dict]:
    """(문서 목록, status). hybrid 결과가 없거나 실패면 rag.select 와 같은 결과 + status['fallback'] 에 이유.
    keep(문서 목록) → 남길 문서(관련도 점검, #70)는 후보를 k 개로 자르기 **전에** 적용한다(자른 뒤에 걸면 관련 기사가 밀려난 채 비게 됨)."""
    raw = raw or {}
    h = raw.get("hybrid")
    if not h or h.get("error"):
        why = (h or {}).get("error") or "하이브리드 결과 없음"
        return rag.select(agent_id, raw, co, as_of), {"mode": "keyword", "fallback": why}
    p = rag.PRESETS[agent_id]
    cands = merge_candidates(agent_id, raw, co, as_of, h["hits"], n=N_CANDIDATES * 3 if keep else N_CANDIDATES)   # 거를 땐 풀을 넓게
    discs = _disclosures_for(p, raw, h.get("query"))
    if keep:
        pool = keep(cands + discs)
        cands, discs = [d for d in pool if d.get("kind") != "공시"], [d for d in pool if d.get("kind") == "공시"]
    return cands[: p.k_docs] + discs, {"mode": "hybrid", "fallback": None}


# ---------------------------------------------------------------- 질문 관련도 점검 (#70)
# 유사도 하나로는 가를 수 없음: 질의에 종목명이 섞여 '관련 기사 있는 현대차 노조 파업'(0.611)이 '관련 기사 없는 삼성전자 노조 파업'(0.643)보다 낮다.
# 그래서 ① 질문 핵심어(종목명·일반어 제외)가 제목·근거 청크·요약에 있거나 ② 유사도가 STRONG_SIM 이상이면 관련 문서로 본다. 핵심어가 없는 질문은 점검하지 않는다.
STRONG_SIM = 0.68
PRIVATE_SOURCES = ("naver_blog", "naver_cafe", "youtube_comment")
PRIVATE_CANDIDATES = 10      # 개인 작성 글 벡터 후보 수(검색 후보 전용, 원문 비공개)
GENERIC_ROOTS = ("최근", "소식", "뉴스", "기사", "있", "이슈", "분위기", "관련", "얼마", "민감", "어때", "어떤", "알려", "영향", "흐름", "지금", "사도", "될까", "팔아",
                 "전망", "계획", "가능", "예정", "방향", "할까", "해야", "주가", "투자", "매수", "매도", "현황", "상황", "요즘", "오늘", "동향", "정보", "내용", "대해", "대한", "어떻게", "무엇", "뭐야", "보여", "말해", "변화",
                 # 서술어·조건어·형용사는 주제가 아니다(#75): '오르면' '내리면' '중요한' '공시(질문 형식)' 등
                 "오르", "오른", "올라", "올랐", "내리", "내린", "내려", "떨어", "하락하", "상승하", "중요", "생기", "생긴", "일어", "달라", "바뀌", "바뀐", "공시", "있어", "있나", "있는", "없어", "되면", "하면", "이면")
PARTICLES = "은는이가을를에의도로과와만"


def topic_terms(question: str | None, names: set[str] | frozenset = frozenset()) -> list[str]:
    """질문에서 종목명·일반어를 빼고 남은 핵심어(조사 한 글자 제거). 예: '현대차 노조 파업 소식 있어?' → ['노조', '파업']."""
    out = []
    for t in re.findall(r"[0-9A-Za-z가-힣]{2,}", question or ""):
        tl = t.lower()
        if t in names or any(n and (tl.startswith(n.lower()) or n.lower().startswith(tl)) for n in names if len(n) >= 2):
            continue
        if any(t.startswith(g) for g in GENERIC_ROOTS):
            continue
        if len(t) >= 3 and t[-1] in PARTICLES:
            t = t[:-1]
        if len(t) >= 3 and t.endswith(("으면", "라면", "다면", "하면", "되면", "오면")):      # 조건 어미 (예: '환율이 오르면' 의 '오르면')
            continue
        if t not in out:
            out.append(t)
    return out


def relevance_filter(docs: list[dict], question: str | None, names: set[str] | frozenset = frozenset()) -> tuple[list[dict], dict]:
    """(남긴 문서, 점검 기록). 핵심어가 없는 질문(일반 질문)이면 그대로 둔다. 기준 미만 문서는 목록에서 뺀다(건수만 기록)."""
    terms = topic_terms(question, names)
    info = {"terms": terms, "strongSim": STRONG_SIM, "checked": bool(terms), "dropped": 0, "notFound": False}
    if not terms:
        return docs, info
    kept = []
    for d in docs:
        text = " ".join([str(d.get("title") or ""), str(d.get("summary") or "")] + [str(c.get("excerpt") or "") for c in d.get("chunks") or []])
        if float(d.get("sim") or 0) >= STRONG_SIM or any(t in text for t in terms):
            kept.append(d)
    info["dropped"] = len(docs) - len(kept)
    info["notFound"] = not kept
    return kept, info


DISCLOSURE_WORD_RE = re.compile("공시|풍문|조회|해명|전환|행사|지분|보고서")


def _disclosures_for(p, raw: dict, query: str | None) -> list[dict]:
    """공시는 임베딩이 없고 이벤트 유형으로만 골라져 질문과 무관하게 같은 건이 나온다(#67 QA). 그래서 질문 기반 문서 뒤에 두고,
    질문에 공시 관련 단어가 없으면 1건만 둔다. 질문이 없으면(질의에 ' | ' 가 없으면) 예전처럼 전부."""
    disc = rag.select_disclosures(raw.get("disclosures"), p)
    question = (query or "").split(" | ")[0] if " | " in (query or "") else ""
    return disc if not question or DISCLOSURE_WORD_RE.search(question) else disc[:1]


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
    from .asof import cut_future, require_as_of

    as_of = require_as_of(as_of)
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
    hits, _ = cut_future(hits, as_of)   # E3: 기준일 다음 날 이후 청크 제거
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
