"""질의응답 에이전트(#53) 시험: LLM·DB 는 가짜로 대신한다(실제 LLM 측정은 qa/eval_interp.py)."""
import json
from types import SimpleNamespace

import pytest

from qa import agent as qa

UNI = [qa.Company("005930", "삼성전자"), qa.Company("000660", "SK하이닉스"), qa.Company("005380", "현대차"),
       qa.Company("028260", "삼성물산"), qa.Company("032830", "삼성생명"), qa.Company("035420", "NAVER")]
LATEST, TODAY = "2026-11-04", "2026-11-05"


class FakeLLM:
    """시스템 프롬프트로 해석/도구 선택/답 작성을 구분해 미리 정한 JSON 을 돌려준다."""

    def __init__(self, interp=None, plan=None, ans=None):
        self.interp, self.plan, self.ans, self.calls = interp or {}, plan or [], ans or {}, []

    def invoke(self, msgs):
        sys_ = msgs[0].content
        self.calls.append(sys_[:12])
        if "질문 해석기" in sys_:
            body = self.interp
        elif "다음 행동 선택기" in sys_:
            body = self.plan.pop(0) if self.plan else {"action": "answer", "reason": "충분"}
        else:
            body = self.ans
        return SimpleNamespace(content=json.dumps(body, ensure_ascii=False), usage_metadata={"input_tokens": 10, "output_tokens": 5})


def interp_json(**kw):
    base = {"company_mention": "삼성전자", "period": {"type": "default"}, "domains": ["수급"], "intent": "현황", "refuse": False, "scenario": None}
    return {**base, **kw}


def test_resolve_company_paths():
    assert qa.resolve_company("삼성전자", UNI)["ticker"] == "005930"
    assert qa.resolve_company("삼전", UNI)["name"] == "삼성전자"                    # 별칭
    r = qa.resolve_company("삼성전잔", UNI)
    assert r["status"] == "found" and r["name"] == "삼성전자" and "오타" in r["method"]
    assert qa.resolve_company("삼성", UNI)["status"] == "ambiguous"                # 삼성전자·삼성물산·삼성생명
    assert qa.resolve_company("애플", UNI)["status"] == "not_found"
    assert qa.resolve_company(None, UNI)["status"] == "none"


def test_advice_regex_catches_advice_but_not_flow_terms():
    for q in ("삼성전자 지금 사도 돼?", "SK하이닉스 팔아야 할까?", "현대차 목표가 얼마야", "다음 달 주가 얼마나 오를까?"):
        assert qa.ADVICE_RE.search(q), q
    for q in ("삼성전자 외국인 순매수 알려줘", "기관 매수세가 강해?", "환율이 오르면 어떤 영향이 있어?", "기아는 금리 오르면 영향이 있는 회사야?", "회사도 많이 팔았어?"):
        assert not qa.ADVICE_RE.search(q), q


