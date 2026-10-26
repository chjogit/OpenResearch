"""LLM 계층·첨삭 모드 테스트 (가짜 LLM 사용)."""
from ch_agents.agents import build_agent_data
from ch_agents.llm import check_output, normalize_keys, parse_json, run_agent
from ch_agents.review import check_numbers, extract_numbers, review_report, style_checks
from conftest import AS_OF, CO, FakeLLM
from test_compute import _fin_bundle, _sent_bundle


def _a2():
    return build_agent_data(2, CO, _fin_bundle(), AS_OF)


def _good(d):
    k_rev = d.facts.key_of("2026년 2분기 매출 전년 동기 대비")
    k_per = d.facts.key_of("PER(TTM 기준)")
    k_per_y = d.facts.key_of("PER(연간 FY2025 기준)")
    return {
        "핵심진단": f"매출이 전년 동기 대비 {{{k_rev}}} 늘었습니다.",
        "주장": [{"문장": f"분기 매출 증가율은 {{{k_rev}}}이다.", "구분": "사실", "근거": [k_rev]},
                 {"문장": f"PER은 TTM {{{k_per}}}, 연간 {{{k_per_y}}}로 기준에 따라 다르다.", "구분": "해석",
                  "근거": [k_per, k_per_y]},
                 {"문장": "이익 증가가 이어질지는 다음 분기 공시로 확인해야 한다.", "구분": "예측", "근거": []}],
        "긍정요인": ["수익성 개선"], "리스크요인": ["변동성"], "미확인": ["EV/EBITDA"], "다음점검": ["다음 분기"],
        "자체점수": 7, "점수이유": "충분",
    }


def test_parse_json_handles_fences_and_garbage():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("설명 {\"a\": 2} 끝") == {"a": 2}
    assert parse_json("no json") is None


def test_check_output_catches_violations():
    d = _a2()
    bad = {"핵심진단": "PER 8.4배이고 목표주가는 없다 {F999}",
           "주장": [{"문장": "매출 171조원", "구분": "사실", "근거": []}, {"문장": "x", "구분": "추정", "근거": ["F1"]}],
           "자체점수": 11}
    c = check_output(bad, d)
    joined = str(c)
    for word in ("없는 키", "키 밖 숫자", "금지 표현", "근거 없는 사실", "구분 값 오류", "자체점수"):
        assert word in joined, word
    assert check_output(_good(d), d) == {}


def test_run_agent_success_renders_values():
    d = _a2()
    out = run_agent(2, data=d, llm=FakeLLM(_good(d)))
    assert out["status"] == "완료"
    assert "조원" not in out["result"]["핵심진단"]  # 결과(JSON)에는 키만
    assert "%" in out["analysis"] and "[F" in out["analysis"]  # 렌더링에서 값으로 바뀜
    assert out["source"].startswith("Neon ")


def test_run_agent_repairs_once():
    d = _a2()
    bad = _good(d)
    bad["주장"][0]["문장"] = "분기 매출은 171조원이다."
    llm = FakeLLM(bad, _good(d))
    out = run_agent(2, data=d, llm=llm)
    assert out["status"] == "완료 (수정 1회)"
    assert len(llm.calls) == 2 and "문제" in llm.calls[1][-1].content


def test_run_agent_removes_unverified_sentences_after_failed_repair():
    d = _a2()
    bad = _good(d)
    bad["주장"].append({"문장": "영업이익은 89조원이다.", "구분": "사실", "근거": ["F2"]})
    out = run_agent(2, data=d, llm=FakeLLM(bad, bad))
    assert out["status"].endswith("(일부 문장 제외)")
    assert out["removed"] == ["영업이익은 89조원이다."]
    assert "89조원" not in out["analysis"]


def test_run_agent_fallback_on_error_and_on_all_removed():
    d = _a2()
    out = run_agent(2, data=d, llm=FakeLLM(TimeoutError("solar")))
    assert out["status"] == "규칙 기반 대체"
    groups = {d.facts.items[c["근거"][0]]["group"] for c in out["result"]["주장"]}
    assert {"TTM 실적", "밸류에이션", "분기 추세"} <= groups  # 판정이 없어도 그룹별 대표 숫자로 채움
    d4 = build_agent_data(4, CO, _sent_bundle(), AS_OF)
    junk = {"핵심진단": "외국인 1,000주", "주장": [{"문장": "강도 3%", "구분": "사실", "근거": ["S1"]}], "자체점수": 5}
    out = run_agent(4, data=d4, llm=FakeLLM(junk, junk))
    assert out["status"] == "규칙 기반 대체"
    assert out["result"]["주장"] and all(c["근거"] for c in out["result"]["주장"])
    assert "외국인 1,000주" not in out["analysis"]


