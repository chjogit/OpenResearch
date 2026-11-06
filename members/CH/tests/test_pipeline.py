"""질문 → 답 파이프라인 그림·설명(#61): 단계 수 = 추적 이벤트 종류, 설명 값 = 설정값."""
import json
import re
from pathlib import Path

import pytest

from qa import agent as qa
from qa import pipeline

HERE = Path(__file__).resolve().parent.parent


def test_every_trace_kind_and_tool_maps_to_a_pipeline_step():
    src = (HERE / "qa" / "agent.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'step\("([^"]+)"', src))
    steps = {s["no"] for s in pipeline.describe(None)["steps"]}
    for k in kinds:
        keys = [f"도구:{t}" for t in qa.TOOLS] if k == "도구" else [k]
        for key in keys:
            assert pipeline.EVENT_STAGE.get(key), f"추적 이벤트 {key} 가 그림 단계에 없음"
            assert set(pipeline.EVENT_STAGE[key]) <= steps
    assert steps == set(range(1, 10)) and all(s["name"] and s["what"] and s["tech"] for s in pipeline.describe(None)["steps"])


@pytest.mark.parametrize("flag,state", [("on", "on"), ("off", "off")])
def test_step5_vector_search_state_follows_the_setting(monkeypatch, flag, state):
    monkeypatch.setenv("CH_RAG_HYBRID", flag)
    s5 = pipeline.describe(None)["steps"][4]
    vec = next(t for t in s5["tech"] if t["label"] == "벡터 검색")
    assert vec["state"] == state and vec["value"].startswith("켜짐" if flag == "on" else "꺼짐")
    assert [x["state"] for x in s5["subs"] if x["name"].startswith("벡터")] == [state]       # 꺼진 하위 단계는 꺼짐 표시(흐리게)
    if flag == "on":
        assert "solar-embedding-2-passage" in vec["value"] and "1024" in vec["value"]


def test_reranker_and_llm_values_come_from_config(monkeypatch):
    from ch_agents import llm as llm_mod

    monkeypatch.setenv("CH_RAG_RERANK", "off")
    steps = {s["no"]: s for s in pipeline.describe(None)["steps"]}
    assert next(t for t in steps[5]["tech"] if t["label"] == "리랭커")["state"] == "off"
    assert next(t for t in steps[2]["tech"] if t["label"] == "LLM")["value"] == llm_mod.MODEL
    assert next(t for t in steps[3]["tech"] if t["label"] == "도구 호출 상한")["value"] == f"{qa.MAX_TOOL_CALLS}회"
    assert qa.VERIFIER_TEXT in next(t for t in steps[7]["tech"] if t["label"] == "검사 항목")["value"]


def test_stats_come_from_the_run_record():
    out = {"question": "삼성전자 수급?", "interpretation": {"company": {"name": "삼성전자"}, "intent": "수급"}, "status": "완료", "outlook": {"cards": [1, 2]},
           "usage": {"llm_calls": 3, "total_seconds": 12.5},
           "trace": [{"kind": "도구", "tool": "run_node_agent", "args": {"agent_no": 4}, "origin": "LLM"},
                     {"kind": "도구", "tool": "doc_search", "result": {"rag": {"found": [1, 2, 3], "hybrid": {"modeLabel": "하이브리드 검색(키워드 + 벡터)"}}}, "origin": "LLM"},
                     {"kind": "답·검사", "kept": 5, "removed": [{"문장": "x"}]}]}
    st = {s["no"]: s["stat"] for s in pipeline.describe(out)["steps"]}
    assert "도구 2회" in st[3] and "에이전트 4" in st[4] and "문서 3건" in st[5] and "하이브리드" in st[5]
    assert st[7] == "통과 5문장 · 제거 1문장" and st[8] == "전망 카드 2장" and "LLM 3회" in st[9]
    assert all(s["stat"] is None for s in pipeline.describe(None)["steps"])


def test_pipeline_json_has_no_secret_or_banned_words():
    s = json.dumps(pipeline.describe(None), ensure_ascii=False)
    assert not re.search(r"API_KEY|postgres|목표\s*주가|추천", s)


def _fake(monkeypatch, hybrid_result, enabled=True):
    from ch_agents import rag, rag_hybrid

    monkeypatch.setattr(rag, "fetch", lambda *a: {"news": []})
    monkeypatch.setattr(rag, "select", lambda *a: [{"doc_id": 1}])
    monkeypatch.setattr(rag_hybrid, "enabled", lambda: enabled)
    monkeypatch.setattr(rag_hybrid, "fetch_hybrid", lambda *a, **k: hybrid_result)
    monkeypatch.setattr("ch_agents.agents.normalize_as_of", lambda x: x or "2026-11-04")


def test_retrieve_docs_records_embedding_call_and_vector_hits(monkeypatch):
    from ch_agents import rag_hybrid

    _fake(monkeypatch, {"hits": [{"doc_id": 7}] * 3})
    monkeypatch.setattr(rag_hybrid, "select_hybrid", lambda *a: ([{"doc_id": 7}], {"mode": "hybrid", "fallback": None}))
    docs, h = qa.retrieve_docs({"name": "x"}, "2026-11-04")
    assert docs == [{"doc_id": 7}] and h["mode"] == "hybrid" and h["vectorHits"] == 3 and h["embedModel"] == rag_hybrid.QUERY_MODEL and h["fallback"] is None


def test_retrieve_docs_falls_back_to_keyword_and_says_why(monkeypatch):
    _fake(monkeypatch, {"error": "RuntimeError: 임베딩 HTTP 500"})
    docs, h = qa.retrieve_docs({"name": "x"}, "2026-11-04")
    assert h["mode"] == "keyword" and "임베딩" in h["fallback"] and "대체" in h["modeLabel"]


def test_retrieve_docs_keyword_only_when_off(monkeypatch):
    _fake(monkeypatch, {}, enabled=False)
    _, h = qa.retrieve_docs({"name": "x"}, "2026-11-04")
    assert h["mode"] == "keyword" and h["fallback"] is None


def test_template_marks_stage_anchors_and_has_no_tech_json():
    t = (HERE / "demo" / "template.html").read_text(encoding="utf-8")
    assert 'data-stage="8"' in t and 'data-stage="9"' in t and 'data-stage="1"' in t and "pipeSvgH" in t and "pipeSvgV" in t
    assert "kvs(e.tech)" not in t and "kvs(tech)" not in t
