"""조건부 시나리오: 공시 민감도의 정적 환산 (P01 기준 문서 5장·12장, 기능 P01-F07 중 '공시 정적 계산').

에이전트 1에는 미래 거시 경로를 입력받도록 학습·평가된 모델이 없습니다. 문서 12.2 에 따라 경로를 모델에 임의로
넣지 않고, 회사가 사업보고서에 공시한 민감도(예: 환율 10% 상승 시 세전손익 +X원)를 사용자가 정한 충격 크기로
선형 환산한 값만 냅니다.

- 결과 종류는 '공시 민감도' 입니다. 매출·영업이익 예측이나 정책의 인과효과가 아닙니다 (문서 5장).
- 공시된 충격 폭보다 큰 충격은 선형 외삽이므로 숫자를 보류합니다 (OUT_OF_SUPPORT, 문서 12.3).
- '금리 0.5% 하락' 처럼 %와 %p 가 모호하면 보류하고 단위를 묻습니다 (문서 9.2: -0.5%p 와 -0.5% 구분).
- '금리 인하 때문에 얼마나' 처럼 인과를 묻는 표현은 인과 부분을 보류합니다 (CAUSAL_UNIDENTIFIED).
- 시나리오에 발생 확률을 붙이지 않습니다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

SRC_REPORT = "core.report_exposure (사업보고서 재무위험관리 주석)"
CAUSAL_RE = re.compile(r"때문에|덕분에|탓에|인과|효과로|영향으로 인해|로 인해")

_FX = r"(?:원/달러\s*)?환율|원달러|달러\s*강세|원화\s*약세"
_RATE = r"(?:기준\s*)?금리|이자율"
_NUM = r"([+-]?\d+(?:\.\d+)?)\s*(%p|%포인트|bp|%)"
_DIR = r"(상승|올라|오르|인상|하락|내려|내리|인하|떨어)"
PAT = re.compile(rf"({_FX}|{_RATE})[^0-9+-]{{0,6}}{_NUM}\s*{_DIR}?")


@dataclass
class ScenarioSpec:
    variable: str            # fx (원/달러, KRW per USD) / rate (금리)
    change: float | None     # 환율은 %, 금리는 %p (bp 는 %p 로 바꿈). 모호하면 None
    unit: str                # %, %p
    raw: str                 # 사용자가 쓴 표현
    shape: str = "disclosed_static"  # 공시 민감도와 같은 '기준일 즉시 일회 변동' 가정
    origin: str = ""
    created_by: str = "user"
    issue: str | None = None  # UNIT_AMBIGUOUS 등

    @property
    def spec_hash(self) -> str:
        return hashlib.sha1(json.dumps(asdict(self), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def parse(text: str, origin: str = "") -> tuple[list[ScenarioSpec], list[str]]:
    """'환율 5% 상승, 금리 0.5%p 하락' → 시나리오 목록과 상태 코드."""
    specs, codes = [], []
    for m in PAT.finditer(text or ""):
        var_txt, num, unit, direction = m.group(1), float(m.group(2)), m.group(3), m.group(4) or ""
        var = "rate" if re.fullmatch(_RATE, var_txt.strip()) or "금리" in var_txt or "이자율" in var_txt else "fx"
        sign = -1 if re.match(r"하락|내려|내리|인하|떨어", direction) else 1
        value = abs(num) * sign if direction else num
        issue = None
        if var == "rate":
            if unit == "bp":
                value, unit = value / 100, "%p"
            elif unit in ("%p", "%포인트"):
                unit = "%p"
            else:  # '금리 0.5% 하락' → 0.5%p 인지, 금리 수준의 0.5% 인지 모호
                value, issue = None, "UNIT_AMBIGUOUS"
        else:
            if unit != "%":
                value, issue = None, "UNIT_AMBIGUOUS"
        specs.append(ScenarioSpec(var, value, "%p" if var == "rate" else "%", m.group(0).strip(), origin=origin,
                                  issue=issue))
        if issue:
            codes.append(issue)
    if CAUSAL_RE.search(text or ""):
        codes.append("CAUSAL_UNIDENTIFIED")
    return specs, list(dict.fromkeys(codes))


def _disclosed(report: list[dict] | None, var: str) -> dict | None:
    rows = [r for r in report or [] if r.get("value") is not None]
    if var == "fx":
        sens = [r for r in rows if r["metric"] == "fx_sens"]
        if not sens:
            return None
        pct = next((float(r["change_pct"]) for r in sens if r.get("change_pct")), None)
        basis = next((r["basis"] for r in sens if r.get("basis")), None) or "손익"
        return {"value": sum(float(r["value"]) for r in sens), "shock": pct, "basis": basis,
                "fy": sens[0].get("fiscal_year"), "unit": "%"}
    ir = next((r for r in rows if r["metric"] == "ir_sens"), None)
    if not ir:
        return None
    return {"value": float(ir["value"]), "shock": float(ir["change_pct"]) if ir.get("change_pct") else None,
            "basis": ir.get("basis") or "손익", "fy": ir.get("fiscal_year"), "unit": "%p"}


def evaluate(spec: ScenarioSpec, report: list[dict] | None) -> dict:
    """공시 민감도를 시나리오 크기로 선형 환산. 돌려주는 값의 status: ok / held."""
    out = {"spec": asdict(spec), "hash": spec.spec_hash, "kind": "공시 민감도(정적 환산)", "causal_effect": None,
           "probability": None, "status": "held", "codes": []}
    if spec.issue:
        out["codes"].append(spec.issue)
        out["reason"] = "단위가 모호함: 금리는 %p(또는 bp), 환율은 % 로 다시 적어 주세요"
        return out
    d = _disclosed(report, spec.variable)
    if not d:
        out["codes"].append("MISSING_DISCLOSURE")
        out["reason"] = "사업보고서 민감도 표가 수집되지 않음"
        return out
    out["disclosed"] = d
    if not d["shock"]:
        out["codes"].append("MISSING_DISCLOSURE")
        out["reason"] = "공시 민감도의 충격 폭이 원문에 없어 환산 불가"
        return out
    if abs(spec.change) > abs(d["shock"]) + 1e-9:
        out["codes"].append("OUT_OF_SUPPORT")
        out["reason"] = (f"공시 충격 폭({d['shock']:g}{d['unit']})보다 큰 충격({abs(spec.change):g}{d['unit']})은 "
                         "선형 외삽이라 숫자를 보류")
        return out
    out["value"] = d["value"] * spec.change / d["shock"]
    out["status"] = "ok"
    return out


def add_facts(f, results: list[dict], as_of: str) -> list[str]:
    keys = []
    g = "시나리오(공시 정적 환산)"
    for r in results:
        sp = r["spec"]
        name = "원/달러 환율" if sp["variable"] == "fx" else "금리"
        label = f"시나리오 {sp['raw']}"
        if r["status"] != "ok":
            f.gap(label, f"{', '.join(r['codes'])}: {r.get('reason', '')}")
            continue
        d = r["disclosed"]
        chg = f"{sp['change']:+g}{sp['unit']}"
        k = f.add(f"{name} {chg} 가정 시 {d['basis']} 영향(FY{d['fy']} 공시 민감도 환산)", r["value"], "KRW±", as_of,
                  SRC_REPORT, kind="calc", group=g,
                  note=(f"공시값(충격 {d['shock']:g}{d['unit']})을 선형 환산. 매출·영업이익 예측이 아니고 인과효과·확률 아님. "
                        f"헤지·통화 구성 변화 미반영, 시나리오 {r['hash']}"))
        keys.append(k)
    return [k for k in keys if k]
