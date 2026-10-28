"""에이전트 1 거시경제 (교재 8장, 기초기획서 R4).

계산하는 것
- 지표별 최신값, 3·12개월 변화, 국면 판정(인상/인하/보합, 원화 강세/약세, 물가 가속/둔화)
- 반도체 수출: 최근 달 전년 대비, 최근 3개월 합계 전년 대비, 최근 6개월 중 전년 대비 증가한 달 수
- 동조성: 종목 일간 수익률과 원/달러·코스피(같은 날), 미국 10년물·필라델피아 반도체(전날) 변화의
  상관·베타를 60·250거래일로 계산하고, 크기(|r| 0.2·0.4 기준 약함/보통/강함)와
  거친 유의 기준(2/√n)을 따로 표시
- 업종별 전달 경로 가이드(숫자 없음): 어떤 변수가 어떤 경로로 실적에 닿는지, DB에 없는 변수는 무자료로

한계: 동조성은 통계적 관계이지 기업의 노출(수출 비중·외화 부채·헤지)이 아닙니다. 노출 데이터는 DB에 없습니다.
거시 통계의 관측일(obs_date)은 발표일이 아니므로 과거 시점 평가에는 발표 지연을 따로 고려해야 합니다.
"""
from __future__ import annotations

from . import exposure
from .facts import (
    Facts,
    check_freshness,
    corr_beta,
    corr_label,
    daily_diffs,
    daily_returns,
    days_between,
    pct_change,
    series_points,
    shift_months,
    value_on_or_before,
)

SRC = "core.macro_obs"

# 통화정책 결정 회의 일정 (kic-agent-data 021 core.policy_meeting). 발표 시각은 한국시간으로 비교합니다.
# 일정은 미리 공표되므로 기준일 뒤의 회의를 써도 미래 정보 누설이 아닙니다(결정 내용은 쓰지 않음).
MEETINGS_SQL = """
SELECT json_build_object('meetings', (
    SELECT json_agg(json_build_object(
               'bank', bank, 'date', decision_date,
               'kst', to_char(announce_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD"T"HH24:MI'),
               'sep', projections, 'status', status) ORDER BY announce_at)
    FROM core.policy_meeting
    WHERE announce_at >= %(as_of)s::date - 200 AND announce_at < %(as_of)s::date + 400)) AS bundle
"""
SRC_PM = "core.policy_meeting (한국은행·연준 공표 일정)"
MEETING_NAMES = {"BOK": "한국은행 금통위 통화정책방향 결정", "FOMC": "FOMC 결정 발표"}
EVENT_SOON = 7  # 다음 결정까지 이 일수 이하이면 '금리 이벤트 임박'

# series_id: (이름, 단위, 변화 방식)  pp=%p 차이, pct=증감률
MACRO_SERIES = {
    "ECOS_BASE_RATE": ("한국 기준금리", "%", "pp"),
    "ECOS_KTB3Y": ("국고채 3년 금리", "%", "pp"),
    "ECOS_KTB10Y": ("국고채 10년 금리", "%", "pp"),
    "FEDFUNDS": ("미국 기준금리(실효)", "%", "pp"),
    "DGS10": ("미국 10년 국채금리", "%", "pp"),
    "ECOS_USDKRW": ("원/달러 환율", "KRW", "pct"),
    "DEXJPUS": ("엔/달러 환율", "idx", "pct"),
    "DEXCHUS": ("위안/달러 환율", "idx", "pct"),
    "DEXUSEU": ("달러/유로 환율", "idx", "pct"),
    "DEXTAUS": ("대만달러/달러 환율", "idx", "pct"),
    "DCOILWTICO": ("WTI 유가", "USD/bbl", "pct"),
    "DCOILBRENTEU": ("브렌트 유가", "USD/bbl", "pct"),
    "IPG3344S": ("미국 반도체·전자부품 산업생산지수", "idx", "pct"),
    "PCU33443344": ("미국 반도체·전자부품 생산자물가지수", "idx", "pct"),
}
EXPORT_SERIES = {
    "KCS_EXP_854232_USD": "반도체 메모리 수출",
    "KCS_EXP_854231_USD": "반도체 프로세서·컨트롤러 수출",
}
CPI_SERIES = {"CPIAUCSL": "미국 CPI", "ECOS_CPI": "한국 소비자물가"}
# 업종 전달 경로에만 쓰는 변수 (해당 업종일 때만 장부에 올림). kic-agent-data #13·#15 에서 수집
# (이름, 단위, 업종, 변화 기간). 중국 수출은 계절성이 커서 전년 같은 달(12개월) 대비만 씀
SECTOR_SERIES = {
    "PCOPPUSDM": ("국제 구리 가격", "USD", ("금속",), (3, 12)),
    "PIORECRUSDM": ("국제 철광석 가격", "USD", ("금속",), (3, 12)),
    "PNGASJPUSDM": ("아시아 LNG 가격", "USD", ("전기·가스",), (3, 12)),
    "QKRN628BIS": ("한국 주거용 부동산 가격지수(BIS)", "idx", ("건설", "은행"), (3, 12)),
    "ECOS_CHN_EXPORT": ("중국 수출(통관기준)", "idx", ("화학", "금속"), (12,)),
}
ALL_SERIES = list(MACRO_SERIES) + list(CPI_SERIES) + list(EXPORT_SERIES) + list(SECTOR_SERIES)

