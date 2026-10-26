"""LLM 계층·첨삭 모드 테스트 (가짜 LLM 사용)."""
from ch_agents.agents import build_agent_data
from ch_agents.llm import check_output, parse_json, run_agent
from ch_agents.review import check_numbers, extract_numbers, review_report
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
    assert out["status"] == "규칙 기반 대체" and out["result"]["주장"] == []  # 삼성 재무엔 경고 판정 없음
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
