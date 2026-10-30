"""하이브리드 검색·리랭킹·chunk_id 근거 인용 테스트: 모의 임베딩·LLM, DB·네트워크 없음."""
import re

from ch_agents import agents, contract, rag, rag_hybrid
from ch_agents.agents import build_agent_data
from ch_agents.llm import run_agent
from conftest import AS_OF, CO, FakeLLM
from test_compute import _sent_bundle
from test_rag import _news, _raw


def _hit(chunk_id, doc_id, title, sim, source="naver_news"):
    return {"chunk_id": chunk_id, "doc_id": doc_id, "source": source, "title": title, "summary": "",
            "published": "2026-10-25", "published_at": "2026-10-25", "url": f"https://v.example/{doc_id}", "sim": sim}


# 벡터로만 찾은 문서(키워드 용어 없음) + 키워드 문서 1과 같은 문서(chunk 연결)
HITS = [_hit(901, 1, "삼성전자 외국인 순매수 1위…수급 개선", 0.80),
        _hit(902, 50, "삼성전자 자금 흐름 변화 점검", 0.90)]


def _hybrid_raw(**over):
    raw = _raw()
    raw["hybrid"] = {"hits": HITS, **over}
    return raw


def test_hybrid_adds_vector_doc_with_chunk_id():
    docs, st = rag_hybrid.select_hybrid(3, _hybrid_raw(), CO, AS_OF)
    news = [d for d in docs if d["kind"] != "공시"]
    by_id = {d["doc_id"]: d for d in news}
    assert by_id[50]["chunk_id"] == 902 and by_id[1]["chunk_id"] == 901   # 벡터로 찾은 문서·키워드와 겹친 문서
    assert news[0]["doc_id"] in (50, 1)                                   # 유사도가 높은 문서가 앞
    assert st == {"mode": "hybrid", "fallback": None}
    assert docs[0]["kind"] == "공시"                                        # 공시는 그대로 앞에


def test_no_chunks_or_error_falls_back_to_keyword_result_and_says_so():
    base = rag.select(3, _raw(), CO, AS_OF)
    for h in (None, {"error": "청크 없음"}, {"error": "RuntimeError: UPSTAGE_API_KEY 가 비어 있습니다"}):
        raw = _raw()
        if h is not None:
            raw["hybrid"] = h
        docs, st = rag_hybrid.select_hybrid(3, raw, CO, AS_OF)
        assert docs == base and st["mode"] == "keyword" and st["fallback"]


def test_fetch_hybrid_failures_are_recorded_not_raised():
    def boom(_):
        raise RuntimeError("API 오류")
    assert "API 오류" in rag_hybrid.fetch_hybrid(3, CO, AS_OF, _raw(), embed=boom)["error"]
    assert rag_hybrid.fetch_hybrid(3, CO, AS_OF, _raw(), embed=lambda t: [0.1] * 1024, run_sql=lambda s, p: [])["error"] == "청크 없음"

    calls = {}

    def run_sql(sql, p):
        calls["p"] = p
        return HITS
    out = rag_hybrid.fetch_hybrid(3, CO, AS_OF, _raw(), embed=lambda t: [0.1] * 1024, run_sql=run_sql)
    assert out == {"hits": HITS}
    assert calls["p"]["cid"] == CO["company_id"] and calls["p"]["qv"].startswith("[0.100000")  # 종목 필터 + 질의 벡터
    assert "INSERT" not in rag_hybrid.VECTOR_SQL.upper() and "UPDATE" not in rag_hybrid.VECTOR_SQL.upper()  # 읽기 전용


def test_fetch_bundle_hybrid_is_off_by_default(monkeypatch):
    monkeypatch.setattr(agents.db, "bundle", lambda sql, p: {})
    monkeypatch.setattr(agents.rag, "fetch", lambda a, co, as_of: {"news": [], "disclosures": []})
    monkeypatch.delenv("CH_RAG_HYBRID", raising=False)
    assert "hybrid" not in agents.fetch_bundle(3, CO, AS_OF)["rag"]
    monkeypatch.setenv("CH_RAG_HYBRID", "on")
    monkeypatch.setattr(agents.rag_hybrid, "fetch_hybrid", lambda *a, **k: {"error": "x"})
    assert agents.fetch_bundle(3, CO, AS_OF)["rag"]["hybrid"] == {"error": "x"}


