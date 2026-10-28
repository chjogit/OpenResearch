"""에이전트 1의 '제작 기준' 연결 (모두의 리서치 P01 거시경제 상세 개발기획서 v1.0, 2026-10-28).

기준 문서를 에이전트 1의 제작 기준으로 둡니다. 기존 기능은 그대로 두되, 기준과 맞지 않는 출력은 '참고용'으로
낮춰 핵심 근거로 쓰지 않게 합니다 (사용자 지시 3-1).

이 모듈이 하는 일
1. 등급(tier)과 결과 종류 (문서 5장): 장부 항목마다 core(P01 기준 부합) / reference(참고용)와
   네 결과 종류(관측·공시 민감도·과거 관계·실적 예측·시나리오) 중 하나를 붙입니다.
2. 질문 계약 P01Plan (문서 3장 Planner, 6장 P01-F01): 질문을 관측/노출/예측/시나리오/인과 과업으로 나누고,
   과업별로 답함·보류·요청 안 함 상태와 보류 사유를 냅니다. 인과 요청은 항상 CAUSAL_UNIDENTIFIED 로 보류.
3. 상태 코드 (문서 23.1): MISSING_VINTAGE, STALE_CORE_INPUT, MODEL_NOT_APPROVED, OUT_OF_SUPPORT 등.
4. 분기 자료 점검 (문서 9.1·9.3, P01-F03): 단독분기 매출의 급변·결측을 '자료 검토 필요'로 표시 (차단은 아님).
5. 세 줄 요약 (문서 20.2 상단 답변): 확인한 사실 / 조건부 예측 / 아직 답 못한 부분.

기준과 맞지 않아 참고용으로 낮춘 것 (이유)
- 주가-거시 동조성(상관·베타): P01 은 기업 실적·노출이 대상. 주가 관계는 P04(기술) 영역이고 노출이 아님 (19장).
- 반도체 수출·업종 원자재 변수: '산업 통제' 변수는 P02 협의 후 추가 (8.1). 지금은 업황 참고치.
- 시장 기준선 ETF 수익률: 가격 정보라 P01 범위 밖. 맥락 참고치.
- 업종 기본값으로 정한 노출 등급: 공시 확인 전 추정치 (8.1 '수출비중을 순외화노출로 대체 금지').
"""
from __future__ import annotations

import re
from datetime import date, timedelta

STANDARD = "모두의리서치 P01 거시경제 상세 개발기획서 v1.0 (2026-10-28)"
POLICY_VERSION = "p01-standard-v1"

# 장부 group → (등급, 결과 종류)
GROUP_TIER: dict[str, tuple[str, str]] = {
    "거시 지표": ("core", "관측"),
    "금리 일정": ("core", "관측"),
    "거시 이상 점검": ("core", "관측(이상 점검)"),
    "노출 근거": ("core", "공시 민감도"),
    "실적 예측(기준선)": ("core", "실적 예측"),
    "분기 자료 점검": ("core", "관측(자료 품질)"),
    "시나리오(공시 정적 환산)": ("core", "시나리오"),
    "동조성": ("reference", "과거 관계(주가, P01 범위 밖)"),
    "수출": ("reference", "관측(산업 통제, P02 협의 전)"),
    "업종 변수": ("reference", "관측(산업 통제, P02 협의 전)"),
    "시장 기준선(ETF·참고)": ("reference", "관측(시장 가격, P01 범위 밖)"),
}
DEFAULT_TIER = ("core", "관측")
TIER_LABEL = {"core": "P01 기준", "reference": "참고용(P01 기준 밖)"}

STATUS_TEXT = {
    "MISSING_VINTAGE": "당시 이용가능 증거(수정 이력) 없음 → 거시 관측은 D1 사후 탐색 등급",
    "QUARTER_MAPPING_CONFLICT": "누적/기간/정정 연결 충돌 또는 분기 자료 없음",
    "QUARTER_REVIEW": "단독분기 값의 급변 → 원문 대조 필요 (차단 아님)",
    "STALE_CORE_INPUT": "핵심 통계가 오래됨",
    "MODEL_NOT_APPROVED": "승인된 학습모델 없음 → 기준선만 제공",
    "OUT_OF_SUPPORT": "공시 범위 밖 충격 → 숫자 보류",
    "UNIT_AMBIGUOUS": "%/%p 단위가 모호함 → 숫자 보류",
    "MISSING_DISCLOSURE": "공시 민감도 미수집 → 시나리오 숫자 보류",
    "CAUSAL_UNIDENTIFIED": "인과 식별 불충분 → 인과 부분 보류",
    "ANOMALY": "거시 입력이 과거 정상 범위 밖 → 해석 전 확인",
}

