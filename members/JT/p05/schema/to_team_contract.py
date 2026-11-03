"""P05 출력(초안 0.1·0.2)을 팀 공통 데이터 계약 r4-1.3 형식으로 바꾼다.

팀 계약 원본: chjogit/OpenResearch members/CH/docs/DATA_CONTRACT.md (r4-1.2 문서) + 스키마 r4-1.3
스키마 사본: team_agent_output_r4-1.3.schema.json (원본 커밋 382a5ca, 2026-11-02. r4-1.3은 선택 필드만 추가)
- r4-1.3에서 쓰는 것: claims[].tag(사실→Fact, 해석→Interpretation, 예측→Prediction)
- 쓰지 않는 것: agent.agentNos(허용값이 3·4·6뿐이라 5번은 넣지 않는다), nodes[]·conflicts(노드 틀은 3·4·6용)
- 0.2의 표 3개(promiseExecution·capitalAllocation·issues)는 근거·주장 ID를 팀 번호로 바꿔 최상위 고유 필드로 둔다

사용: python to_team_contract.py <P05 출력.json> [저장할 경로.json]
1) P05 검사기(validate_output.py)로 원본을 먼저 검사한다. 오류가 있으면 바꾸지 않는다.
2) 팀 계약 형식으로 바꾼다.
3) 팀 스키마(jsonschema)와 팀 link_errors 규칙으로 다시 검사한다.

바꾸는 규칙
- ID: 주장 F·G·P·S → C01…, 근거 E·N·R → E01…  원래 ID는 governance[]의 p05ClaimId, 근거 ledgerKey에 남긴다.
- 보류(hold) 주장은 claims에 넣지 않는다. 팀 계약의 claims는 검증을 통과한 주장만 담기 때문이다.
  대신 unverified[]에 '판단 보류'(availability not_verified)로 올리고, 감성 세부는 personSentiment[]에 둔다.
- 감성·보도 근거는 tier 'reference'(핵심 주장의 유일한 근거로 쓰지 않음), 공시 근거는 'core'.
- 규칙 판정 signal '주의' → downsideRisks, '긍정' → upsideFactors. 둘 다 비면 팀 규칙 5에 따라
  unverified에 '반대 근거·하방 위험'(판단 보류)을 넣는다.
- assumptions → unverified('미확인 전제'), handoff는 최상위 handoff[]로 둔다(에이전트 고유 필드).
  handoff는 다른 에이전트에 넘기는 사실이라 nextChecks(다음 점검)에 넣지 않는다.
- reportId는 팀 contract.build()와 같은 방식(agent·target·asOf·mode·claims의 sha1 앞 8자)으로 만든다.

팀 확인 전 가정
- 에이전트 번호 5, 모듈명 agent5_governance (계약 4장 결정 항목 2: 담당자가 정해 표에 적는다).
"""
from pathlib import Path
import hashlib
import json
import sys

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_output as P05

SCHEMA_DIR = Path(__file__).resolve().parent
TEAM_SCHEMA = SCHEMA_DIR / "team_agent_output_r4-1.3.schema.json"
TEAM_VERSION = "r4-1.3"
AGENT = {"id": 5, "module": "agent5_governance", "name": "에이전트 5 경영진·대주주 분석 (Governance)"}

TYPE_LABEL = {"fact": "사실", "interpretation": "해석", "forecast": "예측"}
TAG = {"fact": "Fact", "interpretation": "Interpretation", "forecast": "Prediction"}   # 팀 nodes.LEGACY_TAG와 같은 대응
TABLES = ("promiseExecution", "capitalAllocation", "issues")
KIND = {"DART_DISCLOSURE": "disclosure", "DART_ROSTER": "disclosure", "NEWS": "document"}
UNRESOLVED_CATEGORY = {   # P05 unresolved.reason → (팀 category, availability)
    "UNVALIDATED_MODEL": ("판단 보류", "not_verified"),
    "DATE_UNKNOWN": ("무자료", "unclassified"),
    "NO_DATA": ("무자료", "unclassified"),
    "CONFLICT": ("판단 보류", "not_verified"),          # 매체별 수치가 달라 원문 확인 전
    "LINK_UNVERIFIED": ("판단 보류", "not_verified"),   # 대상 연결(제목 속 인물=당사자)을 확인하지 못함
}


def team_source_tag(e):
    if e.get("rceptNo"):
        return f"[출처: DART 공시 {e['rceptNo']}, {e.get('publishedAt') or '공개일 미상'}]"
    return f"[출처: {e['verificationStatus']} {e.get('publishedAt') or '공개일 미상'}]"


