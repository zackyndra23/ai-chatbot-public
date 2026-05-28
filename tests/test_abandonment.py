"""Tests for AbandonmentHandler.

Per spec §7.6. Validates DT-8 state-clear semantics + 3-clause lang_hint logic.
"""
import pytest

from modules.abandonment import AbandonmentHandler, AbandonmentResult
from modules.i18n import _reset_registry_for_tests
from modules.service_agent.sa_types import AgentSessionState


@pytest.fixture(autouse=True)
def _reset():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def _base_state(**overrides) -> AgentSessionState:
    defaults = {
        "session_id": "test-001",
        "service_code": "wbs",
        "question_id": "case_handler_quantity",
    }
    defaults.update(overrides)
    return AgentSessionState(**defaults)


# ============================================================================
# Clause 1: lang_hint match (3-clause semantics per spec §7.6)
# ============================================================================


def test_matches_en_via_lang_hint():
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="never mind", state=state, lang_hint="en")
    assert result.matched is True
    assert result.matched_phrase == "never mind"
    assert result.detected_language == "en"
    assert result.matched_via == "lang_hint_match"


def test_matches_id_via_lang_hint():
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="udahan saja", state=state, lang_hint="id")
    assert result.matched is True
    assert result.detected_language == "id"
    assert result.matched_via == "lang_hint_match"


def test_matches_case_insensitive():
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="NEVER MIND", state=state, lang_hint="en")
    assert result.matched is True


# ============================================================================
# Clause 2: cross-lang fallback when hint misses
# ============================================================================


def test_cross_lang_fallback_when_hint_misses():
    """English trigger but lang_hint is 'id' — cross-lang scan should find it."""
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="never mind", state=state, lang_hint="id")
    assert result.matched is True
    assert result.detected_language == "en"  # the bank that hit
    assert result.matched_via == "cross_lang_fallback"


def test_cross_lang_fallback_when_no_hint():
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="udahan saja", state=state, lang_hint=None)
    assert result.matched is True
    assert result.detected_language == "id"
    assert result.matched_via == "cross_lang_fallback"


# ============================================================================
# No match cases
# ============================================================================


def test_no_match_returns_unmatched():
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="what is a case handler?", state=state, lang_hint="en")
    assert result.matched is False
    assert result.matched_phrase is None


def test_empty_text_returns_unmatched():
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="", state=state, lang_hint="en")
    assert result.matched is False


def test_whitespace_only_text_returns_unmatched():
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(text="   ", state=state, lang_hint="en")
    assert result.matched is False


# ============================================================================
# DT-8: state clear semantics
# ============================================================================


def test_handle_clears_sa_state():
    h = AbandonmentHandler()
    state = _base_state(
        answers={"prior_field": "value"},
        ooc_excursion_count=2,
        previous_user_ooc_categories=["OOC-CAREERS"],
        previous_system_meta_actions=["ESCALATION-CONSECUTIVE-OOC"],
        ooc_escalation_suppression_remaining=2,
    )
    h.handle(text="never mind", state=state)
    # SA state cleared
    assert state.service_code == ""
    assert state.question_id == ""
    assert state.answers == {}
    # OOC streak state cleared
    assert state.ooc_excursion_count == 0
    assert state.previous_user_ooc_categories == []
    assert state.previous_system_meta_actions == []
    # Suppression cleared
    assert state.ooc_escalation_suppression_remaining == 0


def test_handle_preserves_session_fallback_language():
    """Per spec §7.6 — session_fallback_language MUST be preserved."""
    h = AbandonmentHandler()
    state = _base_state(session_fallback_language="id")
    h.handle(text="udahan saja", state=state)
    assert state.session_fallback_language == "id"


def test_handle_returns_ack_in_session_fallback_language_id():
    h = AbandonmentHandler()
    state = _base_state(session_fallback_language="id")
    ack = h.handle(text="udahan saja", state=state)
    assert isinstance(ack, str)
    assert "Anda" in ack  # Indonesian uses "Anda" formal


def test_handle_returns_ack_in_session_fallback_language_en():
    h = AbandonmentHandler()
    state = _base_state(session_fallback_language="en")
    ack = h.handle(text="never mind", state=state)
    assert isinstance(ack, str)
    assert len(ack) > 10


def test_handle_returns_ack_falls_back_to_en_for_unknown_lang():
    h = AbandonmentHandler()
    state = _base_state(session_fallback_language="xx_unknown")
    ack = h.handle(text="never mind", state=state)
    # Falls back to English baseline (i18n loader runtime fallback)
    assert "stop here" in ack or "ready to start" in ack


# ============================================================================
# Cross-lang false-positive risk (spec §7.6 clause 3 — defensive test)
# ============================================================================


def test_short_common_words_should_not_false_match_across_langs():
    """Sanity check on clause 3 of lang_hint semantics — abandonment phrases must
    be unambiguous so cross-lang fallback doesn't produce false positives.

    "stop" appears in en + id banks — both legitimate abandonment. Acceptable.
    "ok" / "yes" / "no" must NOT be in any bank — would cause false positives.
    """
    h = AbandonmentHandler()
    state = _base_state()
    # Common confirmations that are NOT abandonment
    for non_abandonment in ["ok", "yes", "no", "alright", "sure", "ya"]:
        result = h.matches(text=non_abandonment, state=state, lang_hint="en")
        assert result.matched is False, (
            f"{non_abandonment!r} false-matched as abandonment — keyword bank too aggressive"
        )


def test_matched_phrase_is_subset_of_input():
    """If matched=True, the matched_phrase should appear in (a lowercased version of) input."""
    h = AbandonmentHandler()
    state = _base_state()
    result = h.matches(
        text="Actually never mind, I'll come back later",
        state=state,
        lang_hint="en",
    )
    assert result.matched is True
    assert result.matched_phrase.lower() in "actually never mind, i'll come back later"
