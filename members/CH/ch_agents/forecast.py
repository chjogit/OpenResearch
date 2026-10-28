"""다음 분기 매출의 기준선 예측과 순차 평가 (P01 기준 문서 7장·10.2·11장·14장, 기능 P01-F05·F11 일부).

무엇을 하나
- B0 전년 동기 유지: 목표 분기의 1년 전 분기 매출을 그대로 예측값으로 씁니다.
- B1 계절·추세: B0 × (최근 4개 분기 합 ÷ 그 전 4개 분기 합). 8개 분기가 연속으로 공개돼 있을 때만.
  선택 규칙은 미리 고정: B1 이 가능하고 그 80% 구간을 낼 과거 오차 표본이 있으면 B1, 아니면 B0
  (자료 충분성 규칙. 평가 성적을 보고 바꾸지 않음).
- 80% 예측구간: 같은 기준선을 과거 모든 기업·분기에 순차 적용해 나온 로그 오차(log 실제/예측)의 10%·90% 분위수.
  기준일까지 '실제 매출이 공시된' 오차만 씁니다. 구간은 보정 검증 전이라 '검증된 80% 구간' 이라고 부르지 않습니다.
- 순차 평가: 각 과거 분기를 예측할 때 그 분기 시작 전에 공시된 오차만으로 구간을 만들고, 포함률·상대 오차를 냅니다.

지키는 것 (문서 9.3·15.2)
- 공시 시점: DART 보고서 접수일(rcept_no)부터 이용 가능. 접수일이 없으면 분기말 45일, 4분기(연간) 90일(제출 기한).
- 기업 간 같은 분기 오차는 독립이 아니므로 표본 수와 함께 '독립 시간축 분기 수'를 따로 보고합니다.
- 승인된 학습모델(ML)은 없습니다. 이 결과는 기준선이며 상태는 MODEL_NOT_APPROVED 입니다. 거시 변수는 쓰지 않으므로
  '거시 영향 예측' 이 아닙니다.
"""
from __future__ import annotations

import calendar
import math
from collections import defaultdict
from datetime import date, timedelta

MODEL_VERSION = "p01-baseline-v1"
LEVEL = 0.8
MIN_RESIDUALS = 40          # 구간을 내는 최소 오차 수
MIN_PERIODS = 4             # 구간을 내는 최소 독립 분기 수
SRC = "core.financial_quarter (revenue)"

# 전 종목 분기 매출 (순차 평가용). 이용 가능일은 파이썬에서 계산합니다.
# 'k' = 그 분기 값이 실린 DART 보고서의 접수일(rcept_no 앞 8자리). 정정 보고서로 받은 값이면 정정 접수일이라,
# 나중 수정값이 과거 시점에 새지 않습니다(P01 7.3). 접수일이 없으면(해외 SEC 등) 제출 기한 규칙(45·90일).
PANEL_SQL = """
WITH r AS (
    SELECT company_id, fiscal_year, report_code, to_date(max(left(rcept_no, 8)), 'YYYYMMDD') AS k
    FROM core.financial_fact WHERE source = 'dart' AND rcept_no ~ '^[0-9]{8}' GROUP BY 1, 2, 3
)
SELECT json_agg(json_build_object('c', q.company_id, 'pe', q.period_end, 'fy', q.fiscal_year, 'fq', q.fiscal_q,
                                  'v', q.amount, 'k', r.k)
                ORDER BY q.company_id, q.period_end) AS rows
FROM core.financial_quarter q
LEFT JOIN r ON q.source = 'dart' AND r.company_id = q.company_id AND r.fiscal_year = q.fiscal_year
 AND r.report_code = CASE q.fiscal_q WHEN 1 THEN '11013' WHEN 2 THEN '11012' WHEN 3 THEN '11014' ELSE '11011' END
WHERE q.metric = 'revenue' AND q.amount IS NOT NULL AND q.amount > 0
  AND q.period_end <= %(as_of)s::date
"""


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def available(pe, fq, k=None) -> date:
    """분기 값을 쓸 수 있는 날: 보고서 접수일 k 가 있으면 그날, 없으면 분기말 45일·4분기 90일(제출 기한)."""
    if k:
        return _d(k)
    return _d(pe) + timedelta(days=90 if int(fq) == 4 else 45)


def known(r: dict) -> date:
    return available(r["pe"], r["fq"], r.get("k"))


def add_quarter(pe: date) -> date:
    m = pe.month + 3
    y = pe.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _consecutive(a: date, b: date) -> bool:
    """a 다음 분기가 b 인가 (분기말 기준 80~100일)."""
    return 80 <= (b - a).days <= 100


def _chain(hist: list[dict], n: int) -> list[dict] | None:
    """최근 n 개 분기가 끊김 없이 이어지면 그 목록, 아니면 None."""
    if len(hist) < n:
        return None
    tail = hist[-n:]
    if all(_consecutive(_d(x["pe"]), _d(y["pe"])) for x, y in zip(tail, tail[1:])):
        return tail
    return None


