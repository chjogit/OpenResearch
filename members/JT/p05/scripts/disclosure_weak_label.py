"""공시 유형 + 주가 반응으로 만드는 약한 라벨(weak label). 대상 감성 모델 학습용.

목적: 사람 주석 없이도 '대주주·경영진 관련 사건이 주주에게 유리했는가'의 학습용 정답 후보를 만든다.
      공시는 날짜·회사가 확정된 사건이라 기사보다 잡음이 적고, 주가 반응은 시장이 실제로 어떻게 받아들였는지를 준다.

규칙(결과를 보기 전에 고정, 2026-10-28)
1) 공시 제목(report_nm)으로 사건 유형과 사전 방향(prior)을 정한다. 아래 RULES 순서대로 처음 맞는 것 하나.
   - 정정 공시([기재정정] 등)와 결과보고서는 새 사건이 아니므로 뺀다.
   - 같은 회사·같은 접수일 공시는 한 사건으로 묶는다. prior가 서로 반대면 prior 없음으로 본다.
2) 주가 반응은 price_reaction.py와 같은 정의(CAR[0,+1], z ±1.96)를 쓴다.
3) 약한 라벨
   - prior와 주가 방향이 같음        → prior, 강도 AGREE
   - prior 있음 + 주가 neutral       → prior, 강도 PRIOR_ONLY
   - prior와 주가 방향이 반대         → HOLD(학습에서 뺌), 강도 CONFLICT
   - prior 없음                      → 주가 라벨, 강도 PRICE_ONLY
   - 가격 계산 불가                  → prior가 있으면 prior(PRIOR_ONLY), 없으면 HOLD(NO_PRICE)
4) holdout 회사(해시 분할 규칙상 holdout으로 가는 회사)는 공시도 받지 않는다. 회사 단위 누수를 막는다.

v2 수정(2026-10-28, dev 공시 제목 148종 점검). 주가 결과를 보고 바꾼 것이 아니라 범위 오류·누락만 고쳤다.
- 자회사·종속회사 주요경영사항 공시는 prior를 붙이지 않는다(주가 라벨만). 그 회사 경영진의 결정이 아니기 때문이다.
- "대표이사(대표집행임원)변경(안내공시)"가 "대표이사변경"과 글자가 달라 빠지던 것을 넣는다.
- "소송등의판결ㆍ결정"을 수사·재판 사건(prior 없음)으로 넣는다.
- 공시마다 제출인(flr_nm)을 filers 열에 남긴다. 기사 연결 때 지분 공시가 그 인물 것인지 확인하는 데 쓴다(p05_db_sync.py).

한계
- 공시 제목만으로는 매수·매도 방향을 모르는 신고(소유상황보고서 등)가 많다. 이들은 주가 라벨만 따른다.
- 회사 주가 반응이라 인물 효과를 분리하지 못한다. 같은 날 실적 발표 등이 섞일 수 있다.
- 사람 정답을 대신하지 않는다. 주석 시트에는 넣지 않는다(주석자 독립성).

자료
- 공시: Neon DB core.disclosure(읽기 전용, DATABASE_URL이 있을 때) 또는 OpenDART list API(DART_API_KEY)
- 가격: 네이버 금융 일봉(price_reaction.py, data/price_raw/ 캐시)

사용 방법(프로젝트 폴더에서):
  .venv-sentiment\\Scripts\\python.exe scripts\\disclosure_weak_label.py            # 자동: DB 주소 있으면 DB, 없으면 DART
  .venv-sentiment\\Scripts\\python.exe scripts\\disclosure_weak_label.py --source dart
"""
from pathlib import Path
import argparse
import json
import os
import re
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dart_person_roster as D
import person_target_pipeline as P
import price_reaction as R

PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA = PROJECT_DIR / "data"
AS_OF = "2026-10-27"
START = "2026-01-01"
LINK_DAYS = 3   # 기사 게시일과 공시 접수일 차이가 이 일수 안이면 같은 사건 후보로 본다

# (제목에 들어 있는 말, 사건 유형, 사전 방향). 순서가 우선순위다. None은 제목만으로 방향을 정하지 않는다.
RULES = [
    ("횡령ㆍ배임", "수사·재판", "negative"),
    ("배임", "수사·재판", "negative"),
    ("자기주식처분", "주주환원", "negative"),
    ("자기주식소각", "주주환원", "positive"),
    ("주식소각", "주주환원", "positive"),
    ("자기주식취득", "주주환원", "positive"),
    ("배당", "주주환원", "positive"),
    ("기업가치제고계획", "주주환원", "positive"),
    ("무상증자", "자본조달", "positive"),
    ("유상증자", "자본조달", "negative"),
    ("전환사채권발행", "자본조달", "negative"),
    ("신주인수권부사채권발행", "자본조달", "negative"),
    ("교환사채권발행", "자본조달", "negative"),
    ("최대주주변경", "지배구조변경", None),
    ("대표이사변경", "선임·교체", None),
    ("대표이사(대표집행임원)변경", "선임·교체", None),
    ("소송등의판결ㆍ결정", "수사·재판", None),
    ("최대주주등소유주식변동", "지분변동", None),
    ("특정증권등소유상황", "지분변동", None),
    ("대량보유상황", "지분변동", None),
    ("타법인주식및출자증권취득", "투자·M&A", None),
    ("타법인주식및출자증권처분", "투자·M&A", None),
    ("회사합병", "투자·M&A", None),
    ("회사분할", "투자·M&A", None),
]
SKIP_PATTERNS = ("정정]", "결과보고서")
SUBSIDIARY_PATTERNS = ("자회사의주요경영사항", "종속회사의주요경영사항")   # 유형은 남기고 prior만 없앤다


