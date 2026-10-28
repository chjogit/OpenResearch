"""실데이터 점검 (LLM 없이 데이터 계산만). Windows cmd 에서 members\\CH 폴더에서:

    python scripts\\smoke_p01_p03.py 005930 000660

DATABASE_URL 은 .env 에서 읽습니다. 출력은 P01(에이전트 1)·P03(에이전트 3) 과업 계약과 핵심 숫자 요약입니다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ch_agents import agents, etf  # noqa: E402


def show(d, keys=("p01", "p03")):
    f = d.facts
    print(f"== {d.agent_id} {d.company['name']} {d.as_of}: 장부 {len(f.items)}개, 무자료 {len(f.gaps)}개, 판정 {len(f.flags)}개")
    for k in keys:
        x = d.extra.get(k)
        if not x:
            continue
        plan = x.get("plan") or {}
        print(json.dumps({"tasks": plan.get("tasks"), "codes": plan.get("status_codes"), "summary": x.get("summary"),
                          "tiers": x.get("tiers")}, ensure_ascii=False, indent=1, default=str)[:3000])
    for k, it in f.items.items():
        if it.get("group") in ("실적 예측(기준선)", "시나리오(공시 정적 환산)", "거시 이상 점검", "분기 자료 점검",
                               "시장 자금 흐름(ETF)", "시장 기준선(ETF·참고)", "과거 관계(사건 연구)"):
            print(f"  {k} [{it.get('tier', '-')}] {it['label']} = {it['text']} ({it['as_of']})")
    for g in f.gaps[:40]:
        print(f"  무자료: {g['label']}: {g['reason']}")
    for fl in f.flags[-8:]:
        print(f"  판정: {fl}")


def main(tickers):
    as_of = agents.today_kst()
    print("ETF 개요:")
    for r in etf.fetch_overview(as_of):
        print("  ", r)
    for t in tickers:
        d1 = agents.fetch_agent_data(1, t, as_of, question="환율 5% 상승, 금리 0.5%p 하락이면 다음 분기 매출은?",
                                     scenario="환율 5% 상승, 금리 0.5%p 하락")
        show(d1)
        d3 = agents.fetch_agent_data(3, t, as_of, period=20, question="외국인이 알고 사는 거야? 따라 사도 돼?")
        show(d3)


if __name__ == "__main__":
    main(sys.argv[1:] or ["005930", "000660"])
