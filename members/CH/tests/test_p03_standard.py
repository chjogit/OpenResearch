"""에이전트 3 제작 기준(docs/P03_투자심리수급_상세개발기획서.md) 연결 시험. DB·LLM 없이 합성 묶음으로 확인합니다.
합성 값은 계산·차단 규칙 검사용이며 성능 근거가 아닙니다."""
import random

from conftest import AS_OF, CO, trading_days
from test_compute import _sent_bundle

from ch_agents import agent3_sentiment_flow as sentiment
from ch_agents import p03
from ch_agents.agents import build_agent_data
from ch_agents.llm import run_agent


def _long_flows(n=260, spikes=(), seed=1):
    """최신순 수급 행. spikes: 그 인덱스(오래된 쪽부터)에서 외국인 대량 순매수."""
    rng = random.Random(seed)
    days = trading_days(n)
    rows = []
    for i, d in enumerate(days):
        fq = rng.gauss(0, 1000) + (40000 if any(s <= i < s + 5 for s in spikes) else 0)
        rows.append({"d": d, "fq": fq, "iq": rng.gauss(0, 1000), "pq": 0, "hold": 50.0, "close": 100000.0,
                     "tv": 1e10})
    return rows[::-1], days


def test_lending_and_search_on_as_of_are_cut():
    b = _sent_bundle(lending=[{"d": d, "v": 100.0} for d in trading_days(30, end=AS_OF)])
    b["search"] = b["search"] + [{"d": AS_OF, "v": 99.0}]
    out = sentiment.compute(b, CO, AS_OF)
    av = out["p03"]["availability"]
    assert any(k.startswith("대차잔고") for k in av["cut"]) and any(k.startswith("검색") for k in av["cut"])
    assert "AVAILABILITY_CUT" in out["p03"]["plan"]["status_codes"]


def test_intent_question_is_held_and_forecast_needs_model():
    out = sentiment.compute(_sent_bundle(), CO, AS_OF, question="외국인이 뭔가 알고 사는 거지? 앞으로 오를까?")
    t = out["p03"]["plan"]["tasks"]
    assert t["의도"]["state"] == "held" and t["예측"]["state"] == "held"
    codes = out["p03"]["plan"]["status_codes"]
    assert "INTENT_NOT_INFERABLE" in codes and "MODEL_NOT_APPROVED" in codes
    assert t["관측"]["state"] == "answered"


def test_signal_days_detects_planted_buying_once_per_run():
    rows, days = _long_flows(spikes=(100, 180))
    sig = p03.signal_days(p03._intensity_series(rows, "fq"))
    buys = [d for d, s in sig if s > 0]
    assert days[100] in buys or days[101] in buys
    assert len([d for d in buys if days[100] <= d <= days[106]]) == 1   # 이어진 날은 한 사건


def test_event_study_uses_only_finished_windows_and_holds_small_sample():
    rows, days = _long_flows(spikes=(100, 180, 250))
    px = [(d, 100.0 * (1 + 0.001 * i)) for i, d in enumerate(days)]
    ks = [(d, 100.0) for d in days]
    ev = p03.event_study(rows, px, ks, days[-1])
    buy20 = next(r for r in ev if r["who"] == "외국인" and r["signal"] == "집중 순매수" and r["h"] == 20)
    assert buy20["n"] == 2                     # 250번째 신호는 20일 결과 창이 아직 안 끝남
    assert buy20["status"] == "held"           # 20건 미만 → 보류
    buy5 = next(r for r in ev if r["who"] == "외국인" and r["signal"] == "집중 순매수" and r["h"] == 5)
    assert buy5["n"] == 3


def test_forward_excess_is_stock_minus_kospi():
    days = trading_days(30)
    px = [(d, 100.0 + i) for i, d in enumerate(days)]
    ks = [(d, 100.0) for d in days]
    x = p03.forward_excess(px, ks, days[0], 5, days[-1])
    assert abs(x - 5.0) < 1e-9
    assert p03.forward_excess(px, ks, days[-3], 5, days[-1]) is None   # 결과 창이 기준일 뒤


def test_panel_rows_attach_unconditional_baseline_and_flag():
    raw = [{"who": "외국인", "signal": "집중 순매수", "h": 20, "n": 846, "dates": 152, "median": -4.2, "p10": -26.6,
            "p90": 19.4, "positive_share": 40.5},
           {"who": "전체", "signal": "모든 거래일", "h": 20, "n": 30000, "dates": 180, "median": -3.0, "p10": -20,
            "p90": 15, "positive_share": 42.0}]
    rows = p03.panel_rows(raw)
    assert len(rows) == 1 and rows[0]["base_median"] == -3.0
    out = sentiment.compute(_sent_bundle(panel_events=raw), CO, AS_OF)
    f = out["facts"]
    k = f.key_of("KOSPI 200 합산 외국인 집중 순매수 뒤 20거래일 코스피 대비 초과수익률 중앙값 − 무조건부 기준선")
    assert k and abs(f.items[k]["value"] - (-1.2)) < 1e-9
    assert any(x.startswith("과거 관계:") and "투자 신호 아님" in x for x in f.flags)


def test_price_items_are_reference_tier():
    out = sentiment.compute(_sent_bundle(), CO, AS_OF)
    f = out["facts"]
    k = f.key_of("20일 주가 수익률")
    assert f.items[k]["tier"] == "reference"
    kv = f.key_of("VIX(미국 시장 변동성 지수)")
    assert f.items[kv]["tier"] == "core"
    assert f.items[f.key_of("외국인 20일 순매수 수량")]["tier"] == "core"


def test_etf_flows_enter_ledger_as_proxy():
    days = trading_days(30)
    etf = {"133690": [{"d": d, "c": 100.0, "n": 100.0, "a": 1e12 + i * 1e10, "nm": "TIGER 미국나스닥100"}
                      for i, d in enumerate(days)],
           "161510": [{"d": d, "c": 100.0, "n": 100.0, "a": 1e12 - i * 1e10, "nm": "PLUS 고배당주"}
                      for i, d in enumerate(days)]}
    out = sentiment.compute(_sent_bundle(etf=etf), CO, AS_OF)
    f = out["facts"]
    k = f.key_of("나스닥100 (TIGER 미국나스닥100) 최근 20거래일 추정 자금 유출입")
    assert abs(f.items[k]["value"] - 20e10) < 1 and f.items[k]["result_type"] == "대용치"
    assert any("위험 선호 쪽" in x for x in f.flags)


def test_contract_carries_p03_fields():
    from conftest import FakeLLM

    d = build_agent_data(3, CO, _sent_bundle(), AS_OF, {"question": "세력이 매집하나?"})
    k = d.facts.key_of("외국인 20일 순매수 수량")
    res = {"핵심진단": f"외국인 20일 {{{k}}}.", "자체점수": 5,
           "주장": [{"문장": f"외국인 20일 순매수 수량은 {{{k}}}이다.", "구분": "사실", "근거": [k]}]}
    c = run_agent(3, data=d, llm=FakeLLM(res))["contract"]
    assert c["p03"]["tasks"]["의도"]["state"] == "held"
    assert "INTENT_NOT_INFERABLE" in c["p03"]["statusCodes"]
    ev = next(e for e in c["evidence"] if e["ledgerKey"] == k)
    assert ev["tier"] == "core"