CAUSAL_RE = re.compile(r"때문에|덕분에|탓에|인과|효과로|로 인해|영향으로 인해")
FORECAST_RE = re.compile(r"다음\s*분기|전망|예측|예상\s*매출|매출\s*(은|이)?\s*얼마")
SCENARIO_RE = re.compile(r"(환율|원달러|금리|이자율)[^.?!]{0,10}\d")


# ---------------------------------------------------------------- 1. 등급·결과 종류

def tier_of(group: str | None) -> tuple[str, str]:
    return GROUP_TIER.get(group or "", DEFAULT_TIER)


def annotate(f) -> dict:
    """장부 항목마다 tier·result_type 을 붙이고 개수를 돌려줍니다."""
    n = {"core": 0, "reference": 0}
    for it in f.items.values():
        tier, rtype = tier_of(it.get("group"))
        it["tier"], it["result_type"] = tier, rtype
        n[tier] += 1
    return n


def reference_keys(f) -> set[str]:
    return {k for k, it in f.items.items() if it.get("tier") == "reference"}


def core_only(keys, f) -> bool:
    """키 목록에 참고용이 아닌 키가 하나라도 있는가 (핵심 주장은 P01 기준 근거가 하나 이상 있어야 함)."""
    ks = [k for k in keys or [] if k in f.items]
    return not ks or any(f.items[k].get("tier") != "reference" for k in ks)


# ---------------------------------------------------------------- 2. 질문 계약

def plan(question: str | None, focus: list[str] | None, scenario: str | None, as_of: str) -> dict:
    """P01Plan: 어떤 과업을 실행하고 무엇을 보류하는지 실행 전에 정합니다."""
    q = " ".join(x for x in (question or "", scenario or "") if x)
    asked = {
        "관측": True,  # 기준일 거시 관측은 항상 제공
        "노출": True,  # 공시 노출 지도는 P01 필수 기능(F04)이라 질문과 무관하게 항상 제공
        "예측": bool(FORECAST_RE.search(q)) or not q,  # 질문이 없으면 기본 분석에 기준선 예측 포함
        "시나리오": bool(scenario) or bool(SCENARIO_RE.search(q)),
        "인과": bool(CAUSAL_RE.search(q)),
    }
    origin = f"{as_of}T23:59:59+09:00"
    return {"standard": STANDARD, "policy": POLICY_VERSION, "question": question, "scenario_text": scenario,
            "focus": list(focus or []), "origin": origin, "metric": "revenue (연결, KRW)", "tasks": asked}


def finalize_plan(p: dict, *, vintage: dict | None, forecast: dict | None, scenarios: list[dict] | None,
                  anomalies: list[dict] | None, quarter: dict | None, stale: list[str] | None = None) -> dict:
    """계산이 끝난 뒤 과업별 상태와 상태 코드를 채웁니다."""
    codes: list[str] = []
    tasks = {}
    if vintage and vintage.get("vintage") == "missing":
        codes.append("MISSING_VINTAGE")
    if stale:
        codes.append("STALE_CORE_INPUT")
    tasks["관측"] = {"state": "answered", "grade": (vintage or {}).get("grade") or "D1"}
    tasks["노출"] = {"state": "answered", "note": "공시 민감도만 숫자, 업종 기본값 등급은 참고용"}
    if p["tasks"]["예측"]:
        fc = forecast or {}
        fcodes = list(fc.get("status") or [])
        codes += fcodes
        tasks["예측"] = {"state": "answered" if fc.get("pick") else "held", "codes": fcodes,
                        "target": fc.get("target"), "model": fc.get("model"),
                        "note": "기준선만(B0/B1), 거시 변수 미사용 → '거시 영향 예측' 아님"}
    else:
        tasks["예측"] = {"state": "not_requested"}
    if p["tasks"]["시나리오"]:
        sc = scenarios or []
        sc_codes = sorted({c for r in sc for c in r.get("codes") or []})
        codes += sc_codes
        ok = [r for r in sc if r.get("status") == "ok"]
        tasks["시나리오"] = {"state": "answered" if ok else "held", "codes": sc_codes, "n": len(sc), "ok": len(ok),
                          "note": "공시 민감도의 정적 환산만. 매출 예측에 더하지 않음"}
        if not sc:
            tasks["시나리오"]["reason"] = "시나리오 표현을 읽지 못함 (예: '환율 5% 상승, 금리 0.5%p 하락')"
    else:
        tasks["시나리오"] = {"state": "not_requested"}
    if p["tasks"]["인과"]:
        codes.append("CAUSAL_UNIDENTIFIED")
        tasks["인과"] = {"state": "held", "codes": ["CAUSAL_UNIDENTIFIED"],
                        "note": "조건부 비교와 인과효과를 분리. 인과 부분만 보류하고 관측·시나리오는 답함"}
    else:
        tasks["인과"] = {"state": "not_requested"}
    if any(a.get("state") == "abnormal" for a in anomalies or []):
        codes.append("ANOMALY")
    if quarter and quarter.get("review"):
        codes.append("QUARTER_REVIEW")
    codes = list(dict.fromkeys(codes))
    return {**p, "tasks": tasks, "status_codes": codes,
            "held_reasons": [f"{c}: {STATUS_TEXT.get(c, c)}" for c in codes],
            "recheck_conditions": recheck(codes)}


