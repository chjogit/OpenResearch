"""R4-2 청크 근거·Cohere 리랭킹 테스트: 모의 임베딩·리랭커·LLM, DB·네트워크 없음."""
import copy
import json

from ch_agents import agents, contract, prompts, rag, rag_hybrid, rerank
from ch_agents.agents import build_agent_data
from ch_agents.llm import build_messages, run_agent
from conftest import AS_OF, CO, FakeLLM
from test_compute import _sent_bundle
from test_rag import _raw


def _chunk(chunk_id, doc_id, title, sim, content="", idx=0, source="naver_news", published="2026-10-25"):
    return {"chunk_id": chunk_id, "doc_id": doc_id, "chunk_idx": idx, "content": content, "source": source,
            "title": title, "summary": "", "published": published, "published_at": published,
            "url": f"https://v.example/{doc_id}", "sim": sim}


# 문서 1(키워드 1위)의 청크 3개, 벡터로만 찾은 문서 50, 영문 뉴스 10(키워드 문서)
HITS = [
    _chunk(901, 1, "삼성전자 외국인 순매수 1위…수급 개선", 0.50, "외국인이 연속 순매수하며 수급이 개선됐다.", 0),
    _chunk(902, 1, "삼성전자 외국인 순매수 1위…수급 개선", 0.45, "기관은 차익실현에 나섰다.", 1),
    _chunk(903, 1, "삼성전자 외국인 순매수 1위…수급 개선", 0.40, "개인은 매도 우위였다.", 2),
    _chunk(904, 50, "삼성전자 자금 흐름 변화 점검", 0.90, "외국인 보유 비중이 1년 중 최고인 52.37 수준이라는 분석.", 0),
    _chunk(905, 10, "Samsung foreign investors sell-off", 0.30, "Foreign investors sold shares.", 0,
           source="finnhub_news"),
]


class FakeReranker:
    name, model = "fake", "fake-rerank"

    def __init__(self, scores=None, exc=None):
        self.scores, self.exc, self.seen = scores, exc, None

    def score(self, query, texts):
        self.seen = (query, texts)
        if self.exc:
            raise self.exc
        rerank.CALLS["total"] += 1
        return self.scores(texts) if callable(self.scores) else list(self.scores)


def _chunk_raw(scores=None, exc=None):
    raw = _raw()
    raw["chunks"] = {"hits": copy.deepcopy(HITS)}
    raw["rerank"] = rag_hybrid.fetch_rerank(3, CO, AS_OF, raw, raw["chunks"]["hits"], reranker=FakeReranker(scores, exc))
    return raw


def _reverse(texts):   # 합산 순위를 거꾸로 매기는 리랭커
    return [float(i) for i in range(len(texts))]


# ---------------------------------------------------------------- 꺼짐 = 지금과 같음

def test_rerank_off_by_default_bundle_and_prompt_unchanged(monkeypatch):
    monkeypatch.setattr(agents.db, "bundle", lambda sql, p: {})
    monkeypatch.setattr(agents.rag, "fetch", lambda a, co, as_of: {"news": [], "disclosures": []})
    called = []
    monkeypatch.setattr(agents.rag_hybrid, "fetch_chunks", lambda *a, **k: called.append(1) or {"error": "x"})
    for env in (None, "off", "OFF"):
        if env is None:
            monkeypatch.delenv("CH_RAG_RERANK", raising=False)
        else:
            monkeypatch.setenv("CH_RAG_RERANK", env)
        r = agents.fetch_bundle(3, CO, AS_OF)["rag"]
        assert "chunks" not in r and "rerank" not in r
    assert called == []
    monkeypatch.setenv("CH_RAG_RERANK", "on")
    r = agents.fetch_bundle(3, CO, AS_OF)["rag"]
    assert called == [1] and r["chunks"] == {"error": "x"} and r["rerank"]["error"] == "청크 없음"


