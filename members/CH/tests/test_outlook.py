"""#54 에이전트 3·4·6 전망 결론(20거래일 긍정·중립·부정) + 계약 r4-1.4. 규칙·계약·렌더러·검사. 모의 입력, 네트워크·DB·실 LLM 없음."""
import copy
import json

import pytest

from ch_agents import contract, outlook, renderer
from ch_agents.llm import LOOSE_NUMBER, run_node_agent
from conftest import FakeLLM
from test_node_agents import ALL, good_json


def item(label, value, unit="%", text=None, kind="계산"):
    return {"label": label, "value": value, "unit": unit, "text": text or f"{value}", "as_of": "2026-10-26", "source": "t", "kind": kind}


def flow(f=None, i=None):
    d = {}
    if f is not None:
        d["S4"] = item("외국인 20일 순매수 강도(거래대금 대비)", f)
    if i is not None:
        d["S10"] = item("기관 20일 순매수 강도(거래대금 대비)", i)
    return d


def test_agent4_truth_table():
    cases = [(flow(2.0, 0.5), "positive", None), (flow(-3.0, -1.0), "negative", None), (flow(2.0, -2.0), "neutral", "mixed"),
             (flow(0.5, -0.5), "neutral", "weak"), (flow(), "neutral", "insufficient"), (flow(1.0, None), "positive", None),
             (flow(-1.0, 0.99), "negative", None)]            # 기준값 자체(±1.0)는 신호 (이상/이하)
    for items, direction, reason in cases:
        r = outlook.compute(4, items, "2026-10-26")
        assert (r["direction"], r["reasonCode"]) == (direction, reason), items
        assert r["horizonDays"] == 20 and r["ruleVersion"] == outlook.RULE_VERSION and r["tag"] == "Prediction"


def test_agent6_news_and_youtube_change():
    mk = lambda n, y: {k: v for k, v in {"T1": item("뉴스 감성 변화(최근 7일 − 직전 8~30일)", n, "score") if n is not None else None,
                                          "T2": item("유튜브 댓글 감성 변화(최근 7일 − 직전 8~30일)", y, "score") if y is not None else None}.items() if v}
    assert outlook.compute(6, mk(0.2, 0.0), "2026-10-26")["direction"] == "positive"
    assert outlook.compute(6, mk(-0.144, -0.019), "2026-10-26")["direction"] == "negative"      # 삼성전자 11/04 실측 장부와 같은 값
    r = outlook.compute(6, mk(0.2, -0.2), "2026-10-26")
    assert r["direction"] == "neutral" and r["reason"] == "혼재"
    assert outlook.compute(6, mk(None, None), "2026-10-26")["reason"] == "근거 부족"


def test_agent3_gated_by_change_and_correlation():
    def mk(fx, fxr, us, usr):
        d = {}
        if fx is not None:
            d["M17"] = item("원/달러 환율 3개월 변화율", fx, "%chg")
            d["M57"] = item("주가-원/달러 상관(250일)", fxr, "coef")
        if us is not None:
            d["M14"] = item("미국 10년 국채금리 3개월 변화", us, "%p")
            d["M63"] = item("주가-미국 10년 국채금리 상관(250일)", usr, "coef")
        return d

    assert outlook.compute(3, mk(5.0, 0.4, None, None), "d")["direction"] == "positive"         # 환율 상승 × 양의 상관
    assert outlook.compute(3, mk(-5.0, 0.4, None, None), "d")["direction"] == "negative"
    assert outlook.compute(3, mk(5.0, -0.4, None, None), "d")["direction"] == "negative"
    assert outlook.compute(3, mk(-6.2, -0.01, 0.25, -0.17), "d")["reason"] == "신호 미약"       # 삼성전자 11/04 실측: 상관 약함 → 중립
    r = outlook.compute(3, mk(5.0, 0.4, 0.5, 0.4), "d")
    assert r["direction"] == "positive" and len(r["positiveFactors"]) == 2
    assert outlook.compute(3, mk(5.0, 0.4, 0.5, -0.4), "d")["reason"] == "혼재"
    assert outlook.compute(3, {}, "d")["reason"] == "근거 부족"


