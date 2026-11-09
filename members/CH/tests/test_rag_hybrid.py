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
    assert docs[-1]["kind"] == "공시"                                       # 공시는 질문 기반 문서 뒤에(#67 QA)


def test_disclosures_follow_question_docs_and_are_capped_unless_question_asks():
    raw = _hybrid_raw()
    n_disc = len([d for d in rag.select_disclosures(raw.get("disclosures"), rag.PRESETS[3])])
    assert n_disc >= 2
    raw["hybrid"]["query"] = "삼성전자 환율 영향은? | 삼성전자 뉴스 키워드"
    docs, _ = rag_hybrid.select_hybrid(3, raw, CO, AS_OF)
    assert [d["kind"] for d in docs].count("공시") == 1 and docs[-1]["kind"] == "공시"
    raw["hybrid"]["query"] = "삼성전자 풍문 해명 공시 있어? | 삼성전자 뉴스 키워드"
    docs, _ = rag_hybrid.select_hybrid(3, raw, CO, AS_OF)
    assert [d["kind"] for d in docs].count("공시") == n_disc


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
    assert out["hits"] == HITS + HITS and "삼성전자" in out["query"]      # 공개 출처 묶음·개인 작성 글 묶음 두 번 검색(같은 모의 행)
    assert calls["p"]["cid"] == CO["company_id"] and calls["p"]["qv"].startswith("[0.100000")  # 종목 필터 + 질의 벡터
    assert "INSERT" not in rag_hybrid.VECTOR_SQL.upper() and "UPDATE" not in rag_hybrid.VECTOR_SQL.upper()  # 읽기 전용


def test_fetch_bundle_hybrid_is_on_by_default_and_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(agents.db, "bundle", lambda sql, p: {})
    monkeypatch.setattr(agents.rag, "fetch", lambda a, co, as_of: {"news": [], "disclosures": []})
    monkeypatch.setattr(agents.rag_hybrid, "fetch_hybrid", lambda *a, **k: {"error": "x"})
    monkeypatch.delenv("CH_RAG_HYBRID", raising=False)
    assert agents.fetch_bundle(3, CO, AS_OF)["rag"]["hybrid"] == {"error": "x"}          # 기본 켬(#67)
    monkeypatch.setenv("CH_RAG_HYBRID", "off")
    assert "hybrid" not in agents.fetch_bundle(3, CO, AS_OF)["rag"]


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


def test_question_goes_into_the_query_sentence():
    a, b = rag_hybrid.query_text(3, CO), rag_hybrid.query_text(3, CO, "외국인 수급 어때?")
    assert b.startswith("외국인 수급 어때? | ") and b.endswith(a) and "|" not in a


W = ["반도체 공급", "환율 변동", "배당 확대", "공장 증설", "노조 협상", "신제품 출시", "미국 관세", "스마트폰 판매", "파운드리 수주", "메모리 가격", "자사주 소각", "로봇 투자"]


