"""#25 노드 기반 에이전트 3·4·6 통합: 장부 병합 → 서술·검증 → 계약 r4-1.3 → 렌더러. 모의 입력, 네트워크·DB·실 LLM 없음."""
import copy

import pytest

from ch_agents import contract, node_agents, nodes, renderer
from ch_agents.llm import run_node_agent
from ch_agents.sentiment_limit import SENT_LIMIT_TEXT
from conftest import AS_OF, CO, FakeLLM
from test_flow_nodes import inputs as flow_inputs
from test_macro_nodes import bundle as macro_bundle
from test_sentiment_nodes import inputs as sent_inputs


class NoLLM:
    def invoke(self, *a, **k):
        raise RuntimeError("no-llm")


def data3(ext=True, scenario="환율 5% 상승"):
    return node_agents.build_data(3, "005930", AS_OF, extension=ext, scenario=scenario, co=CO, inputs=macro_bundle())


def data4(ext=True):
    return node_agents.build_data(4, "005930", AS_OF, extension=ext, co=CO, inputs=flow_inputs())


def data6(ext=True):
    return node_agents.build_data(6, "005930", AS_OF, extension=ext, co=CO, inputs=sent_inputs())


ALL = [(3, data3), (4, data4), (6, data6)]


def good_json(d):
    """장부 첫 판정 문장 하나를 그대로 인용하는 가짜 LLM 출력."""
    fl = next(x for x in d.facts.flags if node_agents.PLACEHOLDER.search(x))
    keys = node_agents.PLACEHOLDER.findall(fl)
    return {"핵심진단": fl, "주장": [{"문장": fl, "구분": "사실", "근거": keys}], "반대근거": [], "긍정요인": [], "리스크요인": [],
            "미확인": [], "다음점검": [], "자체점수": 6, "점수이유": "테스트"}


@pytest.mark.parametrize("no,make", ALL)
def test_data_has_spec_and_merged_ledger_without_key_collision(no, make):
    d = make()
    assert d.agent_id == no and d.spec.agent_id == no and d.extra["node_agent"] is True
    led_keys = [k for res in d.extra["node_report"]["results"].values() for k in res.artifacts["ledger"]]
    assert len(led_keys) == len(set(led_keys)) == len(d.facts.items)            # 노드끼리 키가 겹치지 않음
    assert all(__import__("re").fullmatch(r"[A-Z]\d+", k) for k in d.facts.items)
    assert d.facts.flags and all(x for x in d.facts.flags)


@pytest.mark.parametrize("no,make", ALL)
def test_flags_use_ledger_keys_not_copied_numbers(no, make):
    d = make()
    used = {k for fl in d.facts.flags for k in node_agents.PLACEHOLDER.findall(fl)}
    assert used and used <= set(d.facts.items)


@pytest.mark.parametrize("no,make", ALL)
def test_contract_is_valid_with_nodes_tags_and_agent_nos(no, make):
    out = run_node_agent(no, "005930", llm=FakeLLM(good_json(make())), data=make())
    c = out["contract"]
    assert contract.validate(c) == [] and contract.link_errors(c) == []
    assert c["schemaVersion"] == "r4-1.5" and c["agent"]["id"] == no and c["agent"]["agentNos"] == [no]
    assert c["nodes"] and c["nodeSummary"]["executed"] >= 1 and all(cl["tag"] in nodes.TAGS for cl in c["claims"])
    assert out["status"].startswith("완료") and c["claims"]


@pytest.mark.parametrize("no,make", ALL)
def test_rule_fallback_still_produces_valid_contract(no, make):
    out = run_node_agent(no, "005930", llm=NoLLM(), data=make())
    assert out["status"].startswith("규칙 기반 대체")
    assert contract.validate(out["contract"]) == [] and out["contract"]["claims"]


def test_llm_number_outside_ledger_is_removed_by_verifier():
    d = data6()
    g = good_json(d)
    g["주장"].append({"문장": "삼성전자 주가가 반드시 17% 오른다", "구분": "예측", "근거": []})
    out = run_node_agent(6, "005930", llm=FakeLLM(g, g), data=d)
    texts = " ".join(c["text"] for c in out["contract"]["claims"])
    assert "17%" not in texts


def test_prompt_lists_node_status_and_skip_reasons():
    d = data6(ext=False)
    from ch_agents.llm import build_messages

    _, user = build_messages(d, "expert")
    assert "[노드 실행 현황]" in user and "N12" in user and "건너뜀" in user and "확장 노드를 선택하지 않음" in user


def test_skip_and_prediction_reason_reach_contract_and_render():
    d = data6(ext=True)                                     # 감성 모델 미검증 → 추론 생략
    out = run_node_agent(6, "005930", llm=NoLLM(), data=d)
    c = out["contract"]
    assert "SENT_MODEL_UNVALIDATED" in c["predictionSkippedReason"]
    md = renderer.render(c)["markdown"]
    assert "N12" in md and "SENT_MODEL_UNVALIDATED" in md.replace("`", "") or "추론" in md


def test_skipped_extension_is_shown_in_render_for_every_profile():
    out = run_node_agent(6, "005930", llm=NoLLM(), data=data6(ext=False))
    shown = renderer.render_all(out["contract"])
    assert shown and all("N12" in r["markdown"] and "건너뜀" in r["markdown"] for r in shown.values())


