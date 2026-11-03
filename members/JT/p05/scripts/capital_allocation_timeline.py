"""P05 자본배분 연표: 경영진이 회사 돈을 어디에 썼는지(환원·보상·투자·재편) 공시 순서대로 늘어놓는다.

넣는 공시(dev 6곳, 2026-01-01 ~ 기준일)
- 자사주: 취득 결정(DART tsstkAqDecsn)·취득 결과보고서·처분 결정(tsstkDpDecsn)·주식소각결정·감자결정(자기주식 소각)
- 배당: 현금ㆍ현물배당결정(1주당 배당금, 배당금총액)
- 투자: 신규시설투자등, 타법인주식및출자증권 취득·처분결정
- 재편: 회사합병·회사분할 결정, 기업가치제고계획(내용은 약속–실행 대조표에서 본다)

분류 규칙
- 자사주 취득·처분은 목적에 임직원·임원·성과급·보상이 있으면 '보상', 아니면 취득은 '주주환원', 처분은 '처분'
- 배당·소각·감자(자기주식 소각)는 '주주환원', 시설·타법인 취득은 '투자', 타법인 처분은 '자산 매각'

지키는 규칙
- 숫자는 공시 원문 값만 쓴다. 회사별 합계는 공시 금액을 더한 값이며 성격이 다른 금액은 더하지 않는다.
- 정정 공시는 원 공시 행에 '정정 있음'으로만 표시하고 값은 원 공시 기준이다(정정 원문은 전·후 표가 섞여 있다).
- 기준일 뒤 공시는 쓰지 않는다. 원문은 data/dart_raw/docs/에 보관한다(promise_execution.py와 같은 곳).

사용 방법(프로젝트 폴더에서):
  .venv-sentiment\\Scripts\\python.exe scripts\\capital_allocation_timeline.py
"""
from pathlib import Path
import re
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dart_person_roster as D
import disclosure_weak_label as W
import promise_execution as PE

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA = PROJECT_DIR / "data"
OUT = PROJECT_DIR / "outputs"
AS_OF = W.AS_OF
TAG = AS_OF.replace("-", "")
RULE_VERSION = "capalloc-v1-20261103"
REWARD = re.compile(r"직원|임원|성과급|보상|우리사주|RSU|RSA|PSU|주식매수선택권|스톡옵션|장려금")

# (공시명에 든 말, 사건, 분류). 순서가 우선순위다. 자사주 취득·처분 결정은 API로 따로 넣는다
DOC_RULES = [
    ("자기주식취득결과보고서", "자사주 취득 결과", None),
    ("주식소각결정", "자사주 소각 결정", "주주환원"),
    ("감자결정", "감자 결정", None),
    ("현금ㆍ현물배당결정", "현금배당 결정", "주주환원"),
    ("신규시설투자", "시설투자 결정", "투자"),
    ("타법인주식및출자증권취득결정", "타법인 지분 취득 결정", "투자"),
    ("타법인주식및출자증권처분결정", "타법인 지분 처분 결정", "자산 매각"),
    ("회사합병결정", "합병 결정", "재편"),
    ("회사분할결정", "분할 결정", "재편"),
    ("기업가치제고계획", "기업가치제고계획 공시", "계획"),
]


def field(c, label, skip=0):
    """칸 목록에서 label이 든 첫 칸 뒤 (skip+1)번째 값."""
    for i, x in enumerate(c):
        if label in x and i + 1 + skip < len(c):
            return c[i + 1 + skip]
    return None


def parse_doc(event, text):
    """사건별로 금액·수량·설명을 뽑는다. 못 뽑으면 None."""
    c = PE.cells(text)
    if event == "자사주 취득 결과":
        _, amt, sh = PE.parse_buyback_result(text)
        return amt, sh, ""
    if event == "자사주 소각 결정":
        sh, amt, day, how = PE.parse_retirement(text)
        return amt, sh, f"소각 예정일 {day}, 재원 {how}" if day else how
    if event == "감자 결정":
        sh = PE.num(field(c, "감자주식의 종류와 수", 1) or "")
        how = field(c, "감자방법") or ""
        return None, sh, f"방법 {how}"
    if event == "현금배당 결정":
        dps = field(c, "1주당 배당금", 1)
        return PE.num(field(c, "배당금총액") or ""), None, f"{field(c, '배당구분') or ''}, 보통주 1주당 {dps}원"
    if event == "시설투자 결정":
        return PE.num(field(c, "투자금액") or ""), None, f"{field(c, '투자대상') or ''}"[:60]
    if event == "타법인 지분 취득 결정":
        return PE.num(field(c, "취득금액") or ""), None, f"{field(c, '회사명') or ''}, 목적 {field(c, '취득목적') or ''}"[:80]
    if event == "타법인 지분 처분 결정":
        return PE.num(field(c, "처분금액") or ""), None, f"{field(c, '회사명') or ''}, 목적 {field(c, '처분목적') or ''}"[:80]
    if event in ("합병 결정", "분할 결정"):
        return None, None, (field(c, "합병상대회사", 1) or field(c, "분할설립회사", 1) or "")[:60]   # 다음 칸은 '회사명' 제목
    return None, None, ""


