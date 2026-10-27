"""기초기획서 R2 기준 기능 테스트: 사용자 입력, A1 노출도, A4 이상 징후·요약표, Verifier 연동, 프롬프트 파일, 품질 플래그."""
from datetime import datetime, timedelta, timezone

from ch_agents import exposure, macro, quality, sentiment
from ch_agents import verify as verifier
from ch_agents.agents import build_agent_data
from ch_agents.facts import Facts
from ch_agents.llm import build_messages, run_agent
from ch_agents.prompts import mode_guide
from conftest import AS_OF, CO, FakeLLM
from test_compute import _flow_rows, _macro_bundle, _sent_bundle

# ---------------------------------------------------------------- A1 노출도


def _corr_facts(r=0.5, n=250):
    f = Facts("M")
    f.add("주가-원/달러 상관(250일)", r, "coef", "-", "t", kind="calc", note=f"{n}거래일, 통계적 동조성")
    f.add("주가-미국 10년 국채금리 상관(250일)", 0.05, "coef", "-", "t", kind="calc", note=f"{n}거래일")
    return f


def test_exposure_rules_prior_stat_and_debt():
    f = _corr_facts(r=0.5)
    rows = {r["var"]: r for r in exposure.assess(f, "화학", {"fiscal_year": 2025, "liabilities": 300, "equity": 100},
                                                 AS_OF)}
    assert rows["환율"]["level"] == "높음"          # 화학 기본 중간 + 뚜렷한 동조 → 한 단계 올림
    assert rows["금리"]["level"] == "높음"          # 기본 중간 + 부채비율 300% → 한 단계 올림
    assert rows["원자재·물가"]["level"] == "높음"    # 기본값 그대로
    assert any(fl.startswith("노출 점검 · 환율: 높음") and "{M1}" in fl for fl in f.flags)
    assert any(g["label"] == "기업 고유 노출" for g in f.gaps)


def test_exposure_weak_corr_and_low_debt_and_financials():
    f = _corr_facts(r=0.05)
    rows = {r["var"]: r for r in exposure.assess(f, "반도체", {"fiscal_year": 2025, "liabilities": 30, "equity": 100},
                                                 AS_OF)}
    assert rows["환율"]["level"] == "높음" and rows["환율"]["keys"] == []   # 약한 상관은 근거로 안 씀
    assert rows["금리"]["level"] == "낮음"                                  # 기본 중간 − 부채비율 30%
    f2 = _corr_facts()
    rows2 = {r["var"]: r for r in exposure.assess(f2, "은행", {"fiscal_year": 2025, "liabilities": 1500, "equity": 100},
                                                  AS_OF)}
    assert rows2["금리"]["level"] == "높음" and f2.key_of("부채비율(FY2025)") is None   # 금융업은 부채비율 미사용


def test_exposure_focus_order_and_macro_integration(rng):
    b = _macro_bundle(rng)
    b["fund"] = {"fiscal_year": 2025, "liabilities": 100.0, "equity": 200.0}
    out = macro.compute(b, CO, AS_OF, focus=["금리"])
    assert out["exposure"][0]["var"] == "금리" and out["exposure"][0]["focus"]
    d = build_agent_data(1, CO, b, AS_OF, {"focus": ["금리"]})
    system, user = build_messages(d, "expert")
    assert "[사용자 입력] 관심 거시 변수: 금리" in user and "노출 점검 · 금리" in user
    assert "거시 노출 참고치" in system                 # prompts/expert.md 의 A1 절


# ---------------------------------------------------------------- A4 이상 징후·요약표


def _heavy_selling():
    rows = _flow_rows(n=120, fq=-1000)
    for i, r in enumerate(rows):
        r["fq"] = -1000 + (i % 7) * 300 - 900   # 평소: 작은 변동
        r["iq"] = 500 + (i % 5) * 100
    for r in rows[:5]:
        r["fq"] = -400000                       # 최근 5일: 평소의 수백 배 순매도
    return rows


def test_a4_concentrated_selling_anomaly_and_summary_period():
    out = sentiment.compute(_sent_bundle(flows=_heavy_selling()), CO, AS_OF, period=10)
    f = out["facts"]
    assert any(a.startswith("이상 징후: 외국인 집중 순매도") for a in out["anomalies"])
    kz = f.key_of("외국인 최근 5일 강도의 직전 60일 대비 표준점수")
    assert f.items[kz]["value"] < -2
    assert f.key_of("외국인 10일 순매수 수량") and out["obs_period"] == 10
    labels = [s["label"] for s in out["summary"]]
    assert "외국인 10일 순매수 수량" in labels and "10일 주가 수익률" in labels
    assert any(x.startswith("이상 징후: 뉴스 논조 급격한") for x in out["anomalies"])


