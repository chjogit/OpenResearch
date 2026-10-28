"""데이터 계산(순수 함수) 테스트. DB·LLM 없이 실행됩니다: pytest members/CH/tests"""
import math

from ch_agents import agent1_macro as macro, agent3_sentiment_flow as sentiment, financial
from ch_agents.facts import (
    Facts,
    corr_beta,
    daily_returns,
    fmt,
    pct_change,
    percentile_rank,
    shift_months,
    streak,
)
from ch_agents.llm import PLACEHOLDER, sentence_problems
from conftest import AS_OF, CO, months, trading_days

# ---------------------------------------------------------------- facts

def test_fmt_units():
    assert fmt(1.5e12, "KRW") == "1.50조원"
    assert fmt(-4.09e10, "KRW±") == "-409억원"
    assert fmt(2.2e9, "KRW±") == "+22억원"
    assert fmt(0.5, "%p") == "+0.50%p"
    assert fmt(None, "%") == "무자료"
    assert fmt(float("nan"), "배") == "무자료"


def test_pct_change_guards_negative_base():
    assert pct_change(110, 100) == 10.000000000000009
    assert pct_change(10, -5) is None  # 적자 기준 증감률은 계산하지 않음
    assert pct_change(10, 0) is None


def test_streak_and_percentile():
    assert streak([3, 1, 2, -1]) == 3
    assert streak([-3, -1, 2]) == -2
    assert streak([0, 1]) == 0
    assert percentile_rank([1, 2, 3, 4, 5], 5) == 90
    assert percentile_rank([1, 2], 1) is None


def test_corr_beta_known_line():
    xs = [i / 100 for i in range(-20, 20)]
    r, b, n = corr_beta(xs, [0.8 * x for x in xs])
    assert n == 40 and math.isclose(r, 1) and math.isclose(b, 0.8)
    assert corr_beta(xs[:10], xs[:10])[0] is None  # 표본 30 미만


def test_shift_months_month_end():
    assert shift_months("2026-03-31", 1) == "2026-02-28"
    assert shift_months("2026-01-15", 3) == "2025-10-15"


def test_daily_returns_drop_split_like_jumps():
    pts = [("d1", 100.0), ("d2", 101.0), ("d3", 20.2)]  # 1/5 액면분할처럼 보이는 하락
    r = daily_returns(pts)
    assert "d3" not in r and math.isclose(r["d2"], 0.01)


def test_facts_gap_on_missing_value():
    f = Facts("X")
    assert f.add("a", None, "%") is None
    assert f.gaps == [{"label": "a", "reason": "DB 값 없음"}]
    assert f.add("b", 1.0, "%") == "X1"


# ---------------------------------------------------------------- A1

def _macro_bundle(rng, stock_beta=0.8):
    days = trading_days(270)
    ks, px, usd, dgs = [2500.0], [70000.0], [1400.0], [4.0]
    mkt = [rng.gauss(0, 0.01) for _ in days]
    for i in range(1, len(days)):
        ks.append(ks[-1] * (1 + mkt[i]))
        px.append(px[-1] * (1 + stock_beta * mkt[i] + rng.gauss(0, 0.005)))
        usd.append(usd[-1] * (1 + rng.gauss(0, 0.004)))
        dgs.append(dgs[-1] + rng.gauss(0, 0.03))
    ms = months(26)
    series = {
        "ECOS_BASE_RATE": [{"d": d, "v": 2.5 if i < 23 else 3.0} for i, d in enumerate(ms)],
        "FEDFUNDS": [{"d": d, "v": 4.5 - i * 0.03} for i, d in enumerate(ms)],
        "CPIAUCSL": [{"d": d, "v": 300 * (1.003 ** i)} for i, d in enumerate(ms)],
        "KCS_EXP_854232_USD": [{"d": d, "v": 1e9 * (1 + i * 0.1)} for i, d in enumerate(ms)],
        "ECOS_USDKRW": [{"d": d, "v": v} for d, v in zip(days, usd)],
        "DGS10": [{"d": d, "v": v} for d, v in zip(days, dgs)],
    }
    return {"series": series, "index": {"^KS11": [{"d": d, "v": v} for d, v in zip(days, ks)]},
            "price": [{"d": d, "v": v} for d, v in zip(days, px)], "docs": [{"title": "환율 급등", "published": AS_OF}]}


