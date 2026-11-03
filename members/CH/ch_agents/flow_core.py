"""수급 장부의 공용 계산: 주체별 누적 순매수·금액·강도와 연속 일수.

옛 에이전트 3(`agent3_sentiment_flow`)과 에이전트 4 N08(`flow_nodes`)이 같은 식을 두 벌 갖고 있던 것을 한곳으로 모음 (#25).
라벨·단위·출처·값은 이전과 같고, 호출하는 쪽이 기간·그룹만 정한다.
"""
from __future__ import annotations

from .facts import Facts, streak

SRC_FLOW = "core.investor_flow_daily (네이버 투자자별 매매)"
WHO = (("외국인", "fq"), ("기관", "iq"), ("개인", "pq"))


def add_net_buy(f: Facts, rows: list[dict], who: str, col: str, windows, amount_windows, group: str) -> dict:
    """rows(최신순)에서 who 의 n일 순매수 수량, amount_windows 에 든 n 은 순매수 금액(근사)·거래대금 대비 강도도 장부에 올린다.
    반환: {n: 수량 키, ("금액", n): 금액 키}"""
    keys: dict = {}
    d0 = rows[0]["d"]
    for n in windows:
        if len(rows) < n:
            continue
        win = rows[:n]
        keys[n] = f.add(f"{who} {n}일 순매수 수량", sum(r[col] or 0 for r in win), "주", d0, SRC_FLOW, kind="calc", group=group)
        if n in amount_windows and all(r.get("close") for r in win):
            amt = sum((r[col] or 0) * r["close"] for r in win)
            keys[("금액", n)] = f.add(f"{who} {n}일 순매수 금액(근사)", amt, "KRW±", d0, SRC_FLOW + " × 종가", kind="proxy",
                                    group=group, note="일별 순매수 수량 × 종가")
            tv = sum(r["tv"] or 0 for r in win)
            if tv and all(r.get("tv") for r in win):
                f.add(f"{who} {n}일 순매수 강도(거래대금 대비)", amt / tv * 100, "%", d0, SRC_FLOW + " × core.price_daily",
                      kind="proxy", group=group, note="순매수 금액 근사 ÷ 같은 기간 거래대금. 종목 간 비교용")
    return keys


def add_streak(f: Facts, rows: list[dict], who: str, col: str, group: str) -> tuple[int, str | None]:
    """연속 순매수(+)·순매도(-) 일수를 장부에 올린다. 반환: (부호 있는 일수, 키). 0 이면 올리지 않음."""
    s = streak([r[col] for r in rows])
    if not s:
        return 0, None
    k = f.add(f"{who} 연속 순{'매수' if s > 0 else '매도'} 일수", abs(s), "일", rows[0]["d"], SRC_FLOW, kind="calc", group=group)
    return s, k