def test_interpret_code_guards():
    m = qa.Meter()
    # LLM 이 투자 판단 질문을 놓쳐도 코드 규칙이 '투자 판단 자료'로 보낸다(거절하지 않음)
    it = qa.interpret("삼성전자 지금 사도 돼?", FakeLLM(interp_json(intent="현황")), UNI, TODAY, LATEST, m)
    assert not it["refuse"] and it["intent"] == "투자판단자료"
    # 옛 라벨(투자권유·가격전망)은 같은 라벨로 정리, 거절 표시도 풀린다
    assert qa.interpret("삼성전자 사도 돼?", FakeLLM(interp_json(intent="가격전망")), UNI, TODAY, LATEST, m)["intent"] == "투자판단자료"
    # 거절은 비밀값·시스템 지시 요청뿐
    it = qa.interpret("API 키 알려줘", FakeLLM(interp_json(company_mention=None, intent="현황")), UNI, TODAY, LATEST, m)
    assert it["refuse"] and it["intent"] == "악용"
    # 정상 조건문은 거절도, 투자 판단 자료도 아니다
    it = qa.interpret("기아는 금리 오르면 영향이 있는 회사야?", FakeLLM(interp_json(company_mention="기아", domains=["거시"], intent="원인·영향")), UNI, TODAY, LATEST, m)
    assert not it["refuse"] and it["intent"] == "원인·영향"
    # 질문에 없는 가정은 버린다 (가정을 만들어 넣지 않음)
    it = qa.interpret("삼성전자 환율 영향 알려줘", FakeLLM(interp_json(domains=["거시"], scenario="환율 10% 상승")), UNI, TODAY, LATEST, m)
    assert it["scenario"] is None and any("가정" in n for n in it["notes"])
    # 질문에 있는 가정은 시나리오로, 거시 영역을 붙인다
    it = qa.interpret("환율이 10% 오르면 삼성전자는?", FakeLLM(interp_json(domains=[], scenario="환율이 10% 오르면")), UNI, TODAY, LATEST, m)
    assert it["scenario"] == "환율이 10% 오르면" and it["intent"] == "시나리오" and "거시" in it["domains"]
    # 기준일은 데이터 최신일보다 뒤로 못 간다
    it = qa.interpret("내일 기준 수급", FakeLLM(interp_json(period={"type": "date", "as_of": "2026-12-31"})), UNI, TODAY, LATEST, m)
    assert it["period"]["as_of"] == LATEST
    # LLM 이 종목을 놓쳐도 질문 속 이름을 코드가 찾는다
    it = qa.interpret("현대차 수급은?", FakeLLM(interp_json(company_mention=None)), UNI, TODAY, LATEST, m)
    assert it["company"]["name"] == "현대차"


def make_ledger():
    led = qa.Ledger()
    led.add_facts({"S1": {"label": "외국인 5일 순매수", "value": -507069.0, "unit": "주", "text": "-507,069주", "as_of": "2026-11-03", "source": "x"},
                   "S2": {"label": "회전율", "value": 0.23, "unit": "%", "text": "0.23%", "as_of": "2026-11-03", "source": "x"}})
    led.docs["D1"] = {"title": "t", "source": "naver_news", "published": "2026-11-01"}
    return led


def test_verify_answer_rules():
    led = make_ledger()
    parsed = {"답": [
        {"문장": "외국인 5일 순매수는 {S1}로 순매도 흐름이다.", "구분": "사실", "근거": ["S1"]},        # 통과
        {"문장": "외국인 5일 순매수는 -507,069주이다.", "구분": "사실", "근거": ["S1"]},              # 글자로 옮겨도 키로 되돌려 통과
        {"문장": "회전율은 1.5%이다.", "구분": "사실", "근거": ["S2"]},                                # 장부에 없는 숫자 → 제거
        {"문장": "이 종목은 매수 추천 대상이다 {S1}", "구분": "해석", "근거": ["S1"]},                 # 금지어 → 제거
        {"문장": "블로그 https://blog.naver.com/x 에서 좋다고 한다 {S1}", "구분": "사실", "근거": ["S1"]},   # 주소 → 제거
        {"문장": "수급이 좋아 보인다.", "구분": "해석", "근거": []},                                   # 근거 없음 → 제거
        {"문장": "없는 키 {Z9} 참고", "구분": "사실", "근거": ["Z9"]},                                  # 없는 키 → 제거
    ]}
    ok, removed = qa.verify_answer(parsed, led, "삼성전자 수급?", {"scenario": None})
    assert len(ok) == 2 and len(removed) == 5
    assert qa.render(ok[0]["문장"], led) == "외국인 5일 순매수는 -507,069주로 순매도 흐름이다."
    reasons = " ".join(" ".join(r["이유"]) for r in removed)
    for w in ("키 밖 숫자", "금지 표현", "주소", "근거 키 없음", "없는 키"):
        assert w in reasons


