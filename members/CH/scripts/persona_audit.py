"""페르소나 6종 점검: 같은 계약을 6개 프로필로 렌더링해, 프로필마다 무엇이 부족한지 셉니다.

Windows cmd, members\\CH 폴더에서:
    python scripts\\persona_audit.py 005930 105560 005380          (LLM 포함, 종목당 Solar 2회)
    python scripts\\persona_audit.py 005930 --no-llm                (LLM 없이 규칙 기반 대체 요약으로)

결과: persona_audit.json (커밋하지 않음), 화면에는 요약.

점검 항목
- 답변(렌더링): 프로필별 길이, 구역 수, L1 에 풀이 없이 나온 전문 용어, 상태 코드 원문 노출(MODEL_NOT_APPROVED 등),
  성향별 첫 화면(앞 3개 구역)에 실제 내용이 있는지, '답한 것·보류한 것' 구역 유무.
- 데이터: 미확인 항목을 채울 방법(수집 중·공시 일부·공시 없음·검증 미통과)별로 모아, 어떤 프로필에서 먼저 보이는지.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ch_agents import agents, db, render_all, run_agent  # noqa: E402
from ch_agents.glossary import GLOSSARY  # noqa: E402

# 입문자가 풀이 없이 만나면 막히는 용어 (에이전트 출력에 실제로 나오는 것 위주)
JARGON = ("기준선", "예측구간", "80% 구간", "공시 민감도", "정적 환산", "사건 연구", "초과수익률", "괴리율", "NAV",
          "자금 유출입", "robust z", "표준점수", "대용치", "순매수 강도", "대차잔고", "동조성", "베타", "상관",
          "장단기 금리차", "TTM", "순차평가", "블록", "매크로", "수출 비중", "이자율 민감도", "만기 비중",
          "외환 파생상품", "헤지", "판가 전가력", "매출채권 회수기간", "D1", "빈티지", "국면", "백분위", "VIX",
          "중복 신호", "사건 묶음", "감성", "키워드 사전")
CODE_RE = re.compile(r"\b[A-Z]{3,}(?:_[A-Z]+)+\b")      # MODEL_NOT_APPROVED 같은 상태 코드 원문


def audit_contract(c: dict) -> dict:
    views = render_all(c)
    out = {}
    for name, v in views.items():
        md = v["markdown"]
        secs = [s for s in v["sections"] if s["id"] not in ("disclaimer",)]
        first3 = [s for s in secs[:4] if s["id"] != "summary"][:3]
        gl = next((s for s in secs if s["id"] == "glossary"), None)
        explained = {ln.split("**")[1] for ln in (gl or {}).get("lines", []) if "**" in ln}
        unexplained = sorted(t for t in JARGON if t in md and t not in explained and t not in GLOSSARY)
        out[name] = {
            "chars": len(md), "sections": [s["id"] for s in secs],
            "first_screen": [(s["id"], len(s.get("items") or s.get("lines") or [])) for s in first3],
            "has_scope": any(s["id"] == "scope" for s in secs),
            "codes_shown": sorted(set(CODE_RE.findall(md))),
            "unexplained_terms": unexplained,
            "glossary_terms": len(explained),
        }
    return out


def data_needs(c: dict) -> list[dict]:
    rows = []
    for u in c.get("unverified") or []:
        rows.append({"item": u["item"], "category": u.get("category"), "availability": u.get("availability"),
                     "reason": (u.get("reason") or "")[:120]})
    return rows


def main(argv):
    use_llm = "--no-llm" not in argv
    tickers = [a for a in argv if not a.startswith("--")] or ["005930"]
    as_of = agents.today_kst()
    result = {"as_of": as_of, "llm": use_llm, "runs": []}
    need_count: Counter = Counter()
    need_where: dict = defaultdict(set)
    for t in tickers:
        co = db.company(t)
        for a, kw in ((1, {"question": "환율과 금리가 바뀌면 이 회사 실적은 어떻게 봐야 하나?"}),
                      (3, {"period": 20, "question": "요즘 이 종목 분위기와 수급은 어때?"})):
            data = agents.fetch_agent_data(a, t, as_of, co=co, **kw)
            if use_llm:
                r = run_agent(a, data=data, mode="expert")
            else:
                class _Fail:  # LLM 없이: 규칙 기반 대체 요약 경로
                    def invoke(self, *_a, **_k):
                        raise RuntimeError("no-llm")
                r = run_agent(a, data=data, llm=_Fail(), mode="expert")
            c = r["contract"]
            needs = data_needs(c)
            for n in needs:
                key = (a, n["availability"], n["item"])
                need_count[key] += 1
                need_where[key].add(t)
            result["runs"].append({"ticker": t, "name": co["name"], "agent": a, "status": r["status"],
                                   "claim_stats": r["claim_stats"], "summary": c["summary"]["text"],
                                   "statusCodes": (c.get("p01") or c.get("p03") or {}).get("statusCodes"),
                                   "personas": audit_contract(c), "needs": needs})
    result["needs_rollup"] = [{"agent": a, "availability": av, "item": it, "tickers": sorted(need_where[(a, av, it)]),
                               "n": n} for (a, av, it), n in need_count.most_common()]
    Path("persona_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    # 화면 요약
    for r in result["runs"]:
        print(f"\n== {r['name']} 에이전트 {r['agent']} · {r['status']} · {r['claim_stats']}")
        print("   상태 코드:", r["statusCodes"])
        for name, p in r["personas"].items():
            print(f"   {name:<14} {p['chars']:>6}자 구역 {len(p['sections']):>2} 첫화면 {p['first_screen']} "
                  f"풀이 {p['glossary_terms']} 미풀이 {p['unexplained_terms'][:8]} 코드노출 {p['codes_shown'][:4]}")
    print("\n== 미확인(데이터 보완 후보) 상위")
    for n in result["needs_rollup"][:40]:
        print(f"   A{n['agent']} [{n['availability']}] {n['item'][:50]} ({n['n']}종목)")


if __name__ == "__main__":
    main(sys.argv[1:])
