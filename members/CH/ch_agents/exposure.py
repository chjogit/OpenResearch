"""에이전트 1 기업 노출도: 규칙 기반 노출 지표 (기초기획서 R2 3.2, 리스크 대응 '규칙 기반 노출 지표 우선, LLM은 해석만').

거시 변수 4개(환율·금리·원자재·물가, 수출·경기)마다 노출 등급(높음/중간/낮음)을 코드가 정합니다.
LLM은 이 등급을 바꾸지 못하고, 판정 문장에 붙은 근거 키만 인용해 해석합니다.

등급은 세 가지 근거를 정해진 순서로 합칩니다.
1. 업종 기본값: KRX 업종별 거시 전달 경로(아래 SECTOR_PRIOR). 업종 공통의 출발점일 뿐 회사 고유 값이 아닙니다.
2. 통계 근거: 주가와 그 변수의 250일 상관이 유의하고 |상관| >= 0.3 이면 한 단계 올립니다
   (동조성은 통계적 관계이지 노출이 아니므로 '내리는' 근거로는 쓰지 않습니다).
3. 재무 구조: 금리 변수만. 최근 사업연도 부채비율 200% 이상이면 한 단계 올리고, 50% 이하면 한 단계 내립니다.
   금융업은 부채비율의 의미가 달라 적용하지 않습니다.

회사 공시값(kic-agent-data 가 사업보고서 원문 표에서 뽑아 core.report_exposure 에 저장)이 있으면 먼저 씁니다.
- 환율: 환율 n% 상승 시 손익 영향(전 통화 합계)을 10% 기준으로 맞춰 영업이익과 비교 (10%↑ 높음, 3%↑ 중간)
- 수출·경기: 수출 매출 비중 (60%↑ 높음, 30%↑ 중간)
- 달러 순자산과 외환 파생상품 사용 여부는 근거로 보여 주기만 하고 등급에는 쓰지 않습니다.
- 금리: 이자율 1%p 상승 시 손익 영향(주석 민감도 표)과 차입 조건(TERMS_SQL: 회사채·CP·단기사채 1년 내 만기 비중,
  미상환 회사채 가중평균 발행금리, 자회사 포함 발행금리)은 근거로 보여 주고 미확인 전제의 상태만 바꿉니다(등급 규칙은 그대로).
- 매출채권 회수기간(DSO)은 '결제 시점' 전제의 근거로만 씁니다. 판가 전가력은 숫자로 만들지 않습니다.
"""
from __future__ import annotations

import re

from .availability import AVAIL_SHORT, availability
from .facts import Facts, corr_label, days_between, significant

LEVELS = ("낮음", "중간", "높음")
VARIABLES = ("환율", "금리", "원자재·물가", "수출·경기")

# 업종 기본값 (0 낮음, 1 중간, 2 높음): 환율, 금리, 원자재·물가, 수출·경기
SECTOR_PRIOR: dict[str, tuple[int, int, int, int]] = {
    "반도체": (2, 1, 0, 2),
    "전기·전자": (2, 1, 1, 2),
    "운송장비·부품": (2, 1, 1, 2),
    "기계·장비": (2, 1, 1, 2),
    "화학": (1, 1, 2, 2),
    "금속": (1, 1, 2, 2),
    "비금속": (0, 1, 2, 1),
    "섬유·의류": (2, 0, 1, 1),
    "의료·정밀기기": (1, 1, 0, 1),
    "제약": (1, 1, 0, 1),
    "음식료·담배": (1, 0, 2, 0),
    "유통": (0, 1, 2, 1),
    "건설": (0, 2, 1, 2),
    "전기·가스": (2, 2, 2, 0),
    "운송·창고": (2, 1, 2, 2),
    "통신": (0, 1, 0, 0),
    "IT 서비스": (0, 1, 0, 1),
    "일반서비스": (0, 1, 0, 1),
    "오락·문화": (1, 1, 0, 1),
    "은행": (0, 2, 0, 2),
    "증권": (0, 2, 0, 2),
    "보험": (0, 2, 0, 1),
    "기타금융": (0, 2, 0, 1),
}
DEFAULT_PRIOR = (1, 1, 1, 1)
PATH = {  # 변수별로 무엇을 거쳐 실적에 닿는지 (가이드 모드 설명용, 숫자 없음)
    "환율": "수출 대금의 원화 환산, 원재료·부품 수입 비용, 외화 부채 평가",
    "금리": "차입 이자 비용, 할인율(주가 평가), 금융업은 예대마진·운용 수익",
    "원자재·물가": "원재료 가격과 판매가 전가, 가계 구매력",
    "수출·경기": "제품 수요와 물량, 업황 사이클",
}
# 변수별 통계 근거로 볼 동조성 항목 (agent1_macro.py 의 '주가-<이름> 상관(250일)')
STAT_DRIVERS = {
    "환율": ("원/달러",),
    "금리": ("미국 10년 국채금리", "국고채 3년 금리"),
    "원자재·물가": ("WTI 유가",),
    "수출·경기": ("필라델피아 반도체지수",),
}
FINANCIAL = {"은행", "증권", "보험", "기타금융"}
STRONG_CORR = 0.3
HIGH_DEBT, LOW_DEBT = 200.0, 50.0
SMALL_DEBT_SHARE = 1.0   # 사채·CP 미상환 잔액이 총부채의 이 % 미만이면 만기 비중·발행금리를 '참고'로만 표시
FEW_BONDS = 3            # 발행금리 표본(미상환 회사채 건수)이 이보다 적으면 '표본 적음'
STALE_REPORT_DAYS = 180  # 사업보고서 회계연도 말에서 기준일까지 이 일수가 넘으면 '기준 시점 주의'
TTM_MAX_SPAN = 290       # 연속 4개 분기의 첫 분기말~마지막 분기말 (core.v_ttm 과 같은 기준)
UNKNOWN_NOW = "사업보고서 원문 추출값 없음 (kic-agent-data report-exposure 수집 전이거나 표를 찾지 못함)"


