"""에이전트 3의 '제작 기준' 연결 (docs/P03_투자심리수급_상세개발기획서.md v1.0, P01 문서 구조를 따름).

기존 기능(수급·기준선·중복 신호·논조·관심)은 그대로 두고, 기준에 맞춰 아래를 더합니다.
1. 공개 시점 규칙 (P03-F02, 문서 7.2): 기준일 t 에는 대차 t(다음 영업일 13시 공개)·검색 t(t+1 집계)를 쓰지 않음.
2. 등급·결과 종류 (문서 5장): core / reference, 관측·기준선 비교·과거 관계·조건부 예측·대용치.
   주가 수익률·코스피 대비 초과 수익률·외국인 순매수일 평균 가격은 P04(기술)·오해 소지 때문에 참고용.
3. 질문 계약 P03Plan (P03-F01): 관측/기준선/과거관계/예측/의도. 의도 질문은 INTENT_NOT_INFERABLE 로 보류.
4. 사건 연구 (P03-F07, 문서 14.2): 외국인·기관 5일 순매수 강도 |z|≥2 신호 뒤 5·20거래일 코스피 대비 초과수익률.
   종목 자신의 이력 + KOSPI 200 합산(PANEL_EVENT_SQL). 결과 창이 기준일까지 끝난 사건만, 표본 20건 미만은 보류.
5. 세 줄 요약 (문서 20장).
"""
from __future__ import annotations

import re

STANDARD = "모두의리서치 P03 투자심리·수급 상세 개발기획서 v1.0 (2026-10-28, P01 구조 준용)"
POLICY_VERSION = "p03-standard-v1"
Z_EVENT = 2.0
HORIZONS = (5, 20)
MIN_EVENTS = 20
GAP_DAYS = 5   # 신호가 이어진 날은 하나의 사건 (직전 신호에서 5거래일 넘게 떨어져야 새 사건)

GROUP_TIER: dict[str, tuple[str, str]] = {
    "수급": ("core", "관측"),
    "거래": ("core", "관측"),
    "시장": ("core", "기준선 비교"),
    "논조(감성)": ("core", "관측(사전 기준선 감성)"),
    "관심": ("core", "관측"),
    "시장 자금 흐름(ETF)": ("core", "대용치"),
    "과거 관계(사건 연구)": ("core", "과거 관계"),
    "가격·시장": ("reference", "관측(가격, P04 영역)"),
}
# 그룹과 다르게 볼 항목 (라벨 앞부분)
LABEL_TIER: tuple[tuple[str, tuple[str, str]], ...] = (
    ("VIX", ("core", "관측(시장 위험선호)")),
    ("외국인 순매수일 평균 가격", ("reference", "대용치(실제 매입 단가 아님)")),
    ("현재가의 외국인 순매수 평균 가격 대비", ("reference", "대용치(실제 매입 단가 아님)")),
)

STATUS_TEXT = {
    "MISSING_VINTAGE": "수급·대차 정정 이력 미보관 → D1 사후 탐색 등급",
    "STALE_FLOW": "투자자별 수급 자료가 오래됨",
    "FLOW_LAG": "수급이 가격보다 늦게 끝남 → 연속 일수·최근 강도 해석 주의",
    "AVAILABILITY_CUT": "기준일에 공개 전이던 자료(대차·검색)를 뺌",
    "SENT_MODEL_UNVALIDATED": "감성은 키워드 사전 기준선, 사람 라벨 평가 전",
    "SMALL_SAMPLE": "사건 연구 표본 부족 → 수치 보류",
    "DUPLICATE_SIGNALS": "같은 사건을 반영할 수 있는 신호 묶음 → 하나의 근거로 셈",
    "MODEL_NOT_APPROVED": "승인된 예측 모델 없음 → 관측·과거 관계만",
    "INTENT_NOT_INFERABLE": "매수 의도·정보 보유는 수급 기록으로 추정 불가 → 보류",
}

INTENT_Q = re.compile(r"의도|세력|작전|알고\s*(사|산|파)|정보를|내부자|매집")
FORECAST_Q = re.compile(r"오를까|오르나|떨어질까|내릴까|전망|예측|앞으로|따라\s*사|사도\s*돼|팔아야")


