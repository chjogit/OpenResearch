"""거시 지표의 '당시 알 수 있었는가' 검사 (P01 기준 문서 7.2·7.3·9.3, 기능 P01-F02).

core.macro_obs 의 obs_date 는 관측 대상 기간(월별 자료는 그 달 1일)이지 공표일이 아닙니다. 예를 들어 9월 CPI 는
obs_date 가 9월 1일이지만 실제 공표는 10월입니다. 기준일 9월 15일 분석에 9월 CPI 를 쓰면 미래 정보 누설입니다.

수집기가 공표 시각을 저장하지 않으므로, 계열마다 '기간 끝 + 공표 지연 일수' 의 보수적 규칙을 미리 고정해
기준일에 아직 공표되지 않았을 관측을 뺍니다 (문서 7.3: 공표일만 아는 경우 보수 규칙을 사전 고정).

한계 (문서 9.3 '빈티지 증거 없음'):
- 공표 후 수정된 값(빈티지)을 저장하지 않아, 과거 기준일 분석에도 오늘 기준 최신 수정값이 쓰입니다.
  그래서 이 에이전트의 거시 관측은 'D1 사후 탐색' 등급이며, 과거 시점 예측 성능(D2) 주장에 쓰지 않습니다.
- 지연 일수는 공식 공표 일정의 대략값입니다. 실제 공표가 더 늦은 달이 있을 수 있어 넉넉히 잡았습니다.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

POLICY_VERSION = "p01-avail-v1"

# series_id: (주기 D/M/Q, 기간 끝 다음 이용 가능까지 일수, 근거)
RULES: dict[str, tuple[str, int, str]] = {
    # 일별: 한국은행 ECOS 는 당일 오후 게시, FRED 는 보통 다음 영업일 반영
    "ECOS_USDKRW": ("D", 0, "ECOS 일별 당일 게시"),
    "ECOS_KTB3Y": ("D", 0, "ECOS 일별 당일 게시"),
    "ECOS_KTB10Y": ("D", 0, "ECOS 일별 당일 게시"),
    "DGS10": ("D", 1, "FRED 다음 영업일"),
    "DEXJPUS": ("D", 7, "FRED H.10 주간 공표(월요일)"),
    "DEXCHUS": ("D", 7, "FRED H.10 주간 공표(월요일)"),
    "DEXUSEU": ("D", 7, "FRED H.10 주간 공표(월요일)"),
    "DEXTAUS": ("D", 7, "FRED H.10 주간 공표(월요일)"),
    "DCOILWTICO": ("D", 7, "EIA 현물가격 주간 갱신"),
    "DCOILBRENTEU": ("D", 7, "EIA 현물가격 주간 갱신"),
    # 월별: 그 달 마지막 날 + 지연
    "ECOS_BASE_RATE": ("M", 1, "월말 값"),
    "FEDFUNDS": ("M", 3, "다음 달 첫 영업일"),
    "ECOS_CPI": ("M", 5, "통계청 소비자물가 다음 달 초 공표"),
    "CPIAUCSL": ("M", 16, "BLS CPI 다음 달 중순 공표"),
    "IPG3344S": ("M", 18, "연준 산업생산 다음 달 중순"),
    "PCU33443344": ("M", 16, "BLS 생산자물가 다음 달 중순"),
    "KCS_EXP_854232_USD": ("M", 16, "관세청 확정치 다음 달 15일"),
    "KCS_EXP_854231_USD": ("M", 16, "관세청 확정치 다음 달 15일"),
    "KCS_IMP_854232_USD": ("M", 16, "관세청 확정치 다음 달 15일"),
    "KCS_IMP_854231_USD": ("M", 16, "관세청 확정치 다음 달 15일"),
    "PCOPPUSDM": ("M", 15, "IMF 1차산품 가격 다음 달 초~중순"),
    "PIORECRUSDM": ("M", 15, "IMF 1차산품 가격 다음 달 초~중순"),
    "PNGASJPUSDM": ("M", 15, "IMF 1차산품 가격 다음 달 초~중순"),
    "ECOS_CHN_EXPORT": ("M", 20, "중국 해관 다음 달 중순"),
    # 분기별
    "QKRN628BIS": ("Q", 100, "BIS 주거용 부동산 가격 분기 후 약 3개월"),
}
DEFAULT_RULE = ("M", 31, "규칙 없음: 한 달 지연으로 가정")


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def period_end(obs: date, freq: str) -> date:
    if freq == "D":
        return obs
    if freq == "Q":
        m = ((obs.month - 1) // 3) * 3 + 3
        return date(obs.year, m, calendar.monthrange(obs.year, m)[1])
    return date(obs.year, obs.month, calendar.monthrange(obs.year, obs.month)[1])


def available_on(series_id: str, obs_date) -> date:
    """이 관측이 공개됐다고 볼 수 있는 가장 이른 날 (보수 규칙)."""
    freq, lag, _ = RULES.get(series_id, DEFAULT_RULE)
    return period_end(_d(obs_date), freq) + timedelta(days=lag)


def filter_points(series_id: str, pts: list[tuple[str, float]], as_of: str) -> tuple[list, list]:
    """(기준일에 이용 가능한 관측, 뺀 관측). pts 는 날짜순 [(YYYY-MM-DD, 값)]."""
    cut = _d(as_of)
    keep, drop = [], []
    for p in pts:
        (keep if available_on(series_id, p[0]) <= cut else drop).append(p)
    return keep, drop


def apply(series: dict[str, list], as_of: str, f=None) -> tuple[dict[str, list], dict]:
    """계열 전부에 규칙을 적용합니다. f(장부)를 주면 뺀 관측을 메모로 남깁니다.

    돌려주는 report: {"policy", "dropped": {series_id: [뺀 obs_date…]}, "vintage": "missing"}"""
    out, dropped = {}, {}
    for sid, pts in series.items():
        keep, drop = filter_points(sid, pts, as_of)
        out[sid] = keep
        if drop:
            dropped[sid] = [d for d, _ in drop]
    if f is not None and dropped:
        names = ", ".join(f"{sid} {v[-1][:7]}" for sid, v in sorted(dropped.items()))
        f.note(f"공표 시점 규칙({POLICY_VERSION}): 기준일에 아직 공표 전이었을 관측을 뺌 → {names}")
    return out, {"policy": POLICY_VERSION, "dropped": dropped, "vintage": "missing",
                 "grade": "D1 사후 탐색 (수정 이력 미보관, 공표일은 보수 규칙)"}