def test_macro_regimes_exports_and_comovement(rng):
    out = macro.compute(_macro_bundle(rng), CO, AS_OF)
    f = out["facts"]
    k = f.key_of("한국 기준금리 12개월 변화")
    assert f.items[k]["value"] == 0.5
    assert any("한국 기준금리: 인상 국면" in x for x in f.flags)
    assert any("미국 기준금리(실효): 인하 국면" in x for x in f.flags)
    assert f.key_of("반도체 메모리 수출(최근 월) 전년 대비")
    assert f.items[f.key_of("반도체 메모리 수출: 최근 6개월 중 전년 대비 증가한 달")]["value"] == 6
    beta = f.items[f.key_of("주가-코스피 베타(250일)")]["value"]
    assert 0.6 < beta < 1.0
    assert any("주가-코스피: 상관 강함·유의함" in x for x in f.flags)
    assert any("주가-원/달러: 상관 약함·유의하지 않음" in x for x in f.flags)
    assert "주가-필라델피아 반도체지수 동조성" in [g["label"] for g in f.gaps]  # 반도체인데 SOX 없음 → 무자료
    assert out["sector"] == "반도체"
    assert any(n.startswith("전달 경로") for n in f.notes)


def test_macro_lag_uses_previous_us_day(rng):
    """미국 금리는 한국 거래일 d 에 미국 직전 거래일 변화를 맞춤: 같은 날 변화와 다른 결과여야 함."""
    b = _macro_bundle(rng)
    days = [p["d"] for p in b["price"]]
    px = [p["v"] for p in b["price"]]
    dgs = [b["series"]["DGS10"][0]["v"]]
    for i in range(1, len(days)):  # 주가 변화를 '전날' 금리 변화로 만든다
        dgs.append(dgs[-1] + (px[i + 1] / px[i] - 1) * 10 if i + 1 < len(days) else dgs[-1])
    b["series"]["DGS10"] = [{"d": d, "v": v} for d, v in zip(days, dgs)]
    f = macro.compute(b, CO, AS_OF)["facts"]
    r = f.items[f.key_of("주가-미국 10년 국채금리 상관(250일)")]["value"]
    assert r > 0.9


def test_macro_flags_have_no_loose_numbers(rng):
    f = macro.compute(_macro_bundle(rng), CO, AS_OF)["facts"]
    for fl in f.flags:
        assert not sentence_problems(fl, set(f.items)), fl
        assert all(k in f.items for k in PLACEHOLDER.findall(fl))


# ---------------------------------------------------------------- A2 (삼성전자 실제 값으로 회귀 테스트)

REAL_Q = [  # core.financial_quarter 005930 (2026-10-26 조회), 단위 원
    ("2024-03-31", 2024, 1, 71915601000000, 6606009000000, 6754708000000),
    ("2024-06-30", 2024, 2, 74068302000000, 10443878000000, 9841345000000),
    ("2024-09-30", 2024, 3, 79098731000000, 9183371000000, 10100904000000),
    ("2024-12-31", 2024, 4, 75788269000000, 6492703000000, 7754394000000),
    ("2025-03-31", 2025, 1, 79140503000000, 6685272000000, 8222878000000),
    ("2025-06-30", 2025, 2, 74566317000000, 4676057000000, 5116435000000),
    ("2025-09-30", 2025, 3, 86061747000000, 12166062000000, 12225747000000),
    ("2025-12-31", 2025, 4, 93837371000000, 20073660000000, 19641745000000),
    ("2026-03-31", 2026, 1, 133873444000000, 57232797000000, 47225272000000),
    ("2026-06-30", 2026, 2, 171499470000000, 89492412000000, 71624461000000),
]
REAL_MCAP = {"2024-12-31": 317592431660000, "2025-03-31": 342155071891600, "2025-06-30": 353994347735600,
             "2025-09-30": 496657621655800, "2025-12-31": 709764586847800, "2026-03-31": 989763460558400,
             "2026-06-30": 1952657055072000, AS_OF: 1259873040024000}


