"""P05 약속–실행 대조표: 회사가 공시로 약속한 자본배분을 실제로 지켰는지 공시끼리 맞대어 본다.

대조하는 약속(v1)
1) 자사주 취득: 주요사항보고서(자기주식취득결정)의 예정 금액·주식수·기간
   ↔ 자기주식취득결과보고서의 취득 총액·주식수 (결과보고서에 적힌 '주요사항보고서 제출일'로 짝을 짓는다)
2) 취득 뒤 소각: 결과보고서의 취득 주식수와 1% 안에서 같은 뒤의 주식소각결정이 있으면 followup에 적는다
   (목적이 '주가 안정'이어도 실제로 소각했는지 보인다)
3) 기업가치제고계획 목표: '2. 주요 내용'에서 숫자·단위가 있는 항목을 뽑는다.
   - 'N만주 소각'처럼 수량이 적힌 목표는 주식소각결정과 수량으로 대조한다
   - 그 밖의 목표는 실적 자료가 필요해 '판정 보류'
   - 회사가 같은 공시에 적은 실적은 '이행 현황(회사 자체 보고) / 검증 전' 행으로 따로 둔다
- 약속 공시가 하나도 없는 회사는 '약속 공시 없음 / 자료 없음' 한 행을 둔다(빈 회사가 빠져 보이지 않게)

판정(규칙, 기준값은 팀 합의 전 초안)
- 이행: 이행률 95% 이상 / 부분 이행: 50% 이상 / 미달: 50% 미만
- 진행 중: 결과 공시가 없고 예정 기간이 기준일 뒤에 끝난다
- 결과 미확인: 예정 기간이 끝났는데 결과 공시를 찾지 못했다
- 판정 보류: 숫자 대조 자료가 없다(기업가치제고계획 목표 등)

지키는 규칙
- 판정은 규칙이 한다. 숫자는 공시 원문 값만 쓴다(계산은 이행률 나눗셈뿐).
- 기준일(AS_OF) 뒤 공시는 쓰지 않는다(미래정보 누수 방지).
- 모든 행에 약속·실행 근거 접수번호(rcept_no)를 둔다.
- 원문은 data/dart_raw/docs/에 보관하고 다시 받지 않는다. 키 값은 출력하지 않는다.
- 학습이 아니라 분석이다. 대상은 dev 6곳이다(holdout 회사는 이 표에도 넣지 않는다).

사용 방법(프로젝트 폴더에서):
  .venv-sentiment\\Scripts\\python.exe scripts\\promise_execution.py
"""
from pathlib import Path
import html
import io
import json
import re
import sys
import time
import zipfile

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dart_person_roster as D
import disclosure_weak_label as W

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA = PROJECT_DIR / "data"
OUT = PROJECT_DIR / "outputs"
DOC_DIR = D.RAW_DIR / "docs"
AS_OF = W.AS_OF
TAG = AS_OF.replace("-", "")
RULE_VERSION = "promise-v1-20261103"
DONE, PARTIAL = 0.95, 0.50   # 이행률 기준값(팀 합의 전 초안)


# ---------------------------------------------------------------------------
# 원자료
# ---------------------------------------------------------------------------
def filings(code):
    """data/dart_raw의 공시 목록(기준일까지). 정정 공시는 원 공시 대신 쓰지 않고 따로 표시만 한다."""
    rows = json.loads((D.RAW_DIR / f"{code}_list_{W.START.replace('-', '')}_{TAG}.json").read_text(encoding="utf-8"))
    df = pd.DataFrame(rows)
    df["nm"] = df["report_nm"].str.replace(r"\s+", "", regex=True)
    df = df[df["rcept_dt"] <= TAG]
    sub = df["nm"].str.contains("자회사의주요경영사항|종속회사의주요경영사항")
    return df[~sub].sort_values("rcept_no").reset_index(drop=True)


