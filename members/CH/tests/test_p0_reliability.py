"""P0 신뢰성 회귀 테스트 (2026-10-28 노트북 평가에서 발견한 실패 사례).

각 테스트 이름 앞의 번호는 평가 메모의 P0 번호입니다.
"""
from ch_agents import verify as verifier
from ch_agents.agents import build_agent_data
from conftest import AS_OF, CO
from test_compute import _sent_bundle


def test_p0_3_verifier_ignores_identifiers():
    """'kic-agent-data 021 적용 전' 의 021 을 수치로 보고 문장을 지우던 오탐."""
    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    k = d.facts.key_of("외국인 20일 순매수 수량")
    for text in (
        "금리 결정 일정(core.policy_meeting 없음, kic-agent-data 021 적용 전)은 확인이 필요하다.",
        f"종목코드 005930 의 외국인 순매수는 {{{k}}}이다.",
        "sql/019 적용 후 다시 확인한다.",
    ):
        v = verifier.check_text(text, [k], d)
        assert v["ok"], (text, v["unmatched"])
    # 식별자가 아닌 진짜 숫자는 계속 잡아야 함
    bad = verifier.check_text("외국인 강도는 0.72%였고 21%로 커졌다.", [k], d)
    assert not bad["ok"]


def test_p0_4_corr_size_and_significance_are_separate():
    """250일 -0.17 은 '뚜렷', 60일 -0.16 은 '약함'으로 나와 기준이 섞이던 문제."""
    from ch_agents.facts import Facts, corr_label
    from ch_agents.semantic import direction_problems

    assert corr_label(-0.17, 250) == "상관 약함·유의함"
    assert corr_label(-0.16, 60) == "상관 약함·유의하지 않음"   # 크기는 같고 유의성만 다름
    assert corr_label(0.37, 250) == "상관 보통·유의함"
    assert corr_label(0.94, 250) == "상관 강함·유의함"
    f = Facts("M")
    k = f.add("주가-미국 10년 국채금리 상관(250일)", -0.17, "coef", "-", "t", kind="calc")
    k60 = f.add("주가-미국 10년 국채금리 상관(60일)", -0.16, "coef", "-", "t", kind="calc")
    f.flag(f"주가-미국 10년 국채금리: {corr_label(-0.17, 250)} ({{{k}}}), 최근 60일 {corr_label(-0.16, 60)} ({{{k60}}})")
    assert direction_problems(f"미국 금리와 {{{k}}}로 뚜렷한 동조를 보인다.", f)        # 크기 과장
    assert direction_problems(f"60일 상관 {{{k60}}}은 유의한 관계다.", f)                # 유의성 과장
    assert not direction_problems(f"250일 상관 {{{k}}}은 약하지만 유의하다.", f)


def _guide_facts():
    from ch_agents.facts import Facts

    f = Facts("S")
    f.add("거래대금 최근 5일 평균", 3.14e12, "KRW", "2026-10-26", "t", kind="calc")              # S1
    f.add("거래대금 직전 60일 평균(기준선)", 5.63e12, "KRW", "2026-10-26", "t", kind="calc")      # S2
    f.add("거래대금 배율(최근 5일 ÷ 직전 60일)", 0.56, "배", "2026-10-26", "t", kind="calc")      # S3
    f.add("뉴스 감성(최근 7일)", 0.255, "score", "2026-10-28", "t", kind="calc")                 # S4
    f.add("검색 관심도 배율(최근 7일 ÷ 직전 90일)", 1.44, "배", "2026-10-27", "t", kind="calc")  # S5
    f.add("외국인 5일 순매수 수량", 1417717, "주", "2026-10-26", "t", kind="calc")               # S6
    f.add("외국인 20일 순매수 수량", -23450087, "주", "2026-10-26", "t", kind="calc")            # S7
    base = [{"signal": "거래대금", "measure": "S3", "status": "평소 범위"},
            {"signal": "뉴스 논조", "measure": "S4", "status": "평소 범위"},
            {"signal": "검색 관심도", "measure": "S5", "status": "평소 범위"}]
    return f, base