def baselines(hist: list[dict], target_pe: date) -> dict:
    """hist: 목표 분기 직전까지 이용 가능한 분기(날짜순, 마지막이 목표 직전 분기여야 함). 돌려주는 값: {"B0", "B1", "pick"}."""
    out: dict = {"B0": None, "B1": None, "pick": None}
    if not hist or not _consecutive(_d(hist[-1]["pe"]), target_pe):
        return out
    c4 = _chain(hist, 4)
    if c4:
        out["B0"] = float(c4[0]["v"])  # 목표 분기의 1년 전 분기 = 직전 4개 분기 중 가장 오래된 분기
    c8 = _chain(hist, 8)
    if c8 and out["B0"] is not None:
        last4, prev4 = sum(float(x["v"]) for x in c8[4:]), sum(float(x["v"]) for x in c8[:4])
        if prev4 > 0:
            out["B1"] = out["B0"] * last4 / prev4
    out["pick"] = "B1" if out["B1"] is not None else "B0" if out["B0"] is not None else None
    return out


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def panel_errors(rows: list[dict]) -> list[dict]:
    """모든 기업·분기에 기준선을 적용한 과거 오차. 각 오차에 '예측 시점(목표 분기 시작 전날)'과 '실제 공시일'을 붙입니다."""
    by = defaultdict(list)
    for r in rows or []:
        by[r["c"]].append(r)
    out = []
    for cid, hist in by.items():
        hist.sort(key=lambda x: str(x["pe"]))
        for i in range(1, len(hist)):
            target = hist[i]
            tpe = _d(target["pe"])
            # 예측 시점 = 직전 분기가 공시된 날 (그때까지 공시된 분기만 입력). 기준일 예측과 같은 평가군입니다.
            origin = known(hist[i - 1])
            prior = [h for h in hist[:i] if known(h) <= origin]
            b = baselines(prior, tpe)
            actual = float(target["v"])
            for m in ("B0", "B1"):
                if b[m] and b[m] > 0 and actual > 0:
                    out.append({"c": cid, "pe": tpe.isoformat(), "method": m, "origin": origin.isoformat(),
                                "known": known(target).isoformat(),
                                "err": math.log(actual / b[m])})
    return out


def interval(errors: list[dict], method: str, known_by) -> dict | None:
    """known_by 까지 실제가 공시된 오차로 80% 구간 (로그 오차 분위수)."""
    known_by = str(known_by)[:10]
    errs = [e for e in errors if e["method"] == method and e["known"] <= known_by]
    periods = {e["pe"] for e in errs}
    if len(errs) < MIN_RESIDUALS or len(periods) < MIN_PERIODS:
        return None
    a = (1 - LEVEL) / 2
    return {"lo": quantile([e["err"] for e in errs], a), "hi": quantile([e["err"] for e in errs], 1 - a),
            "n": len(errs), "periods": len(periods)}


def sequential_eval(errors: list[dict], as_of: str) -> dict:
    """기준일까지 결과가 나온 과거 예측의 순차 평가. 각 예측의 구간은 그 예측 시점 전에 공시된 오차로만 만듭니다."""
    res = {}
    for m in ("B0", "B1"):
        done = [e for e in errors if e["method"] == m and e["known"] <= as_of]
        hits, scores, per_co = [], [], defaultdict(list)
        cache: dict = {}
        known = [x for x in errors if x["known"] <= as_of]
        for e in done:
            per_co[e["c"]].append(abs(math.exp(e["err"]) - 1))  # |실제/예측 - 1|
            when = min(e["origin"], as_of)
            if when not in cache:
                cache[when] = interval(known, m, when)
            iv = cache[when]
            if iv:
                hits.append(iv["lo"] <= e["err"] <= iv["hi"])
                w = iv["hi"] - iv["lo"]
                pen = 2 / (1 - LEVEL)
                scores.append(w + pen * max(iv["lo"] - e["err"], 0) + pen * max(e["err"] - iv["hi"], 0))
        co_mae = [sum(v) / len(v) for v in per_co.values()]
        res[m] = {
            "n": len(done), "companies": len(per_co), "periods": len({e["pe"] for e in done}),
            "rel_mae_equal_weight": (sum(co_mae) / len(co_mae) * 100) if co_mae else None,
            "coverage": (sum(hits) / len(hits) * 100) if hits else None, "n_interval": len(hits),
            "interval_score": (sum(scores) / len(scores)) if scores else None,
        }
    return res


