"""보고서 첨삭 모드 (A1·A2·A4).

1. 코드가 보고서의 숫자(조원·억원·원·%·%p·배)를 뽑아, 주변 단어로 장부 항목을 찾아 값을 대조합니다.
   판정: 일치 / 불일치(장부 값 제시) / 대조 불가. LLM은 이 판정을 바꾸지 못합니다.
2. 관점마다 LLM이 빠진 논점과 수정 제안을 장부 키로 씁니다. 실패하면 코드 판정 중 보고서에 없는 것을
   빠진 논점으로 내는 규칙 기반 첨삭으로 대체합니다.
"""
from __future__ import annotations

import re
import time

from .agents import AGENTS, AgentData, fetch_agent_data
from .facts import fmt
from .llm import BANNED, PLACEHOLDER, get_llm, parse_json, render, sentence_problems

REPORT_MAX_CHARS = 12000
NUM = re.compile(r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(조\s*\d[\d,]*\s*억\s*원|조\s*원|조|억\s*원|억|만\s*원|"
                 r"%p|%포인트|%|배|원|만\s*주|억\s*주|주)")
UNIT_KIND = {"조원": "KRW", "조": "KRW", "억원": "KRW", "억": "KRW", "만원": "KRW_or_price", "원": "KRW_or_price",
             "%p": "pp", "%포인트": "pp", "%": "pct", "배": "x", "주": "shares", "만주": "shares", "억주": "shares"}
MULT = {"조원": 1e12, "조": 1e12, "억원": 1e8, "억": 1e8, "만원": 1e4, "만주": 1e4, "억주": 1e8}
FACT_KIND = {"KRW": "KRW", "KRW±": "KRW", "%": "pct", "%chg": "pct", "%p": "pp", "배": "x", "주": "shares"}
SYNONYMS = {
    "매출액": "매출", "영업익": "영업이익", "당기순이익": "순이익", "순익": "순이익", "per": "PER", "pbr": "PBR",
    "roe": "ROE", "주가수익비율": "PER", "환율": "원/달러", "달러": "원/달러", "외인": "외국인", "부채": "부채비율",
    "fcf": "FCF", "잉여현금": "FCF", "기준금리": "기준금리", "국채": "국채금리", "지분율": "외국인 지분율",
}


def _tokens(text: str) -> set[str]:
    t = text.lower()
    for a, b in SYNONYMS.items():
        t = t.replace(a.lower(), " " + b.lower() + " ")
    return {w for w in re.split(r"[^0-9a-z가-힣/]+", t) if len(w) >= 2 and not w.isdigit()}


def extract_numbers(text: str) -> list[dict]:
    out = []
    for m in NUM.finditer(text):
        raw_num, unit = m.group(1), re.sub(r"\s+", "", m.group(2))
        try:
            v = float(raw_num.replace(",", ""))
        except ValueError:
            continue
        if unit.startswith("조") and "억" in unit:  # 1조 2,345억원
            eok = float(re.search(r"조\s*(\d[\d,]*)", m.group(2)).group(1).replace(",", ""))
            v, unit = v * 1e12 + eok * 1e8, "조원"
        else:
            v *= MULT.get(unit, 1)
        ctx = text[max(0, m.start() - 30):m.start()]
        out.append({"text": m.group(0), "value": v, "unit": unit, "kind": UNIT_KIND[unit], "context": ctx,
                    "pos": m.start()})
    return out


def _close(a: float, b: float, kind: str) -> bool:
    if kind in ("pct", "pp"):
        return abs(a - b) <= 0.15
    if kind == "shares":
        return abs(a - b) <= max(abs(b) * 0.01, 1e4 / 2)  # 만주 단위 반올림 허용
    if kind == "x":
        return abs(a - b) <= max(0.1, abs(b) * 0.03)
    return abs(a - b) <= abs(b) * 0.02


def check_numbers(report: str, datas: list[AgentData]) -> list[dict]:
    """보고서 숫자 ↔ 장부 대조. 장부 항목 이름과 주변 단어가 겹치는 것 중 가장 많이 겹치는 항목과 비교합니다."""
    rows = []
    for n in extract_numbers(report):
        ctx_tok = _tokens(n["context"])
        best, best_score = None, 0
        for d in datas:
            for k, it in d.facts.items.items():
                fk = FACT_KIND.get(it["unit"])
                if fk is None or not (fk == n["kind"] or (n["kind"] == "KRW_or_price" and fk == "KRW")):
                    continue
                score = len(ctx_tok & _tokens(it["label"]))
                if score > best_score:
                    best, best_score = (d.agent_id, k, it), score
        if not best:
            rows.append({**n, "verdict": "대조 불가", "agent_id": None, "key": None, "db_text": None})
            continue
        aid, k, it = best
        val = it["value"]
        ok = _close(n["value"], val, n["kind"] if n["kind"] != "KRW_or_price" else "KRW")
        rows.append({**n, "verdict": "일치" if ok else "불일치", "agent_id": aid, "key": k,
                     "db_text": it["text"], "label": it["label"], "as_of": it["as_of"]})
    return rows


def numbers_md(rows: list[dict]) -> str:
    if not rows:
        return "_보고서에서 단위가 붙은 숫자를 찾지 못했습니다._"
    out = ["| 보고서 | 판정 | 장부 항목 | 장부 값 | 키 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        out.append(f"| {r['text']} | {r['verdict']} | {r.get('label') or '-'} | {r.get('db_text') or '-'} | "
                   f"{r.get('key') or '-'} |")
    return "\n".join(out)


REVIEW_SCHEMA = """반드시 아래 JSON 하나만 출력하십시오:
{
  "빠진논점": [{"내용": "보고서가 다루지 않은 핵심 내용", "근거": ["키"]}],
  "수정제안": [{"원문": "보고서 문장 일부(그대로 인용)", "수정안": "고친 문장(숫자는 {키})", "근거": ["키"]}],
  "잘한점": ["..."],
  "완성도점수": 1~10 정수,
  "점수이유": "..."
}
빠진논점·수정제안은 각각 최대 3개. 당신 관점과 관련된 것만 다루십시오."""


def _review_messages(data: AgentData, report: str, rows: list[dict], mode: str) -> tuple[str, str]:
    spec = AGENTS[data.agent_id]
    mine = [r for r in rows if r.get("agent_id") == data.agent_id]
    verdicts = "\n".join(f"- '{r['text']}' → {r['verdict']} (장부 {r['key']} {r['label']} = {r['db_text']})"
                         for r in mine) or "- (이 관점에 해당하는 숫자 없음)"
    guide = ("입문자 모드: 각 지적마다 왜 문제인지와 용어 풀이를 쉬운 말로 덧붙이십시오." if mode == "guide"
             else "전문가 모드: 지적은 간결하게, 수정안은 바로 붙여 쓸 수 있게 쓰십시오.")
    system = f"""당신은 OpenResearch의 [A{data.agent_id}: {spec.name}]이며, 지금은 사용자 보고서를 첨삭합니다.
{spec.role}

[원칙]
1. 숫자는 직접 쓰지 말고 [숫자 장부]의 키를 중괄호로 쓰십시오. 보고서 숫자의 맞고 틀림은 [코드 수치 대조]만 따르십시오.
2. '매수 추천', '매도 추천', '목표주가' 표현은 금지합니다.
3. 당신 관점의 점검 항목 중 보고서가 빠뜨린 것을 찾으십시오:
""" + "\n".join(f"   - {c}" for c in spec.checklist) + f"""

[출력 모드] {guide}

{REVIEW_SCHEMA}"""
    user = f"""[대상] {data.company['name']} ({data.company['ticker']}) · 기준일 {data.as_of}

[사용자 보고서]
{report[:REPORT_MAX_CHARS]}

[코드 수치 대조 (이 관점)]
{verdicts}

[숫자 장부]
{data.facts.for_prompt()}

[코드 판정]
""" + ("\n".join(f"- {x}" for x in data.facts.flags) or "- (없음)")
    return system, user


def _sanitize_review(res: dict, data: AgentData) -> tuple[dict, list[str]]:
    valid = set(data.facts.items)
    removed: list[str] = []
    out = {"빠진논점": [], "수정제안": [], "잘한점": [], "완성도점수": None, "점수이유": str(res.get("점수이유", ""))}
    for it in res.get("빠진논점") or []:
        if not isinstance(it, dict):
            continue
        txt = str(it.get("내용", ""))
        refs = [str(k) for k in it.get("근거") or [] if str(k) in valid]
        (removed.append(txt) if sentence_problems(txt, valid) else out["빠진논점"].append({"내용": txt, "근거": refs}))
    for it in res.get("수정제안") or []:
        if not isinstance(it, dict):
            continue
        new = str(it.get("수정안", ""))
        refs = [str(k) for k in it.get("근거") or [] if str(k) in valid]
        if sentence_problems(new, valid):
            removed.append(new)
        else:
            out["수정제안"].append({"원문": str(it.get("원문", "")), "수정안": new, "근거": refs})
    for x in res.get("잘한점") or []:
        (removed if sentence_problems(str(x), valid) else out["잘한점"]).append(str(x))
    s = res.get("완성도점수")
    out["완성도점수"] = s if isinstance(s, int) and 1 <= s <= 10 else None
    if any(w in out["점수이유"] for w in BANNED):
        out["점수이유"] = ""
    return out, removed


def _fallback_review(data: AgentData, report: str) -> dict:
    missing = []
    for fl in data.facts.flags:
        keys = PLACEHOLDER.findall(fl)
        labels = [data.facts.items[k]["label"] for k in keys if k in data.facts.items]
        if labels and not any(_tokens(lb) & _tokens(report) for lb in labels):
            missing.append({"내용": fl, "근거": keys})
    return {"빠진논점": missing[:3], "수정제안": [], "잘한점": [], "완성도점수": None,
            "점수이유": "LLM 없이 코드 판정 중 보고서에 없는 항목만 표시"}


def review_md(data: AgentData, res: dict, rows: list[dict], status: str, removed: list[str]) -> str:
    r = lambda t: render(t, data)
    mine = [x for x in rows if x.get("agent_id") == data.agent_id]
    out = [f"- **상태**: {status}", "", "**① 수치 검증 (코드 판정)**", ""]
    out += [f"- '{x['text']}' → **{x['verdict']}**" + (f" (장부 {x['label']} = {x['db_text']} `[{x['key']}]`)"
                                                        if x["verdict"] == "불일치" else "") for x in mine] or ["- 해당 없음"]
    out += ["", "**② 빠진 논점**", ""] + ([f"- {r(x['내용'])}" for x in res["빠진논점"]] or ["- 없음"])
    out += ["", "**③ 수정 제안**", ""] + ([f"- \"{x['원문']}\" → {r(x['수정안'])}" for x in res["수정제안"]] or ["- 없음"])
    if res["잘한점"]:
        out += ["", "**잘한 점**", ""] + [f"- {r(x)}" for x in res["잘한점"]]
    s = res["완성도점수"]
    out += ["", f"**④ 관점별 완성도**: {s if s is not None else '-'} / 10 · {r(res['점수이유'])}"]
    if removed:
        out += [f"- 검증되지 않아 뺀 문장 {len(removed)}개"]
    return "\n".join(out)


def review_report(report: str, ticker: str, mode: str = "expert", agent_ids=(1, 2, 4), llm=None,
                  datas: list[AgentData] | None = None, as_of: str | None = None) -> dict:
    body = (report or "").strip()
    if not body or "여기에 첨삭할 보고서를 붙여 넣으세요" in body:
        raise ValueError("첨삭할 보고서 원문이 비어 있습니다.")
    datas = datas or [fetch_agent_data(a, ticker, as_of) for a in agent_ids]
    rows = check_numbers(body, datas)
    reviews = []
    for data in datas:
        t0 = time.monotonic()
        res, removed, status = None, [], "실패"
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system, user = _review_messages(data, body, rows, mode)
            parsed = parse_json((llm or get_llm()).invoke([SystemMessage(content=system),
                                                           HumanMessage(content=user)]).content)
            if parsed is not None:
                res, removed = _sanitize_review(parsed, data)
                status = "완료" + (" (일부 문장 제외)" if removed else "")
        except Exception as e:  # noqa: BLE001
            status = f"실패: {type(e).__name__}"
        if res is None:
            res, status = _fallback_review(data, body), "규칙 기반 대체"
        reviews.append({"agent_id": data.agent_id, "agent_name": data.name, "status": status, "result": res,
                        "removed": removed, "seconds": round(time.monotonic() - t0, 1),
                        "analysis": review_md(data, res, rows, status, removed),
                        "source": "Neon " + ", ".join(sorted({v["source"].split(" (")[0]
                                                              for v in data.facts.items.values()}))})
    return {"ticker": ticker, "mode": mode, "number_check": rows, "number_check_md": numbers_md(rows),
            "reviews": reviews}


__all__ = ["check_numbers", "extract_numbers", "fmt", "numbers_md", "review_report"]