def recheck(codes: list[str]) -> list[str]:
    out = []
    if "MODEL_NOT_APPROVED" in codes:
        out.append("승인 모델 등록(기준선 대비 5% 이상 개선·거시 추가 3% 이상 개선 확인) 후 예측 재실행")
    if "MISSING_VINTAGE" in codes:
        out.append("거시 계열의 공표 시각·수정 이력 수집 후 D2(과거 시점 평가)로 승격")
    if "OUT_OF_SUPPORT" in codes:
        out.append("공시 충격 폭 이내로 가정을 줄이거나 공시 정적 계산 범위만 확인")
    if "QUARTER_REVIEW" in codes:
        out.append("급변 분기의 DART 원문(누적/단독) 대조")
    return out


# ---------------------------------------------------------------- 4. 분기 자료 점검

QOQ_LIMIT = 0.5     # 직전 분기 대비 ±50% 넘게 변하면 검토
YOY_LIMIT = 1.0     # 전년 동기 대비 2배 넘게 변하면 검토


def quarter_check(f, rows: list[dict] | None, cid, as_of: str, group: str = "분기 자료 점검") -> dict:
    """기준일에 공시된 이 기업 단독분기 매출의 연속성·급변을 점검합니다. 차단하지 않고 검토 필요만 표시."""
    from .forecast import known as avail

    cut = date.fromisoformat(as_of)
    mine = sorted([r for r in rows or [] if r.get("c") == cid and avail(r) <= cut], key=lambda r: str(r["pe"]))
    out = {"n": len(mine), "review": [], "gaps": 0}
    if not mine:
        f.gap("단독분기 매출 이력", "기준일에 공시된 분기 매출 없음 (QUARTER_MAPPING_CONFLICT)")
        return out
    for a, b in zip(mine, mine[1:]):
        days = (date.fromisoformat(str(b["pe"])[:10]) - date.fromisoformat(str(a["pe"])[:10])).days
        if not 80 <= days <= 100:
            out["gaps"] += 1
    for i in range(1, len(mine)):
        a, b = float(mine[i - 1]["v"]), float(mine[i]["v"])
        if a > 0 and abs(b / a - 1) > QOQ_LIMIT:
            out["review"].append({"pe": str(mine[i]["pe"])[:10], "kind": "직전 분기 대비", "ratio": b / a})
        if i >= 4 and float(mine[i - 4]["v"]) > 0 and b / float(mine[i - 4]["v"]) - 1 > YOY_LIMIT:
            out["review"].append({"pe": str(mine[i]["pe"])[:10], "kind": "전년 동기 대비", "ratio": b / float(mine[i - 4]["v"])})
    last = mine[-1]
    f.add("공시된 단독분기 매출 이력", len(mine), "개", str(last["pe"])[:10], "core.financial_quarter (revenue)",
          kind="calc", group=group,
          note="DART 누적값 차감(Q2=반기−Q1, Q4=연간−3분기) 결과. 보고서 접수일(없으면 45·90일) 뒤부터 이용")
    if out["gaps"]:
        f.gap("분기 연속성", f"이력 중 끊긴 분기 {out['gaps']}곳 → 기준선 계산에서 제외될 수 있음")
    if out["review"]:
        last_r = out["review"][-1]
        k = f.add(f"단독분기 매출 급변({last_r['pe']}, {last_r['kind']})", (last_r["ratio"] - 1) * 100, "%chg",
                  last_r["pe"], "core.financial_quarter (revenue)", kind="calc", group=group,
                  note="자료 오류인지 실제 업황 변화인지 원문 대조 전 판단 보류")
        if k:
            f.flag(f"분기 자료 검토 필요: 단독분기 매출 급변 ({{{k}}}). 기준선·구간 해석 전 원문 대조")
    return out


