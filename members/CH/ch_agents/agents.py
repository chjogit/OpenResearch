"""에이전트 등록부와 데이터 준비 (DB 조회 → 순수 계산)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any

from . import agent1_macro, agent3_sentiment_flow, db, exposure, financial, quality, rag
from .facts import Facts

KST = timezone(timedelta(hours=9))

# CH 담당 관점: 에이전트 1 거시경제·에이전트 3 투자심리·수급 (기초기획서 R4, 교재 8~9장 번호).
# 재무 코드(financial.py)는 기능을 넘겨받는 팀원이 참고하도록 7번에 남겨 둠
MY_AGENTS = (1, 3)


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
        1, "에이전트 1 거시경제 분석 (Macro & Sensitivity)", agent1_macro,
        role=("금리·환율·물가·반도체 수출 등 거시변수의 최근 변화와 국면을 진단하고, 그 변화가 이 기업의 매출·비용·수요·"
              "할인율로 전달되는 경로를 설명합니다. 동조성 수치는 통계적 관계일 뿐 기업의 환율 노출이 아닙니다."),
        checklist=[
            "현재 금리·환율·물가 국면 (코드 판정 문장의 키를 인용)",
            "이 업종의 전달 경로 중 지금 가장 영향이 큰 경로 1~2개와 그 이유",
            "주가와 거시변수의 동조성: 뚜렷한 것과 약한 것을 구분, 60일과 250일이 다르면 언급",
            "판단에 필요하지만 DB에 없는 변수(기업 노출, 유가 등)를 미확인에 명시",
            "미확인 전제(헤지 여부·결제 시점·판가 전가력 등)를 가정하지 않고 상태 그대로 전달",
            "반대 근거·하방 위험 1~3개",
        ],
        next_checks=["다음 한국은행 금리 결정과 원/달러 방향", "다음 달 관세청 수출 통계", "미국 물가 발표"],
    ),
    7: AgentSpec(  # 10/27 팀원 이관 (기술적 분석·가치/위험 담당). 교재 번호 7(가치평가·위험)에 임시 등록한 참고 코드
        7, "재무·밸류에이션 및 건전성 참고 (이관)", financial,
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
    3: AgentSpec(
        3, "에이전트 3 투자심리·수급 분석 (Sentiment & Flow)", agent3_sentiment_flow,
        role=("외국인·기관·개인 수급의 기간별 흐름과 강도, 외국인 지분율 변화, 뉴스·커뮤니티 논조, 검색 관심도, 시장 전반의 "
              "위험 선호를 분석합니다. 근거는 수급·논조·관심·가격 네 계열로 나누고, 같은 계열 안의 지표는 하나의 근거로 셉니다. "
              "순매수 기록만으로 매수 의도나 정보 보유를 추정하지 않습니다."),
        checklist=[
            "수급: 주체별 5·20·60일 흐름이 같은 방향인지, 강도와 연속 일수",
            "외국인 지분율의 변화와 1년 범위 내 위치",
            "논조·관심: 감성 점수는 키워드 사전 기반이라는 한계와 함께",
            "가격과 수급의 엇갈림, 시장 전반(VIX·코스피 대비) 맥락",
            "규칙·사전 기준선과의 비교 (평소 범위인지 이례적인지)",
            "중복 신호(뉴스+거래량 등)는 하나의 사건 묶음으로, 독립 근거로 중복 계산하지 않음",
            "반대 근거·하방 위험 1~3개",
        ],
        next_checks=["외국인 순매수 방향 전환 여부(5일 기준)", "대차잔고 수집 재개 후 추이", "검색 관심도 급변"],
    ),
}


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def normalize_as_of(as_of) -> str:
    """기준일을 'YYYY-MM-DD' 문자열로 맞춥니다. None 이면 오늘(한국 시간)."""
    from datetime import date

    if as_of is None or as_of == "":
        return today_kst()
    if isinstance(as_of, datetime):
        return as_of.date().isoformat()
    if isinstance(as_of, date):
        return as_of.isoformat()
    if isinstance(as_of, str):
        try:
            return date.fromisoformat(as_of.strip()[:10]).isoformat()
        except ValueError:
            pass
    raise ValueError(f"AS_OF 는 \"2026-10-26\" 처럼 따옴표로 감싼 날짜여야 합니다 (받은 값: {as_of!r}). "
                     "따옴표 없이 2026-10-26 이라고 쓰면 파이썬이 뺄셈으로 계산합니다.")


def fetch_bundle(agent_id: int, co: dict, as_of: str, use_rag: bool = True) -> dict:
    """관점 SQL 묶음 + (기본) RAG 후보 문서·공시. 'rag' 키는 스냅샷에도 그대로 저장됩니다."""
    mod = AGENTS[agent_id].module
    out = db.bundle(mod.SQL, mod.params(co, as_of))
    if use_rag and agent_id in rag.PRESETS:
        try:
            out["rag"] = rag.fetch(agent_id, co, as_of)
        except Exception as e:  # noqa: BLE001  문서 검색이 실패해도 숫자 분석은 진행
            out["rag"] = {"error": f"{type(e).__name__}: {e}"}
    if agent_id == 1:  # 사업보고서 원문 노출 (kic-agent-data 018). 표가 아직 없으면 업종 기본값만 씀
        try:
            out["report"] = db.q(exposure.REPORT_SQL, {"cid": co["company_id"], "as_of": as_of})
        except Exception:  # noqa: BLE001
            out["report"] = None
        try:  # 차입 조건·매출채권 회수기간 (kic-agent-data 019). 표가 아직 없으면 전제는 미확인으로 남음
            out["terms"] = db.bundle(exposure.TERMS_SQL, exposure.terms_params(co, as_of))
        except Exception:  # noqa: BLE001
            out["terms"] = None
    if agent_id in quality.SOURCES:
        try:
            out["quality"] = db.q(quality.SQL)
        except Exception:  # noqa: BLE001  품질 표가 없거나 권한이 없으면 품질 점검만 건너뜀
            out["quality"] = None
    return out


def build_agent_data(agent_id: int, co: dict, bundle: dict, as_of: str, opts: dict | None = None) -> AgentData:
    """opts: 사용자 입력. 에이전트 1 은 focus(관심 거시 변수 목록), 에이전트 3 은 period(기간, 거래일 수)."""
    spec = AGENTS[agent_id]
    opts = {k: v for k, v in (opts or {}).items() if v not in (None, [], "")}
    out = spec.module.compute(bundle, co, as_of, **opts) if opts else spec.module.compute(bundle, co, as_of)
    extra = {k: v for k, v in out.items() if k not in ("facts", "docs", "period")}
    extra["opts"] = opts
    warn = quality.check(agent_id, bundle.get("quality"))
    if warn:
        extra["quality"] = warn
        for w in warn:
            out["facts"].note(f"데이터 품질 주의 · {w['name']}: {w['reason']}")
    docs = out["docs"]
    raw = bundle.get("rag")
    if raw is not None and agent_id in rag.PRESETS:
        if raw.get("error"):
            extra["rag_error"] = raw["error"]
        else:
            docs = rag.select(agent_id, raw, co, as_of)  # 관점 프리셋으로 고른 문서가 모듈 기본 문서를 대신함
    return AgentData(agent_id, spec.name, co, as_of, out["facts"], docs, out["period"], extra)


def fetch_agent_data(agent_id: int, ticker: str, as_of: str | None = None, co: dict | None = None,
                     focus: list[str] | None = None, period: int | None = None) -> AgentData:
    """focus: 에이전트 1 관심 거시 변수(예: ["환율", "금리"]), period: 에이전트 3 기간(거래일, 예: 20)."""
    as_of = normalize_as_of(as_of)
    co = co or db.company(ticker)
    opts = {"focus": focus} if agent_id == 1 else {"period": period} if agent_id == 3 else {}
    return build_agent_data(agent_id, co, fetch_bundle(agent_id, co, as_of), as_of, opts)
