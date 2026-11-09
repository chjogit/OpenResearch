"""뉴스·공시 인용 숫자 대조(#66): 문서에 있는 숫자 통과 / 없는 숫자·값 다른 숫자·기준일 이후·목표가·가격 수준 제거."""
from __future__ import annotations

import pytest

from qa import agent as qa
from qa import citation
from test_qa_agent import make_ledger

AS_OF = "2026-10-30"


def _doc(key="D1", text="", published="2026-10-29", kind="뉴스", title="삼성전자 자사주 매입"):
    return {"key": key, "text": text, "published": published, "kind": kind, "title": title}


@pytest.mark.parametrize("a,b", [("1.8조", "1조 8천억"), ("1.8조", "1조8천억원"), ("53억", "53억원"), ("46조", "46조원"), ("12.6%", "12.6 %"),
                                 ("154,400원", "15만4400원"), ("3.05%", "-3.05%")])
def test_notations_are_normalised(a, b):
    ma, mb = citation.mentions(a)[0], citation.mentions(b)[0]
    assert citation._same(ma, mb)


@pytest.mark.parametrize("a,b", [("53억", "53억달러"), ("12.6%", "12.6%p"), ("1.8조", "1.9조"), ("5배", "5주"), ("+3%", "-3%")])
def test_different_unit_or_value_is_not_same(a, b):
    assert not citation._same(citation.mentions(a)[0], citation.mentions(b)[0])


def test_number_in_cited_document_passes_with_doc_key():
    d = _doc(text="삼성전자·SK하이닉스 자사주 매입 46조원, 거래대금 12.6% 증가")
    ok, bad = citation.check_numbers("자사주 매입은 46조, 거래대금은 12.6% 늘었다", [d], AS_OF)
    assert bad == [] and {g["doc"] for g in ok} == {"D1"} and len(ok) == 2


def test_number_not_in_document_or_with_different_value_is_removed_with_specific_reason():
    d = _doc(text="자사주 매입 46조원")
    _, bad = citation.check_numbers("자사주 매입은 50조", [d], AS_OF)
    assert bad[0]["reason"] == "인용 문서의 값과 다른 숫자"
    _, bad = citation.check_numbers("거래대금은 12.6% 늘었다", [d], AS_OF)
    assert bad[0]["reason"] == "인용 문서에 없는 숫자"
    _, bad = citation.check_numbers("자사주 매입은 46조", [], AS_OF)
    assert bad[0]["reason"] == "근거 문서 번호 없음"


def test_document_after_as_of_is_not_usable():
    d = _doc(text="자사주 매입 46조원", published="2026-11-02")
    _, bad = citation.check_numbers("자사주 매입은 46조", [d], AS_OF)
    assert bad[0]["reason"] == "인용 문서가 기준일 이후"


def test_broker_target_and_price_level_numbers_are_refused_even_if_in_document():
    d = _doc(text="목표주가 95,000원 제시, 종가 154,400원")
    for s in ("증권사는 목표주가를 95,000원으로 제시했다", "KB금융 주가는 154,400원이다", "증권사 TP 는 95,000원이다"):
        _, bad = citation.check_numbers(s, [d], AS_OF)
        assert bad and bad[0]["reason"] in ("증권사 목표·가격 전망 수치는 인용 불가", "주가·가격 수준 숫자는 인용 불가")


def test_subject_note_marks_other_subject_unless_sentence_says_it():
    d = _doc(title="삼성전자우 3.05% 하락…외국인은 53억 순매수")
    assert citation.subject_note(d, "외국인은 53억 순매수했다", "삼성전자", set()) == "삼성전자우"
    assert citation.subject_note(d, "삼성전자우는 외국인이 53억 순매수했다", "삼성전자", set()) == ""
    d2 = _doc(title="삼성전자·SK하이닉스 자사주 매입 46조")
    assert citation.subject_note(d2, "자사주 매입 46조", "삼성전자", {"sk하이닉스", "SK하이닉스"}) == "SK하이닉스"


# ---------------------------------------------------------------- verify_answer 통합

def _ledger_with_docs():
    led = make_ledger()
    led.docs["D1"] = {"title": "삼성전자·SK하이닉스 자사주 매입 46조", "source": "naver_news", "published": "2026-10-29", "kind": "뉴스"}
    led.doc_text["D1"] = "삼성전자·SK하이닉스 자사주 매입 46조원 발표, 거래대금 12.6% 증가"
    led.docs["D2"] = {"title": "주요사항보고서(자기주식취득)", "source": "dart", "published": "2026-10-28", "kind": "공시"}
    led.doc_text["D2"] = "자기주식 취득 1조 8천억원 결정"
    return led


