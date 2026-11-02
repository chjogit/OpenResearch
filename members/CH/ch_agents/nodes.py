"""에이전트 번호(3·4·6)와 노드 실행 틀 (티켓 #21, specs/agent-split.md).

- 번호/노드 이름은 이 파일 한곳에서 정의합니다: 3 거시(N05 Macro_Base · N06 Macro_Ext), 4 수급(N07 Flow_Base · N08 Flow_Ext),
  6 투자심리·뉴스(N11 Sentiment_Base · N12 Sentiment_Ext). 이번 단계는 틀만이며 노드 내용(runner)은 #22~#24 가 등록합니다.
- E1 표준 입출력: 노드는 NodeTask 로 호출되고 NodeResult 로 반환합니다. 근거 연결(evidence_links)이 없는 수치·결론은 검증에서 걸립니다.
- E2 상태 4종: SUCCESS / PARTIAL_SUCCESS / DATA_INSUFFICIENT / FAILED. 기본 노드의 필수 자료가 없으면 바로 DATA_INSUFFICIENT,
  확장 노드는 요건·검증이 미충족이면 건너뛰고(prediction_skipped_reason) 기본 결과를 그대로 돌려줍니다.
- E4 태그: Fact / Computation / Prediction / Interpretation. 상충 신호는 평균 내지 않고 conflicts(관점별 충돌)에 나란히 둡니다.
- E5 MAX_REPAIR_ATTEMPTS(기본 1, 환경변수 CH_MAX_REPAIR_ATTEMPTS)로 보완 재시도 상한을 통일, 초과하면 unresolved 로 넘깁니다.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- 번호·노드 정의 (한곳)

AGENTS = {3: "거시경제·정책", 4: "수급", 6: "투자심리·뉴스"}
STATUSES = ("SUCCESS", "PARTIAL_SUCCESS", "DATA_INSUFFICIENT", "FAILED")
TAGS = ("Fact", "Computation", "Prediction", "Interpretation")
# 기존 출력의 '구분(사실/해석/예측)' → 태그. 숫자 장부 키만 근거인 사실 진술은 legacy_tag(computed_only=True) 로 Computation.
LEGACY_TAG = {"사실": "Fact", "해석": "Interpretation", "예측": "Prediction"}


@dataclass(frozen=True)
class NodeSpec:
    node_id: str
    name: str
    agent: int
    kind: Literal["base", "ext"]
    title: str
    required: tuple[str, ...]  # 이 입력이 없으면: 기본은 DATA_INSUFFICIENT, 확장은 스킵 (노드 내용 티켓이 필요하면 등록 때 바꿈)


NODES: dict[str, NodeSpec] = {s.node_id: s for s in (
    NodeSpec("N05", "Macro_Base", 3, "base", "기업별 거시 노출", ("macro_series",)),
    NodeSpec("N06", "Macro_Ext", 3, "ext", "거시 시나리오·민감도", ("N05", "macro_series", "scenario_assumptions")),
    NodeSpec("N07", "Flow_Base", 4, "base", "유동성·거래대금", ("price", "trading_value")),
    NodeSpec("N08", "Flow_Ext", 4, "ext", "수급 전환·가격 불일치", ("N07", "investor_flow")),
    NodeSpec("N11", "Sentiment_Base", 6, "base", "감성·불확실성", ("documents",)),
    NodeSpec("N12", "Sentiment_Ext", 6, "ext", "후속 시장 반응 검증", ("N11", "price_after_event", "validated_sample")),
)}

# 옛 출력(p01 거시, p03 투자심리·수급) → 새 번호. 옛 3번(투자심리·수급)과 새 3번(거시)이 겹치므로 이름이 아니라 이 표로만 옮긴다.
LEGACY_OUTPUT = {"p01": (3,), "p03": (4, 6)}
LEGACY_AGENT = {1: (3,), 3: (4, 6)}   # 옛 에이전트 번호(1 거시, 3 투자심리·수급) → 새 번호


def agent_nodes(agent_no: int) -> list[NodeSpec]:
    return [s for s in NODES.values() if s.agent == agent_no]


def legacy_agent_nos(old_agent_id: int) -> list[int]:
    return list(LEGACY_AGENT.get(old_agent_id, ()))


def legacy_tag(구분: str | None, computed_only: bool = False) -> str:
    """기존 '구분'을 새 태그로. 숫자 장부 키만 근거인 사실 진술은 computed_only=True 로 Computation."""
    tag = LEGACY_TAG.get(구분 or "", "Interpretation")
    return "Computation" if computed_only and tag == "Fact" else tag


# ---------------------------------------------------------------- E5 재시도 상한

def max_repair_attempts() -> int:
    """보완 재시도 상한 MAX_REPAIR_ATTEMPTS (기본 1, 설정 가능, 0~2 로 제한)."""
    try:
        n = int(os.getenv("CH_MAX_REPAIR_ATTEMPTS", "1"))
    except ValueError:
        n = 1
    return max(0, min(2, n))


# ---------------------------------------------------------------- E1 표준 입출력

class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NodeTask(_Model):
    task_id: str
    node_id: str
    target_ticker: str
    as_of_date: str                                   # 누수 방지 절대 기준일 (E3)
    input_data_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)    # 방법론·확장 활성화·repair 힌트
    constraints: dict[str, Any] = Field(default_factory=dict)   # 타임아웃·토큰/비용 한도·허용 도구


class Finding(_Model):
    """수치·결론 한 건. evidence_links 가 비면 검증에서 걸립니다."""
    kind: Literal["number", "conclusion", "note"] = "conclusion"
    text: str
    tag: Literal["Fact", "Computation", "Prediction", "Interpretation"] = "Interpretation"
    evidence_links: list[str] = Field(default_factory=list)   # 원문 인용 또는 데이터 ID


class ConflictView(_Model):
    text: str
    tag: Literal["Fact", "Computation", "Prediction", "Interpretation"]
    evidence_links: list[str] = Field(default_factory=list)


class Conflict(_Model):
    """관점별 충돌: 상충 신호를 평균·합의하지 않고 나란히 둡니다 (불리한 결과도 보존)."""
    topic: str
    views: list[ConflictView]


class ExecutionMeta(_Model):
    model_version: str | None = None
    seconds: float = 0.0
    cost: float | None = None
    attempts: int = 1


class NodeResult(_Model):
    status: Literal["SUCCESS", "PARTIAL_SUCCESS", "DATA_INSUFFICIENT", "FAILED"]
    node_id: str | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)      # 노드별 표준 산출물(표 등)
    findings: list[Finding] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)      # 결과 전체가 참조한 근거 ID 모음
    missing_items: list[str] = Field(default_factory=list)       # 미확보 입력
    unresolved: list[str] = Field(default_factory=list)          # 보완 상한을 넘어 남은 문제
    reason: str | None = None
    prediction_skipped_reason: str | None = None
    execution_meta: ExecutionMeta = Field(default_factory=ExecutionMeta)


def result_problems(res: NodeResult) -> list[str]:
    """E1·E4 검증: 근거 없는 수치·결론, 충돌 구역 형식."""
    out = [f"근거 연결 없음({f.kind}): {f.text[:40]}" for f in res.findings
           if f.kind in ("number", "conclusion") and not f.evidence_links]
    for c in res.conflicts:
        if len(c.views) < 2:
            out.append(f"관점별 충돌에 관점이 2개 미만: {c.topic}")
        out += [f"충돌 관점에 근거 연결 없음: {c.topic}" for v in c.views if not v.evidence_links]
    return out


class ExtensionNotValidated(Exception):
    """확장 노드의 검증 조건(표본·벤치마크 대비 추가 설명력 등)을 통과하지 못함 → 추론 건너뜀 (E2)."""


Runner = Callable[[NodeTask], NodeResult]
RUNNERS: dict[str, Runner] = {}   # 노드 ID → 실행 함수. #22~#24 가 register() 로 채움


def register(node_id: str):
    if node_id not in NODES:
        raise KeyError(f"알 수 없는 노드: {node_id}")

    def deco(fn: Runner) -> Runner:
        RUNNERS[node_id] = fn
        return fn
    return deco


# ---------------------------------------------------------------- 실행 틀

@dataclass
class _Run:
    spec: NodeSpec
    state: Literal["executed", "skipped"]
    result: NodeResult | None = None
    reason: str | None = None
    missing: list[str] = field(default_factory=list)


def _call(spec: NodeSpec, task: NodeTask, runner: Runner, max_attempts: int) -> NodeResult:
    """runner 를 부르고 근거·충돌 검증에 걸리면 문제 목록을 주어 최대 max_attempts 번 다시 부릅니다. 남은 문제는 unresolved."""
    t0 = time.monotonic()
    problems: list[str] = []
    res: NodeResult | None = None
    used = 0
    for used in range(1, max_attempts + 2):
        t = task if used == 1 else task.model_copy(update={"parameters": {**task.parameters, "repair": problems}})
        res = NodeResult.model_validate(runner(t))
        problems = result_problems(res)
        if not problems:
            break
    assert res is not None
    res.node_id = spec.node_id
    res.execution_meta.attempts = used
    res.execution_meta.seconds = round(time.monotonic() - t0, 3)
    if problems:   # 상한 초과: 문제 있는 진술은 버리고 unresolved 로 넘김 (원하는 결론이 나올 때까지 반복하지 않음)
        res.findings = [f for f in res.findings if f.kind == "note" or f.evidence_links]
        res.conflicts = [c for c in res.conflicts if len(c.views) >= 2 and all(v.evidence_links for v in c.views)]
        res.unresolved += problems
        if res.status == "SUCCESS":
            res.status = "PARTIAL_SUCCESS"
    return res


def run_node(spec: NodeSpec, task: NodeTask, available: set[str], selected: bool, base_ok: bool,
             runner: Runner | None, max_attempts: int) -> _Run:
    missing = [r for r in spec.required if r not in available]
    if spec.kind == "ext":
        if not selected:
            return _Run(spec, "skipped", reason="사용자가 확장 노드를 선택하지 않음")
        if not base_ok:
            return _Run(spec, "skipped", reason="기본 노드 결과가 없어 확장 노드를 건너뜀", missing=missing)
        if missing:
            return _Run(spec, "skipped", reason="확장 노드 입력 요건 미충족", missing=missing)
    elif missing:   # 기본 노드: 필수 자료 결측 → 즉시 DATA_INSUFFICIENT (무리한 추론 금지)
        res = NodeResult(status="DATA_INSUFFICIENT", node_id=spec.node_id, missing_items=missing,
                         reason="기본 노드 필수 자료 결측: " + ", ".join(missing))
        return _Run(spec, "executed", result=res, reason=res.reason, missing=missing)
    if runner is None:
        res = NodeResult(status="FAILED", node_id=spec.node_id, reason="노드 실행 함수가 등록되지 않음 (구현 전)")
        return _Run(spec, "executed", result=res, reason=res.reason)
    try:
        res = _call(spec, task, runner, max_attempts)
    except ExtensionNotValidated as exc:
        return _Run(spec, "skipped", reason=str(exc) or "검증 요건 미충족")
    except Exception as exc:  # noqa: BLE001  노드 하나의 실패가 다른 노드를 막지 않게
        res = NodeResult(status="FAILED", node_id=spec.node_id, reason=f"{type(exc).__name__}: {str(exc)[:120]}")
    return _Run(spec, "executed", result=res, reason=res.reason, missing=res.missing_items)


def run_agent_nodes(agent_no: int, ticker: str, as_of_date: str, extension: bool = False,
                    available: set[str] | None = None, runners: dict[str, Runner] | None = None,
                    parameters: dict[str, Any] | None = None, constraints: dict[str, Any] | None = None,
                    max_attempts: int | None = None) -> dict:
    """에이전트 하나의 노드를 실행하고 보고합니다. 기본 노드는 항상, 확장 노드는 선택(extension)+요건 충족 시.

    반환: {agentNo, status, nodes[{nodeId, name, kind, state(executed|skipped), status, reason, missingInputs}],
           counts{base, extSelected, extExecuted, executed(= 기본 + 실행한 확장)}, prediction_skipped_reason,
           results{nodeId: NodeResult}}"""
    from .asof import require_as_of

    if agent_no not in AGENTS:
        raise KeyError(f"알 수 없는 에이전트 번호: {agent_no} (3·4·6)")
    as_of = require_as_of(as_of_date)
    reg = {**RUNNERS, **(runners or {})}
    attempts = max_repair_attempts() if max_attempts is None else max_attempts
    runs: list[_Run] = []
    base_ok = False
    for spec in agent_nodes(agent_no):
        task = NodeTask(task_id=f"{agent_no}-{spec.node_id}-{ticker}-{as_of}", node_id=spec.node_id, target_ticker=ticker,
                        as_of_date=as_of, parameters={"extension": extension, **(parameters or {})},
                        constraints=constraints or {})
        # 앞선 노드가 결과를 냈으면 그 노드 ID 를 입력으로 인정 (확장 노드는 기본 노드 산출물을 씀)
        have = set(available or ()) | {r.spec.node_id for r in runs
                                       if r.result and r.result.status in ("SUCCESS", "PARTIAL_SUCCESS")}
        run = run_node(spec, task, have, extension, base_ok, reg.get(spec.node_id), attempts)
        if spec.kind == "base":
            base_ok = bool(run.result and run.result.status in ("SUCCESS", "PARTIAL_SUCCESS"))
        runs.append(run)
    nodes = [{"nodeId": r.spec.node_id, "name": r.spec.name, "kind": r.spec.kind, "state": r.state,
              "status": r.result.status if r.result else None, "reason": r.reason, "missingInputs": r.missing}
             for r in runs]
    n_base = sum(1 for r in runs if r.spec.kind == "base")
    n_ext = sum(1 for r in runs if r.spec.kind == "ext")
    ext_exec = sum(1 for r in runs if r.spec.kind == "ext" and r.state == "executed")
    skipped_ext = next((r for r in runs if r.spec.kind == "ext" and r.state == "skipped" and extension), None)
    results = [r.result for r in runs if r.result]
    if not base_ok and all(x.status == "DATA_INSUFFICIENT" for x in results if x.node_id in {r.spec.node_id for r in runs if r.spec.kind == "base"}):
        status = "DATA_INSUFFICIENT"
    elif not base_ok:
        status = "FAILED"
    elif skipped_ext or any(x.status != "SUCCESS" for x in results):
        status = "PARTIAL_SUCCESS"
    else:
        status = "SUCCESS"
    return {"agentNo": agent_no, "status": status, "nodes": nodes,
            "counts": {"base": n_base, "extSelected": n_ext if extension else 0, "extExecuted": ext_exec,
                       "executed": n_base + ext_exec},
            "prediction_skipped_reason": (skipped_ext.reason if skipped_ext and base_ok else None)
            or next((x.prediction_skipped_reason for x in results if x.prediction_skipped_reason), None),
            "results": {x.node_id: x for x in results}}


def pipeline_executed(reports: list[dict], other_agents_base: int = 3, other_ext_executed: int = 0) -> int:
    """6개 파이프라인 전체 실행 노드 수 = 6 + N(실행한 확장 수). CH 3개 에이전트 보고 + 다른 팀원 3개의 기본 노드 수."""
    return sum(r["counts"]["executed"] for r in reports) + other_agents_base + other_ext_executed