def test_p0_2_direction_without_numbers_is_checked():
    """가이드 C08: 거래대금 배율 0.56배를 근거로 '거래대금 증가'라고 쓴 문장이 통과하던 문제."""
    from ch_agents.semantic import baseline_problems, direction_problems

    f, base = _guide_facts()
    c08 = ("외국인·기관 순매도와 개인 순매수, 주가 하락이 함께 나타나지만, 뉴스 논조·검색 관심·거래대금 증가는 "
           "같은 사건 묶음으로 볼 수 있어 독립 근거로 중복해 세지 않습니다.")
    assert any("S3" in p for p in direction_problems(c08, f, ["S1", "S2", "S3", "S4", "S5"]))
    assert not direction_problems("거래대금은 직전 60일보다 줄어든 상태입니다.", f, ["S1", "S2", "S3"])
    # 같은 주어(외국인 5일·20일)가 둘이면 어느 값인지 모르므로 판단하지 않음 (오탐 방지)
    assert not direction_problems("외국인은 5일은 순매수, 20일은 순매도입니다.", f, ["S6", "S7"])
    # 가이드 C07: 기준선 '평소 범위'인 검색 관심도를 '평소보다 높은 편'으로 서술
    c07 = "최근 7일 뉴스 감성은 직전 8~30일보다 소폭 높아졌고, 검색 관심도는 평소보다 높은 편입니다."
    probs = baseline_problems(c07, ["S4", "S5"], base)
    assert len(probs) == 1 and "검색 관심도" in probs[0]
    assert not baseline_problems("검색 관심도는 평소 범위 안에 있습니다.", ["S5"], base)


def test_p0_2_counter_claims_are_checked_too():
    """방향 점검이 주장만 보고 반대근거는 보지 않던 문제."""
    from ch_agents.agents import AgentData
    from ch_agents.llm import check_output

    f, base = _guide_facts()
    data = AgentData(3, "t", CO, AS_OF, f, [], "-", {"baseline": base})
    result = {"핵심진단": "-", "자체점수": 5,
              "주장": [{"문장": "외국인 20일 순매수 수량은 {S7}입니다.", "구분": "사실", "근거": ["S7"]}],
              "반대근거": [{"문장": "거래대금 증가가 동반돼 신호가 강해졌습니다.", "구분": "해석", "근거": ["S3"]}]}
    assert any("S3" in p for p in check_output(result, data)["방향"])


def test_p0_1_flow_lag_and_newer_docs_are_flagged():
    """10/28: 수급 10/26 · 가격 10/27 인데 경고 없이 '연속 순매도 3일'을 오늘 상황처럼 쓴 문제."""
    from ch_agents.agent3_sentiment_flow import flow_lag
    from ch_agents.agents import newer_docs_flag
    from ch_agents.facts import Facts

    f = Facts("S")
    assert flow_lag(f, "2026-10-26", "2026-10-27")
    assert any(x.startswith("자료 시차: 투자자별 수급은 2026-10-26까지, 가격은 2026-10-27까지") for x in f.flags)
    assert any(g["label"] == "2026-10-27 투자자별 수급" for g in f.gaps)
    assert not flow_lag(Facts("S"), "2026-10-27", "2026-10-27")
    docs = [{"published": "2026-10-27", "title": "삼성전자 외국인 순매수 전환, 6거래일 만의 동반 순매수", "summary": ""},
            {"published": "2026-10-28", "title": "반도체주 급등", "summary": "외국인 투자자의 경우 삼성전자를 순매수"},
            {"published": "2026-10-25", "title": "외국인 매도", "summary": ""},          # 장부보다 이전 → 제외
            {"published": "2026-10-28", "title": "HBM 가격 협상력", "summary": "메모리 계약"}]  # 수급 무관 → 제외
    f2 = Facts("S")
    assert newer_docs_flag(f2, docs, "2026-10-26") == 2
    assert any("최신 2026-10-28" in x and "건" not in x for x in f2.flags)


def test_p0_1_agent3_compute_reports_freshness():
    from ch_agents import agent3_sentiment_flow as sentiment

    out = sentiment.compute(_sent_bundle(), CO, AS_OF)
    fr = out["freshness"]
    assert fr["수급"] and fr["가격"] and fr["수급 지연"] == (fr["수급"] < fr["가격"])


