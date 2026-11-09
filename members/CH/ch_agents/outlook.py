"""에이전트 3(거시)·4(수급)·6(투자심리·뉴스)의 20거래일 가격 방향 전망 결론 (#54, 계약 r4-1.4).

결론 값(긍정·중립·부정)은 **정해진 규칙**으로만 정합니다. LLM 은 쓰지 않습니다(재현 가능, 과거 기준일로 다시 계산 가능).
규칙은 `docs/OUTLOOK_RULES.md` 에 먼저 적어 두었고, 기준값은 적중률이 높아지도록 조정하지 않습니다(바꾸면 새 규칙 버전 + 다시 측정).

판정 (에이전트 공통):
  신호 = 노드 장부의 값 하나 또는 두 개로 정한 방향(긍정·부정·기준 미달·자료 없음).
  - 계산할 수 있는 신호가 하나도 없으면 중립 (사유: 근거 부족)
  - 긍정 신호와 부정 신호가 함께 있으면 중립 (사유: 혼재)
  - 기준을 넘는 신호가 없으면 중립 (사유: 신호 미약)
  - 한쪽 방향 신호만 있으면 그 방향
금지: 매수·매도·보유·추천·적기, 가격 수준·목표 수준, 증권사 가격 전망 수치. `problems()` 가 문장을 검사합니다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .sentiment_limit import SENT_EVAL_ACCURACY

RULE_VERSION = "outlook-r1"
HORIZON_DAYS = 20
LABEL = {"positive": "긍정", "neutral": "중립", "negative": "부정"}
REASON = {"mixed": "혼재", "insufficient": "근거 부족", "weak": "신호 미약"}
HERE = Path(__file__).resolve().parent
HIT_RATE_PATH = Path(os.environ.get("CH_OUTLOOK_HIT_RATE") or HERE.parent / "outlook" / "hit_rate.json")   # #55 결과 파일 (없으면 '미검증')
MIN_HIT_N = 30            # 적중률을 보여 주는 최소 표본(독립 표본 기준 아님 — 건수 부족이면 '미검증')

ORCHESTRATOR_NOTE = "세 에이전트 결론의 종합은 오케스트레이터(SW) 담당입니다. 이 결론은 매수·매도·보유 판단이나 가격 수준이 아닙니다."

# ---------------------------------------------------------------- 규칙 (기준값은 한 번 정하고 고정: 규칙 버전 outlook-r1)
# kind="direct": 장부 값 v 가 +기준 이상이면 긍정, -기준 이하이면 부정.
# kind="gated" : 변화값 c 와 과거 주가 상관 r 이 모두 기준 이상일 때만 신호, 방향 = 부호(c) × 부호(r).
RULES: dict[int, list[dict[str, Any]]] = {
    4: [
        {"id": "flow_foreign", "kind": "direct", "name": "외국인 20일 순매수 강도", "label": "외국인 20일 순매수 강도(거래대금 대비)", "threshold": 1.0, "unit": "%",
         "pos": "외국인 20일 순매수 강도 {v}: 순매수 우세(규칙 기준 초과)", "neg": "외국인 20일 순매수 강도 {v}: 순매도 우세(규칙 기준 초과)",
         "neu": "외국인 20일 순매수 강도 {v}: 규칙 기준 미달"},
        {"id": "flow_institution", "kind": "direct", "name": "기관 20일 순매수 강도", "label": "기관 20일 순매수 강도(거래대금 대비)", "threshold": 1.0, "unit": "%",
         "pos": "기관 20일 순매수 강도 {v}: 순매수 우세(규칙 기준 초과)", "neg": "기관 20일 순매수 강도 {v}: 순매도 우세(규칙 기준 초과)",
         "neu": "기관 20일 순매수 강도 {v}: 규칙 기준 미달"},
    ],
    6: [
        {"id": "news_tone", "kind": "direct", "name": "뉴스 감성 변화", "label": "뉴스 감성 변화(최근 7일 − 직전 8~30일)", "threshold": 0.10, "unit": "score",
         "pos": "뉴스 감성 변화 {v}: 직전 기준선보다 개선(규칙 기준 초과)", "neg": "뉴스 감성 변화 {v}: 직전 기준선보다 악화(규칙 기준 초과)",
         "neu": "뉴스 감성 변화 {v}: 규칙 기준 미달"},
        {"id": "youtube_tone", "kind": "direct", "name": "유튜브 댓글 감성 변화", "label": "유튜브 댓글 감성 변화(최근 7일 − 직전 8~30일)", "threshold": 0.10, "unit": "score",
         "pos": "유튜브 댓글 감성 변화 {v}: 직전 기준선보다 개선(규칙 기준 초과)", "neg": "유튜브 댓글 감성 변화 {v}: 직전 기준선보다 악화(규칙 기준 초과)",
         "neu": "유튜브 댓글 감성 변화 {v}: 규칙 기준 미달"},
    ],
    3: [
        {"id": "fx", "kind": "gated", "name": "원/달러 환율", "label": "원/달러 환율 3개월 변화율", "corr_label": "주가-원/달러 상관(250일)",
         "threshold": 3.0, "corr_threshold": 0.20, "unit": "%",
         "pos": "원/달러 환율 3개월 변화 {v}와 과거 주가 상관 {r}의 조합이 주가에 유리한 쪽(규칙 기준 초과)",
         "neg": "원/달러 환율 3개월 변화 {v}와 과거 주가 상관 {r}의 조합이 주가에 불리한 쪽(규칙 기준 초과)",
         "neu": "원/달러 환율 3개월 변화 {v}, 과거 주가 상관 {r}: 규칙 기준 미달"},
        {"id": "us10y", "kind": "gated", "name": "미국 10년 국채금리", "label": "미국 10년 국채금리 3개월 변화", "corr_label": "주가-미국 10년 국채금리 상관(250일)",
         "threshold": 0.25, "corr_threshold": 0.20, "unit": "%p",
         "pos": "미국 10년 국채금리 3개월 변화 {v}와 과거 주가 상관 {r}의 조합이 주가에 유리한 쪽(규칙 기준 초과)",
         "neg": "미국 10년 국채금리 3개월 변화 {v}와 과거 주가 상관 {r}의 조합이 주가에 불리한 쪽(규칙 기준 초과)",
         "neu": "미국 10년 국채금리 3개월 변화 {v}, 과거 주가 상관 {r}: 규칙 기준 미달"},
    ],
}
LIMITS = {
    3: "거시 지표는 발표·수정 이력을 보관하지 않아 과거 기준일 재계산 때 당시에 알 수 없던 값이 섞일 수 있음. 기준을 넘는 신호가 드물어 중립이 많음",
    4: "수급 자료는 시세보다 하루 늦게 적재됨(마지막 수급일 기준). 순매수 기록만으로 매수 의도나 정보 보유를 추정하지 않음",
    6: f"감성 점수는 사전 기준선(정확도 {SENT_EVAL_ACCURACY})이며 블로그·카페·뉴스·유튜브 댓글 원문은 14일만 보관해 과거 기준일 재계산이 어려움",
}

# ---------------------------------------------------------------- 금지 표현 검사 (Verifier)
BANNED_WORDS = ("매수 추천", "매도 추천", "목표주가", "목표 주가", "목표가", "비중 확대", "비중 축소", "추천", "적기", "보유하", "사세요", "파세요", "권유")
BANNED_RE = re.compile(r"(?<!순)(매수|매도)\s*(하세요|하십시오|의견|권고|적기|시점|타이밍|를\s*권|가\s*바람직)|"
                       r"(오를|내릴|상승할|하락할|떨어질)\s*(것|전망|가능성)|\d[\d,.]*\s*(만|천)?\s*원\s*(까지|선)|(증권사|애널리스트|리서치).{0,24}(전망|예상|상향|하향|제시)")


def problems(text: str) -> list[str]:
    """문장 속 금지 표현. 비어 있으면 통과."""
    out = [w for w in BANNED_WORDS if w in text]
    out += [m.group(0) for m in BANNED_RE.finditer(text)]
    return out


# ---------------------------------------------------------------- 계산

def _find(items: dict[str, dict], label: str) -> tuple[str | None, dict | None]:
    for k, v in items.items():
        if v.get("label") == label and v.get("value") is not None:
            return k, v
    return None, None


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def _evaluate(rule: dict, items: dict[str, dict]) -> dict:
    """신호 하나 → {id, name, state, keys, template}. state: positive | negative | neutral(기준 미달) | missing(자료 없음)."""
    k, it = _find(items, rule["label"])
    out = {"id": rule["id"], "name": rule["name"], "keys": [], "state": "missing", "template": None}
    if it is None:
        out["template"] = f"{rule['name']}: 장부에 값이 없어 신호를 계산하지 못함"
        return out
    v = float(it["value"])
    if rule["kind"] == "direct":
        state = "positive" if v >= rule["threshold"] else "negative" if v <= -rule["threshold"] else "neutral"
        out.update(keys=[k], state=state, template=rule[{"positive": "pos", "negative": "neg", "neutral": "neu"}[state]].format(v="{" + k + "}"))
        return out
    kr, ir = _find(items, rule["corr_label"])
    if ir is None:
        out["template"] = f"{rule['name']}: 과거 주가 상관이 장부에 없어 신호를 계산하지 못함"
        return out
    r = float(ir["value"])
    if abs(v) >= rule["threshold"] and abs(r) >= rule["corr_threshold"]:
        state = "positive" if _sign(v) * _sign(r) > 0 else "negative"
    else:
        state = "neutral"
    out.update(keys=[k, kr], state=state, template=rule[{"positive": "pos", "negative": "neg", "neutral": "neu"}[state]].format(v="{" + k + "}", r="{" + kr + "}"))
    return out


def render_text(template: str, items: dict[str, dict]) -> str:
    return re.sub(r"\{([A-Z]\d+)\}", lambda m: items[m.group(1)]["text"] if m.group(1) in items else m.group(0), template)


def rule_description(agent_no: int) -> dict:
    """계약에 싣는 규칙 요약(기준값 포함). 문장에는 숫자를 쓰지 않고 기준값은 여기에만 둠."""
    sigs = []
    for r in RULES[agent_no]:
        d = {"id": r["id"], "name": r["name"], "kind": r["kind"], "ledgerLabel": r["label"], "threshold": r["threshold"], "unit": r["unit"]}
        if r["kind"] == "gated":
            d.update(corrLabel=r["corr_label"], corrThreshold=r["corr_threshold"], direction="부호(변화) × 부호(과거 주가 상관)")
        sigs.append(d)
    return {"version": RULE_VERSION, "signals": sigs, "decision": "신호가 없으면 중립(근거 부족) · 긍정·부정이 함께 있으면 중립(혼재) · 기준 넘는 신호가 없으면 중립(신호 미약) · 한쪽만 있으면 그 방향",
            "doc": "docs/OUTLOOK_RULES.md"}


def compute(agent_no: int, items: dict[str, dict], as_of: str) -> dict:
    """노드 장부(items)만으로 20거래일 전망 결론을 계산. 같은 장부면 같은 결과(재현 가능)."""
    if agent_no not in RULES:
        raise KeyError(f"전망 결론은 에이전트 3·4·6 만 냅니다: {agent_no}")
    sigs = [_evaluate(r, items) for r in RULES[agent_no]]
    pos = [s for s in sigs if s["state"] == "positive"]
    neg = [s for s in sigs if s["state"] == "negative"]
    computed = [s for s in sigs if s["state"] != "missing"]
    if not computed:
        direction, reason = "neutral", "insufficient"
    elif pos and neg:
        direction, reason = "neutral", "mixed"
    elif pos:
        direction, reason = "positive", None
    elif neg:
        direction, reason = "negative", None
    else:
        direction, reason = "neutral", "weak"
    texts = [s["template"] for s in sigs]
    bad = [p for t in texts for p in problems(t)]
    if bad:                      # 규칙 문장이 금지 표현에 걸리면 결론을 내지 않음(방어선: 정상 규칙에서는 생기지 않음)
        direction, reason = "neutral", "insufficient"
    used = {k for s in sigs for k in s["keys"]}
    ledger = {k: {"label": items[k]["label"], "value": items[k]["value"], "unit": items[k].get("unit"), "display": items[k]["text"],
                  "dataDate": items[k].get("as_of"), "source": items[k].get("source"), "valueType": items[k].get("kind")}
              for k in sorted(used) if k in items}
    return {"agentNo": agent_no, "ruleVersion": RULE_VERSION, "horizonDays": HORIZON_DAYS, "startAfter": as_of,
            "direction": direction, "directionLabel": LABEL[direction], "reasonCode": reason, "reason": REASON.get(reason),
            "signals": [{"id": s["id"], "name": s["name"], "state": s["state"], "keys": s["keys"], "template": s["template"],
                         "text": render_text(s["template"], items)} for s in sigs],
            "positiveFactors": [{"signalId": s["id"], "keys": s["keys"], "template": s["template"], "text": render_text(s["template"], items),
                                 "tag": _factor_tag(s["keys"], items)} for s in pos],
            "negativeFactors": [{"signalId": s["id"], "keys": s["keys"], "template": s["template"], "text": render_text(s["template"], items),
                                 "tag": _factor_tag(s["keys"], items)} for s in neg],
            "ledger": ledger, "rule": rule_description(agent_no), "limit": LIMITS[agent_no], "tag": "Prediction",
            "verification": {"checkedSentences": len(texts), "problems": bad}}


def _factor_tag(keys: list[str], items: dict[str, dict]) -> str:
    return "Computation" if keys and all(items.get(k, {}).get("kind") in ("계산", "대용치") for k in keys) else "Fact"


# ---------------------------------------------------------------- 적중률 (#55 결과 파일 읽기)

SOURCE_MARK = "규칙 기반 20거래일 방향(검증 결과는 성능 탭)"     # 답·카드·요약에는 판정 대신 이 출처 표시만 (#73). 판정은 성능 탭·계약 hitRate 에만
VERDICT_LABEL = {"edge": "기준선 대비 우위 있음", "indistinct": "기준선과 구별 안 됨", "unverified": "미검증"}
VERDICT_NOTICE = {      # 화면·계약·질의응답·시연이 같은 문구를 씀 (한 곳 상수)
    "indistinct": "이 결론은 과거 검증에서 우연과 구별되지 않았습니다 — 판단 근거로 쓰기 어렵습니다.",
    "unverified": "이 결론은 과거 검증을 하지 못했습니다(미검증) — 판단 근거로 쓰기 어렵습니다.",
}


def judge(ci95, rates, n) -> str:
    """판정 규칙(docs/OUTLOOK_BACKTEST.md 5-1): 95% 구간 하한이 기준선 셋(항상 긍정·모멘텀·무작위 50%) 중 최고값보다 커야 '우위 있음'."""
    if not ci95 or not isinstance(n, int) or n < MIN_HIT_N:
        return "unverified"
    best = max([0.5] + [r for r in (rates or {}).values() if isinstance(r, (int, float))])
    return "edge" if ci95[0] > best else "indistinct"


def _verdict_fields(v: str) -> dict:
    return {"verdict": v, "verdictLabel": VERDICT_LABEL[v], "notice": VERDICT_NOTICE.get(v)}


def hit_rate(agent_no: int, path: Path | None = None) -> dict:
    """#55 결과 파일에서 에이전트별 적중률을 읽음. 파일·항목이 없거나 규칙 버전이 다르거나 표본이 적으면 '미검증'."""
    p = path or HIT_RATE_PATH
    base = {"status": "unverified", "rate": None, "n": None, "period": None, "basis": None, "ci95": None, "neutralShare": None, "baselines": None, **_verdict_fields("unverified")}
    if not p.exists():
        return {**base, "reason": "측정 전 (적중률 결과 파일 없음 — #55)"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {**base, "reason": "적중률 결과 파일을 읽지 못함"}
    ent = (doc.get("agents") or {}).get(str(agent_no))
    if not ent:
        return {**base, "reason": "이 에이전트의 적중률 결과 없음"}
    if ent.get("unverified"):
        return {**base, "reason": str(ent["unverified"])}
    if doc.get("ruleVersion") != RULE_VERSION:
        return {**base, "reason": f"측정한 규칙 버전({doc.get('ruleVersion')})이 현재({RULE_VERSION})와 다름"}
    n = ent.get("n")
    if not isinstance(n, int) or n < MIN_HIT_N:
        return {**base, "reason": f"표본 {n}건으로 부족(최소 {MIN_HIT_N}건)"}
    non = ent.get("nonOverlapping") or {}
    rates = {k: v.get("rate") for k, v in (non.get("baselines") or {}).items()} or None
    return {"status": "measured", "rate": ent.get("rate"), "n": n, "period": ent.get("period"), "basis": ent.get("basis"),
            "ci95": ent.get("ci95"), "reason": None, "neutralShare": non.get("neutralShare"), "baselines": rates,
            **_verdict_fields(judge(ent.get("ci95"), rates, n))}


def hit_rate_text(h: dict) -> str:
    if h["status"] != "measured":
        return f"과거 적중률: 미검증 ({h['reason']})"
    # 판정(verdict)은 별도 필드·문구(notice)로 함께 표시
    ci = f", 95% 신뢰구간 {h['ci95'][0]:.0%}~{h['ci95'][1]:.0%}" if h.get("ci95") else ""
    extra = ""
    if h.get("neutralShare") is not None:
        extra += f" · 중립 결론 {h['neutralShare']:.0%}(적중률에서 제외)"
    if h.get("baselines"):
        b = h["baselines"]
        extra += f" · 같은 표본 기준선: 항상 긍정 {b['alwaysPositive']:.1%}, 모멘텀 {b['momentum']:.1%}, 무작위 {b['random']:.0%}"
    return f"과거 적중률 {h['rate']:.1%} ({h['n']}건, {h['period']}, 기준: {h['basis']}{ci}){extra}"
