"""의미 점검(방향 불일치) 테스트. 10/27 첫 Solar 실행에서 실제로 나온 오류 문장을 재현합니다."""
from ch_agents.agents import AgentData
from ch_agents.facts import Facts
from ch_agents.llm import check_output, run_agent
from ch_agents.semantic import direction_problems, flag_directions
from conftest import FakeLLM


def _facts():
    f = Facts("S")
    f.add("20일 코스피 대비 초과 수익률", 0.71, "%p", "2026-10-23", "t", kind="calc")          # S1
    f.add("외국인 20일 순매수 수량", -21805837, "주", "2026-10-23", "t", kind="calc")          # S2
    f.add("원/달러 환율 3개월 변화율", -9.87, "%chg", "2026-10-26", "t", kind="calc")          # S3
    f.add("주가-미국 10년 국채금리 상관(250일)", -0.45, "coef", "-", "t", kind="calc")       # S4
    f.add("주가-미국 10년 국채금리 상관(60일)", -0.12, "coef", "-", "t", kind="calc")        # S5
    f.add("뉴스 감성 변화", -0.187, "score", "-", "t", kind="calc")                         # S6
    f.add("한국 기준금리 12개월 변화", 0.5, "%p", "-", "t", kind="calc")                    # S7
    f.flag("20일 코스피 대비: 상회 ({S1})")
    f.flag("원/달러 3개월: 원화 강세(달러 약세) ({S3})")
    f.flag("주가-미국 10년 국채금리: 상관 강함·유의함 ({S4}), 최근 60일 상관 약함·유의하지 않음 ({S5})")
    f.flag("뉴스 논조 악화 ({S6})")
    f.flag("한국 기준금리: 인상 국면 (12개월 변화 {S7})")
    return f


def test_flag_directions_per_segment():
    d = flag_directions(_facts())
    assert d["S1"] == {"상회"} and d["S3"] == {"원화 강세"} and d["S6"] == {"악화"} and d["S7"] == {"인상"}
    assert d["S4"] == {"강함", "유의"} and d["S5"] == {"약함", "비유의"}  # 같은 판정 문장이라도 조각별로 따로 연결


def test_real_errors_from_first_run_are_caught():
    f = _facts()
    # A4: +0.71%p(상회)를 '초과 손실'로 해석
    assert direction_problems("20일 코스피 대비 초과 손실은 {S1}로 작다.", f)
    # A1: '상관 강함' 판정을 '약한 역방향 동조'로 표현
    assert direction_problems("주가는 미국 10년 국채금리와 {S4}로 약한 역방향 동조를 보인다.", f)
    # 판정과 반대 방향
    assert direction_problems("원/달러는 {S3}로 원화 약세 국면이다.", f)
    assert direction_problems("뉴스 논조는 {S6}로 개선됐다.", f)
    assert direction_problems("한국 기준금리는 {S7}로 인하 국면이다.", f)


def test_sign_mismatch():
    f = _facts()
    assert direction_problems("외국인은 20일간 {S2} 순매수했다.", f)          # 값이 - 인데 순매수
    assert direction_problems("기준금리는 {S7} 하락했다.", f)                  # 값이 + 인데 하락
    assert not direction_problems("외국인은 20일간 {S2}로 순매도했다.", f)
    assert not direction_problems("기준금리는 12개월 {S7} 올랐다.", f)


def test_correct_sentences_pass():
    f = _facts()
    ok = [
        "20일 기준 코스피를 {S1}만큼 상회했다.",
        "원/달러 3개월 변화율 {S3}로 원화 강세(달러 약세) 국면이다.",
        "미국 10년 국채금리와는 {S4}로 뚜렷한 역방향 동조이나 60일은 {S5}로 약하다.",
        "뉴스 논조는 {S6}로 악화됐다.",
        "한국 기준금리는 {S7}로 인상 국면이다.",
        "외국인 지분율 변화와 무관한 문장.",
    ]
    for t in ok:
        assert direction_problems(t, f) == [], t


def test_claim_refs_link_key_without_placeholder():
    f = _facts()
    assert direction_problems("코스피 대비 초과 손실이 제한적이다.", f, refs=["S1"])


def _data():
    return AgentData(3, "에이전트 3", {"name": "삼성전자", "ticker": "005930"}, "2026-10-26", _facts(), [], "기간")


def test_pipeline_repairs_then_removes_direction_errors():
    d = _data()
    bad = {"핵심진단": "외국인 수급은 매도 우위.",
           "주장": [{"문장": "코스피 대비 초과 손실은 {S1}로 제한적이다.", "구분": "해석", "근거": ["S1"]},
                    {"문장": "외국인은 {S2}로 순매도했다.", "구분": "사실", "근거": ["S2"]}],
           "자체점수": 6}
    assert "방향" in check_output(bad, d)
    llm = FakeLLM(bad, bad)
    out = run_agent(3, data=d, llm=llm)
    assert len(llm.calls) == 2 and "판정 방향 불일치" in llm.calls[1][-1].content  # 수정 요청에 이유 포함
    assert out["status"] == "완료 (수정 1회) (일부 문장 제외)"
    assert out["removed"] == ["코스피 대비 초과 손실은 {S1}로 제한적이다."]
    assert [c["문장"] for c in out["result"]["주장"]] == ["외국인은 {S2}로 순매도했다."]


def test_fallback_claims_from_flags_pass_direction_check():
    d = _data()
    out = run_agent(3, data=d, llm=FakeLLM(TimeoutError()))
    assert out["status"].startswith("규칙 기반 대체")
    for c in out["result"]["주장"]:
        assert direction_problems(c["문장"], d.facts, c["근거"]) == [], c


def test_misnamed_concepts():
    f = Facts("S")
    f.add("외국인 순매수일 평균 가격(60일, 근사)", 260349, "KRW", "-", "t", kind="proxy")   # S1
    f.add("주가-원/달러 상관(250일)", -0.01, "coef", "-", "t", kind="calc")              # S2
    f.add("대차잔고(주식 수)", 80501951, "주수", "-", "t")                               # S3
    assert direction_problems("현재가는 외국인 평균 매입 단가 {S1} 아래다.", f)
    assert not direction_problems("{S1}은 실제 매입 단가가 아니라 순매수일 종가의 평균이다.", f)
    assert direction_problems("환율 때문에 주가가 움직였다 ({S2}).", f)
    assert direction_problems("공매도 잔고는 {S3}이다.", f)
    assert not direction_problems("대차잔고는 {S3}로 공매도 대용 지표다.", f)
