"""에이전트 1 제작 기준(P01 상세 개발기획서 v1.0) 연결 시험. DB·LLM 없이 합성 묶음으로 확인합니다.

합성 값은 계산·차단 규칙 검사용이며 금융 성능 근거가 아닙니다 (P01 문서 27장)."""
import random

from conftest import AS_OF, CO
from test_compute import _macro_bundle

from ch_agents import agent1_macro as macro
from ch_agents import p01, scenario, vintage
from ch_agents.agents import build_agent_data
from ch_agents.llm import run_agent


def _panel(n_co=30, quarters=10, seed=3):
    """전 종목 단독분기 매출 패널 (2024Q1~). 회사 1 이 대상."""
    rng = random.Random(seed)
    ends = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30",
            "2025-12-31", "2026-03-31", "2026-06-30"][:quarters]
    rows = []
    for c in range(1, n_co + 1):
        base = 1e12 * (1 + c / 10)
        for i, pe in enumerate(ends):
            v = base * (1 + 0.02 * i) * (1 + 0.1 * ((i % 4) == 3)) * (1 + rng.gauss(0, 0.05))
            rows.append({"c": c, "pe": pe, "fy": int(pe[:4]), "fq": i % 4 + 1, "v": v})
    return {"rows": rows}


REPORT = [{"metric": "fx_sens", "currency": "USD", "value": 1e11, "change_pct": 10, "basis": "세전손익", "fiscal_year": 2025, "evidence": ""},
          {"metric": "ir_sens", "currency": None, "value": -2e10, "change_pct": 1, "basis": "세전손익", "fiscal_year": 2025, "evidence": ""}]


def _bundle(**extra):
    b = _macro_bundle(random.Random(7))
    b["panel"] = _panel()
    b["report"] = REPORT
    b.update(extra)
    return b


def test_scenario_and_question_do_not_shadow_modules():
    """10-28 실데이터 점검에서 scenario 인자가 scenario 모듈을 가려 AttributeError 가 났던 회귀."""
    out = macro.compute(_bundle(), CO, AS_OF, scenario="환율 5% 상승, 금리 0.5%p 하락",
                        question="환율 5% 상승, 금리 0.5%p 하락이면 다음 분기 매출은?")
    plan = out["p01"]["plan"]
    assert plan["tasks"]["시나리오"]["state"] == "answered"
    assert plan["tasks"]["시나리오"]["n"] == 2              # 시나리오 칸·질문의 같은 가정은 한 번만
    assert plan["tasks"]["예측"]["state"] == "answered" and plan["tasks"]["노출"]["state"] == "answered"
    f = out["facts"]
    fx = next(it for it in f.items.values() if it["group"] == "시나리오(공시 정적 환산)" and "환율" in it["label"])
    assert abs(fx["value"] - 5e10) < 1                    # 공시 10% → +1,000억 를 5% 로 선형 환산
    ir = next(it for it in f.items.values() if it["group"] == "시나리오(공시 정적 환산)" and "금리" in it["label"])
    assert abs(ir["value"] - 1e10) < 1                    # 1%p 당 −200억, 0.5%p 하락 → +100억


def test_out_of_support_and_ambiguous_units_are_held():
    specs, codes = scenario.parse("환율 20% 상승, 금리 0.5% 하락")
    res = [scenario.evaluate(s, REPORT) for s in specs]
    assert res[0]["status"] == "held" and "OUT_OF_SUPPORT" in res[0]["codes"]   # 공시 10% 밖
    assert res[1]["status"] == "held" and "UNIT_AMBIGUOUS" in res[1]["codes"]   # % 와 %p 모호
    assert "UNIT_AMBIGUOUS" in codes


def test_causal_question_is_held_but_rest_answered():
    out = macro.compute(_bundle(), CO, AS_OF, question="금리 인하 때문에 매출이 얼마나 늘어나나?")
    plan = out["p01"]["plan"]
    assert plan["tasks"]["인과"]["state"] == "held"
    assert "CAUSAL_UNIDENTIFIED" in plan["status_codes"]
    assert plan["tasks"]["관측"]["state"] == "answered"


def test_baseline_forecast_is_not_an_approved_model():
    out = macro.compute(_bundle(), CO, AS_OF)
    fc = out["p01"]["forecast"]
    assert fc["pick"] in ("B0", "B1") and fc["target"] == "2026Q3"
    assert "MODEL_NOT_APPROVED" in fc["status"] and fc["causal_effect"] is None and not fc["publication_eligible"]
    assert fc["lower"] < fc["median"] < fc["upper"]
    assert "MODEL_NOT_APPROVED" in out["p01"]["plan"]["status_codes"]


