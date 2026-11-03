"""경영진·대주주 에이전트 출력 검사기 (초안 0.1·0.2).

사용: python validate_output.py <출력.json>
1) JSON Schema 형식 검사
2) 스키마로 표현하기 어려운 계약 규칙 검사
   - 참조 ID(evidenceIds, basedOnClaimIds, affectsClaimIds)가 실제로 있는가
   - 공개시각이 기준일(asOf)보다 늦은 근거가 없는가(미래정보 누수)
   - 공개시각을 모르는 근거는 unresolved에 DATE_UNKNOWN으로 올렸는가
   - 출처 태그가 확인 상태·접수번호와 맞는가
   - 미확인 근거에 기댄 판정이 '자료 없음' 또는 보류인가
   - 검증 전 감성은 확인 사실이 될 수 없는가
   - 주장 문장의 숫자가 근거 값(또는 규칙 기준값)에서 왔는가(숫자 생성 금지)
"""
from pathlib import Path
import json
import re
import sys

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("governance_agent_output.schema.json")


def contract_errors(doc):
    errs = []
    ev = {e["evidenceId"]: e for e in doc["evidence"]}
    cl = {c["claimId"]: c for c in doc["claims"]}
    as_of = doc["asOf"]
    unknown_dates = {(u.get("evidenceId"), u["reason"]) for u in doc["unresolved"]}

    for c in doc["claims"]:
        cid = c["claimId"]
        for e in c["evidenceIds"]:
            if e not in ev:
                errs.append(f"{cid}: 없는 근거 {e}")
        for b in c.get("basedOnClaimIds", []):
            if b not in cl:
                errs.append(f"{cid}: 없는 주장 {b}")
        used = [ev[e] for e in c["evidenceIds"] if e in ev]
        if any(e["verificationStatus"] == "미확인" for e in used) and \
                c.get("signal") not in (None, "자료 없음") and c["reportStatus"] != "hold":
            errs.append(f"{cid}: 미확인 근거에 기댄 판정은 '자료 없음' 또는 보류여야 함")
        s = c.get("sentiment")
        if s and s["validationStatus"] == "UNVALIDATED" and c["reportStatus"] == "confirmed_fact":
            errs.append(f"{cid}: 검증 전 감성은 확인 사실이 될 수 없음")
        # 숫자 생성 금지: 날짜를 지운 뒤 남은 숫자가 근거 값·대안값·규칙 기준값에 있는지 본다
        allowed = set()
        for e in used:
            for v in (e.get("value"), (e.get("altValue") or {}).get("value")):
                if isinstance(v, (int, float)):
                    allowed.add(float(v))
            for n in re.findall(r"\d+(?:\.\d+)?", e.get("quote", "")):
                allowed.add(float(n))
        for n in re.findall(r"\d+(?:\.\d+)?", (c.get("rule") or {}).get("criterion", "")):
            allowed.add(float(n))
        text = re.sub(r"\d{4}-\d{2}(-\d{2})?", "", c["statement"])
        for n in re.findall(r"\d+(?:\.\d+)?", text):
            if float(n) not in allowed:
                errs.append(f"{cid}: 문장 숫자 {n}이 근거 값에 없음")

    for e in doc["evidence"]:
        eid, pub = e["evidenceId"], e.get("publishedAt")
        if pub and pub[:len(as_of)] > as_of:
            errs.append(f"{eid}: 공개시각 {pub}이 기준일 {as_of}보다 늦음(미래정보)")
        if pub is None and (eid, "DATE_UNKNOWN") not in unknown_dates:
            errs.append(f"{eid}: 공개시각을 모르면 unresolved에 DATE_UNKNOWN으로 올려야 함")
        want = f"[공시 {e['rceptNo']}]" if e["verificationStatus"] == "공시" and e.get("rceptNo") \
            else f"[{e['verificationStatus']}]"
        if e["sourceTag"] != want:
            errs.append(f"{eid}: 출처 태그 {e['sourceTag']} ≠ {want}")
        if e.get("rceptNo") and pub and e.get("publishedAtSource") == "RCEPT_NO" and \
                pub.replace("-", "") != e["rceptNo"][:8]:
            errs.append(f"{eid}: 공개시각이 접수번호 앞 8자리와 다름")

    for group in ("unresolved", "assumptions"):
        for u in doc[group]:
            for a in u["affectsClaimIds"]:
                if a not in cl:
                    errs.append(f"{group}: 없는 주장 {a}")
    for h in doc["handoff"]:
        for a in h.get("claimIds", []):
            if a not in cl:
                errs.append(f"handoff: 없는 주장 {a}")
    for group in ("promiseExecution", "capitalAllocation", "issues"):   # 0.2 표: 근거·주장 참조가 실제로 있는가
        for row in doc.get(group, []):
            for e in row.get("evidenceIds", []) + row.get("followupEvidenceIds", []):
                if e not in ev:
                    errs.append(f"{group}: 없는 근거 {e}")
            if row.get("claimId") and row["claimId"] not in cl:
                errs.append(f"{group}: 없는 주장 {row['claimId']}")
    return errs


def main(path):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    schema_errs = [f"{'/'.join(map(str, e.path)) or '(최상위)'}: {e.message}"
                   for e in Draft202012Validator(schema).iter_errors(doc)]
    errs = schema_errs or contract_errors(doc)   # 형식이 틀리면 계약 규칙은 건너뛴다
    print(f"형식 오류 {len(schema_errs)}건 | 계약 규칙 오류 {0 if schema_errs else len(errs)}건")
    for e in errs:
        print(" -", e)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
