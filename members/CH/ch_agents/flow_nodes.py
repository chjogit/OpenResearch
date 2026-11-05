"""에이전트 4 수급: N07 유동성·거래대금(기본) · N08 수급 전환·가격 불일치(확장) (티켓 #22, specs/agent-split.md '노드 상세').

- 숫자는 모두 DB 에서 읽은 값을 코드가 계산한 것(Facts 장부 키)이며 LLM 이 만들지 않습니다. 각 진술의 evidence_links 는 그 장부 키입니다.
- N07: 거래대금 평균·회전율·유동성 대용(Amihud)·급증/급감·유동성 충격·단기 거래대금 범위. 호가 잔량은 수집하지 않아 '미확보'.
- N08: 외국인·기관·개인 누적 순매수·연속 일수(에이전트 3 와 같은 라벨·같은 식), 손바꿈 조건, 가격-수급 불일치, 전환 확률(조건 충족 시).
  세부 주체(금융투자·투신·연기금)는 '미확보' — 기관 합계로 대체하지 않습니다.
- 투자자별 자료가 없거나 시세보다 늦으면 거래량으로 대신 해석하지 않고 무자료·시차로 표시합니다. 수급만으로 매수 의도·정보 보유를 추정하지 않습니다.
- 가격 차트·순수 거래량 분석(N09·N10 영역)은 하지 않습니다.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev

from .agent3_sentiment_flow import TV_JUMP, Z_ALERT, _intensity_z
from .flow_core import SRC_FLOW, WHO, add_net_buy, add_streak
from .asof import cut_future, require_as_of
from .thresholds import REFERENCE_RATIO
from .facts import MAX_DAILY_MOVE, Facts, series_points, streak
from .nodes import Conflict, ConflictView, Finding, NodeResult, NodeTask, register

SRC_PRICE = "core.price_daily"
SRC_SHARES = "core.company.shares_outstanding"
MIN_ROWS = 20            # 이동평균을 낼 최소 거래일 수 (미만이면 해당 입력 미확보)
RUN_MIN = 3              # 전환 확률: 같은 방향 연속 순매수·순매도가 이 일수 이상일 때를 '상태'로 봄
HORIZON = 5              # 전환 확률: 이후 몇 거래일의 순매수 합으로 방향을 보는지
MIN_EVENTS = 30          # 전환 확률 최소 표본(상태 발생 횟수)
MIN_TRAIN = 15           # 걷기 검증(walk-forward)에서 확률을 낼 때 필요한 직전 표본
MIN_OOS = 15             # 걷기 검증 표본 수
UNDISCLOSED_SUBJECTS = ("금융투자", "투신", "연기금")   # 세부 주체: 현재 수집 안 함

FLOW_SQL = """
SELECT json_build_object(
    'flows', (SELECT json_agg(x ORDER BY x.d DESC) FROM (
        SELECT f.trade_date AS d, f.foreign_net_qty AS fq, f.institution_net_qty AS iq, f.individual_net_qty AS pq,
               f.foreign_hold_pct AS hold, p.close, p.trade_value AS tv
        FROM core.investor_flow_daily f
        LEFT JOIN core.price_daily p ON p.company_id = f.company_id AND p.trade_date = f.trade_date
        WHERE f.company_id = %(cid)s AND f.trade_date <= %(as_of)s::date
        ORDER BY f.trade_date DESC LIMIT 500) x),
    'prices', (SELECT json_agg(x ORDER BY x.d DESC) FROM (
        SELECT trade_date AS d, close, volume, trade_value AS tv
        FROM core.price_daily WHERE company_id = %(cid)s AND trade_date <= %(as_of)s::date
        ORDER BY trade_date DESC LIMIT 500) x),
    'shares', (SELECT shares_outstanding FROM core.company WHERE company_id = %(cid)s)
) AS bundle
"""


def fetch_inputs(co: dict, as_of: str) -> dict:
    """DB 에서 수급·시세·상장주식수를 읽습니다 (읽기 전용). 기준일 다음 날 이후 행은 도구 계층에서 제거(E3)."""
    from . import db

    as_of = require_as_of(as_of)
    b = db.bundle(FLOW_SQL, {"cid": co["company_id"], "as_of": as_of})
    return clean_inputs(b, as_of)


def clean_inputs(b: dict, as_of: str) -> dict:
    as_of = require_as_of(as_of)
    out = {"shares": b.get("shares")}
    for k in ("flows", "prices"):
        rows = [dict(r, d=str(r["d"])[:10]) for r in b.get(k) or []]
        out[k], _ = cut_future(sorted(rows, key=lambda r: r["d"], reverse=True), as_of, ("d",))
    return out


def available_inputs(inp: dict) -> set[str]:
    """노드 틀(run_agent_nodes)에 넘길 '확보된 입력' 이름. 기준에 못 미치면 빠져 DATA_INSUFFICIENT/스킵이 됩니다."""
    px = [r for r in inp.get("prices") or [] if r.get("close")]
    tv = [r for r in inp.get("prices") or [] if r.get("tv")]
    have = set()
    if len(px) >= MIN_ROWS:
        have.add("price")
    if len(tv) >= MIN_ROWS:
        have.add("trading_value")
    if inp.get("flows"):
        have.add("investor_flow")
    return have


# ---------------------------------------------------------------- 공통

def _ledger(f: Facts) -> dict:
    return {k: {x: v[x] for x in ("label", "value", "unit", "text", "as_of", "source", "kind")} for k, v in f.items.items()}


def _find(kind: str, text: str, tag: str, keys) -> Finding:
    return Finding(kind=kind, text=text, tag=tag, evidence_links=[k for k in keys if k])


# ---------------------------------------------------------------- N07 유동성·거래대금

def n07(inp: dict, as_of: str) -> NodeResult:
    as_of = require_as_of(as_of)
    f = Facts("L")
    rows = [r for r in inp.get("prices") or [] if r.get("tv")]          # 최신순
    finds: list[Finding] = []
    d0 = rows[0]["d"] if rows else None
    for n in (5, 20, 60):
        if len(rows) >= n:
            k = f.add(f"거래대금 {n}일 평균", mean(r["tv"] for r in rows[:n]), "KRW", d0, SRC_PRICE, kind="calc", group="거래대금")
            finds.append(_find("number", f"최근 {n}거래일 평균 거래대금 {f.items[k]['text']}", "Computation", [k]))
        else:
            f.gap(f"거래대금 {n}일 평균", f"거래대금이 있는 거래일 {n}일 미만")
    ratio = None
    if len(rows) >= 65:
        m5, b60 = mean(r["tv"] for r in rows[:5]), mean(r["tv"] for r in rows[5:65])
        kr = f.add("거래대금 배율(최근 5일 ÷ 직전 60일)", m5 / b60 if b60 else None, "배", d0, SRC_PRICE, kind="calc",
                   group="거래대금", note=f"{REFERENCE_RATIO:g}보다 크면 평소보다 거래대금이 많음")
        ratio = f.items[kr]["value"] if kr else None
        if kr and ratio >= TV_JUMP:
            finds.append(_find("conclusion", f"거래대금 급증: 최근 5일 평균이 직전 60일 평균의 {f.items[kr]['text']}", "Computation", [kr]))
        elif kr and ratio <= 1 / TV_JUMP:
            finds.append(_find("conclusion", f"거래대금 급감: 최근 5일 평균이 직전 60일 평균의 {f.items[kr]['text']}", "Computation", [kr]))
    else:
        f.gap("거래대금 배율", "거래대금이 있는 거래일 65일 미만")

    # 회전율 = 거래량 ÷ 상장주식수
    shares = inp.get("shares")
    vol = [r for r in inp.get("prices") or [] if r.get("volume") is not None]
    if shares and vol:
        for n in (1, 5, 20):
            if len(vol) >= n:
                k = f.add(f"회전율 {n}일 평균", mean(r["volume"] for r in vol[:n]) / float(shares) * 100, "%", vol[0]["d"],
                          f"{SRC_PRICE} ÷ {SRC_SHARES}", kind="calc", group="회전율", note="일 거래량 ÷ 상장주식수")
                finds.append(_find("number", f"회전율({n}일 평균) {f.items[k]['text']}", "Computation", [k]))
    else:
        f.gap("회전율", "상장주식수 또는 거래량 없음")

    # 유동성 대용: Amihud 비유동성 = 평균(|일 수익률 %| ÷ 거래대금 억원)
    px = sorted(((r["d"], float(r["close"]), float(r["tv"])) for r in inp.get("prices") or [] if r.get("close") and r.get("tv")))
    illiq: list[tuple[str, float]] = []                                   # 오래된 순
    for (_, p0, _), (d1, p1, t1) in zip(px, px[1:]):
        if p0 and t1 > 0:
            ret = (p1 / p0 - 1)
            if abs(ret) <= MAX_DAILY_MOVE:                                # 가격제한폭 밖 변화는 액면분할 등 의심 → 제외
                illiq.append((d1, abs(ret) * 100 / (t1 / 1e12)))
    am = [v for _, v in illiq][::-1]                                       # 최신순
    shock = None
    if len(am) >= 20:
        ka = f.add("Amihud 비유동성 20일 평균(%/거래대금 조원)", mean(am[:20]), "idx", illiq[-1][0], SRC_PRICE, kind="calc",
                   group="유동성", note="|일 수익률 %| ÷ 거래대금(조원)의 평균. 클수록 같은 거래대금에 가격이 더 움직임(유동성 낮음)")
        finds.append(_find("number", f"Amihud 비유동성(20일 평균) {f.items[ka]['text']}", "Computation", [ka]))
        if len(am) >= 65:
            base = am[5:65]
            sd = pstdev(base) * (len(base) / (len(base) - 1)) ** 0.5
            m5 = mean(am[:5])
            if sd:
                z = (m5 - mean(base)) / (sd / 5 ** 0.5)
                k5 = f.add("Amihud 비유동성 최근 5일 평균", m5, "idx", illiq[-1][0], SRC_PRICE, kind="calc", group="유동성")
                kz = f.add("Amihud 최근 5일의 직전 60일 대비 표준점수", z, "coef", illiq[-1][0], SRC_PRICE, kind="calc",
                           group="유동성", note=f"절댓값 {Z_ALERT:g} 이상이면 이례적")
                shock = z
                if kz and z >= Z_ALERT:
                    finds.append(_find("conclusion", f"유동성 충격: 비유동성이 직전 60일 대비 이례적으로 높음(표준점수 {f.items[kz]['text']})",
                                       "Computation", [k5, kz]))
    else:
        f.gap("Amihud 비유동성", "수익률·거래대금이 모두 있는 거래일 20일 미만")

    # 이상 지점: 최근 20거래일 중 직전 20일 평균 대비 거래대금이 급증·급감한 날
    points = []
    for i in range(min(20, max(0, len(rows) - 20))):
        base = mean(r["tv"] for r in rows[i + 1:i + 21])
        if base:
            x = rows[i]["tv"] / base
            if x >= TV_JUMP or x <= 1 / TV_JUMP:
                k = f.add(f"{rows[i]['d']} 거래대금 배율(직전 20일 평균 대비)", x, "배", rows[i]["d"], SRC_PRICE, kind="calc", group="이상 지점")
                points.append({"date": rows[i]["d"], "ratio": round(x, 3), "type": "급증" if x >= TV_JUMP else "급감", "key": k})
                finds.append(_find("conclusion", f"{rows[i]['d']} 거래대금 {'급증' if x >= TV_JUMP else '급감'} ({f.items[k]['text']})",
                                   "Computation", [k]))

    # 단기 유동성 범위: 최근 60거래일 일별 거래대금의 10~90 백분위 (경험적 범위, 모형 아님)
    rng = None
    if len(rows) >= 60:
        vals = sorted(r["tv"] for r in rows[:60])
        lo, hi = vals[int(0.1 * 59)], vals[int(math.ceil(0.9 * 59))]
        kl = f.add("최근 60일 일 거래대금 하단(10백분위)", lo, "KRW", d0, SRC_PRICE, kind="calc", group="유동성 범위")
        kh = f.add("최근 60일 일 거래대금 상단(90백분위)", hi, "KRW", d0, SRC_PRICE, kind="calc", group="유동성 범위")
        rng = {"low": lo, "high": hi, "keys": [kl, kh]}
        finds.append(_find("number", f"단기 일 거래대금 범위(경험적, 최근 60일 10~90 백분위): {f.items[kl]['text']} ~ {f.items[kh]['text']}. "
                                     f"과거 분포일 뿐 예측 모형은 검증되지 않음", "Prediction", [kl, kh]))

    limits = ["호가 잔량: 수집하지 않음 → 미확보 (호가 기반 유동성 지표는 계산하지 않음)"]
    missing = ["호가 잔량"]
    status = "SUCCESS"
    if f.gaps:
        status = "PARTIAL_SUCCESS"
        missing += [g["label"] for g in f.gaps]
    return NodeResult(
        status=status, node_id="N07", findings=finds,
        artifacts={"liquidity": {"tv_ratio": ratio, "amihud_shock_z": shock, "anomaly_points": points, "short_term_range": rng},
                   "ledger": _ledger(f), "data_limits": limits, "gaps": f.gaps},
        evidence_links=sorted(f.items), missing_items=missing,
        reason=None if status == "SUCCESS" else "일부 지표의 자료 부족: " + ", ".join(g["label"] for g in f.gaps))


# ---------------------------------------------------------------- N08 수급 전환·가격 불일치

def _chronological(rows: list[dict], col: str) -> list[float]:
    return [float(r[col] or 0) for r in reversed(rows)]


def switch_stats(q: list[float]) -> dict:
    """순매수 수량(오래된 순) q 의 '연속 RUN_MIN일 이상 같은 방향 → 이후 HORIZON일 합의 방향이 반대로 바뀌는지' 통계.
    확률은 직전까지 결과가 확정된 표본만으로 낸 경험적 빈도(걷기 검증), 비교 기준은 '아무 날이나 부호가 있는 날'의 무조건 빈도."""
    T = len(q)
    run, events, base = 0, [], []        # events/base: (t, y)
    for t in range(T):
        if not q[t]:
            run = 0
        elif t and q[t - 1] and (q[t] > 0) == (q[t - 1] > 0):
            run += 1
        else:
            run = 1
        if t + HORIZON >= T or not q[t]:
            continue
        fut = sum(q[t + 1:t + 1 + HORIZON])
        y = 1 if fut and (fut > 0) != (q[t] > 0) else 0
        base.append((t, y))
        if run >= RUN_MIN:
            events.append((t, y))
    out = {"n_events": len(events), "n_base": len(base), "oos": 0, "brier_cond": None, "brier_base": None}
    known = lambda lst, t: [y for (s, y) in lst if s + HORIZON <= t]          # noqa: E731  t 시점에 결과가 확정된 표본
    bc, bb = [], []
    for (t, y) in events:
        tr_c, tr_b = known(events, t), known(base, t)
        if len(tr_c) >= MIN_TRAIN and tr_b:
            bc.append((mean(tr_c) - y) ** 2)
            bb.append((mean(tr_b) - y) ** 2)
    if bc:
        out.update(oos=len(bc), brier_cond=mean(bc), brier_base=mean(bb))
    ev_y = [y for _, y in events]
    out["p_cond"] = mean(ev_y) if ev_y else None
    out["p_base"] = mean(y for _, y in base) if base else None
    return out


def _prediction(who: str, q: list[float], f: Facts, d0: str) -> tuple[Finding | None, str | None]:
    """(전환 확률 진술, 건너뛴 이유). 표본·걷기 검증 기준을 못 채우거나 현재 상태가 아니면 이유만 돌려줍니다."""
    cur = streak(q[::-1])
    st = switch_stats(q)
    if st["n_events"] < MIN_EVENTS:
        return None, f"{who} 전환 확률 표본 부족: 연속 {RUN_MIN}일 이상 상태 {st['n_events']}회 (최소 {MIN_EVENTS})"
    if st["oos"] < MIN_OOS:
        return None, f"{who} 걷기 검증 표본 부족: {st['oos']}회 (최소 {MIN_OOS})"
    if not st["brier_cond"] < st["brier_base"]:
        return None, (f"{who} 전환 확률 검증 미통과: 조건부 빈도의 Brier {st['brier_cond']:.3f} 가 "
                      f"무조건 빈도 {st['brier_base']:.3f} 보다 낫지 않음 (추가 설명력 없음)")
    if abs(cur) < RUN_MIN:
        return None, f"{who} 현재 연속 순매수·순매도가 {RUN_MIN}일 미만이라 적용 대상 아님"
    kp = f.add(f"{who} 반대 방향 전환 확률({HORIZON}거래일, 경험적)", st["p_cond"] * 100, "%", d0, SRC_FLOW, kind="forecast",
               group="전환", note=f"표본 {st['n_events']}회, 걷기 검증 {st['oos']}회")
    kb = f.add(f"{who} 전환 확률 걷기 검증 Brier(조건부)", st["brier_cond"], "coef", d0, SRC_FLOW, kind="calc", group="전환")
    kn = f.add(f"{who} 전환 확률 걷기 검증 Brier(무조건 기준)", st["brier_base"], "coef", d0, SRC_FLOW, kind="calc", group="전환")
    txt = (f"{who} 연속 {'순매수' if cur > 0 else '순매도'} {abs(cur)}일 상태에서 이후 {HORIZON}거래일 방향이 반대로 바뀐 경험적 빈도 "
           f"{f.items[kp]['text']} (표본 {st['n_events']}회, 걷기 검증 Brier {f.items[kb]['text']} < 기준 {f.items[kn]['text']}). "
           f"과거 빈도이며 의도·정보 보유를 뜻하지 않음")
    return _find("number", txt, "Prediction", [kp, kb, kn]), None


def n08(inp: dict, as_of: str) -> NodeResult:
    as_of = require_as_of(as_of)
    f = Facts("S")
    rows = [dict(r) for r in inp.get("flows") or []]                        # 최신순
    pending = []
    while rows and not (rows[0].get("close") and rows[0].get("tv")):         # 에이전트 3 와 같은 규칙: 시세 공개 전 행은 뺌
        pending.append(rows.pop(0)["d"])
    finds: list[Finding] = []
    conflicts: list[Conflict] = []
    arts: dict = {"pending_flow_dates": pending, "unavailable_subjects": list(UNDISCLOSED_SUBJECTS)}
    missing = [f"세부 주체({'·'.join(UNDISCLOSED_SUBJECTS)})"]
    if not rows:
        return NodeResult(status="DATA_INSUFFICIENT", node_id="N08", missing_items=["투자자별 매매"] + missing,
                          reason="투자자별 수급 자료 없음 (거래량으로 대체 해석하지 않음)", artifacts=arts)
    d0 = rows[0]["d"]
    px_last = (inp.get("prices") or [{}])[0].get("d")
    if px_last and d0 < px_last:                                             # 수급이 시세보다 늦음 → 시차 표시, 대체 해석 안 함
        arts["flow_lag"] = {"flow_last": d0, "price_last": px_last}
        missing.append(f"{px_last} 투자자별 수급 (수집이 시세보다 늦음, 마지막 {d0})")
        finds.append(_find("note", f"자료 시차: 투자자별 수급은 {d0}까지, 시세는 {px_last}까지. 그 뒤 거래일 수급은 미반영(거래량으로 대신 해석하지 않음)",
                           "Fact", []))
    table = {}
    for who, col in WHO:
        row = {}
        got = add_net_buy(f, rows, who, col, (5, 20, 60), (20,), "누적")      # 공용 계산(flow_core): 옛 에이전트 3 과 같은 코드
        for n in (5, 20, 60):
            if n in got:
                row[f"{n}일"] = got[n]
        if ("금액", 20) in got:
            row["금액"] = got[("금액", 20)]
        s, ks = add_streak(f, rows, who, col, "지속성")
        if s:
            row["연속"] = ks
        table[who] = row
        for k in row.values():
            if k:
                finds.append(_find("number", f"{f.items[k]['label']} {f.items[k]['text']}", "Computation", [k]))
    arts["cumulative_table"] = table

    # 손바꿈 조건 (정의는 artifacts 에 함께 남김): ① 외국인·기관 각각 최근 5일 합의 부호가 직전 20일 합과 반대
    # ② 개인 20일 합과 (외국인+기관) 20일 합의 부호가 반대 — 매매 방향의 사실이며 의도 추정이 아님
    arts["definitions"] = {
        "손바꿈": f"① 외국인·기관: 최근 5거래일 순매수 합의 부호가 그 앞 20거래일 합의 부호와 반대 ② 개인 20일 합과 외국인+기관 20일 합의 부호가 반대",
        "불일치": "외국인·기관의 20일 순매수 수량 부호와 20일 주가 수익률 부호가 반대",
        "전환 확률": f"연속 {RUN_MIN}일 이상 같은 방향 뒤 이후 {HORIZON}거래일 합의 방향이 반대인 경험적 빈도. 표본 {MIN_EVENTS}회 이상 + 걷기 검증(Brier)이 무조건 빈도보다 나을 때만",
    }
    handovers = []
    for who, col in WHO[:2]:
        if len(rows) >= 25:
            r5, p20 = sum(r[col] or 0 for r in rows[:5]), sum(r[col] or 0 for r in rows[5:25])
            if r5 and p20 and (r5 > 0) != (p20 > 0):
                k1 = f.add(f"{who} 최근 5일 순매수 수량", r5, "주", d0, SRC_FLOW, kind="calc", group="손바꿈")
                k2 = f.add(f"{who} 직전 20일 순매수 수량", p20, "주", rows[5]["d"], SRC_FLOW, kind="calc", group="손바꿈")
                handovers.append({"who": who, "from": "순매수" if p20 > 0 else "순매도", "to": "순매수" if r5 > 0 else "순매도", "keys": [k1, k2]})
                finds.append(_find("conclusion", f"{who} 순매매 방향 전환: 직전 20일 {f.items[k2]['text']} → 최근 5일 {f.items[k1]['text']} (매매 방향의 사실이며 의도를 뜻하지 않음)",
                                   "Computation", [k1, k2]))
    if len(rows) >= 20:
        pq, fi = sum(r["pq"] or 0 for r in rows[:20]), sum((r["fq"] or 0) + (r["iq"] or 0) for r in rows[:20])
        if pq and fi and (pq > 0) != (fi > 0):
            kp = f.add("개인 20일 순매수 수량(손바꿈 비교)", pq, "주", d0, SRC_FLOW, kind="calc", group="손바꿈")
            kf = f.add("외국인+기관 20일 순매수 수량(손바꿈 비교)", fi, "주", d0, SRC_FLOW, kind="calc", group="손바꿈")
            handovers.append({"who": "개인↔외국인+기관", "from": None, "to": None, "keys": [kp, kf]})
            finds.append(_find("conclusion", f"주체 간 매매 방향 반대: 개인 20일 {f.items[kp]['text']}, 외국인+기관 {f.items[kf]['text']}", "Computation", [kp, kf]))
    arts["handovers"] = handovers

    # 가격-수급 불일치 (가격은 시세표의 종가, 에이전트 3 와 같은 20일 수익률)
    px = series_points([{"d": r["d"], "v": r["close"]} for r in inp.get("prices") or [] if r.get("close")])
    divergences = []
    if len(px) > 20:
        rk = f.add("20일 주가 수익률", (px[-1][1] / px[-21][1] - 1) * 100, "%chg", px[-1][0], SRC_PRICE, kind="calc", group="가격")
        for who, col in WHO[:2]:
            kq = f.key_of(f"{who} 20일 순매수 수량")
            if kq and rk:
                fv, rv = f.items[kq]["value"], f.items[rk]["value"]
                if (fv > 0) != (rv > 0) and fv and rv:
                    divergences.append({"who": who, "flow_key": kq, "return_key": rk, "type": "하락 중 순매수" if fv > 0 else "상승 중 순매도"})
                    finds.append(_find("conclusion", f"가격-수급 불일치: 주가 {'하락' if rv < 0 else '상승'} 중 {who} 순{'매수' if fv > 0 else '매도'} "
                                                     f"(20일 수익률 {f.items[rk]['text']}, 순매수 {f.items[kq]['text']})", "Computation", [rk, kq]))
                    conflicts.append(Conflict(topic=f"{who} 수급과 주가 방향", views=[
                        ConflictView(text=f"{who} 20일 순{'매수' if fv > 0 else '매도'}", tag="Fact", evidence_links=[kq]),
                        ConflictView(text=f"20일 주가 {'하락' if rv < 0 else '상승'}", tag="Fact", evidence_links=[rk])]))
    else:
        f.gap("20일 주가 수익률", "종가가 있는 거래일 21일 미만")
    arts["divergences"] = divergences

    # 전환 확률 (검증 조건 충족 시에만)
    skipped = []
    for who, col in WHO[:2]:
        fnd, why = _prediction(who, _chronological(rows, col), f, d0)
        if fnd:
            finds.append(fnd)
        elif why:
            skipped.append(why)
    arts.update(ledger=_ledger(f), gaps=f.gaps)
    reason = "SWITCH_PROB_UNVALIDATED: " + "; ".join(skipped) if skipped and not any(x.tag == "Prediction" for x in finds) else None
    return NodeResult(status="PARTIAL_SUCCESS" if (reason or arts.get("flow_lag")) else "SUCCESS", node_id="N08", findings=finds,
                      conflicts=conflicts, artifacts=arts, evidence_links=sorted(f.items), missing_items=missing,
                      prediction_skipped_reason=reason, reason=reason)


# ---------------------------------------------------------------- 노드 틀 연결

def make_runners(loader):
    """loader(task) → 입력 dict. 같은 (종목, 기준일)이면 한 번만 읽습니다."""
    cache: dict = {}

    def get(task: NodeTask) -> dict:
        key = (task.target_ticker, task.as_of_date)
        if key not in cache:
            cache[key] = loader(task)
        return cache[key]

    return {"N07": lambda t: n07(get(t), t.as_of_date), "N08": lambda t: n08(get(t), t.as_of_date)}


def _db_loader(task: NodeTask) -> dict:
    from . import db

    return fetch_inputs(db.company(task.target_ticker), task.as_of_date)


for _nid, _fn in make_runners(_db_loader).items():   # 기본 등록: DB 에서 읽는 실행 함수 (테스트·재현은 run_flow_agent(inputs=...) 로 입력을 직접 넘김)
    register(_nid)(_fn)


def run_flow_agent(ticker: str, as_of_date: str, extension: bool = False, inputs: dict | None = None) -> dict:
    """에이전트 4 를 노드 단위로 실행. inputs 를 주면 DB 를 읽지 않습니다(재현·테스트)."""
    from .nodes import run_agent_nodes

    as_of = require_as_of(as_of_date)
    if inputs is None:
        from . import db

        inputs = fetch_inputs(db.company(ticker), as_of)
    else:
        inputs = clean_inputs(inputs, as_of)
    return run_agent_nodes(4, ticker, as_of, extension=extension, available=available_inputs(inputs),
                           runners=make_runners(lambda t: inputs))