SQL = """
WITH s AS (
    SELECT series_id, json_agg(json_build_object('d', obs_date, 'v', value) ORDER BY obs_date) AS obs
    FROM core.macro_obs
    WHERE series_id = ANY(%(series)s)
      AND obs_date <= %(as_of)s::date AND obs_date > %(as_of)s::date - INTERVAL '27 months'
    GROUP BY series_id
), ix AS (
    SELECT symbol, json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date) AS obs
    FROM core.market_index_daily
    WHERE symbol IN ('^KS11', '^SOX')
      AND trade_date <= %(as_of)s::date AND trade_date > %(as_of)s::date - INTERVAL '400 days'
    GROUP BY symbol
)
SELECT json_build_object(
    'series', (SELECT json_object_agg(series_id, obs) FROM s),
    'index', (SELECT json_object_agg(symbol, obs) FROM ix),
    'fund', (SELECT row_to_json(x) FROM (
              SELECT fiscal_year, liabilities, equity, revenue, operating_income, net_income
              FROM core.v_fundamentals_annual
              WHERE company_id = %(cid)s
                AND fiscal_year <= extract(year FROM %(as_of)s::date - 90)::int - 1  -- 사업보고서 제출(3월 말) 전 시점에는 전전년
              ORDER BY fiscal_year DESC LIMIT 1) x),
    -- 기준일에 공시돼 있던 최근 4개 분기 영업이익 (분기보고서 45일, 사업보고서 90일 제출 기한 뒤부터 사용)
    'ttm_op', (SELECT row_to_json(t) FROM (
              SELECT sum(amount) AS operating_income_ttm, max(period_end) AS ttm_end,
                     min(period_end) AS first_end, count(*) AS n
              FROM (SELECT period_end, amount FROM core.financial_quarter
                    WHERE company_id = %(cid)s AND metric = 'operating_income' AND amount IS NOT NULL
                      AND period_end + (CASE WHEN fiscal_q = 4 THEN 90 ELSE 45 END) <= %(as_of)s::date
                    ORDER BY period_end DESC LIMIT 4) q) t),
    'price', (SELECT json_agg(json_build_object('d', trade_date, 'v', close) ORDER BY trade_date)
              FROM core.price_daily
              WHERE company_id = %(cid)s AND trade_date <= %(as_of)s::date
                AND trade_date > %(as_of)s::date - INTERVAL '400 days'),
    'docs', (SELECT json_agg(x) FROM (
              SELECT d.title, d.published_at::date AS published
              FROM rag.document d
              WHERE d.company_id = %(cid)s AND d.source = 'naver_news'
                AND d.published_at::date <= %(as_of)s::date
                AND d.title ~ '환율|금리|수출|관세|물가|달러 강세|원화'
              ORDER BY d.published_at DESC LIMIT 5) x)
) AS bundle
"""


