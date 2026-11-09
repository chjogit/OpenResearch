"""에이전트 200자 요약(#64, 계약 r4-1.5 `summary200`). 오케스트레이터(SW)·사용자가 에이전트 결과를 한눈에 받는 짧은 글.

구성: [핵심 관찰 1~2개 + 가장 중요한 미확보 1개] + [20거래일 전망 방향].
- 뒤쪽 전망 문장은 코드가 만든다(방향·판정 문구는 outlook 상수 그대로, LLM 이 바꾸지 못함). 앞쪽 관찰만 LLM 이 쓴다.
- 숫자는 장부 키({F1})로만 쓰고 검사를 통과한 뒤 값으로 채운다(공백 포함 200자는 값을 채운 뒤 기준).
- 검사에 걸리거나 200자를 넘으면 더 줄여 1회 다시 → 그래도 안 되면 규칙 기반 요약(장부 값 1개 + 전망)으로 대체하고 method 로 표시.
- 빈 요약은 만들지 않는다.
"""
from __future__ import annotations

import re
from typing import Any

MAX_CHARS = 200
# 장부 키(L1·S19·T1081·F18·M7)·노드·사건 번호. 분기 표기(Q3·H1)는 제외
INTERNAL_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(?!Q[1-4](?![0-9])|H[12](?![0-9]))[A-Z]\d{1,5}(?![0-9])|Point-in-Time|(?<![A-Za-z])CAR(?![A-Za-z])")
KEY_NOTE_RE = re.compile(r"\s*[（(]?\b[A-Z]\d{1,5}(?:[·,\s]+[A-Z]\d{1,5})*[)）]?")


def strip_codes(text: str) -> str:
    """문장 속 장부 키 표기(예: '(T1081·T1082)')를 지운다. 값은 이미 채워져 있으니 키 표기만 군더더기다."""
    return re.sub(r"\s{2,}", " ", INTERNAL_CODE_RE.sub("", KEY_NOTE_RE.sub("", text))).strip()
METHOD_LABEL = {
    "node-rule": "노드 결과 규칙 요약(질의응답은 노드만 실행해 LLM 요약 없음)","llm": "LLM 요약", "llm-retry": "LLM 요약(줄여 다시 씀)", "llm-trim": "LLM 요약(검사를 통과한 앞 문장만 남김)", "rule": "규칙 기반 요약(LLM 요약이 검사를 통과하지 못해 대체)"}

SYSTEM = (
    "당신은 투자 분석 에이전트의 결과를 오케스트레이터에게 넘길 요약을 쓰는 보조자입니다. "
    "아래 '재료'만 쓰고 새 사실·숫자를 만들지 마십시오. 숫자는 재료에 있는 {키}(예: {F1})로만 쓰고 직접 숫자를 쓰지 마십시오. "
    "전망 근거 문장은 코드가 앞에 따로 붙입니다. 그것과 다른 핵심 관찰 1개와, 있으면 가장 중요한 미확보 1개를 한국어 평서문으로 씁니다. "
    "매수·매도·보유·추천 같은 결론, 가격 수준·가격 전망, 내부 코드(N05·D1 등)는 쓰지 않습니다. 20거래일 전망은 코드가 따로 붙이니 쓰지 않습니다. "
    '출력은 JSON 하나: {"요약": "..."}'
)


def outlook_tail(contract: dict) -> str:
    """전망 방향(+사유). 과거 검증 판정은 사용자가 읽는 요약에 쓰지 않는다(#73: 성능 탭·계약 hitRate 에만). 문구는 계약의 전망 블록 값 그대로."""
    ol = contract.get("outlook")
    if not ol:
        return ""
    label = ol["directionLabel"] + (f"({ol['reason']})" if ol.get("reason") else "")
    return f"20거래일 전망: {label}."


NO_SIGNAL_NOTE = "전망 근거인 {names} 값을 확보하지 못해 신호를 계산하지 못했습니다."


def driver_text(outlook: dict | None, budget: int, reserve: int = 45) -> str:
    """전망에 쓴 신호 문장(코드가 장부 값으로 만든 문장). 에이전트 4=외국인·기관 순매수 강도, 6=감성 변화, 3=환율·금리 변화와 상관.
    기준을 넘은 신호를 먼저, 그다음 기준 미달 신호. 첫 신호는 항상, 다음 신호는 LLM 문장 자리(reserve)가 남을 때만. 계산된 신호가 없으면 그 사실을 짧게."""
    from .notation import fix_notation

    sigs = [s for s in (outlook or {}).get("signals") or [] if s.get("state") != "missing" and s.get("text")]
    if not sigs:
        names = "·".join(s["name"] for s in (outlook or {}).get("rule", {}).get("signals") or [])
        return NO_SIGNAL_NOTE.format(names=names or "신호") if outlook else ""
    sigs.sort(key=lambda s: s["state"] == "neutral")
    out = ""
    for s in sigs:
        t = fix_notation(str(s["text"]).strip().rstrip(".")) + "."
        if INTERNAL_CODE_RE.search(t) or "{" in t or _banned(t):
            continue
        nxt = f"{out} {t}".strip()
        if len(nxt) > (budget if not out else budget - reserve):
            break
        out = nxt
    return out


def _banned(text: str) -> bool:
    from . import outlook

    return bool(outlook.problems(text))


def _claim_texts(result: dict) -> list[str]:
    out = [c.get("문장", "") for c in result.get("주장") or [] if isinstance(c, dict)]
    return [t for t in out if t]


