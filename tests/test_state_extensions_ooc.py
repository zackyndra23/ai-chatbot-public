import pytest
import pydantic
from modules.service_agent.sa_types import AgentSessionState

_BASE = {"session_id": "test", "service_code": "test", "question_id": "test"}


def test_default_ooc_excursion_count_is_zero():
    state = AgentSessionState(**_BASE)
    assert state.ooc_excursion_count == 0


def test_default_previous_user_ooc_categories_is_empty_list():
    state = AgentSessionState(**_BASE)
    assert state.previous_user_ooc_categories == []
    state.previous_user_ooc_categories.append("OOC-CAREERS")
    new_state = AgentSessionState(**_BASE)
    assert new_state.previous_user_ooc_categories == []  # no shared default mutation


def test_default_previous_system_meta_actions_is_empty_list():
    state = AgentSessionState(**_BASE)
    assert state.previous_system_meta_actions == []
    state.previous_system_meta_actions.append("ESCALATION-CONSECUTIVE-OOC")
    new_state = AgentSessionState(**_BASE)
    assert new_state.previous_system_meta_actions == []  # no shared default mutation


def test_default_session_fallback_language_is_en():
    state = AgentSessionState(**_BASE)
    assert state.session_fallback_language == "en"


def test_default_ooc_escalation_suppression_remaining_is_zero():
    state = AgentSessionState(**_BASE)
    assert state.ooc_escalation_suppression_remaining == 0


def test_ooc_excursion_count_rejects_negative():
    with pytest.raises(pydantic.ValidationError):
        AgentSessionState(**_BASE, ooc_excursion_count=-1)


def test_ooc_escalation_suppression_remaining_rejects_negative():
    with pytest.raises(pydantic.ValidationError):
        AgentSessionState(**_BASE, ooc_escalation_suppression_remaining=-1)


def test_round_trip_existing_state_preserves_ooc_defaults():
    # SA-1: strict-additive — old state dicts (pre-Stage 0) deserialize cleanly
    # All required fields included; OOC fields use defaults
    legacy = {
        "session_id": "legacy-001",
        "service_code": "wbs",
        "question_id": "case_handler_quantity",
        "answers": {},
    }
    state = AgentSessionState(**legacy)
    assert state.ooc_excursion_count == 0
    assert state.previous_user_ooc_categories == []
    assert state.previous_system_meta_actions == []
    assert state.session_fallback_language == "en"
    assert state.ooc_escalation_suppression_remaining == 0
