"""데이터 계약 (기초기획서 R4 3장, 교재 제2판 27장 '주장과 원문 연결').

에이전트 1·3 의 출력을 팀 공통 JSON 으로 바꿉니다. 오케스트레이터·화면·Verifier 는 이 형식만 보면 됩니다.

| 필드 | 뜻 |
| --- | --- |
| reportId | 이 출력 한 건의 ID (관점·종목·기준일·내용 해시) |
| claims[].claimId | 주장 ID (C01…). 반대 근거도 주장으로 두고 role='counter' |
| claims[].type | fact(사실)·interpretation(해석)·forecast(예측) |
| claims[].evidenceIds | 근거 ID (E01…). evidence[] 와 1:1 연결 |
| evidence[].dataDate | 자료 기준일 (관측 시점) |
| evidence[].publishedAt | 공개시각 (문서·공시). 거시 지표는 공표 시각을 수집하지 않아 null |
| evidence[].sourceTag | 출처 태그 ([출처: Neon core.…, 기준일]) — Verifier 가 붙인 값과 같음 |
| downsideRisks / counter claims | 반대 근거 / 하방 위험 |
| unverified[] | 미확인 상태 (무자료, 미확인 전제, 판단 보류) |
| verification | Verifier 결과 (claimId 별 통과·제외) |

근거 ID 는 장부 순서(숫자 → 문서) 그대로 매기므로 같은 입력이면 같은 ID 가 나옵니다.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .availability import AVAILABILITY, availability

SCHEMA_VERSION = "r4-1.1"   # r4-1.1: unverified[].availability 추가 (선택 필드)
SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "agent_output.schema.json"
KST = timezone(timedelta(hours=9))
MODULES = {1: "agent1_macro", 3: "agent3_sentiment_flow"}
TYPE_EN = {"사실": "fact", "해석": "interpretation", "예측": "forecast"}
KEY = re.compile(r"\{([A-Z]\d+)\}")
DISCLAIMER = "투자 검토 참고치 및 리스크 요약입니다. 매수·매도 추천이나 목표주가가 아닙니다."
COUNTER_GAP = "반대 근거·하방 위험"


# ---------------------------------------------------------------- 미확인 항목 중복 판단

_TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")
_STOP = {"여부", "확인", "미확인", "조건", "실제", "기업의", "기업", "등의", "이나", "및"}


def _tokens(text: str) -> set[str]:
    out = set()
    for w in _TOKEN.findall(str(text)):
        w = re.sub(r"(의|별|과|와|이나|에|을|를)$", "", w) if len(w) > 2 else w
        if w not in _STOP:
            out.add(w)
    return out


def same_item(a: str, b: str, ratio: float = 0.5) -> bool:
    """미확인 항목 두 개가 같은 내용을 가리키는지 (짧은 쪽 단어의 절반 이상이 겹치면 같다고 봄).

    10/28 실행: '환헤지 여부·비율'(미확인 전제)과 '환헤지 비율·만기'(판단 보류)처럼 같은 항목이 5쌍 겹쳐 나왔습니다."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= ratio


# ---------------------------------------------------------------- 근거 ID


def evidence_map(data) -> dict[str, str]:
    """장부 키(M7, S3, D2) → 근거 ID(E01…)."""
    keys = list(data.facts.items) + [f"D{i + 1}" for i in range(len(data.docs))]
    width = max(2, len(str(len(keys))))
    return {k: f"E{i + 1:0{width}d}" for i, k in enumerate(keys)}


def evidence_ids(keys, emap: dict[str, str]) -> list[str]:
    return list(dict.fromkeys(emap[k] for k in keys if k in emap))


def source_tag(item: dict) -> str:
    src = str(item.get("source") or "").split(" (")[0]
    when = str(item.get("as_of") or "")
    return f"Neon {src}" + (f", {when}" if when and when != "-" and len(when) <= 12 else "")


def doc_tag(d: dict) -> str:
    if d.get("kind") == "공시":
        return f"{str(d.get('source') or 'dart').upper()} 공시 {d.get('published')}"
    return f"{d.get('kind', '문서')} {d.get('published')}"


