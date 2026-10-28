"""기초기획서 R4 기준 테스트: 번호 체계, 데이터 계약(claimId·evidenceId), 에이전트 1 미확인 전제,
에이전트 3 기준선 비교·중복 신호·의도 추정 금지, Verifier 의 claimId/evidenceId 연결."""
import importlib

import pytest

from ch_agents import agents, contract, exposure, quality, rag
from ch_agents.agents import AGENTS, MY_AGENTS, build_agent_data
from ch_agents.facts import Facts
from ch_agents.llm import build_messages, run_agent, sentence_problems
from ch_agents.prompts import mode_guide
from ch_agents.review import style_checks
from conftest import AS_OF, CO, FakeLLM
from test_compute import _flow_rows, _macro_bundle, _sent_bundle
from test_plan_r2 import REPORT, _heavy_selling

# ---------------------------------------------------------------- 번호 체계 (교재 8~9장)


def test_numbering_and_module_names():
    assert MY_AGENTS == (1, 3)
    assert AGENTS[1].module.__name__.endswith("agent1_macro")
    assert AGENTS[3].module.__name__.endswith("agent3_sentiment_flow")
    assert 4 not in AGENTS and 2 not in AGENTS              # 이전 A2·A4 번호는 쓰지 않음
    assert set(rag.PRESETS) == {1, 2, 3, 4, 5, 7}
    assert rag.PRESETS[3].name == "투자심리·수급" and rag.PRESETS[2].name == "산업·경쟁강도"
    assert set(quality.SOURCES) == {1, 3}
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("ch_agents.macro")
    assert "수급" in mode_guide("expert", 3) and "노출" in mode_guide("expert", 1)


def test_prompt_uses_new_agent_names(rng):
    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    system, user = build_messages(d)
    assert "[에이전트 3 투자심리·수급 분석" in system and "[A4" not in system
    assert "반대근거" in system and "[기준선 비교]" in user


# ---------------------------------------------------------------- 데이터 계약


def _check_contract(c):
    assert contract.validate(c) == [], contract.validate(c)
    assert contract.link_errors(c) == []
    try:  # jsonschema 가 있으면 공식 검사기로도 확인
        import jsonschema
    except ImportError:
        return
    jsonschema.validate(c, contract.load_schema())


def test_contract_agent1_fallback_has_premises_and_ids(rng):
    b = _macro_bundle(rng)
    b["fund"] = {"fiscal_year": 2025, "liabilities": 50.0, "equity": 100.0, "operating_income": 20_000_000e6,
                 "net_income": 1.0}
    b["report"] = REPORT
    d = build_agent_data(1, CO, b, AS_OF)
    out = run_agent(1, data=d, llm=FakeLLM(TimeoutError()))
    c = out["contract"]
    _check_contract(c)
    assert c["reportId"].startswith(f"RPT-1-{CO['ticker']}-20261026-") and out["report_id"] == c["reportId"]
    assert c["agent"]["module"] == "agent1_macro"
    assert [x["claimId"] for x in c["claims"]] == [f"C{i + 1:02d}" for i in range(len(c["claims"]))]
    prem = {p["item"]: p for p in c["premises"]}
    assert prem["환헤지 여부·비율"]["status"] == "일부 확인"                      # 외환 파생상품 공시
    assert prem["수출 매출 비중"]["status"] == "확인" and prem["수출 매출 비중"]["evidenceIds"]
    assert prem["판가 전가력"]["status"] == "미확인" and prem["수출 대금 결제 통화·결제 시점"]["status"] == "미확인"
    cats = {u["category"] for u in c["unverified"]}
    assert "미확인 전제" in cats
    assert all(u["item"] != "수출 매출 비중" for u in c["unverified"])            # 확인된 전제는 미확인에 없음
    ev = {e["evidenceId"]: e for e in c["evidence"]}
    for x in c["claims"]:
        assert x["verification"]["status"] == "passed"
        for e in x["evidenceIds"]:
            assert ev[e]["cited"] and ev[e]["dataDate"]                          # 자료 기준일
    assert "**미확인 전제" in out["analysis"] and "reportId" in out["analysis"]
    assert c["exposure"][0]["evidenceIds"] is not None


