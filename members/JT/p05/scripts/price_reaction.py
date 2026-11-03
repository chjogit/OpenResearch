"""기사 게시일 전후 주가 반응으로 만드는 보조 라벨(약한 라벨).

목적: 사람 정답이 없어도 '이 사건 뒤 주가가 시장보다 유의하게 움직였는가'를 객관적 숫자로 남겨
      공개 모델 기준선과 비교하고, 나중에 학습용 보조 신호로 쓴다.

정의(결과를 보기 전에 고정, 2026-10-28)
- 수익률: 종가 기준 일간 단순수익률
- 초과수익률(AR): 종목 수익률 - 같은 시장 지수 수익률(코스피 종목은 KOSPI, 코스닥 종목은 KOSDAQ)
- 사건일(t0): 기사 게시일 당일 또는 그 뒤 첫 거래일(게시 시각을 모르므로 장 마감 뒤 기사도 다음 날 반응을 잡도록 2일 창을 쓴다)
- 사건 창: t0 ~ t0+1 누적초과수익률 CAR[0,+1]
- 평소 변동성: t0-120 ~ t0-11 거래일 AR의 표준편차 σ (최소 60일)
- z = CAR[0,+1] / (σ × √2)
- 라벨: z ≥ 1.96 → positive, z ≤ -1.96 → negative, 그 사이 → neutral
- 라벨을 붙이지 않는 경우: 사건 창이 기준일 뒤로 넘어감, 평소 변동성 계산 일수 부족, 가격 없음

한계
- 회사 주가 반응이라 대상 인물 하나의 영향만 따로 떼어 내지 못한다(사람 라벨과 정의가 다르다).
- 같은 시기 다른 사건(실적 발표, 다른 기사)이 섞일 수 있다. 같은 회사의 다른 사건이 ±2거래일 안에 있으면 OVERLAP으로 표시한다.
- 사람 정답을 대신하지 않는다. 주석 시트에는 넣지 않는다(주석자 독립성).
- 주가 급변일을 보고 찾은 기사(수집 메모 '주가 급변일 탐색')는 selected_by_price=True로 표시한다.
  결과로 고른 표본이므로 일치도·성능 추정에서는 빼고 본다.

자료: 네이버 금융 일봉 차트(https://fchart.stock.naver.com/sise.nhn), 시장 구분은 네이버 증권 종목 기본정보.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import re

import numpy as np
import pandas as pd
import requests

CHART_URL = "https://fchart.stock.naver.com/sise.nhn"
BASIC_URL = "https://m.stock.naver.com/api/stock/{code}/basic"
HEADERS = {"User-Agent": "Mozilla/5.0"}

EST_WIN = (-120, -11)    # 평소 변동성 추정 창(거래일)
EVENT_WIN = (0, 1)       # 사건 창(거래일)
MIN_EST_DAYS = 60        # 변동성 추정에 필요한 최소 일수
Z_CUT = 1.96             # 양측 5% 기준
OVERLAP_DAYS = 2         # 같은 회사 다른 사건이 이 거래일 안에 있으면 표시
PRICE_LABELS = ["negative", "neutral", "positive"]


# ---------------------------------------------------------------------------
# 1. 가격 받기와 보관
# ---------------------------------------------------------------------------
def fetch_daily(symbol, count=500):
    """일봉 종가를 받는다. symbol은 종목코드 6자리 또는 KOSPI/KOSDAQ."""
    r = requests.get(CHART_URL, params={"symbol": symbol, "timeframe": "day", "count": count, "requestType": 0},
                     headers=HEADERS, timeout=20)
    r.raise_for_status()
    rows = [x.split("|") for x in re.findall(r'data="([^"]+)"', r.text)]
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["close"] = df["close"].astype(float)
    return df[["date", "close"]]


def exchange_of(code):
    """종목의 상장 시장(KOSPI/KOSDAQ)을 조회한다. 추측하지 않는다."""
    r = requests.get(BASIC_URL.format(code=code), headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()["stockExchangeType"]["nameEng"]


def load_prices(codes, raw_dir, as_of, refresh=False):
    """종목·지수 종가를 내려받아 raw_dir에 보관한다. 기준일 이후 가격은 잘라 낸다(재현성).
    이미 받은 파일이 있으면 refresh=True일 때만 다시 받는다."""
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    meta_path = raw_dir / "_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"market": {}}
    cut = pd.Timestamp(as_of)
    prices = {}
    for sym in sorted(set(codes)) + ["KOSPI", "KOSDAQ"]:
        path = raw_dir / f"{sym}.csv"
        if refresh or not path.exists():
            df = fetch_daily(sym)
            df.loc[df["date"] <= cut].to_csv(path, index=False, encoding="utf-8")
            meta.setdefault("fetched_at", {})[sym] = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")
        prices[sym] = pd.read_csv(path, parse_dates=["date"])
        if sym not in ("KOSPI", "KOSDAQ") and sym not in meta["market"]:
            meta["market"][sym] = exchange_of(sym)
    meta.update({"source": CHART_URL, "as_of_cut": as_of})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return prices, meta["market"]


# ---------------------------------------------------------------------------
# 2. 초과수익률과 라벨
# ---------------------------------------------------------------------------
def abnormal_returns(stock, index):
    """같은 거래일끼리 맞춰 종목 수익률 - 지수 수익률을 구한다."""
    m = stock.merge(index, on="date", suffixes=("", "_idx")).sort_values("date").reset_index(drop=True)
    m["ar"] = m["close"].pct_change() - m["close_idx"].pct_change()
    return m[["date", "ar"]].dropna().reset_index(drop=True)


def event_reaction(ar, event_date):
    """사건 하나의 CAR[0,+1], σ, z, 라벨과 상태를 돌려준다."""
    ed = pd.Timestamp(event_date)
    after = ar.index[ar["date"] >= ed]
    if len(after) == 0:
        return {"status": "NO_PRICE"}
    t0 = int(after[0])
    out = {"t0": ar.loc[t0, "date"].strftime("%Y-%m-%d")}
    if t0 + EVENT_WIN[1] >= len(ar):
        return {**out, "status": "WINDOW_INCOMPLETE"}   # 기준일까지 사건 창이 다 지나지 않음
    est = ar.loc[max(0, t0 + EST_WIN[0]): t0 + EST_WIN[1], "ar"]
    if len(est) < MIN_EST_DAYS:
        return {**out, "status": "SHORT_ESTIMATION"}
    car = float(ar.loc[t0 + EVENT_WIN[0]: t0 + EVENT_WIN[1], "ar"].sum())
    n = EVENT_WIN[1] - EVENT_WIN[0] + 1
    sigma = float(est.std(ddof=1))
    z = car / (sigma * np.sqrt(n))
    label = "positive" if z >= Z_CUT else "negative" if z <= -Z_CUT else "neutral"
    return {**out, "status": "LABELED", "car_0_1": round(car, 5), "sigma_est": round(sigma, 5),
            "z": round(z, 3), "price_label": label, "t0_index": t0}


def event_key(note, news_id):
    """수집 메모의 사건 묶음(EV-...)을 쓰고, 없으면 기사 ID를 사건으로 본다."""
    m = re.search(r"사건 (EV-[\w-]+)", str(note))
    return m.group(1) if m else news_id


def compute_reactions(targets, news, roster, prices, market_of):
    """대상 행마다 주가 반응 라벨을 붙인다. 같은 기사의 대상 행은 같은 값을 갖는다."""
    code_of = (roster.drop_duplicates("company_name").set_index("company_name")["company_id"]
               .str.replace("KRX:", "", regex=False).to_dict())
    note_of = news.set_index("news_id")["collection_note"].to_dict()
    ar_cache, rows = {}, []
    for _, t in targets.iterrows():
        code = code_of[t["company_name"]]
        market = market_of[code]
        if code not in ar_cache:
            ar_cache[code] = abnormal_returns(prices[code], prices[market])
        res = event_reaction(ar_cache[code], t["event_date"])
        note = note_of.get(t["news_id"], "")
        rows.append({"row_id": t["row_id"], "news_id": t["news_id"], "company_name": t["company_name"],
                     "split": t["split"], "stock_code": code, "market": market, "event_date": t["event_date"],
                     "event_key": event_key(note, t["news_id"]),
                     # 주가 급변일을 보고 찾은 기사는 결과로 고른 표본이라 성능 추정에서 분리한다
                     "selected_by_price": "주가 급변일 탐색" in str(note), **res})
    out = pd.DataFrame(rows)

    # 같은 회사의 다른 사건이 가까운 거래일에 있으면 반응이 섞였을 수 있다
    out["overlap"] = False
    lab = out.loc[out["status"].eq("LABELED")]
    for i, r in lab.iterrows():
        near = lab.loc[(lab["company_name"] == r["company_name"]) & (lab["event_key"] != r["event_key"])
                       & ((lab["t0_index"] - r["t0_index"]).abs() <= OVERLAP_DAYS)]
        out.loc[i, "overlap"] = not near.empty
    return out.drop(columns=["t0_index"])
