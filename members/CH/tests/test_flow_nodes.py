"""#22 수급 에이전트(4): N07 유동성·거래대금 / N08 수급 전환·가격 불일치. 모의 입력, 네트워크·DB·LLM 없음."""
import copy

import pytest

from ch_agents import flow_nodes, nodes
from ch_agents.agent3_sentiment_flow import compute as sentiment_compute
from conftest import AS_OF, CO, trading_days
from test_compute import _flow_rows, _sent_bundle

DAYS = trading_days(120)[::-1]          # 최신순, 10-23 까지


def prices(n=120, tv=1e12, vol=5_000_000, step=1000, last_tv=None):
    rows = []
    for i, d in enumerate(DAYS[:n]):
        rows.append({"d": d, "close": 200000 + i * step, "volume": vol,
                     "tv": last_tv if (last_tv and i < 5) else tv * (1 + (i % 7) * 0.02)})
    return rows


def inputs(**over):
    base = {"flows": _flow_rows(), "prices": prices(), "shares": 5_900_000_000}
    base.update(over)
    return base


def run(ext=False, **over):
    return flow_nodes.run_flow_agent("005930", AS_OF, extension=ext, inputs=inputs(**over))


# ---- N07

def test_n07_outputs_turnover_value_amihud_range_and_marks_order_book_unavailable():
    r = run()
    res = r["results"]["N07"]
    led = res.artifacts["ledger"]
    labels = {v["label"] for v in led.values()}
    assert {"거래대금 5일 평균", "거래대금 20일 평균", "거래대금 60일 평균", "회전율 20일 평균", "Amihud 비유동성 20일 평균(%/거래대금 조원)",
            "최근 60일 일 거래대금 하단(10백분위)", "최근 60일 일 거래대금 상단(90백분위)"} <= labels
    turn = next(v for v in led.values() if v["label"] == "회전율 1일 평균")
    assert turn["value"] == pytest.approx(5_000_000 / 5_900_000_000 * 100)          # 거래량 ÷ 상장주식수
    assert "호가 잔량" in res.missing_items and any("호가 잔량" in x and "미확보" in x for x in res.artifacts["data_limits"])
    assert res.artifacts["liquidity"]["short_term_range"]["low"] <= res.artifacts["liquidity"]["short_term_range"]["high"]


def test_n07_every_statement_links_to_ledger_keys():
    res = run()["results"]["N07"]
    led = res.artifacts["ledger"]
    assert res.findings and all(f.evidence_links for f in res.findings if f.kind in ("number", "conclusion"))
    assert all(k in led for f in res.findings for k in f.evidence_links)            # 숫자는 장부(DB 값) 키만 근거
    assert nodes.result_problems(res) == []


def test_n07_flags_surge_and_liquidity_shock():
    rows = prices()
    for r in rows[:5]:
        r["tv"] = 5e12                                                              # 최근 5일 거래대금 급증
    res = run(prices=rows)["results"]["N07"]
    txt = " ".join(f.text for f in res.findings)
    assert "거래대금 급증" in txt and res.artifacts["liquidity"]["anomaly_points"]
    assert all(p["type"] in ("급증", "급감") for p in res.artifacts["liquidity"]["anomaly_points"])


def test_n07_flags_drop():
    rows = prices()
    for r in rows[:5]:
        r["tv"] = 1e11
    assert "거래대금 급감" in " ".join(f.text for f in run(prices=rows)["results"]["N07"].findings)


def test_n07_without_shares_marks_turnover_gap_and_is_partial():
    res = run(shares=None)["results"]["N07"]
    assert res.status == "PARTIAL_SUCCESS" and "회전율" in res.missing_items
    assert not any("회전율" in f.text for f in res.findings)


def test_n07_required_data_missing_is_data_insufficient_without_running():
    r = flow_nodes.run_flow_agent("005930", AS_OF, extension=True, inputs=inputs(prices=[]))
    assert r["results"]["N07"].status == "DATA_INSUFFICIENT" and "price" in r["results"]["N07"].missing_items
    assert r["status"] == "DATA_INSUFFICIENT" and r["nodes"][1]["state"] == "skipped"


def test_n07_not_chart_or_pure_volume_analysis():
    res = run()["results"]["N07"]
    text = " ".join(f.text for f in res.findings)
    assert not any(w in text for w in ("이동평균선", "지지선", "저항선", "골든크로스", "거래량 증가"))


# ---- N08

AGENT3_LABELS = [f"{w} {n}일 순매수 수량" for w in ("외국인", "기관", "개인") for n in (5, 20, 60)] + \
                [f"{w} 20일 순매수 금액(근사)" for w in ("외국인", "기관", "개인")] + \
                [f"{w} 20일 순매수 강도(거래대금 대비)" for w in ("외국인", "기관", "개인")] + ["20일 주가 수익률"]