def test_rerank_off_keeps_existing_docs_prompt_and_output():
    b = _sent_bundle()
    b["rag"] = _raw()
    d = build_agent_data(3, CO, b, AS_OF)
    assert d.docs == rag.select(3, _raw(), CO, AS_OF) and "rag_chunks" not in d.extra
    system, user = build_messages(d)
    assert "[근거 청크" not in system + user and prompts.CHUNK_RUNTIME_RULE not in system
    assert "[참고 문서] (DB에서 이 관점으로 검색한" in user and "발췌:" not in user
    res = {"핵심진단": "수급 확인.", "자체점수": 5, "주장": [{"문장": "외국인 보도가 있다.", "구분": "해석", "근거": ["D1"]}]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    assert "rag_chunks" not in out
    assert all("chunkIds" not in c for c in out["contract"]["claims"])
    assert all("chunkId" not in c for c in out["result"]["주장"])


# ---------------------------------------------------------------- 청크 후보

def test_chunk_candidates_per_doc_cap_keyword_inheritance_and_source_weight():
    cands = rag_hybrid.chunk_candidates(3, _raw(), CO, AS_OF, HITS)
    ids = [d["chunk_id"] for d in cands]
    assert 903 not in ids and {901, 902} <= set(ids)                       # 문서당 최대 2개
    by = {d["chunk_id"]: d for d in cands}
    assert by[901]["score"] > by[904]["score"]                              # 키워드 1위 문서 점수 상속
    assert by[901]["excerpt"].startswith("외국인이") and by[901]["chunk_idx"] == 0
    assert by[905]["score"] < by[901]["score"]                              # 영문 뉴스 가중치 0.9
    assert all(len(d["excerpt"]) <= 400 for d in cands)
    long = [_chunk(990, 60, "삼성전자 수급 장문", 0.5, "가" * 900)]
    assert len(rag_hybrid.chunk_candidates(3, _raw(), CO, AS_OF, long)[0]["excerpt"]) <= 400


def test_opinion_doc_ids_are_not_inherited_by_main_chunks():
    # 블로그 doc_id 6 은 kic-opinion 문서. 같은 번호의 메인 청크가 블로그 키워드 점수를 물려받으면 안 됨
    hit = [_chunk(906, 6, "다른 메인 뉴스", 0.2)]
    d = rag_hybrid.chunk_candidates(3, _raw(), CO, AS_OF, hit)[0]
    assert d["score"] == round(0.5 * 0.2 * 1.0, 4) and d["title"] == "다른 메인 뉴스"


def test_fetch_chunks_reads_vector_and_keyword_doc_chunks_read_only():
    seen = []

    def run_sql(sql, p):
        seen.append((sql, p))
        return HITS[:2] if sql is rag_hybrid.VECTOR_SQL else HITS[1:3]
    out = rag_hybrid.fetch_chunks(3, CO, AS_OF, _raw(), embed=lambda t: [0.1] * 1024, run_sql=run_sql)
    assert [h["chunk_id"] for h in out["hits"]] == [901, 902, 903]          # chunk_id 중복 제거·정렬
    assert seen[1][0] is rag_hybrid.DOC_CHUNK_SQL and 1 in seen[1][1]["ids"] and 6 not in seen[1][1]["ids"]
    for sql in (rag_hybrid.VECTOR_SQL, rag_hybrid.DOC_CHUNK_SQL):
        assert "c.content" in sql and "c.chunk_idx" in sql and "INSERT" not in sql.upper() and "UPDATE" not in sql.upper()
    assert rag_hybrid.fetch_chunks(3, CO, AS_OF, {}, embed=lambda t: [0.1] * 1024, run_sql=lambda s, p: [])["error"] == "청크 없음"


# ---------------------------------------------------------------- 리랭킹

def test_rerank_reorders_and_same_snapshot_gives_same_order():
    raw = _chunk_raw(_reverse)
    assert raw["rerank"]["calls"] == 1 and raw["rerank"]["model"] == "fake-rerank" and "error" not in raw["rerank"]
    docs1, st1 = rag_hybrid.select_chunks(3, raw, CO, AS_OF)
    assert st1["mode"] == "chunk" and st1["rerank"]["after"] == st1["rerank"]["before"][::-1]
    snap = json.loads(json.dumps(raw, ensure_ascii=False))                  # 스냅샷 저장 → 다시 읽기
    docs2, st2 = rag_hybrid.select_chunks(3, snap, CO, AS_OF)
    assert [d.get("chunk_id") for d in docs1] == [d.get("chunk_id") for d in docs2] and st1 == st2
    news = [d for d in docs1 if d["kind"] != "공시"]
    assert news[0]["rerank_score"] >= news[-1]["rerank_score"]


def test_rerank_failure_falls_back_to_combined_order_with_reason():
    base = rag_hybrid.chunk_candidates(3, _raw(), CO, AS_OF, HITS)
    for exc in (RuntimeError("한도 초과 (HTTP 429)"), NotImplementedError("Solar"), RuntimeError("COHERE_API_KEY 없음")):
        raw = _chunk_raw(exc=exc)
        assert raw["rerank"]["error"] and "scores" not in raw["rerank"]
        docs, st = rag_hybrid.select_chunks(3, raw, CO, AS_OF)
        assert st["mode"] == "chunk" and str(exc) in st["rerank_fallback"]
        assert [d["chunk_id"] for d in docs if d.get("chunk_id")] == [d["chunk_id"] for d in base][: rag.PRESETS[3].k_docs]
    raw = _raw()
    raw["chunks"] = {"error": "청크 없음"}
    docs, st = rag_hybrid.select_chunks(3, raw, CO, AS_OF)
    assert docs == rag.select(3, _raw(), CO, AS_OF) and st["mode"] == "keyword" and st["fallback"] == "청크 없음"


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body or {}

    def json(self):
        return self._b


class _Sess:
    def __init__(self, resp):
        self.resp, self.sent = resp, None

    def post(self, url, json=None, headers=None, timeout=None):
        self.sent = (url, json, headers)
        return self.resp


def test_cohere_reranker_request_and_errors(monkeypatch):
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    s = _Sess(_Resp(200))
    before = rerank.CALLS["total"]
    try:
        rerank.CohereReranker(session=s).score("q", ["a"])
        raise AssertionError("키 없음 오류가 나야 함")
    except RuntimeError as e:
        assert "COHERE_API_KEY" in str(e) and s.sent is None and rerank.CALLS["total"] == before   # 호출 안 함
    monkeypatch.setenv("COHERE_API_KEY", "test-key")
    monkeypatch.delenv("CH_RERANK_MODEL", raising=False)
    s = _Sess(_Resp(200, {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]}))
    assert rerank.CohereReranker(session=s).score("삼성전자 투자심리", ["a", "b"]) == [0.1, 0.9]
    url, body, headers = s.sent
    assert url == "https://api.cohere.com/v2/rerank" and body["model"] == "rerank-v5.0-pro"
    assert body["query"] == "삼성전자 투자심리" and body["documents"] == ["a", "b"] and body["top_n"] == 2
    assert headers["Authorization"] == "Bearer test-key"
    monkeypatch.setenv("CH_RERANK_MODEL", "rerank-v5.0-fast")
    assert rerank.CohereReranker().model == "rerank-v5.0-fast"
    for code, msg in ((429, "한도 초과"), (500, "HTTP 500")):
        try:
            rerank.CohereReranker(session=_Sess(_Resp(code))).score("q", ["a"])
            raise AssertionError
        except RuntimeError as e:
            assert msg in str(e)
    try:
        rerank.CohereReranker(session=_Sess(_Resp(200, {"results": [{"index": 0, "relevance_score": 0.5}]}))).score("q", ["a", "b"])
        raise AssertionError
    except RuntimeError as e:
        assert "빠진" in str(e)


