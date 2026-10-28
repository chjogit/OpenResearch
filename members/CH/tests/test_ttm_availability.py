"""TTM 영업이익 연결과 미확인 항목의 '채울 방법' 분류 (계약 r4-1.1)."""
import pytest

from ch_agents import contract, exposure
from ch_agents.agent1_macro import SQL as A1_SQL
from ch_agents.agents import build_agent_data
from ch_agents.availability import availability
from ch_agents.facts import Facts
from ch_agents.llm import run_agent
from ch_agents.renderer import render
from conftest import AS_OF, CO, FakeLLM
from test_compute import _macro_bundle, _sent_bundle
from test_p0_reliability import _samsung_terms
from test_plan_r2 import REPORT

TTM = {"operating_income_ttm": 120e12, "ttm_end": "2026-06-30", "first_end": "2025-09-30", "n": 4}


def _assess(ttm):
    fund, terms, report = _samsung_terms()
    f = Facts("M")
    rows = {r["var"]: r for r in exposure.assess(f, "반도체", fund, "2026-10-28", report=report, terms=terms, ttm=ttm)}
    return f, rows


def test_ttm_ratio_is_added_and_gap_removed():
    f, rows = _assess(TTM)
    k = f.key_of("환율 10% 상승 시 손익 영향 ÷ 영업이익(TTM, 2026-06까지 4개 분기)")
    assert k and f.items[k]["value"] == pytest.approx(435059000000.0 * 2 / 120e12 * 100)
    assert f.items[k]["as_of"] == "2026-06-30" and "core.financial_quarter" in f.items[k]["source"]
    assert not any(g["label"].startswith("최근 4개 분기(TTM)") for g in f.gaps)
    fl = next(x for x in f.flags if x.startswith("기준 시점 주의:"))
    assert f"{{{k}}}" in fl                                               # 판정이 TTM 비율을 가리킴
    assert k in rows["환율"]["keys"]
    f0, rows0 = _assess(None)                                             # 등급은 같은 회계연도 비율로 정함 (바뀌지 않음)
    assert rows0["환율"]["level"] == rows["환율"]["level"]


@pytest.mark.parametrize("bad", [dict(TTM, n=3), dict(TTM, first_end="2025-03-31"), dict(TTM, operating_income_ttm=None)])
def test_ttm_needs_four_consecutive_quarters(bad):
    f, _ = _assess(bad)
    assert not f.key_of("환율 10% 상승 시 손익 영향 ÷ 영업이익(TTM, 2026-06까지 4개 분기)")
    gap = next(g for g in f.gaps if g["label"].startswith("최근 4개 분기(TTM)"))
    assert "연속 4개 분기" in gap["reason"]


def test_ttm_sql_respects_filing_deadline():
    assert "'ttm_op'" in A1_SQL and "core.financial_quarter" in A1_SQL
    assert "CASE WHEN fiscal_q = 4 THEN 90 ELSE 45 END" in A1_SQL        # 기준일에 아직 공시 전인 분기는 쓰지 않음


@pytest.mark.parametrize("item,reason,code", [
    ("2026-10-27 투자자별 수급", "수급 수집이 가격보다 늦음 (수급 마지막 2026-10-26)", "collecting"),
    ("블로그 감성 변화", "직전 기간 문서 0건·0일뿐 (수집 기간 짧음)", "collecting"),
    ("외국인 집중 매매 점검", "강도 계산에 필요한 65거래일 미만", "collecting"),
    ("금리 결정 일정", "core.policy_meeting 없음 (kic-agent-data 021 적용 전)", "collecting"),
    ("환헤지 여부·비율", "사업보고서에 외환 파생상품 사용 공시. 헤지 비율·만기는 미확인", "partial_disclosure"),
    ("차입 조건(변동·고정금리 비중, 만기)", "", "partial_disclosure"),
    ("공시 내용의 지분율·금액 등 세부 수치", "", "partial_disclosure"),
    ("판가 전가력", "", "not_disclosed"),
    ("수출 대금 결제 통화·결제 시점", "매출채권 회수기간만 확인", "not_disclosed"),
    ("달러 비용 비중(원재료·부품 수입 통화)", "", "not_disclosed"),
    ("반대 근거·하방 위험", "검증을 통과한 반대 근거와 하방 위험이 없음", "not_verified"),
    ("무엇인지 모를 항목", "", "unclassified"),
])
def test_availability_rules(item, reason, code):
    assert availability(item, reason) == code


def test_contract_carries_availability_and_validates(rng):
    b = _macro_bundle(rng)
    b["fund"] = {"fiscal_year": 2025, "liabilities": 50.0, "equity": 100.0, "operating_income": 20_000_000e6,
                 "net_income": 1.0}
    b["report"] = REPORT
    out = run_agent(1, data=build_agent_data(1, CO, b, AS_OF), llm=FakeLLM(TimeoutError()))
    c = out["contract"]
    assert c["schemaVersion"] == contract.SCHEMA_VERSION and contract.validate(c) == [] and contract.link_errors(c) == []
    assert c["unverified"] and all(u["availability"] and u["availabilityLabel"] for u in c["unverified"])
    by = {u["item"]: u["availability"] for u in c["unverified"]}
    assert by["판가 전가력"] == "not_disclosed"
    assert "| 채울 방법 |" in out["analysis"]                               # 분석 마크다운의 미확인 전제 표
    old = dict(c, schemaVersion="r4-1.0")                                  # 이전 버전 출력도 그대로 통과
    assert contract.validate(old) == []


def test_renderer_shows_availability_by_level():
    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    c = run_agent(3, data=d, llm=FakeLLM(TimeoutError()))["contract"]
    l1 = render(c, {"level": "L1"})["markdown"]
    l2 = render(c, {"level": "L2"})["markdown"]
    l3 = render(c, {"level": "L3"})["markdown"]
    assert "_(수집 중)_" in l1 and "**[수집 중]**" in l2 and "·collecting]" in l3
