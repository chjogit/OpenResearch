r"""전망 결론(규칙 outlook-r1)의 과거 적중률 측정 (#55). 계산 방식·도출 과정: docs/OUTLOOK_BACKTEST.md

    cd members\CH
    python -m outlook.backtest              # → outlook/hit_rate.json, backtest_samples_nonoverlap.csv, (선택) --verify 로 노드 실행과 값 대조

절차: 과거 기준일 t 마다 (1) t 까지의 데이터만으로 에이전트 3·4 의 결론을 outlook.compute 로 계산(as_of 규칙: t 이후 행 금지)
      (2) t 종가 대비 20거래일 뒤 종가 수익률을 구해 KOSPI(^KS11) 같은 기간 수익률과 비교.
적중(기본): 긍정 결론이면 초과수익률(종목−KOSPI) > 0, 부정 결론이면 < 0. 보조: 절대수익률 > 0 / < 0. 중립은 적중률에서 빼고 비율만 보고.
표본: 전체(에이전트 4 는 매 거래일, 에이전트 3 은 5거래일마다) + 겹치지 않는 20거래일 간격(종목별 거래일 번호 % 20 == 0).
기준선: 항상 긍정 / 모멘텀(직전 20거래일 초과수익률 부호) / 무작위 50% — 모두 같은 표본(비중립 결론이 난 기준일)에서 비교.
규칙·기준값은 이 측정 결과를 보고 고치지 않는다(과적합 금지). 고치면 새 규칙 버전으로 다시 재고 두 결과를 모두 남긴다.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from bisect import bisect_right
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ch_agents import agent1_macro, db, outlook  # noqa: E402
from ch_agents.facts import Facts  # noqa: E402
from ch_agents.flow_core import WHO, add_net_buy  # noqa: E402

START = "2023-01-02"          # 첫 기준일: 수급 이력(2022-09 시작)·거시 250일 상관·27개월 창이 모두 채워진 뒤
HORIZON = outlook.HORIZON_DAYS
STEP = {4: 1, 3: 5}           # 전체 표본의 기준일 간격(거래일). 에이전트 3 은 계산 비용 때문에 5거래일마다
NONOVERLAP = 20
MACRO_IDS = list(agent1_macro.ALL_SERIES)
RESULT_JSON = HERE / "hit_rate.json"
RESULT_CSV = HERE / "backtest_samples_nonoverlap.csv"
BASIS = "20거래일 KOSPI 대비 초과수익률 부호(긍정 >0, 부정 <0)"
COMMAND = r"cd members\CH && python -m outlook.backtest"


# ---------------------------------------------------------------- 통계

def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def rate(k: int, n: int) -> dict:
    return {"hits": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


# ---------------------------------------------------------------- 입력 (읽기 전용)

def load() -> dict:
    cos = db.q("SELECT company_id, ticker, name FROM core.company WHERE market = 'KR' ORDER BY company_id")
    kospi = {str(r["trade_date"])[:10]: float(r["close"]) for r in db.q(
        "SELECT trade_date, close FROM core.market_index_daily WHERE symbol = '^KS11' AND close IS NOT NULL ORDER BY trade_date")}
    px: dict[int, list] = {}
    for r in db.q("SELECT company_id, trade_date, close FROM core.price_daily WHERE close IS NOT NULL ORDER BY company_id, trade_date"):
        px.setdefault(r["company_id"], []).append((str(r["trade_date"])[:10], float(r["close"])))
    fl: dict[int, list] = {}
    for r in db.q("SELECT f.company_id, f.trade_date AS d, f.foreign_net_qty AS fq, f.institution_net_qty AS iq, f.individual_net_qty AS pq, "
                  "p.close, p.trade_value AS tv FROM core.investor_flow_daily f "
                  "LEFT JOIN core.price_daily p ON p.company_id = f.company_id AND p.trade_date = f.trade_date ORDER BY f.company_id, f.trade_date"):
        fl.setdefault(r["company_id"], []).append({**r, "d": str(r["d"])[:10]})
    return {"companies": cos, "kospi": kospi, "px": px, "flows": fl}


def load_macro() -> dict:
    series: dict[str, list] = {}
    for r in db.q("SELECT series_id, obs_date, value FROM core.macro_obs WHERE series_id = ANY(%(s)s) ORDER BY series_id, obs_date", {"s": MACRO_IDS}):
        series.setdefault(r["series_id"], []).append({"d": str(r["obs_date"])[:10], "v": r["value"]})
    index: dict[str, list] = {}
    for r in db.q("SELECT symbol, trade_date, close FROM core.market_index_daily WHERE symbol IN ('^KS11', '^SOX') AND close IS NOT NULL ORDER BY symbol, trade_date"):
        index.setdefault(r["symbol"], []).append({"d": str(r["trade_date"])[:10], "v": float(r["close"])})
    return {"series": series, "index": index}


# ---------------------------------------------------------------- 과거 기준일 t 의 장부 → 결론 (t 이후 데이터 금지)

def flow_items(rows_asc: list[dict], dates: list[str], t: str) -> dict:
    """에이전트 4: flow_nodes.n08 과 같은 계산(add_net_buy)으로 t 시점 순매수 강도 장부를 만든다. t 이후 행은 쓰지 않음."""
    end = bisect_right(dates, t)
    rows = list(reversed(rows_asc[max(0, end - 70):end]))          # 최신순
    while rows and not (rows[0].get("close") and rows[0].get("tv")):  # n08 과 같은 규칙: 시세 공개 전 행은 뺌
        rows.pop(0)
    if not rows:
        return {}
    f = Facts("S")
    for who, col in WHO:
        add_net_buy(f, rows, who, col, (5, 20, 60), (20,), "누적")
    return f.items


class MacroSlicer:
    """에이전트 3: 긴 이력 번들을 t 까지 잘라(bisect) agent1_macro.compute 에 넘긴다(노드 N05 와 같은 계산, 공표 시점 규칙 vintage 포함)."""

    def __init__(self, macro: dict, price: list[tuple[str, float]]):
        self.m = macro
        self.price = [{"d": d, "v": v} for d, v in price]
        self.keys = {sid: [r["d"] for r in rows] for sid, rows in macro["series"].items()}
        self.ikeys = {sym: [r["d"] for r in rows] for sym, rows in macro["index"].items()}
        self.pkeys = [r["d"] for r in self.price]

    def bundle(self, t: str) -> dict:
        cut = lambda rows, ks: rows[:bisect_right(ks, t)]            # noqa: E731
        return {"series": {sid: cut(rows, self.keys[sid]) for sid, rows in self.m["series"].items()},
                "index": {sym: cut(rows, self.ikeys[sym]) for sym, rows in self.m["index"].items()},
                "price": cut(self.price, self.pkeys), "fund": None, "ttm_op": None, "docs": []}

    def items(self, co: dict, t: str) -> dict:
        try:
            return agent1_macro.compute(self.bundle(t), co, t)["facts"].items
        except Exception:  # noqa: BLE001 — 계산 못 한 기준일은 장부 없음 → '근거 부족' 중립으로 센다
            return {}


# ---------------------------------------------------------------- 수익률·적중

def sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def forward(px: list[tuple[str, float]], kospi: dict, i: int) -> dict | None:
    """종목 거래일 번호 i(기준일)의 직전 20거래일·이후 20거래일 수익률과 KOSPI 대비 초과수익률."""
    if i < HORIZON or i + HORIZON >= len(px):
        return None
    (d0, p0), (dm, pm), (d1, p1) = px[i], px[i - HORIZON], px[i + HORIZON]
    if not (d0 in kospi and dm in kospi and d1 in kospi):
        return None
    r = p1 / p0 - 1
    k = kospi[d1] / kospi[d0] - 1
    r_prev = p0 / pm - 1
    k_prev = kospi[d0] / kospi[dm] - 1
    return {"end": d1, "ret": r, "kospi": k, "excess": r - k, "prev_excess": r_prev - k_prev}


def run_agent(agent_no: int, data: dict, macro: dict | None, limit: int | None) -> list[dict]:
    rows_out = []
    cos = data["companies"][:limit] if limit else data["companies"]
    for c in cos:
        px = data["px"].get(c["company_id"]) or []
        dates = [d for d, _ in px]
        if agent_no == 4:
            fl = data["flows"].get(c["company_id"]) or []
            fkeys = [r["d"] for r in fl]
        else:
            ms = MacroSlicer(macro, px)
            co = {**c, "market": "KR", "krx_sector": None, "sector": None, "index_tags": None, "peer_method": None}
        for i, (t, _) in enumerate(px):
            if t < START or i % STEP[agent_no] != 0:
                continue
            fw = forward(px, data["kospi"], i)
            if fw is None:
                continue
            items = flow_items(fl, fkeys, t) if agent_no == 4 else ms.items(co, t)
            o = outlook.compute(agent_no, items, t)
            rows_out.append({"agent": agent_no, "ticker": c["ticker"], "asOf": t, "direction": o["direction"], "reason": o["reason"] or "",
                             "idx": i, "end": fw["end"], "ret": round(fw["ret"], 6), "kospi": round(fw["kospi"], 6),
                             "excess": round(fw["excess"], 6), "prevExcess": round(fw["prev_excess"], 6)})
    return rows_out


# ---------------------------------------------------------------- 집계

def hit(direction: str, v: float) -> bool:
    return v > 0 if direction == "positive" else v < 0


def summarize(rows: list[dict]) -> dict:
    calls = [r for r in rows if r["direction"] != "neutral"]
    neutral = [r for r in rows if r["direction"] == "neutral"]
    by_reason: dict[str, int] = {}
    for r in neutral:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    primary = sum(hit(r["direction"], r["excess"]) for r in calls)
    absolute = sum(hit(r["direction"], r["ret"]) for r in calls)
    always_pos = sum(r["excess"] > 0 for r in calls)
    mom = sum(sign(r["prevExcess"]) == sign(r["excess"]) and sign(r["excess"]) != 0 for r in calls)
    pos = [r for r in calls if r["direction"] == "positive"]
    neg = [r for r in calls if r["direction"] == "negative"]
    return {"samples": len(rows), "calls": len(calls), "positive": len(pos), "negative": len(neg), "neutral": len(neutral),
            "neutralShare": round(len(neutral) / len(rows), 4) if rows else None, "neutralByReason": by_reason,
            "primary": rate(primary, len(calls)), "absolute": rate(absolute, len(calls)),
            "positiveCalls": rate(sum(r["excess"] > 0 for r in pos), len(pos)), "negativeCalls": rate(sum(r["excess"] < 0 for r in neg), len(neg)),
            "baselines": {"alwaysPositive": rate(always_pos, len(calls)), "momentum": rate(mom, len(calls)), "random": {"rate": 0.5, "note": "무작위 50%"}},
            "tickers": len({r["ticker"] for r in rows}), "firstAsOf": min((r["asOf"] for r in rows), default=None),
            "lastAsOf": max((r["asOf"] for r in rows), default=None)}


def verify(data: dict, macro: dict, k: int = 4) -> dict:
    """백테스트 계산이 실제 노드 실행(run_nodes + merge_facts)과 같은 장부 값을 내는지 몇 건 대조."""
    from ch_agents import node_agents

    checked, mismatches = 0, []
    for c in data["companies"][:: max(1, len(data["companies"]) // k)][:k]:
        px = data["px"][c["company_id"]]
        co = db.company(c["ticker"])
        fl = data["flows"].get(c["company_id"]) or []
        ms = MacroSlicer(macro, px)
        for t in (px[len(px) // 2][0], px[len(px) - 60][0]):
            real4 = {v["label"]: v["value"] for v in node_agents.merge_facts(node_agents.run_nodes(4, c["ticker"], t, True, None, None, co))[0].items.values()}
            mine4 = {v["label"]: v["value"] for v in flow_items(fl, [r["d"] for r in fl], t).values()}
            real3 = {v["label"]: v["value"] for v in node_agents.merge_facts(node_agents.run_nodes(3, c["ticker"], t, False, None, None, co))[0].items.values()}
            mine3 = {v["label"]: v["value"] for v in ms.items(co, t).values()}
            for no, real, mine in ((4, real4, mine4), (3, real3, mine3)):
                for rule in outlook.RULES[no]:
                    for lab in (rule["label"], rule.get("corr_label")):
                        if lab is None:
                            continue
                        checked += 1
                        a, b = real.get(lab), mine.get(lab)
                        if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-9 * max(1.0, abs(a))):
                            mismatches.append({"agent": no, "ticker": c["ticker"], "asOf": t, "label": lab, "node": a, "backtest": b})
    return {"checkedValues": checked, "mismatches": mismatches}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="종목 수 제한(시험용)")
    ap.add_argument("--verify", action="store_true", help="노드 실행과 장부 값 대조만 하고 끝냄")
    ap.add_argument("--agent3-limit", type=int, default=42, help="에이전트 3 에 쓸 종목 수(계산 비용). 종목 순서(company_id)대로 균등 간격으로 뽑음")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    data = load()
    macro = load_macro()
    print(f"입력 적재 {time.time() - t0:.0f}s, 종목 {len(data['companies'])}")
    if a.verify:
        v = verify(data, macro)
        print(json.dumps(v, ensure_ascii=False, indent=1))
        return
    all4 = run_agent(4, data, None, a.limit)
    print(f"에이전트 4: 표본 {len(all4)} ({time.time() - t0:.0f}s)")
    cos = data["companies"]
    stride = max(1, len(cos) // a.agent3_limit)
    data3 = {**data, "companies": cos[::stride][:a.agent3_limit]}
    all3 = run_agent(3, data3, macro, a.limit)
    print(f"에이전트 3: 표본 {len(all3)} ({time.time() - t0:.0f}s)")
    agents, csv_rows = {}, []
    for no, rows in ((4, all4), (3, all3)):
        nonov = [r for r in rows if r["idx"] % NONOVERLAP == 0]
        s_all, s_non = summarize(rows), summarize(nonov)
        pr = s_non["primary"]
        agents[str(no)] = {"rate": pr["rate"], "n": pr["n"], "ci95": pr["ci95"], "basis": BASIS, "period": f"{s_non['firstAsOf']}~{s_non['lastAsOf']} 기준일, 종목 {s_non['tickers']}개, 20거래일 간격(겹치지 않음)",
                           "headline": "겹치지 않는 20거래일 간격 표본", "nonOverlapping": s_non, "allDays": s_all,
                           "note": "같은 날짜의 종목들은 시장 움직임을 공유해 서로 독립이 아니므로 신뢰구간은 실제보다 좁게 나옴" }
        csv_rows += nonov
    agents["6"] = {"unverified": "과거 자료 보관 14일 — 과거 기준일 재계산 불가. 앞으로 결과를 쌓아 사후 측정(docs/OUTLOOK_BACKTEST.md '앞으로 쌓기', python -m outlook.forward)"}
    for no in ("4", "3"):
        e = agents[no]
        rates = {k: v.get("rate") for k, v in e["nonOverlapping"]["baselines"].items()}
        e["verdict"] = outlook.judge(e["ci95"], rates, e["n"])
        e["verdictLabel"] = outlook.VERDICT_LABEL[e["verdict"]]
    agents["6"]["verdict"] = "unverified"
    agents["6"]["verdictLabel"] = outlook.VERDICT_LABEL["unverified"]
    out = {"ruleVersion": outlook.RULE_VERSION, "generatedAt": time.strftime("%Y-%m-%d %H:%M"), "command": COMMAND, "horizonDays": HORIZON,
           "start": START, "basis": BASIS, "agents": agents, "seconds": round(time.time() - t0)}
    if not a.no_write:
        RESULT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        cols = ["agent", "ticker", "asOf", "direction", "reason", "end", "ret", "kospi", "excess", "prevExcess"]
        with RESULT_CSV.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(csv_rows)
    for no in ("4", "3"):
        e = agents[no]
        print(no, "판정", e["verdictLabel"], "| 헤드라인", e["rate"], e["n"], e["ci95"], "| 중립", e["nonOverlapping"]["neutralShare"], "| 기준선", {k: v.get("rate") for k, v in e["nonOverlapping"]["baselines"].items()})
        print("   전체", e["allDays"]["primary"], e["allDays"]["neutralShare"])


if __name__ == "__main__":
    main()
