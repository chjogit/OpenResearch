r"""앞으로 쌓아 사후 측정 (#55): 에이전트 6 처럼 과거 기준일 재계산이 불가능한 영역을 위해, 오늘의 전망 결론을 기록해 두고 20거래일이 지난 뒤 채점한다.

    cd members\CH
    python -m outlook.forward record --tickers 005930,000660,005380,105560   # 오늘 기준 에이전트 3·4·6 결론을 outlook/forward_log.jsonl 에 추가(같은 기준일·종목·에이전트는 한 번만)
    python -m outlook.forward score                                          # 20거래일이 지난 기록을 채점 → outlook/forward_score.json

매 거래일 한 번 record 를 돌리면(수동 또는 스케줄) 몇 달 뒤 에이전트 6 의 적중률을 같은 정의(KOSPI 대비 초과수익률 부호)로 낼 수 있다.
채점 결과를 hit_rate.json 의 에이전트 6 칸에 합치는 일은 표본이 30건 이상 쌓인 뒤 사람이 확인하고 한다(자동으로 덮어쓰지 않음).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from ch_agents import db, node_agents, outlook  # noqa: E402
from outlook import backtest  # noqa: E402

LOG = HERE / "forward_log.jsonl"
SCORE = HERE / "forward_score.json"


def read_log() -> list[dict]:
    return [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()] if LOG.exists() else []


def record(tickers: list[str], as_of: str | None) -> int:
    as_of = as_of or str(db.q("SELECT max(trade_date) AS m FROM core.price_daily")[0]["m"])[:10]
    have = {(r["asOf"], r["ticker"], r["agent"]) for r in read_log()}
    n = 0
    with LOG.open("a", encoding="utf-8") as fh:
        for tk in tickers:
            co = db.company(tk)
            for no in (3, 4, 6):
                if (as_of, tk, no) in have:
                    continue
                o = node_agents.build_data(no, tk, as_of, extension=False, co=co).extra["outlook"]
                fh.write(json.dumps({"recordedAt": time.strftime("%Y-%m-%d %H:%M"), "asOf": as_of, "ticker": tk, "agent": no, "direction": o["direction"],
                                     "reason": o["reasonCode"], "ruleVersion": o["ruleVersion"], "signals": {s["id"]: s["state"] for s in o["signals"]}},
                                    ensure_ascii=False) + "\n")
                n += 1
    return n


def score() -> dict:
    rows = read_log()
    kospi = {str(r["trade_date"])[:10]: float(r["close"]) for r in db.q(
        "SELECT trade_date, close FROM core.market_index_daily WHERE symbol = '^KS11' AND close IS NOT NULL ORDER BY trade_date")}
    scored: dict[int, list[dict]] = {3: [], 4: [], 6: []}
    pending = 0
    for r in rows:
        co = db.company(r["ticker"])
        px = [(str(x["trade_date"])[:10], float(x["close"])) for x in db.q(
            "SELECT trade_date, close FROM core.price_daily WHERE company_id = %(c)s AND close IS NOT NULL ORDER BY trade_date", {"c": co["company_id"]})]
        idx = {d: i for i, (d, _) in enumerate(px)}
        fw = backtest.forward(px, kospi, idx[r["asOf"]]) if r["asOf"] in idx else None
        if fw is None:
            pending += 1
            continue
        scored[r["agent"]].append({**r, "excess": fw["excess"], "ret": fw["ret"], "prevExcess": fw["prev_excess"]})
    out = {"scoredAt": time.strftime("%Y-%m-%d %H:%M"), "ruleVersion": outlook.RULE_VERSION, "pending": pending, "agents": {}}
    for no, rs in scored.items():
        out["agents"][str(no)] = backtest.summarize(rs) if rs else {"samples": 0}
    SCORE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record", "score"])
    ap.add_argument("--tickers", default="005930,000660,005380,105560")
    ap.add_argument("--as-of", default=None)
    a = ap.parse_args()
    if a.cmd == "record":
        print("기록", record([t for t in a.tickers.split(",") if t], a.as_of), "건 →", LOG)
    else:
        o = score()
        print("채점 대기", o["pending"], "건;", {k: v.get("samples") for k, v in o["agents"].items()})


if __name__ == "__main__":
    main()