def test_premises_without_report_are_unconfirmed():
    f = Facts("M")
    rows = exposure.assess(f, "반도체", None, AS_OF)
    prem = {p["item"]: p["status"] for p in exposure.premises(f, rows, "반도체")}
    assert set(prem.values()) == {"미확인"} and len(prem) == 6


TERMS = {"maturity": [{"kind": "bond", "fiscal_year": 2026, "reprt_code": "11012", "stlm_dt": "2026-06-30",
                       "total": 600.0, "within_1y": 150.0},
                      {"kind": "cp", "fiscal_year": 2026, "reprt_code": "11012", "stlm_dt": "2026-06-30",
                       "total": 400.0, "within_1y": 400.0}],
         "bond_rate": {"stlm_dt": "2026-06-30", "n": 3, "wavg": 3.25, "min": 2.9, "max": 3.8},
         "dso": {"period_end": "2026-06-30", "report_code": "11012", "dso_days": 71.4, "receivable_account": "매출채권"},
         "price_excerpts": 2}
REPORT_IR = REPORT + [{"fiscal_year": 2025, "metric": "ir_sens", "currency": "ALL", "value": -49_900e6,
                       "change_pct": 1, "basis": "세전이익"}]


def test_premises_with_debt_terms_dso_and_ir():
    f = Facts("M")
    fund = {"fiscal_year": 2025, "liabilities": 50.0, "equity": 100.0, "operating_income": 20_000_000e6}
    rows = exposure.assess(f, "반도체", fund, AS_OF, report=REPORT_IR, terms=TERMS)
    prem = {p["item"]: p for p in exposure.premises(f, rows, "반도체")}
    debt = prem["차입 조건(변동·고정금리 비중, 만기)"]
    assert debt["status"] == "일부 확인" and "만기 구조" in debt["detail"] and "변동·고정금리 비중" in debt["detail"]
    assert round(f.items[debt["keys"][0]]["value"], 6) == 55.0                   # (150 + 400) / (600 + 400)
    assert any(f.items[k]["value"] == 3.25 for k in debt["keys"])        # 가중평균 발행금리
    assert any(f.items[k]["value"] == -49_900e6 for k in debt["keys"])   # 이자율 1%p 민감도
    pay = prem["수출 대금 결제 통화·결제 시점"]
    assert pay["status"] == "일부 확인" and f.items[pay["keys"][0]]["value"] == 71.4
    price = prem["판가 전가력"]
    assert price["status"] == "미확인" and "발췌 2건" in price["detail"] and "판단 보류" in price["detail"]
    assert prem["달러 비용 비중(원재료·부품 수입 통화)"]["status"] == "일부 확인"
    rate_row = next(r for r in rows if r["var"] == "금리")
    assert rate_row["level"] == "낮음" and any("이자율 민감도" in x for x in rate_row["reasons"])  # 등급 규칙은 그대로


def test_premises_terms_without_report_still_flags_missing_disclosure():
    f = Facts("M")
    rows = exposure.assess(f, "반도체", None, AS_OF, terms={"maturity": [], "bond_rate": {"n": 0}, "dso": None,
                                                         "price_excerpts": 0})
    assert any(g["label"] == "기업 고유 노출" for g in f.gaps)
    prem = {p["item"]: p["status"] for p in exposure.premises(f, rows, "반도체")}
    assert set(prem.values()) == {"미확인"}


