"""대표 지수·배당 ETF (kic-agent-data core.etf_price_daily, 10-28 확장).

쓰는 곳
- 에이전트 1: 시장 기준선(코스피200·미국 S&P500·나스닥100·국내 고배당의 1·3·12개월 수익률). P01 기준(기업 실적·거시 노출)
  밖의 가격 정보라 '참고' 등급으로 장부에 올립니다.
- 에이전트 3: ETF 설정·환매 추정 자금 흐름(순자산 변화 − 가격 효과)과 괴리율. 시장 전반 위험 선호의 근거입니다.
- 노트북 ETF 셀: overview() 표.

자금 흐름 추정: flow_t = 순자산_t − 순자산_{t−1} × NAV_t / NAV_{t−1}. 분배금 지급일에는 순자산이 줄어 유출처럼 보이고,
NAV 가 없으면 종가를 씁니다. 실제 설정·환매 좌수가 아닌 추정치(대용치)입니다.
"""
from __future__ import annotations

from .facts import Facts, pct_change, shift_months, value_on_or_before

SRC = "core.etf_price_daily"
# 분류 → (대표 ETF, 이름). 국내 상장 ETF 를 대표로 둬 NAV·순자산이 있는 같은 기준으로 비교합니다.
CATEGORIES = {
    "kospi200": ("069500", "코스피200 (KODEX 200)"),
    "sp500": ("360750", "미국 S&P500 (TIGER 미국S&P500)"),
    "nasdaq100": ("133690", "나스닥100 (TIGER 미국나스닥100)"),
    "kr_high_dividend": ("161510", "국내 고배당 (PLUS 고배당주)"),
}
REP_TICKERS = [t for t, _ in CATEGORIES.values()]

SQL = """
SELECT json_object_agg(ticker, obs) AS etf FROM (
    SELECT ticker, json_agg(json_build_object('d', trade_date, 'c', close, 'n', nav, 'a', net_assets, 'nm', name)
                            ORDER BY trade_date) AS obs
    FROM core.etf_price_daily
    WHERE ticker = ANY(%(etf)s)
      AND trade_date <= %(as_of)s::date AND trade_date > %(as_of)s::date - INTERVAL '400 days'
    GROUP BY ticker) x
"""
ALL_SQL = """
SELECT e.ticker, e.trade_date, e.name, e.close, e.nav, e.net_assets, e.base_index, e.source,
       i.category, i.market, i.name_check
FROM core.etf_price_daily e LEFT JOIN core.etf_info i USING (ticker)
WHERE e.trade_date <= %(as_of)s::date AND e.trade_date > %(as_of)s::date - INTERVAL '400 days'
ORDER BY e.ticker, e.trade_date
"""
ALL_SQL_OLD = """
SELECT ticker, trade_date, name, close, nav, net_assets, base_index, source
FROM core.etf_price_daily
WHERE trade_date <= %(as_of)s::date AND trade_date > %(as_of)s::date - INTERVAL '400 days'
ORDER BY ticker, trade_date
"""


def _f(x):
    return None if x is None else float(x)


def series(obs: list[dict] | None) -> list[dict]:
    return [{"d": str(o["d"])[:10], "c": _f(o.get("c")), "n": _f(o.get("n")), "a": _f(o.get("a")),
             "nm": o.get("nm")} for o in obs or [] if o.get("c") is not None]


def returns(rows: list[dict]) -> dict:
    """1·3·12개월 가격 수익률(%). 분배금 미포함(가격 기준)."""
    if not rows:
        return {}
    pts = [(r["d"], r["c"]) for r in rows]
    d, v = pts[-1]
    out = {"last": d, "close": v}
    for m in (1, 3, 12):
        old = value_on_or_before(pts, shift_months(d, m))
        out[f"r{m}m"] = pct_change(v, old and old[1]) if old and old[0] < d else None
    return out


def flows(rows: list[dict], days: int) -> float | None:
    """최근 days 거래일 추정 자금 흐름 합(원). 순자산이 없으면 None."""
    tail = rows[-(days + 1):]
    if len(tail) < days + 1:
        return None
    total = 0.0
    for a, b in zip(tail, tail[1:]):
        if a["a"] is None or b["a"] is None:
            return None
        pa, pb = (a["n"], b["n"]) if a["n"] and b["n"] else (a["c"], b["c"])
        if not pa:
            return None
        total += b["a"] - a["a"] * pb / pa
    return total


def premium(row: dict) -> float | None:
    """괴리율(%) = 종가 / NAV − 1."""
    return (row["c"] / row["n"] - 1) * 100 if row.get("n") else None