def _fin_bundle(**over):
    b = {
        "ttm": {"ttm_end": "2026-06-30", "bs_end": "2026-06-30", "revenue_ttm": 485272032000000,
                "operating_income_ttm": 178964931000000, "net_income_ttm": 150717225000000, "op_margin_ttm": 0.3688,
                "roe_ttm": 0.2602, "debt_ratio": 0.311, "per_ttm": 8.36, "pbr": 2.17, "equity": 579309676000000},
        "quarters": [{"period_end": pe, "fiscal_year": fy, "fiscal_q": fq,
                      "m": {"revenue": rev, "operating_income": op, "net_income": ni}}
                     for pe, fy, fq, rev, op, ni in REAL_Q],
        "valuation": {"fiscal_year": 2025, "price_date": "2026-10-23", "per": 27.87, "pbr": 2.89},
        "annual": [{"fiscal_year": 2025, "revenue": 333605938000000, "operating_income": 43601051000000,
                    "net_income": 45206805000000}],
        "cash": [{"fiscal_year": 2025, "acct": "영업활동현금흐름", "amounts": [85315148000000]},
                 {"fiscal_year": 2025, "acct": "유형자산의취득", "amounts": [47522179000000]},
                 {"fiscal_year": 2025, "acct": "배당금의지급", "amounts": [9897183000000]},
                 {"fiscal_year": 2025, "acct": "자기주식의취득", "amounts": [0, 8189263000000]},
                 {"fiscal_year": 2025, "acct": "이자의지급", "amounts": [469730000000]}],
        "mcap": [{"d": d, "v": v} for d, v in REAL_MCAP.items()],
        "peers": [{"market": "KR", "ticker": f"P{i}", "name": f"p{i}", "op_margin_ttm": m, "roe_ttm": m / 2,
                   "per_ttm": p, "pbr": 1.5, "debt_ratio": 0.5}
                  for i, (m, p) in enumerate([(0.68, 5.75), (0.2, 30), (0.1, -3), (0.25, 20), (0.15, 15)])],
        "peer_method": "manual:반도체",
        "risk": {"max_drawdown_250d": -0.4289, "volatility_60d": 0.88, "below_52w_high": -0.4055},
    }
    b.update(over)
    return b


def test_financial_real_samsung_per_band_matches_v_ttm():
    f = financial.compute(_fin_bundle(), CO, AS_OF)["facts"]
    cur = f.items[f.key_of("PER 밴드 현재값(시가총액 ÷ 최근 TTM 순이익)")]["value"]
    assert abs(cur - 8.36) < 0.01  # v_ttm.per_ttm 과 같은 정의
    assert f.key_of("PER(TTM 기준)") and f.key_of("PER(연간 FY2025 기준)")  # 두 기준을 다른 키로
    # 매출 전년 동기 대비: 171.50조 / 74.57조
    yoy = f.items[f.key_of("2026년 2분기 매출 전년 동기 대비")]["value"]
    assert abs(yoy - (171499470000000 / 74566317000000 - 1) * 100) < 1e-6
    assert f.items[f.key_of("매출 전년 동기 대비 연속 증가 분기 수")]["value"] == 6  # 2025Q1~2026Q2
    fcf = f.items[f.key_of("FY2025 잉여현금흐름(FCF)")]["value"]
    assert fcf == 85315148000000 - 47522179000000
    icr = f.items[f.key_of("이자보상배율 대용치(FY2025)")]
    assert icr["kind"] == "대용치" and abs(icr["value"] - 43601051000000 / 469730000000) < 1e-6
    assert not any(x.startswith("데이터 점검") for x in f.flags)  # 분기 합계 = TTM


def test_financial_peer_median_excludes_negative_per():
    f = financial.compute(_fin_bundle(), CO, AS_OF)["facts"]
    assert f.items[f.key_of("Peer PER(TTM) 중앙값")]["value"] == 17.5  # 5.75, 15, 20, 30 (적자 −3 제외)
    assert f.items[f.key_of("Peer 영업이익률 중앙값")]["value"] == 20.0


