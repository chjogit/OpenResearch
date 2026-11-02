"""#24 거시경제·정책(3): N05 기업별 거시 노출 / N06 거시 시나리오·민감도. 모의 입력, 네트워크·DB·LLM 없음."""
import copy
import random
import re

import pytest

from ch_agents import agent1_macro, macro_nodes, nodes
from conftest import AS_OF, CO
from test_compute import _macro_bundle
from test_plan_r2 import REPORT

FUND = {"fiscal_year": 2025, "liabilities": 50.0, "equity": 100.0, "operating_income": 20_000_000e6, "net_income": 1.0}


def bundle(**over):
    b = _macro_bundle(random.Random(7))
    b["report"] = REPORT
    b["fund"] = dict(FUND)
    b.update(over)
    return b


def run(ext=False, scenario=None, b=None, **kw):
    return macro_nodes.run_macro_agent("005930", AS_OF, extension=ext, scenario=scenario, inputs=b or bundle(), co=CO, **kw)


# ---- N05

def test_n05_matches_agent1_for_same_input():
    b = bundle()
    old = agent1_macro.compute(copy.deepcopy(b), CO, AS_OF)
    res = run()["results"]["N05"]
    led = res.artifacts["ledger"]
    assert {k: v["value"] for k, v in led.items()} == {k: v["value"] for k, v in old["facts"].items.items()}   # 지표·정적 환산 입력 값 동일
    assert [(r["variable"], r["level"]) for r in res.artifacts["exposure_table"]] == [(r["var"], r["level"]) for r in old["exposure"]]
    assert res.artifacts["unconfirmed"] and {u["item"] for u in res.artifacts["unconfirmed"]} == \
        {p["item"] for p in old["premises"] if p["status"] != "확인"}


def test_n05_separates_disclosure_facts_from_external_estimates():
    res = run()["results"]["N05"]
    rows = {r["variable"]: r for r in res.artifacts["exposure_table"]}
    assert rows["환율"]["basis"] == "공시 사실" and rows["수출·경기"]["basis"] == "공시 사실"
    assert rows["금리"]["basis"] == "외부 추정" and rows["원자재·물가"]["basis"] == "외부 추정"
    texts = [f.text for f in res.findings]
    assert all(t.startswith(("[공시 사실]", "[외부 추정]", "기준일")) for t in texts)
    kinds = res.artifacts["fact_basis"]
    led = res.artifacts["ledger"]
    assert all(kinds[k] == "공시 사실" for k, v in led.items() if v["kind"] == "회사 공시")
    assert set(kinds.values()) <= set(macro_nodes.BASIS.values())
    disclosed = [f for f in res.findings if f.tag == "Fact"]
    assert disclosed and all(f.text.startswith("[공시 사실]") for f in disclosed)


def test_n05_rows_without_evidence_are_notes_not_conclusions():
    res = run()["results"]["N05"]
    weak = [f for f in res.findings if "원자재·물가" in f.text]
    assert weak and weak[0].kind == "note" and weak[0].evidence_links == []        # 업종 기본값뿐인 등급은 결론으로 세지 않음
    assert nodes.result_problems(res) == []
    assert all(k in res.artifacts["ledger"] for f in res.findings for k in f.evidence_links)


def test_n05_marks_missing_point_in_time_history_as_limit():
    res = run()["results"]["N05"]
    assert any("Point-in-Time" in m and "수정 이력" in m for m in res.missing_items)
    assert res.artifacts["pit"]["limit"] == macro_nodes.PIT_LIMIT and res.artifacts["pit"]["grade"].startswith("D1")


def test_n05_without_company_disclosure_is_partial():
    res = run(b=bundle(report=None, fund=None))["results"]["N05"]
    assert res.status == "PARTIAL_SUCCESS" and "외부 추정" in res.reason
    assert not any(r["basis"] == "공시 사실" for r in res.artifacts["exposure_table"])


def test_values_published_after_as_of_are_not_used():
    clean = bundle()
    dirty = bundle()
    for sid, pts in dirty["series"].items():                                        # 기준일 뒤 관측을 섞음 (극단값)
        pts.append({"d": "2026-11-15", "v": 9999.0})
    dirty["index"]["^KS11"].append({"d": "2026-11-01", "v": 1.0})
    dirty["price"].append({"d": "2026-11-03", "v": 1.0})
    a = run(b=clean)["results"]["N05"]
    b = run(b=dirty)["results"]["N05"]
    assert {k: v["value"] for k, v in a.artifacts["ledger"].items()} == {k: v["value"] for k, v in b.artifacts["ledger"].items()}
    cleaned = macro_nodes.clean_inputs(dirty, AS_OF)
    assert all(p["d"] <= AS_OF for pts in cleaned["series"].values() for p in pts)
    assert all(p["d"] <= AS_OF for p in cleaned["price"])


def test_unpublished_observation_is_dropped_by_publication_rule():
    b = bundle()
    b["series"]["ECOS_BASE_RATE"].append({"d": "2026-10-01", "v": 9.99})           # 월별 지표: 10월 값은 10-26 에 아직 공표 전
    res = run(b=b)["results"]["N05"]
    assert res.artifacts["pit"]["dropped"] >= 1
    assert any("공표 전이었던 관측" in f.text for f in res.findings)
    assert 9.99 not in {v["value"] for v in res.artifacts["ledger"].values()}


def test_no_macro_series_is_data_insufficient():
    b = bundle()
    b["series"] = {}
    r = run(ext=True, scenario="환율 5% 상승", b=b)
    assert r["results"]["N05"].status == "DATA_INSUFFICIENT" and r["status"] == "DATA_INSUFFICIENT"
    assert r["nodes"][1]["state"] == "skipped" and r["counts"]["executed"] == 1


