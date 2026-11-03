"""P05 결과를 Neon p05 스키마에 올리고, DB 기사를 공시 사건에 연결한다.

하는 일
1) data/disclosure_weak_labels_20261027.csv → p05.disclosure_weak_label (전체 교체)
2) rag.document의 naver_news·naver_news_backfill 중 dev 회사 기사에서, 제목에 DART 명부 이름이 정확히 들어간 것만 고른다
   - 두 출처에 같은 기사가 있을 수 있어 URL을 정규화해 중복을 지운다(14일 뒤 지워지지 않는 naver_news_backfill 쪽을 남긴다).
   - 동명이인이 확인된 이름(AMBIGUOUS_NAMES)은 제목에 회사명도 있을 때만 쓴다.
3) 고른 기사를 같은 회사 ±LINK_DAYS일 공시 사건에 연결 → p05.news_event_link (전체 교체)

지키는 규칙
- 계정은 .env의 DATABASE_URL(p05_writer)만 쓴다. 값은 출력하지 않는다.
- holdout 회사 기사는 조회하지 않는다(회사 단위 누수 방지).
- 이름은 명부와 정확히 일치할 때만 쓴다. 약칭·성·호칭은 쓰지 않는다.
- 기사 본문·요약은 p05에 복사하지 않는다. doc_id로만 연결한다(원본은 rag.document).
- 네이버 뉴스 학습 이용은 2026-10-29 팀 확인을 받았다(이슈 #27 요청 4·5, 사용자가 팀원에게 직접 확인).
- 한계: 제목에 명부 밖 인물이 함께 나오는지는 자동으로 거르지 못한다. 학습 전에 사람이 표본을 확인한다.
- 한계: 네이버 검색은 검색어당 1,000건까지라 기사가 많은 인물은 1월까지 닿지 못했을 수 있다(수집팀 작업 로그 참고).

사용 방법(프로젝트 폴더에서):
  .venv-sentiment\\Scripts\\python.exe scripts\\p05_db_sync.py
"""
from pathlib import Path
import re
import sys

import pandas as pd
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disclosure_weak_label as W

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA = PROJECT_DIR / "data"
AS_OF = W.AS_OF
RULE_VERSION = "weak-v2-topic2-news3-person1-20261103"  # 약한 라벨 v2 + 주제 일치 v2 + 기사 선택 v3(백필 우선 중복 제거) + 인물 관련 공시만(concerns_person)

DDL = """
CREATE TABLE IF NOT EXISTS p05.disclosure_weak_label (
    event_id      text PRIMARY KEY,
    stock_code    text NOT NULL,
    company_name  text NOT NULL,
    event_date    date NOT NULL,
    event_types   text,
    report_nms    text,
    rcept_nos     text,
    n_filings     int,
    prior         text,
    t0            date,
    status        text,
    car_0_1       numeric,
    sigma_est     numeric,
    z             numeric,
    price_label   text,
    weak_label    text NOT NULL,
    weak_strength text NOT NULL,
    source        text,
    rule_version  text NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE p05.disclosure_weak_label IS '공시 유형+주가 반응 약한 라벨. 사람 정답 아님. scripts/disclosure_weak_label.py';
CREATE TABLE IF NOT EXISTS p05.news_event_link (
    doc_id        bigint NOT NULL,
    target_name   text   NOT NULL,
    company_name  text   NOT NULL,
    published_at  date,
    link          text   NOT NULL,     -- DISCLOSURE_NEAR | TOPIC_MISMATCH | NO_DISCLOSURE
    event_id      text REFERENCES p05.disclosure_weak_label (event_id),
    days_gap      int,                 -- 공시일 - 기사일
    weak_label    text,
    weak_strength text,
    in_seed       boolean NOT NULL,    -- 기존 수작업 seed와 같은 URL인가
    rule_version  text NOT NULL,
    loaded_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (doc_id, target_name)
);
ALTER TABLE p05.news_event_link ADD COLUMN IF NOT EXISTS source text;   -- naver_news | naver_news_backfill
ALTER TABLE p05.disclosure_weak_label ADD COLUMN IF NOT EXISTS filers text;   -- DART 제출인, report_nms와 같은 순서
COMMENT ON TABLE p05.news_event_link IS 'rag.document 기사(제목에 명부 인물) ↔ 공시 사건. 학습 이용 2026-10-29 팀 확인';
"""