def classify(report_nm):
    """공시 제목 → (사건 유형, prior). 대상 밖이면 (None, None)."""
    nm = re.sub(r"\s+", "", str(report_nm))
    if any(s in nm for s in SKIP_PATTERNS):
        return None, None
    for word, etype, prior in RULES:
        if word in nm:
            return etype, (None if any(s in nm for s in SUBSIDIARY_PATTERNS) else prior)
    return None, None


# ---------------------------------------------------------------------------
# 1. 학습에 쓸 회사(holdout 회사 제외)
# ---------------------------------------------------------------------------
def training_companies(roster):
    """명부 회사 중 해시 분할 규칙상 dev로 가는 회사만. 기사 없는 회사도 같은 규칙을 미리 적용한다."""
    companies = sorted(roster["company_name"].unique())
    split = P.assign_company_split(companies)
    return [c for c in companies if split[c] == "dev"]


# ---------------------------------------------------------------------------
# 2. 공시 목록: DB 우선, 없으면 DART
# ---------------------------------------------------------------------------
def disclosures_from_db(stock_codes):
    """Neon core.disclosure 조회(읽기 전용). 열 이름은 kic-agent-data sql/002_core_tables.sql 기준.
    주의: DB 주소가 아직 없어 이 함수는 실제 DB로 실행해 보지 못했다(미검증).
    DB 공시 수집 범위에 지분공시가 빠져 있으면 지분변동 사건이 DART 경로보다 적게 나온다."""
    import psycopg   # DB를 쓸 때만 필요하다
    sql = """SELECT c.ticker AS stock_code, d.rcept_no, d.rcept_dt, d.report_nm
             FROM core.disclosure d JOIN core.company c ON c.company_id = d.company_id
             WHERE c.market = 'KR' AND c.ticker = ANY(%(codes)s) AND d.rcept_dt BETWEEN %(lo)s AND %(hi)s"""
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '15s'")
        rows = conn.execute(sql, {"codes": list(stock_codes), "lo": START, "hi": AS_OF}).fetchall()
    df = pd.DataFrame(rows, columns=["stock_code", "rcept_no", "rcept_dt", "report_nm"])
    df["rcept_dt"] = pd.to_datetime(df["rcept_dt"]).dt.strftime("%Y%m%d")
    return df.assign(source="neon_core_disclosure")


def disclosures_from_dart(stock_codes):
    """OpenDART 공시검색(list) API. 회사별 전체 페이지를 받아 원본을 data/dart_raw/에 보관한다."""
    key = D.load_key()
    codes = D.corp_codes(key)
    rows = []
    for sc in stock_codes:
        cc = codes[sc]["corp_code"]
        params = {"corp_code": cc, "bgn_de": START.replace("-", ""), "end_de": AS_OF.replace("-", ""),
                  "page_count": 100}
        first = D.get_json(key, "list", {**params, "page_no": 1})
        items = first.get("list", []) if first.get("status") == "000" else []
        for page in range(2, int(first.get("total_page", 1) or 1) + 1):
            items += D.get_json(key, "list", {**params, "page_no": page}).get("list", [])
        raw = D.RAW_DIR / f"{sc}_list_{START.replace('-', '')}_{AS_OF.replace('-', '')}.json"
        raw.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        rows += [{"stock_code": sc, "rcept_no": it["rcept_no"], "rcept_dt": it["rcept_dt"],
                  "report_nm": it["report_nm"], "flr_nm": it.get("flr_nm", "")} for it in items]
    return pd.DataFrame(rows).assign(source="opendart_list")


def load_disclosures(stock_codes, source="auto"):
    if source == "db" or (source == "auto" and os.environ.get("DATABASE_URL")):
        return disclosures_from_db(stock_codes)
    return disclosures_from_dart(stock_codes)