# ---------------------------------------------------------------- 1. 공개 시점

def availability(b: dict, as_of: str) -> dict:
    """묶음에서 기준일에 공개 전이던 관측을 뺍니다. 돌려주는 값: 뺀 항목 기록."""
    cut: dict = {}
    for key, label in (("lending", "대차잔고(다음 영업일 13시 공개)"), ("search", "검색 관심도(다음 날 집계)")):
        rows = b.get(key) or []
        keep = [r for r in rows if str(r.get("d"))[:10] < as_of]
        if len(keep) < len(rows):
            cut[label] = [str(r.get("d"))[:10] for r in rows if str(r.get("d"))[:10] >= as_of]
        b[key] = keep
    return {"policy": POLICY_VERSION, "cut": cut, "vintage": "missing",
            "rules": {"수급": "거래일 18:30 이후", "대차": "다음 영업일 13:00 이후", "검색": "다음 날",
                      "문서": "published_at 이후"}}


# ---------------------------------------------------------------- 2. 등급

def tier_of(group: str | None, label: str) -> tuple[str, str]:
    for prefix, t in LABEL_TIER:
        if label.startswith(prefix):
            return t
    return GROUP_TIER.get(group or "", ("core", "관측"))


def annotate(f) -> dict:
    n = {"core": 0, "reference": 0}
    for it in f.items.values():
        tier, rtype = tier_of(it.get("group"), it["label"])
        if it.get("kind") == "대용치" and rtype == "관측":
            rtype = "대용치"
        it["tier"], it["result_type"] = tier, rtype
        n[tier] += 1
    return n


# ---------------------------------------------------------------- 3. 질문 계약

def plan(question: str | None, period: int, as_of: str) -> dict:
    q = question or ""
    return {"standard": STANDARD, "policy": POLICY_VERSION, "question": question or None, "period": period,
            "origin": f"{as_of}T23:59:59+09:00",
            "asked": {"관측": True, "기준선": True, "과거관계": True,
                      "예측": bool(FORECAST_Q.search(q)), "의도": bool(INTENT_Q.search(q))}}


def finalize(p: dict, *, avail: dict, freshness: dict, flags: list[str], clusters: list, events: dict,
             sentiment_used: bool) -> dict:
    codes = ["MISSING_VINTAGE"]
    if avail.get("cut"):
        codes.append("AVAILABILITY_CUT")
    if any(x.startswith("자료 지연: 투자자별 수급") for x in flags):
        codes.append("STALE_FLOW")
    if freshness.get("수급 지연"):
        codes.append("FLOW_LAG")
    if sentiment_used:
        codes.append("SENT_MODEL_UNVALIDATED")
    if clusters:
        codes.append("DUPLICATE_SIGNALS")
    ev_ok = [e for e in events.get("rows", []) if e.get("status") == "ok"]
    if events.get("rows") and not ev_ok:
        codes.append("SMALL_SAMPLE")
    tasks = {
        "관측": {"state": "answered", "grade": "D1 사후 탐색 (정정 이력 미보관)"},
        "기준선": {"state": "answered", "note": "규칙 기준선(직전 60·90일, KOSPI 200 합산)"},
        "과거관계": {"state": "answered" if ev_ok else "held", "n_ok": len(ev_ok), "n": len(events.get("rows", [])),
                    "note": "신호 뒤 초과수익률 분포. 투자 신호·인과 아님"},
    }
    if p["asked"]["예측"]:
        codes.append("MODEL_NOT_APPROVED")
        tasks["예측"] = {"state": "held", "codes": ["MODEL_NOT_APPROVED"],
                        "note": "승인 예측 모델 없음. 과거 관계는 예측이 아님"}
    else:
        tasks["예측"] = {"state": "not_requested"}
    if p["asked"]["의도"]:
        codes.append("INTENT_NOT_INFERABLE")
        tasks["의도"] = {"state": "held", "codes": ["INTENT_NOT_INFERABLE"],
                        "note": "순매수 기록은 의도·정보 보유를 말하지 않음. 관측 부분만 답함"}
    else:
        tasks["의도"] = {"state": "not_requested"}
    codes = list(dict.fromkeys(codes))
    return {**p, "tasks": tasks, "status_codes": codes,
            "held_reasons": [f"{c}: {STATUS_TEXT.get(c, c)}" for c in codes]}