def test_n08_values_equal_agent3_flow_facts_for_same_input():
    b = _sent_bundle()
    f3 = sentiment_compute(copy.deepcopy(b), CO, AS_OF)["facts"]
    inp = {"flows": copy.deepcopy(b["flows"]),
           "prices": [{"d": p["d"], "close": p["v"], "volume": 1, "tv": 1e12} for p in reversed(b["price"])],
           "shares": 1e9}
    led = flow_nodes.n08(flow_nodes.clean_inputs(inp, AS_OF), AS_OF).artifacts["ledger"]
    new = {v["label"]: v["value"] for v in led.values()}
    old = {v["label"]: v["value"] for v in f3.items.values()}
    shared = [l for l in AGENT3_LABELS if l in new]
    assert len(shared) >= 12 and all(new[l] == pytest.approx(old[l]) for l in shared)
    for who in ("외국인", "기관", "개인"):                                           # 연속 일수도 같은 값
        for s in ("매수", "매도"):
            lab = f"{who} 연속 순{s} 일수"
            if lab in new:
                assert new[lab] == old[lab]


def test_n08_cumulative_table_streak_handover_and_divergence():
    flows = _flow_rows(fq=1000)                                                      # 외국인 순매수, 가격은 하락 중
    flows[0:5] = [dict(r, fq=-4000) for r in flows[0:5]]                             # 최근 5일만 외국인 순매도 → 손바꿈
    res = run(ext=True, flows=flows)["results"]["N08"]
    assert set(res.artifacts["cumulative_table"]) == {"외국인", "기관", "개인"}
    assert any(h["who"] == "외국인" and h["from"] == "순매수" and h["to"] == "순매도" for h in res.artifacts["handovers"])
    assert res.artifacts["definitions"]["손바꿈"] and res.artifacts["definitions"]["불일치"]
    f = [x for x in res.findings if "순매매 방향 전환" in x.text]
    assert f and "의도를 뜻하지 않음" in f[0].text


def test_n08_divergence_when_price_falls_while_foreigner_buys():
    res = run(ext=True, flows=_flow_rows(fq=1000))["results"]["N08"]                # 가격 하락(step>0), 외국인 순매수
    d = res.artifacts["divergences"]
    assert any(x["who"] == "외국인" and x["type"] == "하락 중 순매수" for x in d)
    c = [c for c in res.conflicts if "외국인" in c.topic]
    assert c and len(c[0].views) == 2 and all(v.evidence_links for v in c[0].views)  # 관점별 충돌에 나란히, 평균 아님


def test_n08_detailed_subjects_are_unavailable_not_replaced_by_institution_total():
    res = run(ext=True)["results"]["N08"]
    assert res.artifacts["unavailable_subjects"] == ["금융투자", "투신", "연기금"]
    assert any("세부 주체" in m for m in res.missing_items)
    labels = {v["label"] for v in res.artifacts["ledger"].values()}
    assert not any(w in l for l in labels for w in ("금융투자", "투신", "연기금"))      # 기관 합계를 세부 주체로 쓰지 않음


def test_no_investor_flow_is_not_replaced_by_volume():
    r = run(ext=True, flows=[])
    assert r["nodes"][0]["state"] == "executed" and r["nodes"][1]["state"] == "skipped"
    assert r["nodes"][1]["missingInputs"] == ["investor_flow"] and "N08" not in r["results"]
    direct = flow_nodes.n08(flow_nodes.clean_inputs(inputs(flows=[]), AS_OF), AS_OF)
    assert direct.status == "DATA_INSUFFICIENT" and "거래량으로 대체 해석하지 않음" in direct.reason and direct.findings == []


def test_flow_later_than_price_is_shown_as_lag_not_filled():
    flows = _flow_rows()[3:]                                                         # 수급이 3거래일 늦게 끝남
    res = run(ext=True, flows=flows)["results"]["N08"]
    lag = res.artifacts["flow_lag"]
    assert lag["flow_last"] < lag["price_last"] and res.status == "PARTIAL_SUCCESS"
    assert any("자료 시차" in f.text and "거래량으로 대신 해석하지 않음" in f.text for f in res.findings)
    assert any("수집이 시세보다 늦음" in m for m in res.missing_items)


def test_flow_rows_after_as_of_are_removed():
    fut = [{"d": "2026-10-27", "fq": 9, "iq": 9, "pq": 9, "hold": 1, "close": 1, "tv": 1}]
    cleaned = flow_nodes.clean_inputs({"flows": fut + _flow_rows(), "prices": [dict(prices()[0], d="2026-11-02")] + prices(), "shares": 1}, AS_OF)
    assert all(r["d"] <= AS_OF for r in cleaned["flows"] + cleaned["prices"])
    with pytest.raises(ValueError):
        flow_nodes.clean_inputs({}, "")