def test_contract_counter_claims_and_verifier_links():
    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    k = d.facts.key_of("외국인 20일 순매수 수량")
    r = d.facts.key_of("20일 주가 수익률")
    res = {"핵심진단": "외국인 순매도 우위.", "자체점수": 6,
           "주장": [{"문장": f"외국인은 20일간 {{{k}}} 순매도했다.", "구분": "사실", "근거": [k]},
                   {"문장": "외국인은 20일간 9,999주 순매수했다.", "구분": "사실", "근거": [k]}],
           "반대근거": [{"문장": f"주가는 20일 {{{r}}} 변해 수급과 같은 방향이다.", "구분": "사실", "근거": [r]}],
           "리스크요인": [f"순매도 지속 시 수급 부담 {{{k}}}"]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    c = out["contract"]
    _check_contract(c)
    roles = [(x["claimId"], x["role"]) for x in c["claims"]]
    assert ("C01", "main") in roles and any(r_ == "counter" for _, r_ in roles)
    assert c["downsideRisks"] and c["downsideRisks"][0]["riskId"] == "R01"
    em = contract.evidence_map(d)
    for v in out["verification"]:
        assert v["claimId"] and v["evidenceIds"]
    assert {x["claimId"]: x["evidenceIds"] for x in c["claims"]}["C01"] == [em[k]]
    assert "**반대 근거·하방 위험**" in out["analysis"] and "C01 [사실]" in out["analysis"]


def test_contract_documents_keep_published_time():
    from test_rag import _raw

    raw = _raw()
    b = _sent_bundle()
    b["rag"] = raw
    d = build_agent_data(3, CO, b, AS_OF)
    out = run_agent(3, data=d, llm=FakeLLM(TimeoutError()))
    docs = [e for e in out["contract"]["evidence"] if e["kind"] in ("document", "disclosure")]
    assert docs and all(e["publishedAt"] and e["sourceTag"].startswith("[출처: ") for e in docs)
    _check_contract(out["contract"])


def test_validator_catches_contract_breaks():
    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    c = run_agent(3, data=d, llm=FakeLLM(TimeoutError()))["contract"]
    broken = {**c, "claims": [{**c["claims"][0], "type": "의견", "evidenceIds": ["E999"]}]}
    assert any("허용 값 아님" in e for e in contract.validate(broken))
    assert any("없는 근거 ID" in e for e in contract.link_errors(broken))


# ---------------------------------------------------------------- 에이전트 3: 기준선 비교·중복 신호·의도 추정


def _news_and_volume_spike():
    rows = _flow_rows()
    for r in rows[:5]:
        r["tv"] = 3e12                      # 최근 5일 거래대금 3배
    return _sent_bundle(flows=rows)


def test_baseline_table_and_sentiment_model_status():
    d = build_agent_data(3, CO, _news_and_volume_spike(), AS_OF)
    base = {b["signal"]: b for b in d.extra["baseline"]}
    assert base["거래대금"]["status"] == "기준선 대비 이례적"
    assert base["뉴스 논조"]["method"].startswith("사전: 키워드 감성 사전") and "미검증" in base["뉴스 논조"]["method"]
    d2 = build_agent_data(3, CO, _sent_bundle(flows=_heavy_selling()), AS_OF)
    fx = {b["signal"]: b for b in d2.extra["baseline"]}["외국인 순매수 강도"]
    assert fx["base"] and fx["status"] == "기준선 대비 이례적"              # 기준선 값도 장부에 있음
    k = d.facts.key_of("거래대금 배율(최근 5일 ÷ 직전 60일)")
    assert round(d.facts.items[k]["value"], 2) == 3.0
    assert any(a.startswith("이상 징후: 거래대금 급증") for a in d.extra["anomalies"])


def test_news_and_volume_grouped_as_one_event():
    d = build_agent_data(3, CO, _news_and_volume_spike(), AS_OF)
    (cl,) = d.extra["dup_clusters"]
    assert {"뉴스 논조", "거래대금"} <= set(cl["signals"])
    assert any(fl.startswith("중복 신호 주의") and "X1" in fl for fl in d.facts.flags)
    kn = cl["members"]["뉴스 논조"][0]
    kt = cl["members"]["거래대금"][0]
    bad = {"문장": f"뉴스 논조 개선 {{{kn}}}과 거래대금 급증 {{{kt}}}, 두 신호가 함께 확인되어 근거가 더욱 강하다.",
           "구분": "해석", "근거": [kn, kt]}
    good = {"문장": f"뉴스 논조 개선 {{{kn}}}과 거래대금 급증 {{{kt}}}은 같은 사건을 반영할 수 있다.",
            "구분": "해석", "근거": [kn, kt]}
    res = {"핵심진단": "관심이 높아진 상태.", "자체점수": 5, "주장": [bad, good]}
    out = run_agent(3, data=d, llm=FakeLLM(res, res))
    assert out["checks"].get("중복 신호")
    assert bad["문장"] in out["removed"] and [c["문장"] for c in out["result"]["주장"]] == [good["문장"]]
    dup = out["contract"]["duplicateSignals"][0]
    assert dup["clusterId"] == "X1" and len(dup["evidenceIds"]) >= 2
    assert "**중복 신호 주의 (X1)**" in out["analysis"]


def test_single_signal_is_not_a_cluster():
    d = build_agent_data(3, CO, _sent_bundle(docs=[], search=None), AS_OF)
    assert d.extra["dup_clusters"] == []


def test_intent_inference_is_blocked_but_caveat_allowed():
    assert sentence_problems("외국인의 매수 의도가 보인다", set())
    assert sentence_problems("세력이 개입했다", set())
    assert not sentence_problems("순매수 기록만으로 매수 의도를 추정할 수 없다", set())


def test_review_style_rules_r4():
    rep = ("뉴스 호재와 거래량 급증이 동시에 나타나 상승 신호가 강하다. "
           "회사는 헤지를 하고 있어 환율 영향이 작다.")
    got = {(x["agent_id"], x["message"][:10]) for x in style_checks(rep)}
    assert any(a == 3 and m.startswith("뉴스와 거래량") for a, m in got)
    assert any(a == 1 and m.startswith("헤지·결제") for a, m in got)
    ok = "뉴스와 거래량 증가가 동시에 나타났지만 같은 사건을 반영할 수 있다. 헤지 여부는 미확인이다."
    assert not [x for x in style_checks(ok) if x["agent_id"] in (1, 3)]


def test_fetch_agent_data_routes_period_to_agent3(monkeypatch):
    seen = {}
    monkeypatch.setattr(agents, "fetch_bundle", lambda a, co, as_of: _sent_bundle())
    monkeypatch.setattr(agents, "build_agent_data",
                        lambda a, co, b, as_of, opts: seen.setdefault(a, opts))
    agents.fetch_agent_data(3, "005930", AS_OF, co=CO, period=10)
    agents.fetch_agent_data(1, "005930", AS_OF, co=CO, focus=["환율"])
    assert seen == {3: {"period": 10}, 1: {"focus": ["환율"]}}


def test_equity_basis_sensitivity_not_compared_with_operating_income():
    f = Facts("M")
    rep = [{"fiscal_year": 2025, "metric": "fx_sens", "currency": "ALL", "value": 154_400e6, "change_pct": 10,
            "basis": "자본"}]
    fund = {"fiscal_year": 2025, "liabilities": 50.0, "equity": 100.0, "operating_income": 1_000e6}
    rows = {r["var"]: r for r in exposure.assess(f, "건설", fund, AS_OF, report=rep)}
    assert not rows["환율"]["company"] and any("자본 기준" in x for x in rows["환율"]["reasons"])
    assert f.key_of("환율 10% 상승 시 손익 영향 ÷ 영업이익(FY2025)") is None


# ---------------------------------------------------------------- 회사채 발행사 이름 매칭


def test_issuer_names_normalize_and_aliases():
    assert exposure.norm_issuer("(주)씨제이 제일제당") == "씨제이제일제당"
    assert exposure.norm_issuer("네이버 주식회사") == "네이버" and exposure.norm_issuer("S-Oil") == "S-OIL"
    assert exposure.norm_issuer("우리금융지주") == "우리금융지주"              # '주'·'사' 글자를 따로 지우지 않음
    assert exposure.norm_issuer("한국가스공사") == "한국가스공사"
    assert exposure.issuer_names({"ticker": "000270", "name": "기아"}) == ["기아"]
    assert exposure.issuer_names({"ticker": "035420", "name": "NAVER"}) == ["NAVER", "네이버"]
    assert exposure.issuer_names({"ticker": "036570", "name": "NC"}) == ["NC", "엔씨", "엔씨소프트"]
    # 자회사 이름은 별칭에 넣지 않음 (모회사 금리에 섞이지 않도록)
    for subs in ("한화오션", "신세계디에프", "두산에너빌리티", "카카오페이증권", "현대카드", "삼성카드"):
        assert all(subs not in v for v in exposure.ISSUER_ALIASES.values())
    assert all(exposure.norm_issuer(a) == a for v in exposure.ISSUER_ALIASES.values() for a in v)


def test_terms_sql_matches_issuer_by_equality(monkeypatch):
    sql = exposure.TERMS_SQL
    assert "%(issuers)s" in sql and "[\\s()㈜주식회사]" not in sql      # 글자 단위 삭제 정규식 제거
    assert "~ regexp_replace((SELECT name" not in sql                    # '포함' 비교 대신 '같음' 비교
    p = exposure.terms_params({"company_id": 7, "ticker": "055550", "name": "신한지주"}, AS_OF)
    assert p == {"cid": 7, "as_of": AS_OF, "issuers": ["신한지주", "신한금융지주"]}
    seen = []
    monkeypatch.setattr(agents.db, "bundle", lambda q, params: seen.append(params) or {})
    monkeypatch.setattr(agents.db, "q", lambda *a, **k: [])
    monkeypatch.setattr(agents.rag, "fetch", lambda *a, **k: [])
    agents.fetch_bundle(1, {**CO, "company_id": 1}, AS_OF)
    assert any(isinstance(x, dict) and x.get("issuers") == ["삼성전자"] for x in seen)


def test_group_bond_rate_is_evidence_only():
    """자회사 포함(연결) 발행금리: 자회사 발행분이 있을 때만 별도 근거로 올리고 등급은 바꾸지 않습니다."""
    fund = {"fiscal_year": 2025, "liabilities": 50.0, "equity": 100.0, "operating_income": 20_000_000e6}
    grp = {"n": 9, "issuers": 3, "wavg": 3.9, "min": 3.1, "max": 4.6}
    f = Facts("M")
    rows = exposure.assess(f, "기타금융", fund, AS_OF, report=REPORT_IR, terms={**TERMS, "bond_rate_group": grp})
    k = rows[0]["basis"]["k_rate_grp"]
    assert f.items[k]["value"] == 3.9 and "발행사 3곳" in f.items[k]["label"] and "등급에는 쓰지 않음" in f.items[k]["note"]
    assert "외화채" in f.items[k]["note"]
    prem = {p["item"]: p for p in exposure.premises(f, rows, "기타금융")}
    debt = prem["차입 조건(변동·고정금리 비중, 만기)"]
    assert k in debt["keys"] and "자회사 포함 회사채 발행금리" in debt["detail"]
    base = exposure.assess(Facts("M"), "기타금융", fund, AS_OF, report=REPORT_IR, terms=TERMS)
    assert [r["level"] for r in rows] == [r["level"] for r in base]               # 등급 규칙은 그대로
    # 자회사 발행분이 없으면(그룹 건수 = 자체 건수) 따로 올리지 않음
    f2 = Facts("M")
    same = {**grp, "n": TERMS["bond_rate"]["n"]}
    rows2 = exposure.assess(f2, "기타금융", fund, AS_OF, report=REPORT_IR, terms={**TERMS, "bond_rate_group": same})
    assert "k_rate_grp" not in rows2[0]["basis"]


def test_terms_sql_uses_bonds_only_and_drops_spc():
    sql = exposure.TERMS_SQL
    assert "i.kind_nm ~ '회사채'" in sql and "'회사채|사채'" not in sql      # 전자단기사채는 금리에서 제외
    assert "'bond_rate_group'" in sql and "유동화" in sql


def test_terms_sql_reads_legal_name_without_requiring_column():
    """kic-agent-data 020 의 정식 회사명을 비교하되, 열이 아직 없는 DB 에서도 쿼리가 깨지지 않게 jsonb 로 읽습니다."""
    sql = exposure.TERMS_SQL
    assert "to_jsonb(c) ->> 'legal_name'" in sql and "c.legal_name" not in sql
    assert "x.issuer_norm = (SELECT legal FROM me)" in sql
