"""에이전트 3 거시경제·정책: N05 기업별 거시 노출(기본) · N06 거시 시나리오·민감도(확장) (티켓 #24, specs/agent-split.md '노드 상세').

기존 에이전트 1(`agent1_macro.compute`)의 계산을 그대로 쓰고(같은 입력이면 같은 값), 노드 틀(NodeTask/NodeResult)과 태그를 얹습니다.

- N05: 분석 시점에 공표돼 있던 값만 사용(vintage.apply + 도구 계층의 기준일 컷), 공시 재무구조 매핑으로 노출 경로·등급·범위,
  각 항목에 '공시 사실 / 외부 추정' 근거 구분, 미확인·공백 목록. 발표·수정 이력이 없는 지표는 PIT 한계로 표시.
- N06: 사용자가 정한 금리·환율 시나리오를 회사가 공시한 민감도로 선형 환산(공시 충격 폭 안에서만), 반대 조건, 한계.
  숫자는 DB 키(장부)만. 시나리오 환산은 실적 예측·인과효과·확률이 아니며, 거시 변수를 실적 예측의 개선 근거로 쓰지 않습니다.
"""
from __future__ import annotations

import dataclasses
import re

from . import agent1_macro, forecast
from . import scenario as scen_mod
from .asof import cut_future, require_as_of
from .facts import Facts, series_points
from .nodes import Finding, NodeResult, NodeTask, register

# 장부 항목의 근거 구분 (facts.KIND_LABEL 의 한글 라벨 기준)
BASIS = {"회사 공시": "공시 사실", "실측": "외부 지표(실측)", "계산": "계산(코드)", "대용치": "외부 추정(대용치)",
         "예측(기준선)": "외부 추정(기준선)"}
PIT_LIMIT = "거시지표 발표·수정 이력(Point-in-Time) 미보관: 최신값 위주이며 공표일은 보수 규칙으로 추정 (D1 사후 탐색 등급)"
SCENARIO_LIMITS = ("공시 민감도의 선형 환산이며 실적 예측·인과효과·확률이 아님",
                   "공시 충격 폭보다 큰 충격은 선형 외삽이라 숫자를 내지 않음",
                   "헤지 비율·통화 구성 변화는 반영하지 않음")
KEY = re.compile(r"\{([A-Z]\d+)\}")


# ---------------------------------------------------------------- 입력

def clean_inputs(b: dict, as_of: str) -> dict:
    """E3: 거시 시계열·가격·지수에서 기준일 다음 날 이후 관측을 제거합니다(통화정책 일정은 미리 공표되므로 그대로)."""
    as_of = require_as_of(as_of)
    out = dict(b)
    out["series"] = {sid: cut_future(v, as_of, ("d",))[0] for sid, v in (b.get("series") or {}).items()}
    out["index"] = {sym: cut_future(v, as_of, ("d",))[0] for sym, v in (b.get("index") or {}).items()}
    if b.get("price") is not None:
        out["price"] = cut_future(b["price"], as_of, ("d",))[0]
    return out


def available_inputs(b: dict, scenario: str | None = None) -> set[str]:
    have = set()
    if any(series_points(v) for v in (b.get("series") or {}).values()):
        have.add("macro_series")
    if scenario:
        specs, _ = scen_mod.parse(scenario)
        if specs:
            have.add("scenario_assumptions")
    return have


def _ledger(f: Facts) -> dict:
    return {k: {x: v[x] for x in ("label", "value", "unit", "text", "as_of", "source", "kind", "note")} for k, v in f.items.items()}


def _render(text: str, items: dict) -> str:
    return KEY.sub(lambda m: items[m.group(1)]["text"] if m.group(1) in items else m.group(0), text)


def _find(kind: str, text: str, tag: str, keys) -> Finding:
    return Finding(kind=kind, text=text, tag=tag, evidence_links=[k for k in keys if k])


# ---------------------------------------------------------------- N05 기업별 거시 노출