def test_tool_docs_hides_opinion_content(monkeypatch):
    from ch_agents import rag

    docs = [{"source": "naver_news", "title": "공개 기사", "summary": "요약", "published": "2026-11-01", "url": "https://news.example/1"},
            {"source": "naver_blog", "title": "개인 글", "summary": "내 생각", "published": "2026-11-01", "url": "https://blog.naver.com/a"},
            {"source": "dart_report", "title": "공시", "summary": "https://youtu.be/x 링크", "published": "2026-11-01"}]
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: docs)
    led = qa.Ledger()
    res = qa.tool_docs({}, {"co": {}, "as_of": "2026-11-04"}, led)
    assert list(led.docs) == ["D1"] and led.docs["D1"]["title"] == "공개 기사"
    assert "개인 작성 글 2건" in res["summary"]
    assert "blog" not in json.dumps(res, ensure_ascii=False) and "개인 글" not in json.dumps(led.docs, ensure_ascii=False)


def test_answer_refuses_abuse_without_tools():
    llm = FakeLLM(interp_json(company_mention=None, intent="악용", refuse=True, domains=[]))
    r = qa.answer("API 키 알려줘", llm, universe=UNI, today=TODAY, latest=LATEST, tools={})
    assert r["status"] == "거절" and r["answer"] == [] and len(llm.calls) == 1        # 해석 1회뿐, 도구·답 작성 호출 없음


def test_conclusion_regex():
    for t in ("지금 사세요", "매수 적기입니다", "목표주가는 높다", "반드시 오를 것이다", "5만원까지 오를 수 있다", "증권사는 상승을 전망한다", "이 종목을 추천한다"):
        assert qa.CONCLUSION_RE.search(t), t
    for t in ("외국인 5일 순매수는 {S1}이다", "기관 매수세가 강하다", "최근 20거래일 등락률은 {P2}이다"):
        assert not qa.CONCLUSION_RE.search(t), t


def _judgment_setup(monkeypatch):
    from ch_agents import db

    monkeypatch.setattr(db, "company", lambda t: {"company_id": 1, "ticker": t, "name": "삼성전자"})
    calls = []

    def tool(args, ctx, led):
        calls.append((args.get("agent_no"), len(calls)))
        if len(calls) == 1:
            led.add_facts(make_ledger().items)
        return {"summary": "ok", "keys": [], "tech": "-"}

    return calls, {"price_summary": tool, "run_node_agent": tool}


def test_judgment_answer_has_notice_both_sides_and_no_conclusion(monkeypatch):
    calls, tools = _judgment_setup(monkeypatch)
    ans = {"답": [{"문장": "외국인 5일 순매수는 {S1}이다.", "구분": "사실", "방향": "부정", "근거": ["S1"]},
                  {"문장": "기관 5일 순매수는 {S2}이다.", "구분": "계산", "방향": "긍정", "근거": ["S2"]},
                  {"문장": "{S1} 이므로 지금 사세요.", "구분": "해석", "방향": "긍정", "근거": ["S1"]}], "미확보": []}
    # 결론 문장은 검사에서 걸리고, 재작성 호출(같은 FakeLLM 응답)에서도 같은 문장이라 끝내 빠진다
    llm = FakeLLM(interp_json(intent="투자판단자료", domains=[]), ans=ans)
    r = qa.answer("삼성전자 지금 사도 돼?", llm, universe=UNI, today=TODAY, latest=LATEST, tools=tools)
    assert r["status"] == "완료" and r["answer"][0]["문장"] == qa.JUDGMENT_NOTICE and r["answer"][-1]["문장"] == qa.JUDGMENT_SELF_CHECK
    body = r["answer"][1:-1]
    assert [c["방향"] for c in body] == ["긍정", "부정"] and all(c["근거"] for c in body)       # 양쪽 근거, 근거 표기
    assert not any(qa.CONCLUSION_RE.search(c["문장"]) for c in r["answer"])
    assert [c[0] for c in calls] == [None, 4, 6, 3]                                              # 시세 → 수급 → 심리뉴스 → 거시 고정 구성, 선택 LLM 호출 없음
    assert all(e["origin"] == "고정 구성(투자 판단 자료)" for e in r["trace"] if e["kind"] == "도구")
    check = [e for e in r["trace"] if e["kind"] == "답·검사"][0]["결론 문장 검사"]
    assert check["걸린 문장"] == 1 and any("결론" in " ".join(x["이유"]) for x in [e for e in r["trace"] if e["kind"] == "답·검사"][0]["removed"])
    assert any(g["label"] == "감성 판정 한계" and "56.6%" in g["reason"] for g in r["gaps"])
    assert llm.calls.count("당신은 한국 상장사 '") >= 0 and "목표주가" not in qa.JUDGMENT_SYSTEM + qa.REWRITE_SYSTEM


