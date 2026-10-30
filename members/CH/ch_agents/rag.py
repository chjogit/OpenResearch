"""DB 기반 RAG: 관점별 질의 프리셋으로 Neon의 문서·공시를 찾아 에이전트 프롬프트에 근거로 붙입니다.

구성
- 문서: rag.document (네이버 뉴스·블로그·카페, Finnhub 영문 뉴스, 유튜브 댓글)의 제목과 요약
- 공시: core.disclosure (DART·SEC 공시 제목과 유형)

검색 방식 (Neon에서 BM25 확장 pg_search 는 쓸 수 없고, 한국어 형태소 사전도 없으므로)
1. SQL: 종목·기간·출처로 좁힌 뒤 관점별 용어가 제목/요약에 들어 있는 문서를 후보로 뽑습니다 (읽기 전용).
2. 파이썬: 용어 가중치 × 위치(제목 2, 요약 1) × 출처 가중치 × 최신성 으로 점수를 매기고,
   사진 기사 감점, 거의 같은 제목 중복 제거, 출처별 개수 제한을 거쳐 상위 k개를 고릅니다.
   이 단계는 순수 함수라 같은 후보를 넣으면 같은 결과가 나옵니다 (테스트·스냅샷 재현 가능).

원칙
- 문서는 사건·맥락의 근거일 뿐입니다. 문서 속 숫자는 DB 확정값이 아니므로 프롬프트에서 인용을 막고,
  코드 검사(키 밖 숫자)가 그대로 걸러냅니다.
- 블로그·카페·댓글은 '개인 의견'으로 표시합니다.

팀원 사용법 (교재 번호: 1 거시, 2 산업·사업모델, 3 투자심리·수급, 4 기술적, 5 경영진·대주주, 7 가치평가·위험(재무))
    from ch_agents.rag import retrieve, docs_for_prompt
    docs = retrieve(5, "005930", as_of="2026-10-26")
    print(docs_for_prompt(docs))
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

# ---------------------------------------------------------------- 관점별 질의 프리셋


@dataclass(frozen=True)
class Preset:
    name: str
    terms: dict[str, float]                       # 용어 → 가중치 (소문자로 비교)
    sources: dict[str, float]                     # 출처 → 가중치
    days: int = 45                                # 문서 검색 기간
    events: tuple[str, ...] = ()                  # 공시 유형 (core.disclosure.event_type)
    report_re: str = ""                           # 공시 제목 정규식 (유형이 비어 있는 공시 보완)
    disclosure_days: int = 365
    k_docs: int = 6
    k_disclosures: int = 4
    long_days: dict[str, int] = field(default_factory=dict)  # 연 1회 문서(사업보고서)는 기간을 길게, 최신성 감점 없음
    min_base: float = 2                           # 이 점수 미만 문서는 제외 (약한 용어 하나만 걸린 문서 거르기)
    per_source: dict[str, int] = field(default_factory=dict)


NEWS = {"naver_news": 1.0, "finnhub_news": 0.9}
OPINION = {"naver_blog": 0.55, "naver_cafe": 0.45, "youtube_comment": 0.4}
OPINION_CAP = {"naver_blog": 2, "naver_cafe": 2, "youtube_comment": 1}

PRESETS: dict[int, Preset] = {
    1: Preset(
        "거시경제·변수 민감도",
        {"환율": 2, "원/달러": 2, "원·달러": 2, "원화": 2, "달러 강세": 2, "달러 약세": 2, "기준금리": 2,
         "금리 인하": 2, "금리 인상": 2, "관세": 2, "수출": 1.5, "물가": 2, "인플레이션": 2, "연준": 2, "fomc": 2,
         "국제유가": 2, "유가 상승": 2, "유가 하락": 2, "wti": 2, "브렌트": 2, "국채": 1.5, "금리": 1, "경기 둔화": 2, "경기 침체": 2, "경기 회복": 1.5, "경기 부양": 1.5, "무역": 1, "수입": 0.5,
         "tariff": 2, "federal reserve": 2, "the fed": 1.5, "interest rate": 2, "inflation": 2, "dollar": 1.5, "export": 1.5, "oil price": 1.5, "crude": 1.5,
         "환위험": 2, "통화선도": 2, "통화스왑": 2, "헷지": 1.5, "위험회피": 1.5, "가격변동": 1.5, "판가": 1.5},
        {**NEWS, "dart_report": 1.2}, days=30, long_days={"dart_report": 500}),
    7: Preset(
        "재무·밸류에이션·건전성",
        {"실적": 1.5, "영업이익": 2, "매출": 1, "순이익": 2, "어닝": 2, "컨센서스": 2, "가이던스": 2, "잠정": 1.5,
         "배당": 2, "자사주": 2, "소각": 2, "주주환원": 2, "밸류업": 2, "부채": 2, "차입": 2, "회사채": 2,
         "신용등급": 3, "유상증자": 3, "감사의견": 3, "적자": 2, "흑자": 1.5, "이익률": 2, "현금흐름": 2,
         "earnings": 2, "revenue": 1.5, "guidance": 2, "dividend": 2, "buyback": 2, "margin": 1.5, "debt": 1.5},
        NEWS, days=45,
        events=("earnings_prelim", "earnings_change", "audit_report", "dividend", "buyback", "stock_retirement",
                "rights_issue", "convertible_bond", "capital_reduction", "value_up_plan", "quarterly_report",
                "half_year_report", "annual_report", "guidance", "loan_decision", "earnings"),
        k_disclosures=5),
    2: Preset(
        "산업·경쟁강도",
        {"점유율": 3, "경쟁": 1, "경쟁사": 2, "수주": 2, "공급계약": 2, "고객사": 2, "신제품": 2, "증설": 2,
         "양산": 2, "업황": 2, "판가": 2, "가격 인상": 2, "가격 인하": 2, "공급 과잉": 3, "재고": 1.5, "규제": 1,
         "신사업": 2, "인수": 1.5, "합병": 1.5, "진출": 1, "수요": 1,
         "market share": 3, "competition": 2, "competitor": 2, "contract": 1.5, "capacity": 1.5, "pricing": 2},
        NEWS, days=60, min_base=3,
        events=("supply_contract", "capex", "investment_acquisition", "merger", "business_transfer", "spin_off",
                "share_exchange", "material_agreement", "guidance", "acquisition_completed"),
        report_re="거래처|공급계약|영업양수"),
    3: Preset(
        "투자심리·수급",
        {"외국인": 2, "기관": 1.5, "개인 투자자": 1.5, "개인은": 1, "순매수": 2, "순매도": 2, "수급": 2, "공매도": 2, "대차": 2,
         "투자심리": 2, "개미": 1.5, "급등": 1.5, "급락": 1.5, "매물": 1.5, "차익실현": 2, "쏠림": 1.5,
         "신고가": 1, "반대매매": 2, "신용잔고": 2, "빚투": 2,
         "short interest": 2, "foreign investors": 2, "sell-off": 1.5, "rally": 1},
        {**NEWS, **OPINION}, days=20,
        events=("rumor_clarification", "rumor_inquiry", "conversion_exercise"), disclosure_days=120,
        k_docs=7, k_disclosures=3, per_source=OPINION_CAP),
    4: Preset(
        "기술적 분석",
        {"신고가": 2, "신저가": 2, "이동평균": 2, "이평선": 2, "골든크로스": 3, "데드크로스": 3, "지지선": 2,
         "저항선": 2, "거래량": 1.5, "전고점 돌파": 2, "저항선 돌파": 2, "기술적 반등": 2, "반등": 1, "박스권": 2, "차트": 1.5, "과매수": 2, "과매도": 2,
         "rsi": 2, "상한가": 2, "하한가": 2, "갭": 1,
         "52-week": 2, "all-time high": 2, "support": 1, "resistance": 1.5},
        {**NEWS, **OPINION}, days=20, k_docs=6, per_source=OPINION_CAP, min_base=3),
    5: Preset(
        "대주주·경영진",
        {"최대주주": 3, "경영권": 3, "지배구조": 3, "승계": 3, "상속": 2, "증여": 2, "오너": 2, "지주사": 2,
         "횡령": 3, "배임": 3, "행동주의": 3, "주주제안": 3, "대표이사": 2, "사외이사": 2, "이사회": 2,
         "주주총회": 2, "임원": 1, "회장": 0.75, "지분": 1, "소송": 0.75, "경영권 분쟁": 3, "지분 매각": 2, "사법 리스크": 3,
         "ceo": 1.5, "board of directors": 2, "chairman": 1.5, "activist": 3, "lawsuit": 1.5, "governance": 3},
        NEWS, days=60, min_base=3,
        events=("major_holder_change", "governance_report", "shareholders_meeting", "litigation",
                "officer_change", "embezzlement", "merger", "spin_off", "share_exchange"),
        report_re="임원ㆍ주요주주|최대주주|경영권",
        k_disclosures=5),
}

SOURCE_LABEL = {"naver_news": "뉴스", "finnhub_news": "해외뉴스", "dart_report": "사업보고서(회사 공시)", "naver_blog": "블로그(개인 의견)",
                "naver_cafe": "카페(개인 의견)", "youtube_comment": "유튜브 댓글(개인 의견)"}
EVENT_LABEL = {
    "earnings_prelim": "잠정실적", "earnings_change": "손익구조 변경", "audit_report": "감사보고서",
    "dividend": "배당", "buyback": "자기주식", "stock_retirement": "주식소각", "rights_issue": "유상증자",
    "convertible_bond": "전환사채", "capital_reduction": "감자", "value_up_plan": "기업가치 제고계획",
    "quarterly_report": "분기보고서", "half_year_report": "반기보고서", "annual_report": "사업보고서",
    "guidance": "경영계획", "loan_decision": "금전대여", "earnings": "실적 발표(8-K)",
    "supply_contract": "공급계약", "capex": "시설투자", "investment_acquisition": "타법인 지분취득",
    "merger": "합병", "business_transfer": "영업양수도", "spin_off": "분할", "share_exchange": "주식교환",
    "material_agreement": "주요 계약(8-K)", "acquisition_completed": "인수 완료(8-K)",
    "rumor_clarification": "풍문 해명", "rumor_inquiry": "조회공시", "conversion_exercise": "전환권 행사",
    "major_holder_change": "최대주주 지분 변동", "governance_report": "지배구조 보고서",
    "shareholders_meeting": "주주총회", "litigation": "소송", "officer_change": "임원 변경(8-K)",
    "embezzlement": "횡령·배임",
}
PHOTO_RE = re.compile(r"\[(포토|사진|영상|TF사진관|화보)\]|포토\]|사진관|\[photo\]", re.IGNORECASE)
DEDUP_RATIO = 0.72
HALF_LIFE_DAYS = 14


# ---------------------------------------------------------------- SQL (후보 추출, 읽기 전용)

SQL = """
WITH t AS (SELECT unnest(%(terms)s::text[]) AS term),
c AS (
    SELECT doc_id, source, title, coalesce(summary, '') AS summary, published_at, url
    FROM rag.document
    WHERE company_id = %(cid)s AND source = ANY(%(sources)s::text[])
      AND published_at <= %(as_of)s::date
      AND published_at > %(as_of)s::date - CASE WHEN source = ANY(%(long_src)s::text[]) THEN %(long_days)s::int
                                                ELSE %(days)s::int END
),
m AS (
    SELECT c.doc_id,
           array_agg(t.term) FILTER (WHERE strpos(lower(c.title), t.term) > 0) AS tt,
           array_agg(t.term) FILTER (WHERE strpos(lower(c.summary), t.term) > 0) AS st
    FROM c JOIN t ON strpos(lower(c.title), t.term) > 0 OR strpos(lower(c.summary), t.term) > 0
    GROUP BY c.doc_id
)
SELECT json_build_object(
    'news', (SELECT json_agg(x) FROM (
        SELECT c.doc_id, c.source, c.title, left(c.summary, 240) AS summary, c.published_at::date AS published, c.published_at AS published_at,
               c.url, coalesce(m.tt, '{}') AS tt, coalesce(m.st, '{}') AS st
        FROM m JOIN c USING (doc_id)
        ORDER BY coalesce(cardinality(m.tt), 0) * 2 + coalesce(cardinality(m.st), 0) DESC, c.published_at DESC
        LIMIT 300) x),
    'disclosures', (SELECT json_agg(x) FROM (
        SELECT rcept_no, rcept_dt, report_nm, event_type, source, url
        FROM core.disclosure
        WHERE company_id = %(cid)s AND rcept_dt <= %(as_of)s::date
          AND rcept_dt > %(as_of)s::date - %(ddays)s::int
          AND (event_type = ANY(%(events)s::text[]) OR (%(report_re)s <> '' AND report_nm ~ %(report_re)s))
        ORDER BY rcept_dt DESC, rcept_no DESC
        LIMIT 40) x)
) AS bundle
"""


def params(agent_id: int, co: dict, as_of: str) -> dict:
    p = PRESETS[agent_id]
    return {"cid": co["company_id"], "as_of": as_of, "terms": [t.lower() for t in p.terms],
            "sources": list(p.sources), "days": p.days, "events": list(p.events),
            "long_src": list(p.long_days), "long_days": max(p.long_days.values(), default=p.days),
            "report_re": p.report_re, "ddays": p.disclosure_days}


def fetch(agent_id: int, co: dict, as_of: str) -> dict:
    """DB에서 후보를 읽습니다. 결과는 스냅샷에 그대로 저장할 수 있는 dict 입니다."""
    from . import db

    return db.bundle(SQL, params(agent_id, co, as_of))


# ---------------------------------------------------------------- 점수·선별 (순수 함수)

def _norm_title(t: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>", " ", t or "")
    return re.sub(r"[^0-9a-zA-Z가-힣]", "", t).lower()


def _clean(t: str, n: int = 90) -> str:
    t = re.sub(r"<[^>]+>|&quot;|&amp;|&lt;|&gt;", " ", t or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _age(published: str, as_of: str) -> int:
    try:
        return max(0, (date.fromisoformat(as_of[:10]) - date.fromisoformat(str(published)[:10])).days)
    except ValueError:
        return 999


def _short_names(co: dict) -> list[str]:
    name = (co.get("name") or "").strip()
    out = [name] if name else []
    for suffix in ("홀딩스", "지주", "우"):
        if name.endswith(suffix) and len(name) > len(suffix) + 1:
            out.append(name[: -len(suffix)])
    return [n.lower() for n in out]


def _mentions(text: str, names: list[str]) -> bool:
    """종목명이 들어 있는지. '현대차증권'·'현대차證' 처럼 계열 증권사 이름은 종목 언급으로 보지 않습니다."""
    for n in names:
        if n and re.search(re.escape(n) + r"(?!\s*(증권|證|투자증권))", text):
            return True
    return False


def score_doc(row: dict, preset: Preset, co: dict, as_of: str) -> tuple[float, list[str]]:
    """문서 하나의 점수와 일치 용어. 0점이면 제외."""
    weights = {t.lower(): w for t, w in preset.terms.items()}
    title, summary = (row.get("title") or "").lower(), (row.get("summary") or "").lower()
    tt = [t for t in weights if t in title]
    st = [t for t in weights if t in summary]
    base = sum(weights[t] * 2 for t in tt) + sum(weights[t] for t in st)
    # 제목에 용어가 있거나, 요약에 서로 다른 용어가 2개 이상 있어야 후보로 인정 ('유가증권시장'의 '유가' 같은 우연 일치 방지)
    if base < preset.min_base or not (tt or len(st) >= 2):
        return 0.0, []
    s = base * preset.sources.get(row.get("source"), 0.3)
    names = _short_names(co)
    if row.get("source") not in ("finnhub_news", "dart_report") and names:  # 영문 뉴스·사업보고서는 종목별로 수집되어 이름 검사 불필요
        if _mentions(title, names):
            s += 1.0                   # 제목에 종목명: 이 종목에 관한 문서
        elif _mentions(summary, names):
            s *= 0.5                   # 요약에만 종목명: 시황·타 종목 기사일 가능성
        else:
            return 0.0, []             # 종목명이 없으면 다른 종목 기사로 보고 제외
    if PHOTO_RE.search(row.get("title") or ""):
        s *= 0.3                       # 사진 기사는 정보가 적음
    if row.get("source") not in preset.long_days:
        s *= 1 / (1 + _age(row.get("published"), as_of) / HALF_LIFE_DAYS)
    return round(s, 3), sorted(set(tt) | set(st), key=lambda t: -weights[t])


def select_docs(rows: list[dict], preset: Preset, co: dict, as_of: str) -> list[dict]:
    scored = []
    for r in rows or []:
        s, terms = score_doc(r, preset, co, as_of)
        if s > 0:
            scored.append((s, r, terms))
    scored.sort(key=lambda x: (x[0], str(x[1].get("published")), str(x[1].get("doc_id"))), reverse=True)
    kept, norms, per_src = [], [], {}
    for s, r, terms in scored:
        n = _norm_title(r.get("title"))
        if not n or any(n == m or SequenceMatcher(None, n, m).ratio() >= DEDUP_RATIO for m in norms):
            continue
        src = r.get("source")
        cap = preset.per_source.get(src)
        if cap is not None and per_src.get(src, 0) >= cap:
            continue
        norms.append(n)
        per_src[src] = per_src.get(src, 0) + 1
        kept.append({
            "kind": SOURCE_LABEL.get(src, src), "source": src, "published": str(r.get("published"))[:10],
            "published_at": str(r.get("published_at") or r.get("published")),  # 최초 공개시각 (R4 데이터 계약)
            "title": _clean(r.get("title")), "summary": _clean(r.get("summary"), 110),
            "url": r.get("url"), "terms": terms[:4], "score": s, "doc_id": r.get("doc_id"),
        })
        if len(kept) >= preset.k_docs:
            break
    return kept


def _report_title(nm: str) -> str:
    nm = re.sub(r"^\[[^\]]+\]", "", nm or "")
    return re.sub(r"\s{2,}", " ", nm).strip()


def select_disclosures(rows: list[dict], preset: Preset) -> list[dict]:
    """같은 제목이 반복되면(예: 최대주주 지분 변동 신고) 최신 1건만 두고 건수를 붙입니다."""
    groups: dict[str, dict] = {}
    for r in rows or []:
        title = _report_title(r.get("report_nm"))
        sub = "자회사" in title or "종속회사" in title
        key = (re.sub(r"\(.*?\)|\s", "", title) or title) + ("|자회사" if sub else "")  # 자회사 공시는 따로 묶음
        g = groups.get(key)
        if g is None:
            groups[key] = g = {
                "kind": "공시", "source": r.get("source") or "dart", "published": str(r.get("rcept_dt"))[:10],
                "title": _clean(title), "event": EVENT_LABEL.get(r.get("event_type") or "", r.get("event_type") or "기타"),
                "url": r.get("url"), "count": 0, "subsidiary": sub,
            }
        g["count"] += 1
    out = sorted(groups.values(), key=lambda g: g["published"], reverse=True)
    return out[: preset.k_disclosures]


def select(agent_id: int, raw: dict, co: dict, as_of: str) -> list[dict]:
    """후보 묶음에서 최종 문서 목록을 고릅니다 (공시 먼저, 그다음 문서)."""
    p = PRESETS[agent_id]
    raw = raw or {}
    return select_disclosures(raw.get("disclosures"), p) + select_docs(raw.get("news"), p, co, as_of)


def retrieve(agent_id: int, ticker_or_co, as_of: str | None = None) -> list[dict]:
    """팀원용 진입점: 관점 번호(1~6)와 종목코드(또는 company dict)로 문서 목록을 돌려줍니다."""
    from . import db
    from .agents import normalize_as_of

    as_of = normalize_as_of(as_of)
    co = ticker_or_co if isinstance(ticker_or_co, dict) else db.company(ticker_or_co)
    return select(agent_id, fetch(agent_id, co, as_of), co, as_of)


# ---------------------------------------------------------------- 프롬프트·출력 표시

PROMPT_RULE = ("[참고 문서]는 사건·맥락의 정성 근거입니다. 근거 키로 D번호를 쓰십시오. "
               "문서 속 숫자·전망치는 DB 검증값이 아니므로 쓰지 마십시오. "
               "'개인 의견' 문서는 여론의 존재만 근거로 삼고 사실 주장의 근거로 쓰지 마십시오. "
               "공시는 '제출됨' 사실만 말하고, 내용(지분율·금액)은 본문이 없으므로 미확인에 적으십시오.")


def doc_line(i: int, d: dict, with_summary: bool = True) -> str:
    if d.get("kind") == "공시":
        extra = f" 외 동일 공시 {d['count'] - 1}건" if d.get("count", 1) > 1 else ""
        sub = " · 자회사 관련" if d.get("subsidiary") else ""
        return f"- D{i}: {d['published']} [공시·{d['event']}] {d['title']}{extra}{sub}"
    line = f"- D{i}: {d['published']} [{d.get('kind', '뉴스')}] {d['title']}"
    if with_summary and d.get("summary"):
        line += f"\n    요약: {d['summary']}"
    return line


def docs_for_prompt(docs: list[dict]) -> str:
    return "\n".join(doc_line(i + 1, d) for i, d in enumerate(docs)) or "- (없음)"


def docs_markdown(docs: list[dict]) -> list[str]:
    out = []
    for i, d in enumerate(docs):
        title = f"[{d['title']}]({d['url']})" if d.get("url") else d["title"]
        tag = f"공시·{d['event']}" if d.get("kind") == "공시" else d.get("kind", "뉴스")
        more = f" (외 {d['count'] - 1}건)" if d.get("count", 1) > 1 else ""
        if d.get("chunk_id") is not None:  # R6: [D1] chunk #<chunk_id> · <source> · <날짜> · <URL 또는 제목>
            out.append(f"- [D{i + 1}] chunk #{d['chunk_id']} · {d.get('source')} · {d['published']} · {d.get('url') or d['title']}")
            continue
        out.append(f"- D{i + 1} · {d['published']} · {tag} · {title}{more}")
    return out
