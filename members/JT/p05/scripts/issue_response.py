"""P05 쟁점과 해명: 경영진·대주주를 둘러싼 쟁점이 무엇이었고 회사·당사자가 어떻게 답했는지 정리한다.

두 갈래
A) 공시 쟁점: 풍문또는보도에대한해명, 조회공시요구(풍문또는보도)·답변, 소송등의제기·판결, 횡령ㆍ배임 공시
   - 원문에서 쟁점(보도 내용·조회 요구·사건명)과 답(해명·답변·결정 내용)을 뽑는다(공시 원문, 160자 이내)
   - 답의 성격은 규칙으로 나눈다: 부인 / 미확정(검토 중) / 인정·확정 / 법원 결정(취하·각하·기각·인용) / 대응 예정
   - 재공시 예정일이 있으면 그 뒤의 같은 종류 공시를 후속 공시로 잇는다
B) 보도 쟁점: p05.news_event_link의 기사(제목에 명부 인물)를 주제 규칙으로 묶는다
   - 기사 제목·본문은 결과에 복사하지 않는다. doc_id와 건수만 남긴다(원문은 rag.document)
   - 같은 묶음 안에서 해명·반박·부인·사과 같은 말이 든 기사를 '보도 속 해명'으로 센다

지키는 규칙
- 판정은 규칙이 한다. 쟁점이 사실인지는 판단하지 않는다(누가 무엇을 주장했고 무엇으로 답했는지만).
- 기준일 뒤 공시·기사는 쓰지 않는다. DB는 읽기만 한다. 대상은 dev 6곳이다.
- 한계: 제목에 인물이 나와도 쟁점의 당사자가 아닐 수 있다(예: 국감 증인 채택 기사). 주제 규칙은 사람 확인이 필요하다.
- 한계: 네이버 검색 1,000건 제한 때문에 인물별 기사 수는 기간마다 편차가 있다. 건수는 크기 비교가 아니라 존재 확인용이다.

사용 방법(프로젝트 폴더에서):
  .venv-sentiment\\Scripts\\python.exe scripts\\issue_response.py
"""
from pathlib import Path
import re
import sys

import pandas as pd
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dart_person_roster as D
import disclosure_weak_label as W
import p05_db_sync as S
import promise_execution as PE

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA = PROJECT_DIR / "data"
OUT = PROJECT_DIR / "outputs"
AS_OF = W.AS_OF
TAG = AS_OF.replace("-", "")
RULE_VERSION = "issue-v1-20261103"

# ---------------------------------------------------------------------------
# A) 공시 쟁점
# ---------------------------------------------------------------------------
DISC_KINDS = [   # (공시명에 든 말, 종류)
    ("풍문또는보도에대한해명", "풍문 해명"),
    ("조회공시요구(풍문또는보도)에대한답변", "조회공시 답변"),
    ("조회공시요구", "조회공시 요구"),
    ("소송등의제기", "소송 제기"),
    ("소송등의판결", "소송 결정"),
    ("횡령ㆍ배임", "횡령·배임"),
]
GOV_WORDS = re.compile(r"경영권|최대주주|대주주|지분|자사주|자기주식|배당|승계|오너|회장|이사회|주주|임원|대표이사|횡령|배임")
CUT = 160


def clip(s):
    s = re.sub(r"\s+", " ", str(s or "")).strip(" |")
    return s[:CUT] + ("…" if len(s) > CUT else "")


def between(text, start, end):
    """start와 end 사이 글(자르지 않음)."""
    m = re.search(start + r"(.*?)(?:" + (end or "$") + ")", text, flags=re.S)
    return re.sub(r"\s+", " ", m[1]).strip(" |") if m and m[1] else ""


END_ANSWER = r"\d\.\s*재공시|※\s*관련공시|※\s*이 내용은"   # 답변 첫머리의 '※이 내용은…재공시사항임'은 아래에서 지운다