def api_events(key, corp_code, api, event):
    """자사주 취득·처분 결정(DART 주요사항보고서 API)."""
    j = D.get_json(key, api, {"corp_code": corp_code, "bgn_de": W.START.replace("-", ""), "end_de": TAG})
    out = []
    for r in j.get("list", []) if j.get("status") == "000" else []:
        if r["rcept_no"][:8] > TAG:
            continue
        p = "aqpln" if api == "tsstkAqDecsn" else "dppln"
        amt = (PE.num(r.get(f"{p}_prc_ostk")) or 0) + (PE.num(r.get(f"{p}_prc_estk")) or 0)
        sh = (PE.num(r.get(f"{p}_stk_ostk")) or 0) + (PE.num(r.get(f"{p}_stk_estk")) or 0)
        purpose = str(r.get("aq_pp" if p == "aqpln" else "dp_pp", "")).strip()
        if p == "aqpln":
            cat = "보상" if REWARD.search(purpose) else "주주환원"
            period = f"{PE.kdate(r.get('aqexpd_bgd'))}~{PE.kdate(r.get('aqexpd_edd'))}"
        else:
            cat = "보상" if REWARD.search(purpose) else "처분"
            period = f"{PE.kdate(r.get('dpprpd_bgd'))}~{PE.kdate(r.get('dpprpd_edd'))}"
        out.append({"rcept_no": r["rcept_no"], "event": event, "category": cat, "amount": amt or None,
                    "shares": sh or None, "detail": f"목적 {purpose[:40]}, 기간 {period}"})
    return out


def build_company(key, code, name, corp_code):
    fl = PE.filings(code)
    rows = api_events(key, corp_code, "tsstkAqDecsn", "자사주 취득 결정")
    rows += api_events(key, corp_code, "tsstkDpDecsn", "자사주 처분 결정")
    purpose_of = {}   # 취득 결정 제출일 → 분류(결과보고서에 물려준다)
    for r in rows:
        if r["event"] == "자사주 취득 결정":
            purpose_of[f"{r['rcept_no'][:4]}-{r['rcept_no'][4:6]}-{r['rcept_no'][6:8]}"] = r["category"]

    originals = fl[~fl["nm"].str.contains("정정")]
    fixed_by = {}   # 원 공시 접수번호 → 정정 접수번호들. 정정은 그 앞의 같은 종류 공시 중 가장 최근 것에 붙인다
    for _, f in fl[fl["nm"].str.contains("정정")].iterrows():
        word = next((w for w, _, _ in DOC_RULES if w in f["nm"]), None) or next(
            (w for w in ("자기주식취득결정", "자기주식처분결정") if w in f["nm"]), None)
        prev = originals[(originals["rcept_no"] < f["rcept_no"]) & originals["nm"].str.contains(word)] if word else []
        if len(prev):
            fixed_by.setdefault(prev["rcept_no"].iloc[-1], []).append(f["rcept_no"])
    for _, f in originals.iterrows():
        rule = next((r for r in DOC_RULES if r[0] in f["nm"]), None)
        if not rule:
            continue
        _, event, cat = rule
        text = PE.doc_text(key, f["rcept_no"])
        amt, sh, detail = parse_doc(event, text) if text else (None, None, "원문 없음")
        if event == "자사주 취득 결과":
            decided = PE.parse_buyback_result(text)[0] if text else None
            cat = purpose_of.get(decided, "주주환원")
            detail = f"취득 결정 {decided} 건의 결과"
        if event == "감자 결정":
            cat = "주주환원" if "소각" in detail else "재편"
        rows.append({"rcept_no": f["rcept_no"], "event": event, "category": cat, "amount": amt, "shares": sh,
                     "detail": detail})

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["rcept_no"].str[:8]).dt.strftime("%Y-%m-%d")
    df["correction"] = df["rcept_no"].map(lambda r: ", ".join(fixed_by.get(r, [])) or None)
    df["detail"] = df["detail"].fillna("").str.replace(r"\s+", " ", regex=True).str.strip()
    return df.assign(company_name=name, stock_code=code)