def _evidence(data, emap: dict[str, str], cited: set[str]) -> list[dict]:
    out = []
    for k, it in data.facts.items.items():
        out.append({
            "evidenceId": emap[k], "ledgerKey": k, "kind": "number", "label": it["label"], "value": it["value"],
            "unit": it["unit"], "display": it["text"], "valueType": it["kind"], "group": it.get("group") or None,
            "dataDate": it.get("as_of"), "publishedAt": None, "source": it.get("source"),
            "sourceTag": f"[출처: {source_tag(it)}]", "url": None, "note": it.get("note") or None,
            "cited": k in cited,
        })
    for i, d in enumerate(data.docs):
        k = f"D{i + 1}"
        out.append({
            "evidenceId": emap[k], "ledgerKey": k, "kind": "disclosure" if d.get("kind") == "공시" else "document",
            "label": d.get("title"), "value": None, "unit": None, "display": None, "valueType": d.get("kind"),
            "group": None, "dataDate": str(d.get("published"))[:10] if d.get("published") else None,
            "publishedAt": str(d.get("published_at") or d.get("published") or "") or None,
            "source": d.get("source"), "sourceTag": f"[출처: {doc_tag(d)}]", "url": d.get("url"), "note": None,
            "cited": k in cited,
        })
    return out


# ---------------------------------------------------------------- 문장

def plain(text: str, data) -> str:
    """장부 키는 값으로, 문서 키는 근거 ID 로 바꾼 사람이 읽는 문장."""
    items = data.facts.items
    emap = evidence_map(data)

    def sub(m):
        k = m.group(1)
        if k in items:
            return items[k]["text"]
        return f"[{emap.get(k, k)}]"

    return KEY.sub(sub, str(text or ""))


def _keys_in(text: str, refs=None) -> list[str]:
    return list(dict.fromkeys(KEY.findall(str(text or "")) + [str(k) for k in refs or []]))


def assign_claim_ids(result: dict) -> dict:
    """주장(role=main)과 반대근거(role=counter)에 C01… 을 매깁니다. 이미 있으면 그대로 둡니다."""
    out = dict(result)
    n = 0
    for field in ("주장", "반대근거"):
        rows = []
        for c in out.get(field) or []:
            if not isinstance(c, dict):
                continue
            n += 1
            rows.append({**c, "claimId": c.get("claimId") or f"C{n:02d}"})
        out[field] = rows
    return out


# ---------------------------------------------------------------- 계약 객체