def material(result: dict, data: Any, contract: dict | None = None) -> tuple[str, str | None]:
    """LLM 에 주는 재료 문자열과 가장 중요한 미확보 1개. 전망 근거 신호 문장은 코드가 앞에 붙이므로 재료에 넣지 않는다."""
    lines = [f"핵심진단: {result.get('핵심진단', '')}"] if result.get("핵심진단") else []
    lines += [f"- {t}" for t in _claim_texts(result)[:4]]
    gap = next((str(x) for x in result.get("미확인") or []), None)
    if gap:
        lines.append(f"미확보(가장 중요): {gap}")
    return "\n".join(lines), gap


def _problems(raw: str, data: Any, budget: int) -> tuple[list[str], str]:
    """원문(키 포함) 검사 → (문제 목록, 값을 채운 문장)."""
    from . import contract as contract_mod
    from . import llm as llm_mod
    from . import outlook

    probs = list(llm_mod.sentence_problems(raw, llm_mod._valid_keys(data), llm_mod.label_terms(data)))
    probs += [f"금지 표현 {w}" for w in outlook.problems(raw)]
    text = contract_mod.plain(raw, data).strip()
    if INTERNAL_CODE_RE.search(re.sub(r"\{[A-Z]\d+\}", "", raw)) or INTERNAL_CODE_RE.search(text):      # 키({L1})는 값으로 바뀌므로 키를 뺀 원문과 값을 채운 글을 본다
        probs.append("내부 코드 노출")
    if len(text) > budget:
        probs.append(f"{len(text)}자 > {budget}자")
    if not text:
        probs.append("빈 요약")
    return probs, text


def _ask(model: Any, msgs: list) -> str | None:
    from . import llm as llm_mod

    parsed = llm_mod.parse_json(llm_mod.invoke(model, msgs).content)
    text = (parsed or {}).get("요약") if isinstance(parsed, dict) else None
    return str(text).strip() if text else None


def _llm_text(model: Any, result: dict, data: Any, budget: int, contract: dict | None = None) -> tuple[str | None, str | None]:
    """(요약, 방식). 실패하면 (None, None)."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    mat, _ = material(result, data, contract)
    if model is None or not mat:
        return None, None
    msgs = [SystemMessage(content=SYSTEM),
            HumanMessage(content=f"재료:\n{mat}\n\n한두 문장만 쓰십시오. {{키}}는 최대 3개이고 키 하나는 값으로 바뀌면 5~12자가 됩니다. 값을 채운 뒤 공백 포함 {budget}자 이내여야 하니 설명 글자는 {max(budget - 36, 20)}자 안팎으로 짧게 쓰십시오.")]
    try:
        raw = _ask(model, msgs)
        for attempt in range(2):
            if raw is None:
                return None, None
            probs, text = _problems(raw, data, budget)
            if not probs:
                return text, "llm" if attempt == 0 else "llm-retry"
            if attempt == 1:
                return _trim(raw, data, budget)
            msgs += [AIMessage(content=f'{{"요약": "{raw}"}}'), HumanMessage(content=(
                "다음 문제가 있습니다. 같은 재료만 써서 더 짧게 고친 JSON 하나만 다시 출력하십시오.\n" + "\n".join(f"- {p}" for p in probs[:6])))]
            raw = _ask(model, msgs)
    except Exception:  # noqa: BLE001  호출 실패는 규칙 기반 요약으로
        return None, None
    return None, None


def _trim(raw: str, data: Any, budget: int) -> tuple[str | None, str | None]:
    """줄여 다시 써도 길거나 일부 문장이 검사에 걸리면: 검사를 통과한 문장만 앞에서부터 예산 안에서 남긴다. 하나도 없으면 (None, None)."""
    kept = ""
    for sent in re.split(r"(?<=[.!?])\s+", raw.strip()):
        probs, text = _problems(sent, data, 10 ** 6)
        if probs or not text:
            continue
        nxt = f"{kept} {text}".strip()
        if len(nxt) > budget:
            break
        kept = nxt
    return (kept, "llm-trim") if kept else (None, None)


def rule_text(result: dict, contract: dict, data: Any, budget: int) -> str:
    """규칙 기반 대체: 장부 값이 있는 첫 주장 문장 1개(길이에 맞는 것). 없으면 전망 장부 항목 1개, 그것도 없으면 상태 문장."""
    from . import contract as contract_mod

    for raw in _claim_texts(result):
        if re.search(r"\{[A-Z]\d+\}", raw):
            text = contract_mod.plain(raw, data).strip()
            if text and len(text) <= budget and not INTERNAL_CODE_RE.search(text):
                return text
    for v in ((contract.get("outlook") or {}).get("ledger") or {}).values():
        text = f"{v['label']} {v['display']}"
        if len(text) <= budget:
            return text
    return f"{data.name}: 요약에 쓸 수 있는 핵심 관찰을 확보하지 못했습니다."[:budget]


def make_brief(out: dict, data: Any, model: Any = None) -> dict:
    """계약에 붙일 {summary200, summary200Method}. 항상 비어 있지 않고 MAX_CHARS 이하."""
    contract = out["contract"]
    tail = outlook_tail(contract)
    budget = MAX_CHARS - (len(tail) + 1 if tail else 0)
    result = out.get("result") or {}
    driver = driver_text(contract.get("outlook"), budget)
    rest = budget - len(driver) - 1 if driver else budget
    text, method = (_llm_text(model, result, data, rest, contract) if rest >= 45 else (None, None))
    if driver:
        text, method = (f"{driver} {text}" if text else driver), (method or "rule")
    elif not text:
        text, method = rule_text(result, contract, data, budget), "rule"
    full = f"{text} {tail}".strip()
    if len(full) > MAX_CHARS:     # 방어선: 전망 문구가 예상보다 길 때 앞쪽 관찰을 자름
        full = f"{text[:max(MAX_CHARS - len(tail) - 2, 0)].rstrip()}… {tail}".strip()[:MAX_CHARS]
    return {"summary200": full, "summary200Method": method}