def test_conflicts_are_kept_side_by_side_not_averaged():
    docs = [{"doc_id": 1, "source": "naver_news", "title": "삼성전자 실적 발표 기대", "summary": "삼성전자 실적 발표를 기대한다.",
             "url": "u1", "d": AS_OF, "score": 0.6, "label": "positive", "method": "lexicon", "chunk_id": None},
            {"doc_id": 2, "source": "naver_news", "title": "삼성전자 실적 발표 우려", "summary": "삼성전자 실적 발표에 우려가 나왔다.",
             "url": "u2", "d": AS_OF, "score": -0.6, "label": "negative", "method": "lexicon", "chunk_id": None}]
    d = node_agents.build_data(6, "005930", AS_OF, co=CO, inputs=sent_inputs(docs=docs))
    assert any(x.startswith("관점별 충돌") for x in d.facts.flags)
    c = run_node_agent(6, "005930", llm=NoLLM(), data=d)["contract"]
    assert c["conflicts"] and len(c["conflicts"][0]["views"]) == 2
    assert "관점별 충돌" in renderer.render(c)["markdown"]


def test_n06_limit_and_mention_limit_reach_prompt():
    from ch_agents.llm import build_messages

    assert "추정 모델 미사용(실험상 예측 개선 없음)" in build_messages(data3(), "expert")[1]
    assert "부수적으로 언급" in build_messages(data6(), "expert")[1]


def test_legacy_numbers_map_to_new_agents_through_conversion_table():
    got = node_agents.legacy_to_nodes(1, "005930", AS_OF, co=CO, inputs=macro_bundle())
    assert [d.agent_id for d in got] == [3]
    assert nodes.legacy_agent_nos(3) == [4, 6]


def test_no_investment_advice_in_node_agent_outputs():
    import re

    for no, make in ALL:
        out = run_node_agent(no, "005930", llm=NoLLM(), data=make())
        blob = " ".join(c["text"] for c in out["contract"]["claims"]) + out["analysis"]
        assert not re.search(r"매수\s*(추천|의견)|매도\s*(추천|의견)|목표\s*주가\s*[:는]|사세요|파세요", blob), no


def test_node_scorecard_never_overwrites_the_before_split_record(tmp_path, monkeypatch):
    from ch_agents import evaluate

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        evaluate.node_scorecard(["005930"], save_to="eval_results.json", as_of=AS_OF)


def test_summarize_runs_counts_like_llm_scorecard():
    from ch_agents import evaluate

    out = run_node_agent(6, "005930", llm=FakeLLM(good_json(data6())), data=data6())
    s = evaluate.summarize_runs([out, run_node_agent(4, "005930", llm=NoLLM(), data=data4())])
    assert s["runs"] == 2 and s["status"] and s["avg_claims"] > 0 and "check_violations_last_attempt" in s


def test_run_legacy_via_nodes_maps_old_numbers(monkeypatch):
    from ch_agents import llm

    seen = []
    monkeypatch.setattr(llm, "run_node_agent", lambda no, *a, **k: seen.append((no, k.get("scenario"))) or {"agent": no})
    assert llm.run_legacy_via_nodes(3, "005930", scenario="x") == [{"agent": 4}, {"agent": 6}]
    assert llm.run_legacy_via_nodes(1, "005930", scenario="환율 5% 상승") == [{"agent": 3}]
    assert seen == [(4, None), (6, None), (3, "환율 5% 상승")]
    with pytest.raises(KeyError):
        llm.run_legacy_via_nodes(7, "005930")


def test_numbers_outside_ledger_are_masked_in_flags_and_notes():
    assert node_agents._mask_loose_numbers("Brier 0.265 가 0.262 보다 {S3} 5일 N07 12,345주 3.5%") == \
        "Brier (수치는 노드 산출물 참조) 가 (수치는 노드 산출물 참조) 보다 {S3} 5일 N07 (수치는 노드 산출물 참조)주 (수치는 노드 산출물 참조)"
    for no, make in ALL:
        d = make()
        for t in [*d.facts.flags, *d.facts.notes]:
            rest = node_agents.PLACEHOLDER.sub("", t)
            assert not node_agents.LOOSE_NUMBER.search(rest.replace(node_agents.DIRECTION_RULE, "").replace(SENT_LIMIT_TEXT, "")), (no, t)


def test_direction_rule_is_in_prompt_notes():
    assert node_agents.DIRECTION_RULE in data4().facts.notes


def test_out_of_scope_items_get_fixed_reason_and_others_keep_node_reason():
    from ch_agents.availability import OUT_OF_SCOPE_TEXT, availability
    assert availability("호가 잔량") == "not_disclosed" and availability("세부 주체(금융투자·투신·연기금)") == "not_disclosed"
    for no, make in ALL:
        f = make().facts
        for g in f.gaps:
            if "호가 잔량" in g["label"] or "세부 주체" in g["label"]:
                assert g["reason"] == OUT_OF_SCOPE_TEXT
            else:
                assert OUT_OF_SCOPE_TEXT not in g["reason"]


def test_prompt_lists_intentionally_unused_sources_without_banned_word():
    from ch_agents.llm import COMMON_RULES
    line = next(l for l in COMMON_RULES.split("\n") if l.startswith("14. "))
    assert "증권사 가격 전망" in line and "블로그·카페·유튜브 원문" in line and "미확인" in line
    assert "목표주가" not in line and "목표가" not in line
