"""#31 LLM 응답 폭주 방지: 출력 토큰 상한·시간 제한·프롬프트 크기 제한. 모의 LLM, 네트워크 없음."""
import time

import pytest

from ch_agents import llm, node_agents
from ch_agents.facts import Facts
from ch_agents.llm import run_node_agent
from conftest import AS_OF, CO
from test_sentiment_nodes import inputs as sent_inputs


class LengthFinishReasonError(Exception):
    """openai 가 출력 상한까지 생성하고도 JSON 이 끝나지 않을 때 내는 오류와 같은 이름."""


class APITimeoutError(Exception):
    pass


class Boom:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def invoke(self, *a, **k):
        self.calls += 1
        raise self.exc


def data6():
    return node_agents.build_data(6, "005930", AS_OF, extension=True, co=CO, inputs=sent_inputs())


def test_get_llm_sets_output_cap_timeout_and_one_retry(monkeypatch):
    monkeypatch.setenv("UPSTAGE_API_KEY", "dummy")
    m = llm.get_llm()
    assert m.max_tokens == llm.MAX_OUTPUT_TOKENS == 6000
    assert m.request_timeout == llm.CALL_TIMEOUT_S == 120.0 and m.max_retries == 1


def test_runaway_generation_falls_back_fast_with_reason():
    boom = Boom(LengthFinishReasonError("length limit reached"))
    t0 = time.monotonic()
    out = run_node_agent(6, "005930", llm=boom, data=data6())
    assert time.monotonic() - t0 < 5 and boom.calls == 1          # 다시 호출하지 않음
    assert out["status"] == "규칙 기반 대체 (LLM 출력 상한 초과)" and out["contract"]["claims"]


def test_timeout_falls_back_with_reason():
    out = run_node_agent(6, "005930", llm=Boom(APITimeoutError("timed out")), data=data6())
    assert out["status"] == "규칙 기반 대체 (LLM 호출 실패: APITimeoutError)"


def test_oversized_prompt_is_not_sent(monkeypatch):
    monkeypatch.setattr(llm, "MAX_PROMPT_CHARS", 1000)
    boom = Boom(RuntimeError("must not be called"))
    out = run_node_agent(6, "005930", llm=boom, data=data6())
    assert boom.calls == 0 and out["status"] == "규칙 기반 대체 (프롬프트 크기 초과)"
    assert out["prompt_stats"]["max_chars"] == 1000


def test_prompt_stats_are_recorded_for_normal_runs():
    out = run_node_agent(6, "005930", llm=Boom(RuntimeError("x")), data=data6())
    st = out["prompt_stats"]
    assert st["system_chars"] > 0 and st["user_chars"] > 0 and st["est_tokens"] > 0 and st["ledger_items"] > 0
    assert "ledger_trimmed" in st


def test_trim_ledger_keeps_only_events_named_in_findings():
    f = Facts("N")
    for i in range(1, 101):
        f.items[f"T{i}"] = {"label": f"사건 E{i} 평균 감성", "value": 0.1, "unit": "score", "text": "+0.10"}
    f.items["T200"] = {"label": "뉴스 감성(최근 7일)", "value": 0.2, "unit": "score", "text": "+0.20"}
    f.flags.append("사건 E1 평균 감성 {T1}")
    f.notes.append("한계 {T2}")
    dropped = node_agents.trim_ledger(f)
    assert dropped == 98 and set(f.items) == {"T1", "T2", "T200"}


def test_real_sized_event_flood_stays_within_prompt_cap():
    """사건이 수백 개여도(셀트리온 462개) 프롬프트는 상한 안."""
    docs = [{"doc_id": i, "source": "naver_news", "title": f"삼성전자 새 소식 {i} 항목 {i * 7919}", "summary": f"삼성전자 관련 별개 사건 {i} 번호 {i * 104729}",
             "url": f"u{i}", "d": AS_OF, "score": 0.3, "label": "positive", "method": "lexicon", "chunk_id": None} for i in range(1, 300)]
    d = node_agents.build_data(6, "005930", AS_OF, co=CO, inputs=sent_inputs(docs=docs))
    from ch_agents.llm import build_messages

    s, u = build_messages(d, "expert")
    assert len(s) + len(u) < llm.MAX_PROMPT_CHARS
    assert len(d.facts.items) < 120 and getattr(d.facts, "trimmed_items", 0) > 0