def _corr_evidence(f: Facts, names: tuple[str, ...]) -> tuple[str | None, float | None, int | None]:
    for name in names:
        k = f.key_of(f"주가-{name} 상관(250일)")
        if not k:
            continue
        it = f.items[k]
        n = None
        note = it.get("note") or ""
        if "거래일" in note:
            try:
                n = int(note.split("거래일")[0].strip().split()[-1])
            except ValueError:
                n = None
        return k, it["value"], n
    return None, None, None


REPORT_SQL = """
SELECT fiscal_year, metric, currency, value, change_pct, basis, rcept_no
FROM core.report_exposure
WHERE company_id = %(cid)s
  AND fiscal_year = (SELECT max(fiscal_year) FROM core.report_exposure
                     WHERE company_id = %(cid)s
                       AND fiscal_year <= extract(year FROM %(as_of)s::date - 90)::int - 1)
"""
# 회사채 발행실적의 발행사 이름은 공시마다 표기가 달라(한글 표기·정식 이름·옛 이름) 회사 마스터 이름과 바로 맞지
# 않습니다. 이름을 정규화한 뒤 '같은지'로 비교합니다. '포함'으로 비교하면 자회사(한화 → 한화오션, 신세계 →
# 신세계디에프)가 모회사 금리에 섞입니다. 별칭은 DB에서 확인한 회사 자신의 발행사 표기만 넣고 자회사는 넣지 않습니다.
# kic-agent-data 가 DART 기업개황 정식 회사명(core.company.legal_name)을 채우면 TERMS_SQL 이 그것도 함께 비교하므로,
# 정식 회사명으로 맞춰지는 회사는 별칭이 필요 없습니다 (별칭은 옛 이름·공시마다 다른 표기용으로 남김).
# OCI홀딩스(010060)에는 'OCI' 별칭을 두지 않습니다. 반기보고서의 OCI주식회사 제88·89회 채권(2024~2025년 발행)은
# 분할 신설회사 OCI(456040) 보고서에도 같은 채권으로 실리는 자회사 발행분입니다.
ISSUER_ALIASES: dict[str, tuple[str, ...]] = {
    "000120": ("씨제이대한통운",),
    "001040": ("씨제이",),
    "001450": ("현대해상화재보험",),
    "002380": ("케이씨씨",),
    "005300": ("롯데칠성음료",),
    "005380": ("현대자동차",),
    "005490": ("포스코홀딩스",),
    "005940": ("엔에이치투자증권",),
    "007070": ("지에스리테일",),
    "007340": ("디엔오토모티브",),
    "024110": ("중소기업은행",),
    "030200": ("케이티",),
    "033780": ("케이티앤지",),
    "035420": ("네이버",),
    "036570": ("엔씨", "엔씨소프트"),
    "047810": ("한국항공우주산업",),
    "055550": ("신한금융지주",),
    "071320": ("한국지역난방공사",),
    "079550": ("엘아이지디펜스앤에어로스페이스",),
    "095340": ("아이에스시",),
    "097950": ("씨제이제일제당",),
    "105560": ("KB금융지주",),
    "120110": ("코오롱인더스트리",),
    "204320": ("에이치엘만도",),
    "298050": ("에이치에스효성첨단소재",),
}
_ISSUER_STRIP = re.compile(r"\(주\)|㈜|주식회사|\s")


def norm_issuer(name: str) -> str:
    """TERMS_SQL 의 발행사 정규화와 같은 규칙: (주)·㈜·'주식회사'·공백을 빼고 대문자로."""
    return _ISSUER_STRIP.sub("", str(name or "")).upper()


def issuer_names(co: dict) -> list[str]:
    """회사 자신의 발행사로 볼 이름 (정규화 후). 회사 마스터 이름 + 별칭."""
    names = [co.get("name") or "", *ISSUER_ALIASES.get(str(co.get("ticker") or ""), ())]
    return list(dict.fromkeys(n for n in map(norm_issuer, names) if n))


def terms_params(co: dict, as_of: str) -> dict:
    return {"cid": co["company_id"], "as_of": as_of, "issuers": issuer_names(co)}