def test_no_hybrid_key_keeps_existing_behaviour():
    b = _sent_bundle()
    b["rag"] = _raw()
    d = build_agent_data(3, CO, b, AS_OF)
    assert d.docs == rag.select(3, _raw(), CO, AS_OF) and "rag_hybrid" not in d.extra
    assert not any("chunk #" in line for line in rag.docs_markdown(d.docs))


def test_sample_question_citations_all_in_evidence_list():
    """삼성전자 최근 공시·재무 상태 → 모의 임베딩·LLM. 본문 D 키가 모두 근거 목록에 있고 chunk_id 가 나온다."""
    raw = _raw()
    raw["hybrid"] = rag_hybrid.fetch_hybrid(3, CO, AS_OF, raw, embed=lambda t: [0.1] * 1024, run_sql=lambda s, p: HITS)
    b = _sent_bundle()
    b["rag"] = raw
    d = build_agent_data(3, CO, b, AS_OF)
    assert d.extra["rag_hybrid"]["mode"] == "hybrid"
    keys = [f"D{i + 1}" for i, x in enumerate(d.docs) if x.get("chunk_id")]
    assert keys
    k = keys[0]
    res = {"핵심진단": "수급 개선 보도를 확인했다.", "자체점수": 6,
           "주장": [{"문장": f"외국인 순매수 보도가 있다 ({{{k}}}).", "구분": "사실", "근거": [k]}]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    body_keys = set(re.findall(r"`\[(D\d+)\]`", out["analysis"].split("**참고 문서")[0]))
    listed = set(re.findall(r"^- \[?(D\d+)\]?", out["analysis"].split("**참고 문서 (DB 검색)**")[1], re.M))
    assert k in body_keys and body_keys <= listed
    assert re.search(rf"\[{k}\] chunk #\d+ · naver_news · 2026-10-2\d · https://", out["analysis"])
    ev = {e["ledgerKey"]: e for e in out["contract"]["evidence"]}
    assert isinstance(ev[k]["chunkId"], int)
    assert all("chunkId" not in e for e in out["contract"]["evidence"] if e["kind"] != "document")
    assert contract.validate(out["contract"]) == [] and contract.link_errors(out["contract"]) == []


def test_old_output_without_chunk_id_still_validates():
    b = _sent_bundle()
    b["rag"] = _raw()
    d = build_agent_data(3, CO, b, AS_OF)
    res = {"핵심진단": "수급 확인.", "자체점수": 5, "주장": []}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    assert contract.validate(out["contract"]) == []
    assert all("chunkId" not in e for e in out["contract"]["evidence"])


def test_embed_query_with_mock_session(monkeypatch):
    class R:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b

    class S:
        def __init__(self, resp):
            self.resp, self.sent = resp, None

        def post(self, url, json=None, headers=None, timeout=None):
            self.sent = (url, json)
            return self.resp

    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    try:
        rag_hybrid.embed_query("q", S(R(200, {})))
        raise AssertionError("키 없음 오류가 나야 함")
    except RuntimeError as e:
        assert "UPSTAGE_API_KEY" in str(e)
    monkeypatch.setenv("UPSTAGE_API_KEY", "k")
    s = S(R(200, {"data": [{"embedding": [0.0] * 1024}]}))
    assert len(rag_hybrid.embed_query("q", s)) == 1024 and s.sent[1]["model"] == "solar-embedding-2-passage"
    try:
        rag_hybrid.embed_query("q", S(R(200, {"data": [{"embedding": [0.0] * 8}]})))
        raise AssertionError("차원 오류가 나야 함")
    except RuntimeError as e:
        assert "차원" in str(e)