def test_run_agent_guide_mode_adds_glossary():
    d = _a2()
    out = run_agent(2, data=d, llm=FakeLLM(_good(d)), mode="guide")
    assert "**용어 풀이**" in out["analysis"] and "**PER**" in out["analysis"]


# ---------------------------------------------------------------- 첨삭

REPORT = """삼성전자 2분기 매출은 171.5조원으로 전년 동기 대비 130.0% 늘었다.
PER은 9.5배로 저평가다. 외국인 20일 순매수 수량은 -20,000주로 매도 우위다."""


def test_extract_numbers_units():
    nums = extract_numbers("매출 1조 2,345억원, 이익률 12.3%, 금리 +0.5%p, PER 9.5배, 주가 215,500원")
    assert [n["unit"] for n in nums] == ["조원", "%", "%p", "배", "원"]
    assert nums[0]["value"] == 1e12 + 2345e8


def test_check_numbers_verdicts():
    datas = [_a2(), build_agent_data(4, CO, _sent_bundle(), AS_OF)]
    rows = {r["text"]: r for r in check_numbers(REPORT, datas)}
    assert rows["171.5조원"]["verdict"] == "일치"
    assert rows["130.0%"]["verdict"] == "일치"  # 171.50 / 74.57 − 1 = 130.0%
    assert rows["9.5배"]["verdict"] == "불일치" and rows["9.5배"]["db_text"] == "8.36배"


def test_review_report_llm_and_fallback():
    datas = [_a2()]
    k = datas[0].facts.key_of("PER(TTM 기준)")
    good = {"빠진논점": [{"내용": "현금흐름 언급 없음", "근거": ["F20"]}],
            "수정제안": [{"원문": "PER은 9.5배로", "수정안": f"PER(TTM)은 {{{k}}}로", "근거": [k]},
                     {"원문": "저평가다", "수정안": "PER 7배라 저평가", "근거": []}],
            "잘한점": ["분기 비교"], "완성도점수": 6, "점수이유": "밸류에이션 기준 혼동"}
    out = review_report(REPORT, "005930", llm=FakeLLM(good), datas=datas)
    r = out["reviews"][0]
    assert r["status"] == "완료 (일부 문장 제외)" and r["removed"] == ["PER 7배라 저평가"]
    assert "불일치" in r["analysis"] and "8.36배" in r["analysis"]
    out = review_report(REPORT, "005930", llm=FakeLLM(TimeoutError()), datas=datas)
    assert out["reviews"][0]["status"] == "규칙 기반 대체"


def test_review_rejects_placeholder_report():
    import pytest
    with pytest.raises(ValueError):
        review_report("(여기에 첨삭할 보고서를 붙여 넣으세요)", "005930", datas=[_a2()])


def test_parse_json_skips_braces_in_preamble():
    raw = '생각: {설명} 그리고 {"x": 1} 다음이 답입니다 {"핵심진단": "a {b}", "주장": []}'
    assert parse_json(raw) == {"핵심진단": "a {b}", "주장": []}


def test_extract_numbers_man_units_and_shares_match():
    nums = extract_numbers("외국인은 20일간 2,181만주 순매도, 주가 21.55만원")
    assert [(n["unit"], n["value"]) for n in nums] == [("만주", 21810000.0), ("만원", 215500.0)]
    d4 = build_agent_data(4, CO, _sent_bundle(), AS_OF)  # 외국인 20일 = -20,000주
    rows = check_numbers("외국인 20일 순매수 수량은 -2만주였다.", [d4])
    assert rows[0]["verdict"] == "일치" and rows[0]["label"] == "외국인 20일 순매수 수량"


def test_parse_json_escaped_quotes_and_braces_in_strings():
    raw = r'{"핵심진단": "따옴표 \" 와 } 괄호", "주장": [{"문장": "\\ 백슬래시", "구분": "예측", "근거": []}]}'
    out = parse_json(raw)
    assert out["핵심진단"] == '따옴표 " 와 } 괄호' and out["주장"][0]["문장"] == "\\ 백슬래시"