# ---------------------------------------------------------------- 4. 사건 연구

def _intensity_series(rows_desc: list[dict], col: str) -> list[tuple[str, float]]:
    out = []
    for r in reversed(rows_desc):
        if r.get("close") and r.get("tv"):
            out.append((str(r["d"])[:10], (r.get(col) or 0) * r["close"] / r["tv"] * 100))
    return out


def signal_days(series: list[tuple[str, float]], z_min: float = Z_EVENT) -> list[tuple[str, int]]:
    """(날짜, 방향 +1/-1). 직전 60일(최근 5일 제외) 분포 대비 최근 5일 평균의 표준점수. 이어진 날은 첫날만."""
    out, last_i = [], -10 ** 9
    vals = [v for _, v in series]
    for i in range(64, len(vals)):
        recent, base = vals[i - 4:i + 1], vals[i - 64:i - 4]
        mu = sum(base) / len(base)
        sd = (sum((x - mu) ** 2 for x in base) / (len(base) - 1)) ** 0.5
        if not sd:
            continue
        z = (sum(recent) / 5 - mu) / (sd / 5 ** 0.5)
        if abs(z) >= z_min:
            if i - last_i > GAP_DAYS:
                out.append((series[i][0], 1 if z > 0 else -1))
            last_i = i
    return out


def _quant(xs: list[float], q: float) -> float:
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def forward_excess(price: list[tuple[str, float]], kospi: list[tuple[str, float]], day: str, h: int,
                   as_of: str) -> float | None:
    """day 종가 → h 거래일 뒤 종가 수익률 − 같은 날짜 코스피 수익률(%). 결과 창이 기준일 안에 끝나야 함."""
    days = [d for d, _ in price]
    if day not in days:
        return None
    i = days.index(day)
    if i + h >= len(price) or price[i + h][0] > as_of:
        return None
    kd = dict(kospi)
    a, b = kd.get(price[i][0]), kd.get(price[i + h][0])
    if not a or not b:
        return None
    return ((price[i + h][1] / price[i][1]) - (b / a)) * 100


def summarize(values: list[float], dates: list[str], h: int, all_days: list[str]) -> dict:
    """표본 수, 겹치지 않는 사건 수(독립 기간), 분위수, 양(+) 비율."""
    indep, last = 0, -10 ** 9
    pos_of = {d: i for i, d in enumerate(all_days)}
    for d in sorted(dates):
        i = pos_of.get(d, 0)
        if i - last >= h:
            indep += 1
            last = i
    if not values:
        return {"n": 0, "independent": 0}
    return {"n": len(values), "independent": indep, "median": _quant(values, 0.5), "p10": _quant(values, 0.1),
            "p90": _quant(values, 0.9), "positive_share": sum(v > 0 for v in values) / len(values) * 100}


def event_study(rows_desc: list[dict], price: list[tuple[str, float]], kospi: list[tuple[str, float]],
                as_of: str) -> list[dict]:
    """종목 자신의 이력으로 사건 연구. 결과 행: 주체·방향·h 마다 하나."""
    out = []
    all_days = [d for d, _ in price]
    base = {h: [x for d in all_days if (x := forward_excess(price, kospi, d, h, as_of)) is not None] for h in HORIZONS}
    for who, col in (("외국인", "fq"), ("기관", "iq")):
        sig = signal_days(_intensity_series(rows_desc, col))
        for direction, name in ((1, "집중 순매수"), (-1, "집중 순매도")):
            days = [d for d, s in sig if s == direction]
            for h in HORIZONS:
                vals, ds = [], []
                for d in days:
                    x = forward_excess(price, kospi, d, h, as_of)
                    if x is not None:
                        vals.append(x)
                        ds.append(d)
                s = summarize(vals, ds, h, all_days)
                bs = summarize(base[h], [], h, all_days) if base[h] else {}
                out.append({"scope": "종목", "who": who, "signal": name, "h": h, **s,
                            "base_median": bs.get("median"), "base_n": bs.get("n"),
                            "status": "ok" if s["n"] >= MIN_EVENTS else "held"})
    return out


