"""Tests for OOCContext + OOCAuditMetadata + extended OOCDecision/OOCResult schemas.

Per spec §2.1.1 + §2.1.2 + §7.5 + §7.8.
"""
import pytest
import pydantic

from modules.out_of_context.ooc_types import (
    OOCContext,
    OOCAuditMetadata,
    OOCDecision,
    OOCResult,
    OOCCategory,
    ShapeUsed,
    OOCLabel,
    LEGACY_LABEL_MAP,
)


# ============================================================================
# OOCContext
# ============================================================================


def test_ooc_context_minimal_construction():
    ctx = OOCContext(
        user_text="hello",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
    )
    assert ctx.session_fallback_language == "en"
    assert ctx.active_service is None
    assert ctx.pre_data is False
    assert ctx.high_stakes_intake is False
    assert ctx.previously_seen_OOC_in_session == 0
    assert ctx.previous_user_ooc_categories == []
    assert ctx.previous_system_meta_actions == []
    assert ctx.ooc_escalation_suppression_remaining == 0


def test_ooc_context_rejects_invalid_confidence_above_one():
    with pytest.raises(pydantic.ValidationError):
        OOCContext(
            user_text="x",
            user_detected_language="en",
            raw_detected_language="en",
            raw_detection_confidence=1.5,
        )


def test_ooc_context_rejects_invalid_confidence_below_zero():
    with pytest.raises(pydantic.ValidationError):
        OOCContext(
            user_text="x",
            user_detected_language="en",
            raw_detected_language="en",
            raw_detection_confidence=-0.1,
        )


def test_ooc_context_rejects_negative_streak():
    with pytest.raises(pydantic.ValidationError):
        OOCContext(
            user_text="x",
            user_detected_language="en",
            raw_detected_language="en",
            raw_detection_confidence=0.5,
            previously_seen_OOC_in_session=-1,
        )


def test_ooc_context_default_factory_isolation():
    ctx1 = OOCContext(
        user_text="x", user_detected_language="en",
        raw_detected_language="en", raw_detection_confidence=0.5,
    )
    ctx1.previous_user_ooc_categories.append("OOC-CAREERS")
    ctx2 = OOCContext(
        user_text="y", user_detected_language="en",
        raw_detected_language="en", raw_detection_confidence=0.5,
    )
    assert ctx2.previous_user_ooc_categories == []  # not shared


# ============================================================================
# OOCAuditMetadata (Refinement #4)
# ============================================================================


def test_audit_metadata_minimal():
    m = OOCAuditMetadata(classifier_confidence=0.8, classifier_mode="hybrid")
    assert m.classifier_confidence == 0.8
    assert m.bidi_wrap_applied is False
    assert m.extracted_mention is None
    assert m.previous_categories_chain == []


def test_audit_metadata_rejects_invalid_classifier_mode():
    with pytest.raises(pydantic.ValidationError):
        OOCAuditMetadata(classifier_confidence=0.5, classifier_mode="invalid")


def test_audit_metadata_rejects_invalid_confidence_range():
    with pytest.raises(pydantic.ValidationError):
        OOCAuditMetadata(classifier_confidence=1.5, classifier_mode="hybrid")


def test_audit_metadata_serializes_to_dict():
    m = OOCAuditMetadata(
        classifier_confidence=0.9,
        classifier_mode="keyword",
        extracted_mention="tax consulting",
        active_service="wbs",
        pre_data=False,
        high_stakes_intake=False,
    )
    d = m.model_dump()
    assert d["classifier_confidence"] == 0.9
    assert d["classifier_mode"] == "keyword"
    assert d["extracted_mention"] == "tax consulting"


# ============================================================================
# OOCDecision (extended)
# ============================================================================


def test_ooc_decision_legacy_construction():
    # Pre-Stage-0 callers: yes/label/confidence/reason
    d = OOCDecision(yes=True, label="freelance", confidence=0.95, reason="strict_keyword")
    assert d.yes is True
    assert d.label == "freelance"
    assert d.classifier_mode == "hybrid"  # default


def test_ooc_decision_new_extracted_fields_default_none():
    d = OOCDecision(yes=False)
    assert d.extracted_mention is None
    assert d.extracted_hint is None


def test_ooc_decision_with_extracted_mention():
    d = OOCDecision(
        yes=True, label="OOC-ADJACENT-SERVICE", confidence=0.7,
        extracted_mention="tax consulting",
    )
    assert d.extracted_mention == "tax consulting"


# ============================================================================
# OOCResult (extended) — UPDATE_SESSION_FALLBACK_LANGUAGE MUST NOT EXIST
# ============================================================================


def test_ooc_result_minimal_construction():
    r = OOCResult()
    assert r.message == ""
    assert r.set_escalation_suppression is False
    assert r.streak_classification == "user_ooc"
    assert r.audit_metadata is None
    # Legacy
    assert r.triggered is False
    assert r.route == "out_of_context_agent"


def test_ooc_result_does_not_have_update_session_fallback_language_field():
    """Per spec revision Minor #1: field removed; orchestrator owns state semantics."""
    r = OOCResult()
    assert not hasattr(r, "update_session_fallback_language"), (
        "OOCResult.update_session_fallback_language was intentionally removed in "
        "the spec revision (Minor #1). Orchestrator owns session_fallback_language "
        "mutation based on raw_detection_confidence + T1-OOC cold-start exception. "
        "If you see this assertion fail, someone re-added the field — read the "
        "spec §7.2 + §2.1.2 before restoring it."
    )


def test_ooc_result_with_full_payload():
    audit = OOCAuditMetadata(classifier_confidence=0.9, classifier_mode="hybrid")
    r = OOCResult(
        message="rendered text",
        category="OOC-PARTNERSHIP",
        shape_used="cold_start",
        language_used="en",
        set_escalation_suppression=False,
        streak_classification="user_ooc",
        audit_metadata=audit,
        triggered=True,
    )
    assert r.message == "rendered text"
    assert r.category == "OOC-PARTNERSHIP"
    assert r.audit_metadata is audit
    assert r.streak_classification == "user_ooc"


def test_ooc_result_escalation_payload():
    audit = OOCAuditMetadata(
        classifier_confidence=0.95, classifier_mode="hybrid",
        trigger="consecutive_ooc_escalation", streak_length=3,
    )
    r = OOCResult(
        message="handover text",
        category="ESCALATION-CONSECUTIVE-OOC",
        shape_used="escalation_handover",
        language_used="en",
        set_escalation_suppression=True,
        streak_classification="system_meta",
        audit_metadata=audit,
    )
    assert r.streak_classification == "system_meta"
    assert r.set_escalation_suppression is True
    assert r.category == "ESCALATION-CONSECUTIVE-OOC"


# ============================================================================
# LEGACY_LABEL_MAP — translation table for migrating call sites
# ============================================================================


def test_legacy_label_map_freelance_translates():
    assert LEGACY_LABEL_MAP["freelance"] == "OOC-FREELANCE"


def test_legacy_label_map_partnership_translates():
    assert LEGACY_LABEL_MAP["partnership"] == "OOC-PARTNERSHIP"


def test_legacy_label_map_none_translates_to_none():
    assert LEGACY_LABEL_MAP["none"] is None


def test_legacy_label_map_covers_all_legacy_values():
    # OOCLabel is Literal["freelance", "partnership", "none"]; map must cover all 3
    for legacy_value in ["freelance", "partnership", "none"]:
        assert legacy_value in LEGACY_LABEL_MAP