def test_guide_mode_self_questions_rendered_and_checked():
    d = _a2()
    out_json = _good(d)
    out_json["스스로질문"] = ["이익 증가가 일시적인가?", "PER 8배면 싼가?"]
    out = run_agent(2, data=d, llm=FakeLLM(out_json, out_json), mode="guide")
    assert "스스로 확인해 볼 질문" in out["analysis"] and "PER 8배면 싼가?" in out["removed"]


def test_style_checks():
    rep = ("PER은 9.5배로 저평가다. PER(TTM)은 Peer 중앙값 대비 낮다.\n"
           "환율과의 상관이 높기 때문에 실적이 오른다. 외국인이 정보를 알고 사는 듯하다. 매수 추천한다.")
    got = [(x["agent_id"], x["message"]) for x in style_checks(rep)]

    def has(aid, prefix):
        return any(a == aid and m.startswith(prefix) for a, m in got)

    assert has(2, "PER의 기준") and has(2, "비교 기준 없이")
    assert has(1, "통계적 동조성을 원인") and has(4, "순매수 기록만으로") and has(0, "투자 권유 표현")
    assert len([x for x in style_checks(rep) if x["sentence"].startswith("PER(TTM)")]) == 0
    out = review_report(rep, "005930", llm=FakeLLM(TimeoutError()), datas=[_a2()])
    assert "표현 점검" in out["reviews"][0]["analysis"] and "공통 표현 점검" in out["number_check_md"]


def test_normalize_bare_keys():
    valid = {"M7", "F2", "S10"}
    assert normalize_keys("환율 M7, 이익 [F2], 강도 (S10), 없는 M99, 에이전트 A1, {M7}", valid) == \
        "환율 {M7}, 이익 {F2}, 강도 {S10}, 없는 M99, 에이전트 A1, {M7}"
    d = _a2()
    out_json = _good(d)
    k = d.facts.key_of("PER(TTM 기준)")
    out_json["주장"][1]["문장"] = f"PER(TTM)은 {k}이다."
    out = run_agent(2, data=d, llm=FakeLLM(out_json))
    assert out["status"] == "완료" and "8.36배" in out["analysis"]


def test_snapshot_roundtrip(tmp_path, monkeypatch):
    from ch_agents import db, evaluate

    monkeypatch.setattr(db, "company", lambda t: dict(CO))
    monkeypatch.setattr(evaluate, "fetch_bundle", lambda a, co, as_of: {2: _fin_bundle(), 4: _sent_bundle()}[a])
    path = evaluate.capture_snapshot("005930", str(tmp_path / "s.json"), as_of=AS_OF, agent_ids=(2, 4))
    datas = evaluate.load_snapshot(path)
    k = datas[2].facts.key_of("PER(TTM 기준)")
    assert datas[2].facts.items[k]["value"] == 8.36 and set(datas) == {2, 4}
    out = run_agent(2, data=datas[2], llm=FakeLLM(TimeoutError()))
    assert out["status"] == "규칙 기반 대체"


def test_run_agent_keeps_better_attempt():
    d = _a2()
    first = _good(d)
    first["주장"].append({"문장": "영업이익 89조원", "구분": "사실", "근거": ["F2"]})  # 문제 1건
    worse = {"핵심진단": "매출 171조원", "주장": [{"문장": "x 1%", "구분": "추정", "근거": []}], "자체점수": 0}
    out = run_agent(2, data=d, llm=FakeLLM(first, worse))
    assert out["status"] == "완료 (일부 문장 제외)"  # 첫 시도 채택 → '수정 1회' 아님
    assert out["removed"] == ["영업이익 89조원"]


def test_json_mode_falls_back_when_unsupported():
    from ch_agents import llm as L

    class Bound:
        def __init__(self, ok):
            self.ok = ok

        def invoke(self, msgs):
            if not self.ok:
                raise ValueError("400 BadRequest: response_format is not supported")

            class R:
                content = "<think>{생각}</think>" + __import__("json").dumps(_good(_a2()), ensure_ascii=False)
            return R()

    class Model(Bound):
        def bind(self, **kw):
            assert kw == {"response_format": {"type": "json_object"}}
            return Bound(False)

    L._JSON_MODE["on"] = True
    out = run_agent(2, data=_a2(), llm=Model(True))
    assert out["status"] == "완료" and L._JSON_MODE["on"] is False
    L._JSON_MODE["on"] = True