def doc_text(key, rcept_no):
    """공시 원문(document API)을 받아 보관하고, 표 칸을 ' | '로 나눈 글로 바꾼다."""
    path = DOC_DIR / f"{rcept_no}.xml"
    if not path.exists():
        r = requests.get(f"{D.API}/document.xml", params={"crtfc_key": key, "rcept_no": rcept_no}, timeout=60)
        r.raise_for_status()
        time.sleep(0.3)
        if r.content[:2] != b"PK":
            return None   # 원문 없음(014 등)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        main = min(z.namelist(), key=len)   # 본문 파일(첨부보다 이름이 짧다)
        DOC_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(z.read(main))
    raw = path.read_bytes()
    for enc in ("utf-8", "cp949"):
        try:
            t = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    t = re.sub(r"<STYLE.*?</STYLE>|<style.*?</style>", " ", t, flags=re.S)
    t = re.sub(r"<(TR|tr)[ >]", "\n<", t)
    t = re.sub(r"<(TD|TH|TE|TU|td|th)[ >]", " | <", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def num(s):
    s = str(s).replace(",", "").strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def kdate(s):
    """'2026년 09월 30일' / '2026-09-30' / '2026.09.30' → '2026-09-30'."""
    m = re.search(r"(\d{4})\s*[년.\-]\s*(\d{1,2})\s*[월.\-]\s*(\d{1,2})", str(s))
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


def cells(text):
    return [c.strip() for c in re.split(r"\s*\|\s*|\n", text) if c.strip()]


# ---------------------------------------------------------------------------
# 1) 자사주 취득 결정 ↔ 결과보고서
# ---------------------------------------------------------------------------
def buyback_decisions(key, corp_code):
    j = D.get_json(key, "tsstkAqDecsn", {"corp_code": corp_code, "bgn_de": W.START.replace("-", ""), "end_de": TAG})
    rows = j.get("list", []) if j.get("status") == "000" else []
    out = []
    for r in rows:
        amt = (num(r.get("aqpln_prc_ostk")) or 0) + (num(r.get("aqpln_prc_estk")) or 0)
        shares = (num(r.get("aqpln_stk_ostk")) or 0) + (num(r.get("aqpln_stk_estk")) or 0)
        out.append({"rcept_no": r["rcept_no"], "board_date": kdate(r.get("aq_dd")),
                    "plan_amount": amt or None, "plan_shares": shares or None,
                    "period_start": kdate(r.get("aqexpd_bgd")), "period_end": kdate(r.get("aqexpd_edd")),
                    "purpose": str(r.get("aq_pp", "")).strip(), "method": str(r.get("aq_mth", "")).strip()})
    return pd.DataFrame(out)


def parse_buyback_result(text):
    """결과보고서: 짝 지을 결정 제출일, 취득 총액(보통+기타), 취득 주식수(3. 취득내용의 '계' 행)."""
    m = re.search(r"주요사항보고서\s*제출일\s*:?\s*\|?\s*([0-9년월일 .\-]+)", text)
    decided = kdate(m[1]) if m else None
    amount = None
    sec4 = re.search(r"\n\s*4\.(.*?)(?=\n\s*5\.)", text, flags=re.S)   # 4. 취득 예정 내용과 실제 취득 내용의 일치 여부
    if sec4:
        vals = [c for c in cells(sec4[1]) if num(c) is not None or c == "-"]
        if len(vals) >= 4:
            amount = sum(num(v) or 0 for v in vals[2:4]) or None   # [예정 보통, 예정 기타, 총액 보통, 총액 기타]
    shares = None
    sec3 = re.search(r"\n\s*3\.(.*?)(?=\n\s*4\.)", text, flags=re.S)   # 3. 취득내용: 일자 | 종류 | 주문수량 | 취득수량 | ...
    if sec3:
        c = cells(sec3[1])
        tot = sum(num(c[i + 3]) or 0 for i in range(len(c) - 3)
                  if kdate(c[i]) and "주식" in c[i + 1] and num(c[i + 3]) is not None)
        shares = tot or None
    return decided, amount, shares


# ---------------------------------------------------------------------------
# 2) 주식소각결정
# ---------------------------------------------------------------------------
def parse_retirement(text):
    m = re.search(r"소각할\s*주식의\s*종류와\s*수(.*?)2\.\s*발행주식", text, flags=re.S)
    shares = sum(num(c) or 0 for c in cells(m[1]) if num(c) is not None) if m else None
    m = re.search(r"소각예정금액\s*\(원\)\s*\|?\s*([\d,]+)", text)
    amount = num(m[1]) if m else None
    m = re.search(r"소각\s*예정일\s*\|?\s*([0-9\-.년월일 ]+)", text)
    src = re.search(r"소각할\s*주식의\s*취득방법\s*\|?\s*([^\n|]+)", text)
    return shares or None, amount, kdate(m[1]) if m else None, src[1].strip() if src else ""


# ---------------------------------------------------------------------------
# 3) 기업가치제고계획 목표 문장
# ---------------------------------------------------------------------------
UNIT = re.compile(r"\d[\d,.]*\s*(%|배|조\s*원|조원|억\s*원|억원|만\s*주|만주|원|조)")
GOAL_WORDS = re.compile(r"목표|계획|추진|예정|이상|까지")
REPORT_HEAD = re.compile(r"이행\s*현황|이행\s*실적|성과")


def value_up_clauses(text):
    """'2. 주요 내용' 안에서 숫자와 단위가 있는 항목만 뽑는다(공시 원문, 각 160자 이내). 판정은 하지 않는다.
    나누는 규칙: 목표 낱말이 없고 '달성'이 있거나, '이행 현황·성과' 제목 아래 항목이면 회사 자체 보고 실적."""
    m = re.search(r"주요\s*내용(.*?)(?:\n\s*3\.\s*조세특례|$)", text, flags=re.S)
    body = re.sub(r"\s+", " ", m[1] if m else "")
    parts = re.split(r"\s(?=[□■○◦●▶※]|-\s|\d\)\s|\d\.\s|[①-⑩]|<|\[)", body)
    out, under_report = [], False
    for p in parts:
        p = p.strip(" |·-□■○◦●▶※")
        if REPORT_HEAD.search(p) and not re.search(r"계획|목표", p.split(":")[0]):
            under_report = True          # 실적 제목(숫자가 있으면 그 자체도 항목이다)
        elif re.search(r"계획|목표", p) and not UNIT.search(p):
            under_report = False         # 숫자 없는 목표·계획 제목
        if 8 <= len(p) <= 160 and UNIT.search(p):
            reported = ("달성" in p and not re.search(r"목표", p)) or (under_report and not GOAL_WORDS.search(p))
            out.append(("자체 보고 실적" if reported else "목표", p))
    return list(dict.fromkeys(out))


def planned_retire_shares(clause):
    """'911만주 자기주식 소각'처럼 소각 수량이 적힌 목표면 주식수를 돌려준다."""
    m = re.search(r"([\d,.]+)\s*만\s*주[^/]{0,15}소각", clause)
    return float(m[1].replace(",", "")) * 1e4 if m else None


def find_retirement(retire, after_rcept_no, shares, tol=0.01):
    """뒤에 나온 소각결정 중 수량이 tol 안에서 같은 첫 공시."""
    if not shares or not len(retire):
        return None
    c = retire[(retire["rcept_no"] >= after_rcept_no) & retire["shares"].notna()]
    c = c[(c["shares"] - shares).abs() <= shares * tol]
    return c.iloc[0] if len(c) else None


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------
def verdict(rate, has_result, period_end):
    if rate is not None:
        return "이행" if rate >= DONE else "부분 이행" if rate >= PARTIAL else "미달"
    if not has_result:
        return "진행 중" if period_end and period_end > AS_OF else "결과 미확인"
    return "판정 보류"


def build_company(key, code, name, corp_code):
    fl = filings(code)
    rows = []
    results = []
    for _, f in fl[fl["nm"].str.contains("자기주식취득결과보고서")].iterrows():
        t = doc_text(key, f["rcept_no"])
        d, amt, sh = parse_buyback_result(t) if t else (None, None, None)
        results.append({"rcept_no": f["rcept_no"], "rcept_dt": f["rcept_dt"], "decided": d, "amount": amt, "shares": sh})
    results = pd.DataFrame(results, columns=["rcept_no", "rcept_dt", "decided", "amount", "shares"])

    retire = []
    for _, f in fl[fl["nm"].str.contains("주식소각결정") & ~fl["nm"].str.contains("정정")].iterrows():
        t = doc_text(key, f["rcept_no"])
        sh, amt, day, how = parse_retirement(t) if t else (None, None, None, "")
        retire.append({"rcept_no": f["rcept_no"], "rcept_dt": f["rcept_dt"], "shares": sh, "amount": amt,
                       "retire_date": day, "how": how})
    retire = pd.DataFrame(retire, columns=["rcept_no", "rcept_dt", "shares", "amount", "retire_date", "how"])

    dec = buyback_decisions(key, corp_code)
    dec = dec[dec["rcept_no"].str[:8] <= TAG] if len(dec) else dec
    for _, d in dec.sort_values("rcept_no").iterrows() if len(dec) else []:
        filed = f"{d['rcept_no'][:4]}-{d['rcept_no'][4:6]}-{d['rcept_no'][6:8]}"
        res = results[results["decided"] == filed]
        has = len(res) > 0
        amt = res["amount"].sum() if has and res["amount"].notna().any() else None
        sh = res["shares"].sum() if has and res["shares"].notna().any() else None
        rate = (amt / d["plan_amount"]) if amt and d["plan_amount"] else (sh / d["plan_shares"]) if sh and d["plan_shares"] else None
        rows.append({
            "company_name": name, "stock_code": code, "promise_type": "자사주 취득",
            "promise_date": filed, "promise_rcept_no": d["rcept_no"],
            "promise": f"{d['period_start']}~{d['period_end']} 자사주 {d['plan_shares'] or 0:,.0f}주, {(d['plan_amount'] or 0) / 1e8:,.0f}억 원 취득"
                       + (f" (목적: {d['purpose'][:40]})" if d["purpose"] else ""),
            "plan_value": d["plan_amount"], "unit": "원",
            "deadline": d["period_end"],
            "execution_rcept_no": "|".join(res["rcept_no"]) if has else None,
            "execution_date": res["rcept_dt"].max() if has else None,
            "execution": (f"{sh:,.0f}주" if sh else "주식수 추출 실패") + ", "
                         + (f"{amt / 1e8:,.0f}억 원 취득" if amt else "금액 추출 실패") if has else None,
            "actual_value": amt, "rate": rate, "verdict": verdict(rate, has, d["period_end"]),
            "note": "" if has or d["period_end"] else "예정 기간 없음"})
        # 취득한 주식이 그 뒤 소각으로 이어졌나(수량 1% 안에서 일치). 목적과 실제 쓰임을 함께 본다
        r0 = find_retirement(retire, d["rcept_no"], sh) if has else None   # 결과보고서보다 소각결정이 먼저 나올 수 있다
        if r0 is not None:
            rows[-1]["followup"] = f"소각결정 {r0['shares']:,.0f}주 ({r0['retire_date']} 소각 예정)"
            rows[-1]["followup_rcept_no"] = r0["rcept_no"]
        elif "소각" in d["purpose"]:
            rows[-1]["note"] = "목적에 소각을 적었지만 수량이 맞는 소각결정을 찾지 못했다"

    for _, f in fl[fl["nm"].str.contains("기업가치제고계획")].iterrows():
        t = doc_text(key, f["rcept_no"])
        clauses = value_up_clauses(t) if t else []
        day = f"{f['rcept_dt'][:4]}-{f['rcept_dt'][4:6]}-{f['rcept_dt'][6:]}"
        base = {"company_name": name, "stock_code": code, "promise_date": day, "promise_rcept_no": f["rcept_no"],
                "plan_value": None, "unit": None, "deadline": None, "execution_rcept_no": None,
                "execution_date": None, "execution": None, "actual_value": None, "rate": None}
        note = "규칙으로 뽑은 항목이라 사람 확인 필요" + ("" if t else " / 원문 없음")
        goals = [c for k, c in clauses if k == "목표"]
        for c in goals or ["(숫자 목표 자동 추출 없음, 원문·첨부 확인 필요)"]:
            row = {**base, "promise_type": "기업가치제고계획 목표", "promise": c, "verdict": "판정 보류",
                   "note": note + ". 정량 대조에는 실적·환원 실적 자료가 필요하다"}
            plan = planned_retire_shares(c)
            r0 = find_retirement(retire, f"{f['rcept_dt']}000000", plan)
            if plan:
                row.update(plan_value=plan, unit="주", note=note + ". 소각 수량만 공시끼리 대조했다")
                if r0 is not None:
                    rate = min(r0["shares"] / plan, 1.0)
                    row.update(execution=f"소각결정 {r0['shares']:,.0f}주 ({r0['retire_date']} 소각 예정)",
                               execution_rcept_no=r0["rcept_no"], execution_date=r0["rcept_dt"],
                               actual_value=r0["shares"], rate=rate, verdict=verdict(rate, True, None))
            rows.append(row)
        for c in (c for k, c in clauses if k == "자체 보고 실적"):
            rows.append({**base, "promise_type": "기업가치제고계획 이행 현황", "promise": "-",
                         "execution": f"(회사 자체 보고) {c}", "verdict": "검증 전",
                         "note": note + ". 회사가 같은 공시에 적은 실적이라 독립 근거가 아니다"})

    if not rows:
        rows.append({"company_name": name, "stock_code": code, "promise_type": "약속 공시 없음",
                     "promise_date": None, "promise_rcept_no": None,
                     "promise": "기간 안에 자사주 취득 결정·기업가치제고계획 공시가 없다", "plan_value": None,
                     "unit": None, "deadline": None, "execution_rcept_no": None, "execution_date": None,
                     "execution": None, "actual_value": None, "rate": None, "verdict": "자료 없음",
                     "note": "처분·소각·배당 공시는 자본배분 연표에서 다룬다"})
    return rows, results, retire


def write_markdown(df):
    """사람이 읽는 대조표(outputs). 숫자·판정은 CSV와 같다."""
    lines = [f"# 약속–실행 대조표 (dev 6곳, 기준일 {AS_OF})", "",
             f"- 규칙 {RULE_VERSION}. 이행 {DONE:.0%} 이상, 부분 이행 {PARTIAL:.0%} 이상, 그 아래는 미달(팀 합의 전 초안)",
             "- 근거는 모두 DART 공시 접수번호다. 기업가치제고계획 항목은 규칙으로 뽑아 사람 확인이 필요하다", ""]
    for name, g in df.groupby("company_name", sort=False):
        lines += [f"## {name}", "", "| 약속일 | 유형 | 약속 | 실행 | 이행률 | 판정 | 근거 |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for _, r in g.iterrows():
            rate = f"{r['rate']:.1%}" if pd.notna(r["rate"]) else "-"
            src = " / ".join(x for x in [r["promise_rcept_no"], r["execution_rcept_no"], r.get("followup_rcept_no")]
                             if isinstance(x, str) and x)
            cell = lambda v: str(v).replace("|", "/") if isinstance(v, str) and v else "-"
            done = cell(r["execution"]) + (f" → {r['followup']}" if isinstance(r.get("followup"), str) else "")
            lines.append(f"| {cell(r['promise_date'])} | {r['promise_type']} | {cell(r['promise'])} | {done} "
                         f"| {rate} | {r['verdict']} | {src or '-'} |")
        lines.append("")
    (OUT / f"promise_execution_dev_{TAG}.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    roster = pd.read_csv(DATA / "person_target_roster_dart_20261027.csv", dtype=str)
    code_of = (roster.drop_duplicates("company_name").set_index("company_name")["company_id"]
               .str.replace("KRX:", "", regex=False).to_dict())
    dev_cos = W.training_companies(roster)
    key = D.load_key()
    corp = D.corp_codes(key)

    rows, unmatched, retires = [], [], []
    for name in dev_cos:
        code = code_of[name]
        r, results, retire = build_company(key, code, name, corp[code]["corp_code"])
        rows += r
        retires += [{"company_name": name, "stock_code": code, **x} for x in retire.to_dict("records")]
        used = {x for v in (row["execution_rcept_no"] for row in r if row["promise_type"] == "자사주 취득") if v
                for x in v.split("|")}
        unmatched += [{"company_name": name, **x} for x in results.to_dict("records") if x["rcept_no"] not in used]

    df = pd.DataFrame(rows).assign(as_of=AS_OF, rule_version=RULE_VERSION)
    df.to_csv(DATA / f"promise_execution_dev_{TAG}.csv", index=False, encoding="utf-8-sig")
    # 소각결정은 다음 단계(자본배분 연표)에서 쓴다
    pd.DataFrame(retires).to_csv(DATA / f"share_retirement_dev_{TAG}.csv", index=False, encoding="utf-8-sig")
    write_markdown(df)
    print(f"약속 {len(df)}행 | 회사 {df['company_name'].nunique()}곳 | 기준일 {AS_OF} | 소각결정 {len(retires)}건")
    print(df.groupby(["promise_type", "verdict"]).size().to_string())
    if unmatched:
        print("짝 없는 결과보고서:", pd.DataFrame(unmatched)[["company_name", "rcept_no", "decided"]].to_dict("records"))


if __name__ == "__main__":
    main()