# 차입 조건·매출채권 회수기간 (kic-agent-data 019, 작업 debt-terms). 정기보고서는 기말 뒤 제출 기한
# (사업보고서 90일, 분·반기 45일)이 지난 것만 씁니다 (평가 시점에 공개되지 않았던 값을 쓰지 않도록).
TERMS_SQL = """
WITH due AS (
    SELECT b.kind, b.fiscal_year, b.reprt_code, b.label, max(b.stlm_dt) AS stlm_dt,
           max(b.amount_raw) FILTER (WHERE b.bucket = 'total') AS total,
           coalesce(sum(b.amount_raw) FILTER (WHERE b.bucket IN ('1y','10d','10-30d','30-90d','90-180d','180d-1y')), 0)
               AS within_1y
    FROM core.debt_balance b
    WHERE b.company_id = %(cid)s
      AND b.stlm_dt + CASE WHEN b.reprt_code = '11011' THEN 90 ELSE 45 END <= %(as_of)s::date
    GROUP BY b.kind, b.fiscal_year, b.reprt_code, b.label
), mat AS (
    SELECT DISTINCT ON (kind) kind, fiscal_year, reprt_code, stlm_dt, total, within_1y
    FROM due WHERE total > 0
    ORDER BY kind, stlm_dt DESC, (label ~ '합계') DESC, total DESC
), iss_rep AS (
    SELECT fiscal_year, reprt_code, max(stlm_dt) AS stlm_dt FROM core.debt_issue
    WHERE company_id = %(cid)s
      AND stlm_dt + CASE WHEN reprt_code = '11011' THEN 90 ELSE 45 END <= %(as_of)s::date
    GROUP BY fiscal_year, reprt_code ORDER BY max(stlm_dt) DESC LIMIT 1
), me AS (  -- DART 기업개황 정식 회사명 (kic-agent-data 020 legal_name). 열이 아직 없으면 NULL
    SELECT nullif(upper(regexp_replace(coalesce(to_jsonb(c) ->> 'legal_name', ''), '\\(주\\)|㈜|주식회사|\\s', '', 'g')),
                  '') AS legal
    FROM core.company c WHERE c.company_id = %(cid)s
), bonds AS (  -- 회사채만 (녹색·사회적·지속가능채권 포함). 전자단기사채는 1년 내 만기 비중에서 따로 봄
    SELECT x.*, (x.issuer ~ '^\\s*당\\s*사\\s*$'           -- 발행사를 '당사'로 적은 경우 (기아)
                 OR x.issuer_norm = ANY(%(issuers)s::text[])  -- 마스터 이름 + 별칭
                 OR x.issuer_norm = (SELECT legal FROM me)) AS own
    FROM (SELECT i.*, upper(regexp_replace(regexp_replace(i.issuer, '\\(제[^)]*\\)|\\(?주\\d+\\)', '', 'g'),
                                           '\\(주\\)|㈜|주식회사|\\s', '', 'g')) AS issuer_norm
          FROM core.debt_issue i JOIN iss_rep r USING (fiscal_year, reprt_code)
          WHERE i.company_id = %(cid)s AND i.rate > 0 AND i.face_amount_raw > 0
            AND i.kind_nm ~ '회사채' AND coalesce(i.repaid, '') !~ '^상환') x
), iss AS (
    SELECT * FROM bonds WHERE own
), grp AS (  -- 자회사 포함(연결 발행실적). 유동화 SPC(제N차·제N호·유동화)는 그룹 조달이 아니라 뺌
    SELECT * FROM bonds
    WHERE own OR issuer !~ '제\\s*[일이삼사오육칠팔구십백0-9]+\\s*(차|호)|유동화'
), dso AS (
    SELECT * FROM core.v_dso
    WHERE ticker = (SELECT ticker FROM core.company WHERE company_id = %(cid)s) AND market = 'KR'
      AND dso_days IS NOT NULL
      AND period_end + CASE WHEN report_code = '11011' THEN 90 ELSE 45 END <= %(as_of)s::date
    ORDER BY period_end DESC LIMIT 1
), bor AS (  -- 총차입금: 재무상태표 차입 계정 합 (kic-agent-data 024, source 'dart_borrow'). 금융업 '차입부채'는 뺌
    SELECT fiscal_year, report_code, fs_div, max(period_end) AS period_end,
           sum(amount) FILTER (WHERE account_nm !~ '차입부채') AS total, count(*) AS n,
           string_agg(split_part(account_nm, '#', 1), '·' ORDER BY amount DESC) AS accounts
    FROM core.financial_fact
    WHERE company_id = %(cid)s AND source = 'dart_borrow' AND sj_div = 'BS' AND period_end IS NOT NULL
      AND period_end + CASE WHEN report_code = '11011' THEN 90 ELSE 45 END <= %(as_of)s::date
    GROUP BY fiscal_year, report_code, fs_div
    ORDER BY max(period_end) DESC, (fs_div = 'CFS') DESC LIMIT 1
), fscb AS (  -- 회사채 발행 종목(금융위원회_채권발행정보, kic-agent-data 025). 기준일에 발행돼 있고 만기 전인 본인 발행 종목
    SELECT * FROM core.bond_issue_fsc
    WHERE company_id = %(cid)s AND issue_amount > 0 AND issue_date <= %(as_of)s::date
      AND (maturity_date IS NULL OR maturity_date > %(as_of)s::date)
)
SELECT json_build_object(
    'maturity', (SELECT json_agg(row_to_json(mat)) FROM mat),
    'bond_rate', (SELECT json_build_object(
                    'stlm_dt', (SELECT stlm_dt FROM iss_rep), 'n', count(*),
                    'wavg', sum(rate * face_amount_raw) / NULLIF(sum(face_amount_raw), 0),
                    'min', min(rate), 'max', max(rate)) FROM iss),
    'bond_rate_group', (SELECT json_build_object(
                    'n', count(*), 'issuers', count(DISTINCT CASE WHEN own THEN '' ELSE issuer_norm END),
                    'wavg', sum(rate * face_amount_raw) / NULLIF(sum(face_amount_raw), 0),
                    'min', min(rate), 'max', max(rate)) FROM grp),
    'dso', (SELECT row_to_json(dso) FROM dso),
    'borrow', (SELECT row_to_json(bor) FROM bor),
    'fsc_bonds', (SELECT json_build_object(
                    'n', count(*), 'amount', sum(issue_amount),
                    'floating', sum(issue_amount) FILTER (WHERE rate_kind = 'floating'),
                    'known', sum(issue_amount) FILTER (WHERE rate_kind IS NOT NULL),
                    'wavg', sum(issue_amount * coupon_rate) FILTER (WHERE coupon_rate IS NOT NULL)
                            / NULLIF(sum(issue_amount) FILTER (WHERE coupon_rate IS NOT NULL), 0),
                    'next_maturity', min(maturity_date)) FROM fscb),
    'price_excerpts', (SELECT count(*) FROM rag.document d
                       WHERE d.company_id = %(cid)s AND d.source = 'dart_report' AND d.title ~ '가격변동'
                         AND d.published_at::date <= %(as_of)s::date)
) AS bundle
"""
SRC_TERMS = "core.debt_balance·core.debt_issue (DART 정기보고서 주요정보)"
SRC_FSC_BOND = "core.bond_issue_fsc (금융위원회_채권발행정보, 출처: 금융위원회·한국예탁결제원)"
SRC_BORROW = "core.financial_fact dart_borrow (DART 전체 재무제표 재무상태표 차입 계정)"
SRC_DSO = "core.v_dso (DART 전체 재무제표 매출채권 ÷ 4개 분기 매출)"
SRC_REPORT = "core.report_exposure (DART 사업보고서 원문 표)"
FX_HIGH, FX_MID = 10.0, 3.0          # 환율 10% 상승 시 손익 영향 ÷ 영업이익 (%)
EXP_HIGH, EXP_MID = 60.0, 30.0       # 수출 비중 (%)