def company_forecast(rows: list[dict], cid, as_of: str) -> dict:
    """한 기업의 다음 미공시 분기 매출 기준선 예측. 상태 코드를 함께 돌려줍니다."""
    mine = sorted([r for r in rows or [] if r["c"] == cid and known(r) <= _d(as_of)],
                  key=lambda x: str(x["pe"]))
    out = {"model": MODEL_VERSION, "status": [], "support_state": "baseline_only", "causal_effect": None,
           "publication_eligible": False, "level": LEVEL}
    if not mine:
        out["status"].append("QUARTER_MAPPING_CONFLICT")
        out["reason"] = "기준일에 공시된 분기 매출 없음"
        return out
    last = mine[-1]
    tpe = add_quarter(_d(last["pe"]))
    fq = int(last["fq"]) % 4 + 1
    fy = int(last["fy"]) + (1 if fq == 1 else 0)
    out.update({"target": f"{fy}Q{fq}", "target_end": tpe.isoformat(), "last_known": str(last["pe"])[:10],
                "horizon": "분기 종료 후 발표 전 추정" if tpe <= _d(as_of) else "다음 분기 예측"})
    b = baselines(mine, tpe)
    out.update({k: b[k] for k in ("B0", "B1", "pick")})
    if not b["pick"]:
        out["status"].append("STALE_CORE_INPUT")
        out["reason"] = "연속된 과거 4개 분기 매출이 없음"
        return out
    out["status"].append("MODEL_NOT_APPROVED")
    errors = panel_errors(rows)
    iv = interval(errors, b["pick"], as_of)
    if iv is None and b["pick"] == "B1" and b["B0"] is not None:
        # 사전 고정 규칙(자료 충분성): B1 은 8개 분기가 필요해 과거 오차 표본이 적음. 구간을 못 내면 구간이 있는 B0 로.
        iv0 = interval(errors, "B0", as_of)
        if iv0 is not None:
            b["pick"], iv = "B0", iv0
            out["pick_rule"] = "B1 구간 표본 부족 → B0 (사전 고정 규칙)"
            out["pick"] = "B0"
    point = b[b["pick"]]
    out["median"] = point
    if iv:
        out.update({"lower": point * math.exp(iv["lo"]), "upper": point * math.exp(iv["hi"]),
                    "residual_n": iv["n"], "residual_periods": iv["periods"]})
    else:
        out["interval_held"] = "과거 오차 표본 부족"
    out["evaluation"] = sequential_eval(errors, as_of)
    return out


def add_facts(f, fc: dict, as_of: str) -> list[str]:
    """장부에 올리고, 핵심 키를 돌려줍니다."""
    g = "실적 예측(기준선)"
    keys = []
    if not fc.get("pick"):
        f.gap("다음 분기 매출 기준선 예측", fc.get("reason") or "자료 부족")
        return keys
    tgt = fc["target"]
    names = {"B0": "전년 동기 유지(B0)", "B1": "계절·추세(B1)"}
    for m in ("B0", "B1"):
        if fc.get(m) is not None:
            k = f.add(f"{tgt} 매출 기준선 {names[m]}", fc[m], "KRW", as_of, f"{SRC} · {MODEL_VERSION}",
                      kind="forecast", group=g,
                      note=("선택된 기준선. " if fc["pick"] == m else "비교용. ") + "승인 모델 없음, 거시 변수 미사용")
            keys.append(k)
    if fc.get("lower") is not None:
        lab = f"{tgt} 매출 80% 예측구간"
        note = (f"과거 {fc['residual_n']}개 기업·분기 오차({fc['residual_periods']}개 분기)의 분위수. 보정 미검증, "
                "기업 간 같은 분기 오차는 독립이 아님")
        keys.append(f.add(lab + " 하한", fc["lower"], "KRW", as_of, f"{SRC} · {MODEL_VERSION}", kind="forecast",
                          group=g, note=note))
        keys.append(f.add(lab + " 상한", fc["upper"], "KRW", as_of, f"{SRC} · {MODEL_VERSION}", kind="forecast",
                          group=g, note=note))
    else:
        f.gap(f"{tgt} 매출 80% 예측구간", fc.get("interval_held") or "보류")
    ev = (fc.get("evaluation") or {}).get(fc["pick"]) or {}
    if ev.get("rel_mae_equal_weight") is not None:
        f.add(f"기준선 {fc['pick']} 과거 순차평가 상대오차(기업 균등)", ev["rel_mae_equal_weight"], "%", as_of,
              f"{SRC} · {MODEL_VERSION}", kind="calc", group=g,
              note=f"{ev['companies']}개 기업·{ev['periods']}개 분기, 사후 정정값 기준(빈티지 없음)")
    if ev.get("coverage") is not None:
        f.add(f"기준선 {fc['pick']} 과거 80% 구간 포함률", ev["coverage"], "%", as_of, f"{SRC} · {MODEL_VERSION}",
              kind="calc", group=g, note=f"{ev['n_interval']}건. 목표 75~85% (문서 15.2), 표본이 작아 판정 아님")
    f.note(f"실적 예측({tgt}, {fc['horizon']}): 기준선만 있음(승인 모델 없음). 주가·투자 판단이 아니라 매출 규모의 참고 범위")
    return [k for k in keys if k]