# ---- 전환 확률 (E2: 검증 미통과 → 건너뜀 + 이유)

def test_switch_probability_skipped_with_reason_when_sample_is_small():
    r = run(ext=True)
    res = r["results"]["N08"]
    assert not any(f.tag == "Prediction" for f in res.findings)                      # 매일 같은 방향인 합성 자료: 추가 설명력 없음
    assert res.prediction_skipped_reason.startswith("SWITCH_PROB_UNVALIDATED") and "검증 미통과" in res.prediction_skipped_reason
    assert r["prediction_skipped_reason"] == res.prediction_skipped_reason           # 에이전트 출력에도 이유가 남음
    assert r["counts"]["executed"] == 2 and r["status"] == "PARTIAL_SUCCESS"         # 기술 분석 표는 그대로 나옴
    assert res.artifacts["cumulative_table"]


def test_switch_probability_skipped_when_history_is_short():
    r = run(ext=True, flows=_flow_rows(n=40))
    res = r["results"]["N08"]
    assert "표본 부족" in res.prediction_skipped_reason and not any(f.tag == "Prediction" for f in res.findings)


def _stats(**kw):
    base = {"n_events": 40, "n_base": 200, "oos": 25, "brier_cond": 0.20, "brier_base": 0.25, "p_cond": 0.6, "p_base": 0.4}
    return {**base, **kw}


def _seq(streak_len=4):
    return [-1.0] * 30 + [1.0] * streak_len        # 오래된 순, 끝이 연속 순매수


def test_switch_probability_gating(monkeypatch):
    f = flow_nodes.Facts("S")
    monkeypatch.setattr(flow_nodes, "switch_stats", lambda q: _stats())
    ok, why = flow_nodes._prediction("외국인", _seq(4), f, "2026-10-23")
    assert why is None and ok.tag == "Prediction" and "의도·정보 보유를 뜻하지 않음" in ok.text and len(ok.evidence_links) == 3
    for override, expect in (({"n_events": 29}, "표본 부족"), ({"oos": 14}, "걷기 검증 표본 부족"),
                             ({"brier_cond": 0.30}, "검증 미통과")):
        monkeypatch.setattr(flow_nodes, "switch_stats", lambda q, o=override: _stats(**o))
        none, why = flow_nodes._prediction("외국인", _seq(4), flow_nodes.Facts("S"), "d")
        assert none is None and expect in why
    monkeypatch.setattr(flow_nodes, "switch_stats", lambda q: _stats())
    none, why = flow_nodes._prediction("외국인", _seq(2), flow_nodes.Facts("S"), "d")   # 현재 연속 3일 미만
    assert none is None and "적용 대상 아님" in why


def test_switch_stats_counts_events_and_uses_only_known_outcomes():
    q = ([1.0] * 4 + [-1.0] * 6) * 12                      # 4일 순매수 → 6일 순매도 반복
    st = flow_nodes.switch_stats(q)
    assert st["n_events"] > 0 and 0 <= st["p_cond"] <= 1 and st["n_base"] >= st["n_events"]
    assert flow_nodes.switch_stats([0.0] * 50)["n_events"] == 0
    short = flow_nodes.switch_stats([1.0] * 5)
    assert short["n_events"] == 0 and short["oos"] == 0 and short["brier_cond"] is None   # 결과가 확정된 표본이 없으면 검증 불가


def test_prediction_is_never_produced_without_validation_in_a_full_run(monkeypatch):
    monkeypatch.setattr(flow_nodes, "switch_stats", lambda q: _stats(brier_cond=0.4))
    res = run(ext=True, flows=_flow_rows(fq=1000))["results"]["N08"]
    assert not any(f.tag == "Prediction" for f in res.findings) and "검증 미통과" in res.prediction_skipped_reason


# ---- 노드 틀 연결

def test_runners_registered_and_frame_counts_nodes():
    assert {"N07", "N08"} <= set(nodes.RUNNERS)
    base_only = run(ext=False)
    assert [n["state"] for n in base_only["nodes"]] == ["executed", "skipped"] and base_only["counts"]["executed"] == 1
    both = run(ext=True)
    assert both["counts"] == {"base": 1, "extSelected": 1, "extExecuted": 1, "executed": 2}


def test_all_findings_pass_evidence_and_tag_validation():
    for nid, res in run(ext=True, flows=_flow_rows(fq=1000))["results"].items():
        assert nodes.result_problems(res) == [], nid
        assert all(f.tag in nodes.TAGS for f in res.findings)
        led = res.artifacts["ledger"]
        assert all(k in led for f in res.findings for k in f.evidence_links)