def params(co: dict, as_of: str) -> dict:
    return {"cid": co["company_id"], "as_of": as_of, "series": ALL_SERIES}


# ---------------------------------------------------------------- 업종별 전달 경로 (숫자 없는 해석 틀)
# 변수 이름 뒤 ※ 는 DB에 없는 변수 (무자료로 표시)
TRANSMISSION = {
    "반도체": [
        "원/달러: 달러로 받는 수출 대금의 원화 환산액을 바꿈. 달러 비용·헤지에 따라 순효과는 달라짐",
        "엔/달러·위안/달러: 일본·중국 경쟁사와의 상대 가격경쟁력",
        "미국 금리·필라델피아 반도체지수: 글로벌 IT 수요 기대와 성장주 할인율 경로",
        "메모리·프로세서 수출: 업황(물량·가격)의 직접 지표",
        "대만달러/달러: 경쟁국 통화. 원화와 함께 움직이는지가 상대 가격경쟁력에 영향",
        "미국 반도체 생산자물가·산업생산: 전방 수요와 가격 흐름",
    ],
    "전기·전자": [
        "원/달러: 수출 대금 원화 환산과 부품 수입 비용의 양방향 경로",
        "미국 금리·소비: 전방 수요",
        "반도체 수출: 부품 업황",
    ],
    "운송장비·부품": [
        "원/달러: 수출 차량·부품 가격경쟁력과 원화 환산 매출",
        "엔/달러: 일본 경쟁사 대비 가격경쟁력",
        "유가: 차량 수요(연비 선호)와 원가",
        "미국 금리: 할부 금융 비용을 통한 차량 수요",
        "관세·통상정책: 수출 단가와 물량 ※",
    ],
    "은행": [
        "한국 기준금리: 대출·예금 금리 차이(순이자마진)",
        "국고채 금리 곡선(장단기 금리차): 조달·운용 수익",
        "주택가격(BIS): 담보가치와 대손비용 경로",
        "경기: 대손비용 ※",
    ],
    "증권": ["기준금리·시장금리: 채권 운용 손익", "주식 거래대금: 수수료 수익 ※"],
    "보험": ["장기 국고채 금리: 자산운용 수익과 부채 평가", "한국 기준금리: 단기 운용 수익"],
    "기타금융": ["자회사 업종의 거시 경로를 따름. 은행 자회사가 있으면 기준금리·순이자마진 경로가 중요",
             "한국 기준금리: 조달 비용"],
    "화학": ["유가: 원재료 비용과 제품 가격", "원/달러: 원재료 수입 비용과 수출 대금", "중국 수출: 중국 제조업 경기와 제품 수요"],
    "금속": ["원/달러: 원재료 수입과 수출 대금", "구리·철광석 가격: 원재료 비용과 제품 가격",
           "중국 수출: 중국 제조업 경기와 철강·비철 수요"],
    "음식료·담배": ["원/달러: 곡물 등 원재료 수입 비용", "국내 물가: 판매가 전가 여력"],
    "건설": ["한국 기준금리: 분양 수요와 자금 조달 비용", "주택가격(BIS): 분양 수요와 미분양 위험"],
    "전기·가스": ["유가·아시아 LNG 가격: 연료비", "원/달러: 연료 수입 비용", "요금 규제 ※"],
    "통신": ["한국 기준금리: 배당주 할인율·차입 비용", "경기 민감도는 낮은 편"],
    "IT 서비스": ["미국·한국 금리: 성장주 할인율", "기업 IT 투자 경기 ※"],
    "제약": ["원/달러: 수출과 원료 수입", "금리: 연구개발형 기업의 할인율"],
    "유통": ["국내 물가: 가계 구매력", "한국 기준금리: 가계 구매력"],
}
DEFAULT_TRANSMISSION = ["원/달러: 수출·수입 비중에 따라 매출·비용 양방향", "한국·미국 금리: 조달 비용과 할인율",
                        "물가: 원가와 판매가 전가 여력"]


NAME_HINTS = (("증권", "증권"), ("생명", "보험"), ("화재", "보험"), ("손해보험", "보험"), ("은행", "은행"),
              ("금융", "기타금융"), ("카드", "기타금융"))