def ttm_operating_income(ttm: dict | None) -> tuple[float, str] | None:
    """기준일에 공시돼 있던 최근 4개 분기 영업이익 합 (agent1 SQL 'ttm_op'). 4개가 연속(약 1년 안)일 때만."""
    t = ttm or {}
    if t.get("n") != 4 or t.get("operating_income_ttm") is None or not t.get("ttm_end") or not t.get("first_end"):
        return None
    if days_between(str(t["first_end"]), str(t["ttm_end"])) > TTM_MAX_SPAN:
        return None
    return float(t["operating_income_ttm"]), str(t["ttm_end"])[:10]


def _report_facts(f: Facts, report: list[dict] | None, fundamentals: dict | None, ttm: dict | None = None) -> dict:
    """원문 추출값을 장부에 올리고, 등급 판단에 쓸 값을 돌려줍니다."""
    got: dict = {}
    if not report:
        return got
    fy = report[0].get("fiscal_year")
    when = f"FY{fy}"
    by = {(r["metric"], r["currency"]): r for r in report}
    sens = [r for r in report if r["metric"] == "fx_sens" and r.get("value") is not None]
    if sens:
        pct = next((float(r["change_pct"]) for r in sens if r.get("change_pct")), None)
        basis = next((r["basis"] for r in sens if r.get("basis")), None) or "손익"
        usd = by.get(("fx_sens", "USD"))
        total = sum(float(r["value"]) for r in sens)
        label_pct = f"{pct:g}%" if pct else "n%(원문 미기재)"
        got["k_sens"] = f.add(f"환율 {label_pct} 상승 시 {basis} 영향(전 통화 합계, {when})", total, "KRW±", when,
                              SRC_REPORT, kind="report", group="노출 근거",
                              note="사업보고서 재무위험관리 주석의 민감도 표. 회사가 공시한 값")
        if usd:
            f.add(f"환율 {label_pct} 상승 시 {basis} 영향(USD, {when})", float(usd["value"]), "KRW±", when, SRC_REPORT,
                  kind="report", group="노출 근거")
        oi = (fundamentals or {}).get("operating_income")
        if basis == "자본":  # 자본(기타포괄손익 포함) 기준 민감도는 손익이 아니므로 영업이익과 비교하지 않음
            got["equity_basis"] = True
        elif pct and oi and float(oi) > 0:
            ratio = total * (10.0 / pct) / float(oi) * 100
            got["ratio"] = ratio
            got["k_ratio"] = f.add(f"환율 10% 상승 시 손익 영향 ÷ 영업이익({when})", ratio, "%", when,
                                   SRC_REPORT + " × core.v_fundamentals_annual", kind="calc", group="노출 근거",
                                   note="변동 폭을 10%로 맞춘 값. +면 원화 약세(환율 상승)에 손익 증가, -면 감소")
        t = ttm_operating_income(ttm)
        if basis != "자본" and pct and t and t[0] > 0:
            got["k_ratio_ttm"] = f.add(f"환율 10% 상승 시 손익 영향 ÷ 영업이익(TTM, {t[1][:7]}까지 4개 분기)",
                                       total * (10.0 / pct) / t[0] * 100, "%", t[1],
                                       SRC_REPORT + " × core.financial_quarter", kind="calc", group="노출 근거",
                                       note=f"분자는 {when} 공시 민감도, 분모는 기준일에 공시돼 있던 최근 4개 분기 영업이익 합. "
                                            "최근 실적 규모 대비 크기를 보는 참고치이고, 등급은 같은 회계연도끼리 비교한 연간 비율로 정함")
    exp = by.get(("export_share", "ALL"))
    if exp and exp.get("value") is not None:
        got["export"] = float(exp["value"])
        got["k_export"] = f.add(f"수출 매출 비중({when})", float(exp["value"]), "%", when, SRC_REPORT, kind="report",
                                group="노출 근거", note="사업의 내용 '매출 실적'의 내수·수출 표에서 계산 (별도 기준일 수 있음)")
    a, li = by.get(("fx_asset", "USD")), by.get(("fx_liab", "USD"))
    if a and li and a.get("value") is not None and li.get("value") is not None:
        got["k_net"] = f.add(f"달러 화폐성 순자산(자산 − 부채, {when})", float(a["value"]) - float(li["value"]), "KRW±",
                             when, SRC_REPORT, kind="calc", group="노출 근거",
                             note="+면 환율 상승 시 환산 이익 방향, -면 손실 방향")
    if by.get(("fx_derivative", "ALL")):
        got["hedge"] = True
    if by.get(("fx_hedge_acct", "ALL")):   # kic-agent-data 파서 v2 (10-29)
        got["hedge_acct"] = True
    liab = by.get(("ir_sens_liab", "ALL"))   # v2: 이자율 민감도 표의 부채 쪽 행만의 영향 → 변동금리부 부채 역산 (근거로만)
    if liab and liab.get("value") is not None and liab.get("change_pct"):
        chg = float(liab["change_pct"])
        est = abs(float(liab["value"])) / (chg / 100)
        got["float_est"] = est
        got["k_float"] = f.add(f"변동금리부 부채 추정(이자율 민감도 역산, {when})", est, "KRW", when, SRC_REPORT,
                               kind="proxy", group="노출 근거",
                               note=(f"이자율 민감도 표의 부채 쪽 행({chg:g}%p 상승 시 영향)을 {chg:g}%p 로 나눈 값. "
                                     "공시 정형값이 아니고 금융부채·차입금 범위는 회사마다 다름. 노출 등급에는 쓰지 않음"))
        tot = (fundamentals or {}).get("liabilities")
        if tot and float(tot) > 0:
            got["k_float_ratio"] = f.add(f"변동금리부 부채 추정 ÷ 부채총계({when})", est / float(tot) * 100, "%", when,
                                         SRC_REPORT + " × core.v_fundamentals_annual", kind="calc", group="노출 근거",
                                         note="대용치 비율. 부채총계에는 무이자 부채도 들어 있어 '차입금 중 변동금리 비중'보다 작게 나옴")
    ir = by.get(("ir_sens", "ALL"))
    if ir and ir.get("value") is not None:
        pct = float(ir["change_pct"]) if ir.get("change_pct") else None
        got["k_ir"] = f.add(f"이자율 {f'{pct:g}%p' if pct else 'n%p(원문 미기재)'} 상승 시 {ir.get('basis') or '손익'} "
                            f"영향({when})", float(ir["value"]), "KRW±", when, SRC_REPORT, kind="report",
                            group="노출 근거", note="재무위험관리 주석의 이자율 민감도 표 (변동금리부 자산·부채 기준)")
    return got