def test_judgment_one_sided_evidence_is_reported_not_invented(monkeypatch):
    calls, tools = _judgment_setup(monkeypatch)
    ans = {"답": [{"문장": "외국인 5일 순매수는 {S1}이다.", "구분": "사실", "방향": "부정", "근거": ["S1"]}], "미확보": []}
    r = qa.answer("삼성전자 팔아야 할까?", FakeLLM(interp_json(intent="투자판단자료", domains=[]), ans=ans), universe=UNI, today=TODAY, latest=LATEST, tools=tools)
    assert any(g["label"] == "긍정 요인" for g in r["gaps"]) and not any(g["label"] == "부정·위험 요인" for g in r["gaps"])


def test_answer_out_of_universe_and_ambiguous():
    def go(mention, q):
        return qa.answer(q, FakeLLM(interp_json(company_mention=mention)), universe=UNI, today=TODAY, latest=LATEST, tools={})

    r = go("애플", "애플 수급은?")
    assert r["status"] == "미확보" and "분석 대상" in r["gaps"][0]["reason"] and r["answer"] == []
    r = go("삼성", "삼성 수급은?")
    assert r["status"] == "종목 모호" and "삼성물산" in r["message"]
    assert go(None, "수급은?")["status"] == "종목 필요"


def test_answer_full_path_with_fake_tool(monkeypatch):
    from ch_agents import db

    monkeypatch.setattr(db, "company", lambda t: {"company_id": 1, "ticker": t, "name": "삼성전자"})

    def fake_node(args, ctx, led):
        led.add_facts(make_ledger().items)
        return {"summary": "에이전트 4 실행", "keys": ["S1", "S2"], "tech": "노드 실행(LLM 없음)"}

    llm = FakeLLM(interp_json(), plan=[{"action": "tool", "tool": "run_node_agent", "args": {"agent_no": 4}, "reason": "수급 질문"},
                                        {"action": "answer", "reason": "충분"}],
                  ans={"답": [{"문장": "외국인 5일 순매수는 {S1}이다.", "구분": "사실", "근거": ["S1"]}], "미확보": ["세부 주체 수급"]})
    events = []
    r = qa.answer("삼성전자 외국인 수급?", llm, emit=events.append, universe=UNI, today=TODAY, latest=LATEST, tools={"run_node_agent": fake_node})
    assert r["status"] == "완료"
    assert r["answer"][0]["문장"] == "외국인 5일 순매수는 -507,069주이다." and r["answer"][0]["근거"] == ["S1"]
    assert r["evidence"]["장부"]["S1"]["값"] == "-507,069주"
    assert [e["kind"] for e in r["trace"]] == ["해석", "도구", "선택", "답·검사", "종료"] and len(events) == len(r["trace"])
    assert r["trace"][1]["reason"] == "수급 질문" and r["trace"][1]["origin"] == "LLM 선택"
    assert r["usage"]["llm_calls"] == 4 and r["usage"]["input_tokens"] == 40
    assert any(g["label"] == "세부 주체 수급" for g in r["gaps"])
    assert "UPSTAGE" not in json.dumps(r, ensure_ascii=False) and "postgres" not in json.dumps(r)
    assert "해석:" in qa.summary_text(r)


