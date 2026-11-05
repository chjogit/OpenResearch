r"""질의응답 해석 정확도 측정 (티켓 #53): 시험셋(testset.json) 질문마다 해석 단계만 실제 LLM 으로 돌려 정답 라벨과 비교한다.

    cd members\CH
    python -m qa.eval_interp            # → qa/eval_results.json (질의응답 HTML '시험셋 결과' 탭이 읽음)
항목: 종목·기간·영역·의도·거절·가정. 정확도가 낮은 항목은 고치지 않고 틀린 사례만 기록한다(PM 이 개선 여부 판단).
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from qa import agent  # noqa: E402

FIELDS = ("종목", "기간", "영역", "의도", "거절", "가정")


def company_key(c: dict) -> str:
    return {"found": c.get("name"), "not_found": "OUT", "ambiguous": "AMBIG", "none": "NONE"}[c["status"]]


def period_key(p: dict):
    return [p["type"], p["days"] if p["type"] == "relative" else p["as_of"] if p["type"] == "date" else None]


def compare(item: dict, it: dict) -> dict[str, tuple[bool, str, str]]:
    ep = item["period"]
    exp_p = [ep["type"], ep.get("value")]
    got = {"종목": company_key(it["company"]), "기간": period_key(it["period"]), "영역": sorted(it["domains"]), "의도": it["intent"],
           "거절": it["refuse"], "가정": bool(it["scenario"])}
    exp = {"종목": item["company"], "기간": exp_p, "영역": sorted(item["domains"]), "의도": item["intent"], "거절": item["refuse"], "가정": item["scenario"]}
    return {f: (got[f] == exp[f], json.dumps(exp[f], ensure_ascii=False), json.dumps(got[f], ensure_ascii=False)) for f in FIELDS}


def main():
    from ch_agents import db, llm as L

    items = json.loads((HERE / "testset.json").read_text(encoding="utf-8"))["items"]
    universe = agent.load_universe()
    latest = str(db.q("SELECT max(trade_date) AS m FROM core.price_daily")[0]["m"])[:10]
    today = time.strftime("%Y-%m-%d")
    llm = L.get_llm()

    def one(item):
        return agent.interpret(item["q"], llm, universe, today, latest, agent.Meter())

    t0 = time.monotonic()
    with ThreadPoolExecutor(4) as ex:
        its = list(ex.map(one, items))
    acc = {f: {"ok": 0, "total": 0, "rate": 0.0} for f in FIELDS}
    wrong = []
    for item, it in zip(items, its):
        for f, (ok, exp, got) in compare(item, it).items():
            acc[f]["total"] += 1
            acc[f]["ok"] += ok
            if not ok:
                wrong.append({"q": item["q"], "field": f, "expected": exp, "got": got})
    for v in acc.values():
        v["rate"] = round(v["ok"] / v["total"], 3)
    allok = sum(all(ok for ok, _, _ in compare(i, t).values()) for i, t in zip(items, its))
    out = {"n": len(items), "ran_at": time.strftime("%Y-%m-%d %H:%M"), "llm": L.MODEL, "today": today, "latest": latest,
           "accuracy": acc, "all_fields_correct": {"ok": allok, "total": len(items), "rate": round(allok / len(items), 3)},
           "wrong": wrong, "seconds": round(time.monotonic() - t0, 1), "items": [i["q"] for i in items]}
    (HERE / "eval_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for f, v in acc.items():
        print(f"{f}: {v['ok']}/{v['total']} = {v['rate']:.0%}")
    print(f"전 항목 정답 {allok}/{len(items)}, {out['seconds']}초, 틀린 항목 {len(wrong)}건")


if __name__ == "__main__":
    main()
