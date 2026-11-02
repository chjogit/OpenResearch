"""#18 청크 인용 보강(CH_CHUNK_CITE=boost) 테스트: 모의 LLM·리랭커, DB·네트워크 없음."""
import json

from ch_agents import agents, prompts, rag
from ch_agents.llm import build_messages, check_output, run_agent
from conftest import AS_OF, CO, FakeLLM
from test_rerank_chunks import _chunk_data, _key_of


def _boost(monkeypatch, on=True):
    if on:
        monkeypatch.setenv("CH_CHUNK_CITE", "boost")
    else:
        monkeypatch.delenv("CH_CHUNK_CITE", raising=False)


# ---------------------------------------------------------------- 스위치

def test_boost_off_by_default_prompt_same_as_r4_2(monkeypatch):
    _boost(monkeypatch, on=False)
    d = _chunk_data()
    system, user = build_messages(d)
    assert prompts.CHUNK_BOOST_RULE not in system and "[청크 인용 목록]" not in user
    assert "발췌: 외국인 보유 비중이 1년 중 최고인 52.37" in user           # 기존 형식 그대로 (숫자 가림 없음)
    for env in ("off", "OFF", ""):
        monkeypatch.setenv("CH_CHUNK_CITE", env)
        assert build_messages(d) == (system, user)


def test_boost_needs_chunk_mode(monkeypatch):
    """청크 근거가 없는(CH_RAG_RERANK=off) 실행에는 보강이 켜져 있어도 아무것도 바뀌지 않음."""
    from test_compute import _sent_bundle
    from test_rag import _raw
    b = _sent_bundle()
    b["rag"] = _raw()
    d = agents.build_agent_data(3, CO, b, AS_OF)
    before = build_messages(d)
    _boost(monkeypatch)
    assert build_messages(d) == before


def test_boost_prompt_format_masks_numbers_and_lists_citation_units(monkeypatch):
    _boost(monkeypatch)
    d = _chunk_data()
    system, user = build_messages(d)
    assert prompts.CHUNK_BOOST_RULE in system and prompts.CHUNK_RUNTIME_RULE in system
    k = _key_of(d, 904)
    assert f"- {k} · chunk_id=904 · " in user
    assert "52.37" not in user and "1년 중 최고인 [수치] 수준" in user        # 청크 숫자는 가려서 보여줌
    assert f"[청크 인용 목록]" in user and f"{k}=chunk 904" in user
    assert d.docs[[x.get("chunk_id") for x in d.docs].index(904)]["excerpt"].count("52.37") == 1  # 원문은 그대로


def test_mask_numbers_keeps_single_digits():
    assert rag.mask_numbers("3분기 영업이익 9.1조, 1,234억 원, 2026년") == "3분기 영업이익 [수치]조, [수치]억 원, [수치]년"


def test_chunk_only_mode_uses_chunks_without_reranker(monkeypatch):
    monkeypatch.setattr(agents.db, "bundle", lambda sql, p: {})
    monkeypatch.setattr(agents.rag, "fetch", lambda a, co, as_of: {"news": [], "disclosures": []})
    monkeypatch.setattr(agents.rag_hybrid, "fetch_chunks", lambda *a, **k: {"hits": [{"chunk_id": 1}]})
    called = []
    monkeypatch.setattr(agents.rag_hybrid, "fetch_rerank", lambda *a, **k: called.append(1) or {"calls": 1})
    monkeypatch.setenv("CH_RAG_RERANK", "chunk")
    r = agents.fetch_bundle(3, CO, AS_OF)["rag"]
    assert called == [] and r["rerank"] == {"error": "리랭킹 끔 (CH_RAG_RERANK=chunk)", "calls": 0}
    monkeypatch.setenv("CH_RAG_RERANK", "on")
    assert agents.fetch_bundle(3, CO, AS_OF)["rag"]["rerank"] == {"calls": 1} and called == [1]


# ---------------------------------------------------------------- 검사: 보강 형식에서도 기존 차단 유지

def test_boost_flags_missing_chunk_citation_only_when_on(monkeypatch):
    d = _chunk_data()
    res = {"핵심진단": "수급 확인.", "자체점수": 5, "주장": [{"문장": "수급 판정이 있다.", "구분": "예측", "근거": []}]}
    _boost(monkeypatch, on=False)
    assert prompts.CHUNK_BOOST_MISSING not in check_output(res, d).get("근거", [])
    _boost(monkeypatch)
    assert prompts.CHUNK_BOOST_MISSING in check_output(res, d)["근거"]
    k = _key_of(d, 901)
    res["주장"].append({"문장": "외국인 순매수 보도가 있다.", "구분": "해석", "근거": [k], "chunkId": [901]})
    assert prompts.CHUNK_BOOST_MISSING not in check_output(res, d).get("근거", [])


def test_boost_out_of_list_chunk_id_and_chunk_numbers_still_removed(monkeypatch):
    _boost(monkeypatch)
    d = _chunk_data()
    k1, k4 = _key_of(d, 901), _key_of(d, 904)
    res = {"핵심진단": "외국인 수급 개선 보도가 있다.", "자체점수": 6,
           "주장": [{"문장": "외국인 순매수 보도가 있다.", "구분": "해석", "근거": [k1], "chunkId": [901]},
                  {"문장": "목록에 없는 청크를 근거로 든 문장.", "구분": "해석", "근거": [k1], "chunkId": [123456]},
                  {"문장": "외국인 보유 비중이 52.37 수준이라는 분석이 있다.", "구분": "해석", "근거": [k4], "chunkId": [904]},
                  {"문장": "목표주가 상향이 필요하다.", "구분": "해석", "근거": [k1], "chunkId": [901]}]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    texts = [c["문장"] for c in out["result"]["주장"]]
    assert texts == ["외국인 순매수 보도가 있다."]
    assert "52.37" not in json.dumps(out["result"], ensure_ascii=False)
    assert out["result"]["주장"][0]["chunkId"] == [901]
    checks = [x for v in out["checks"].values() for x in v]
    assert any("목록 밖 chunk_id [123456]" in x for x in checks) and any("청크 속 숫자 인용" in x for x in checks)


def test_boost_opinion_chunk_still_not_sole_fact_basis(monkeypatch):
    _boost(monkeypatch)
    d = _chunk_data()
    d.docs[-1]["kind"] = "블로그(개인 의견)"
    k = f"D{len(d.docs)}"
    ok = _key_of(d, 901)
    res = {"핵심진단": "수급 보도 확인.", "자체점수": 5,
           "주장": [{"문장": "개인 의견 청크만 근거로 한 사실.", "구분": "사실", "근거": [k]},
                  {"문장": "외국인 수급 보도가 있다.", "구분": "해석", "근거": [ok]}]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    assert [c["문장"] for c in out["result"]["주장"]] == ["외국인 수급 보도가 있다."]