def build(run: dict, data, mode: str = "expert") -> dict:
    """run_agent 결과(dict)와 AgentData 로 계약 JSON 을 만듭니다."""
    res = run["result"]
    emap = evidence_map(data)
    vlog = {v.get("claimId"): v for v in run.get("verification") or [] if v.get("claimId")}
    claims, cited = [], set()
    for field, role in (("주장", "main"), ("반대근거", "counter")):
        for c in res.get(field) or []:
            keys = _keys_in(c.get("문장"), c.get("근거"))
            cited.update(keys)
            v = vlog.get(c.get("claimId"), {})
            claims.append({
                "claimId": c.get("claimId"), "role": role, "text": plain(c.get("문장"), data),
                "template": c.get("문장"), "type": TYPE_EN.get(c.get("구분"), "interpretation"),
                "typeLabel": c.get("구분") or "해석", "evidenceIds": evidence_ids(keys, emap),
                "sourceTags": [f"[출처: {s}]" for s in c.get("출처") or []],
                "verification": {"status": "passed" if v.get("ok", True) else "failed",
                                 "checkedBy": "fact_source_verifier", "unmatched": v.get("unmatched") or []},
            })

    def items(field, prefix):
        out = []
        for i, t in enumerate(res.get(field) or []):
            keys = _keys_in(t)
            cited.update(keys)
            out.append({f"{prefix}Id": f"{prefix[0].upper()}{i + 1:02d}", "text": plain(t, data),
                        "evidenceIds": evidence_ids(keys, emap)})
        return out

    risks = items("리스크요인", "risk")
    ups = items("긍정요인", "upside")
    head_keys = _keys_in(res.get("핵심진단"))
    cited.update(head_keys)

    unverified = [{"item": g["label"], "reason": g["reason"], "category": "무자료", "status": "미확인",
                   "evidenceIds": []} for g in data.facts.gaps]
    for p in data.extra.get("premises") or []:
        if p["status"] != "확인":
            unverified.append({"item": p["item"], "reason": p["detail"], "category": "미확인 전제",
                               "status": p["status"], "evidenceIds": evidence_ids(p["keys"], emap)})
    for t in res.get("미확인") or []:
        item, ev = plain(t, data), evidence_ids(_keys_in(t), emap)
        dup = next((u for u in unverified if same_item(item, u["item"])), None)
        if dup is not None:  # 미확인 전제·무자료와 같은 항목을 LLM 이 다시 쓴 것: 새 줄을 만들지 않고 근거만 합침
            dup["evidenceIds"] = list(dict.fromkeys(dup["evidenceIds"] + ev))
            continue
        unverified.append({"item": item, "reason": "에이전트가 판단에 필요하다고 본 미확인 항목",
                           "category": "판단 보류", "status": "미확인", "evidenceIds": ev})
    if not any(c["role"] == "counter" for c in claims) and not risks:
        # 규칙 5: 반대 근거·하방 위험이 검증을 통과하지 못해 비었으면, 없다는 사실을 미확인으로 드러냅니다.
        unverified.append({"item": COUNTER_GAP, "reason": "검증을 통과한 반대 근거와 하방 위험이 없음",
                           "category": "판단 보류", "status": "미확인", "evidenceIds": []})

    for u in unverified:
        u["availability"] = availability(u["item"], u["reason"])
        u["availabilityLabel"] = AVAILABILITY[u["availability"]]
    out = {
        "schemaVersion": SCHEMA_VERSION,
        "reportId": None,
        "agent": {"id": data.agent_id, "module": MODULES.get(data.agent_id, f"agent{data.agent_id}"),
                  "name": data.name},
        "target": {"ticker": data.company.get("ticker"), "name": data.company.get("name"),
                   "market": data.company.get("market")},
        "mode": mode,
        "asOf": data.as_of,
        "observationPeriod": data.period,
        "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "status": run["status"],
        "userInput": data.extra.get("opts") or {},
        "summary": {"text": plain(res.get("핵심진단"), data), "evidenceIds": evidence_ids(head_keys, emap)},
        "claims": claims,
        "upsideFactors": ups,
        "downsideRisks": risks,
        "unverified": unverified,
        "nextChecks": [plain(t, data) for t in res.get("다음점검") or []],
        "evidence": [],
        "codeFindings": [{"text": plain(fl, data), "evidenceIds": evidence_ids(_keys_in(fl), emap)}
                         for fl in data.facts.flags],
        "verification": {
            "checker": "agent/verifier/fact_source_verifier.py",
            "checked": len(run.get("verification") or []),
            "passed": sum(1 for v in run.get("verification") or [] if v.get("ok")),
            "removedSentences": len(run.get("removed") or []),
            "results": [{"claimId": v.get("claimId"), "ok": bool(v.get("ok")), "unmatched": v.get("unmatched") or [],
                         "evidenceIds": v.get("evidenceIds") or []} for v in run.get("verification") or []],
        },
        "dataQuality": data.extra.get("quality") or [],
        "selfScore": res.get("자체점수"),
        "disclaimer": DISCLAIMER,
    }
    if data.agent_id == 1:
        out["exposure"] = [{"variable": r["var"], "level": r["level"], "basis": plain(", ".join(r["reasons"]), data),
                            "companySpecific": bool(r.get("company")), "path": r["path"], "focus": bool(r["focus"]),
                            "evidenceIds": evidence_ids(r["keys"], emap)} for r in data.extra.get("exposure") or []]
        out["premises"] = [{"item": p["item"], "status": p["status"], "detail": p["detail"], "why": p["why"],
                            "evidenceIds": evidence_ids(p["keys"], emap)} for p in data.extra.get("premises") or []]
        cited.update(k for r in data.extra.get("exposure") or [] for k in r["keys"])
    if data.agent_id == 3:
        out["anomalies"] = [{"text": plain(t, data), "evidenceIds": evidence_ids(_keys_in(t), emap)}
                            for t in data.extra.get("anomalies") or []]
        out["baseline"] = [{"signal": b["signal"], "method": b["method"], "rule": b["rule"], "status": b["status"],
                            "evidenceIds": evidence_ids([k for k in (b["current"], b["base"], b["measure"]) if k], emap)}
                           for b in data.extra.get("baseline") or []]
        out["duplicateSignals"] = [{"clusterId": c["id"], "signals": c["signals"],
                                    "evidenceIds": evidence_ids(c["keys"], emap),
                                    "rule": "같은 사건을 반영할 수 있어 독립 근거로 중복 계산하지 않음"}
                                   for c in data.extra.get("dup_clusters") or []]
        out["sentimentModel"] = data.extra.get("sentiment_model")
    out["evidence"] = _evidence(data, emap, cited)
    body = json.dumps({k: out[k] for k in ("agent", "target", "asOf", "mode", "claims")}, ensure_ascii=False,
                      sort_keys=True)
    out["reportId"] = (f"RPT-{data.agent_id}-{data.company.get('ticker')}-{data.as_of.replace('-', '')}-"
                       f"{hashlib.sha1(body.encode()).hexdigest()[:8]}")
    return out