INTERP = {"scenario": None, "period": {"as_of": AS_OF}, "company": {"name": "삼성전자", "ticker": "005930"}}


def test_verify_answer_allows_cited_news_number_with_tag_and_subject_note():
    led = _ledger_with_docs()
    parsed = {"답": [{"문장": "자사주 매입은 46조, 거래대금은 12.6% 늘었다.", "구분": "사실", "근거": ["D1"]}]}
    ok, removed = qa.verify_answer(parsed, led, "삼성전자 이슈?", INTERP)
    assert removed == [] and ok[0]["태그"] == "사실(뉴스 인용)" and ok[0]["인용"][0] == {"문서": "D1", "날짜": "2026-10-29", "종류": "뉴스"}
    assert "인용 기사의 대상: SK하이닉스" in ok[0]["문장"] or "인용 기사의 대상" in ok[0]["문장"]


def test_verify_answer_disclosure_tag_and_normalised_notation():
    led = _ledger_with_docs()
    ok, removed = qa.verify_answer({"답": [{"문장": "자기주식 취득 규모는 1.8조원이다.", "구분": "사실", "근거": ["D2"]}]}, led, "q", INTERP)
    assert removed == [] and ok[0]["태그"] == "사실(공시 인용)"


def test_verify_answer_removes_uncited_wrong_future_and_target_numbers_with_reasons():
    led = _ledger_with_docs()
    led.docs["D3"] = {"title": "미래 기사", "source": "naver_news", "published": "2026-11-03", "kind": "뉴스"}
    led.doc_text["D3"] = "매출 77조 전망"
    parsed = {"답": [
        {"문장": "자사주 매입은 46조이다.", "구분": "사실", "근거": ["S1"]},                       # 문서 번호 없이 → 제거
        {"문장": "자사주 매입은 50조이다.", "구분": "사실", "근거": ["D1"]},                       # 값 다름
        {"문장": "주가수익비율은 3배이다.", "구분": "사실", "근거": ["D1"]},                       # 문서에 없음(그 단위 수치 자체가 없음)
        {"문장": "매출은 77조이다.", "구분": "사실", "근거": ["D3"]},                              # 기준일 이후
        {"문장": "증권사 목표주가는 95,000원이다.", "구분": "사실", "근거": ["D1"]},               # 금지 표현
    ]}
    ok, removed = qa.verify_answer(parsed, led, "q", INTERP)
    assert ok == [] and len(removed) == 5
    reasons = " ".join(" ".join(r["이유"]) for r in removed)
    for w in ("키 밖 숫자", "인용 문서의 값과 다른 숫자", "인용 문서에 없는 숫자", "인용 문서가 기준일 이후", "금지 표현"):
        assert w in reasons


def test_causal_cited_sentence_is_tagged_as_interpretation():
    led = _ledger_with_docs()
    ok, _ = qa.verify_answer({"답": [{"문장": "자사주 매입 46조 때문에 매도 압력이 줄었다고 풀이된다.", "구분": "사실", "근거": ["D1"]}]}, led, "q", INTERP)
    assert ok[0]["구분"] == "해석" and ok[0]["태그"] == "해석(뉴스 인용)"


def test_answer_prompt_carries_document_excerpt_only_for_public_docs():
    led = _ledger_with_docs()
    p = qa.build_answer_prompt("q", {**INTERP, "company": {"name": "삼성전자"}}, led)
    assert "발췌: 삼성전자·SK하이닉스 자사주 매입 46조원" in p
    assert "블로그" not in p


# ---------------------------------------------------------------- 문서 검색 고정 단계

def _run(monkeypatch, tools, **kw):
    from ch_agents import db
    from test_qa_agent import LATEST, TODAY, UNI, FakeLLM, interp_json

    monkeypatch.setattr(db, "company", lambda t: {"company_id": 1, "ticker": t, "name": "삼성전자"})
    llm = FakeLLM(interp_json(**kw), plan=[{"action": "answer", "reason": "충분"}] * 3,
                  ans={"답": [{"문장": "외국인 5일 순매수는 {S1}이다.", "구분": "사실", "근거": ["S1"]}]})
    return qa.answer("삼성전자 외국인 수급?", llm, universe=UNI, today=TODAY, latest=LATEST, tools=tools)