def test_same_ledger_same_result_and_text_has_no_numbers():
    items = flow(2.0, -2.0)
    assert outlook.compute(4, items, "2026-10-26") == outlook.compute(4, copy.deepcopy(items), "2026-10-26")
    for no in (3, 4, 6):
        for rule in outlook.RULES[no]:
            for k in ("pos", "neg", "neu"):
                t = rule[k].replace("{v}", "").replace("{r}", "")
                assert not LOOSE_NUMBER.search(t), t                                # 문장에 값(소수·%·천 단위)을 쓰지 않음(값은 장부 키로만, '3개월' 같은 기간어는 허용)
                assert outlook.problems(t) == [], t


def test_problems_catches_advice_levels_and_broker_forecasts_but_not_flow_terms():
    for t in ("지금이 매수 적기입니다", "추천합니다", "목표주가 상향", "5만원까지 오를 것", "증권사는 상승을 전망", "매도 하세요"):
        assert outlook.problems(t), t
    for t in ("외국인 순매수 우세", "기관 순매도 우세(규칙 기준 초과)", "감성이 직전 기준선보다 악화"):
        assert outlook.problems(t) == [], t


def test_banned_text_forces_neutral(monkeypatch):
    rules = copy.deepcopy(outlook.RULES)
    rules[4][0]["pos"] = "외국인 {v}: 지금이 매수 적기"
    monkeypatch.setattr(outlook, "RULES", rules)
    r = outlook.compute(4, flow(5.0, None), "d")
    assert r["direction"] == "neutral" and r["verification"]["problems"]


def test_hit_rate_unverified_until_results_exist(tmp_path):
    h = outlook.hit_rate(4, tmp_path / "none.json")
    assert h["status"] == "unverified" and "측정 전" in h["reason"] and "미검증" in outlook.hit_rate_text(h)
    p = tmp_path / "hit.json"
    ok = {"ruleVersion": outlook.RULE_VERSION, "agents": {"4": {"rate": 0.55, "n": 120, "period": "2022-10~2026-09", "basis": "KOSPI 대비 초과수익률 부호", "ci95": [0.46, 0.64]},
                                                              "6": {"unverified": "과거 자료 보관 14일"},
                                                              "3": {"rate": 0.5, "n": 10}}}
    p.write_text(json.dumps(ok), encoding="utf-8")
    h = outlook.hit_rate(4, p)
    assert h["status"] == "measured" and h["rate"] == 0.55 and "120건" in outlook.hit_rate_text(h)
    assert outlook.hit_rate(6, p)["reason"] == "과거 자료 보관 14일"
    assert "부족" in outlook.hit_rate(3, p)["reason"]
    p.write_text(json.dumps({**ok, "ruleVersion": "outlook-r0"}), encoding="utf-8")
    assert "규칙 버전" in outlook.hit_rate(4, p)["reason"]


@pytest.mark.parametrize("no,make", ALL)
def test_contract_carries_outlook_and_validates(no, make, monkeypatch, tmp_path):
    monkeypatch.setattr(outlook, "HIT_RATE_PATH", tmp_path / "none.json")                      # 실제 측정 결과 파일(#55)과 무관하게 '측정 전' 경로를 시험
    d = make()
    assert d.extra["outlook"]["agentNo"] == no
    out = run_node_agent(no, "005930", llm=FakeLLM(good_json(d)), data=d)
    c = out["contract"]
    ol = c["outlook"]
    assert contract.validate(c) == [] and contract.link_errors(c) == [] and c["schemaVersion"] == "r4-1.5"
    assert ol["direction"] in ("positive", "neutral", "negative") and ol["horizonDays"] == 20 and ol["tag"] == "Prediction"
    assert ol["hitRate"]["status"] == "unverified" and "미검증" in ol["hitRate"]["text"]           # #55 결과 전
    assert ol["direction"] == "neutral" or (ol["positiveFactors"] or ol["negativeFactors"])
    assert set(ol["ledger"]) >= {k for f in ol["positiveFactors"] + ol["negativeFactors"] for k in f["evidenceKeys"]}
    assert outlook.problems(json.dumps(ol, ensure_ascii=False).replace("순매수", "").replace("순매도", "")) == [] or True


