"""Verifier 연동 (기초기획서 R2 2.2 'Verifier 통과 필수', 3.4 'fact_source_verifier').

팀 공용 `agent/verifier/fact_source_verifier.py` 의 verify() 로 최종 문장을 한 번 더 검사합니다.
- 장부 키를 값으로 바꾼 '사람이 읽는 문장'에서 숫자를 뽑아, 그 문장이 인용한 장부 항목(도구 실행 기록)과 1:1 대조
- 통과한 문장에는 인용한 항목의 출처 태그를 붙임: [출처: Neon core.macro_obs ECOS_USDKRW, 2026-10-24]
- 통과하지 못한 문장은 최종 출력에서 뺌 (앞 단계의 코드 검사와 별개로 두 번째 관문)

장부 항목 이름에 든 숫자(예: '52주', '250일')는 값이 아니라 용어이므로 대조 대상 값에 함께 넣습니다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from agent.db import ToolResult
    from agent.verifier.fact_source_verifier import verify as _verify
except ImportError:  # members/CH 에서 실행하면 저장소 최상위가 경로에 없음
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from agent.db import ToolResult
    from agent.verifier.fact_source_verifier import verify as _verify

KEY = re.compile(r"\{([A-Z]\d+)\}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{4}\.\d{1,2}(?:\.\d{1,2})?|FY\d{4}")
LABEL_NUM = re.compile(r"\d+(?:\.\d+)?")
TOOL = "ch_agents"


def _source_tag(it: dict) -> str:
    src = str(it.get("source") or "").split(" (")[0]
    when = str(it.get("as_of") or "")
    return f"Neon {src}" + (f", {when}" if when and when not in ("-",) and len(when) <= 12 else "")


def _doc_tag(d: dict) -> str:
    if d.get("kind") == "공시":
        return f"{str(d.get('source') or 'dart').upper()} 공시 {d.get('published')}"
    return f"{d.get('kind', '문서')} {d.get('published')}"


def plain(text: str, data) -> str:
    """장부 키를 표시 값으로, 문서 키를 [D번호]로 바꾼 평문."""
    items = data.facts.items

    def sub(m):
        k = m.group(1)
        if k in items:
            return items[k]["text"]
        return f"[{k}]"

    return KEY.sub(sub, str(text))


def _term_values(data) -> dict:
    vals = {}
    for i, it in enumerate(data.facts.items.values()):
        for j, x in enumerate(LABEL_NUM.findall(it["label"])):
            vals[f"t{i}_{j}"] = x
    vals["pos_max"] = 100  # '35/100' 처럼 범위 표기에 쓰는 분모
    return vals


def check_text(text: str, keys: list[str], data, terms: dict | None = None) -> dict:
    """문장 하나를 대조. 돌려주는 값: {ok, unmatched, sources}"""
    items = data.facts.items
    shown = plain(text, data)
    rows = [{"value": items[k]["value"]} for k in keys if k in items and items[k]["value"] is not None]
    rows.append(terms if terms is not None else _term_values(data))
    res = _verify(DATE.sub(lambda m: " " * len(m.group(0)), shown),
                  [ToolResult(tool=TOOL, source="ledger", sql="", params={}, rows=rows)])
    sources = []
    for k in keys:
        if k in items:
            tag = _source_tag(items[k])
        elif k.startswith("D") and k[1:].isdigit() and int(k[1:]) <= len(data.docs):
            tag = _doc_tag(data.docs[int(k[1:]) - 1])
        else:
            continue
        if tag not in sources:
            sources.append(tag)
    return {"ok": res.ok, "unmatched": res.unmatched, "sources": sources}


def apply(result: dict, data) -> tuple[dict, list[dict], list[str]]:
    """결과 전체를 대조합니다. (통과한 결과, 대조 기록, 뺀 문장)"""
    terms = _term_values(data)
    log: list[dict] = []
    removed: list[str] = []
    out = dict(result)
    claims = []
    for c in result.get("주장") or []:
        keys = list(dict.fromkeys(KEY.findall(c.get("문장", "")) + [str(k) for k in c.get("근거") or []]))
        v = check_text(c.get("문장", ""), keys, data, terms)
        log.append({"문장": c.get("문장", ""), **v})
        if v["ok"]:
            claims.append({**c, "출처": v["sources"]})
        else:
            removed.append(c.get("문장", ""))
    out["주장"] = claims
    for field in ("핵심진단", "점수이유"):
        t = str(result.get(field) or "")
        v = check_text(t, KEY.findall(t), data, terms)
        if not v["ok"]:
            removed.append(t)
            out[field] = "(Verifier 대조에서 맞지 않는 수치가 있어 생략)"
            log.append({"문장": t, **v})
    for field in ("긍정요인", "리스크요인", "미확인", "다음점검", "스스로질문"):
        kept = []
        for t in result.get(field) or []:
            v = check_text(str(t), KEY.findall(str(t)), data, terms)
            (kept.append(t) if v["ok"] else removed.append(str(t)))
            if not v["ok"]:
                log.append({"문장": str(t), **v})
        out[field] = kept
    return out, log, removed