def test_fetch_rerank_counts_calls_and_uses_query_and_excerpts(monkeypatch):
    monkeypatch.setenv("COHERE_API_KEY", "test-key")
    s = _Sess(_Resp(429))
    raw = _raw()
    out = rag_hybrid.fetch_rerank(3, CO, AS_OF, raw, HITS, reranker=rerank.CohereReranker(session=s))
    assert out["calls"] == 1 and "한도 초과" in out["error"] and out["provider"] == "cohere"
    assert out["query"].startswith("삼성전자 투자심리·수급")                   # 종목명 + 관점 프리셋
    docs = s.sent[1]["documents"]
    assert len(docs) <= rerank.TOP_N and any("외국인이 연속 순매수" in t for t in docs)
    monkeypatch.setenv("CH_RERANK_PROVIDER", "solar")
    assert isinstance(rerank.get_reranker(), rerank.SolarReranker)
    out = rag_hybrid.fetch_rerank(3, CO, AS_OF, raw, HITS)
    assert out["calls"] == 0 and "NotImplementedError" in out["error"]


# ---------------------------------------------------------------- 프롬프트·인용 규칙

def _chunk_data(scores=_reverse):
    b = _sent_bundle()
    b["rag"] = _chunk_raw(scores)
    return build_agent_data(3, CO, b, AS_OF)


def _key_of(d, chunk_id):
    return next(f"D{i + 1}" for i, x in enumerate(d.docs) if x.get("chunk_id") == chunk_id)