def parse_disclosure(kind, text, report_nm=""):
    """(쟁점, 답, 답의 성격, 재공시 예정일). 답의 성격은 자르기 전 전체 글로 정하고, 요지만 160자로 자른다."""
    t = re.sub(r"\s+", " ", text)
    redo = PE.kdate(between(t, r"재공시예정일", r"※|$"))
    if kind == "풍문 해명":
        issue = between(t, r"1\.\s*풍문 또는 보도의 내용", r"2\.\s*풍문")
        answer = between(t, r"해명내용", END_ANSWER)
    elif kind == "조회공시 답변":
        issue = between(t, r"1\.\s*제목", r"2\.\s*내용")
        body = re.sub(r"※\s*이 내용은[^※]*?재공시사항임", " ", between(t, r"2\.\s*내용", r"\d\.\s*재공시예정일|$"))
        answer = between(body + " ※ 관련공시", r"^", END_ANSWER)
    elif kind == "조회공시 요구":
        issue, answer = between(t, r"조회공시요구내용", r"2\.\s*공시시한"), ""
    elif kind in ("소송 제기", "소송 결정"):
        name = between(t, r"1\.\s*사건의 명칭", r"사건번호")
        who = between(t, r"2\.\s*원고\S*", r"3\.")
        issue = f"{name} (신청인 {who})"
        answer = (between(t, r"향후대책", r"6\.") if kind == "소송 제기"
                  else between(t, r"판결ㆍ결정내용", r"4\.\s*판결"))
    else:   # 횡령·배임
        issue = between(t, r"혐의내용", r"2\.\s*고발인|2\.\s*횡령")
        answer = between(t, r"판결내용", r"2\.\s*횡령") or between(t, r"향후대책", r"4\.")
    akind = answer_kind(kind, answer, report_nm)
    gist = re.sub(r"^-?\s*본 공시는.*?(공시|재공시)(\(미확정\))?입니다\.\s*-?\s*", "", answer)   # 형식 문장은 요지에서 뺀다
    return clip(issue), clip(gist), akind, redo


def answer_kind(kind, answer, report_nm=""):
    """순서: 부인 → 이사회 결의 → 미확정(본문 표현 또는 공시명의 '(미확정)') → 혐의 없음 → 대응 예정 → 확정."""
    if kind == "조회공시 요구":
        return "답변 대기"
    if kind == "소송 결정":
        m = re.search(r"취하|각하|기각|인용|화해|조정|승소|패소", answer)
        return f"법원 결정({m[0]})" if m else "법원 결정"
    if re.search(r"사실무근|사실이 아니|사실과 다르|사실과 상이|(과|와)\s*무관|(거래|사실)가 아님", answer):
        return "부인"
    if re.search(r"결의하였|하기로 결정하였", answer) and not re.search(r"확정되지|결정된 바는? 없", answer):
        return "이사회 결의로 답"
    if (re.search(r"확정된 (사항|부분|바)\s*(은|는)?\s*없|확정되지|결정된 바는? 없|검토\s*중|미정|결정한 사항이 없", answer)
            or "미확정" in report_nm):
        return "미확정(검토 중)"
    if re.search(r"불송치|혐의없음|무혐의|무죄", answer):
        return "혐의 없음 결정"
    if re.search(r"대응할 예정|대응 예정|법적 절차", answer):
        return "대응 예정"
    return "인정·확정" if answer else "답 없음"


def disclosure_issues(key, code, name):
    fl = PE.filings(code)
    rows = []
    for _, f in fl[~fl["nm"].str.contains("정정")].iterrows():
        kind = next((k for w, k in DISC_KINDS if w in f["nm"]), None)
        if not kind:
            continue
        text = PE.doc_text(key, f["rcept_no"])
        issue, answer, akind, redo = (parse_disclosure(kind, text, f["nm"]) if text
                                      else ("(원문 없음)", "", "답 없음", None))
        sub = "자회사" if re.search(r"자회사|종속회사", f["nm"]) else ""
        rows.append({"company_name": name, "stock_code": code, "source": "공시", "date": PE.kdate(f["rcept_dt"][:4] + "-"
                     + f["rcept_dt"][4:6] + "-" + f["rcept_dt"][6:]), "kind": kind + (f"({sub})" if sub else ""),
                     "topic": "경영진·대주주 관련" if GOV_WORDS.search(issue + answer) else "회사 사업",
                     "issue": issue, "answer": answer, "answer_kind": akind, "redo_date": redo,
                     "rcept_no": f["rcept_no"], "flr_nm": f["flr_nm"]})
    df = pd.DataFrame(rows)
    if not len(df):
        return df
    # 후속 공시: 재공시 예정일 앞뒤 3일 안의 같은 회사 해명·답변 / 조회 요구에는 같은 날 이후 첫 답변
    df["followup_rcept_no"] = None
    for i, r in df.iterrows():
        cand = df[(df["rcept_no"] > r["rcept_no"]) & df["kind"].str.contains("해명|답변")]
        if r["kind"] == "조회공시 요구":
            cand = cand[cand["kind"].str.contains("답변")]
        elif r["redo_date"]:
            d = pd.Timestamp(r["redo_date"])
            cand = cand[(pd.to_datetime(cand["date"]) - d).abs() <= pd.Timedelta(days=3)]
        elif r["kind"] == "소송 제기":
            cand = df[(df["rcept_no"] > r["rcept_no"]) & (df["kind"] == "소송 결정")]
        else:
            cand = cand.iloc[0:0]
        if len(cand):
            df.at[i, "followup_rcept_no"] = cand["rcept_no"].iloc[0]
    return df