def n05(b: dict, co: dict, as_of: str, focus: list[str] | None = None, computed: dict | None = None) -> NodeResult:
    as_of = require_as_of(as_of)
    c = computed or agent1_macro.compute(b, co, as_of, focus=focus)
    f: Facts = c["facts"]
    items = f.items
    finds: list[Finding] = []
    # ① 공시 사실로 분류되는 장부 항목
    for k, it in items.items():
        if it["kind"] == "회사 공시":
            finds.append(_find("number", f"[공시 사실] {it['label']} {it['text']}", "Fact", [k]))
    # ② 노출 등급 (규칙 기반 해석): 근거 키가 있는 행만 결론, 업종 기본값뿐인 행은 근거 없는 추정이므로 참고(note)
    table = []
    for r in c["exposure"]:
        basis = "공시 사실" if r.get("company") else "외부 추정"
        reasons = "; ".join(_render(x, items) for x in r["reasons"])
        table.append({"variable": r["var"], "level": r["level"], "basis": basis, "path": r["path"], "reasons": reasons,
                      "keys": list(r["keys"]), "focus": bool(r["focus"])})
        text = f"[{basis}] {r['var']} 노출 {r['level']}: {reasons} (경로: {r['path']})"
        finds.append(_find("conclusion" if r["keys"] else "note", text, "Interpretation", r["keys"]))
    vint = c["p01"]["vintage"]
    by_series = {sid: list(days) for sid, days in (vint.get("dropped") or {}).items()}   # {지표: [공표 전이라 뺀 관측일]}
    dropped = sum(len(v) for v in by_series.values())
    pit = {"policy": vint.get("policy"), "dropped": dropped, "dropped_by_series": by_series, "grade": vint.get("grade"),
           "limit": PIT_LIMIT}
    if dropped:
        finds.append(_find("note", f"기준일({as_of})에 아직 공표 전이었던 관측 {dropped}건은 사용하지 않음", "Fact", []))
    unconfirmed = [{"item": p["item"], "status": p["status"], "detail": p["detail"], "why": p["why"]}
                   for p in c["premises"] if p["status"] != "확인"]
    has_company = any(r.get("company") for r in c["exposure"])
    status = "SUCCESS" if has_company else "PARTIAL_SUCCESS"
    return NodeResult(
        status=status, node_id="N05", findings=finds,
        artifacts={"exposure_table": table, "fact_basis": {k: BASIS.get(v["kind"], v["kind"]) for k, v in items.items()},
                   "pit": pit, "unconfirmed": unconfirmed, "gaps": f.gaps, "sector": c["sector"], "ledger": _ledger(f),
                   "basis_legend": BASIS},
        evidence_links=sorted(items), missing_items=[PIT_LIMIT],
        reason=None if has_company else "회사 공시 근거가 없어 업종 기본값 위주(외부 추정)")


# ---------------------------------------------------------------- N06 거시 시나리오·민감도