def _samsung_terms():
    """10/28 스냅샷의 삼성전자 차입 조건 (회사채 1건, 154억 원) 과 FY2025 재무."""
    fund = {"fiscal_year": 2025, "liabilities": 130621773000000, "equity": 436320337000000,
            "operating_income": 43601051000000}
    terms = {"maturity": [{"kind": "bond", "fiscal_year": 2026, "reprt_code": "11012", "stlm_dt": "2026-06-30",
                           "total": 15415000000, "within_1y": 7707000000}],
             "bond_rate": {"stlm_dt": "2026-06-30", "n": 1, "wavg": 7.7, "min": 7.7, "max": 7.7},
             "dso": {"period_end": "2026-06-30", "report_code": "11012", "dso_days": 72.5,
                     "receivable_account": "매출채권"}}
    report = [{"fiscal_year": 2025, "metric": "fx_sens", "currency": "USD", "value": 435059000000.0,
               "change_pct": 5.0, "basis": "당기손익"}]
    return fund, terms, report


def test_p0_6_small_debt_and_few_bonds_are_marked():
    from ch_agents import exposure
    from ch_agents.facts import Facts

    fund, terms, report = _samsung_terms()
    f = Facts("M")
    rows = {r["var"]: r for r in exposure.assess(f, "반도체", fund, "2026-10-28", report=report, terms=terms)}
    k = f.key_of("사채·CP 미상환 잔액 ÷ 총부채(FY2025 부채 기준)")
    assert k and f.items[k]["value"] < 0.1
    assert any(x.startswith("규모 주의:") and f"{{{k}}}" in x for x in f.flags)
    reasons = " ".join(rows["금리"]["reasons"])
    assert "1년 내 만기 비중 (규모 작음, 참고)" in reasons and "회사채 발행금리 (규모 작음, 참고)" in reasons
    # 규모가 충분하면 표시하지 않음, 표본만 적으면 '표본 적음'
    big = dict(terms, maturity=[dict(terms["maturity"][0], total=5e12, within_1y=1e12)])
    f2 = Facts("M")
    rows2 = {r["var"]: r for r in exposure.assess(f2, "반도체", fund, "2026-10-28", report=report, terms=big)}
    assert not any(x.startswith("규모 주의:") for x in f2.flags)
    assert "회사채 발행금리 (표본 적음, 참고)" in " ".join(rows2["금리"]["reasons"])


def test_p0_5_report_basis_is_flagged_when_stale():
    from ch_agents import exposure
    from ch_agents.facts import Facts

    fund, terms, report = _samsung_terms()
    f = Facts("M")
    exposure.assess(f, "반도체", fund, "2026-10-28", report=report, terms=terms)
    fl = [x for x in f.flags if x.startswith("기준 시점 주의:")]
    assert len(fl) == 1 and "FY2025" in fl[0] and "2026-06" in fl[0]
    assert any(g["label"].startswith("최근 4개 분기(TTM) 영업이익") for g in f.gaps)
    f2 = Facts("M")
    exposure.assess(f2, "반도체", fund, "2026-03-31", report=report, terms=terms)   # 회계연도 말 직후는 표시 안 함
    assert not any(x.startswith("기준 시점 주의:") for x in f2.flags)
    # 판정 문구를 그대로 옮겨 써도 Verifier 가 날짜를 수치로 잡지 않음
    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    assert verifier.check_text(fl[0], [], d)["ok"]


def test_p0_8_claim_cap_and_stats_definition():
    """같은 입력으로 주장 7개·20개가 나오고, 표의 'Verifier 통과'가 주장 수보다 크던 문제."""
    from ch_agents.llm import MAX_CLAIMS, run_agent
    from conftest import FakeLLM

    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    k = d.facts.key_of("외국인 20일 순매수 수량")
    claim = {"문장": f"외국인은 20일간 {{{k}}}로 순매도했다.", "구분": "사실", "근거": [k]}
    res = {"핵심진단": "외국인은 순매도 우위.", "자체점수": 6, "주장": [dict(claim) for _ in range(12)],
           "리스크요인": ["외국인 순매도가 이어질 수 있음"]}
    out = run_agent(3, data=d, llm=FakeLLM(res))
    st = out["claim_stats"]
    assert st["claims"] == MAX_CLAIMS and st["trimmed"] == 12 - MAX_CLAIMS
    assert st["verified_claims"] <= st["claims"] + st["counters"]          # 주장 수를 넘을 수 없음
    assert st["checked_sentences"] >= st["verified_claims"]                 # 전체 대조 수는 따로 셈
    assert "(일부 문장 제외)" not in out["status"]                           # 상한으로 자른 것은 검증 실패가 아님