# ---------------------------------------------------------------------------
# B) 보도 쟁점
# ---------------------------------------------------------------------------
TOPICS = [   # (주제, 제목 규칙). 순서가 우선순위다
    ("사법·수사", r"검찰|기소|구형|항소|공판|법원|선고|사법\s*리스크|수사|고발|횡령|배임|시세조종|주가조작|무죄|혐의|재판"),
    ("경영권 분쟁", r"경영권|분쟁|위약벌|공개매수|연합|가처분|주총 표 대결|표대결"),
    ("노사 갈등", r"노조|파업|노사|성과급\s*(갈등|요구|불만|협상)|단체교섭|임금"),   # 임원 성과급 지급 기사는 빼려고 성과급만으로는 잡지 않는다
    ("주주가치 논란", r"주주가치|훼손|반대표|주주단체|인적분할|블록딜|쪼개기|엑시트|행동주의"),
    ("승계·지분", r"승계|상속|증여|지분 인수|지분 확대|지배구조"),
    ("개인 의혹", r"법카|법인카드|의혹|갑질"),
]
RESPONSE = re.compile(r"해명|반박|부인|사실무근|입장|사과|송구|항변|무고|법적 대응|선 그|일축|\"없다\"|'없다'")
CONFLICT = re.compile(r"의혹|논란|비판|반발|갈등|분쟁|우려|리스크|반대|고발|소송|기소|구형|파업|규탄|압박|훼손")


def news_issues(conn, dev_names):
    rows = conn.execute("""SELECT l.company_name, l.target_name, l.published_at, l.doc_id, d.title
                           FROM p05.news_event_link l JOIN rag.document d USING (doc_id)
                           WHERE l.company_name = ANY(%s) AND l.published_at <= %s""", [dev_names, AS_OF]).fetchall()
    news = pd.DataFrame(rows, columns=["company_name", "target_name", "published_at", "doc_id", "title"])
    news["topic"] = news["title"].map(lambda t: next((n for n, p in TOPICS if re.search(p, t)), None))
    news["is_response"] = news["title"].str.contains(RESPONSE)
    news["is_conflict"] = news["title"].str.contains(CONFLICT)
    news = news.dropna(subset=["topic"]).drop_duplicates(["company_name", "doc_id"])   # 한 기사에 인물이 여럿이면 한 번만
    out = []
    for (co, topic), g in news.groupby(["company_name", "topic"]):
        month = pd.to_datetime(g["published_at"]).dt.strftime("%Y-%m")
        peak = month.value_counts()
        resp = g[g["is_response"]].sort_values("published_at")
        out.append({"company_name": co, "source": "보도", "topic": topic,
                    "targets": ", ".join(g["target_name"].value_counts().index[:3]),
                    "first_date": str(g["published_at"].min()), "last_date": str(g["published_at"].max()),
                    "n_articles": len(g), "n_conflict_articles": int(g["is_conflict"].sum()),
                    "peak_month": f"{peak.index[0]}({peak.iloc[0]}건)",
                    "n_response_articles": len(resp),
                    "response_targets": ", ".join(resp["target_name"].value_counts().index[:3]),
                    "issue_doc_ids": "|".join(map(str, g[g["is_conflict"]].sort_values("published_at")["doc_id"].head(3))),
                    "response_doc_ids": "|".join(map(str, resp["doc_id"].head(3))),
                    # 논란 표현이 없는 묶음은 쟁점이 아니라 사건 보도로 둔다(해명을 기대할 일이 아니다)
                    "status": ("사건 보도(논란 표현 없음)" if not g["is_conflict"].any()
                               else "보도 속 해명 있음" if len(resp) else "해명 보도 확인 안 됨")})
    return pd.DataFrame(out).sort_values(["company_name", "n_articles"], ascending=[True, False])