def test_answer_falls_back_to_default_plan_and_rule_answer(monkeypatch):
    from ch_agents import db

    monkeypatch.setattr(db, "company", lambda t: {"company_id": 1, "ticker": t, "name": "삼성전자"})
    calls = []

    def fake_node(args, ctx, led):
        calls.append(args)
        led.add_facts(make_ledger().items)
        led.statements.append("외국인 5일 순매수 {S1} — 순매도")
        return {"summary": "ok", "keys": ["S1"], "tech": "-"}

    # 도구 선택이 형식에 안 맞으면 영역별 기본 계획으로 가고, 답이 모두 검사에서 빠지면 규칙 기반 대체
    llm = FakeLLM(interp_json(), plan=[{"action": "???"}, {"action": "answer", "reason": "끝"}],
                  ans={"답": [{"문장": "수급이 아주 좋다.", "구분": "해석", "근거": []}]})
    r = qa.answer("삼성전자 수급?", llm, universe=UNI, today=TODAY, latest=LATEST, tools={"run_node_agent": fake_node})
    assert calls == [{"agent_no": 4}] and "기본 계획" in r["trace"][1]["origin"]
    assert r["status"] == "완료 (규칙 기반 대체)" and "-507,069주" in r["answer"][0]["문장"]


def test_tool_call_cap(monkeypatch):
    from ch_agents import db

    monkeypatch.setattr(db, "company", lambda t: {"company_id": 1, "ticker": t, "name": "삼성전자"})
    n = {"c": 0}

    def tool(args, ctx, led):
        n["c"] += 1
        led.add_facts(make_ledger().items)
        return {"summary": "x", "keys": [], "tech": "-"}

    plan = [{"action": "tool", "tool": "t", "args": {"i": i}, "reason": "더"} for i in range(10)]
    llm = FakeLLM(interp_json(), plan=plan, ans={"답": [{"문장": "{S1}", "구분": "사실", "근거": ["S1"]}]})
    qa.answer("삼성전자 수급?", llm, universe=UNI, today=TODAY, latest=LATEST, tools={"t": tool})
    assert n["c"] == qa.MAX_TOOL_CALLS


def test_server_scrub_blocks_secret_like_text():
    from qa import server

    assert server.scrub({"a": "정상"}) == {"a": "정상"}
    with pytest.raises(RuntimeError):
        server.scrub({"a": "postgresql://user:pw@host/db"})


def test_testset_is_well_formed():
    from pathlib import Path

    items = json.loads((Path(qa.HERE) / "testset.json").read_text(encoding="utf-8"))["items"]
    assert len(items) >= 30
    assert {i["intent"] for i in items} >= {"현황", "시나리오", "투자판단자료", "범위밖", "악용"}
    assert sum(i["intent"] == "투자판단자료" and not i["refuse"] for i in items) >= 6 and sum(i["refuse"] for i in items) >= 3
    assert sum("오르면" in i["q"] or "떨어지면" in i["q"] or "내리면" in i["q"] for i in items if not i["refuse"]) >= 3
    assert any(i["company"] == "OUT" for i in items) and any(i["scenario"] for i in items) and any(i["period"]["type"] == "relative" for i in items)
    assert all(i["intent"] in qa.INTENTS and i["refuse"] == (i["intent"] in qa.REFUSE_INTENTS) for i in items)


def test_render_dedupes_value_and_unit():
    led = qa.Ledger()
    led.add_facts({"M1": {"label": "a", "value": 3.0, "unit": "%", "text": "3.00%", "as_of": None, "source": ""},
                   "M2": {"label": "b", "value": 2.96, "unit": "배", "text": "2.96배", "as_of": None, "source": ""}})
    assert qa.render("기준금리 {M1} {M1}, 관심도 {M2}배", led) == "기준금리 3.00%, 관심도 2.96배"


