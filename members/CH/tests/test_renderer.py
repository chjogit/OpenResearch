"""페르소나 렌더러: 숙련도 3단계 × 성향 공격/방어 (팀 회의 2026-10-28).

같은 계약을 6개 프로필로 보여 줄 때 수치·근거·판정(공통 구역 내용)은 같고, 순서와 설명 깊이만 다른지 검사합니다."""
import pytest
from ch_agents.agents import build_agent_data
from ch_agents.llm import BANNED, run_agent
from ch_agents.profile import ALL_PROFILES, Level, Stance, UserProfile, parse_level, parse_stance
from ch_agents.renderer import COMMON, content_set, render, render_all
from conftest import AS_OF, CO, FakeLLM
from test_compute import _macro_bundle, _sent_bundle
from test_plan_r2 import REPORT


def _agent3_contract():
    d = build_agent_data(3, CO, _sent_bundle(), AS_OF)
    k = d.facts.key_of("외국인 20일 순매수 수량")
    r = d.facts.key_of("20일 주가 수익률")
    res = {"핵심진단": f"외국인 20일 순매수 수량은 {{{k}}}이다.", "자체점수": 6,
           "주장": [{"문장": f"외국인은 20일간 {{{k}}} 순매도했다.", "구분": "사실", "근거": [k]}],
           "반대근거": [{"문장": f"주가는 20일 {{{r}}} 변했다.", "구분": "사실", "근거": [r]}],
           "리스크요인": [f"순매도가 이어지면 수급 부담이 커질 수 있다 {{{k}}}"],
           "긍정요인": [], "미확인": [], "다음점검": ["외국인 5일 순매수 방향 전환 여부"]}
    return run_agent(3, data=d, llm=FakeLLM(res, res))["contract"]


def _agent1_contract(rng):
    b = _macro_bundle(rng)
    b["fund"] = {"fiscal_year": 2025, "liabilities": 50.0, "equity": 100.0, "operating_income": 20_000_000e6,
                 "net_income": 1.0}
    b["report"] = REPORT
    d = build_agent_data(1, CO, b, AS_OF)
    return run_agent(1, data=d, llm=FakeLLM(TimeoutError()))["contract"]


def _ids(r):
    return [s["id"] for s in r["sections"]]


@pytest.mark.parametrize("which", ["agent1", "agent3"])
def test_content_is_identical_across_six_profiles(rng, which):
    c = _agent1_contract(rng) if which == "agent1" else _agent3_contract()
    views = render_all(c)
    assert len(views) == 6
    sets = {k: content_set(v) for k, v in views.items()}
    first = next(iter(sets.values()))
    assert first and all(s == first for s in sets.values())
    claim_ids = {x["claimId"] for x in c["claims"]}
    assert claim_ids <= {ref for _, ref, _, _ in first}            # 모든 주장·반대 근거가 들어감
    for v in views.values():
        assert v["reportId"] == c["reportId"]
        assert v["markdown"].rstrip().endswith(f"_{c['disclaimer']}_")
        body = v["markdown"].replace(c["disclaimer"], "")                 # 면책 문구 자체에는 '목표주가'가 들어 있음
        assert not any(b in body for b in BANNED)


def test_stance_changes_order_only(rng):
    c = _agent3_contract()
    d = render(c, UserProfile(Level.L2, Stance.DEFENSIVE))
    a = render(c, UserProfile(Level.L2, Stance.AGGRESSIVE))
    di, ai = _ids(d), _ids(a)
    assert di.index("risks") < di.index("counter") < di.index("claims")    # 방어: 하방 위험부터
    assert ai.index("signals") < ai.index("claims") < ai.index("counter")  # 공격: 변화 신호부터
    for ids in (di, ai):                                                   # 어느 성향에서도 빠지지 않음
        assert {"summary", "counter", "risks", "unverified", "nextChecks"} <= set(ids)
    assert di[0] == ai[0] == "summary"
    assert set(di) == set(ai)


def test_level_changes_depth(rng):
    c = _agent1_contract(rng)
    l1 = render(c, {"level": "L1", "stance": "defensive"})
    l2 = render(c, {"level": "L2", "stance": "defensive"})
    l3 = render(c, {"level": "L3", "stance": "defensive"})
    assert "glossary" in _ids(l1) and "<details>" in l1["markdown"] and "`C01`" not in l1["markdown"]
    assert "보고서" in l2["markdown"] and ("[사실]" in l2["markdown"] or "[해석]" in l2["markdown"])
    assert "method" in _ids(l3) and "`C01`" in l3["markdown"] and "fact_source_verifier" in l3["markdown"]
    assert "glossary" not in _ids(l3) and "method" not in _ids(l1)
    n_ev = lambda r: len(next(s for s in r["sections"] if s["id"] == "evidence")["lines"])
    assert n_ev(l3) >= n_ev(l2)                                            # L3 은 인용 안 한 근거까지


def test_missing_counter_and_risk_are_shown_not_hidden():
    c = {"reportId": "RPT-x", "agent": {"name": "에이전트 3"}, "target": {}, "asOf": AS_OF, "status": "완료",
         "summary": {"text": "요약", "evidenceIds": []}, "claims": [], "downsideRisks": [], "unverified": [],
         "evidence": [], "disclaimer": "투자 권유 아님"}
    for p in ALL_PROFILES:
        r = render(c, p)
        assert "반대 근거를 확인하지 못함" in r["markdown"] and "하방 위험을 확인하지 못함" in r["markdown"]


def test_fallback_status_and_caveats_come_first(rng):
    c = _agent1_contract(rng)                                              # LLM 실패 → 규칙 기반 대체
    for p in ALL_PROFILES:
        ids = _ids(render(c, p))
        assert ids[:2] == ["summary", "caveats"]


def test_profile_parsing_and_sh_aliases():
    assert parse_stance("A") == Stance.AGGRESSIVE and parse_stance("신중형") == Stance.DEFENSIVE
    assert parse_level("L4") == Level.L3 and parse_level("입문자") == Level.L1
    assert UserProfile.from_dict({"level": "L3", "stance": "공격"}).to_dict()["stance"] == "aggressive"
    assert UserProfile.from_dict(None) == UserProfile(Level.L2, Stance.DEFENSIVE)
    with pytest.raises(ValueError):
        parse_level("L5")
    with pytest.raises(ValueError):
        parse_stance("U")                                                  # 미정은 받지 않음: 화면이 기본값을 정함
    assert len(ALL_PROFILES) == 6 and set(COMMON) >= {"counter", "risks", "unverified", "nextChecks"}


def test_renderer_fixed_text_adds_no_numbers_or_advice():
    from ch_agents.llm import BANNED_RE
    from ch_agents.renderer import HOW_TO, L1_HINT, TITLES, TYPE_L1
    fixed = [t for ts in TITLES.values() for t in ts] + list(HOW_TO.values()) + list(L1_HINT.values()) \
        + list(TYPE_L1.values())
    for t in fixed:
        assert not any(ch.isdigit() for ch in t), t                       # 렌더러가 새 숫자를 만들지 않음
        assert not any(b in t for b in BANNED) and not BANNED_RE.search(t), t


def test_signals_are_not_duplicated():
    c = _agent3_contract()
    r = render(c, UserProfile(Level.L1, Stance.AGGRESSIVE))
    texts = [it["text"] for s in r["sections"] if s["id"] == "signals" for it in s["items"]]
    assert texts and len(texts) == len(set(texts))