# ---- N06

def test_n06_scenario_value_equals_agent1_static_conversion():
    old = agent1_macro.compute(bundle(), CO, AS_OF, scenario="환율 5% 상승")["p01"]["scenarios"][0]
    row = run(ext=True, scenario="환율 5% 상승")["results"]["N06"].artifacts["scenario_table"][0]
    assert row["status"] == "ok" and row["effect"] == pytest.approx(old["value"])
    assert row["counter_effect"] == pytest.approx(-old["value"]) and row["disclosed_shock"] == 10.0


def test_n06_every_number_has_a_ledger_key_and_assumptions_are_stated():
    res = run(ext=True, scenario="환율 5% 상승")["results"]["N06"]
    led = res.artifacts["ledger"]
    nums = [f for f in res.findings if f.kind == "number"]
    assert len(nums) == 2 and all(f.evidence_links and all(k in led for k in f.evidence_links) for f in nums)
    assert nodes.result_problems(res) == []
    texts = " ".join(f.text for f in res.findings)
    assert "[반대 조건]" in texts and "한계:" in texts and "헤지" in texts
    assert res.artifacts["limits"] and led[nums[0].evidence_links[0]]["unit"] == "KRW±"


def test_n06_never_claims_macro_improves_earnings_forecasts():
    res = run(ext=True, scenario="환율 5% 상승")["results"]["N06"]
    blob = " ".join([f.text for f in res.findings] + [str(v) for v in res.artifacts["limits"]])
    blob += " ".join(v["note"] or "" for v in res.artifacts["ledger"].values())
    blob = blob.replace("추정 모델 미사용(실험상 예측 개선 없음)", "")                    # 개선이 없다는 PM 지정 한계 문구는 허용
    assert not re.search(r"예측(을|이)?\s*(개선|향상)|(개선|향상)(한다|시킨다|된다|시켜)", blob)
    assert "실적 예측·인과효과·확률이 아님" in blob                                 # 환산값은 예측이 아니라는 문구


def test_n06_out_of_support_shock_is_held_with_reason_and_prediction_skipped():
    res = run(ext=True, scenario="환율 30% 상승")["results"]["N06"]
    row = res.artifacts["scenario_table"][0]
    assert row["status"] == "held" and "OUT_OF_SUPPORT" in row["codes"] and "effect" not in row
    assert res.prediction_skipped_reason.startswith("SCENARIO_UNSUPPORTED") and res.status == "PARTIAL_SUCCESS"
    assert not any(f.kind == "number" for f in res.findings)                      # 숫자를 내지 않음


def test_n06_ambiguous_unit_and_causal_wording_are_held():
    res = run(ext=True, scenario="금리 0.5% 하락")["results"]["N06"]
    assert res.artifacts["scenario_table"][0]["codes"] == ["UNIT_AMBIGUOUS"]
    res2 = run(ext=True, scenario="금리 인하 때문에 환율 5% 상승")["results"]["N06"]
    assert "CAUSAL_UNIDENTIFIED" in res2.artifacts["causal_codes"]


def test_n06_without_disclosed_sensitivity_is_held_not_estimated():
    res = run(ext=True, scenario="환율 5% 상승", b=bundle(report=None))["results"]["N06"]
    assert res.artifacts["scenario_table"][0]["codes"] == ["MISSING_DISCLOSURE"] and res.prediction_skipped_reason


def test_n06_skipped_by_frame_without_scenario_assumptions():
    r = run(ext=True, scenario=None)
    ext = r["nodes"][1]
    assert ext["state"] == "skipped" and ext["missingInputs"] == ["scenario_assumptions"] and "요건" in ext["reason"]
    assert r["counts"] == {"base": 1, "extSelected": 1, "extExecuted": 0, "executed": 1} and r["status"] == "PARTIAL_SUCCESS"


def test_n06_direct_call_without_scenario_is_data_insufficient():
    res = macro_nodes.n06(bundle(), CO, AS_OF, "")
    assert res.status == "DATA_INSUFFICIENT" and res.missing_items == ["scenario_assumptions"]


# ---- 노드 틀 연결

def test_base_only_and_extension_counts():
    base_only = run(ext=False, scenario="환율 5% 상승")
    assert [n["state"] for n in base_only["nodes"]] == ["executed", "skipped"] and base_only["counts"]["executed"] == 1
    both = run(ext=True, scenario="환율 5% 상승")
    assert both["counts"] == {"base": 1, "extSelected": 1, "extExecuted": 1, "executed": 2} and both["status"] == "SUCCESS"


def test_runners_are_registered_and_use_agent_number_3():
    assert {"N05", "N06"} <= set(nodes.RUNNERS)
    assert nodes.AGENTS[3] == "거시경제·정책" and [s.node_id for s in nodes.agent_nodes(3)] == ["N05", "N06"]


def test_no_future_data_in_tool_layer_requires_as_of():
    with pytest.raises(ValueError):
        macro_nodes.run_macro_agent("005930", "", inputs=bundle(), co=CO)
    with pytest.raises(ValueError):
        macro_nodes.clean_inputs(bundle(), None)


def test_n06_states_estimation_model_is_not_used():
    res = run(ext=True, scenario="환율 5% 상승")["results"]["N06"]
    assert any("추정 모델 미사용(실험상" in x for x in res.artifacts["limits"])
    assert any("추정 모델 미사용(실험상" in f.text for f in res.findings)
