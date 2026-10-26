"""에이전트 등록부와 데이터 준비 (DB 조회 → 순수 계산)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any

from . import db, financial, macro, sentiment
from .facts import Facts

KST = timezone(timedelta(hours=9))


@dataclass
class AgentSpec:
    agent_id: int
    name: str
    module: ModuleType
    role: str
    checklist: list[str]
    next_checks: list[str]


@dataclass
class AgentData:
    agent_id: int
    name: str
    company: dict
    as_of: str
    facts: Facts
    docs: list[dict]
    period: str
    extra: dict[str, Any] = field(default_factory=dict)


AGENTS: dict[int, AgentSpec] = {
    1: AgentSpec(
        1, "거시경제 및 변수 민감도 분석 에이전트 (Macro & Sensitivity)", macro,
        role=("금리·환율·물가·반도체 수출 등 거시변수의 최근 변화와 국면을 진단하고, 그 변화가 이 기업의 매출·비용·수요·"
              "할인율로 전달되는 경로를 설명합니다. 동조성 수치는 통계적 관계일 뿐 기업의 환율 노출이 아닙니다."),
        checklist=[
            "현재 금리·환율·물가 국면 (코드 판정 문장의 키를 인용)",
            "이 업종의 전달 경로 중 지금 가장 영향이 큰 경로 1~2개와 그 이유",
            "주가와 거시변수의 동조성: 뚜렷한 것과 약한 것을 구분, 60일과 250일이 다르면 언급",
            "판단에 필요하지만 DB에 없는 변수(기업 노출, 유가 등)를 미확인에 명시",
        ],
        next_checks=["다음 한국은행 금리 결정과 원/달러 방향", "다음 달 관세청 수출 통계", "미국 물가 발표"],
    ),
    2: AgentSpec(
        2, "재무·밸류에이션 및 건전성 분석 에이전트 (Financial & Risk)", financial,
        role=("TTM 실적과 분기 추세, 밸류에이션(자기 PER 밴드와 Peer 대비 위치), 현금흐름과 주주환원, 부채·이자 감당력을 "
              "심사합니다. PER은 TTM 기준과 연간 기준을 반드시 구분하고, 대용치는 대용치라고 밝힙니다."),
        checklist=[
            "이익의 방향: 최근 분기 전년 동기 대비와 이익률 흐름",
            "밸류에이션: PER(TTM)·PER(연간) 구분, 자기 밴드 내 위치, Peer 중앙값 대비",
            "현금 창출력: 영업현금흐름·설비투자·FCF와 주주환원",
            "건전성: 부채비율, 이자보상배율 대용치, 코드 경고",
            "이익이 급변한 시기라면 PER이 낮거나 높은 이유가 이익 변화 때문일 수 있음을 언급",
        ],
        next_checks=["다음 분기 실적 공시의 매출·영업이익률", "사업보고서의 설비투자 계획", "Peer 실적 발표"],
    ),
    4: AgentSpec(
        4, "투자심리 및 수급 분석 에이전트 (Sentiment & Supply/Demand)", sentiment,
        role=("외국인·기관·개인 수급의 기간별 흐름과 강도, 외국인 지분율 변화, 뉴스·커뮤니티 논조, 검색 관심도, 시장 전반의 "
              "위험 선호를 분석합니다. 근거는 수급·논조·관심·가격 네 계열로 나누고, 같은 계열 안의 지표는 하나의 근거로 셉니다. "
              "순매수 기록만으로 매수 의도나 정보 보유를 추정하지 않습니다."),
        checklist=[
            "수급: 주체별 5·20·60일 흐름이 같은 방향인지, 강도와 연속 일수",
            "외국인 지분율의 변화와 1년 범위 내 위치",
            "논조·관심: 감성 점수는 키워드 사전 기반이라는 한계와 함께",
            "가격과 수급의 엇갈림, 시장 전반(VIX·코스피 대비) 맥락",
        ],
        next_checks=["외국인 순매수 방향 전환 여부(5일 기준)", "대차잔고 수집 재개 후 추이", "검색 관심도 급변"],
    ),
}


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def fetch_bundle(agent_id: int, co: dict, as_of: str) -> dict:
    mod = AGENTS[agent_id].module
    return db.bundle(mod.SQL, mod.params(co, as_of))


def build_agent_data(agent_id: int, co: dict, bundle: dict, as_of: str) -> AgentData:
    spec = AGENTS[agent_id]
    out = spec.module.compute(bundle, co, as_of)
    extra = {k: v for k, v in out.items() if k not in ("facts", "docs", "period")}
    return AgentData(agent_id, spec.name, co, as_of, out["facts"], out["docs"], out["period"], extra)


def fetch_agent_data(agent_id: int, ticker: str, as_of: str | None = None, co: dict | None = None) -> AgentData:
    as_of = as_of or today_kst()
    co = co or db.company(ticker)
    return build_agent_data(agent_id, co, fetch_bundle(agent_id, co, as_of), as_of)