def test_financial_distress_flags():
    b = _fin_bundle()
    b["ttm"] = {**b["ttm"], "debt_ratio": 2.5, "net_income_ttm": -1e12}
    b["cash"] = [{"fiscal_year": 2025, "acct": "영업활동현금흐름", "amounts": [-5e11]},
                 {"fiscal_year": 2025, "acct": "유형자산의취득", "amounts": [1e12]},
                 {"fiscal_year": 2025, "acct": "이자의지급", "amounts": [5e13]}]
    f = financial.compute(b, CO, AS_OF)["facts"]
    joined = " ".join(f.flags)
    for word in ("TTM 순손실", "부채비율 과다", "영업현금흐름 적자", "잉여현금흐름 적자", "이자보상배율 대용치 1 미만"):
        assert word in joined, word
    for fl in f.flags:
        assert not sentence_problems(fl, set(f.items)), fl


def test_financial_data_consistency_flag():
    b = _fin_bundle()
    b["ttm"] = {**b["ttm"], "revenue_ttm": 400000000000000}
    f = financial.compute(b, CO, AS_OF)["facts"]
    assert any(x.startswith("데이터 점검") for x in f.flags)


def test_financial_missing_ttm_is_gap():
    f = financial.compute({"quarters": [], "peers": []}, CO, AS_OF)["facts"]
    labels = [g["label"] for g in f.gaps]
    assert "TTM 실적·멀티플" in labels and "분기 추세" in labels and "Peer 비교" in labels


# ---------------------------------------------------------------- A4

def _flow_rows(n=120, fq=-1000, hold0=46.0):
    days = trading_days(n)[::-1]  # 최신순
    return [{"d": d, "fq": fq, "iq": 500, "pq": -fq - 500, "hold": hold0 + i * 0.01, "close": 200000,
             "tv": 1e12} for i, d in enumerate(days)]


def _sent_bundle(**over):
    days = trading_days(80)
    b = {
        "flows": _flow_rows(),
        "price": [{"d": d, "v": 300000 - i * 1000} for i, d in enumerate(days)],
        "kospi": [{"d": d, "v": 3000 + i} for i, d in enumerate(days)],
        "vix": [{"d": d, "v": 15 + (i % 10)} for i, d in enumerate(trading_days(250))],
        "docs": [
            {"d": "2026-10-25", "source": "naver_news", "n": 10, "score": 0.5},
            {"d": "2026-10-24", "source": "naver_news", "n": 0, "score": None},  # 점수 없는 날은 제외
            {"d": "2026-10-10", "source": "naver_news", "n": 30, "score": 0.0},
            {"d": "2026-10-09", "source": "naver_news", "n": 1, "score": 0.0},
            {"d": "2026-10-08", "source": "naver_news", "n": 1, "score": 0.0},
            {"d": "2026-10-07", "source": "naver_news", "n": 1, "score": 0.0},
            {"d": "2026-10-06", "source": "naver_news", "n": 1, "score": 0.0},
            {"d": "2026-10-05", "source": "naver_news", "n": 1, "score": 0.0},
            {"d": "2026-10-04", "source": "naver_news", "n": 1, "score": 0.0},
            {"d": "2026-10-25", "source": "naver_blog", "n": 3, "score": -0.5},
        ],
        "search": [{"d": d, "v": 10.0 if i < 393 else 30.0} for i, d in
                   enumerate(sorted({(__import__("datetime").date(2026, 10, 25)
                                      - __import__("datetime").timedelta(days=k)).isoformat() for k in range(400)}))],
        "lending": None,
    }
    b.update(over)
    return b


def test_sentiment_flows_streak_intensity_and_divergence():
    f = sentiment.compute(_sent_bundle(flows=_flow_rows(fq=1000)), CO, AS_OF)["facts"]
    assert f.items[f.key_of("외국인 20일 순매수 수량")]["value"] == 20000
    inten = f.items[f.key_of("외국인 20일 순매수 강도(거래대금 대비)")]["value"]
    assert math.isclose(inten, 20000 * 200000 / (20 * 1e12) * 100)
    assert f.items[f.key_of("외국인 연속 순매수 일수")]["value"] == 120
    assert any("외국인 120거래일 연속 순매수" in x for x in f.flags)
    assert any(x.startswith("엇갈림: 주가 하락 중 외국인 순매수") for x in f.flags)