def db_url():
    for line in (PROJECT_DIR / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    sys.exit("DATABASE_URL이 .env에 없습니다.")


def nan_to_none(df):
    return df.astype(object).where(df.notna(), None)


def upload_events(conn, events):
    cols = ["event_id", "stock_code", "company_name", "event_date", "event_types", "report_nms", "rcept_nos", "filers",
            "n_filings", "prior", "t0", "status", "car_0_1", "sigma_est", "z", "price_label",
            "weak_label", "weak_strength", "source"]
    rows = nan_to_none(events[cols]).values.tolist()
    with conn.transaction():
        conn.execute("DELETE FROM p05.news_event_link")       # 사건을 참조하므로 먼저 비운다
        conn.execute("DELETE FROM p05.disclosure_weak_label")
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO p05.disclosure_weak_label ({', '.join(cols)}, rule_version) "
                f"VALUES ({', '.join(['%s'] * len(cols))}, %s)", [r + [RULE_VERSION] for r in rows])
    return len(rows)


# 앞쪽 출처를 중복 제거 때 남긴다. naver_news는 14일 보관 뒤 삭제되고 백필은 보관 대상에서 빠진다
# (kic-agent-data #50, 2026-11-02 병합). 그래서 지워지지 않는 백필 쪽 doc_id를 남긴다(2026-11-03).
NEWS_SOURCES = ["naver_news_backfill", "naver_news"]
# 수집팀이 알려 준 동명이인(2026-10-29). 제목에 회사명이 없으면 다른 사람일 수 있다
AMBIGUOUS_NAMES = {"김동춘", "최영일"}
COMPANY_WORDS = {"현대자동차": ["현대자동차", "현대차"], "LG화학": ["LG화학", "엘지화학"]}   # 회사명 확인용(인물 이름 아님)


def norm_url(url):
    """중복 판정용 URL: 프로토콜·www·끝 슬래시·#조각·utm 추적값을 뺀다. 기사 번호가 든 쿼리는 남긴다."""
    u = re.sub(r"^https?://(www\.)?", "", str(url).strip().split("#")[0]).rstrip("/")
    if "?" in u:
        base, q = u.split("?", 1)
        q = "&".join(p for p in sorted(q.split("&")) if p and not p.startswith("utm_"))
        u = base + ("?" + q if q else "")
    return u.lower()


def fetch_dev_news(conn, codes):
    sql = """SELECT d.doc_id, c.ticker AS stock_code, d.title, d.url, d.published_at, d.source
             FROM rag.document d JOIN core.company c ON c.company_id = d.company_id
             WHERE c.market = 'KR' AND c.ticker = ANY(%(codes)s) AND d.source = ANY(%(sources)s)
               AND d.published_at BETWEEN %(lo)s AND %(hi)s"""
    rows = conn.execute(sql, {"codes": codes, "sources": NEWS_SOURCES, "lo": W.START, "hi": AS_OF}).fetchall()
    news = pd.DataFrame(rows, columns=["doc_id", "stock_code", "title", "url", "published_at", "source"])
    news["url_key"] = news["url"].map(norm_url)
    news["_rank"] = news["source"].map(NEWS_SOURCES.index)
    return (news.sort_values(["_rank", "doc_id"]).drop_duplicates(["stock_code", "url_key"])
            .drop(columns="_rank").reset_index(drop=True))


def match_names(news, roster, name_of):
    """제목에 같은 회사 명부 이름이 정확히 들어간 기사만. 한 기사에 여러 명이면 사람마다 한 행."""
    names = roster.groupby("company_name")["canonical_name"].apply(lambda s: sorted(set(s))).to_dict()
    out = []
    for _, n in news.iterrows():
        company = name_of[n["stock_code"]]
        title = str(n["title"])
        for person in names.get(company, []):
            if not person or person not in title:
                continue
            if person in AMBIGUOUS_NAMES and not any(w in title for w in COMPANY_WORDS.get(company, [company])):
                continue
            out.append({**n.to_dict(), "company_name": company, "target_name": person})
    return pd.DataFrame(out)