# ---------------------------------------------------------------- 5. 세 줄 요약

def summary3(f, p: dict) -> dict:
    """문서 20.2 상단 답변: 확인한 사실 / 조건부 예측 / 아직 답 못한 부분. 숫자는 장부 키로만."""
    def first(group, pred=lambda it: True):
        for k, it in f.items.items():
            if it.get("group") == group and pred(it):
                return k
        return None

    facts_line = []
    for lab in ("원/달러 환율 3개월 변화율", "한국 기준금리 12개월 변화"):
        k = f.key_of(lab)
        if k:
            facts_line.append(f"{f.items[k]['label']} {{{k}}}")
    k_exp = first("노출 근거", lambda it: it.get("kind") == "회사 공시")
    if k_exp:
        facts_line.append(f"{f.items[k_exp]['label']} {{{k_exp}}}")
    t = p.get("tasks", {})
    pred = []
    if (t.get("예측") or {}).get("state") == "answered":
        k_pick = first("실적 예측(기준선)", lambda it: "선택된 기준선" in (it.get("note") or ""))
        k_lo = first("실적 예측(기준선)", lambda it: it["label"].endswith("하한"))
        k_hi = first("실적 예측(기준선)", lambda it: it["label"].endswith("상한"))
        if k_pick:
            pred.append(f"{f.items[k_pick]['label']} {{{k_pick}}}"
                        + (f", 80% 구간 {{{k_lo}}}~{{{k_hi}}} (보정 미검증)" if k_lo and k_hi else ""))
    for k, it in f.items.items():
        if it.get("group") == "시나리오(공시 정적 환산)":
            pred.append(f"{it['label']} {{{k}}}")
    held = [h.split(":")[0] for h in p.get("held_reasons") or []]
    return {
        "확인한 사실": "; ".join(facts_line) or "기준일 거시 관측만 확인",
        "조건부 예측": "; ".join(pred) or "제공하지 않음 (요청 없음 또는 보류)",
        "아직 답 못한 부분": ", ".join(held) or "없음",
    }


def plan_md(p: dict) -> list[str]:
    """보고서에 넣는 과업표."""
    names = {"answered": "답함", "held": "보류", "not_requested": "요청 없음"}
    out = ["", f"**P01 과업 계약** ({POLICY_VERSION}, 예측 시점 {p.get('origin')})", "",
           "| 과업 | 상태 | 비고 |", "| --- | --- | --- |"]
    for name, t in (p.get("tasks") or {}).items():
        note = t.get("note") or t.get("grade") or t.get("reason") or ""
        codes = ", ".join(t.get("codes") or [])
        out.append(f"| {name} | {names.get(t.get('state'), t.get('state'))} | {(codes + ' · ') if codes else ''}{note} |")
    if p.get("held_reasons"):
        out += ["", "보류·주의 코드: " + "; ".join(p["held_reasons"])]
    return out


def fallback_headline(data, default: str) -> str:
    """LLM 핵심진단이 검사·Verifier 에서 빠졌을 때 쓰는 코드 요약 (장부 키만 있어 대조를 통과함).
    에이전트 1(p01)·3(p03) 공통. 세 줄 요약이 없으면 default."""
    px = (getattr(data, "extra", None) or {}).get("p01") or (getattr(data, "extra", None) or {}).get("p03")
    s = (px or {}).get("summary") or {}
    first = s.get("확인한 사실")
    if not first or "{" not in first:
        return default
    held = s.get("아직 답 못한 부분")
    return f"(규칙 요약) 확인한 사실: {first}" + (f". 보류: {held}" if held and held != "없음" else "")
