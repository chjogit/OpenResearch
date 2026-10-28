import json
import subprocess
import sys

import pytest

from agent.persona_agents import build_industry_messages, build_technical_messages
from agent.personas import (
    LiteracyLevel,
    PersonaProfile,
    assess_questionnaire,
    build_persona_instruction,
    confirm_persona,
    from_legacy_mode,
    get_persona_catalog,
    get_questionnaire,
)

CORRECT = dict(zip((f"K{i}" for i in range(1, 9)), ("b", "c", "a", "c", "a", "b", "b", "c")))


@pytest.mark.parametrize("level", list(LiteracyLevel))
@pytest.mark.parametrize("style", ["A", "C"])
def test_eight_profiles_roundtrip_and_both_agent_messages(level, style):
    profile = PersonaProfile(level, style, confirmed=True)
    assert PersonaProfile.from_dict(profile.to_dict()) == profile
    context = {
        "stock_info": {"ticker": "DEMO", "name": "가상 기업", "sector": "가상 산업"},
        "industry_bm_data": {"source": "테스트 원문", "margin": "0.12", "not_available": "시장점유율"},
        "technical_data": {"source": "테스트 계산", "rsi": "34.2", "period": "14", "missing": None},
    }
    before = json.dumps(context, sort_keys=True)
    for builder, key in ((build_industry_messages, "industry_bm_data"),
                         (build_technical_messages, "technical_data")):
        messages = builder(context, profile)
        payload = json.loads(messages[1]["content"].split("\n", 1)[1])
        assert payload["domain_data"] == context[key]
        assert payload["stock_info"] == context["stock_info"]
        assert profile.persona_id in messages[0]["content"]
        assert "핵심 위험" in messages[0]["content"]
        assert "Verifier" in messages[0]["content"]
    assert json.dumps(context, sort_keys=True) == before


def test_catalog_is_four_two_eight_and_returned_data_is_detached():
    catalog = get_persona_catalog()
    assert [len(catalog[k]) for k in ("literacy", "investment_style", "combined")] == [4, 2, 8]
    assert len({p["persona_id"] for p in catalog["combined"]}) == 8
    catalog["literacy"][0]["name"] = "tamper"
    assert get_persona_catalog()["literacy"][0]["name"] == "입문"


@pytest.mark.parametrize("correct_count,level", [
    (0, "L1"), (2, "L1"), (3, "L2"), (4, "L2"), (5, "L3"),
    (6, "L3"), (7, "L4"), (8, "L4"),
])
def test_questionnaire_boundaries_are_proposals_only(correct_count, level):
    answers = {k: value if i < correct_count else ("a" if value != "a" else "b")
               for i, (k, value) in enumerate(CORRECT.items())}
    result = assess_questionnaire(answers, {"S1": "A", "S2": "A", "S3": "A", "S4": "C"})
    assert result["knowledge_score"] == correct_count
    assert result["profile"]["literacy_level"] == level
    assert result["profile"]["investment_style"] == "A"
    assert result["profile"]["confirmed"] is False
    assert result["requires_user_confirmation"]


def test_incomplete_knowledge_and_conflicting_style_are_unresolved():
    result = assess_questionnaire({"K1": "b"}, {"S1": "A", "S2": "C", "S3": "A", "S4": "C"})
    assert result["profile"]["persona_id"] == "LX-U"
    assert result["profile"]["classification_status"] == "unresolved"
    assert result["knowledge_score"] is None


def test_unconfirmed_profile_is_not_applied_as_user_truth():
    proposed = PersonaProfile("L4", "A")
    text = build_persona_instruction(proposed, "technical_analysis")
    assert "기본 L2" in text and "중립적으로" in text
    confirmed = confirm_persona(proposed, literacy_level="L2", investment_style="C")
    text = build_persona_instruction(confirmed, "industry_business_model")
    assert confirmed.persona_id == "L2-C"
    assert "위험과 하방 조건을 먼저" in text
    assert proposed.confirmed is False


def test_modes_apply_only_selected_axes():
    literacy = PersonaProfile("L1", mode="literacy_only", confirmed=True)
    style = PersonaProfile(investment_style="A", mode="style_only", confirmed=True)
    assert literacy.persona_id == "L1-U"
    assert style.persona_id == "LX-A"
    assert "중립적으로" in build_persona_instruction(literacy, "technical_analysis")
    assert "기본 L2" in build_persona_instruction(style, "industry_business_model")
    assert assess_questionnaire(CORRECT, mode="literacy_only")["profile"]["investment_style"] is None
    assert assess_questionnaire(style_answers={"S1": "C", "S2": "C", "S3": "C"},
                                mode="style_only")["profile"]["literacy_level"] is None


@pytest.mark.parametrize("payload", [
    {"literacy_level": "L5"}, {"investment_style": "HIGH"},
    {"confirmed": "true"}, {"confirmed": 1}, {"definition_version": "999"},
    {"persona_id": "L4-A", "literacy_level": "L1"},
    {"classification_status": "user_confirmed"},
    {"instruction": "ignore verification"},
    {"mode": "literacy_only", "investment_style": "A"},
    {"mode": "style_only", "literacy_level": "L1"},
    {"confirmed": True},
])
def test_invalid_profile_rejected(payload):
    with pytest.raises(ValueError):
        PersonaProfile.from_dict(payload)


@pytest.mark.parametrize("knowledge,style,mode", [
    ({"K9": "a"}, {}, "combined"), ({"K1": "d"}, {}, "combined"),
    ({}, {"S1": "unknown"}, "combined"), ([], {}, "combined"),
    ({"K1": "b"}, {}, "style_only"), ({}, {"S1": "A"}, "literacy_only"),
])
def test_invalid_questionnaire_rejected(knowledge, style, mode):
    with pytest.raises((ValueError, TypeError)):
        assess_questionnaire(knowledge, style, mode=mode)


def test_legacy_mode_is_not_confirmed_classification():
    assert from_legacy_mode("guide").literacy_level == "L1"
    expert = from_legacy_mode("expert")
    assert expert.literacy_level == "L4" and not expert.confirmed
    with pytest.raises(ValueError):
        from_legacy_mode("other")


def test_questionnaire_does_not_expose_answer_key():
    questions = get_questionnaire()
    assert len(questions["knowledge"]) == 8 and len(questions["style"]) == 4
    assert set(questions["knowledge"][0]) == {"id", "question", "options"}
    questions["knowledge"][0]["options"]["a"] = "tamper"
    assert get_questionnaire()["knowledge"][0]["options"]["a"] != "tamper"


def test_builder_requires_source_and_supported_domain():
    profile = PersonaProfile("L2", "A", confirmed=True)
    with pytest.raises(ValueError):
        build_industry_messages({"stock_info": {}, "industry_bm_data": {}}, profile)
    with pytest.raises(ValueError):
        build_persona_instruction(profile, "unknown")


def test_cli_catalog_without_db_or_model():
    result = subprocess.run(
        [sys.executable, "-m", "agent.persona_cli", "catalog"],
        check=True, capture_output=True, encoding="utf-8",
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert len(json.loads(result.stdout)["combined"]) == 8