def test_unpublished_monthly_obs_are_dropped():
    """9월 CPI(obs 9/1)는 10/5 이후에야 공개 → 10/3 기준일에서는 빠짐 (P01 7.3)."""
    pts = [("2026-08-01", 1.0), ("2026-09-01", 2.0)]
    keep, drop = vintage.filter_points("ECOS_CPI", pts, "2026-10-03")
    assert keep == [("2026-08-01", 1.0)] and drop == [("2026-09-01", 2.0)]
    keep, _ = vintage.filter_points("ECOS_CPI", pts, "2026-10-10")
    assert len(keep) == 2


def test_reference_tier_for_out_of_standard_outputs():
    out = macro.compute(_bundle(), CO, AS_OF)
    f = out["facts"]
    beta = f.items[f.key_of("주가-코스피 베타(250일)")]
    assert beta["tier"] == "reference"                     # 주가 동조성: P01 범위 밖 → 참고용
    rate = f.items[f.key_of("한국 기준금리 12개월 변화")]
    assert rate["tier"] == "core" and rate["result_type"] == "관측"
    assert "참고용(제작 기준 밖)" in f.for_prompt()


def test_contract_carries_p01_fields():
    from conftest import FakeLLM

    d = build_agent_data(1, CO, _bundle(), AS_OF, {"scenario": "환율 5% 상승"})
    k = d.facts.key_of("한국 기준금리 12개월 변화")
    res = {"핵심진단": f"기준금리 {{{k}}}.", "자체점수": 5,
           "주장": [{"문장": f"한국 기준금리 12개월 변화는 {{{k}}}이다.", "구분": "사실", "근거": [k]}]}
    c = run_agent(1, data=d, llm=FakeLLM(res))["contract"]
    assert c["p01"]["standard"].startswith("모두의리서치 P01")
    assert c["p01"]["tasks"]["시나리오"]["state"] == "answered"
    ev = next(e for e in c["evidence"] if e["ledgerKey"] == k)
    assert ev["tier"] == "core" and ev["resultType"] == "관측"
    assert set(c["p01"]["summary"]) == {"확인한 사실", "조건부 예측", "아직 답 못한 부분"}


def test_quarter_jump_is_flagged_for_review():
    b = _bundle()
    rows = b["panel"]["rows"]
    last = max((r for r in rows if r["c"] == 1), key=lambda r: r["pe"])
    last["v"] *= 3                                          # 단독분기 3배 급변 → 원문 대조 필요
    out = macro.compute(b, CO, AS_OF)
    assert out["p01"]["quarter"]["review"]
    assert "QUARTER_REVIEW" in out["p01"]["plan"]["status_codes"]
    assert any("분기 자료 검토 필요" in x for x in out["facts"].flags)


def test_summary_uses_only_ledger_keys():
    out = macro.compute(_bundle(), CO, AS_OF, scenario="환율 5% 상승")
    s = out["p01"]["summary"]
    raw = " ".join(s.values())
    assert "{M" in raw and "억원" not in raw and "조원" not in raw   # 값은 {M..} 키로만 (라벨의 가정 '5%' 는 사용자 입력)
    assert p01.STATUS_TEXT["MODEL_NOT_APPROVED"]


def test_claim_citing_only_reference_items_is_flagged():
    from ch_agents.llm import check_output

    d = build_agent_data(1, CO, _bundle(), AS_OF)
    kb = d.facts.key_of("주가-코스피 베타(250일)")
    kr = d.facts.key_of("한국 기준금리 12개월 변화")
    bad = {"핵심진단": f"시장 베타 {{{kb}}}.", "자체점수": 5,
           "주장": [{"문장": f"주가는 시장과 함께 움직인다 {{{kb}}}.", "구분": "사실", "근거": [kb]}]}
    probs = check_output(bad, d).get("근거", [])
    assert any("참고용 항목만 근거인 주장" in p for p in probs) and any("핵심진단" in p for p in probs)
    ok = {"핵심진단": f"기준금리 {{{kr}}}.", "자체점수": 5,
          "주장": [{"문장": f"기준금리 변화 {{{kr}}}, 시장 베타 {{{kb}}}.", "구분": "사실", "근거": [kr, kb]}]}
    assert not any("참고용" in p for p in check_output(ok, d).get("근거", []))