def test_p0_9_unverified_duplicates_are_merged():
    from ch_agents.contract import same_item

    pairs = [("환헤지 비율·만기", "환헤지 여부·비율"),
             ("수출 대금 결제 통화별 매출·회수 조건(결제 시점)", "수출 대금 결제 통화·결제 시점"),
             ("판가 전가력(계약 구조·경쟁 강도)", "판가 전가력"),
             ("원재료·부품 수입 비용의 달러 비중", "달러 비용 비중(원재료·부품 수입 통화)"),
             ("은행 차입 조건 및 변동·고정금리 비중", "차입 조건(변동·고정금리 비중, 만기)")]
    for a, b in pairs:
        assert same_item(a, b), (a, b)
    assert not same_item("외국인·기관 순매수의 실제 의도나 정보 보유 여부", "판가 전가력")


def test_p0_9_contract_has_no_duplicate_unverified():
    import random

    from ch_agents.llm import run_agent
    from conftest import FakeLLM
    from test_compute import _macro_bundle

    b = _macro_bundle(random.Random(7))
    d = build_agent_data(1, CO, b, AS_OF)
    prem = [p["item"] for p in d.extra.get("premises") or [] if p["status"] != "확인"]
    k = next(iter(d.facts.items))
    res = {"핵심진단": "거시 국면 점검.", "자체점수": 5,
           "주장": [{"문장": f"{d.facts.items[k]['label']}은 {{{k}}}이다.", "구분": "사실", "근거": [k]}],
           "미확인": ["환헤지 비율·만기", "판가 전가력(계약 구조·경쟁 강도)", "다음 분기 가이던스"]}
    c = run_agent(1, data=d, llm=FakeLLM(res))["contract"]
    held = [u for u in c["unverified"] if u["category"] == "판단 보류"]
    assert any(p.startswith("환헤지") for p in prem) and any(p.startswith("판가") for p in prem)
    assert not any(u["item"].startswith(("환헤지", "판가")) for u in held)   # 미확인 전제와 겹치는 항목은 합침
    assert any(u["item"] == "다음 분기 가이던스" for u in held)          # 새 항목은 그대로 남음


def test_a5_key_in_wrong_slot_is_dropped():
    """A5: 비율 키를 날짜 자리에 쓴 '기준일 46.15%' 가 미확인 항목에 그대로 남던 문제 (10/29 페르소나 점검)."""
    from ch_agents.facts import Facts
    from ch_agents.llm import sanitize
    from ch_agents.semantic import slot_problems

    f = Facts("M")
    pct = f.add("외국인 지분율", 46.15, "%", "2026-10-24", "t")
    krw = f.add("원/달러 환율", 1376.0, "KRW", "2026-10-24", "t")
    amt = f.add("총차입금", 3.2e12, "KRW", "2026-09-30", "t", kind="report")
    idx = f.add("코스피 지수", 2600.12, "idx", "2026-10-24", "t")
    assert slot_problems(f"외국인 지분율 확인 필요(기준일 {{{pct}}})", f)
    assert slot_problems(f"공시일: {{{pct}}} 이후 자료 확인", f)
    assert slot_problems(f"외국인 지분율은 {{{pct}}}%이다.", f)          # 단위 중복
    assert slot_problems(f"차입금 비중 {{{amt}}}은 공시로 확인한다.", f)   # 비율 자리에 금액
    for ok in (f"외국인 지분율은 {{{pct}}}이다.", f"원/달러 환율 {{{krw}}} 기준으로 본다.", f"환율: {{{krw}}}",
               f"외국인 지분율 {{{pct}}}일 때 기준일은 2026-10-24이다.", f"코스피는 {{{idx}}}포인트다.",
               f"총차입금 {{{amt}}}의 변동금리 비중은 미확인이다."):
        assert not slot_problems(ok, f), ok

    import random

    from test_compute import _macro_bundle

    d = build_agent_data(1, CO, _macro_bundle(random.Random(7)), AS_OF)
    k = next(k for k, v in d.facts.items.items() if v["unit"] == "%")
    res = {"핵심진단": "거시 국면 점검.", "자체점수": 5, "주장": [],
           "미확인": [f"환헤지 비율(기준일 {{{k}}})", "환헤지 비율·만기"]}
    out, removed = sanitize(res, d)
    assert out["미확인"] == ["환헤지 비율·만기"] and any("기준일" in r for r in removed)