def _basis_check(f: Facts, report: list[dict] | None, fundamentals: dict | None, terms: dict | None,
                 as_of: str, ttm_key: str | None = None) -> None:
    """노출 근거의 기준 시점이 섞이거나 오래됐는지 알립니다 (P0).

    환율 민감도·부채비율은 사업보고서 연간(FY) 기준이고, 매출채권 회수기간은 최근 정기보고서·4개 분기 매출 기준입니다.
    10/28 실행에서 FY2025 영업이익을 분모로 쓴 비율이 2026년 실적 규모와 맞지 않았는데 표시가 없었습니다."""
    fy = (report or [{}])[0].get("fiscal_year") or (fundamentals or {}).get("fiscal_year")
    if not fy:
        return
    try:
        age = days_between(f"{int(fy)}-12-31", as_of)
    except (TypeError, ValueError):
        return
    if age <= STALE_REPORT_DAYS:
        return
    dso = (terms or {}).get("dso") or {}
    mixed = f" 매출채권 회수기간은 {str(dso['period_end'])[:7]} 정기보고서 기준이라 시점이 다름." if dso.get("period_end") else ""
    tail = (f" 최근 4개 분기 영업이익 대비 비율은 {{{ttm_key}}}" if ttm_key
            else " 영업이익 대비 비율은 최근 실적 규모에서는 달라질 수 있음")
    f.flag(f"기준 시점 주의: 환율·이자율 민감도와 부채비율은 FY{fy} 사업보고서(연간) 기준이라 이후 분기 실적 변화가 "
           f"반영되지 않음.{mixed}{tail}")
    if not ttm_key:
        f.gap("최근 4개 분기(TTM) 영업이익 대비 환율 민감도", "기준일에 공시된 연속 4개 분기 영업이익 없음 (분기 재무 미수집 또는 결측)")


def _when(d: str | None, code: str | None) -> str:
    q = {"11013": "1분기", "11012": "반기", "11014": "3분기", "11011": "사업"}.get(code or "", "")
    return f"{(d or '')[:7]} {q}보고서".strip()


def _terms_facts(f: Facts, terms: dict | None, fundamentals: dict | None = None, financial: bool = False) -> dict:
    """차입 조건·매출채권 회수기간을 장부에 올립니다. 금액 단위는 원문 표를 따르므로 비율만 씁니다.

    규모(P0): 10/28 실행에서 삼성전자 '1년 내 만기 50%'·'발행금리 7.70%'가 미상환 회사채 1건(총부채의 0.01% 수준)
    에서 나온 값인데 총부채 기준 지표와 같은 무게로 보였습니다. 총부채 대비 잔액 비중과 표본 수를 함께 올리고,
    작으면 '참고'로 표시합니다(등급 규칙은 원래대로 이 값들을 쓰지 않음)."""
    got: dict = {}
    if not terms:
        return got
    mat = [m for m in terms.get("maturity") or [] if m.get("total")]
    if mat:
        tot = sum(float(m["total"]) for m in mat)
        liab = (fundamentals or {}).get("liabilities")
        if liab and float(liab) > 0:
            share = tot / float(liab) * 100
            got["k_mat_share"] = f.add(
                f"사채·CP 미상환 잔액 ÷ 총부채(FY{(fundamentals or {}).get('fiscal_year')} 부채 기준)", share, "%",
                f"FY{(fundamentals or {}).get('fiscal_year')}", SRC_TERMS + " × core.v_fundamentals_annual", kind="calc",
                group="노출 근거", note="정기보고서 미상환 잔액(원문 표 단위를 원으로 봄) ÷ 연간 부채총계. 규모 판단용")
            if share < SMALL_DEBT_SHARE:
                got["small_debt"] = True
                f.flag(f"규모 주의: 사채·CP 미상환 잔액이 총부채에서 차지하는 비중이 작음 ({{{got['k_mat_share']}}}). "
                       "만기 비중·회사채 발행금리는 전체 차입 조건을 대표하지 않는 참고치")
        within = sum(float(m["within_1y"] or 0) for m in mat)
        last = max(mat, key=lambda m: m["stlm_dt"] or "")
        kinds = "·".join({"bond": "회사채", "cp": "CP", "stb": "단기사채"}.get(m["kind"], m["kind"]) for m in mat)
        got["k_mat"] = f.add(f"1년 안에 만기가 오는 비중({kinds} 미상환 잔액, {_when(last['stlm_dt'], last['reprt_code'])})",
                             within / tot * 100 if tot else None, "%", last["stlm_dt"], SRC_TERMS, kind="calc",
                             group="노출 근거", note="잔여만기 구간별 미상환 잔액에서 계산. 은행 차입금은 포함하지 않음")
    br = terms.get("bond_rate") or {}
    if br.get("n") and br["n"] < FEW_BONDS:
        got["few_bonds"] = True
    if br.get("n") and br.get("wavg") is not None:
        got["k_rate"] = f.add(f"미상환 회사채 가중평균 발행금리({br['n']}건, {(br.get('stlm_dt') or '')[:7]} 기준)",
                              float(br["wavg"]), "%", br.get("stlm_dt"), SRC_TERMS, kind="calc", group="노출 근거",
                              note=f"발행 당시 표면금리를 권면총액으로 가중. 범위 {br.get('min')}~{br.get('max')}%")
    grp = terms.get("bond_rate_group") or {}
    if grp.get("n") and grp.get("wavg") is not None and grp["n"] > (br.get("n") or 0):
        # 자회사 발행분이 있을 때만: 금융지주·지주사는 실제 조달 대부분을 자회사가 하므로 회사 자체 금리와 나란히 보여 줌
        got["k_rate_grp"] = f.add(
            f"자회사 포함 미상환 회사채 가중평균 발행금리({grp['n']}건·발행사 {grp.get('issuers')}곳, "
            f"{(br.get('stlm_dt') or '')[:7]} 기준)", float(grp["wavg"]), "%", br.get("stlm_dt"), SRC_TERMS,
            kind="calc", group="노출 근거",
            note=f"정기보고서 연결 발행실적 기준(유동화 SPC 제외). 범위 {grp.get('min')}~{grp.get('max')}%. "
                 "발행실적에 통화 구분이 없어 해외 자회사 외화채 금리가 섞일 수 있음. 등급에는 쓰지 않음")
    dso = terms.get("dso")
    if dso and dso.get("dso_days") is not None:
        got["k_dso"] = f.add(f"매출채권 회수기간({_when(dso.get('period_end'), dso.get('report_code'))})",
                             float(dso["dso_days"]), "일", dso.get("period_end"), SRC_DSO, kind="calc",
                             group="노출 근거", note=f"기말 '{dso.get('receivable_account')}' ÷ 4개 분기 매출 × 365")
    bor = {} if financial else (terms.get("borrow") or {})   # 금융업의 사채·차입은 영업 자금이라 차입 부담으로 보지 않음
    if bor.get("total") is not None:
        when = _when(bor.get("period_end"), bor.get("report_code"))
        got["borrow_total"] = float(bor["total"])
        got["k_borrow"] = f.add(f"총차입금({when})", float(bor["total"]), "KRW", bor.get("period_end"), SRC_BORROW,
                                kind="calc", group="노출 근거",
                                note=f"재무상태표 차입 계정 합({bor.get('accounts')}). 리스부채 제외, "
                                     f"{'연결' if bor.get('fs_div') == 'CFS' else '별도'} 기준")
        liab = (fundamentals or {}).get("liabilities")
        if liab and float(liab) > 0:
            got["k_borrow_share"] = f.add(f"총차입금 ÷ 부채총계({when} ÷ FY{(fundamentals or {}).get('fiscal_year')})",
                                          float(bor["total"]) / float(liab) * 100, "%", bor.get("period_end"),
                                          SRC_BORROW + " × core.v_fundamentals_annual", kind="calc", group="노출 근거",
                                          note="부채 중 이자가 붙는 차입의 비중(시점이 다를 수 있음). 등급에는 쓰지 않음")
    fb = {} if financial else (terms.get("fsc_bonds") or {})
    if fb.get("n") and fb.get("known"):
        got["k_bond_float"] = f.add(f"본인 발행 회사채 중 변동금리 비중(발행금액 기준, {fb['n']}종목)",
                                    float(fb.get("floating") or 0) / float(fb["known"]) * 100, "%", None, SRC_FSC_BOND,
                                    kind="calc", group="노출 근거",
                                    note="기준일에 발행돼 있고 만기 전인 종목(조기상환 미반영). 자회사 발행분·은행 차입 제외")
        if fb.get("wavg") is not None:
            got["k_bond_coupon"] = f.add(f"본인 발행 회사채 가중평균 표면이율({fb['n']}종목)", float(fb["wavg"]), "%", None,
                                         SRC_FSC_BOND, kind="calc", group="노출 근거",
                                         note=f"발행금액 가중. 가장 가까운 만기 {fb.get('next_maturity') or '-'}")
    got["price_excerpts"] = int(terms.get("price_excerpts") or 0)
    return got