def convert_evidence(p05_evidence, cited):
    emap, out = {}, []
    width = 3 if len(p05_evidence) >= 100 else 2
    for i, e in enumerate(p05_evidence, 1):
        eid = f"E{i:0{width}d}"
        emap[e["evidenceId"]] = eid
        disclosed = e["verificationStatus"] == "공시"
        value = e.get("value")
        out.append({
            "evidenceId": eid,
            "ledgerKey": e["evidenceId"][0] + str(int(e["evidenceId"][1:])),   # E14 → E14, N003 → N3
            "kind": "number" if isinstance(value, (int, float)) and not isinstance(value, bool) else
            KIND.get(e["sourceType"], "document"),
            "label": e.get("item"),
            "value": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
            "unit": e.get("unit"),
            "display": None,
            "valueType": "회사 공시" if disclosed else e["verificationStatus"],
            "dataDate": e.get("dataDate"),
            "publishedAt": e.get("publishedAt"),
            "source": e["sourceType"],
            "sourceTag": team_source_tag(e),
            "url": e.get("url"),
            "note": e.get("quote"),
            "cited": e["evidenceId"] in cited,
            "tier": "core" if disclosed else "reference",
            "resultType": "공시" if disclosed else "보도",
        })
    return emap, out


def convert(doc):
    p05_errs = P05.contract_errors(doc)
    shown = [c for c in doc["claims"] if c["reportStatus"] != "hold"]
    held = [c for c in doc["claims"] if c["reportStatus"] == "hold"]
    cited = {e for c in shown for e in c["evidenceIds"]}
    emap, evidence = convert_evidence(doc["evidence"], cited)
    ev_tag = {emap[e["evidenceId"]]: t["sourceTag"] for e, t in zip(doc["evidence"], evidence)}
    cmap = {c["claimId"]: f"C{i:02d}" for i, c in enumerate(shown, 1)}

    claims, governance, results = [], [], []
    for c in shown:
        cid = cmap[c["claimId"]]
        eids = [emap[e] for e in c["evidenceIds"]]
        bad = [m for m in p05_errs if m.startswith(c["claimId"] + ":")]
        claims.append({
            "claimId": cid, "role": "main", "text": c["statement"], "type": c["claimType"],
            "typeLabel": TYPE_LABEL[c["claimType"]], "tag": TAG[c["claimType"]], "evidenceIds": eids,
            "sourceTags": list(dict.fromkeys(ev_tag[e] for e in eids)),
            "verification": {"status": "failed" if bad else "passed", "checkedBy": "p05 validate_output",
                             "unmatched": bad},
        })
        results.append({"claimId": cid, "ok": not bad})
        governance.append({k: v for k, v in {
            "claimId": cid, "p05ClaimId": c["claimId"], "kind": c["kind"], "area": c["area"],
            "signal": c.get("signal"), "rule": c.get("rule"), "reportStatus": c["reportStatus"],
            "basedOnClaimIds": [cmap[b] for b in c.get("basedOnClaimIds", []) if b in cmap] or None,
        }.items() if v is not None})

    def linked(signal):
        return [{"text": c["statement"], "evidenceIds": [emap[e] for e in c["evidenceIds"]]}
                for c in shown if c.get("signal") == signal]

    unverified = []
    for u in doc["unresolved"]:
        if u["reason"] == "UNVALIDATED_MODEL":
            continue   # 보류 주장마다 아래에서 따로 올린다
        cat, avail = UNRESOLVED_CATEGORY.get(u["reason"], ("미확인 전제", "unclassified"))
        unverified.append({"item": u["item"], "reason": u["reason"], "category": cat, "status": "미확인",
                           "evidenceIds": [emap[u["evidenceId"]]] if u.get("evidenceId") in emap else [],
                           "availability": avail})
    person_sentiment = []
    for c in held:
        s = c.get("sentiment") or {}
        who = (s.get("target") or {}).get("name", "대상")
        eids = [emap[e] for e in c["evidenceIds"]]
        unverified.append({"item": f"{who} 관련 기사 주주 영향 감성", "reason": c.get("holdReason", "보류"),
                           "category": "판단 보류", "status": "미확인", "evidenceIds": eids,
                           "availability": "not_verified"})
        if s:
            person_sentiment.append({"p05ClaimId": c["claimId"], "area": c["area"], "evidenceIds": eids,
                                     "target": s.get("target"), "label": s.get("label"),
                                     "probabilities": s.get("probabilities"), "method": s.get("method"),
                                     "validationStatus": s.get("validationStatus")})
    for a in doc["assumptions"]:
        unverified.append({"item": a["statement"], "reason": "전제가 맞아야 관련 주장이 성립",
                           "category": "미확인 전제", "status": "미확인", "evidenceIds": [],
                           "availability": "unclassified"})
    downside, upside = linked("주의"), linked("긍정")
    if not downside and not any(c["type"] in ("fact", "interpretation") for c in claims if c["role"] == "counter"):
        unverified.append({"item": "반대 근거·하방 위험", "reason": "검증을 통과한 반대 근거·하방 위험이 없음",
                           "category": "판단 보류", "status": "미확인", "evidenceIds": []})

    out = {
        "schemaVersion": TEAM_VERSION,
        "reportId": "",
        "agent": AGENT,
        "target": {"ticker": doc["subject"]["stockCode"], "name": doc["subject"]["companyName"], "market": "KR",
                   "corpCode": doc["subject"]["corpCode"]},
        "mode": "expert",
        "asOf": doc["asOf"],
        "observationPeriod": doc.get("dataMode"),
        "generatedAt": doc["generatedAt"],
        "status": "완료" if doc["completeness"] == "complete" else "완료 (일부 자료만)",
        "summary": {"text": shown[0]["statement"] if shown else
                    "대상 인물 기사 감성은 모델 검증 전이라 모두 판정 보류다." if held else
                    "검증을 통과한 주장이 없다. 판정 전 항목은 미확인과 P05 표에 있다.",
                    "evidenceIds": claims[0]["evidenceIds"] if claims else []},
        "claims": claims,
        "upsideFactors": upside,
        "downsideRisks": downside,
        "unverified": unverified,
        "nextChecks": [],
        "evidence": evidence,
        "verification": {"checker": "p05 validate_output", "checked": len(results),
                         "passed": sum(r["ok"] for r in results), "removedSentences": 0, "results": results},
        "dataQuality": doc.get("qualityFlags", []),
        "disclaimer": doc["disclaimer"],
        "sentimentModel": (person_sentiment[0]["method"] + " / 검증 전(UNVALIDATED), 보조 신호")
        if person_sentiment else None,
        # 에이전트 5 고유 필드 (계약 6장 4: 최상위에 추가)
        "governance": governance,
        "personSentiment": person_sentiment,
        "handoff": [{"toAgentId": h["toAgentId"], "item": h["item"],
                     "claimIds": [cmap[x] for x in h.get("claimIds", []) if x in cmap]} for h in doc["handoff"]],
        "p05Source": {"schemaVersion": doc["schemaVersion"], "reportId": doc["reportId"]},
    }
    for name in TABLES:   # 0.2 표: 근거·주장 ID만 팀 번호로 바꾼다. 보류 주장에 붙은 행은 claimId를 뺀다
        if name in doc:
            out[name] = [{**{k: v for k, v in row.items() if k != "claimId"},
                          "evidenceIds": [emap[e] for e in row.get("evidenceIds", [])],
                          **({"followupEvidenceIds": [emap[e] for e in row["followupEvidenceIds"]]}
                             if row.get("followupEvidenceIds") else {}),
                          **({"claimId": cmap[row["claimId"]]} if row.get("claimId") in cmap else {})}
                         for row in doc[name]]
    body = json.dumps({k: out[k] for k in ("agent", "target", "asOf", "mode", "claims")}, ensure_ascii=False,
                      sort_keys=True)
    out["reportId"] = (f"RPT-{AGENT['id']}-{out['target']['ticker']}-{out['asOf'].replace('-', '')}-"
                       f"{hashlib.sha1(body.encode()).hexdigest()[:8]}")
    return out, p05_errs


