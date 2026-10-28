"""에이전트 등록부와 데이터 준비 (DB 조회 → 순수 계산)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any

from . import agent1_macro, agent3_sentiment_flow, db, etf, exposure, financial, forecast, p03, quality, rag
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
            "주가와 거시변수의 동조성: 상관의 크기(강함/보통/약함)와 통계적 유의성을 구분, 60일과 250일이 다르면 언급",
            "판단에 필요하지만 DB에 없는 변수(기업 노출, 유가 등)를 미확인에 명시",
            "미확인 전제(헤지 여부·결제 시점·판가 전가력 등)를 가정하지 않고 상태 그대로 전달",
            "제작 기준(P01): 결과를 관측·공시 민감도·실적 예측(기준선, 승인 모델 없음)·시나리오(공시 정적 환산)로 구분, "
            "시나리오 값을 매출 예측에 더하지 않고 인과효과·확률로 쓰지 않음",
            "참고용(제작 기준 밖) 항목(주가 동조성·산업 변수·ETF 수익률)은 보조 맥락으로만, 핵심 진단의 근거로 쓰지 않음",
            "반대 근거·하방 위험 1~3개. 하방 위험은 '어떤 조건이면 → 무엇을 확인할지(장부 키)' 형태로 써서 입문자도 다음 행동을 알게",
            "주장은 7개 이하, 반대근거는 3개 이하 (넘치면 코드가 뒤에서 자름)",
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
            "제작 기준(P03): 관측·기준선 비교·과거 관계(사건 연구)·대용치(ETF 자금 흐름·순매수 금액)를 구분. "
            "과거 관계는 예측·투자 신호가 아니며, 신호 뒤 중앙값을 '모든 거래일 기준선'과 함께 말함",
            "참고용 항목(주가 수익률·외국인 순매수일 평균 가격)은 보조 맥락으로만",
            "반대 근거·하방 위험 1~3개. 하방 위험은 '어떤 조건이면 → 무엇을 확인할지(장부 키)' 형태로 써서 입문자도 다음 행동을 알게",
            "주장은 7개 이하, 반대근거는 3개 이하 (넘치면 코드가 뒤에서 자름)",
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


# 종목과 무관한 시장 전체 조회(분기 매출 패널·KOSPI 200 사건 연구·ETF·금리 일정)는 같은 기준일이면 결과가 같아
# 여러 종목을 돌릴 때 한 번만 조회합니다. 수집이 매시간 돌므로 10분만 보관합니다.
SHARED_TTL = 600
_SHARED: dict = {}


def shared(name: str, as_of: str, fn):
    import time

    key = (name, as_of)
    hit = _SHARED.get(key)
    if hit and time.monotonic() - hit[0] < SHARED_TTL:
        return hit[1]
    val = fn()
    _SHARED[key] = (time.monotonic(), val)
    return val


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
        try:  # 금리 결정 일정 (kic-agent-data 021). 표가 아직 없으면 일정은 무자료로 남음
            out["meetings"] = shared("meetings", as_of, lambda: db.bundle(mod.MEETINGS_SQL, {"as_of": as_of}))
        except Exception:  # noqa: BLE001
            out["meetings"] = None
        try:  # P01-F05 기준선 예측·순차평가용 전 종목 분기 매출 패널
            out["panel"] = shared("panel", as_of, lambda: db.q(forecast.PANEL_SQL, {"as_of": as_of})[0])
        except Exception:  # noqa: BLE001
            out["panel"] = None
    if agent_id in (1, 3):  # 대표 지수·배당 ETF (kic-agent-data 022). 1 은 참고용 시장 기준선, 3 은 ETF 자금 흐름
        try:
            out["etf"] = shared("etf", as_of,
                                lambda: (db.q(etf.SQL, {"etf": etf.REP_TICKERS, "as_of": as_of})[0] or {}).get("etf"))
        except Exception:  # noqa: BLE001
            out["etf"] = None
    if agent_id == 3:  # P03-F07 KOSPI 200 합산 사건 연구 (결과가 기준일까지 확정된 사건만)
        try:
            out["panel_events"] = shared("panel_events", as_of, lambda: db.bundle(
                p03.PANEL_EVENT_SQL, {"as_of": as_of, "z": p03.Z_EVENT}) or None)
        except Exception:  # noqa: BLE001
            out["panel_events"] = None
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
    newer_docs_flag(out["facts"], docs, (extra.get("freshness") or {}).get("수급"))
    return AgentData(agent_id, spec.name, co, as_of, out["facts"], docs, out["period"], extra)


FLOW_WORDS = ("외국인", "기관", "순매수", "순매도", "수급")


def newer_docs_flag(f, docs: list[dict], ledger_last: str | None) -> int:
    """장부(수급) 마지막 날짜보다 뒤에 나온 수급 관련 문서가 있으면 판정으로 알립니다.

    문서 속 숫자는 확정값이 아니어서 장부를 고치지 않습니다. 판정 문구에는 건수를 넣지 않습니다
    (LLM 이 '3건' 을 옮겨 쓰면 장부에 없는 숫자가 되어 문장이 지워짐). 대신 '장부가 최신 흐름보다 늦을 수 있음'을
    판정으로 남겨, LLM 이 장부의 연속 일수 등을 오늘 상황처럼 쓰지 않게 합니다."""
    if not ledger_last or not docs:
        return 0
    newer = [d for d in docs if str(d.get("published", ""))[:10] > ledger_last
             and any(w in f"{d.get('title', '')} {d.get('summary', '')}" for w in FLOW_WORDS)]
    if newer:
        last = max(str(d["published"])[:10] for d in newer)
        f.flag(f"자료 시차: 수급 장부({ledger_last}) 이후 날짜의 수급 관련 문서가 있음 (최신 {last}). "
               "장부가 최근 흐름을 반영하지 못했을 수 있음, 확인 필요")
    return len(newer)


def fetch_agent_data(agent_id: int, ticker: str, as_of: str | None = None, co: dict | None = None,
                     focus: list[str] | None = None, period: int | None = None, scenario: str | None = None,
                     question: str | None = None) -> AgentData:
    """focus: 에이전트 1 관심 거시 변수(예: ["환율", "금리"]), period: 에이전트 3 기간(거래일, 예: 20).
    scenario: 에이전트 1 조건(예: "환율 5% 상승, 금리 0.5%p 하락"), question: 사용자 질문 원문 (P01·P03 과업 계약)."""
    as_of = normalize_as_of(as_of)
    co = co or db.company(ticker)
    if agent_id == 1:
        opts = {"focus": focus, "scenario": scenario, "question": question}
    elif agent_id == 3:
        opts = {"period": period, "question": question}
    else:
        opts = {}
    opts = {k: v for k, v in opts.items() if v not in (None, [], "")}
    return build_agent_data(agent_id, co, fetch_bundle(agent_id, co, as_of), as_of, opts)