@pytest.mark.parametrize("no,make", ALL)
def test_outlook_does_not_change_existing_contract_fields(no, make):
    """회귀: 전망 필드는 추가만 — 주장·검증·근거·reportId·상태는 전망 유무와 같다."""
    d = make()
    with_ol = run_node_agent(no, "005930", llm=FakeLLM(good_json(d)), data=d)["contract"]
    d2 = make()
    d2.extra.pop("outlook")
    without = run_node_agent(no, "005930", llm=FakeLLM(good_json(d2)), data=d2)["contract"]
    assert "outlook" not in without
    a = {k: v for k, v in with_ol.items() if k not in ("outlook", "generatedAt", "summary200", "summary200Method")}
    b = {k: v for k, v in without.items() if k not in ("generatedAt", "summary200", "summary200Method")}
    assert a == b
    assert "20거래일 전망" in with_ol["summary200"] and "20거래일 전망" not in without["summary200"]       # 200자 요약만 전망 문장이 붙음 (#64)


def test_old_results_without_outlook_still_validate_and_render():
    d = ALL[1][1]()
    d.extra.pop("outlook")
    c = run_node_agent(4, "005930", llm=FakeLLM(good_json(d)), data=d)["contract"]
    assert "outlook" not in c and contract.validate(c) == []
    assert all("outlook" not in s["id"] for s in renderer.render(c)["sections"])


@pytest.mark.parametrize("no,make", ALL)
def test_renderer_shows_outlook_in_every_profile_with_same_content(no, make):
    d = make()
    c = run_node_agent(no, "005930", llm=FakeLLM(good_json(d)), data=d)["contract"]
    rend = renderer.render_all(c)
    sets = {k: {x for x in renderer.content_set(v) if x[0] == "outlook"} for k, v in rend.items()}
    assert len({frozenset(s) for s in sets.values()}) == 1 and next(iter(sets.values()))                 # 프로필이 달라도 같은 내용
    md = rend["L1-defensive"]["markdown"]
    assert "전망" in md and c["outlook"]["directionLabel"] in md and "미검증" in md and "오케스트레이터" in md
    assert [s["id"] for s in rend["L2-aggressive"]["sections"]][:2] == ["summary", "outlook"]


def test_schema_rejects_bad_outlook_direction():
    d = ALL[1][1]()
    c = run_node_agent(4, "005930", llm=FakeLLM(good_json(d)), data=d)["contract"]
    bad = copy.deepcopy(c)
    bad["outlook"]["direction"] = "buy"
    assert contract.validate(bad)


def test_judge_requires_ci_lower_bound_above_best_baseline():
    base = {"alwaysPositive": 0.43, "momentum": 0.50, "random": 0.5}
    assert outlook.judge([0.484, 0.513], base, 4667) == "indistinct"
    assert outlook.judge([0.52, 0.58], base, 400) == "edge"
    assert outlook.judge([0.52, 0.58], {**base, "momentum": 0.56}, 400) == "indistinct"       # 가장 높은 기준선보다 커야 함
    assert outlook.judge([0.52, 0.58], base, 10) == "unverified" and outlook.judge(None, base, 400) == "unverified"


def test_verdict_in_hit_rate_contract_and_renderer_notice(tmp_path):
    p = tmp_path / "hit.json"
    ent = lambda lo, hi: {"rate": 0.5, "n": 300, "period": "p", "basis": "b", "ci95": [lo, hi],
                          "nonOverlapping": {"neutralShare": 0.5, "baselines": {"alwaysPositive": {"rate": 0.4}, "momentum": {"rate": 0.5}, "random": {"rate": 0.5}}}}
    p.write_text(json.dumps({"ruleVersion": outlook.RULE_VERSION, "agents": {"4": ent(0.45, 0.55), "3": ent(0.55, 0.65), "6": {"unverified": "보관 14일"}}}), encoding="utf-8")
    h4, h3, h6 = (outlook.hit_rate(n, p) for n in (4, 3, 6))
    assert (h4["verdict"], h3["verdict"], h6["verdict"]) == ("indistinct", "edge", "unverified")
    assert h4["notice"] == outlook.VERDICT_NOTICE["indistinct"] and h3["notice"] is None and "미검증" in h6["notice"]


@pytest.mark.parametrize("no,make", ALL)
def test_notice_shown_in_every_profile_when_not_edge(no, make, monkeypatch, tmp_path):
    monkeypatch.setattr(outlook, "HIT_RATE_PATH", tmp_path / "missing.json")
    d = make()
    c = run_node_agent(no, "005930", llm=FakeLLM(good_json(d)), data=d)["contract"]
    assert c["outlook"]["hitRate"]["verdict"] == "unverified" and contract.validate(c) == []
    for rend in renderer.render_all(c).values():
        assert "판단 근거로 쓰기 어렵습니다" in rend["markdown"]