def link_errors(c):
    """팀 contract.link_errors와 같은 규칙. 반대 근거(counter)까지 검사한다(계약 4장 결정 항목 3 제안)."""
    ids = {e["evidenceId"] for e in c["evidence"]}
    errs, seen = [], set()
    for x in c["claims"]:
        if x["claimId"] in seen:
            errs.append(f"claimId 중복 {x['claimId']}")
        seen.add(x["claimId"])
        if x["type"] in ("fact", "interpretation") and not x["evidenceIds"]:
            errs.append(f"{x['claimId']}: 근거 없는 {x['typeLabel']}")
    for field in ("claims", "downsideRisks", "upsideFactors", "unverified", "personSentiment") + TABLES:
        for x in c.get(field) or []:
            bad = [e for e in x.get("evidenceIds") or [] if e not in ids]
            if bad:
                errs.append(f"{field}: 없는 근거 ID {bad}")
    return errs


def main(src, dst=None):
    sys.stdout.reconfigure(encoding="utf-8")
    doc = json.loads(Path(src).read_text(encoding="utf-8"))
    out, p05_errs = convert(doc)
    if p05_errs:
        print(f"P05 원본 계약 오류 {len(p05_errs)}건 — 변환하지 않음")
        for e in p05_errs:
            print(" -", e)
        return 1
    schema = json.loads(TEAM_SCHEMA.read_text(encoding="utf-8"))
    schema_errs = [f"{'/'.join(map(str, e.path)) or '(최상위)'}: {e.message}"
                   for e in Draft202012Validator(schema).iter_errors(out)]
    errs = schema_errs + link_errors(out)
    print(f"{out['reportId']} | 주장 {len(out['claims'])} · 보류 {len(out['personSentiment'])} · "
          f"근거 {len(out['evidence'])} · 미확인 {len(out['unverified'])} | 팀 스키마 오류 {len(schema_errs)}건 · "
          f"연결 오류 {len(errs) - len(schema_errs)}건")
    for e in errs:
        print(" -", e)
    if dst and not errs:
        Path(dst).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("저장:", dst)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
