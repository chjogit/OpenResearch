"""Verifier 연동 (기초기획서 R2 2.2 'Verifier 통과 필수', 3.4 'fact_source_verifier').

팀 공용 `agent/verifier/fact_source_verifier.py` 의 verify() 로 최종 문장을 한 번 더 검사합니다.
- 장부 키를 값으로 바꾼 '사람이 읽는 문장'에서 숫자를 뽑아, 그 문장이 인용한 장부 항목(도구 실행 기록)과 1:1 대조
- 통과한 문장에는 인용한 항목의 출처 태그를 붙임: [출처: Neon core.macro_obs ECOS_USDKRW, 2026-10-24]
- 통과하지 못한 문장은 최종 출력에서 뺌 (앞 단계의 코드 검사와 별개로 두 번째 관문)

장부 항목 이름에 든 숫자(예: '52주', '250일')는 값이 아니라 용어이므로 대조 대상 값에 함께 넣습니다.

기초기획서 R4 4.4 'Verifier: 수치 대조 + 출처 태그 + claimId/evidenceId 연결'
- 대조 기록 한 줄마다 claimId(주장 ID)와 evidenceIds(근거 ID)를 남깁니다. 통과하지 못한 주장도 ID 와 함께 기록됩니다.
- 주장(주장)과 반대 근거(반대근거)를 같은 방식으로 대조합니다.
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
DATE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?|\d{4}\.\d{1,2}(?:\.\d{1,2})?|FY\d{4}")
# 값이 아니라 식별자인 숫자: 0으로 시작하는 번호(마이그레이션 021, 종목코드 005930), 스키마·테이블 이름 속 숫자
IDENT = re.compile(r"(?<![\d.,])0\d+(?![\d.,%])|\b[a-z_]+\.[a-z_]*\d+[a-z_\d]*\b|\bsql/\d+\b")
LABEL_NUM = re.compile(r"\d+(?:\.\d+)?")
TOOL = "ch_agents"
CLAIM_FIELDS = ("주장", "반대근거")


from .contract import assign_claim_ids, evidence_ids, evidence_map  # noqa: E402
from .contract import doc_tag as _doc_tag  # noqa: E402
from .contract import source_tag as _source_tag  # noqa: E402


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
    masked = IDENT.sub(lambda m: " " * len(m.group(0)), DATE.sub(lambda m: " " * len(m.group(0)), shown))
    res = _verify(masked,
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
    emap = evidence_map(data)
    log: list[dict] = []
    removed: list[str] = []
    out = assign_claim_ids(result)
    for field in CLAIM_FIELDS:
        claims = []
        for c in out.get(field) or []:
            keys = list(dict.fromkeys(KEY.findall(c.get("문장", "")) + [str(k) for k in c.get("근거") or []]))
            v = check_text(c.get("문장", ""), keys, data, terms)
            ev = evidence_ids(keys, emap)
            log.append({"claimId": c["claimId"], "구분": field, "문장": c.get("문장", ""), **v, "evidenceIds": ev})
            if v["ok"]:
                claims.append({**c, "출처": v["sources"], "evidenceIds": ev})
            else:
                removed.append(c.get("문장", ""))
        out[field] = claims
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