# 기사 제목이 그 공시 사건을 다룬다고 볼 최소 단서. 날짜만 가까우면 행사·사진 기사까지 붙는 문제를 막는다(10-28 dev 표본 점검 뒤 추가)
# v2(10-28): dev 기사 1846건 제목 점검 뒤 수정
#  - "주식" 삭제: 주식선물·주식 거래·자기주식까지 걸림. 실제로 맞던 건 "주식 가압류"뿐이라 "가압류"로 명시
#  - "주담대"·"의결권" 추가: 지분 담보 대출, 지분 매입에 따른 의결권 제한 기사
#  - 지분변동의 매입·매수는 자사주 기사(주주환원 쪽)에 걸리지 않도록 TOPIC_SKIP_IF로 뺀다
TOPIC_WORDS = {
    "주주환원": ["배당", "자사주", "자기주식", "소각", "주주환원", "밸류업", "기업가치제고"],
    "지분변동": ["지분", "가압류", "매입", "매도", "매수", "증여", "상속", "처분", "블록딜", "담보", "주담대", "의결권"],
    "자본조달": ["유상증자", "증자", "전환사채", "CB", "BW", "교환사채"],
    "수사·재판": ["횡령", "배임", "검찰", "재판", "기소", "구형", "선고", "수사"],
    "투자·M&A": ["인수", "합병", "M&A", "출자", "분할"],
    "선임·교체": ["선임", "사임", "교체", "취임", "대표이사"],
    "지배구조변경": ["최대주주", "경영권", "지배력"],
}
# 주제어를 품고 있지만 뜻이 다른 표현. 비교 전에 제목에서 지운다(시장 시황·투자의견·기념일 기사)
TOPIC_NOISE = re.compile(r"순매수|순매도|공매도|매수\s*상위|매도\s*상위|'매수'|\"매수\"|매수\s*(의견|유지|추천)"
                         r"|주택담보|세대교체|재판단|취임\s*\d+\s*(주년|년)")
# 이 단어가 제목에 있으면 그 사건 유형으로는 연결하지 않는다
TOPIC_SKIP_IF = {"지분변동": ["자사주", "자기주식"]}