# KOSPI 200 합산 사건 연구 (P03-F07). 같은 날 여러 종목의 신호는 같은 시장 충격을 공유 → 신호 날짜 수를 함께 냄
PANEL_EVENT_SQL = """
WITH f AS (
    SELECT f.company_id, f.trade_date AS d,
           f.foreign_net_qty * p.close / NULLIF(p.trade_value, 0) * 100 AS fi,
           f.institution_net_qty * p.close / NULLIF(p.trade_value, 0) * 100 AS ii, p.close
    FROM core.investor_flow_daily f
    JOIN core.price_daily p ON p.company_id = f.company_id AND p.trade_date = f.trade_date
    JOIN core.company c ON c.company_id = f.company_id
    WHERE 'KOSPI200' = ANY(c.index_tags) AND f.trade_date <= %(as_of)s::date AND p.trade_value > 0
), w AS (
    SELECT *,
        avg(fi) OVER s5 AS f5, avg(fi) OVER b60 AS fmu, stddev_samp(fi) OVER b60 AS fsd,
        avg(ii) OVER s5 AS i5, avg(ii) OVER b60 AS imu, stddev_samp(ii) OVER b60 AS isd,
        count(*) OVER b60 AS nb,
        lead(close, 5) OVER o AS c5, lead(d, 5) OVER o AS d5, lead(close, 20) OVER o AS c20, lead(d, 20) OVER o AS d20
    FROM f
    WINDOW o AS (PARTITION BY company_id ORDER BY d),
           s5 AS (PARTITION BY company_id ORDER BY d ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
           b60 AS (PARTITION BY company_id ORDER BY d ROWS BETWEEN 64 PRECEDING AND 5 PRECEDING)
), z AS (
    SELECT company_id, d, close, c5, d5, c20, d20,
           (f5 - fmu) / NULLIF(fsd / sqrt(5), 0) AS fz, (i5 - imu) / NULLIF(isd / sqrt(5), 0) AS iz
    FROM w WHERE nb = 60
), z2 AS (
    SELECT *, lag(fz) OVER o AS fz_prev, lag(iz) OVER o AS iz_prev
    FROM z WINDOW o AS (PARTITION BY company_id ORDER BY d)
), ev AS (
    SELECT '외국인' AS who, CASE WHEN fz > 0 THEN '집중 순매수' ELSE '집중 순매도' END AS signal, company_id, d, close,
           c5, d5, c20, d20
    FROM z2 WHERE abs(fz) >= %(z)s AND (fz_prev IS NULL OR abs(fz_prev) < %(z)s)
    UNION ALL
    SELECT '기관', CASE WHEN iz > 0 THEN '집중 순매수' ELSE '집중 순매도' END, company_id, d, close, c5, d5, c20, d20
    FROM z2 WHERE abs(iz) >= %(z)s AND (iz_prev IS NULL OR abs(iz_prev) < %(z)s)
), k AS (
    SELECT trade_date AS d, close FROM core.market_index_daily WHERE symbol = '^KS11'
), r AS (
    SELECT ev.who, ev.signal, h.h, ev.d,
           CASE h.h WHEN 5 THEN (ev.c5 / ev.close - k5.close / k0.close) * 100
                    ELSE (ev.c20 / ev.close - k20.close / k0.close) * 100 END AS x
    FROM ev CROSS JOIN (VALUES (5), (20)) AS h(h)
    JOIN k k0 ON k0.d = ev.d
    LEFT JOIN k k5 ON k5.d = ev.d5
    LEFT JOIN k k20 ON k20.d = ev.d20
    WHERE (h.h = 5 AND ev.d5 <= %(as_of)s::date) OR (h.h = 20 AND ev.d20 <= %(as_of)s::date)
    UNION ALL  -- 무조건부 기준선: 같은 종목·기간의 모든 거래일
    SELECT '전체', '모든 거래일', h.h, z.d,
           CASE h.h WHEN 5 THEN (z.c5 / z.close - k5.close / k0.close) * 100
                    ELSE (z.c20 / z.close - k20.close / k0.close) * 100 END
    FROM z CROSS JOIN (VALUES (5), (20)) AS h(h)
    JOIN k k0 ON k0.d = z.d
    LEFT JOIN k k5 ON k5.d = z.d5
    LEFT JOIN k k20 ON k20.d = z.d20
    WHERE (h.h = 5 AND z.d5 <= %(as_of)s::date) OR (h.h = 20 AND z.d20 <= %(as_of)s::date)
)
SELECT json_agg(json_build_object(
    'who', who, 'signal', signal, 'h', h, 'n', n, 'dates', dates, 'median', med, 'p10', p10, 'p90', p90,
    'positive_share', pos) ORDER BY who, signal, h) AS bundle
FROM (SELECT who, signal, h, count(x) AS n, count(DISTINCT d) AS dates,
             percentile_cont(0.5) WITHIN GROUP (ORDER BY x) AS med,
             percentile_cont(0.1) WITHIN GROUP (ORDER BY x) AS p10,
             percentile_cont(0.9) WITHIN GROUP (ORDER BY x) AS p90,
             avg((x > 0)::int) * 100 AS pos
      FROM r WHERE x IS NOT NULL GROUP BY who, signal, h) s
"""