def test_doc_search_always_runs_first_once_and_is_not_counted_against_tool_cap(monkeypatch):
    calls = []

    def doc(args, ctx, led):
        calls.append("doc")
        return {"summary": "문서 0건", "keys": [], "tech": "-"}

    def node(args, ctx, led):
        calls.append("node")
        led.add_facts(make_ledger().items)
        return {"summary": "ok", "keys": ["S1"], "tech": "-"}

    r = _run(monkeypatch, {"doc_search": doc, "run_node_agent": node})
    tools = [e for e in r["trace"] if e["kind"] == "도구"]
    assert calls == ["doc", "node"] and tools[0]["tool"] == "doc_search" and tools[0]["origin"] == "고정 단계(항상 실행)"
    assert r["status"] == "완료"


def test_doc_search_runs_for_judgment_questions_too_and_not_for_refusal(monkeypatch):
    calls = []

    def doc(args, ctx, led):
        calls.append("doc")
        return {"summary": "x", "keys": [], "tech": "-"}

    def node(args, ctx, led):
        led.add_facts(make_ledger().items)
        return {"summary": "ok", "keys": ["S1"], "tech": "-"}

    _run(monkeypatch, {"doc_search": doc, "run_node_agent": node, "price_summary": node}, intent="투자판단자료")
    assert calls == ["doc"]
    calls.clear()
    _run(monkeypatch, {"doc_search": doc, "run_node_agent": node}, refuse=True)
    assert calls == []


def test_share_price_level_with_move_words_is_refused_as_price_level():
    d = _doc(text="삼성전자 18만원에 마감, 2만100원 하락")
    _, bad = citation.check_numbers("삼성전자는 2만100원 하락한 18만 원에 마감했다", [d], AS_OF)
    assert {b["reason"] for b in bad} == {"주가·가격 수준 숫자는 인용 불가"}
    ok, bad = citation.check_numbers("자사주 매입 규모는 1조 8천억원이다", [_doc(text="자사주 1.8조원 매입, 주가 상승")], AS_OF)
    assert bad == [] and len(ok) == 1                  # 큰 금액(조·억 단위)은 가격 수준이 아님


def test_strip_targets_removes_broker_target_clauses_from_excerpt():
    t = citation.strip_targets("자사주 매입 46조원 발표. 증권사는 목표주가를 95,000원으로 제시했다. 거래대금 12.6% 증가")
    assert "46조" in t and "12.6%" in t and "95,000" not in t and "목표주가" not in t


# ---------------------------------------------------------------- #72 단위 종류·방향·전망 태그·표기 잔여물

@pytest.mark.parametrize("sent,doc", [("참여자는 1만명이다", "참여 인원 1만원"), ("3만건이 접수", "3만명 접수"), ("5만주를 매수", "5만원 상승")])
def test_count_unit_kind_must_match(sent, doc):
    _, bad = citation.check_numbers(sent, [_doc(text=doc)], AS_OF)
    assert bad and bad[0]["reason"] != ""


@pytest.mark.parametrize("sent,doc", [("신규 계좌가 1만명 늘었다", "신규 계좌 1만 명"), ("5만주 매수", "5만 주 매수"), ("순매수 53억", "순매수 53억원")])
def test_same_count_unit_passes(sent, doc):
    ok, bad = citation.check_numbers(sent, [_doc(text=doc)], AS_OF)
    assert bad == [] and len(ok) == 1


def test_people_and_won_amounts_are_different_units():
    a, b = citation.mentions("1만명")[0], citation.mentions("1만원")[0]
    assert a["unit"] == "명" and b["unit"] == "KRW" and not citation._same(a, b)
    assert citation.mentions("53억 개인 순매수")[0]["unit"] == "KRW"             # '개인' 의 '개' 는 단위 아님
    assert citation.mentions("1억 주식")[0]["unit"] == "KRW"


@pytest.mark.parametrize("sent,doc", [
    ("외국인이 순매수 53억을 기록했다", "외국인 순매도 53억원"),
    ("영업이익이 5조 증가했다", "영업이익 5조원 감소"),
    ("연결 순이익 흑자 1,200억", "순이익 적자 1200억원"),
])
def test_opposite_direction_is_removed(sent, doc):
    _, bad = citation.check_numbers(sent, [_doc(text=doc)], AS_OF)
    assert [b["reason"] for b in bad] == ["인용 문서와 방향이 반대인 숫자"]


