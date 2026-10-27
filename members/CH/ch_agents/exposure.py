"""A1 기업 노출도: 규칙 기반 노출 지표 (기초기획서 R2 3.2, 리스크 대응 '규칙 기반 노출 지표 우선, LLM은 해석만').

거시 변수 4개(환율·금리·원자재·물가, 수출·경기)마다 노출 등급(높음/중간/낮음)을 코드가 정합니다.
LLM은 이 등급을 바꾸지 못하고, 판정 문장에 붙은 근거 키만 인용해 해석합니다.

등급은 세 가지 근거를 정해진 순서로 합칩니다.
1. 업종 기본값: KRX 업종별 거시 전달 경로(아래 SECTOR_PRIOR). 업종 공통의 출발점일 뿐 회사 고유 값이 아닙니다.
2. 통계 근거: 주가와 그 변수의 250일 상관이 유의하고 |상관| >= 0.3 이면 한 단계 올립니다
   (동조성은 통계적 관계이지 노출이 아니므로 '내리는' 근거로는 쓰지 않습니다).
3. 재무 구조: 금리 변수만. 최근 사업연도 부채비율 200% 이상이면 한 단계 올리고, 50% 이하면 한 단계 내립니다.
   금융업은 부채비율의 의미가 달라 적용하지 않습니다.

DB에 없는 근거(수출 비중·외화 매출·외화 부채·헤지 비율)는 '미확인'으로 남기고, 등급에 쓰지 않습니다.
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
# 변수별 통계 근거로 볼 동조성 항목 (macro.py 의 '주가-<이름> 상관(250일)')
STAT_DRIVERS = {
    "환율": ("원/달러",),
    "금리": ("미국 10년 국채금리", "국고채 3년 금리"),
    "원자재·물가": ("WTI 유가",),
    "수출·경기": ("필라델피아 반도체지수",),
}
FINANCIAL = {"은행", "증권", "보험", "기타금융"}
STRONG_CORR = 0.3
HIGH_DEBT, LOW_DEBT = 200.0, 50.0
UNKNOWN = "수출 비중·외화 매출·외화 부채·헤지 비율 (DART 사업보고서 본문 미수집)"


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


def assess(f: Facts, sector: str, fundamentals: dict | None, as_of: str, focus: list[str] | None = None) -> list[dict]:
    """노출 등급을 정해 판정 문장을 장부에 올리고, 표에 쓸 행 목록을 돌려줍니다."""
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

    rows = []
    for i, var in enumerate(VARIABLES):
        level = prior[i]
        reasons = [f"업종({sector}) 기본 {LEVELS[prior[i]]}" if sector in SECTOR_PRIOR else "업종 미분류: 기본 중간"]
        keys: list[str] = []
        k, r, n = _corr_evidence(f, STAT_DRIVERS[var])
        if k and r is not None and n and significant(r, n) and abs(r) >= STRONG_CORR:
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
                     "focus": bool(focus and any(x in var for x in focus))})
    f.gap("기업 고유 노출", UNKNOWN)
    f.note("노출 등급은 규칙(업종 기본값 → 통계 근거 → 재무 구조)으로 정한 값이며, 회사의 실제 노출 비율이 아님")
    if focus:
        rows.sort(key=lambda r: not r["focus"])
    return rows


def table_md(rows: list[dict], render) -> str:
    out = ["| 거시 변수 | 노출 등급 | 근거 | 전달 경로 |", "| --- | --- | --- | --- |"]
    for r in rows:
        star = " (관심)" if r["focus"] else ""
        out.append(f"| {r['var']}{star} | {r['level']} | {render(', '.join(r['reasons']))} | {r['path']} |")
    return "\n".join(out)
