"""#33 부호 점검 조건절 오탐·'해석하지 않는다' 부정형, 에이전트 6 목표주가 대체 표현 지침."""
from ch_agents import node_agents
from ch_agents.facts import Facts
from ch_agents.llm import build_messages, sentence_problems
from ch_agents.semantic import direction_problems
from conftest import AS_OF, CO
from test_sentiment_nodes import inputs as sent_inputs


def _f():
    f = Facts("M")
    f.add("달러 화폐성 순자산", -915100000000, "KRW±", "2026-10-30", "t", kind="calc")        # M1 (음수 = 순부채)
    f.add("주가-원/달러 상관(250일)", 0.2, "coef", "-", "t", kind="calc")                    # M2
    f.add("외국인 순매수 수량", 120000, "주", "2026-10-30", "t", kind="calc")                 # M3
    return f


def test_conditional_clause_after_negative_value_is_not_its_predicate():
    f = _f()
    ok = [("달러 화폐성 순자산이 {M1}로 음수여서 환율 상승 시 환산 손실 방향이 있다.", None),
          ("환율이 오르면 손실이 커지는 구조다. 순자산 {M1}이 음수이므로 환율 상승 때 환산 손실이다.", None),
          ("달러 화폐성 순자산이 음수여서 환율 상승 시 환산 손실 방향이 생깁니다.", ["M1"])]
    for t, refs in ok:
        assert direction_problems(t, f, refs) == [], t


def test_same_clause_sign_violations_are_still_caught():
    f = _f()
    assert direction_problems("달러 화폐성 순자산이 {M1}로 증가했다.", f)                        # 값 - 인데 증가
    assert direction_problems("달러 화폐성 순자산이 크게 증가한 상태라 환율 변동에 안전하다.", f, ["M1"])
    assert direction_problems("외국인 순매수 수량은 {M3}로 순매도였다.", f)                        # 값 + 인데 순매도


def test_interpret_negation_forms_pass_and_real_causation_still_caught():
    f = _f()
    for t in ("원/달러 환율과 주가 간 250일 상관은 {M2}, 통계적 동조성이며 노출·인과로 해석하지 않는다.",
              "250일 상관 {M2}은 인과로 해석할 수 없습니다.",
              "250일 상관 {M2}은 노출 근거로 단정하지 못합니다."):
        assert direction_problems(t, f) == [], t
    assert direction_problems("250일 상관 {M2}은 인과로 해석된다.", f)
    assert direction_problems("250일 상관 {M2}은 환율 때문에 생긴 관계다.", f)


def test_target_price_ban_is_kept():
    for t in ("목표주가 관련 언급을 포함한 문서", "증권사 목표가 상향", "목표 주가 제시", "TP 상향"):
        assert [p for p in sentence_problems(t, set()) if "금지 표현" in p], t


def test_agent6_prompt_asks_for_neutral_wording_instead_of_target_price():
    d = node_agents.build_data(6, "005930", AS_OF, co=CO, inputs=sent_inputs())
    system, user = build_messages(d, "expert")
    assert "증권사 전망 관련 언급" in system + user and "목표주가" in system + user       # 지침에만 단어가 나옴
