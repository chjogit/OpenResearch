"""P05 핵심 산출물 3개(약속–실행·자본배분 연표·쟁점과 해명)를 회사별 출력으로 묶고 팀 계약 r4-1.3으로 바꾼다.

흐름
1) data/의 세 CSV(promise_execution·capital_allocation_timeline·issue_response_*)를 읽는다
2) 회사마다 P05 원본(초안 0.2)을 만든다
   - data/governance_rules_<회사>_<기준일>.json(노트북 규칙 13개, scripts/export_notebook_rules.py)이 있으면 먼저 넣는다.
     노트북 근거 E01~E20·규칙 G01~G13·F01~F02·P01은 번호를 그대로 두고, 표에서 나온 근거·주장은 그 뒤로 잇는다
   - outputs/contract_sentiment_<회사>_<기준일>.json(대상 감성, 보류 S01…)이 있으면 그다음에 넣는다(근거 N·R 번호 유지)
   - 근거: DART 공시는 접수번호마다 하나(E01…), 보도 묶음은 묶음마다 하나(N001…, 기사 제목은 넣지 않는다)
   - 주장으로 올리는 것: 판정이 난 약속(이행·부분 이행·미달, 규칙 PE01), 취득 뒤 소각 사실,
     답이 분명한 공시 쟁점(부인·이사회 결의·법원 결정)
   - 주장으로 올리지 않는 것: 판정 보류·진행 중 약속, 미확정 해명, 보도 쟁점 묶음 → unresolved와 표에만 둔다
   - 주장 문장에는 날짜와 규칙 기준값 말고는 숫자를 쓰지 않는다(숫자는 근거 값에 있다)
3) P05 검사기 → schema/to_team_contract.convert() → 팀 스키마·연결 규칙 검사. 오류가 있으면 저장하지 않는다

출력: outputs/p05_governance_<회사>_<기준일>.json(원본 0.2), outputs/team_contract_p05_<회사>_<기준일>.json(r4-1.3)

사용 방법(프로젝트 폴더에서):
  .venv-sentiment\\Scripts\\python.exe scripts\\build_governance_contract.py
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys

import pandas as pd
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "schema"))
import dart_person_roster as D
import disclosure_weak_label as W
import promise_execution as PE
import to_team_contract as T
import validate_output as V

DATA, OUT = ROOT / "data", ROOT / "outputs"
AS_OF = W.AS_OF
TAG = AS_OF.replace("-", "")
KST = timezone(timedelta(hours=9))
PE_RULE = {"ruleId": "PE01", "thresholdStatus": "draft",
           "criterion": "실행 공시 값이 약속 값의 95% 이상이면 이행(긍정), 50% 이상이면 부분 이행(중립), 그 아래는 미달(주의)"}
SIGNAL = {"이행": "긍정", "부분 이행": "중립", "미달": "주의"}
# 주장으로 올리는 답: 법원 결정·이사회 결의처럼 공시에 결과가 적힌 것만. '부인'은 규칙 분류라 표에만 둔다
CLEAR_ANSWER = ("이사회 결의로 답", "법원 결정")


def val(v):
    return None if pd.isna(v) else v


class Evidence:
    """근거 목록. 같은 접수번호·같은 보도 묶음은 한 번만 넣는다."""

    def __init__(self, report_nm):
        self.items, self.by_key, self.report_nm = [], {}, report_nm

    def next_id(self, prefix, width):
        n = max([int(x["evidenceId"][1:]) for x in self.items if x["evidenceId"][0] == prefix] or [0])
        return f"{prefix}{n + 1:0{width}d}"

    def dart(self, rcept_no, value=None, unit=None, quote=None):
        rcept_no = str(rcept_no)
        if rcept_no not in self.by_key:
            day = f"{rcept_no[:4]}-{rcept_no[4:6]}-{rcept_no[6:8]}"
            e = {"evidenceId": self.next_id("E", 2),
                 "sourceType": "DART_DISCLOSURE", "verificationStatus": "공시", "sourceTag": f"[공시 {rcept_no}]",
                 "item": self.report_nm.get(rcept_no, "DART 공시"), "dataDate": day, "publishedAt": day,
                 "publishedAtSource": "RCEPT_NO", "rceptNo": rcept_no,
                 "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"}
            if value is not None:
                e.update(value=float(value), unit=unit or "")
            if quote:
                e["quote"] = quote
            self.items.append(e)
            self.by_key[rcept_no] = e
        elif quote and "quote" not in self.by_key[rcept_no]:   # 먼저 인용 없이 등록된 공시(후속 공시 등)
            self.by_key[rcept_no]["quote"] = quote
        return self.by_key[rcept_no]["evidenceId"]

    def news(self, r):
        key = ("news", r["topic"])
        if key not in self.by_key:
            e = {"evidenceId": self.next_id("N", 3),
                 "sourceType": "NEWS", "verificationStatus": "보도", "sourceTag": "[보도]",
                 "item": f"보도 묶음 기사 수(주제 {r['topic']}, 제목 속 인물 {r['targets']})",
                 "value": float(r["n_articles"]), "unit": "건",
                 "dataDate": f"{r['first_date'][:7]}~{r['last_date'][:7]}", "publishedAt": r["last_date"],
                 "publishedAtSource": "PAGE"}
            self.items.append(e)
            self.by_key[key] = e
        return self.by_key[key]["evidenceId"]


# ---------------------------------------------------------------------------
# 노트북 규칙 판정(data/governance_rules_<회사>_<기준일>.json, scripts/export_notebook_rules.py) 합치기
# ---------------------------------------------------------------------------
RULE_TEXT = {   # 규칙 예시(schema/example_삼성전자_20261027.json)에서 다듬은 문장. 나머지는 점검 이름으로 만든다
    "G08": "의장과 대표가 분리되어 이사회의 경영진 견제 장치가 갖춰져 있다.",
    "G09": "최종 의사결정자가 이사회 밖에 있어 결정 권한과 법적 책임이 어긋난다.",
}
RULE_FACTS = {   # 규칙 판정이 기대는 공시 사실(예시와 같은 문장). 근거 ID → (주장 문장, 영역, 기대는 규칙)
    "E14": ("이사회 의장은 사외(독립)이사다.", "D", "G08"),
    "E15": ("실질 지배자인 이재용 회장은 등기임원 명단에 없다.", "D", "G09"),
}
COUNTER = {   # 노트북 counter_conditions를 규칙에 붙인다
    "G09": ("등기이사 복귀 안건이 주총에 오르면 판정이 바뀐다.", "G09: 주의 → 중립"),
    "G07": ("보상용 자사주 중 상당량이 소각으로 전환되면 판정이 바뀐다.", "G07: 주의 → 중립"),
}
# 노트북의 옛 에이전트 번호 → 팀 새 번호(팀 nodes.LEGACY_AGENT: 1→3, 3→4·6). 2번은 새 번호 미확인
OLD_AGENT = {"3번 수급": "agent4(수급)", "1번 거시·정책": "agent3(거시경제·정책)", "2번 사업모델": "2번 사업모델(새 번호 미확인)"}


def url_date(url):
    """기사 URL 속 날짜(YYYYMMDD 또는 /YYYY/MM/DD/). 없으면 None."""
    import re
    m = re.search(r"(20\d{2})/(\d{2})/(\d{2})/", url or "") or re.search(r"(20\d{2})(\d{2})(\d{2})\d*", url or "")
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{mo}-{d}" if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31 else None


def rule_part(path, ev):
    """노트북 근거 20건·규칙 13개를 P05 근거·주장으로 바꾼다. 근거 ID와 규칙 번호(G01~G13)는 노트북 그대로다."""
    data = json.loads(path.read_text(encoding="utf-8"))
    unresolved, claims = [], []
    for r in sorted(data["evidence"], key=lambda x: x["evidence_id"]):   # 노트북 표는 E19·E20이 E14 앞에 있다
        eid, state = r["evidence_id"], r["상태"]
        e = {"evidenceId": eid, "item": r["항목"], "verificationStatus": state, "dataDate": r["기준일"],
             "value": r["값"], "unit": r["단위"]}
        if state == "공시":
            no = r["rcept_no"]
            e.update(sourceType="DART_DISCLOSURE", sourceTag=f"[공시 {no}]", rceptNo=no, url=r["출처"],
                     publishedAt=f"{no[:4]}-{no[4:6]}-{no[6:8]}", publishedAtSource="RCEPT_NO")
        else:
            pub = url_date(r["출처"])
            e.update(sourceType="NEWS", sourceTag=f"[{state}]", publishedAt=pub,
                     publishedAtSource="URL" if pub else "UNKNOWN")
            if r["출처"]:
                e["url"] = r["출처"]
        if state == "보도 상충" and r.get("대안값") is not None:
            e["altValue"] = {"value": r["대안값"], "url": r.get("대안값_출처") or r["출처"]}
        if r.get("비고"):
            e["quote"] = r["비고"]
        ev.items.append({k: v for k, v in e.items() if v is not None or k in ("dataDate", "publishedAt", "value")})
    used = {}
    for i, r in enumerate(data["result"], 1):
        gid = f"G{i:02d}"   # 노트북 RULES 순서 = 메모의 claim_id
        c = {"claimId": gid, "claimType": "interpretation", "kind": "governance_rule", "area": r["area"],
             "statement": RULE_TEXT.get(gid, f"'{r['점검']}' 점검의 규칙 판정은 '{r['signal']}'이다."),
             "evidenceIds": r["evidence_ids"], "signal": r["signal"],
             "rule": {"ruleId": gid, "criterion": r["판정 기준"], "thresholdStatus": "draft"},
             "reportStatus": "conditional_interpretation"}
        if r.get("비고"):
            c["note"] = r["비고"]
        if gid in COUNTER:
            c["counterEvidence"] = [{"statement": COUNTER[gid][0], "effect": COUNTER[gid][1]}]
        claims.append(c)
        for e in r["evidence_ids"]:
            used.setdefault(e, []).append(gid)
    for k, (eid, (text, area, gid)) in enumerate(RULE_FACTS.items(), 1):
        claims.insert(k - 1, {"claimId": f"F{k:02d}", "claimType": "fact", "kind": "disclosed_fact", "area": area,
                              "statement": text, "evidenceIds": [eid], "reportStatus": "confirmed_fact"})
        next(c for c in claims if c["claimId"] == gid)["basedOnClaimIds"] = [f"F{k:02d}"]
    claims.append({"claimId": "P01", "claimType": "forecast", "kind": "scheduled_event", "area": "A",
                   "statement": "예정된 증여가 끝나면 이재용 회장 지분율은 1.75%가 된다는 보도가 있다.",
                   "evidenceIds": ["E03"], "reportStatus": "conditional_interpretation"})
    used.setdefault("E03", []).append("P01")
    for u in data["memo"]["unresolved"]:
        unresolved.append({"evidenceId": u["evidence_id"], "item": u["item"], "reason": u["reason"],
                           "affectsClaimIds": used.get(u["evidence_id"], [])})
    for e in ev.items:
        if e.get("publishedAt") is None:
            unresolved.append({"evidenceId": e["evidenceId"], "item": f"{e['item']} 공개일 미상", "reason": "DATE_UNKNOWN",
                               "affectsClaimIds": used.get(e["evidenceId"], [])})
    assumptions = [{"statement": a, "affectsClaimIds": ["G03"]} for a in data["memo"]["assumptions"]]
    assumptions.append({"statement": "증여가 예정일(2026-11-12)에 완료된다.", "affectsClaimIds": ["P01"]})
    handoff = [{"toAgentId": OLD_AGENT.get(h["to"], h["to"]), "item": h["item"],
                "claimIds": ["G01", "P01"] if "지분" in h["item"] else []} for h in data["memo"]["handoff"]]
    return claims, unresolved, assumptions, handoff, data["data_mode"]


def sentiment_part(path, ev):
    """대상 감성 출력(outputs/contract_sentiment_<회사>_<기준일>.json, 초안 0.1)의 보류 주장·근거를 그대로 넣는다.
    근거 N·R 번호는 원래 행과 묶여 있어 바꾸지 않는다. 표의 보도 묶음 근거는 그 뒤 번호를 쓴다(next_id가 최댓값 기준)."""
    s = json.loads(path.read_text(encoding="utf-8"))
    taken = {e["evidenceId"] for e in ev.items}
    clash = [e["evidenceId"] for e in s["evidence"] if e["evidenceId"] in taken]
    if clash:
        raise ValueError(f"감성 근거 번호가 겹친다: {clash}")
    ev.items.extend(s["evidence"])
    return s["claims"], s["unresolved"], s.get("qualityFlags", [])


def build_doc(name, code, corp_code, pe, tl, disc, news):
    report_nm = dict(zip(*PE.filings(code)[["rcept_no", "report_nm"]].values.T))
    ev = Evidence(report_nm)
    claims, unresolved, n_f, n_g = [], [], 0, 0
    assumptions, rule_handoff, rule_mode = [], [], None
    rules = DATA / f"governance_rules_{name}_{TAG}.json"
    if rules.exists():
        claims, unresolved, assumptions, rule_handoff, rule_mode = rule_part(rules, ev)
        n_f = sum(c["claimId"][0] == "F" for c in claims)
        n_g = sum(c["claimId"][0] == "G" for c in claims)
    senti_flags = []
    senti = OUT / f"contract_sentiment_{name}_{TAG}.json"
    if senti.exists():   # 표의 보도 근거보다 먼저 넣어야 N 번호가 겹치지 않는다
        s_claims, s_unresolved, senti_flags = sentiment_part(senti, ev)
        claims += s_claims
        unresolved += s_unresolved

    def add_claim(**c):
        nonlocal n_f, n_g
        if c["claimType"] == "fact":
            n_f += 1
            c["claimId"] = f"F{n_f:02d}"
        else:
            n_g += 1
            c["claimId"] = f"G{n_g:02d}"
        claims.append(c)
        return c["claimId"]

    # 자본배분 연표(근거 값은 연표 금액 또는 주식수)
    capital = []
    for _, r in tl.iterrows():
        amt, sh = val(r["amount"]), val(r["shares"])
        eid = ev.dart(r["rcept_no"], amt if amt else sh, "원" if amt else "주", val(r["detail"]) or None)
        capital.append({"date": r["date"], "event": r["event"], "category": r["category"],
                        "amount": float(amt) if amt else None, "shares": float(sh) if sh else None,
                        "detail": val(r["detail"]) or "", "correctionRceptNos": val(r["correction"]),
                        "evidenceIds": [eid]})

    # 약속–실행
    promises, held, ongoing = [], [], []
    for _, r in pe.iterrows():
        eids = []
        if val(r["promise_rcept_no"]):
            eids.append(ev.dart(r["promise_rcept_no"], val(r["plan_value"]), val(r["unit"]) or None))
        for x in str(val(r["execution_rcept_no"]) or "").split("|"):
            if x:
                eids.append(ev.dart(x, val(r["actual_value"])))
        follow = val(r.get("followup_rcept_no"))
        if follow:
            eids.append(ev.dart(follow))
        row = {"promiseType": r["promise_type"], "promiseDate": val(r["promise_date"]), "promise": r["promise"],
               "execution": val(r["execution"]), "followup": val(r.get("followup")),
               "rate": float(r["rate"]) if val(r["rate"]) is not None else None, "verdict": r["verdict"],
               "evidenceIds": eids, "note": val(r["note"]) or ""}
        if r["verdict"] in SIGNAL:
            what = "자사주 취득 결정은" if r["promise_type"] == "자사주 취득" else "기업가치제고계획의 소각 수량 목표는"
            row["claimId"] = add_claim(
                claimType="interpretation", kind="governance_rule", area="C" if r["promise_type"] == "자사주 취득" else "B",
                statement=f"{r['promise_date']} {what} 실행 공시 기준 '{r['verdict']}'으로 판정했다.",   # 규칙 ID는 rule에 둔다
                evidenceIds=eids[:2] if follow else eids, signal=SIGNAL[r["verdict"]], rule=PE_RULE,
                reportStatus="conditional_interpretation")
            if follow:
                add_claim(claimType="fact", kind="disclosed_fact", area="C",
                          statement=f"{r['promise_date']} 결정으로 취득한 자사주와 수량이 같은 주식소각결정이 뒤따랐다.",
                          evidenceIds=eids[1:], reportStatus="confirmed_fact")
        elif r["verdict"] == "판정 보류" and eids:
            held.append(eids[0])
        elif r["verdict"] == "진행 중" and eids:
            ongoing.append(eids[0])
        promises.append(row)
    if held:
        unresolved.append({"evidenceId": held[0], "reason": "NO_DATA", "affectsClaimIds": [],
                           "item": f"기업가치제고계획 숫자 목표 {len(held)}개는 실적 자료가 없어 판정 보류"})
    for e in dict.fromkeys(ongoing):
        unresolved.append({"evidenceId": e, "reason": "NO_DATA", "affectsClaimIds": [],
                           "item": "자사주 취득 결정 진행 중(결과 공시 전)"})

    # 쟁점과 해명
    issues = []
    for _, r in disc.iterrows():
        eid = ev.dart(r["rcept_no"], quote=val(r["issue"]) or None)
        row = {"source": "공시", "date": r["date"], "kind": r["kind"], "topic": r["topic"],
               "issue": val(r["issue"]), "answer": val(r["answer"]), "status": r["answer_kind"], "evidenceIds": [eid]}
        if val(r["followup_rcept_no"]):
            row["followupEvidenceIds"] = [ev.dart(r["followup_rcept_no"])]
        if str(r["answer_kind"]).startswith(CLEAR_ANSWER):
            issue = str(r["issue"]).rstrip("…")
            text = (f"{issue}에서 회사는 이사회 결의 내용을 밝혔다." if r["answer_kind"] == "이사회 결의로 답"
                    else f"'{issue}' 사건은 {r['answer_kind']}으로 공시됐다.")
            row["claimId"] = add_claim(claimType="fact", kind="disclosed_fact",
                                       area="E" if "소송" in r["kind"] else "A", statement=text,
                                       evidenceIds=[eid], reportStatus="confirmed_fact")
        issues.append(row)
    for _, r in news.iterrows():
        ids = [int(x) for x in f"{val(r['issue_doc_ids']) or ''}|{val(r['response_doc_ids']) or ''}".split("|") if x]
        issues.append({"source": "보도", "period": f"{r['first_date']}~{r['last_date']}", "topic": r["topic"],
                       "status": r["status"], "targets": r["targets"], "nArticles": int(r["n_articles"]),
                       "nConflictArticles": int(r["n_conflict_articles"]),
                       "nResponseArticles": int(r["n_response_articles"]),
                       "docIds": list(dict.fromkeys(ids)), "evidenceIds": [ev.news(r)]})
    if len(news):
        unresolved.append({"reason": "LINK_UNVERIFIED", "affectsClaimIds": [],
                           "item": "보도 쟁점 묶음은 제목 규칙 결과라 주장으로 올리지 않았다(제목 속 인물이 당사자인지 미확인)"})

    if sum(e["evidenceId"][0] == "E" for e in ev.items) > 99:
        raise ValueError(f"{name}: DART 근거가 99건을 넘는다(근거 ID 형식 E00)")
    return {
        "schemaVersion": "0.2-draft", "reportId": f"RPT-P05-{TAG}-{code}", "agentId": T.AGENT["module"],
        "perspective": "경영진·대주주",
        "subject": {"companyName": name, "stockCode": code, "corpCode": corp_code},
        "asOf": AS_OF, "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "dataMode": ("DART 공시 목록·원문 + 기사 제목 규칙(제목 미복사)"
                     + (f" + 노트북 규칙 판정({rule_mode})" if rule_mode else "")), "completeness": "partial",
        "claims": claims, "evidence": ev.items, "unresolved": unresolved, "assumptions": assumptions,
        "handoff": rule_handoff + [
            {"toAgentId": "가치·위험(번호 미확인)",
             "item": "자본배분 연표의 배당·자사주·투자 금액은 공시 원문 값이다. 주당가치·밸류에이션 영향은 가치·위험 관점이 계산한다."},
            {"toAgentId": "agent6(투자심리·뉴스)",
             "item": "보도 쟁점 묶음은 제목 속 경영진·대주주 기준이다. 종목 전체 분위기·언급량은 에이전트 6이 본다."}],
        "qualityFlags": ["THRESHOLDS_DRAFT", "RULE_BASED_EXTRACTION", "NEWS_TITLE_RULES_UNREVIEWED"]
                        + (["SAME_TOPIC_DIFFERENT_BASIS"] if rule_mode else [])   # G07(보도·의결액)과 연표(공시 결정)가 같은 자사주를 다른 기준으로 잰다
                        + senti_flags,
        "disclaimer": "투자 권유가 아니다. 판정은 공시끼리 맞댄 규칙 결과이며 기준값은 팀 합의 전 초안이다.",
        "promiseExecution": promises, "capitalAllocation": capital, "issues": issues,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    roster = pd.read_csv(DATA / "person_target_roster_dart_20261027.csv", dtype=str)
    code_of = (roster.drop_duplicates("company_name").set_index("company_name")["company_id"]
               .str.replace("KRX:", "", regex=False).to_dict())
    corp = D.corp_codes(D.load_key())
    read = lambda f: pd.read_csv(DATA / f, dtype={"stock_code": str, "promise_rcept_no": str, "execution_rcept_no": str,
                                                   "followup_rcept_no": str, "rcept_no": str, "correction": str})
    pe, tl = read(f"promise_execution_dev_{TAG}.csv"), read(f"capital_allocation_timeline_dev_{TAG}.csv")
    disc, news = read(f"issue_response_disclosure_dev_{TAG}.csv"), read(f"issue_response_news_dev_{TAG}.csv")
    p05_schema = Draft202012Validator(json.loads(V.SCHEMA_PATH.read_text(encoding="utf-8")))
    team_schema = Draft202012Validator(json.loads(T.TEAM_SCHEMA.read_text(encoding="utf-8")))
    bad = 0
    for name in W.training_companies(roster):
        code = code_of[name]
        pick = lambda df: df[df["company_name"] == name]
        doc = build_doc(name, code, corp[code]["corp_code"], pick(pe), pick(tl), pick(disc), pick(news))
        errs = [f"P05 형식 {'/'.join(map(str, e.path))}: {e.message}" for e in p05_schema.iter_errors(doc)]
        errs = errs or V.contract_errors(doc)
        team, _ = T.convert(doc) if not errs else (None, None)
        if team:
            errs += [f"팀 형식 {'/'.join(map(str, e.path))}: {e.message}" for e in team_schema.iter_errors(team)]
            errs += T.link_errors(team)
        print(f"{name}: 주장 {len(doc['claims'])} · 근거 {len(doc['evidence'])} · 약속 {len(doc['promiseExecution'])} "
              f"· 연표 {len(doc['capitalAllocation'])} · 쟁점 {len(doc['issues'])} | 오류 {len(errs)}건"
              + (f" | {team['reportId']}" if team else ""))
        for e in errs[:10]:
            print("  -", e)
        if errs:
            bad += 1
            continue
        (OUT / f"p05_governance_{name}_{TAG}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / f"team_contract_p05_{name}_{TAG}.json").write_text(json.dumps(team, ensure_ascii=False, indent=2),
                                                                  encoding="utf-8")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