def test_sentiment_docs_weighting_and_gaps():
    f = sentiment.compute(_sent_bundle(), CO, AS_OF)["facts"]
    assert f.items[f.key_of("뉴스 감성(최근 7일)")]["value"] == 0.5
    assert f.items[f.key_of("뉴스 감성 변화(최근 7일 − 직전 8~30일)")]["value"] == 0.5
    assert any("이상 징후: 뉴스 논조 급격한 개선" in x for x in f.flags)  # 변화 0.5 ≥ 0.15
    labels = [g["label"] for g in f.gaps]
    assert "블로그 감성(최근 7일)" in labels  # 3건 < 최소 5건
    assert "주식대차 잔고(공매도 대용)" in labels
    assert not any("문서 수" in v["label"] for v in f.items.values())  # 문서 수는 관심 지표로 쓰지 않음


def test_sentiment_search_spike():
    f = sentiment.compute(_sent_bundle(), CO, AS_OF)["facts"]
    assert math.isclose(f.items[f.key_of("검색 관심도 배율(최근 7일 ÷ 직전 90일)")]["value"], 3.0)
    assert any("검색 관심 급증" in x for x in f.flags)


def test_sentiment_flags_have_no_loose_numbers():
    f = sentiment.compute(_sent_bundle(flows=_flow_rows(fq=1000)), CO, AS_OF)["facts"]
    for fl in f.flags:
        assert not sentence_problems(fl, set(f.items)), fl


def test_financial_sector_skips_debt_flag_and_name_hint():
    co = {**CO, "name": "KB금융", "peer_method": None, "krx_sector": None}
    assert macro.sector_of(co) == "기타금융"
    b = _fin_bundle()
    b["ttm"] = {**b["ttm"], "debt_ratio": 12.0}
    f = financial.compute(b, co, AS_OF)["facts"]
    assert not any("부채비율 과다" in x for x in f.flags)
    assert any(n.startswith("금융업") for n in f.notes)


def test_financial_missing_quarter_breaks_windows():
    b = _fin_bundle()
    b["quarters"] = [q for q in b["quarters"] if q["period_end"] != "2025-12-31"]  # 2025년 4분기 누락
    f = financial.compute(b, CO, AS_OF)["facts"]
    # 최근 4개 분기가 이어지지 않으므로 PER 밴드 현재값·TTM 매출 전년 대비를 만들지 않음
    assert f.key_of("PER 밴드 현재값(시가총액 ÷ 최근 TTM 순이익)") is None
    assert f.key_of("TTM 매출 전년 대비") is None
    # 전년 동기(2025-06-30)는 있으므로 분기 비교는 유지, 연속 증가는 누락 분기에서 끊김
    assert f.key_of("2026년 2분기 매출 전년 동기 대비")
    assert f.items[f.key_of("매출 전년 동기 대비 연속 증가 분기 수")]["value"] == 2


def test_macro_lag_skips_stale_us_data(rng):
    b = _macro_bundle(rng)
    b["series"]["DGS10"] = b["series"]["DGS10"][:-20]  # 미국 금리가 4주 늦게 멈춤
    f = macro.compute(b, CO, AS_OF)["facts"]
    from datetime import date
    last_us = b["series"]["DGS10"][-1]["d"]
    last_pair = f.items[f.key_of("주가-미국 10년 국채금리 상관(250일)")]["as_of"].split(" ~ ")[1]
    assert (date.fromisoformat(last_pair) - date.fromisoformat(last_us)).days <= 4  # 늦은 구간은 짝짓지 않음


def test_macro_new_series_cpi_spread_and_oil(rng):
    b = _macro_bundle(rng)
    ms = months(26)
    days = [p["d"] for p in b["price"]]
    b["series"]["ECOS_CPI"] = [{"d": d, "v": 110 * (1.002 ** i)} for i, d in enumerate(ms)]
    b["series"]["ECOS_KTB3Y"] = [{"d": d, "v": 3.0} for d in days]
    b["series"]["ECOS_KTB10Y"] = [{"d": d, "v": 3.5 if i < 200 else 2.8} for i, d in enumerate(days)]
    b["series"]["DCOILWTICO"] = [{"d": d, "v": 70.0 + i * 0.01} for i, d in enumerate(days)]
    f = macro.compute(b, CO, AS_OF)["facts"]
    assert f.key_of("한국 소비자물가 전년 대비")
    assert math.isclose(f.items[f.key_of("국고채 장단기 금리차(10년 − 3년)")]["value"], -0.2)
    assert any("한국 장단기 금리 역전" in x for x in f.flags)
    assert f.items[f.key_of("WTI 유가")]["text"].endswith("달러/배럴")
    assert "브렌트 유가" in [g["label"] for g in f.gaps]  # 없는 시리즈는 무자료