FINANCIAL_SECTORS = {"은행", "증권", "보험", "기타금융"}
SEMI_SECTORS = {"반도체", "전기·전자"}
OIL_SECTORS = {"화학", "운송·창고", "전기·가스", "운송장비·부품"}


def sector_of(co: dict) -> str:
    """Peer 테마(수동 선정) → KRX 업종 → 종목명 단서 순으로 업종을 정합니다."""
    method = (co.get("peer_method") or "")
    if method.startswith("manual:"):
        return method.split(":", 1)[1]
    if co.get("krx_sector"):
        return co["krx_sector"]
    for word, sector in NAME_HINTS:
        if word in (co.get("name") or ""):
            return sector
    return "미분류"


# ---------------------------------------------------------------- 계산

def _regime_rate(chg12: float | None) -> str | None:
    if chg12 is None:
        return None
    return "인상 국면" if chg12 > 0.25 else "인하 국면" if chg12 < -0.25 else "보합"


def _last_change(points: list[tuple[str, float]]) -> str | None:
    for (_, v0), (d1, v1) in zip(reversed(points[:-1]), reversed(points[1:])):
        if v0 != v1:
            return d1
    return None


def compute(b: dict, co: dict, as_of: str, focus: list[str] | None = None, **_) -> dict:
    f = Facts("M")
    series = {k: series_points(v) for k, v in (b.get("series") or {}).items()}
    sector = sector_of(co)

    # 1) 지표 패널과 국면
    for sid, (name, unit, how) in MACRO_SERIES.items():
        pts = series.get(sid) or []
        if not pts:
            f.gap(name, "시계열 없음")
            continue
        d, v = pts[-1]
        f.add(name, v, unit, d, f"{SRC} {sid}", group="거시 지표")
        for label, months in (("3개월", 3), ("12개월", 12)):
            old = value_on_or_before(pts, shift_months(d, months))
            if how == "pp":
                chg = None if old is None else v - old[1]
                k = f.add(f"{name} {label} 변화", chg, "%p", d, f"{SRC} {sid}", kind="calc", group="거시 지표")
                if label == "12개월" and k:
                    f.flag(f"{name}: {_regime_rate(chg)} (12개월 변화 {{{k}}})")
            else:
                f.add(f"{name} {label} 변화율", pct_change(v, old and old[1]), "%chg", d, f"{SRC} {sid}",
                      kind="calc", group="거시 지표")
        if sid == "ECOS_BASE_RATE" and (lc := _last_change(pts)):
            f.note(f"한국 기준금리 마지막 변경 관측월: {lc[:7]}")
    # 1-1) 업종 전용 변수 (구리·철광석·LNG·주택가격): 해당 업종에서만
    for sid, (name, unit, sectors, spans) in SECTOR_SERIES.items():
        if sector not in sectors:
            continue
        pts = series.get(sid) or []
        if not pts:
            f.gap(name, "시계열 없음 (kic-agent-data 수집 대기)")
            continue
        d, v = pts[-1]
        f.add(name, v, unit, d, f"{SRC} {sid}", group="업종 변수")
        for months in spans:
            old = value_on_or_before(pts, shift_months(d, months))
            label = "전년 같은 달 대비" if months == 12 and spans == (12,) else f"{months}개월 변화율"
            f.add(f"{name} {label}", pct_change(v, old and old[1]), "%chg", d, f"{SRC} {sid}",
                  kind="calc", group="업종 변수")

    usd = series.get("ECOS_USDKRW") or []
    check_freshness(f, "원/달러 환율", usd[-1][0] if usd else None, as_of, 7)
    check_freshness(f, "미국 10년 국채금리", (series.get("DGS10") or [("", 0)])[-1][0] or None, as_of, 10)
    check_freshness(f, "한국 기준금리", (series.get("ECOS_BASE_RATE") or [("", 0)])[-1][0] or None, as_of, 75)
    if usd:
        k3 = f.key_of("원/달러 환율 3개월 변화율")
        chg = f.items[k3]["value"] if k3 else None
        if chg is not None:
            state = "원화 약세(달러 강세)" if chg > 3 else "원화 강세(달러 약세)" if chg < -3 else "환율 보합권"
            f.flag(f"원/달러 3개월: {state} ({{{k3}}})")

    for sid, name in CPI_SERIES.items():
        cpi = series.get(sid) or []
        if len(cpi) < 16:
            f.gap(f"{name} 전년 대비", "관측 16개월 미만 (수집 전이거나 과거분 부족)")
            continue
        d, v = cpi[-1]
        yoy = pct_change(v, (value_on_or_before(cpi, shift_months(d, 12)) or (None, None))[1])
        d3 = value_on_or_before(cpi, shift_months(d, 3))
        yoy3 = None
        if d3:
            base = value_on_or_before(cpi, shift_months(d3[0], 12))
            yoy3 = pct_change(d3[1], base and base[1])
        k = f.add(f"{name} 전년 대비", yoy, "%chg", d, f"{SRC} {sid}", kind="calc", group="거시 지표")
        k2 = f.add(f"{name} 전년 대비(3개월 전)", yoy3, "%chg", d3 and d3[0], f"{SRC} {sid}", kind="calc",
                   group="거시 지표")
        if k and k2 and yoy is not None and yoy3 is not None:
            f.flag(f"{name}: {'가속' if yoy > yoy3 + 0.2 else '둔화' if yoy < yoy3 - 0.2 else '횡보'} "
                   f"({{{k2}}} → {{{k}}})")

    # 한국 장단기 금리차 (10년 − 3년)
    k10, k3 = series.get("ECOS_KTB10Y") or [], series.get("ECOS_KTB3Y") or []
    if k10 and k3:
        d = min(k10[-1][0], k3[-1][0])
        a10, a3 = value_on_or_before(k10, d), value_on_or_before(k3, d)
        spread = a10[1] - a3[1]
        k_sp = f.add("국고채 장단기 금리차(10년 − 3년)", spread, "%p", d, f"{SRC} ECOS_KTB10Y − ECOS_KTB3Y",
                     kind="calc", group="거시 지표")
        old = shift_months(d, 12)
        o10, o3 = value_on_or_before(k10, old), value_on_or_before(k3, old)
        if o10 and o3:
            k_sc = f.add("국고채 장단기 금리차 12개월 변화", spread - (o10[1] - o3[1]), "%p", d,
                         f"{SRC} ECOS_KTB10Y − ECOS_KTB3Y", kind="calc", group="거시 지표")
            if k_sp and k_sc and spread < 0:
                f.flag(f"한국 장단기 금리 역전 ({{{k_sp}}})")

    # 2) 반도체 수출 (월별, 관세청)
    for sid, name in EXPORT_SERIES.items():
        pts = series.get(sid) or []
        if len(pts) < 15:
            f.gap(name, "관측 15개월 미만")
            continue
        d = pts[-1][0]
        last, last_y = pts[-1][1], (value_on_or_before(pts, shift_months(d, 12)) or (None, None))[1]
        r3 = sum(v for _, v in pts[-3:])
        y3 = sum(v for _, v in pts[-15:-12])
        f.add(f"{name}(최근 월)", last, "USD", d, f"관세청 {sid}", group="수출")
        f.add(f"{name}(최근 월) 전년 대비", pct_change(last, last_y), "%chg", d, f"관세청 {sid}", kind="calc",
              group="수출")
        f.add(f"{name}(최근 3개월 합계) 전년 대비", pct_change(r3, y3), "%chg", d, f"관세청 {sid}", kind="calc",
              group="수출")
        ups = 0
        for i in range(6):
            dd, vv = pts[-1 - i]
            base = value_on_or_before(pts, shift_months(dd, 12))
            ups += bool(base and base[1] and vv > base[1])
        f.add(f"{name}: 최근 6개월 중 전년 대비 증가한 달", ups, "개", d, f"관세청 {sid}", kind="calc", group="수출")

    # 3) 동조성
    price = series_points(b.get("price"))
    stock_r = daily_returns(price)
    idx = {k: series_points(v) for k, v in (b.get("index") or {}).items()}
    drivers = [  # (이름, 변화 dict, 하루 늦춤, 단위 설명)
        ("원/달러", daily_returns(usd), False, "원/달러 1% 변화당 주가 변화(%)"),
        ("코스피", daily_returns(idx.get("^KS11") or []), False, "코스피 1% 변화당 주가 변화(%) (시장 베타)"),
        ("미국 10년 국채금리", daily_diffs(series.get("DGS10") or []), True,
         "미국 금리 1%p 변화당 다음 거래일 주가 변화(비율)"),
    ]
    if sector in SEMI_SECTORS:
        drivers.append(("필라델피아 반도체지수", daily_returns(idx.get("^SOX") or []), True,
                        "SOX 1% 변화당 다음 거래일 주가 변화(%)"))
    if sector in OIL_SECTORS:
        drivers.append(("WTI 유가", daily_returns(series.get("DCOILWTICO") or []), True,
                        "WTI 1% 변화당 다음 거래일 주가 변화(%)"))
    if sector in FINANCIAL_SECTORS:
        drivers.append(("국고채 3년 금리", daily_diffs(series.get("ECOS_KTB3Y") or []), False,
                        "국고채 3년 1%p 변화당 같은 날 주가 변화(비율)"))
    trade_days = sorted(stock_r)
    period = "-"
    for name, chg, lag, unit_note in drivers:
        if not chg:
            f.gap(f"주가-{name} 동조성", "시계열 없음")
            continue
        drv_days = sorted(chg)
        pairs = []
        for d in trade_days:
            if lag:  # 한국 거래일 d 에는 미국의 직전 거래일 변화가 반영됨 (4일 넘게 떨어지면 자료 지연으로 보고 제외)
                i = bisect_left_days(drv_days, d)
                if i == 0 or days_between(drv_days[i - 1], d) > 4:
                    continue
                pairs.append((d, chg[drv_days[i - 1]], stock_r[d]))
            elif d in chg:
                pairs.append((d, chg[d], stock_r[d]))
        res = {}
        for win in (60, 250):
            sub = pairs[-win:]
            r, beta, n = corr_beta([x for _, x, _ in sub], [y for _, _, y in sub])
            res[win] = (r, beta, n, sub)
        r250, b250, n250, sub250 = res[250]
        r60, _, n60, _ = res[60]
        if r250 is None:
            f.gap(f"주가-{name} 동조성", "겹치는 거래일 30일 미만")
            continue
        period = f"{sub250[0][0]} ~ {sub250[-1][0]}"
        src = f"core.price_daily × {name}"
        k_r = f.add(f"주가-{name} 상관(250일)", r250, "coef", period, src, kind="calc", group="동조성",
                    note=f"{n250}거래일, 통계적 동조성이며 노출·인과 아님" + (" (미국 전날 기준)" if lag else ""))
        f.add(f"주가-{name} 베타(250일)", b250, "coef", period, src, kind="calc", group="동조성", note=unit_note)
        k_r60 = f.add(f"주가-{name} 상관(60일)", r60, "coef", f"최근 {n60}거래일", src, kind="calc", group="동조성")
        # 크기(|r|)와 유의성(표본 수 기준)을 따로 표시합니다. '뚜렷/약함' 한 단어로 합치면
        # 250일 -0.17(유의) 과 60일 -0.16(비유의) 이 다른 말로 읽혀 기준이 섞입니다.
        recent = ""
        if k_r60 and r60 is not None:
            same_dir = (r60 > 0) == (r250 > 0)
            recent = (f", 최근 60일 {corr_label(r60, n60)}" + ("" if same_dir else "·방향 반대")
                      + f" ({{{k_r60}}})")
        f.flag(f"주가-{name}: {corr_label(r250, n250)} ({{{k_r}}}){recent}")

    # 4) 업종별 전달 경로
    guide = TRANSMISSION.get(sector, DEFAULT_TRANSMISSION)
    f.note(f"업종 기준: {sector}" + (" (종목명으로 추정, KRX 업종 미수집)" if not co.get("krx_sector")
                                     and not (co.get("peer_method") or "").startswith("manual:") else ""))
    for line in guide:
        f.note("전달 경로 · " + line.replace(" ※", ""))
        if line.endswith("※"):
            f.gap(line.split(":")[0], "이 업종 경로에 필요하지만 DB에 없는 변수")

    # 4-1) 금리 결정 일정 (금통위·FOMC)
    next_checks = policy_calendar(f, b.get("meetings"), as_of)

    docs = [{"title": d["title"], "published": str(d["published"])[:10]} for d in (b.get("docs") or [])]
    # 5) 기업 노출도 (규칙 기반, exposure.py)
    rows = exposure.assess(f, sector, b.get("fund"), as_of, focus, b.get("report"), b.get("terms"),
                           b.get("ttm_op"))
    # 6) 미확인 전제 (R4): 헤지·결제 시점·판가 전가력 등. 노출 등급은 이 전제가 확인되지 않은 상태의 참고치
    prem = exposure.premises(f, rows, sector)
    open_items = [p["item"] for p in prem if p["status"] != "확인"]
    if open_items:
        f.note("미확인 전제(가정하지 말 것): " + ", ".join(open_items))
    return {"facts": f, "docs": docs, "period": f"거시 지표 최근 12개월 · 동조성 {period}", "sector": sector,
            "exposure": rows, "premises": prem, "focus": list(focus or []), "next_checks": next_checks}


