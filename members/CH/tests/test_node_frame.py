"""#21 노드 실행 틀: 번호·노드 정의, 기본/확장 실행·스킵 보고, E1(스키마·근거 연결)·E2(상태·fallback)·E4(태그·충돌)·E5(재시도 상한)."""
import pytest
from pydantic import ValidationError

from ch_agents import nodes
from ch_agents.nodes import (Conflict, ConflictView, ExtensionNotValidated, Finding, NodeResult, NodeTask,
                             run_agent_nodes)

AS_OF = "2026-10-26"
ALL = {"macro_series", "scenario_assumptions", "price", "trading_value", "investor_flow", "documents",
       "price_after_event", "validated_sample"}


def ok(findings=None, **kw):
    return NodeResult(status="SUCCESS", findings=findings or [Finding(kind="number", text="x", tag="Fact", evidence_links=["E01"])], **kw)


def runners(**over):
    base = {n: (lambda t: ok()) for n in nodes.NODES}
    base.update(over)
    return base


# ---- 번호·노드 정의 (한곳)

def test_agent_numbers_and_node_names_are_defined_in_one_place():
    assert nodes.AGENTS == {3: "거시경제·정책", 4: "수급", 6: "투자심리·뉴스"}
    got = {(s.agent, s.kind): (s.node_id, s.name) for s in nodes.NODES.values()}
    assert got == {(3, "base"): ("N05", "Macro_Base"), (3, "ext"): ("N06", "Macro_Ext"),
                   (4, "base"): ("N07", "Flow_Base"), (4, "ext"): ("N08", "Flow_Ext"),
                   (6, "base"): ("N11", "Sentiment_Base"), (6, "ext"): ("N12", "Sentiment_Ext")}


def test_legacy_conversion_table_is_explicit_not_by_name():
    assert nodes.LEGACY_OUTPUT == {"p01": (3,), "p03": (4, 6)}
    assert nodes.legacy_agent_nos(1) == [3] and nodes.legacy_agent_nos(3) == [4, 6]   # 옛 3(투자심리·수급) ≠ 새 3(거시)
    assert nodes.legacy_agent_nos(2) == []


# ---- 기본/확장 실행·스킵과 노드 수 보고

@pytest.mark.parametrize("agent", [3, 4, 6])
def test_base_only_runs_one_node_and_reports_ext_skipped(agent):
    r = run_agent_nodes(agent, "005930", AS_OF, extension=False, available=ALL, runners=runners())
    assert [n["state"] for n in r["nodes"]] == ["executed", "skipped"]
    assert r["nodes"][1]["reason"] == "사용자가 확장 노드를 선택하지 않음"
    assert r["counts"] == {"base": 1, "extSelected": 0, "extExecuted": 0, "executed": 1}
    assert r["status"] == "SUCCESS" and r["prediction_skipped_reason"] is None


@pytest.mark.parametrize("agent", [3, 4, 6])
def test_base_plus_extension_runs_both(agent):
    r = run_agent_nodes(agent, "005930", AS_OF, extension=True, available=ALL, runners=runners())
    assert [n["state"] for n in r["nodes"]] == ["executed", "executed"]
    assert r["counts"] == {"base": 1, "extSelected": 1, "extExecuted": 1, "executed": 2}


def test_extension_with_missing_inputs_is_skipped_with_reason_and_not_counted():
    r = run_agent_nodes(4, "005930", AS_OF, extension=True, available={"price", "trading_value"}, runners=runners())
    ext = r["nodes"][1]
    assert ext["state"] == "skipped" and ext["missingInputs"] == ["investor_flow"] and "요건" in ext["reason"]
    assert r["counts"]["executed"] == 1 and r["counts"]["extSelected"] == 1 and r["counts"]["extExecuted"] == 0
    assert r["status"] == "PARTIAL_SUCCESS" and r["results"]["N07"].status == "SUCCESS"   # 기본 결과는 그대로


def test_pipeline_node_count_is_base_count_plus_executed_extensions():
    reps = [run_agent_nodes(a, "005930", AS_OF, extension=(a != 6), available=ALL, runners=runners()) for a in (3, 4, 6)]
    # CH 3개: 기본 3 + 확장 2 실행, 다른 팀원 기본 3 → 6 + 2
    assert nodes.pipeline_executed(reps) == 8