def _has(word, title):
    if word.isascii():   # CB·BW·M&A는 영문 단어 경계로만(CBDC 같은 오탐 방지)
        return re.search(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", title) is not None
    return word in title


def on_topic(title, event_types):
    title = TOPIC_NOISE.sub(" ", str(title))
    for t in str(event_types).split("|"):
        if any(s in title for s in TOPIC_SKIP_IF.get(t, [])):
            continue
        if any(_has(w, title) for w in TOPIC_WORDS.get(t, [])):
            return True
    return False


EQUITY_REPORTS = ("특정증권등소유상황", "대량보유상황", "최대주주등소유주식변동")
GROUP_REPORT = "최대주주등소유주식변동"   # 회사가 최대주주·특수관계인 전체를 묶어 내는 신고서
GROUP_ROLES = ("최대주주", "주요주주")


def concerns_person(event, person, roles):
    """사건이 그 인물과 관련 있는가. 회사 결정(배당·자사주 등)은 모두 관련, 지분 공시는 본인 제출이거나
    최대주주 그룹 신고서(인물이 최대주주·주요주주일 때)만 관련. 10-29: 삼성전자 지분 공시 대부분이 일반 임원 제출이라 추가"""
    filers = str(event.get("filers") or "").split("|")
    for i, nm in enumerate(str(event["report_nms"]).split("|")):
        nm = re.sub(r"\s+", "", nm)
        if not any(r in nm for r in EQUITY_REPORTS):
            if W.classify(nm)[0]:
                return True                      # 지분 공시가 아닌 대상 사건(회사 결정)
            continue
        filer = filers[i].strip() if i < len(filers) else ""
        if filer == person or (GROUP_REPORT in nm and any(g in r for r in roles for g in GROUP_ROLES)):
            return True
    return False


def link(matched, events, seed_urls, roles_of=None):
    ev = events.assign(_d=pd.to_datetime(events["event_date"]))
    roles_of = roles_of or {}
    rows = []
    for _, m in matched.iterrows():
        md = pd.Timestamp(m["published_at"])
        near = ev.loc[(ev["company_name"] == m["company_name"])
                      & ((ev["_d"] - md).dt.days.abs() <= W.LINK_DAYS)]
        roles = roles_of.get((m["company_name"], m["target_name"]), set())
        near = near.loc[near.apply(lambda e: concerns_person(e, m["target_name"], roles), axis=1)] if len(near) else near
        base = {"doc_id": int(m["doc_id"]), "target_name": m["target_name"], "company_name": m["company_name"],
                "published_at": md.date(), "in_seed": m["url_key"] in seed_urls, "source": m["source"]}
        if near.empty:
            rows.append({**base, "link": "NO_DISCLOSURE", "event_id": None, "days_gap": None,
                         "weak_label": None, "weak_strength": None})
            continue
        topical = near.loc[near["event_types"].apply(lambda t: on_topic(m["title"], t))]
        if topical.empty:
            rows.append({**base, "link": "TOPIC_MISMATCH", "event_id": None, "days_gap": None,
                         "weak_label": None, "weak_strength": None})
            continue
        near = topical
        e = near.iloc[(near["_d"] - md).dt.days.abs().argsort()].iloc[0]
        rows.append({**base, "link": "DISCLOSURE_NEAR", "event_id": e["event_id"],
                     "days_gap": int((e["_d"] - md).days), "weak_label": e["weak_label"],
                     "weak_strength": e["weak_strength"]})
    return pd.DataFrame(rows)


def upload_links(conn, links):
    cols = ["doc_id", "target_name", "company_name", "published_at", "link", "event_id", "days_gap",
            "weak_label", "weak_strength", "in_seed", "source"]
    rows = nan_to_none(links[cols]).values.tolist()
    with conn.transaction():
        conn.execute("DELETE FROM p05.news_event_link")
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO p05.news_event_link ({', '.join(cols)}, rule_version) "
                f"VALUES ({', '.join(['%s'] * len(cols))}, %s)", [r + [RULE_VERSION] for r in rows])
    return len(rows)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    roster = pd.read_csv(DATA / "person_target_roster_dart_20261027.csv", dtype=str)
    code_of = (roster.drop_duplicates("company_name").set_index("company_name")["company_id"]
               .str.replace("KRX:", "", regex=False).to_dict())
    dev_cos = W.training_companies(roster)
    codes = [code_of[c] for c in dev_cos]
    name_of = {code_of[c]: c for c in dev_cos}
    events = pd.read_csv(DATA / f"disclosure_weak_labels_{AS_OF.replace('-', '')}.csv", dtype={"stock_code": str})
    seed_urls = set(pd.read_csv(DATA / "person_news_seed_20261027.csv", dtype=str)["source_url"].dropna().map(norm_url))

    with psycopg.connect(db_url()) as conn:
        conn.autocommit = True
        conn.execute("SET statement_timeout = '60s'")
        with conn.transaction():
            conn.execute(DDL)
        n_ev = upload_events(conn, events)
        news = fetch_dev_news(conn, codes)
        matched = match_names(news, roster, name_of)
        roles_of = roster.groupby(["company_name", "canonical_name"])["role"].apply(set).to_dict()
        links = link(matched, events, seed_urls, roles_of) if len(matched) else pd.DataFrame()
        n_link = upload_links(conn, links) if len(links) else 0
        check = conn.execute("""SELECT (SELECT count(*) FROM p05.disclosure_weak_label),
                                       (SELECT count(*) FROM p05.news_event_link)""").fetchone()

    links.to_csv(DATA / f"db_news_event_link_{AS_OF.replace('-', '')}.csv", index=False, encoding="utf-8-sig")
    print(f"사건 업로드 {n_ev}행 | dev 회사 기사 {len(news)}건(URL 중복 제거 뒤, {news['source'].value_counts().to_dict()}) "
          f"({news['published_at'].min()} ~ {news['published_at'].max()})")
    print(f"명부 이름 일치 {len(matched)}행 (기사 {matched['doc_id'].nunique() if len(matched) else 0}건) | 연결 업로드 {n_link}행")
    if len(links):
        print("연결:", links["link"].value_counts().to_dict(), "| seed와 겹침:", int(links["in_seed"].sum()))
        print("회사별:", links["company_name"].value_counts().to_dict())
        print("연결된 행의 약한 라벨:", links["weak_label"].value_counts().to_dict())
    print("DB 재확인(p05 표 행 수):", check)


if __name__ == "__main__":
    main()