def panel_rows(raw) -> list[dict]:
    """PANEL_EVENT_SQL 결과 → 사건 연구 행. '모든 거래일' 행은 각 신호 행의 무조건부 기준선으로 붙임."""
    base = {int(r["h"]): r for r in raw or [] if r.get("signal") == "모든 거래일"}
    out = []
    for r in raw or []:
        if r.get("signal") == "모든 거래일":
            continue
        n = int(r.get("n") or 0)
        out.append({"scope": "KOSPI 200 합산", "who": r["who"], "signal": r["signal"], "h": int(r["h"]), "n": n,
                    "independent": int(r.get("dates") or 0), "median": r.get("median"), "p10": r.get("p10"),
                    "p90": r.get("p90"), "positive_share": r.get("positive_share"),
                    "base_median": (base.get(int(r["h"])) or {}).get("median"),
                    "base_n": (base.get(int(r["h"])) or {}).get("n"),
                    "base_positive_share": (base.get(int(r["h"])) or {}).get("positive_share"),
                    "status": "ok" if n >= MIN_EVENTS else "held"})
    return out


def add_event_facts(f, rows: list[dict], as_of: str, current: dict[str, int] | None = None,
                    group: str = "과거 관계(사건 연구)") -> list[dict]:
    """사건 연구를 장부에 올립니다. current: 지금 켜진 신호 {주체: 방향}. 그 신호에 해당하는 행만 장부에 올리고,
    켜진 신호가 없으면 KOSPI 200 합산의 외국인 20일 행만 올립니다(맥락용)."""
    cur = current or {}
    pick = []
    for r in rows:
        want = cur.get(r["who"])
        sig_dir = 1 if r["signal"] == "집중 순매수" else -1
        if want is not None and want == sig_dir:
            pick.append(r)
    if not pick:
        pick = [r for r in rows if r["scope"] == "KOSPI 200 합산" and r["who"] == "외국인" and r["h"] == 20]
    for r in pick:
        name = f"{r['scope']} {r['who']} {r['signal']} 뒤 {r['h']}거래일 코스피 대비 초과수익률"
        if r["status"] != "ok":
            f.gap(name, f"표본 {r['n']}건 (최소 {MIN_EVENTS}건) → SMALL_SAMPLE 보류")
            continue
        src = ("core.investor_flow_daily × core.price_daily × ^KS11"
               + (" (KOSPI 200 합산)" if r["scope"] != "종목" else ""))
        note = (f"사건 {r['n']}건·서로 다른 신호일 {r['independent']}개, 결과가 기준일까지 확정된 사건만. "
                f"과거 관계이며 예측·투자 신호·인과 아님. 신호: 5일 순매수 강도 |z|≥{Z_EVENT:g}")
        k = f.add(name + " 중앙값", r["median"], "%p", as_of, src, kind="calc", group=group, note=note)
        f.add(name + " 10% 분위", r["p10"], "%p", as_of, src, kind="calc", group=group)
        f.add(name + " 90% 분위", r["p90"], "%p", as_of, src, kind="calc", group=group)
        f.add(name + " 양(+) 비율", r["positive_share"], "%", as_of, src, kind="calc", group=group)
        if r.get("base_median") is not None:
            kb = f.add(f"{r['scope']} 모든 거래일 {r['h']}거래일 초과수익률 중앙값(무조건부 기준선)", r["base_median"],
                       "%p", as_of, src, kind="calc", group=group, note=f"{r.get('base_n')}개 종목·거래일")
            kd = f.add(name + " 중앙값 − 무조건부 기준선", r["median"] - r["base_median"], "%p", as_of, src,
                       kind="calc", group=group, note="신호가 없을 때와의 차이. 0 근처면 신호의 추가 정보가 작음")
            if k and kb and kd:
                f.flag(f"과거 관계: {r['scope']} {r['who']} {r['signal']} 뒤 {r['h']}일 초과수익률 중앙값 {{{k}}}, "
                       f"모든 거래일 기준선 {{{kb}}} (차이 {{{kd}}}). 과거 표본의 관계이며 예측·투자 신호 아님")
        r["key"] = k
    return pick


