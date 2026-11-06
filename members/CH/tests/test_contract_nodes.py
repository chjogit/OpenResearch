"""#21 데이터 계약 r4-1.3: 에이전트 번호·nodes[]·태그·충돌 (모두 선택 필드), 옛 p01·p03 출력의 변환표, 분석 값 불변."""
import copy
import random

import pytest

from ch_agents import contract, nodes
from ch_agents.agents import build_agent_data
from ch_agents.llm import run_agent
from conftest import AS_OF, CO, FakeLLM
from test_compute import _macro_bundle, _sent_bundle

# 분리 전(origin/main 87f039f)에서 같은 입력(시드 7 거시 번들·_sent_bundle, LLM 실패 → 코드 계산만)으로 만든 reportId.
# 새 선택 필드(agentNos·tag)가 ID 해시에 들어가면 같은 입력인데 ID 가 바뀌므로 여기서 걸린다.
GOLDEN_REPORT_ID = {1: "RPT-1-005930-20261026-c1d396e8", 3: "RPT-3-005930-20261026-b1aaab1f"}


def _out(aid):
    bundle = _macro_bundle(random.Random(7)) if aid == 1 else _sent_bundle()
    return run_agent(aid, data=build_agent_data(aid, CO, bundle, AS_OF), llm=FakeLLM(TimeoutError()))


@pytest.fixture(scope="module")
def outs():
    return {1: _out(1), 3: _out(3)}


def test_version_is_r4_1_4_and_old_versions_still_validate(outs):
    assert contract.SCHEMA_VERSION == "r4-1.5"
    for aid, out in outs.items():
        c = out["contract"]
        assert contract.validate(c) == [] and contract.link_errors(c) == []
        for old in ("r4-1.0", "r4-1.1", "r4-1.2", "r4-1.3"):
            assert contract.validate(dict(c, schemaVersion=old)) == []       # 이전 버전 이름도 통과
    bad = dict(outs[1]["contract"], schemaVersion="r9")
    assert contract.validate(bad)                                          # 모르는 버전은 걸림


def test_legacy_agents_carry_new_numbers_via_explicit_table(outs):
    assert outs[1]["contract"]["agent"]["agentNos"] == [3]                 # p01 거시 → 3
    assert outs[3]["contract"]["agent"]["agentNos"] == [4, 6]              # p03 투자심리·수급 → 4·6
    assert outs[1]["contract"]["agent"]["id"] == 1 and outs[3]["contract"]["agent"]["id"] == 3   # 옛 id 는 그대로


@pytest.mark.parametrize("aid", [1, 3])
def test_analysis_values_are_identical_to_before_the_split(outs, aid):
    c = outs[aid]["contract"]
    assert c["reportId"] == GOLDEN_REPORT_ID[aid]                          # 분석 내용 해시가 분리 전과 같음
    stripped = copy.deepcopy(c)
    stripped["agent"].pop("agentNos")
    for cl in stripped["claims"]:
        cl.pop("tag")
    # 새 선택 필드를 빼면 옛 구조: 나머지 키 집합이 r4-1.2 와 같고 값 비교는 위 reportId(주장·근거·기준일 해시)로 고정
    assert "nodes" not in c and "conflicts" not in c and "nodeSummary" not in c   # 노드를 안 돌리면 필드가 생기지 않음
    assert set(stripped) >= {"claims", "evidence", "verification", "unverified", "downsideRisks"}


def test_claim_tag_mapping_to_legacy_label(outs):
    for out in outs.values():
        for cl in out["contract"]["claims"]:
            assert cl["tag"] in nodes.TAGS
            if cl["typeLabel"] == "해석":
                assert cl["tag"] == "Interpretation"
            if cl["typeLabel"] == "예측":
                assert cl["tag"] == "Prediction"
            if cl["typeLabel"] == "사실":
                assert cl["tag"] in ("Fact", "Computation")                # 근거가 모두 계산 항목이면 Computation


def test_old_output_is_upgraded_by_table_without_touching_values(outs):
    c = outs[3]["contract"]
    old = copy.deepcopy(c)
    old["schemaVersion"] = "r4-1.0"
    old["agent"].pop("agentNos")
    for cl in old["claims"]:
        cl.pop("tag")
    assert contract.validate(old) == []                                    # 옛 출력은 그대로 통과
    new = contract.upgrade_legacy(old)
    assert new["agent"]["agentNos"] == [4, 6] and all(cl["tag"] in nodes.TAGS for cl in new["claims"])
    assert contract.validate(new) == [] and contract.link_errors(new) == []
    assert {k: v for k, v in new.items() if k not in ("agent", "claims")} == {k: v for k, v in old.items() if k not in ("agent", "claims")}
    assert [(a["text"], a["evidenceIds"]) for a in new["claims"]] == [(a["text"], a["evidenceIds"]) for a in old["claims"]]
    assert contract.upgrade_legacy(new) == new                             # 두 번 해도 같음
    assert old["agent"].get("agentNos") is None                            # 원본을 건드리지 않음


def test_with_nodes_attaches_selected_fields_and_validates(outs):
    ALL = {"macro_series", "scenario_assumptions", "price", "trading_value", "investor_flow", "documents",
           "price_after_event", "validated_sample"}

    def ext_fail(task):
        raise nodes.ExtensionNotValidated("SENT_MODEL_UNVALIDATED")

    def base(task):
        view = lambda t, e: nodes.ConflictView(text=t, tag="Fact", evidence_links=[e])  # noqa: E731
        return nodes.NodeResult(status="SUCCESS", findings=[nodes.Finding(kind="number", text="n", tag="Fact", evidence_links=["E01"])],
                                conflicts=[nodes.Conflict(topic="수급 방향", views=[view("외국인 순매수", "S1"), view("기관 순매도", "S2")])])
    rep = nodes.run_agent_nodes(6, "005930", AS_OF, extension=True, available=ALL,
                                runners={"N11": base, "N12": ext_fail})
    c = contract.with_nodes(outs[3]["contract"], rep)
    assert contract.validate(c) == [] and contract.link_errors(c) == []
    assert [(n["nodeId"], n["state"]) for n in c["nodes"]] == [("N11", "executed"), ("N12", "skipped")]
    assert c["nodes"][1]["reason"] == "SENT_MODEL_UNVALIDATED" and c["predictionSkippedReason"] == "SENT_MODEL_UNVALIDATED"
    assert c["nodeSummary"]["executed"] == 1 and c["nodeSummary"]["base"] == 1 and c["nodeSummary"]["extSelected"] == 1
    assert len(c["conflicts"]) == 1 and [v["tag"] for v in c["conflicts"][0]["views"]] == ["Fact", "Fact"]
    assert "nodes" not in outs[3]["contract"]                              # 원본은 그대로


def test_schema_rejects_malformed_nodes_field(outs):
    c = dict(outs[1]["contract"], nodes=[{"nodeId": "5", "name": "x", "kind": "mid", "state": "executed"}])
    errs = contract.validate(c)
    assert any("nodeId" in e for e in errs) and any("kind" in e for e in errs)


def test_other_team_outputs_without_new_fields_still_validate(outs):
    c = copy.deepcopy(outs[1]["contract"])
    c["agent"].pop("agentNos")
    for cl in c["claims"]:
        cl.pop("tag")
    c["schemaVersion"] = "r4-1.3"
    assert contract.validate(c) == []                                      # 새 필드는 선택 — 다른 팀원 출력이 깨지지 않음
