"""청크 리랭킹 (R4-2, 11/2 사용자 지시서): 하이브리드 합산 점수 상위 20 청크를 질의와의 관련도로 다시 매깁니다.

- 켜기: 환경변수 CH_RAG_RERANK=on (기본 꺼짐 → 청크 근거·리랭킹 모두 쓰지 않고 지금 결과와 완전히 같음).
- 기본 구현은 Cohere Rerank v2 API (POST https://api.cohere.com/v2/rerank, docs.cohere.com/reference/rerank).
  모델은 CH_RERANK_MODEL (기본 rerank-v5.0-pro: 다국어·한국어 지원, docs.cohere.com/docs/rerank 11/2 확인).
  키는 COHERE_API_KEY (.env), 로그·출력에 남기지 않음. 트라이얼 키는 월 1,000회이므로 호출 수를 기록합니다.
- 질의 = 관점 프리셋 + 종목명 (rag_hybrid.query_text), 문서 = 청크 제목 + 발췌(최대 400자).
- 실패·한도 초과(HTTP 429)·키 없음이면 예외 → 호출 쪽(rag_hybrid.fetch_rerank)이 이유를 기록하고 합산 순위를 씁니다.
- Solar 점수 방식은 대체 구현 자리만 둡니다(인터페이스만, 호출하면 NotImplementedError → 합산 순위 대체).
"""
from __future__ import annotations

import os
from typing import Protocol

TOP_N = 20                                  # 리랭커에 넣는 합산 점수 상위 청크 수
DEFAULT_MODEL = "rerank-v5.0-pro"
COHERE_URL = "https://api.cohere.com/v2/rerank"
MAX_TOKENS_PER_DOC = 512                    # 제목+발췌 400자면 충분 (과금 단위 절약)

CALLS = {"total": 0}                        # 이 프로세스에서 실제로 보낸 리랭킹 요청 수 (실패 응답 포함)


def enabled() -> bool:
    return os.getenv("CH_RAG_RERANK", "off").lower() == "on"


def model_name() -> str:
    return os.getenv("CH_RERANK_MODEL", DEFAULT_MODEL)


def doc_text(d: dict) -> str:
    return f"{d.get('title') or ''}\n{d.get('excerpt') or d.get('summary') or ''}".strip()


class Reranker(Protocol):
    name: str
    model: str

    def score(self, query: str, texts: list[str]) -> list[float]:
        """texts 와 같은 순서의 관련도 점수."""
        ...


class CohereReranker:
    name = "cohere"

    def __init__(self, model: str | None = None, session=None):
        self.model = model or model_name()
        self.session = session

    def score(self, query: str, texts: list[str]) -> list[float]:
        key = os.getenv("COHERE_API_KEY")
        if not key:
            raise RuntimeError("COHERE_API_KEY 없음")
        if not texts:
            return []
        session = self.session
        if session is None:
            import requests as session  # noqa: N812
        CALLS["total"] += 1
        r = session.post(COHERE_URL, json={"model": self.model, "query": query, "documents": texts,
                                           "top_n": len(texts), "max_tokens_per_doc": MAX_TOKENS_PER_DOC},
                         headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=30)
        if r.status_code == 429:
            raise RuntimeError("한도 초과 (HTTP 429)")
        if r.status_code != 200:
            raise RuntimeError(f"리랭킹 HTTP {r.status_code}")
        scores: list[float | None] = [None] * len(texts)
        for x in r.json().get("results") or []:
            scores[int(x["index"])] = float(x["relevance_score"])
        if any(s is None for s in scores):
            raise RuntimeError("리랭킹 응답에 빠진 문서가 있음")
        return [float(s) for s in scores]  # type: ignore[arg-type]


class SolarReranker:
    """대체 구현 자리 (Solar LLM 으로 관련도 점수 매기기). 인터페이스만 두고 구현하지 않습니다."""
    name = "solar"

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("UPSTAGE_MODEL_NAME", "solar-pro4")

    def score(self, query: str, texts: list[str]) -> list[float]:
        raise NotImplementedError("Solar 점수 방식은 인터페이스만 있음")


PROVIDERS = {"cohere": CohereReranker, "solar": SolarReranker}


def get_reranker() -> Reranker:
    """CH_RERANK_PROVIDER (기본 cohere)."""
    return PROVIDERS.get(os.getenv("CH_RERANK_PROVIDER", "cohere").lower(), CohereReranker)()
