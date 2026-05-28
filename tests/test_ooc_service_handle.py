"""Tests for OOCService.handle(ctx) — Layer B pipeline.

Per spec §1.2 B1-B5. Validates DT-1, DT-2, DT-3, DT-4, DT-5, SP-1, SP-2.
Also covers SA-2 (legacy maybe_handle() preserved).
"""
import logging
import pytest

from modules.i18n import _reset_registry_for_tests
from modules.out_of_context.ooc_service import OOCService
from modules.out_of_context.ooc_types import OOCContext


@pytest.fixture(autouse=True)
def _reset():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """Stub LLM call so handle() tests are deterministic offline."""
    def fake(self, text, lang, active_service):
        return "NONE", 0.0

    monkeypatch.setattr(
        "modules.out_of_context.ooc_classifier.OOCClassifier._llm_classify",
        fake,
    )


# ============================================================================
# Cold-start scenarios (DT-1)
# ============================================================================


def test_handle_cold_start_partnership_returns_cold_start_shape():
    # DT-1
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
    )
    result = svc.handle(ctx)
    assert result is not None
    assert result.category == "OOC-PARTNERSHIP"
    assert result.shape_used == "cold_start"
    assert result.language_used == "en"
    assert result.streak_classification == "user_ooc"
    assert result.set_escalation_suppression is False
    # Routing assets substituted in message
    assert "contact@acmeservices.example.com" in result.message or "@" in result.message
    # No unsubstituted placeholders
    assert "{" not in result.message


# ============================================================================
# Mid-flow scenarios (DT-2, DT-3, DT-4)
# ============================================================================


def test_handle_mid_flow_standard_returns_3_paragraph_composite():
    # DT-2
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
        active_service="wbs",
        current_field_id="case_handler_quantity",
        last_question_text="How many case handlers do you have?",
        pre_data=False,
        high_stakes_intake=False,
    )
    result = svc.handle(ctx)
    assert result is not None
    assert result.shape_used == "mid_flow_standard"
    # P1 + P2 (re-anchor) + P3 (re-pose)
    assert "Whistleblowing Hotline (WBS)" in result.message
    assert "How many case handlers do you have?" in result.message


def test_handle_mid_flow_high_stakes_returns_4_paragraph_composite():
    # DT-3
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
        active_service="compliance_audit",
        current_field_id="case_summary",
        pre_data=False,
        high_stakes_intake=True,
    )
    result = svc.handle(ctx)
    assert result.shape_used == "mid_flow_high_stakes"
    # P4 includes urgent/sensitive language
    assert "urgent" in result.message.lower() or "sensitive" in result.message.lower()


def test_handle_pre_data_overrides_high_stakes():
    # DT-4 — spec Q#3 refinement: pre_data wins over high_stakes
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
        active_service="compliance_audit",
        pre_data=True,
        high_stakes_intake=True,
    )
    result = svc.handle(ctx)
    assert result.shape_used == "mid_flow_pre_data"
    # Opt-in continuation
    assert "we hadn't started yet" in result.message or "start fresh" in result.message.lower()


# ============================================================================
# Escalation scenario (DT-5)
# ============================================================================


def test_handle_escalation_fires_when_threshold_reached():
    # DT-5 — 3rd consecutive OOC triggers escalation_handover
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
        previously_seen_OOC_in_session=2,  # 2 + 1 = 3 = threshold
    )
    result = svc.handle(ctx)
    assert result is not None
    assert result.category == "ESCALATION-CONSECUTIVE-OOC"
    assert result.shape_used == "escalation_handover"
    assert result.streak_classification == "system_meta"
    assert result.set_escalation_suppression is True
    # Audit metadata reflects escalation
    assert result.audit_metadata is not None
    assert result.audit_metadata.trigger == "consecutive_ooc_escalation"
    assert result.audit_metadata.streak_length == 2


def test_handle_below_threshold_does_NOT_escalate():
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
        previously_seen_OOC_in_session=1,  # 1 + 1 = 2 < threshold 3
    )
    result = svc.handle(ctx)
    assert result.streak_classification == "user_ooc"
    assert result.shape_used == "cold_start"
    assert result.set_escalation_suppression is False


# ============================================================================
# Constraint #4 in-scope protection (DT-9)
# ============================================================================


def test_handle_in_scope_question_returns_none():
    # DT-9 — in-scope qualification clarification → None (pass through)
    svc = OOCService()
    ctx = OOCContext(
        user_text="what's a case handler?",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
        active_service="wbs",
        current_field_id="case_handler_quantity",
    )
    result = svc.handle(ctx)
    assert result is None


# ============================================================================
# Audit metadata typing (Refinement #4)
# ============================================================================


def test_handle_returns_typed_audit_metadata():
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
    )
    result = svc.handle(ctx)
    assert result.audit_metadata is not None
    # Schema-valid: classifier_confidence in [0,1], classifier_mode in enum
    assert 0.0 <= result.audit_metadata.classifier_confidence <= 1.0
    assert result.audit_metadata.classifier_mode in ("keyword", "hybrid", "llm")
    assert result.audit_metadata.ooc_excursion_count_post == 1
    assert result.audit_metadata.active_service is None  # cold-start


def test_handle_audit_metadata_serializes_to_dict_for_mongo():
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
        active_service="wbs",
        current_field_id="case_handler_quantity",
    )
    result = svc.handle(ctx)
    d = result.audit_metadata.model_dump()
    # Schema fields for operator queries in spec §9
    assert "classifier_confidence" in d
    assert "classifier_mode" in d
    assert "active_service" in d
    assert "pre_data" in d
    assert "high_stakes_intake" in d
    assert d["active_service"] == "wbs"


# ============================================================================
# Language handling — RTL bidi wrap reflected in audit
# ============================================================================


def test_handle_in_ar_sets_bidi_wrap_applied():
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="ar",
        raw_detected_language="ar",
        raw_detection_confidence=0.95,
    )
    result = svc.handle(ctx)
    # Falls back to English text for ar (Phase 2a) but bidi_wrap_applied=True
    assert result.audit_metadata.bidi_wrap_applied is True


def test_handle_in_en_does_not_set_bidi_wrap_applied():
    svc = OOCService()
    ctx = OOCContext(
        user_text="I want to partner with Acme Services",
        user_detected_language="en",
        raw_detected_language="en",
        raw_detection_confidence=0.95,
    )
    result = svc.handle(ctx)
    assert result.audit_metadata.bidi_wrap_applied is False


# ============================================================================
# SA-2: legacy maybe_handle() backward compat
# ============================================================================


def test_legacy_maybe_handle_still_works():
    """SA-2 — pre-Stage-0 maybe_handle() must continue working."""
    svc = OOCService()
    # Legacy signature: kwargs only, returns OOCResult or None
    result = svc.maybe_handle(
        user_text="I want to be a freelancer",
        language_code="en",
    )
    # Legacy returns OOCResult on hit
    assert result is not None
    assert result.triggered is True
    assert result.decision.label == "freelance"  # legacy label preserved


def test_legacy_maybe_handle_returns_none_on_miss():
    svc = OOCService()
    result = svc.maybe_handle(
        user_text="what's the weather today",
        language_code="en",
    )
    # Empty string / no keyword hit → None
    assert result is None