# ---------------------------------------------------------------- 검사 (외부 의존성 없이)

def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict,
          "null": type(None)}


def validate(obj, schema: dict | None = None, path: str = "$", root: dict | None = None) -> list[str]:
    """JSON Schema 의 일부(type·required·properties·items·enum·pattern·$ref)만 검사하는 작은 검사기.
    jsonschema 패키지 없이도 계약 위반을 찾게 하려는 용도입니다."""
    schema = load_schema() if schema is None else schema
    root = root or schema
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        schema = node
    errs: list[str] = []
    t = schema.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        ok = any(isinstance(obj, _TYPES[x]) and not (x in ("integer", "number") and isinstance(obj, bool))
                 for x in ts)
        if not ok:
            return [f"{path}: 형식 {ts} 아님 ({type(obj).__name__})"]
    if "enum" in schema and obj not in schema["enum"]:
        errs.append(f"{path}: 허용 값 아님 ({obj!r})")
    if "pattern" in schema and isinstance(obj, str) and not re.search(schema["pattern"], obj):
        errs.append(f"{path}: 형식 패턴 불일치 ({obj!r})")
    if isinstance(obj, dict):
        for k in schema.get("required", []):
            if k not in obj:
                errs.append(f"{path}: '{k}' 없음")
        for k, sub in (schema.get("properties") or {}).items():
            if k in obj:
                errs += validate(obj[k], sub, f"{path}.{k}", root)
    if isinstance(obj, list) and "items" in schema:
        for i, x in enumerate(obj):
            errs += validate(x, schema["items"], f"{path}[{i}]", root)
    return errs


def link_errors(contract: dict) -> list[str]:
    """근거 ID 연결 검사: 주장·위험·미확인이 가리키는 evidenceId 가 evidence[] 에 있는지, claimId 가 겹치지 않는지."""
    ids = {e["evidenceId"] for e in contract.get("evidence") or []}
    errs = []
    seen = set()
    for c in contract.get("claims") or []:
        if c["claimId"] in seen:
            errs.append(f"claimId 중복 {c['claimId']}")
        seen.add(c["claimId"])
        if c["type"] in ("fact", "interpretation") and c["role"] == "main" and not c["evidenceIds"]:
            errs.append(f"{c['claimId']}: 근거 없는 {c['typeLabel']}")
    for field in ("claims", "downsideRisks", "upsideFactors", "unverified", "codeFindings", "exposure", "premises",
                  "anomalies", "baseline", "duplicateSignals"):
        for x in contract.get(field) or []:
            bad = [e for e in x.get("evidenceIds") or [] if e not in ids]
            if bad:
                errs.append(f"{field}: 없는 근거 ID {bad}")
    return errs