def test_sentiment_foreign_avg_price_proxy():
    rows = _flow_rows(fq=1000)
    for i, r in enumerate(rows):
        r["close"] = 200000 if i else 180000  # 오늘만 180,000
    f = sentiment.compute(_sent_bundle(flows=rows), CO, AS_OF)["facts"]
    k = f.key_of("외국인 순매수일 평균 가격(60일, 근사)")
    assert f.items[k]["kind"] == "대용치" and 199000 < f.items[k]["value"] < 200000
    assert any("외국인 순매수일 평균 가격(근사)보다 낮음" in x for x in f.flags)


def test_financial_peer_names_note():
    f = financial.compute(_fin_bundle(), CO, AS_OF)["facts"]
    note = next(n for n in f.notes if n.startswith("Peer 영업이익률 상위"))
    assert note.startswith("Peer 영업이익률 상위: p0, p3, p1")


def test_macro_drivers_follow_sector(rng):
    bank = {**CO, "name": "KB금융", "peer_method": None, "krx_sector": None}
    b = _macro_bundle(rng)
    b["series"]["ECOS_KTB3Y"] = [{"d": p["d"], "v": 3 + i * 0.001} for i, p in enumerate(b["price"])]
    f = macro.compute(b, bank, AS_OF)["facts"]
    labels = [v["label"] for v in f.items.values()] + [g["label"] for g in f.gaps]
    assert any("국고채 3년 금리 상관" in x for x in labels)
    assert not any("필라델피아" in x for x in labels)


def test_format_price_and_share_levels():
    assert fmt(260349.47, "KRW") == "260,349원"
    assert fmt(80501951, "주수") == "80,501,951주"
    assert fmt(-21805837, "주") == "-21,805,837주"


def test_macro_recent_window_wording(rng):
    """250일은 뚜렷하고 60일은 같은 방향이지만 약하면 '반대'가 아니라 '약함'으로 표시."""
    f = macro.compute(_macro_bundle(rng), CO, AS_OF)["facts"]
    for fl in f.flags:
        assert "최근 60일은 다름" not in fl


def test_sentiment_relative_performance_flag():
    f = sentiment.compute(_sent_bundle(), CO, AS_OF)["facts"]  # 주가 하락, 코스피 상승 → 하회
    assert any(x.startswith("20일 코스피 대비: 하회") for x in f.flags)
    assert "+면 코스피보다 나음" in f.items[f.key_of("20일 코스피 대비 초과 수익률")]["note"]


def test_sector_series_only_for_matching_sector(rng):
    from ch_agents import agent1_macro as macro

    b = _macro_bundle(rng)
    ms = months(26)
    b["series"]["PCOPPUSDM"] = [{"d": m, "v": 9000.0 + 10 * i} for i, m in enumerate(ms)]
    metal = dict(CO, name="고려아연", peer_method="manual:금속")
    f = macro.compute(b, metal, AS_OF)["facts"]
    k = f.key_of("국제 구리 가격 12개월 변화율")
    assert k and f.items[k]["value"] > 0
    assert any(g["label"] == "국제 철광석 가격" for g in f.gaps)     # 같은 업종이지만 아직 수집 전
    semi = macro.compute(b, CO, AS_OF)["facts"]                     # 반도체에는 올리지 않음
    assert semi.key_of("국제 구리 가격") is None
    assert not any("구리" in g["label"] for g in semi.gaps)


def test_china_exports_yoy_only_for_chemicals(rng):
    from ch_agents import agent1_macro as macro

    b = _macro_bundle(rng)
    b["series"]["ECOS_CHN_EXPORT"] = [{"d": m, "v": 300000.0 + 1000 * i} for i, m in enumerate(months(26))]
    f = macro.compute(b, dict(CO, name="LG화학", peer_method="manual:화학"), AS_OF)["facts"]
    assert f.key_of("중국 수출(통관기준) 전년 같은 달 대비")
    assert f.key_of("중국 수출(통관기준) 3개월 변화율") is None      # 계절성 때문에 3개월 변화는 쓰지 않음
    assert not any("중국" in g["label"] for g in f.gaps)
