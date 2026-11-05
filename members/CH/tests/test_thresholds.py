"""#63 검사 오탐: 판단 기준값('1배 미만')은 키 밖 숫자가 아니다. 허용 목록은 코드 상수에서 생성되고, 기준값이 아닌 숫자는 계속 막힌다."""
import pytest

from ch_agents import agent3_sentiment_flow as flow
from ch_agents import facts, llm, outlook
from ch_agents.thresholds import REFERENCE_RATIO, threshold_terms
from qa import agent as qa

VALID = {"L1", "L2", "L3", "L4"}
SENT = "거래대금 5일 평균 {L1}과 20일 평균 {L2}가 60일 평균 {L3}보다 낮고 거래대금 배율 {L4}가 1배 미만이라 최근 거래가 위축되었다."


def test_reported_sentence_passes_and_value_like_numbers_stay_blocked():
    assert llm.sentence_problems(SENT, VALID) == []
    for t in ("배율 {L4}가 1.3배 미만이다", "외국인 순매수 강도 4.7% {L4}", "환율 변화 0.2%p {L4}", "배율 3배 {L4}"):
        assert any("키 밖 숫자" in p for p in llm.sentence_problems(t, VALID)), t


def test_terms_are_generated_from_code_constants():
    terms = threshold_terms()
    assert {f"{REFERENCE_RATIO:g}배", f"{flow.TV_JUMP:g}배", f"{1 / flow.TV_JUMP:g}배", f"{facts.MAX_DAILY_MOVE * 100:g}%"} <= terms
    for rules in outlook.RULES.values():
        for r in rules:
            if r.get("unit") in ("%", "%p"):
                assert f"{r['threshold']:g}{r['unit']}" in terms                  # 전망 규칙 기준값이 바뀌면 허용 목록도 따라 바뀜
    assert "1.3배" not in terms and "0.2%p" not in terms                         # 반올림으로 다른 값이 되는 표기는 만들지 않음


def test_qa_verifier_allows_threshold_but_not_other_numbers():
    led = qa.Ledger()
    led.items.update({"L4": {"label": "거래대금 배율", "text": "0.82배", "value": 0.82}})
    ok, removed = qa.verify_answer({"답": [{"문장": SENT.replace("{L1}", "{L4}").replace("{L2}", "{L4}").replace("{L3}", "{L4}"), "구분": "해석", "방향": "부정", "근거": ["L4"]},
                                       {"문장": "배율 {L4}가 1.3배 미만이다.", "구분": "해석", "방향": "부정", "근거": ["L4"]}]}, led, "질문", {"scenario": None})
    assert len(ok) == 1 and len(removed) == 1 and "키 밖 숫자" in " ".join(removed[0]["이유"])
