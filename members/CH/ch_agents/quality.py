"""데이터 품질 플래그 (기초기획서 R2 4.1 3단계 '품질 플래그 참고', 5장 리스크 '데이터 품질 대시보드·플래그 연동').

kic-agent-data 가 기록하는 quality.api_status(원천 API별 마지막 성공·연속 실패)를 읽어,
이 관점이 쓰는 원천에 문제가 있으면 출력에 '데이터 품질 주의'를 붙입니다. 숫자 판단에는 쓰지 않습니다.
"""
from __future__ import annotations

from datetime import datetime, timezone

SQL = ("SELECT api_name, last_success, last_error, last_error_msg, consecutive_failures, quota_hit "
       "FROM quality.api_status")

# 관점별로 쓰는 원천 API (quality.api_status.api_name)
SOURCES = {
    1: {"ecos·fred": "거시 지표(ECOS·FRED)", "yfinance": "지수(코스피·SOX)", "fsc": "국내 시세",
        "data.go.kr": "관세청 수출"},
    3: {"naver_finance": "투자자별 순매수", "naver": "뉴스·블로그·카페", "naver_datalab": "검색 관심도",
        "fsc": "국내 시세·대차잔고", "youtube": "유튜브 댓글", "yfinance": "VIX·코스피"},
}
STALE_HOURS = 48
MAX_FAILURES = 3


def _ts(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def check(agent_id: int, rows: list[dict] | None, now: datetime | None = None) -> list[dict]:
    """주의가 필요한 원천만 돌려줍니다: [{api, name, reason}]. 기록이 없는 원천은 '기록 없음'."""
    if rows is None:
        return []
    now = now or datetime.now(timezone.utc)
    by = {r.get("api_name"): r for r in rows}
    out = []
    for api, name in SOURCES.get(agent_id, {}).items():
        r = by.get(api)
        if r is None:
            out.append({"api": api, "name": name, "reason": "수집 품질 기록 없음 (아직 실행 전이거나 기록 대상 아님)"})
            continue
        last = _ts(r.get("last_success"))
        fails = int(r.get("consecutive_failures") or 0)
        if r.get("quota_hit"):
            out.append({"api": api, "name": name, "reason": "호출 한도 도달"})
        elif fails >= MAX_FAILURES:
            out.append({"api": api, "name": name, "reason": f"연속 실패 {fails}회"})
        elif last is None or (now - last).total_seconds() > STALE_HOURS * 3600:
            out.append({"api": api, "name": name, "reason": f"마지막 성공이 {STALE_HOURS}시간 넘게 지남"})
    return out