def test_a4_prompt_and_markdown_tables():
    d = build_agent_data(4, CO, _sent_bundle(flows=_heavy_selling()), AS_OF, {"period": 10})
    _, user = build_messages(d, "guide")
    assert "관찰 기간: 10거래일" in user
    res = run_agent(4, data=d, llm=FakeLLM(TimeoutError()))
    md = res["analysis"]
    assert "**이상 징후**" in md and "**심리·수급 요약표 (관찰 기간 10거래일)**" in md
    assert res["anomalies"] and res["status"].startswith("규칙 기반 대체")


# ---------------------------------------------------------------- Verifier


def test_every_ledger_value_survives_shared_verifier(rng):
    """표시 형식(fmt)으로 쓴 모든 장부 값이 팀 공용 fact_source_verifier 대조를 통과해야 함."""
    datas = [build_agent_data(1, CO, _macro_bundle(rng), AS_OF),
             build_agent_data(4, CO, _sent_bundle(flows=_heavy_selling()), AS_OF, {"period": 10})]
    for d in datas:
        terms = verifier._term_values(d)
        for k, it in d.facts.items.items():
            if it["value"] is None:
                continue
            v = verifier.check_text(f"{it['label']}은 {{{k}}}이다.", [k], d, terms)
            assert v["ok"], (k, it["label"], it["text"], v["unmatched"])
            assert v["sources"] and v["sources"][0].startswith("Neon ")


def test_verifier_flags_number_not_in_ledger_and_tags_sources():
    d = build_agent_data(4, CO, _sent_bundle(), AS_OF)
    k = d.facts.key_of("외국인 20일 순매수 수량")
    ok = verifier.check_text(f"외국인은 {{{k}}} 순매도했다.", [k], d)
    assert ok["ok"] and ok["sources"] == ["Neon core.investor_flow_daily, " + d.facts.items[k]["as_of"]]
    bad = verifier.check_text(f"외국인은 {{{k}}} 순매도했고 강도는 7.77%였다.", [k], d)
    assert not bad["ok"] and bad["unmatched"] == ["7.77%"]


def test_run_agent_adds_source_tags_and_verification_log():
    d = build_agent_data(4, CO, _sent_bundle(), AS_OF)
    k = d.facts.key_of("외국인 20일 순매수 수량")
    res = {"핵심진단": "외국인은 순매도 우위.", "자체점수": 6,
           "주장": [{"문장": f"외국인은 20일간 {{{k}}}로 순매도했다.", "구분": "사실", "근거": [k]}]}
    out = run_agent(4, data=d, llm=FakeLLM(res))
    assert out["status"] == "완료"
    assert out["result"]["주장"][0]["출처"][0].startswith("Neon core.investor_flow_daily")
    assert "[출처: Neon core.investor_flow_daily" in out["analysis"]
    assert out["verification"] and all(v["ok"] for v in out["verification"])
    assert "Verifier (fact_source_verifier)" in out["analysis"]


# ---------------------------------------------------------------- 프롬프트 파일


def test_prompt_files_split_by_mode_and_agent():
    e1, e4, g1 = mode_guide("expert", 1), mode_guide("expert", 4), mode_guide("guide", 1)
    assert "거시 노출 참고치" in e1 and "거시 노출 참고치" not in e4
    assert "수급·심리 요약" in e4
    assert "스스로질문" in g1 and "지표 정의" in g1
    assert "스스로질문" not in e1


# ---------------------------------------------------------------- 품질 플래그


def test_quality_flags():
    now = datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc)
    rows = [{"api_name": "ecos·fred", "last_success": now - timedelta(hours=1), "consecutive_failures": 0},
            {"api_name": "yfinance", "last_success": now - timedelta(hours=60), "consecutive_failures": 0},
            {"api_name": "fsc", "last_success": now, "consecutive_failures": 4}]
    out = {w["api"]: w["reason"] for w in quality.check(1, rows, now)}
    assert "ecos·fred" not in out and "48시간" in out["yfinance"] and "연속 실패 4회" in out["fsc"]
    assert "기록 없음" in out["data.go.kr"]
    assert quality.check(1, None, now) == []          # 품질 표를 못 읽으면 점검하지 않음


def test_quality_notes_reach_markdown(rng):
    b = _macro_bundle(rng)
    b["quality"] = [{"api_name": "ecos·fred", "last_success": None, "consecutive_failures": 0}]
    d = build_agent_data(1, CO, b, AS_OF)
    res = run_agent(1, data=d, llm=FakeLLM(TimeoutError()))
    assert "**데이터 품질 주의**" in res["analysis"] and res["quality"]