def test_unregistered_runner_is_failed_not_silently_ok(monkeypatch):
    monkeypatch.setattr(nodes, "RUNNERS", {})      # 다른 모듈(flow_nodes·macro_nodes)이 import 되며 등록한 실행 함수와 무관하게
    r = run_agent_nodes(3, "005930", AS_OF, available=ALL, runners={})
    assert r["status"] == "FAILED" and "등록되지 않음" in r["nodes"][0]["reason"]


# ---- E2 상태와 fallback

def test_base_missing_required_data_is_data_insufficient_without_calling_runner():
    called = []
    r = run_agent_nodes(6, "005930", AS_OF, extension=True, available=set(),
                        runners=runners(N11=lambda t: called.append(t) or ok()))
    assert called == []
    base = r["results"]["N11"]
    assert base.status == "DATA_INSUFFICIENT" and base.missing_items == ["documents"] and "필수 자료 결측" in base.reason
    assert r["status"] == "DATA_INSUFFICIENT"
    assert r["nodes"][1]["state"] == "skipped"          # 기본이 못 돌았으니 확장도 건너뜀


def test_extension_validation_failure_skips_prediction_and_keeps_base_result():
    def ext(task):
        raise ExtensionNotValidated("SENT_MODEL_UNVALIDATED: 사람 라벨 표본 부족")
    r = run_agent_nodes(6, "005930", AS_OF, extension=True, available=ALL, runners=runners(N12=ext))
    assert r["results"]["N11"].status == "SUCCESS" and "N12" not in r["results"]
    assert r["nodes"][1]["state"] == "skipped" and "SENT_MODEL_UNVALIDATED" in r["nodes"][1]["reason"]
    assert r["prediction_skipped_reason"].startswith("SENT_MODEL_UNVALIDATED")
    assert r["status"] == "PARTIAL_SUCCESS" and r["counts"]["executed"] == 1


def test_node_exception_becomes_failed_and_does_not_crash_others():
    def boom(task):
        raise RuntimeError("db down")
    r = run_agent_nodes(3, "005930", AS_OF, extension=True, available=ALL, runners=runners(N05=boom))
    assert r["results"]["N05"].status == "FAILED" and "RuntimeError" in r["results"]["N05"].reason
    assert r["nodes"][1]["state"] == "skipped" and r["status"] == "FAILED"


def test_four_statuses_only():
    assert nodes.STATUSES == ("SUCCESS", "PARTIAL_SUCCESS", "DATA_INSUFFICIENT", "FAILED")
    with pytest.raises(ValidationError):
        NodeResult(status="DONE")


# ---- E1 스키마·근거 연결

def test_node_task_is_a_schema_and_rejects_unknown_fields():
    t = NodeTask(task_id="t", node_id="N05", target_ticker="005930", as_of_date=AS_OF)
    assert t.input_data_ids == [] and t.parameters == {} and t.constraints == {}
    with pytest.raises(ValidationError):
        NodeTask(task_id="t", node_id="N05", target_ticker="005930", as_of_date=AS_OF, free_text="x")


def test_runner_gets_task_and_must_return_schema():
    seen = []

    def run(task):
        seen.append(task)
        return {"status": "SUCCESS", "findings": [{"kind": "number", "text": "a", "tag": "Fact", "evidence_links": ["E1"]}]}
    r = run_agent_nodes(3, "005930", AS_OF, available=ALL, runners=runners(N05=run))
    assert isinstance(seen[0], NodeTask) and seen[0].as_of_date == AS_OF and seen[0].target_ticker == "005930"
    assert isinstance(r["results"]["N05"], NodeResult)

    def bad(task):
        return {"status": "SUCCESS", "text": "자유 텍스트"}      # 스키마 밖
    r2 = run_agent_nodes(3, "005930", AS_OF, available=ALL, runners=runners(N05=bad))
    assert r2["results"]["N05"].status == "FAILED"


def test_number_or_conclusion_without_evidence_links_is_caught_and_dropped():
    bad = Finding(kind="number", text="PER 12.3", tag="Computation", evidence_links=[])
    good = Finding(kind="conclusion", text="노출 있음", tag="Interpretation", evidence_links=["D1"])
    assert nodes.result_problems(NodeResult(status="SUCCESS", findings=[bad, good])) == ["근거 연결 없음(number): PER 12.3"]
    r = run_agent_nodes(3, "005930", AS_OF, available=ALL, max_attempts=0,
                        runners=runners(N05=lambda t: NodeResult(status="SUCCESS", findings=[bad, good])))
    res = r["results"]["N05"]
    assert [f.text for f in res.findings] == ["노출 있음"]            # 근거 없는 수치는 결과에서 빠짐
    assert res.status == "PARTIAL_SUCCESS" and res.unresolved == ["근거 연결 없음(number): PER 12.3"]