def test_chunk_prompt_has_runtime_rule_excerpts_and_chunk_ids():
    d = _chunk_data()
    assert d.extra["rag_chunks"]["mode"] == "chunk"
    system, user = build_messages(d)
    assert prompts.CHUNK_RUNTIME_RULE in system
    assert prompts.CHUNK_RUNTIME_RULE.startswith("아래 [근거 청크] 에서만 정성 근거를 쓴다. 문장마다 해당 chunk_id 를 붙인다.")
    assert "[근거 청크] (공시 제목 + 검색한 청크 본문 발췌" in user
    k = _key_of(d, 901)
    assert f"- {k}: " in user and "chunk_id=901" in user and "발췌: 외국인이 연속 순매수" in user


def test_no_chunks_prompt_says_no_chunk_evidence():
    b = _sent_bundle()
    raw = _raw()
    raw["chunks"] = {"error": "청크 없음"}
    raw["rerank"] = {"error": "청크 없음", "calls": 0}
    b["rag"] = raw
    d = build_agent_data(3, CO, b, AS_OF)
    _, user = build_messages(d)
    assert "[근거 청크]\n- (근거 청크 없음)" in user and d.docs == rag.select(3, _raw(), CO, AS_OF)


def test_out_of_list_chunk_id_sentence_removed_and_chunk_ids_filled():
    d = _chunk_data()
    k = _key_of(d, 901)
    res = {"핵심진단": "외국인 수급 개선 보도가 있다.", "자체점수": 6,
           "주장": [{"문장": "외국인 순매수 보도가 있다.", "구분": "해석", "근거": [k], "chunkId": [901]},
                  {"문장": "기관 매도 보도가 있다.", "구분": "해석", "근거": [k]},
                  {"문장": "목록에 없는 청크를 근거로 든 문장.", "구분": "해석", "근거": [k], "chunkId": [123456]}],
           "반대근거": [{"문장": "개인은 매도 우위라는 보도도 있다.", "구분": "해석", "근거": [k], "chunkId": "#901"}]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    texts = [c["문장"] for c in out["result"]["주장"]]
    assert "목록에 없는 청크를 근거로 든 문장." not in texts and "목록에 없는 청크를 근거로 든 문장." in out["removed"]
    assert any("목록 밖 chunk_id [123456]" in x for x in out["checks"].get("근거", []))
    assert all(c["chunkId"] == [901] for c in out["result"]["주장"])      # LLM 이 안 붙인 문장도 D키로 채움
    assert out["result"]["반대근거"][0]["chunkId"] == [901]
    claims = out["contract"]["claims"]
    assert all(c["chunkIds"] == [901] for c in claims)
    assert {c["role"] for c in claims} == {"main", "counter"}
    assert contract.validate(out["contract"]) == [] and contract.link_errors(out["contract"]) == []
    assert out["rag_chunks"]["mode"] == "chunk" and out["rag_chunks"]["calls"] == 1


def test_chunk_numbers_cannot_be_quoted():
    d = _chunk_data()
    k = _key_of(d, 904)
    res = {"핵심진단": "외국인 보유 비중이 52.37 수준이라는 분석이 있다.", "자체점수": 6,
           "주장": [{"문장": "외국인 보유 비중이 52.37 수준이라는 분석이 있다.", "구분": "해석", "근거": [k]},
                  {"문장": "외국인 보유 비중이 높다는 분석이 있다.", "구분": "해석", "근거": [k]}],
           "리스크요인": ["보유 비중 52.37 은 과열 신호일 수 있다."]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    texts = [c["문장"] for c in out["result"]["주장"]]
    assert texts == ["외국인 보유 비중이 높다는 분석이 있다."]
    assert "52.37" not in json.dumps(out["result"], ensure_ascii=False)
    assert any("청크 속 숫자 인용" in x for v in out["checks"].values() for x in v)


def test_opinion_chunk_cannot_be_sole_fact_basis_and_bans_kept():
    d = _chunk_data()
    d.docs[-1]["kind"] = "블로그(개인 의견)"            # 개인 의견 청크로 바꿔 봄
    k = f"D{len(d.docs)}"
    ok = _key_of(d, 901) if d.docs[-1].get("chunk_id") != 901 else "D1"
    res = {"핵심진단": "수급 보도 확인.", "자체점수": 5,
           "주장": [{"문장": "개인 의견 청크만 근거로 한 사실.", "구분": "사실", "근거": [k]},
                  {"문장": "목표주가 상향이 필요하다.", "구분": "해석", "근거": [ok]},
                  {"문장": "외국인 수급 보도가 있다.", "구분": "해석", "근거": [ok]}]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    texts = [c["문장"] for c in out["result"]["주장"]]
    assert texts == ["외국인 수급 보도가 있다."]