@pytest.mark.parametrize("sent,doc", [
    ("외국인이 순매수 53억을 기록했다", "외국인 순매수 53억원"),
    ("외국인이 53억을 순매수했다", "외국인 순매수 53억원, 기관 순매도 10억원"),
    ("외국인은 53억원이다", "외국인 53억원 규모"),                      # 문서에 방향어 없음 → 통과
    ("자사주 매입 46조 때문에 매도 압력이 줄었다고 풀이된다", "자사주 매입 46조원 발표, 거래대금 12.6% 증가"),   # 방향어가 숫자와 다른 절
])
def test_same_or_unstated_direction_passes(sent, doc):
    ok, bad = citation.check_numbers(sent, [_doc(text=doc)], AS_OF)
    assert bad == [] and ok


def test_second_document_with_same_direction_rescues():
    docs = [_doc("D1", "외국인 순매도 53억원"), _doc("D2", "외국인 순매수 53억원")]
    ok, bad = citation.check_numbers("외국인이 순매수 53억", docs, AS_OF)
    assert bad == [] and ok[0]["doc"] == "D2"


def test_forecast_flag_from_sentence_or_document():
    d = _doc(text="증권사들은 올해 영업이익을 123.3조원으로 전망했다")
    ok, _ = citation.check_numbers("영업이익은 123.3조원이다", [d], AS_OF)
    assert ok[0]["forecast"] is True
    ok, _ = citation.check_numbers("증권사는 영업이익 123.3조원을 예상한다", [_doc(text="영업이익 123.3조원 기록")], AS_OF)
    assert ok[0]["forecast"] is True
    ok, _ = citation.check_numbers("영업이익은 6조원이다", [_doc(text="영업이익 6조원, 컨센서스를 상회했다")], AS_OF)
    assert ok[0]["forecast"] is False                                      # '컨센서스 상회' 는 확정 실적 설명
    ok, _ = citation.check_numbers("자사주 매입은 46조", [_doc(text="자사주 매입 46조원 발표")], AS_OF)
    assert ok[0]["forecast"] is False


def test_forecast_sentence_is_tagged_prediction_with_doc_number_and_marker():
    led = _ledger_with_docs()
    led.doc_text["D1"] = "증권사들은 삼성전자 올해 영업이익을 123.3조원으로 전망했다"
    ok, removed = qa.verify_answer({"답": [{"문장": "올해 영업이익은 123.3조원이다.", "구분": "사실", "근거": ["D1"]}]}, led, "q", INTERP)
    assert removed == [] and ok[0]["구분"] == "예측" and ok[0]["태그"] == "예측(증권사 전망 인용, D1)" and "(전망 인용)" in ok[0]["문장"] and not qa.CONCLUSION_RE.search(ok[0]["문장"])
    ok, _ = qa.verify_answer({"답": [{"문장": "자사주 매입은 46조이다.", "구분": "사실", "근거": ["D1"]}]}, _ledger_with_docs(), "q", INTERP)
    assert ok[0]["태그"] == "사실(뉴스 인용)"                                 # 전망 아닌 문서는 그대로


def test_target_price_forecast_still_refused():
    d = _doc(text="증권사 목표주가 95,000원 제시")
    _, bad = citation.check_numbers("목표주가는 95,000원이다", [d], AS_OF)
    assert bad and bad[0]["reason"] == "증권사 목표·가격 전망 수치는 인용 불가"


@pytest.mark.parametrize("raw,clean", [
    ("외국인이 순매수했다 (사실, 부정, [S1,S2…])", "외국인이 순매수했다"),
    ("거래대금이 늘었다 (해석, 중립, [S1])", "거래대금이 늘었다"),
    ("거래대금이 늘었다 [S3, D2]", "거래대금이 늘었다"),
    ("위험 요인이다 (부정, [M1])", "위험 요인이다"),
    ("지분율은 {S1}이다 (계산)", "지분율은 {S1}이다"),
    ("전년 대비 (증가율 {S1})", "전년 대비 (증가율 {S1})"),                  # 내용 있는 괄호는 남김
])
def test_strip_residue(raw, clean):
    out, _ = citation.strip_residue(raw)
    assert out == clean


def test_verify_answer_strips_internal_markers_before_saving():
    led = _ledger_with_docs()
    ok, removed = qa.verify_answer({"답": [{"문장": "외국인 5일 순매수는 {S1}이다 (사실, 부정, [S1,S2…]).", "구분": "사실", "근거": ["S1"]}]}, led, "q", INTERP)
    assert removed == [] and "(사실" not in ok[0]["문장"] and "[S1" not in ok[0]["문장"] and ok[0]["정리"] == "내부 표기 제거"