def current_signals(f) -> dict[str, int]:
    """장부의 '최근 5일 강도의 직전 60일 대비 표준점수' 가 |z|≥2 인 주체와 방향."""
    out = {}
    for who in ("외국인", "기관"):
        k = f.key_of(f"{who} 최근 5일 강도의 직전 60일 대비 표준점수")
        if k and abs(f.items[k]["value"]) >= Z_EVENT:
            out[who] = 1 if f.items[k]["value"] > 0 else -1
    return out


# ---------------------------------------------------------------- 5. 세 줄 요약

def summary3(f, p: dict) -> dict:
    facts = []
    for lab in ("외국인 20일 순매수 강도(거래대금 대비)", "기관 20일 순매수 강도(거래대금 대비)", "뉴스 감성(최근 7일)"):
        k = f.key_of(lab)
        if k:
            facts.append(f"{lab} {{{k}}}")
    rel = [x for x in f.flags if x.startswith(("외국인 20일", "기관 20일", "이상 징후", "중복 신호"))]
    held = [h.split(":")[0] for h in p.get("held_reasons") or []]
    return {"확인한 사실": "; ".join(facts) or "수급 관측 없음",
            "평소·시장 대비": " / ".join(rel[:4]) or "평소 범위 (코드 기준 이례 없음)",
            "아직 답 못한 부분": ", ".join(held) or "없음"}


def plan_md(p: dict) -> list[str]:
    names = {"answered": "답함", "held": "보류", "not_requested": "요청 없음"}
    out = ["", f"**P03 과업 계약** ({POLICY_VERSION}, 기준 시점 {p.get('origin')})", "",
           "| 과업 | 상태 | 비고 |", "| --- | --- | --- |"]
    for name, t in (p.get("tasks") or {}).items():
        codes = ", ".join(t.get("codes") or [])
        note = t.get("note") or t.get("grade") or ""
        out.append(f"| {name} | {names.get(t.get('state'), t.get('state'))} | {(codes + ' · ') if codes else ''}{note} |")
    if p.get("held_reasons"):
        out += ["", "보류·주의 코드: " + "; ".join(p["held_reasons"])]
    return out


def event_md(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    out = ["", "**과거 관계 (사건 연구, 투자 신호 아님)**", "",
           "| 범위 | 신호 | 기간 | 사건 수 | 신호일 수 | 중앙값 | 모든 거래일 중앙값(기준선) | 10%~90% | 양(+) 비율 | 상태 |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        if r["status"] == "ok":
            base = f"{r['base_median']:+.2f}%p" if r.get("base_median") is not None else "-"
            out.append(f"| {r['scope']} | {r['who']} {r['signal']} | {r['h']}일 | {r['n']} | {r['independent']} | "
                       f"{r['median']:+.2f}%p | {base} | {r['p10']:+.2f}~{r['p90']:+.2f}%p | {r['positive_share']:.0f}% | 확인 |")
        else:
            out.append(f"| {r['scope']} | {r['who']} {r['signal']} | {r['h']}일 | {r['n']} | - | - | - | - | - | 표본 부족 |")
    return out