def test_vector_top_docs_are_guaranteed_ahead_of_keyword_scores_and_carry_evidence():
    many = [_hit(900 + i, 100 + i, W[i], 0.40 + i * 0.01) for i in range(12)]
    docs, st = rag_hybrid.select_hybrid(3, {**_raw(), "hybrid": {"hits": many}}, CO, AS_OF)
    news = [d for d in docs if d["kind"] != "공시"]
    need = -(-int(rag.PRESETS[3].k_docs * rag_hybrid.VECTOR_SHARE * 100) // 100)
    top_vec = sorted(many, key=lambda h: -h["sim"])[:need]
    assert [d["doc_id"] for d in news[:need]] == [h["doc_id"] for h in top_vec]       # 유사도 순으로 먼저
    assert all(d["origin"] in ("벡터", "둘 다") and d["chunks"] and d["chunks"][0]["chunkId"] == d["chunk_id"] for d in news[:need])
    assert st["mode"] == "hybrid"


def test_origin_marks_keyword_only_and_both():
    docs, _ = rag_hybrid.select_hybrid(3, _hybrid_raw(), CO, AS_OF)
    origins = {d["doc_id"]: d["origin"] for d in docs if d["kind"] != "공시"}
    assert origins[50] == "벡터" and origins[1] == "둘 다" and "키워드" in origins.values()


def test_future_and_other_company_chunks_never_reach_the_sql_params():
    seen = {}

    def run_sql(sql, p):
        seen.update(p)
        return HITS
    rag_hybrid.fetch_hybrid(3, CO, AS_OF, _raw(), embed=lambda t: [0.1] * 1024, run_sql=run_sql, question="수급?")
    assert seen["as_of"] == AS_OF and seen["cid"] == CO["company_id"] if "company_id" in CO else seen["as_of"] == AS_OF
    assert "d.company_id = %(cid)s" in rag_hybrid.VECTOR_SQL and "d.published_at <= %(as_of)s::date" in rag_hybrid.VECTOR_SQL


# ---------------------------------------------------------------- 질문 관련도 점검 (#70)

def test_topic_terms_drop_company_names_and_generic_words():
    names = {"현대차", "삼성전자"}
    assert rag_hybrid.topic_terms("현대차 노조 파업 소식 있어?", names) == ["노조", "파업"]
    assert rag_hybrid.topic_terms("현대차는 금리 변화에 얼마나 민감해?", names) == ["금리"]
    assert rag_hybrid.topic_terms("삼성전자 최근 이슈가 뭐야?", names) == []          # 일반 질문
    assert rag_hybrid.topic_terms("삼성전자 지금 팔아야 할까?", names) == []


def _d(title, sim=0.0, excerpt=""):
    return {"title": title, "summary": "", "sim": sim, "chunks": [{"excerpt": excerpt}] if excerpt else []}


def test_relevance_filter_keeps_term_match_or_strong_similarity_and_drops_the_rest():
    docs = [_d("현대차 노조 파업에 매출 감소", 0.61), _d("현대차 신차 출시", 0.65), _d("현대차 배당 확대", 0.69), _d("현대차 노조 협상", 0.0, "")]
    kept, info = rag_hybrid.relevance_filter(docs, "현대차 노조 파업 소식 있어?", {"현대차"})
    assert [d["title"] for d in kept] == ["현대차 노조 파업에 매출 감소", "현대차 배당 확대", "현대차 노조 협상"]   # 파업 일치·유사도 0.69·노조 일치
    assert info["dropped"] == 1 and info["notFound"] is False and info["terms"] == ["노조", "파업"]


def test_relevance_filter_says_not_found_instead_of_filling_with_general_news():
    docs = [_d("삼성전자 외국인 순매수", 0.64), _d("삼성전자 환율 노출", 0.62)]
    kept, info = rag_hybrid.relevance_filter(docs, "삼성전자 우주 탐사 계획은?", {"삼성전자"})
    assert kept == [] and info["notFound"] is True and info["dropped"] == 2
    same, info2 = rag_hybrid.relevance_filter(docs, "삼성전자 최근 이슈가 뭐야?", {"삼성전자"})    # 핵심어 없는 일반 질문은 점검 안 함
    assert same == docs and info2["checked"] is False and info2["notFound"] is False


def test_chunk_text_counts_as_match():
    kept, _ = rag_hybrid.relevance_filter([_d("실적 발표", 0.5, "노조 파업으로 생산 차질")], "현대차 노조 파업", {"현대차"})
    assert len(kept) == 1


def test_select_hybrid_applies_keep_before_cutting_to_k():
    raw = _hybrid_raw()
    raw["hybrid"]["query"] = "q | base"
    seen = {}

    def keep(ds):
        seen["n"] = len(ds)
        return [d for d in ds if d.get("kind") != "공시"][:1]
    docs, st = rag_hybrid.select_hybrid(3, raw, CO, AS_OF, keep=keep)
    assert len(docs) == 1 and st["mode"] == "hybrid" and seen["n"] >= 2


def test_fetch_hybrid_searches_public_and_private_sources_separately():
    calls = []

    def run_sql(sql, p):
        calls.append((tuple(p["sources"]), p["n"]))
        return [{"chunk_id": len(calls), "doc_id": len(calls), "content": "x", "published_at": f"{AS_OF}T00:00:00", "published": AS_OF,
                 "source": p["sources"][0], "title": "t", "summary": "", "url": "u", "sim": 0.5}]
    out = rag_hybrid.fetch_hybrid(3, CO, AS_OF, {}, embed=lambda q: [0.1, 0.2], run_sql=run_sql)
    assert len(calls) == 2 and not set(calls[0][0]) & set(rag_hybrid.PRIVATE_SOURCES)
    assert set(calls[1][0]) <= set(rag_hybrid.PRIVATE_SOURCES) and calls[1][1] == rag_hybrid.PRIVATE_CANDIDATES
    assert len(out["hits"]) == 2