def summarize(tl):
    """회사별 합계. 실제 취득은 결과보고서 기준, 결정만 있고 결과가 없으면 '진행 중'으로 따로 센다."""
    out = []
    for name, g in tl.groupby("company_name", sort=False):
        s = lambda ev, cat=None: g.loc[(g["event"] == ev) & ((g["category"] == cat) if cat else True), "amount"].sum()
        out.append({"company_name": name,
                    "배당 결정 합계(원)": s("현금배당 결정"),
                    "자사주 취득 실적-주주환원(원)": s("자사주 취득 결과", "주주환원"),
                    "자사주 취득 실적-보상(원)": s("자사주 취득 결과", "보상"),
                    "자사주 처분 결정-보상(원)": s("자사주 처분 결정", "보상"),
                    "자사주 처분 결정-그 밖(원)": s("자사주 처분 결정", "처분"),
                    "자사주 소각 결정(장부가, 원)": s("자사주 소각 결정"),
                    "시설·지분 투자 결정(원)": s("시설투자 결정") + s("타법인 지분 취득 결정"),
                    "공시 건수": len(g)})
    return pd.DataFrame(out)


def write_markdown(tl, sm):
    eok = lambda v: f"{v / 1e8:,.0f}억" if pd.notna(v) and v else "-"
    lines = [f"# 자본배분 연표 (dev 6곳, 2026-01-01 ~ {AS_OF})", "",
             f"- 규칙 {RULE_VERSION}. 금액은 공시 원문 값이다. 결정 금액은 계획이고 실적은 '취득 결과' 행이다",
             "- 시설·지분 투자 금액은 여러 해에 걸친 계획 총액일 수 있다. 소각 금액은 장부가라 현금 지출이 아니다",
             "- 분류(보상·주주환원 등)는 공시 목적 문구로 정한 규칙이다", "", "## 회사별 합계", "",
             "| 회사 | 배당 | 자사주 취득(환원) | 자사주 취득(보상) | 처분(보상) | 소각(장부가) | 투자 결정 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for _, r in sm.iterrows():
        lines.append(f"| {r['company_name']} | {eok(r['배당 결정 합계(원)'])} | {eok(r['자사주 취득 실적-주주환원(원)'])} "
                     f"| {eok(r['자사주 취득 실적-보상(원)'])} | {eok(r['자사주 처분 결정-보상(원)'])} "
                     f"| {eok(r['자사주 소각 결정(장부가, 원)'])} | {eok(r['시설·지분 투자 결정(원)'])} |")
    for name, g in tl.groupby("company_name", sort=False):
        lines += ["", f"## {name}", "", "| 날짜 | 사건 | 분류 | 금액 | 주식수 | 내용 | 접수번호 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for _, r in g.iterrows():
            sh = f"{r['shares']:,.0f}" if pd.notna(r["shares"]) and r["shares"] else "-"
            note = str(r["detail"] or "").replace("|", "/") + (f" (정정 {r['correction']})" if r["correction"] else "")
            lines.append(f"| {r['date']} | {r['event']} | {r['category']} | {eok(r['amount'])} | {sh} | {note} | {r['rcept_no']} |")
    (OUT / f"capital_allocation_timeline_dev_{TAG}.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    roster = pd.read_csv(DATA / "person_target_roster_dart_20261027.csv", dtype=str)
    code_of = (roster.drop_duplicates("company_name").set_index("company_name")["company_id"]
               .str.replace("KRX:", "", regex=False).to_dict())
    key = D.load_key()
    corp = D.corp_codes(key)
    parts = [build_company(key, code_of[n], n, corp[code_of[n]]["corp_code"]) for n in W.training_companies(roster)]
    tl = (pd.concat(parts, ignore_index=True).sort_values(["company_name", "rcept_no"])
          .assign(as_of=AS_OF, rule_version=RULE_VERSION))
    cols = ["company_name", "stock_code", "date", "event", "category", "amount", "shares", "detail", "correction",
            "rcept_no", "as_of", "rule_version"]
    tl[cols].to_csv(DATA / f"capital_allocation_timeline_dev_{TAG}.csv", index=False, encoding="utf-8-sig")
    sm = summarize(tl)
    write_markdown(tl, sm)
    print(f"연표 {len(tl)}행 | 회사 {tl['company_name'].nunique()}곳 | 기준일 {AS_OF}")
    print(tl.groupby(["event", "category"]).size().to_string())
    miss = tl[tl["amount"].isna() & tl["shares"].isna() & ~tl["event"].isin(["합병 결정", "분할 결정", "기업가치제고계획 공시"])]
    print("금액·수량 둘 다 못 뽑은 행:", miss[["company_name", "event", "rcept_no"]].to_dict("records"))


if __name__ == "__main__":
    main()
