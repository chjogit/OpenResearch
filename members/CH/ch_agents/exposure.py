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
"""
from __future__ import annotations

from .facts import Facts, significant

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
SRC_REPORT = "core.report_exposure (DART 사업보고서 원문 표)"
FX_HIGH, FX_MID = 10.0, 3.0          # 환율 10% 상승 시 손익 영향 ÷ 영업이익 (%)
EXP_HIGH, EXP_MID = 60.0, 30.0       # 수출 비중 (%)


def _report_facts(f: Facts, report: list[dict] | None, fundamentals: dict | None) -> dict:
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
    return got


def assess(f: Facts, sector: str, fundamentals: dict | None, as_of: str, focus: list[str] | None = None,
           report: list[dict] | None = None) -> list[dict]:
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
    rep = _report_facts(f, report, fundamentals)

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
            reasons.append(f"주가와 뚜렷한 동조 {{{k}}}")
            keys.append(k)
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
                     "focus": bool(focus and any(x in var for x in focus)), "company": company})
    if not rep:
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
    k_net, k_exp = _key_prefix(f, "달러 화폐성 순자산"), _key_prefix(f, "수출 매출 비중")
    k_debt = _key_prefix(f, "부채비율(")
    out = []
    for item, why in PREMISES:
        status, detail, keys = "미확인", "DB에 자료 없음", []
        if item.startswith("환헤지"):
            if hedge:
                status, detail = "일부 확인", "사업보고서에 외환 파생상품 사용 공시. 헤지 비율·만기는 미확인"
            else:
                detail = "사업보고서 원문에서 외환 파생상품 표를 찾지 못했거나 미수집"
        elif item.startswith("수출 대금"):
            detail = "결제 통화별 매출·매출채권 회수 기간 자료 없음"
        elif item.startswith("판가"):
            detail = "판매가 조정 조건(계약 구조·경쟁 강도) 자료 없음"
        elif item.startswith("달러 비용") and k_net:
            status, detail, keys = "일부 확인", "화폐성 자산·부채의 달러 순액만 공시값 있음. 비용의 통화 구성은 미확인", [k_net]
        elif item.startswith("수출 매출") and k_exp:
            status, detail, keys = "확인", "사업보고서 매출 실적 표의 내수·수출 구분", [k_exp]
        elif item.startswith("수출 매출"):
            detail = "사업보고서 원문에서 회사 전체 내수·수출 표를 찾지 못했거나 미수집 (업종 기본값 사용)"
        elif item.startswith("차입"):
            if sector in FINANCIAL:
                detail = "금융업: 예대 금리 구조·자산 부채 만기 차이 자료 없음"
            elif k_debt:
                status, detail, keys = "일부 확인", "부채비율만 확인. 변동금리 비중·만기 구조는 미확인", [k_debt]
        out.append({"item": item, "status": status, "detail": detail, "why": why, "keys": keys})
    return out


def premises_md(items: list[dict], render) -> str:
    out = ["| 전제 | 상태 | 내용 | 왜 필요한가 |", "| --- | --- | --- | --- |"]
    for p in items:
        keys = " ".join("{" + k + "}" for k in p["keys"])
        out.append(f"| {p['item']} | {p['status']} | {render(p['detail'] + (' ' + keys if keys else ''))} | {p['why']} |")
    return "\n".join(out)


def table_md(rows: list[dict], render) -> str:
    out = ["| 거시 변수 | 노출 등급 | 근거 | 전달 경로 |", "| --- | --- | --- | --- |"]
    for r in rows:
        star = " (관심)" if r["focus"] else ""
        out.append(f"| {r['var']}{star} | {r['level']} | {render(', '.join(r['reasons']))} | {r['path']} |")
    return "\n".join(out)