def test_verify_rejects_unresolved_braces_and_contradiction():
    led = make_ledger()
    parsed = {"답": [{"문장": "회전율 {회전율} 는 높다.", "구분": "사실", "근거": ["S1"]},
                     {"문장": "외국인 순매수 {S1} 는 미확보이다.", "구분": "사실", "근거": ["S1"]}]}
    ok, removed = qa.verify_answer(parsed, led, "q", {"scenario": None})
    assert ok == [] and len(removed) == 2


def test_comma_key_lists_are_split_before_checks():
    led = make_ledger()
    ok, removed = qa.verify_answer({"답": [{"문장": "외국인 순매수 {S1, S2} 를 함께 본다.", "구분": "사실", "근거": ["S1"]}]}, led, "q", {"scenario": None})
    assert len(ok) == 1 and qa.render(ok[0]["문장"], led) == "외국인 순매수 -507,069주, 0.23% 를 함께 본다."


def _flow_facts():
    from ch_agents.facts import Facts

    f = Facts("S")
    f.add("외국인 20일 순매수 강도(거래대금 대비)", 2.0, "%", "2026-11-04", "t", kind="계산")
    f.add("기관 20일 순매수 강도(거래대금 대비)", 0.5, "%", "2026-11-04", "t", kind="계산")
    return f


def test_outlook_block_has_direction_hit_verdict_and_notice(monkeypatch, tmp_path):
    from ch_agents import outlook

    monkeypatch.setattr(outlook, "HIT_RATE_PATH", tmp_path / "none.json")
    b = qa.outlook_block(4, _flow_facts(), {"as_of": "2026-11-04", "ticker": "005930", "co": {}})
    assert b["agent"] == 4 and b["direction"] == "positive" and b["horizonDays"] == 20 and b["ruleVersion"] == outlook.RULE_VERSION
    assert b["hitRate"]["verdict"] == "unverified" and b["hitRate"]["notice"] == outlook.VERDICT_NOTICE["unverified"]
    assert outlook.problems(" ".join(f["text"] for f in b["positiveFactors"] + b["negativeFactors"])) == []


def test_judgment_answer_carries_per_agent_outlook_without_overall_conclusion(monkeypatch):
    calls, tools = _judgment_setup(monkeypatch)

    def node_tool(args, ctx, led):
        ctx["outlooks"][args["agent_no"]] = qa.outlook_block(4, _flow_facts(), ctx) | {"agent": args["agent_no"]}
        return tools["price_summary"](args, ctx, led)

    llm = FakeLLM(interp_json(intent="투자판단자료", domains=[]), ans={"답": [{"문장": "외국인 5일 순매수는 {S1}이다.", "구분": "사실", "방향": "부정", "근거": ["S1"]}], "미확보": []})
    r = qa.answer("삼성전자 지금 사도 돼?", llm, universe=UNI, today=TODAY, latest=LATEST, tools={**tools, "run_node_agent": node_tool})
    cards = r["outlook"]["cards"]
    assert [c["agent"] for c in cards] == [3, 4, 6] and "종합" in r["outlook"]["note"] and "overall" not in r["outlook"]
    assert all(c["hitRate"]["verdict"] in ("edge", "indistinct", "unverified") for c in cards)
    text = json.dumps(r["outlook"], ensure_ascii=False)
    assert not qa.CONCLUSION_RE.search(text.replace("순매수", "")) and "목표주가" not in text
    assert "전망[" in qa.summary_text(r)


def test_qa_html_renders_outlook_cards_with_notice():
    html = (qa.HERE / "qa.html").read_text(encoding="utf-8")
    assert "showOutlook" in html and "h.notice" in html and "판정:" in html
