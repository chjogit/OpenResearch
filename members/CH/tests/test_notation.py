"""#60 값 표기 바로잡기: 부호 중복·같은 단위 연속·값 뒤 조사. 숫자·키는 바뀌지 않는다."""
import json
import re

import pytest

from ch_agents.notation import fix_notation, notation_problems
from qa import agent as qa


@pytest.mark.parametrize("src,want", [
    ("연속 순매도 일수 1일가 1일로 집계된다", "연속 순매도 일수 1일이 1일로 집계된다"),
    ("E10 평균 감성 +-0.250, E8 -+0.500", "E10 평균 감성 -0.250, E8 +0.500"),
    ("다음 금통위까지 8일일, FOMC 41일일 후", "다음 금통위까지 8일, FOMC 41일 후"),
    ("외국인 순매수 -38,044,711주가 음수", "외국인 순매수 -38,044,711주가 음수"),         # 이미 맞는 표기는 그대로
    ("금액 -8,878,392원이 많고 3.00%가 1.63배을 넘는다", "금액 -8,878,392원이 많고 3.00%가 1.63배를 넘는다"),
    ("76백분위으로, 12일는 3개월이", "76백분위로, 12일은 3개월이"),                       # 으로/로: 받침 없음·ㄹ받침은 '로'
    ("2026-11-04 기준 5일이 아니라 3일간 2%이상", "2026-11-04 기준 5일이 아니라 3일간 2%이상"),   # 날짜·'일간'·붙은 한글은 건드리지 않음
])
def test_fix_notation_cases(src, want):
    assert fix_notation(src) == want
    assert fix_notation(want) == want and notation_problems(fix_notation(src)) == []            # 멱등, 고친 뒤 검사 0건


def test_fix_never_changes_digits():
    for src in ("일수 1일가 1일로", "감성 +-0.250 과 -+0.500", "8일일 41일일 후 -19.85%가", "3,000원원이 4배을"):
        assert re.findall(r"\d[\d,.]*", fix_notation(src)) == re.findall(r"\d[\d,.]*", src.replace("일일", "일").replace("원원", "원"))


def test_notation_problems_reports_each_kind():
    assert notation_problems("a +-0.250") == ["부호 중복"] and notation_problems("8일일") == ["같은 단위 연속"] and notation_problems("1일가") == ["값 뒤 조사 불일치"]
    assert notation_problems("감성 -0.250, 1일이 지났다") == []


def test_qa_render_fixes_sign_unit_and_josa_but_keeps_ledger_values():
    led = qa.Ledger()
    led.items.update({"S1": {"text": "1일"}, "T1": {"text": "-0.250"}, "M1": {"text": "8일"}})
    out = qa.render("연속 순매도 일수 {S1}가 {S1}로, 평균 감성 +{T1}, 금통위까지 {M1}일 남았다", led)
    assert out == "연속 순매도 일수 1일이 1일로, 평균 감성 -0.250, 금통위까지 8일 남았다" and notation_problems(out) == []


def test_contract_plain_fixes_unit_duplicate_in_next_checks():
    from ch_agents import contract

    class D:
        class facts:
            items = {"M1": {"text": "8일"}}
        docs = []

    assert contract.plain("직전 금통위 결정 후 {M1}일, 다음 점검", D) == "직전 금통위 결정 후 8일, 다음 점검"


@pytest.mark.parametrize("src,want", [
    ("전년 대비 증가한 달은 6개개, 3건건이 5점점", "전년 대비 증가한 달은 6개, 3건이 5점"),
    ("개개인 6개개인 1일일차 6개개월", "개개인 6개개인 1일일차 6개개월"),        # 뒤에 다른 한글 단어가 붙으면 건드리지 않음
])
def test_duplicate_count_units_use_same_unit_list_as_josa(src, want):
    from ch_agents import notation

    assert fix_notation(src) == want and notation_problems(want) == [] and "개|점" in notation.UNITS
