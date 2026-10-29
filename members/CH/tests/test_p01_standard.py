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


def test_prompt_carries_question_and_task_contract():
    from ch_agents.llm import build_messages

    d = build_agent_data(1, CO, _bundle(), AS_OF, {"scenario": "환율 5% 상승", "question": "다음 분기 매출은?"})
    _, user = build_messages(d)
    assert "질문: 다음 분기 매출은?" in user and "시나리오: 환율 5% 상승" in user
    assert "[과업 계약]" in user and "장부 그룹 [실적 예측(기준선)]" in user and "MODEL_NOT_APPROVED" in user


def test_user_scenario_numbers_are_terms_not_values():
    from ch_agents.llm import label_terms, sentence_problems

    d = build_agent_data(1, CO, _bundle(), AS_OF, {"scenario": "환율 5% 상승, 금리 0.5%p 하락"})
    k = next(k for k, it in d.facts.items.items() if it["group"] == "시나리오(공시 정적 환산)")
    text = f"환율 5% 상승·금리 0.5%p 하락 시나리오는 공시 민감도 기준 {{{k}}}로 환산됩니다."
    assert not [p for p in sentence_problems(text, set(d.facts.items), label_terms(d)) if "키 밖 숫자" in p]
    assert [p for p in sentence_problems("환율 7% 상승이면 …", set(d.facts.items), label_terms(d)) if "키 밖" in p]


def test_dropped_headline_falls_back_to_rule_summary():
    from conftest import FakeLLM

    d = build_agent_data(1, CO, _bundle(), AS_OF)
    k = d.facts.key_of("한국 기준금리 12개월 변화")
    res = {"핵심진단": "환율이 123.45% 올랐다.", "자체점수": 5,      # 장부에 없는 숫자 → 빠짐
           "주장": [{"문장": f"한국 기준금리 12개월 변화는 {{{k}}}이다.", "구분": "사실", "근거": [k]}]}
    out = run_agent(1, data=d, llm=FakeLLM(res), max_repair=0)
    head = out["contract"]["summary"]["text"]
    assert head.startswith("(규칙 요약) 확인한 사실:") and "{" not in head


def test_receipt_date_overrides_deadline_rule():
    """정정 보고서로 받은 값은 정정 접수일부터 이용 가능 (나중 수정값이 과거 시점에 새지 않음)."""
    from ch_agents import forecast

    r = {"pe": "2025-03-31", "fq": 1, "k": "2026-08-01"}
    assert str(forecast.known(r)) == "2026-08-01"
    assert str(forecast.known({"pe": "2025-03-31", "fq": 1})) == "2025-05-15"
    rows = [{"c": 1, "pe": "2025-03-31", "fy": 2025, "fq": 1, "v": 1.0, "k": "2026-08-01"}]
    assert forecast.company_forecast(rows, 1, "2026-07-01")["status"] == ["QUARTER_MAPPING_CONFLICT"]


V2 = [{"metric": "ir_sens_liab", "currency": "ALL", "value": -92_814e6, "change_pct": 1, "basis": "세전이익",
       "fiscal_year": 2025, "evidence": ""},
      {"metric": "fx_derivative", "currency": "ALL", "value": 1, "change_pct": None, "basis": None, "fiscal_year": 2025,
       "evidence": ""},
      {"metric": "fx_hedge_acct", "currency": "ALL", "value": 1, "change_pct": None, "basis": None, "fiscal_year": 2025,
       "evidence": ""}]


def test_v2_hedge_and_floating_debt_are_evidence_only():
    """관점 B (10-29): 헤지·변동금리 차입은 미확인 전제 상태와 근거에만 반영하고 노출 등급은 바꾸지 않음."""
    base = macro.compute(_bundle(report=REPORT), CO, AS_OF)
    v2 = macro.compute(_bundle(report=REPORT + V2), CO, AS_OF)
    assert [(r["var"], r["level"]) for r in base["exposure"]] == [(r["var"], r["level"]) for r in v2["exposure"]]
    f = v2["facts"]
    k = next(k for k, it in f.items.items() if it["label"].startswith("변동금리부 부채 추정(이자율 민감도 역산"))
    assert abs(f.items[k]["value"] - 9_281.4e9) < 1 and f.items[k]["kind"] == "대용치"
    prem = {p["item"]: p for p in v2["premises"]}
    hedge = next(p for i, p in prem.items() if i.startswith("환헤지"))
    assert hedge["status"] == "일부 확인" and "위험회피회계" in hedge["detail"]
    debt = next(p for i, p in prem.items() if i.startswith("차입"))
    assert k in debt["keys"] and "민감도 역산" in debt["detail"]
    assert not any(k in r["keys"] for r in v2["exposure"])        # 등급 근거 키에는 들어가지 않음


BORROW = {"borrow": {"fiscal_year": 2026, "report_code": "11012", "fs_div": "CFS", "period_end": "2026-06-30",
                     "total": 20_000e9, "n": 3, "accounts": "장기차입금·단기차입금·사채"}}


def test_total_borrowings_is_evidence_and_floating_share_denominator():
    """10-29: 총차입금(재무상태표 차입 계정 합)은 근거·차입 전제에만, 변동금리 추정 비중의 분모로 씀. 등급 불변."""
    base = macro.compute(_bundle(report=REPORT + V2), CO, AS_OF)
    out = macro.compute(_bundle(report=REPORT + V2, terms=BORROW), CO, AS_OF)
    assert [(r["var"], r["level"]) for r in base["exposure"]] == [(r["var"], r["level"]) for r in out["exposure"]]
    f = out["facts"]
    kb = next(k for k, it in f.items.items() if it["label"].startswith("총차입금(2026-06"))
    ks = next(k for k, it in f.items.items() if it["label"] == "변동금리부 부채 추정 ÷ 총차입금")
    assert f.items[kb]["value"] == 20_000e9 and abs(f.items[ks]["value"] - 46.407) < 0.01 and f.items[ks]["kind"] == "대용치"
    debt = next(p for p in out["premises"] if p["item"].startswith("차입"))
    assert kb in debt["keys"] and ks in debt["keys"] and "총차입금" in debt["detail"]
    assert not any(k in r["keys"] for r in out["exposure"] for k in (kb, ks))


def test_floating_estimate_larger_than_borrowings_is_not_turned_into_share():
    small = {"borrow": {**BORROW["borrow"], "total": 5_000e9}}
    out = macro.compute(_bundle(report=REPORT + V2, terms=small), CO, AS_OF)
    f = out["facts"]
    assert not any(it["label"] == "변동금리부 부채 추정 ÷ 총차입금" for it in f.items.values())
    assert any("범위 주의" in x for x in f.flags)


def test_fsc_bond_floating_share_is_evidence_only():
    terms = {**BORROW, "fsc_bonds": {"n": 3, "amount": 600e9, "floating": 150e9, "known": 600e9, "wavg": 3.1,
                                     "next_maturity": "2027-02-01"}}
    base = macro.compute(_bundle(report=REPORT), CO, AS_OF)
    out = macro.compute(_bundle(report=REPORT, terms=terms), CO, AS_OF)
    assert [(r["var"], r["level"]) for r in base["exposure"]] == [(r["var"], r["level"]) for r in out["exposure"]]
    f = out["facts"]
    k = next(k for k, it in f.items.items() if it["label"].startswith("본인 발행 회사채 중 변동금리 비중"))
    assert f.items[k]["value"] == 25.0
    debt = next(p for p in out["premises"] if p["item"].startswith("차입"))
    assert k in debt["keys"] and "고정·변동 구분은 확인" in debt["detail"]