def _float_share(f: Facts, rep: dict) -> None:
    """변동금리부 부채 추정(민감도 역산) ÷ 총차입금. 둘 다 있을 때만, 근거로만(등급 불변).
    역산값에는 차입금 밖의 금융부채가 섞일 수 있어 100% 를 넘으면 값 대신 범위 불일치 주의만 남깁니다."""
    est, tot = rep.get("float_est"), rep.get("borrow_total")
    if not est or not tot or tot <= 0:
        return
    share = est / tot * 100
    if share > 100:
        f.flag(f"범위 주의: 변동금리부 부채 추정 {{{rep['k_float']}}}이 총차입금 {{{rep['k_borrow']}}}보다 큼 "
               "(민감도 표의 부채 범위가 차입금보다 넓음). 변동금리 비중은 계산하지 않음")
        return
    rep["k_float_borrow"] = f.add("변동금리부 부채 추정 ÷ 총차입금", share, "%", None,
                                  SRC_REPORT + " × " + SRC_BORROW, kind="proxy", group="노출 근거",
                                  note="대용치. 민감도 역산(사업보고서 연말)과 총차입금(최근 보고서)의 시점이 다를 수 있음. "
                                       "등급에는 쓰지 않음")


def assess(f: Facts, sector: str, fundamentals: dict | None, as_of: str, focus: list[str] | None = None,
           report: list[dict] | None = None, terms: dict | None = None, ttm: dict | None = None) -> list[dict]:
    """노출 등급을 정해 판정 문장을 장부에 올리고, 표에 쓸 행 목록을 돌려줍니다.
    회사 공시값(사업보고서 원문)이 있으면 그것이 업종 기본값보다 먼저입니다."""
    prior = SECTOR_PRIOR.get(sector, DEFAULT_PRIOR)
    debt_key = None
    debt = None
    if fundamentals and sector not in FINANCIAL:
        liab, eq = fundamentals.get("liabilities"), fundamentals.get("equity")
        if liab is not None and eq and eq > 0:
            debt = liab / eq * 100
            debt_key = f.add(f"부채비율(FY{fundamentals.get('fiscal_year')})", debt, "%",
                             f"FY{fundamentals.get('fiscal_year')}", "core.v_fundamentals_annual (DART)",
                             kind="calc", group="노출 근거", note="부채 ÷ 자본. 금리 노출 판단에만 사용")
    if fundamentals is None and sector not in FINANCIAL:
        f.gap("부채비율", "연간 재무 없음 (금리 노출은 업종 기본값만 사용)")
    rep = _report_facts(f, report, fundamentals, ttm)
    rep.update(_terms_facts(f, terms, fundamentals, financial=sector in FINANCIAL))
    _float_share(f, rep)
    _basis_check(f, report, fundamentals, terms, as_of, rep.get("k_ratio_ttm"))

    rows = []
    for i, var in enumerate(VARIABLES):
        level = prior[i]
        reasons = [f"업종({sector}) 기본 {LEVELS[prior[i]]}" if sector in SECTOR_PRIOR else "업종 미분류: 기본 중간"]
        keys: list[str] = []
        company = False
        if var == "환율" and "ratio" in rep:
            r = abs(rep["ratio"])
            level = 2 if r >= FX_HIGH else 1 if r >= FX_MID else 0
            reasons = [f"회사 공시 민감도: 영업이익 대비 {{{rep['k_ratio']}}}"]
            keys.append(rep["k_ratio"])
            if "k_ratio_ttm" in rep:
                reasons.append(f"최근 4개 분기 영업이익 대비 {{{rep['k_ratio_ttm']}}}")
                keys.append(rep["k_ratio_ttm"])
            company = True
        elif var == "환율" and "k_sens" in rep:
            why = "자본 기준이라" if rep.get("equity_basis") else "영업이익이 없어"
            reasons.append(f"회사 공시 민감도 {{{rep['k_sens']}}} ({why} 등급에는 미반영)")
            keys.append(rep["k_sens"])
        if var == "환율" and "k_net" in rep:
            reasons.append(f"달러 순자산 {{{rep['k_net']}}}")
            keys.append(rep["k_net"])
        if var == "환율" and rep.get("hedge"):
            reasons.append("외환 파생상품(통화선도 등) 사용 공시")
        if var == "수출·경기" and "export" in rep:
            e = rep["export"]
            level = 2 if e >= EXP_HIGH else 1 if e >= EXP_MID else 0
            reasons = [f"회사 공시 수출 비중 {{{rep['k_export']}}}"]
            keys.append(rep["k_export"])
            company = True
        k, r, n = _corr_evidence(f, STAT_DRIVERS[var])
        if k and r is not None and n and significant(r, n) and abs(r) >= STRONG_CORR:
            if not company:
                level = min(2, level + 1)
            reasons.append(f"주가와 {corr_label(r, n)} {{{k}}}")
            keys.append(k)
        if var == "금리":
            for k, label in (("k_ir", "회사 공시 이자율 민감도"), ("k_mat", "1년 내 만기 비중"), ("k_rate", "회사채 발행금리"),
                             ("k_rate_grp", "자회사 포함 회사채 발행금리")):
                if k in rep:
                    tag = ""
                    if k in ("k_mat", "k_rate", "k_rate_grp") and rep.get("small_debt"):
                        tag = "(규모 작음, 참고) "
                    elif k == "k_rate" and rep.get("few_bonds"):
                        tag = "(표본 적음, 참고) "
                    reasons.append(f"{label} {tag}{{{rep[k]}}}")
                    keys.append(rep[k])
        if var == "금리" and debt is not None and debt_key:
            if debt >= HIGH_DEBT:
                level = min(2, level + 1)
                reasons.append(f"부채비율 높음 {{{debt_key}}}")
                keys.append(debt_key)
            elif debt <= LOW_DEBT:
                level = max(0, level - 1)
                reasons.append(f"부채비율 낮음 {{{debt_key}}}")
                keys.append(debt_key)
        text = f"노출 점검 · {var}: {LEVELS[level]} (" + ", ".join(reasons) + ")"
        f.flag(text)
        rows.append({"var": var, "level": LEVELS[level], "reasons": reasons, "keys": keys, "path": PATH[var],
                     "focus": bool(focus and any(x in var for x in focus)), "company": company,
                     "basis": {k: v for k, v in rep.items() if k.startswith("k_") or k in ("price_excerpts", "hedge_acct")}})
    if not any(k in rep for k in ("k_sens", "ratio", "export", "k_net", "hedge", "k_ir")):
        f.gap("기업 고유 노출", UNKNOWN_NOW)
    else:
        if "ratio" not in rep and "k_sens" not in rep:
            f.gap("환율 민감도(회사 공시)", "사업보고서 원문에서 민감도 표를 찾지 못함")
        if "export" not in rep:
            f.gap("수출 매출 비중(회사 공시)", "사업보고서 원문에서 회사 전체 내수·수출 표를 찾지 못함")
    f.note("노출 등급 규칙: 회사 공시값(사업보고서 원문 표)이 있으면 그것으로, 없으면 업종 기본값에서 출발해 "
           "주가 동조성·부채비율로 조정. 헤지 효과는 수치로 반영하지 않음")
    if focus:
        rows.sort(key=lambda r: not r["focus"])
    return rows