# ---------------------------------------------------------------------------
def write_markdown(disc, news):
    lines = [f"# 쟁점과 해명 (dev 6곳, 2026-01-01 ~ {AS_OF})", "",
             f"- 규칙 {RULE_VERSION}. 쟁점이 사실인지는 판단하지 않는다. 누가 무엇을 주장했고 무엇으로 답했는지만 적는다",
             "- 공시 쟁점은 원문에서 뽑은 160자 이내 요지다. 보도 쟁점은 기사 제목을 옮기지 않고 건수·doc_id만 둔다",
             "- 보도 건수는 네이버 1,000건 제한으로 기간 편차가 있어 존재 확인용이다. 주제 분류는 사람 확인이 필요하다", ""]
    for co in sorted(set(disc["company_name"]) | set(news["company_name"])):
        lines += [f"## {co}", ""]
        d = disc[disc["company_name"] == co]
        if len(d):
            lines += ["### 공시로 확인된 쟁점과 답", "", "| 날짜 | 종류 | 관련 | 쟁점 | 답(요지) | 답의 성격 | 후속 | 접수번호 |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for _, r in d.iterrows():
                c = lambda v: str(v).replace("|", "/") if isinstance(v, str) and v else "-"
                lines.append(f"| {r['date']} | {r['kind']} | {r['topic']} | {c(r['issue'])} | {c(r['answer'])} "
                             f"| {r['answer_kind']} | {c(r['followup_rcept_no'])} | {r['rcept_no']} |")
            lines.append("")
        n = news[news["company_name"] == co]
        if len(n):
            lines += ["### 보도로 나타난 쟁점", "",
                      "| 주제 | 제목 속 인물 | 기간 | 기사 수(논란 표현) | 정점 | 해명 기사 | 해명한 쪽(제목 속 인물) | 상태 |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for _, r in n.iterrows():
                lines.append(f"| {r['topic']} | {r['targets']} | {r['first_date']}~{r['last_date']} "
                             f"| {r['n_articles']}({r['n_conflict_articles']}) "
                             f"| {r['peak_month']} | {r['n_response_articles']} | {r['response_targets'] or '-'} | {r['status']} |")
            lines.append("")
    (OUT / f"issue_response_dev_{TAG}.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    roster = pd.read_csv(DATA / "person_target_roster_dart_20261027.csv", dtype=str)
    code_of = (roster.drop_duplicates("company_name").set_index("company_name")["company_id"]
               .str.replace("KRX:", "", regex=False).to_dict())
    dev = W.training_companies(roster)
    key = D.load_key()
    disc = pd.concat([disclosure_issues(key, code_of[n], n) for n in dev], ignore_index=True)
    with psycopg.connect(S.db_url()) as conn:
        conn.execute("SET default_transaction_read_only = on")
        news = news_issues(conn, dev)
    disc.assign(as_of=AS_OF, rule_version=RULE_VERSION).to_csv(
        DATA / f"issue_response_disclosure_dev_{TAG}.csv", index=False, encoding="utf-8-sig")
    news.assign(as_of=AS_OF, rule_version=RULE_VERSION).to_csv(
        DATA / f"issue_response_news_dev_{TAG}.csv", index=False, encoding="utf-8-sig")
    write_markdown(disc, news)
    print(f"공시 쟁점 {len(disc)}건 | 보도 쟁점 묶음 {len(news)}개 | 기준일 {AS_OF}")
    print(disc.groupby(["kind", "answer_kind"]).size().to_string())
    print(news[["company_name", "topic", "n_articles", "n_response_articles"]].to_string(index=False))


if __name__ == "__main__":
    main()