def add_market_facts(f: Facts, bundle: dict | None, group: str = "시장 기준선(ETF·참고)") -> list[str]:
    """에이전트 1: 분류별 대표 ETF 의 1·3·12개월 수익률. P01 핵심이 아닌 참고 정보."""
    data = bundle or {}
    keys = []
    for cat, (tic, name) in CATEGORIES.items():
        rows = series(data.get(tic))
        if not rows:
            f.gap(f"{name} 시세", "ETF 시세 없음 (kic-agent-data ETF 확장 수집 전)")
            continue
        r = returns(rows)
        for m in (3, 12):
            keys.append(f.add(f"{name} {m}개월 수익률", r.get(f"r{m}m"), "%chg", r["last"], f"{SRC} {tic}",
                              kind="calc", group=group, note="가격 기준(분배금 미포함), 기업 실적과 무관한 시장 참고치"))
    return [k for k in keys if k]


def add_flow_facts(f: Facts, bundle: dict | None, days: tuple[int, ...] = (5, 20),
                   group: str = "시장 자금 흐름(ETF)") -> dict:
    """에이전트 3: 분류별 대표 ETF 의 설정·환매 추정 자금 흐름과 괴리율. 돌려주는 값: {분류: {days: 키}}."""
    data = bundle or {}
    got: dict = {}
    for cat, (tic, name) in CATEGORIES.items():
        rows = series(data.get(tic))
        if not rows:
            f.gap(f"{name} 자금 흐름", "ETF 시세 없음 (kic-agent-data ETF 확장 수집 전)")
            continue
        got[cat] = {}
        for n in days:
            k = f.add(f"{name} 최근 {n}거래일 추정 자금 유출입", flows(rows, n), "KRW±", rows[-1]["d"], f"{SRC} {tic}",
                      kind="proxy", group=group,
                      note="순자산 변화 − NAV 변화 효과. 설정·환매 좌수가 아닌 추정치, 분배금 지급일은 유출처럼 보임")
            got[cat][n] = k
        p = premium(rows[-1])
        if p is not None:
            f.add(f"{name} 괴리율", p, "%chg", rows[-1]["d"], f"{SRC} {tic}", kind="calc", group=group,
                  note="종가 / NAV − 1. 해외지수 ETF 는 시차로 커질 수 있음")
    # 위험 선호 판정: 해외 성장(나스닥100) vs 국내 고배당 20일 흐름 방향
    a, b = (got.get("nasdaq100") or {}).get(20), (got.get("kr_high_dividend") or {}).get(20)
    if a and b:
        va, vb = f.items[a]["value"], f.items[b]["value"]
        if va > 0 > vb:
            f.flag(f"ETF 자금: 나스닥100 유입·국내 고배당 유출 (위험 선호 쪽, {{{a}}}, {{{b}}})")
        elif vb > 0 > va:
            f.flag(f"ETF 자금: 국내 고배당 유입·나스닥100 유출 (방어 선호 쪽, {{{b}}}, {{{a}}})")
    return got


def overview(rows: list[dict]) -> list[dict]:
    """노트북용: ETF 마다 최신 종가·수익률·괴리율·20일 추정 자금 흐름. rows 는 ALL_SQL 결과."""
    by: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for r in rows:
        by.setdefault(r["ticker"], []).append({"d": str(r["trade_date"])[:10], "c": _f(r["close"]), "n": _f(r["nav"]),
                                               "a": _f(r["net_assets"]), "nm": r.get("name")})
        meta[r["ticker"]] = r
    out = []
    for tic, s in by.items():
        ret = returns(s)
        m = meta[tic]
        fl = flows(s, 20)
        out.append({"ticker": tic, "name": m.get("name"), "category": m.get("category"), "market": m.get("market") or "KR",
                    "last": ret.get("last"), "close": ret.get("close"), "r1m": ret.get("r1m"), "r3m": ret.get("r3m"),
                    "r12m": ret.get("r12m"), "premium_pct": premium(s[-1]),
                    "flow20_억원": None if fl is None else round(fl / 1e8, 1), "rows": len(s),
                    "name_check": m.get("name_check")})
    return sorted(out, key=lambda x: (str(x["category"]), x["ticker"]))


def fetch_overview(as_of: str) -> list[dict]:
    from . import db

    try:
        rows = db.q(ALL_SQL, {"as_of": as_of})
    except Exception:  # noqa: BLE001  core.etf_info(kic-agent-data 022) 적용 전
        rows = db.q(ALL_SQL_OLD, {"as_of": as_of})
    return overview(rows)
