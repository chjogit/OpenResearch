"""#32 점검 오탐 수정: #30 대표 문장은 통과(지우지 않음), 진짜 위반은 계속 잡힘. 노드 번호는 근거 키가 아님."""
from ch_agents import llm, node_agents
from ch_agents.facts import Facts
from ch_agents.llm import build_messages, check_output, sentence_problems
from ch_agents.semantic import direction_problems
from conftest import AS_OF, CO
from test_flow_nodes import inputs as flow_inputs


def _probs(text):
    return sentence_problems(text, {"S1", "T1"})


# ---------------------------------------------------------------- (가) 오탐
def test_negated_intent_statements_pass():
    ok = [
        "외국인 전환 확률은 과거 빈도이며 매수·매도 의도나 정보 보유를 뜻하지 않습니다.",
        "순매수·순매도 전환 기록은 매매 방향의 사실이며 매수·매도 의도나 정보 보유를 뜻하지 않는다.",
        "이 수급 흐름만으로 매수 의도를 의미한다고 볼 수 없습니다.",
        "세력의 개입 여부는 이 자료로 알 수 없습니다.",
    ]
    for t in ok:
        assert not [p for p in _probs(t) if "의도" in p], t


def test_real_intent_inference_is_still_caught():
    for t in ("외국인이 매집 의도를 가지고 있다.", "기관 세력이 매수 의도로 움직이고 있다.", "내부 정보를 알고 사는 것으로 보인다."):
        assert [p for p in _probs(t) if "의도" in p], t


def test_company_target_is_not_target_price():
    assert "목표가" not in " ".join(_probs("연간 판매·수익성 목표가 하향 조정됐다는 보도가 있습니다."))
    assert "목표가" not in " ".join(_probs("셀트리온은 매출 목표가 상향됐다고 밝혔다."))


def test_real_target_price_wording_is_still_banned():
    for t in ("목표가를 상향한다.", "증권사 목표가 하향 소식.", "목표주가는 10만원이다.", "목표 주가 제시", "TP 는 높다"):
        assert [p for p in _probs(t) if "금지 표현" in p], t


def test_negated_causation_wording_passes_and_real_causation_is_caught():
    f = Facts("S")
    f.add("주가-원/달러 상관(250일)", 0.2, "coef", "-", "t", kind="calc")   # S1
    for t in ("250일 상관 {S1}은 통계적 동조성일 뿐 기업 노출·인과를 뜻하지 않는다.",
              "250일 상관 {S1}은 통계적 동조성이며 인과를 의미하지 않습니다.",
              "250일 상관 {S1}은 인과가 아닙니다."):
        assert direction_problems(t, f) == [], t
    assert direction_problems("250일 상관 {S1}은 환율 때문에 생긴 것이다.", f)
    assert direction_problems("250일 상관 {S1}은 환율이 주가에 미친 인과를 보여 준다.", f)


# ---------------------------------------------------------------- (나) 노드 번호
def data4():
    return node_agents.build_data(4, "005930", AS_OF, extension=True, co=CO, inputs=flow_inputs())


def test_prompt_says_node_ids_are_not_evidence_keys():
    _, user = build_messages(data4(), "expert")
    assert "노드 번호" in user and "근거 키가 아니" in user


def test_node_id_as_evidence_key_is_rejected_with_reason():
    d = data4()
    res = {"핵심진단": "x", "주장": [{"문장": "호가 잔량 자료가 없어 유동성 깊이는 알 수 없다", "구분": "해석", "근거": ["N07", "N08"]}],
           "반대근거": [], "긍정요인": [], "리스크요인": [], "미확인": [], "다음점검": [], "자체점수": 5, "점수이유": "t"}
    checks = check_output(res, d)
    msg = " ".join(checks.get("근거", []))
    assert "근거 키 오류" in msg and "노드 번호는 근거 키가 아님" in msg