# ---------------------------------------------------------------- 미확인 전제 (기초기획서 R4 2.2·4.2)
# 노출 등급은 아래 전제가 확인되지 않은 상태의 '참고치'입니다. 전제마다 상태(확인/일부 확인/미확인)를 코드가 정하고,
# LLM은 미확인 전제를 사실처럼 가정하지 못합니다 (교재 8장: 판매량·판가·헤지·결제 시점이 필요).
PREMISES = (
    ("환헤지 여부·비율", "헤지 비율·만기에 따라 환율 변화가 손익에 닿는 크기가 달라짐"),
    ("수출 대금 결제 통화·결제 시점", "결제 통화와 회수 기간에 따라 환율 효과가 반영되는 시점이 달라짐"),
    ("판가 전가력", "원가·환율 변화를 판매가에 넘길 수 있으면 이익 영향이 줄어듦"),
    ("달러 비용 비중(원재료·부품 수입 통화)", "달러 매출과 달러 비용이 상쇄되는 만큼 순노출이 줄어듦"),
    ("수출 매출 비중", "수출 비중이 클수록 환율·해외 경기 영향이 큼"),
    ("차입 조건(변동·고정금리 비중, 만기)", "변동금리 비중이 크면 금리 변화가 이자 비용에 바로 반영됨"),
)


def _key_prefix(f: Facts, prefix: str) -> str | None:
    return next((k for k, v in f.items.items() if v["label"].startswith(prefix)), None)


