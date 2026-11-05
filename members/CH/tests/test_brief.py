"""#64 에이전트 200자 요약(계약 r4-1.5 summary200): 길이·구성·검사·대체. 모의 입력, 네트워크·DB·실 LLM 없음."""
import json

import pytest

from ch_agents import brief, contract
from ch_agents.llm import run_node_agent
from conftest import FakeLLM
from test_node_agents import ALL, good_json


def _first_key(d):
    return next(iter(d.facts.items))


def _run(no, make, *brief_outputs):
    d = make()
    llm = FakeLLM(good_json(d), *brief_outputs) if brief_outputs else FakeLLM(good_json(d))
    return d, run_node_agent(no, "005930", llm=llm, data=d)["contract"], llm


@pytest.mark.parametrize("no,make", ALL)
def test_llm_summary_has_observation_then_code_made_outlook_tail(no, make):
    d = make()
    k = _first_key(d)
    _, c, _ = _run(no, make, {"요약": f"핵심 지표는 {{{k}}}로 확인된다."})
    s = c["summary200"]
    assert c["schemaVersion"] == "r4-1.5" and c["summary200Method"] == "llm" and 0 < len(s) <= 200
    assert d.facts.items[k]["text"] in s and "{" not in s
    assert s.endswith(brief.outlook_tail(c)) and c["outlook"]["directionLabel"] in s       # 전망 방향·판정은 코드가 붙임
    assert contract.validate(c) == []


def test_too_long_is_shortened_once_then_passes():
    no, make = ALL[1]
    d = make()
    k = _first_key(d)
    long = "관찰 " * 90 + f"{{{k}}}"
    _, c, llm = _run(no, make, {"요약": long}, {"요약": f"{{{k}}} 확인."})
    assert c["summary200Method"] == "llm-retry" and len(c["summary200"]) <= 200
    assert sum(1 for m in llm.calls if m[0].content == brief.SYSTEM) == 2


@pytest.mark.parametrize("bad", [
    "지금 매수하세요 {K}",                     # 결론
    "N05 점검 결과 {K}",                      # 내부 코드
    "외국인 4.7% 순매수",                      # 키 밖 숫자
    "관찰 {K} 이고 {Z99} 도 있다",              # 없는 키
])
def test_failed_checks_fall_back_to_rule_summary(bad):
    no, make = ALL[1]
    d = make()
    k = _first_key(d)
    bad = bad.replace("{K}", f"{{{k}}}")
    _, c, llm = _run(no, make, {"요약": bad}, {"요약": bad})
    assert c["summary200Method"] == "rule" and 0 < len(c["summary200"]) <= 200
    assert "매수하세요" not in c["summary200"] and brief.INTERNAL_CODE_RE.search(c["summary200"]) is None
    assert c["summary200"].endswith(brief.outlook_tail(c))
    assert contract.validate(c) == []


def test_never_empty_and_no_outlook_has_no_tail():
    no, make = ALL[1]
    d = make()
    d.extra.pop("outlook")
    c = run_node_agent(no, "005930", llm=FakeLLM(good_json(d)), data=d)["contract"]
    assert c["summary200"] and "20거래일 전망" not in c["summary200"] and len(c["summary200"]) <= 200


def test_old_results_without_summary200_still_validate():
    no, make = ALL[1]
    _, c, _ = _run(no, make)
    old = json.loads(json.dumps(c))
    old.pop("summary200"), old.pop("summary200Method")
    old["schemaVersion"] = "r4-1.4"
    assert contract.validate(old) == []


def test_llm_failure_gives_rule_summary_without_extra_call():
    no, make = ALL[1]
    d = make()
    llm = FakeLLM(RuntimeError("boom"))
    c = run_node_agent(no, "005930", llm=llm, data=d)["contract"]
    assert len(llm.calls) == 1 and c["summary200Method"] == "rule" and 0 < len(c["summary200"]) <= 200


def test_still_too_long_after_retry_keeps_only_leading_sentences_that_pass():
    no, make = ALL[1]
    d = make()
    k = _first_key(d)
    long = f"첫 관찰은 {{{k}}}이다. " + "둘째 문장 " * 60 + ". N05 점검이 있다. 마지막 문장이다."
    _, c, _ = _run(no, make, {"요약": long}, {"요약": long})
    assert c["summary200Method"] == "llm-trim" and len(c["summary200"]) <= 200 and c["summary200"].startswith("첫 관찰은")
    assert "N05" not in c["summary200"] and contract.validate(c) == []


@pytest.mark.parametrize("text", ["확장 노드 N12는 선택되지 않았다", "E4의 실적 경신", "D1 사후 탐색", "Point-in-Time 이력"])
def test_internal_code_regex_catches_codes_glued_to_korean_particles(text):
    assert brief.INTERNAL_CODE_RE.search(text)
    assert not brief.INTERNAL_CODE_RE.search("KB금융 3분기 12%, 2026-11-04 기준 ETF1")


def test_demo_save_check_flags_empty_long_and_coded_briefs():
    from demo import build_demo

    mk = lambda t: {"runs": {"k": {"contract": {"summary200": t}}}}
    assert build_demo.brief_hits(mk("정상 요약"), None) == []
    assert len(build_demo.brief_hits(mk(""), None)) == 1 and len(build_demo.brief_hits(mk("가" * 201), None)) == 1
    assert len(build_demo.brief_hits(mk("N12는 미실행"), None)) == 1
    qs = {"items": [{"result": {"agentBriefs": [{"agent": 4, "text": "나" * 201}], "brief": {"text": "답 요약"}}}]}
    assert len(build_demo.brief_hits(mk("정상"), qs)) == 1