# ---------------------------------------------------------------------------
# 3. 사건 묶기 → 주가 반응 → 약한 라벨
# ---------------------------------------------------------------------------
def to_events(disc, name_of):
    """대상 유형만 남기고 같은 회사·같은 접수일을 한 사건으로 묶는다."""
    d = disc.copy()
    d[["event_type", "prior"]] = d["report_nm"].apply(lambda s: pd.Series(classify(s)))
    d = d.loc[d["event_type"].notna()]

    def merge(g):
        priors = set(g["prior"].dropna())
        return pd.Series({
            "company_name": name_of[g.name[0]],
            "event_types": "|".join(sorted(set(g["event_type"]))),
            "report_nms": "|".join(g["report_nm"]),
            "rcept_nos": "|".join(g["rcept_no"]),
            "filers": "|".join(g["flr_nm"].fillna("")) if "flr_nm" in g else None,   # report_nms와 같은 순서
            "n_filings": len(g),
            "prior": priors.pop() if len(priors) == 1 else None,   # 반대 방향이 섞이면 prior 없음
            "source": g["source"].iloc[0],
        })
    ev = d.groupby(["stock_code", "rcept_dt"]).apply(merge, include_groups=False).reset_index()
    ev["event_date"] = pd.to_datetime(ev["rcept_dt"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    ev.insert(0, "event_id", [f"DE-{c}-{d}" for c, d in zip(ev["stock_code"], ev["rcept_dt"])])
    return ev


def weak_label(prior, price_label):
    if price_label is None or pd.isna(price_label):
        return (prior, "PRIOR_ONLY") if prior else ("HOLD", "NO_PRICE")
    if not prior:
        return price_label, "PRICE_ONLY"
    if price_label == prior:
        return prior, "AGREE"
    if price_label == "neutral":
        return prior, "PRIOR_ONLY"
    return "HOLD", "CONFLICT"


def label_events(ev, prices, market_of):
    ar_cache, rows = {}, []
    for _, e in ev.iterrows():
        code = e["stock_code"]
        if code not in ar_cache:
            ar_cache[code] = R.abnormal_returns(prices[code], prices[market_of[code]])
        res = R.event_reaction(ar_cache[code], e["event_date"])
        res.pop("t0_index", None)
        lab, strength = weak_label(e["prior"], res.get("price_label"))
        rows.append({**e.to_dict(), "market": market_of[code], **res,
                     "weak_label": lab, "weak_strength": strength})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 4. dev 기사 행과 공시 사건 연결
# ---------------------------------------------------------------------------
def link_news(targets, events):
    """dev 대상 행마다 같은 회사의 ±LINK_DAYS일 공시 사건 중 가장 가까운 것을 붙인다. holdout 행은 보지 않는다."""
    dev = targets.loc[targets["split"] == "dev"].copy()
    ev = events.assign(_d=pd.to_datetime(events["event_date"]))
    out = []
    for _, t in dev.iterrows():
        td = pd.Timestamp(t["event_date"])
        near = ev.loc[(ev["company_name"] == t["company_name"]) & ((ev["_d"] - td).dt.days.abs() <= LINK_DAYS)]
        base = {"row_id": t["row_id"], "news_id": t["news_id"], "company_name": t["company_name"],
                "event_date": t["event_date"], "target_name": t["target_name"]}
        if near.empty:
            out.append({**base, "link": "NO_DISCLOSURE"})
            continue
        e = near.iloc[(near["_d"] - td).dt.days.abs().argsort()].iloc[0]
        out.append({**base, "link": "DISCLOSURE_NEAR", "event_id": e["event_id"],
                    "days_gap": int((e["_d"] - td).days), "event_types": e["event_types"],
                    "weak_label": e["weak_label"], "weak_strength": e["weak_strength"]})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["auto", "db", "dart"], default="auto")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    roster = pd.read_csv(DATA / "person_target_roster_dart_20261027.csv", dtype=str)
    code_of = (roster.drop_duplicates("company_name").set_index("company_name")["company_id"]
               .str.replace("KRX:", "", regex=False).to_dict())
    train_cos = training_companies(roster)
    codes = [code_of[c] for c in train_cos]
    name_of = {code_of[c]: c for c in train_cos}

    disc = load_disclosures(codes, args.source)
    ev = to_events(disc, name_of)
    prices, market_of = R.load_prices(codes, DATA / "price_raw", AS_OF)
    events = label_events(ev, prices, market_of)
    tag = AS_OF.replace("-", "")
    events.to_csv(DATA / f"disclosure_weak_labels_{tag}.csv", index=False, encoding="utf-8-sig")

    targets = pd.read_csv(DATA / "person_target_candidates_20261027.csv", dtype=str)
    linked = link_news(targets, events)
    linked.to_csv(DATA / f"person_target_dev_disclosure_link_{tag}.csv", index=False, encoding="utf-8-sig")

    print(f"학습 회사 {len(train_cos)}곳 | 공시 {len(disc)}건 → 대상 사건 {len(events)}개 | 출처 {disc['source'].iloc[0]}")
    print("약한 라벨:", events["weak_label"].value_counts().to_dict())
    print("강도:", events["weak_strength"].value_counts().to_dict())
    print("유형:", events["event_types"].str.split("|").explode().value_counts().to_dict())
    print("dev 기사 연결:", linked["link"].value_counts().to_dict())


if __name__ == "__main__":
    main()