def premises(f: Facts, rows: list[dict], sector: str) -> list[dict]:
    """미확인 전제 목록: [{item, status, detail, why, keys}]. 상태는 장부와 노출표에서 코드가 정합니다."""
    fx = next((r for r in rows if r["var"] == "환율"), {"reasons": []})
    hedge = any("파생상품" in x for x in fx["reasons"])
    basis = (rows[0].get("basis") if rows else None) or {}
    k_net, k_exp = _key_prefix(f, "달러 화폐성 순자산"), _key_prefix(f, "수출 매출 비중")
    k_debt = _key_prefix(f, "부채비율(")
    k_ir, k_mat, k_rate, k_dso = (basis.get(k) for k in ("k_ir", "k_mat", "k_rate", "k_dso"))
    k_grp = basis.get("k_rate_grp")
    k_sens = basis.get("k_sens")
    k_float, k_float_ratio = basis.get("k_float"), basis.get("k_float_ratio")
    k_borrow, k_float_borrow = basis.get("k_borrow"), basis.get("k_float_borrow")
    k_bond_float, k_bond_coupon = basis.get("k_bond_float"), basis.get("k_bond_coupon")
    hedge_acct = bool(basis.get("hedge_acct"))
    out = []
    for item, why in PREMISES:
        status, detail, keys = "미확인", "DB에 자료 없음", []
        if item.startswith("환헤지"):
            if hedge and hedge_acct:
                status, detail = "일부 확인", ("사업보고서에 외환 파생상품 사용과 위험회피회계 적용 공시. 계약 규모는 회사마다 "
                                              "표기·단위가 달라 숫자로 쓰지 않음(환헤지 계약 원문 발췌는 참고 문서). 헤지 비율은 미확인")
            elif hedge:
                status, detail = "일부 확인", "사업보고서에 외환 파생상품 사용 공시. 헤지 비율·만기는 미확인"
            else:
                detail = "사업보고서 원문에서 외환 파생상품 표를 찾지 못했거나 미수집"
        elif item.startswith("수출 대금"):
            if k_dso:
                status, detail, keys = "일부 확인", "매출채권 회수기간만 확인. 결제 통화별 매출·회수 조건은 미확인", [k_dso]
            else:
                detail = "결제 통화별 매출·매출채권 회수 기간 자료 없음"
        elif item.startswith("판가"):
            n = basis.get("price_excerpts") or 0
            detail = (f"사업보고서 '가격변동 추이' 원문 발췌 {n}건만 있음(판단 근거로만 인용). 계약 구조·경쟁 강도 미확인, 판단 보류"
                      if n else "판매가 조정 조건(계약 구조·경쟁 강도) 자료 없음")
        elif item.startswith("달러 비용"):
            keys = [k for k in (k_net, k_sens) if k]
            if keys:
                status, detail = "일부 확인", ("화폐성 자산·부채의 달러 순액·환율 민감도만 공시값 있음. "
                                              "원재료·부품 비용의 통화 구성은 미확인")
        elif item.startswith("수출 매출") and k_exp:
            status, detail, keys = "확인", "사업보고서 매출 실적 표의 내수·수출 구분", [k_exp]
        elif item.startswith("수출 매출"):
            detail = "사업보고서 원문에서 회사 전체 내수·수출 표를 찾지 못했거나 미수집 (업종 기본값 사용)"
        elif item.startswith("차입"):
            keys = [k for k in (k_borrow, k_bond_float, k_bond_coupon, k_mat, k_rate, k_grp, k_ir, k_float,
                                k_float_borrow or k_float_ratio) if k]
            if sector in FINANCIAL and not keys:
                detail = "금융업: 예대 금리 구조·자산 부채 만기 차이 자료 없음"
            elif keys:
                status = "일부 확인"
                got = [x for x, k in (("총차입금", k_borrow), ("본인 발행 회사채 고정·변동 구분", k_bond_float),
                                      ("사채·CP 만기 구조", k_mat), ("회사채 발행금리", k_rate),
                                      ("자회사 포함 회사채 발행금리", k_grp), ("이자율 민감도", k_ir),
                                      ("변동금리부 부채 추정(민감도 역산)", k_float)) if k]
                rest = ("회사채의 고정·변동 구분은 확인, 은행 차입의 금리 조건은 미확인" if k_bond_float else
                        "변동금리 비중은 민감도 역산 추정치(총차입금 대비)뿐이고 은행 차입 조건은 미확인" if k_float_borrow else
                        "변동금리 비중은 민감도 역산 추정치뿐이고 은행 차입 조건은 미확인" if k_float else
                        "변동·고정금리 비중과 은행 차입 조건은 공시 정형 자료가 없어 미확인")
                detail = f"{'·'.join(got)} 확인. {rest}"
                keys += [k_debt] if k_debt else []
            elif k_debt:
                status, detail, keys = "일부 확인", "부채비율만 확인. 변동금리 비중·만기 구조는 미확인", [k_debt]
        out.append({"item": item, "status": status, "detail": detail, "why": why, "keys": keys})
    return out


def premises_md(items: list[dict], render) -> str:
    out = ["| 전제 | 상태 | 내용 | 왜 필요한가 | 채울 방법 |", "| --- | --- | --- | --- | --- |"]
    for p in items:
        keys = " ".join("{" + k + "}" for k in p["keys"])
        how = "-" if p["status"] == "확인" else AVAIL_SHORT.get(availability(p["item"], p["detail"]), "분류 전")
        out.append(f"| {p['item']} | {p['status']} | {render(p['detail'] + (' ' + keys if keys else ''))} | {p['why']} "
                   f"| {how} |")
    return "\n".join(out)


def table_md(rows: list[dict], render) -> str:
    out = ["| 거시 변수 | 노출 등급 | 근거 | 전달 경로 |", "| --- | --- | --- | --- |"]
    for r in rows:
        star = " (관심)" if r["focus"] else ""
        out.append(f"| {r['var']}{star} | {r['level']} | {render(', '.join(r['reasons']))} | {r['path']} |")
    return "\n".join(out)