def n06(b: dict, co: dict, as_of: str, scenario: str | None) -> NodeResult:
    as_of = require_as_of(as_of)
    specs, codes = scen_mod.parse(scenario or "", origin=as_of)
    if not specs:
        return NodeResult(status="DATA_INSUFFICIENT", node_id="N06", missing_items=["scenario_assumptions"],
                          reason="시나리오 가정(금리·환율 변화 폭)이 없음")
    f = Facts("X")
    results = [scen_mod.evaluate(sp, b.get("report")) for sp in specs]
    ok = [r for r in results if r["status"] == "ok"]
    keys = iter(scen_mod.add_facts(f, results, as_of))
    counter_res = []
    for r in ok:   # 반대 조건(counter-factual): 같은 크기의 반대 방향 변화
        sp = r["spec"]
        opp = dataclasses.replace(scen_mod.ScenarioSpec(**sp), change=-sp["change"], raw=f"반대 조건 {sp['raw']}")
        counter_res.append(scen_mod.evaluate(opp, b.get("report")))
    counter_keys = iter(scen_mod.add_facts(f, counter_res, as_of))
    finds: list[Finding] = []
    table = []
    cmap = {id(o): c for o, c in zip(ok, counter_res)}
    for r in results:
        sp = r["spec"]
        row = {"scenario": sp["raw"], "variable": sp["variable"], "change": sp["change"], "unit": sp["unit"], "status": r["status"],
               "codes": r["codes"], "reason": r.get("reason")}
        if r["status"] == "ok":
            k = next(keys)
            d = r["disclosed"]
            kc = next(counter_keys)
            row.update(effect=r["value"], effect_key=k, basis=d["basis"], fiscal_year=d["fy"], disclosed_shock=d["shock"],
                       disclosed_unit=d["unit"], counter_effect=cmap[id(r)].get("value"), counter_key=kc)
            finds.append(_find("number", f"[공시 사실 환산] {f.items[k]['label']} {f.items[k]['text']}", "Computation", [k]))
            if kc:
                finds.append(_find("number", f"[반대 조건] {f.items[kc]['label']} {f.items[kc]['text']}", "Computation", [kc]))
        else:
            finds.append(_find("note", f"시나리오 보류 '{sp['raw']}': {', '.join(r['codes'])} — {r.get('reason', '')}", "Interpretation", []))
        table.append(row)
    for text in SCENARIO_LIMITS:
        finds.append(_find("note", f"한계: {text}", "Interpretation", []))

    # 불확실성: 거시 입력을 쓰지 않은 매출 기준선 구간(참고). 시나리오 환산과 섞어 예측 구간처럼 쓰지 않음
    baseline = None
    try:
        panel = (b.get("panel") or {}).get("rows")
        if panel:
            fc = forecast.company_forecast(panel, co.get("company_id"), as_of)
            bk = forecast.add_facts(f, fc, as_of)
            if bk:
                baseline = {"keys": bk, "note": "거시 변수를 쓰지 않은 매출 기준선·구간(참고). 시나리오 환산값과는 별개"}
    except Exception as exc:  # noqa: BLE001  참고 항목이라 실패해도 시나리오 표는 그대로
        baseline = {"error": f"{type(exc).__name__}"}
    reason = None
    if not ok:
        reason = "SCENARIO_UNSUPPORTED: " + "; ".join(f"{r['spec']['raw']} → {', '.join(r['codes'])}" for r in results)
    return NodeResult(
        status="SUCCESS" if ok and len(ok) == len(results) else "PARTIAL_SUCCESS", node_id="N06", findings=finds,
        artifacts={"scenario_table": table, "limits": list(SCENARIO_LIMITS), "baseline_reference": baseline,
                   "causal_codes": codes, "ledger": _ledger(f), "gaps": f.gaps},
        evidence_links=sorted(f.items), prediction_skipped_reason=reason, reason=reason)


# ---------------------------------------------------------------- 노드 틀 연결

def make_runners(loader):
    """loader(task) → 거시 입력 묶음. 같은 (종목, 기준일)이면 한 번만 읽고 에이전트 1 계산도 한 번만 합니다."""
    cache: dict = {}

    def get(task: NodeTask):
        key = (task.target_ticker, task.as_of_date)
        if key not in cache:
            b, co = loader(task)
            b = clean_inputs(b, task.as_of_date)
            cache[key] = (b, co)
        return cache[key]

    def r05(t: NodeTask) -> NodeResult:
        b, co = get(t)
        return n05(b, co, t.as_of_date, focus=t.parameters.get("focus"))

    def r06(t: NodeTask) -> NodeResult:
        b, co = get(t)
        return n06(b, co, t.as_of_date, t.parameters.get("scenario"))

    return {"N05": r05, "N06": r06}


def _db_loader(task: NodeTask):
    from . import db
    from .agents import fetch_bundle

    co = db.company(task.target_ticker)
    return fetch_bundle(1, co, task.as_of_date, use_rag=False), co


for _nid, _fn in make_runners(_db_loader).items():   # 기본 등록(DB). 재현·테스트는 run_macro_agent(inputs=, co=) 로 입력을 직접 넘김
    register(_nid)(_fn)


def run_macro_agent(ticker: str, as_of_date: str, extension: bool = False, scenario: str | None = None,
                    focus: list[str] | None = None, inputs: dict | None = None, co: dict | None = None) -> dict:
    """에이전트 3(거시)을 노드 단위로 실행. 확장(N06)은 extension=True 이고 시나리오 가정이 있을 때만 실행됩니다."""
    from .nodes import run_agent_nodes

    as_of = require_as_of(as_of_date)
    if inputs is None:
        from . import db
        from .agents import fetch_bundle

        co = co or db.company(ticker)
        inputs = fetch_bundle(1, co, as_of, use_rag=False)
    inputs = clean_inputs(inputs, as_of)
    return run_agent_nodes(3, ticker, as_of, extension=extension, available=available_inputs(inputs, scenario),
                           runners=make_runners(lambda t: (inputs, co)),
                           parameters={"scenario": scenario, "focus": focus})