def kor_date(day: str) -> str:
    """'2026-11-26' → '2026년 11월 26일' (Verifier 가 연·월·일 숫자를 장부 대조에서 빼는 형식)."""
    y, m, d = (int(x) for x in day[:10].split("-"))
    return f"{y}년 {m}월 {d}일"


def policy_calendar(f: Facts, bundle: dict | None, as_of: str) -> list[str]:
    """다음·직전 금리 결정까지 일수를 장부에 올리고, 다음 점검에 넣을 날짜 문장을 돌려줍니다.
    기준일(한국시간) 하루가 끝나기 전에 발표된 결정은 '직전', 그 뒤는 '다음'입니다."""
    from datetime import date, timedelta

    if bundle is None:
        f.gap("금리 결정 일정", "core.policy_meeting 없음 (kic-agent-data 021 적용 전)")
        return []
    rows = (bundle or {}).get("meetings") or []
    cutoff = (date.fromisoformat(as_of) + timedelta(days=1)).isoformat() + "T00:00"
    out: list[str] = []
    for bank, name in MEETING_NAMES.items():
        mine = [m for m in rows if m.get("bank") == bank and m.get("kst")]
        past = [m for m in mine if m["kst"] < cutoff]
        fut = [m for m in mine if m["kst"] >= cutoff]
        if past:
            m = past[-1]
            f.add(f"직전 {name} 후 경과 일수({kor_date(m['kst'])} 한국시간)", days_between(m["kst"][:10], as_of), "일",
                  as_of, SRC_PM, kind="calc", group="금리 일정")
        if not fut:
            f.gap(f"다음 {name} 일정", "공표 전이거나 core.policy_meeting 에 아직 없음")
            continue
        m = fut[0]
        extra = ("경제전망 발표 회의" if m.get("sep") else "") + (", 일정 잠정" if m.get("status") == "tentative" else "")
        when = kor_date(m["kst"])
        days = days_between(as_of, m["kst"][:10])
        k = f.add(f"다음 {name}까지 일수({when} {m['kst'][11:16]} 한국시간{', ' + extra.strip(', ') if extra else ''})",
                  days, "일", as_of, SRC_PM, kind="calc", group="금리 일정",
                  note="FOMC 는 미 동부시간 14시 발표라 한국시간으로는 다음 날 새벽" if bank == "FOMC" else None)
        if k and days <= EVENT_SOON:
            f.flag(f"금리 이벤트 임박: {when} {name} ({{{k}}} 남음)")
        out.append(f"{when} {name}(한국시간)" + (" · 경제전망 포함" if m.get("sep") else ""))
    return out


def bisect_left_days(days: list[str], d: str) -> int:
    lo, hi = 0, len(days)
    while lo < hi:
        mid = (lo + hi) // 2
        if days[mid] < d:
            lo = mid + 1
        else:
            hi = mid
    return lo