# ---- E4 태그·관점별 충돌

def test_tags_and_legacy_mapping():
    assert nodes.TAGS == ("Fact", "Computation", "Prediction", "Interpretation")
    assert [nodes.legacy_tag(x) for x in ("사실", "해석", "예측", None)] == ["Fact", "Interpretation", "Prediction", "Interpretation"]
    assert nodes.legacy_tag("사실", computed_only=True) == "Computation" and nodes.legacy_tag("해석", computed_only=True) == "Interpretation"
    with pytest.raises(ValidationError):
        Finding(text="x", tag="Opinion")


def test_conflict_keeps_opposing_views_side_by_side_without_average():
    v1 = ConflictView(text="외국인 순매수 확대", tag="Fact", evidence_links=["S1"])
    v2 = ConflictView(text="기관 순매도 지속", tag="Fact", evidence_links=["S2"])
    c = Conflict(topic="수급 방향", views=[v1, v2])
    assert nodes.result_problems(NodeResult(status="SUCCESS", conflicts=[c])) == []
    assert "average" not in c.model_dump() and len(c.views) == 2
    with pytest.raises(ValidationError):
        Conflict(topic="t", views=[v1], average=0.0)                      # 평균 필드 없음(금지)
    one = Conflict(topic="t", views=[v1])
    assert nodes.result_problems(NodeResult(status="SUCCESS", conflicts=[one])) == ["관점별 충돌에 관점이 2개 미만: t"]


# ---- E5 재시도 상한

def test_repair_limit_default_is_one_and_configurable(monkeypatch):
    monkeypatch.delenv("CH_MAX_REPAIR_ATTEMPTS", raising=False)
    assert nodes.max_repair_attempts() == 1
    monkeypatch.setenv("CH_MAX_REPAIR_ATTEMPTS", "2")
    assert nodes.max_repair_attempts() == 2
    monkeypatch.setenv("CH_MAX_REPAIR_ATTEMPTS", "9")
    assert nodes.max_repair_attempts() == 2                               # 상한 2
    monkeypatch.setenv("CH_MAX_REPAIR_ATTEMPTS", "abc")
    assert nodes.max_repair_attempts() == 1


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_repair_loop_stops_at_limit_and_marks_unresolved(limit):
    calls = []

    def always_bad(task):
        calls.append(task.parameters.get("repair"))
        return NodeResult(status="SUCCESS", findings=[Finding(kind="number", text="n", evidence_links=[])])
    r = run_agent_nodes(3, "005930", AS_OF, available=ALL, max_attempts=limit, runners=runners(N05=always_bad))
    assert len(calls) == limit + 1                                        # 호출 = 1 + 재시도 상한, 그 이상 반복하지 않음
    assert calls[0] is None and all(c for c in calls[1:])                 # 재시도 때만 문제 목록을 힌트로 전달
    res = r["results"]["N05"]
    assert res.unresolved and res.execution_meta.attempts == limit + 1


def test_repair_succeeds_on_retry_without_unresolved():
    def fixes_itself(task):
        links = ["E1"] if task.parameters.get("repair") else []
        return NodeResult(status="SUCCESS", findings=[Finding(kind="number", text="n", evidence_links=links)])
    r = run_agent_nodes(3, "005930", AS_OF, available=ALL, max_attempts=1, runners=runners(N05=fixes_itself))
    res = r["results"]["N05"]
    assert res.status == "SUCCESS" and res.unresolved == [] and res.execution_meta.attempts == 2


def test_run_agent_uses_the_same_repair_limit(monkeypatch):
    """기존 '수정 1회' 루프도 같은 상한을 쓴다: 인자를 안 주면 MAX_REPAIR_ATTEMPTS."""
    import inspect

    from ch_agents.llm import run_agent
    assert inspect.signature(run_agent).parameters["max_repair"].default is None


def test_unknown_agent_number_is_rejected():
    with pytest.raises(KeyError):
        run_agent_nodes(1, "005930", AS_OF)       # 옛 번호는 노드 틀로 직접 부르지 않음 (변환표 사용)
    with pytest.raises(ValueError):
        run_agent_nodes(3, "005930", "")          # E3: 기준일 필수
