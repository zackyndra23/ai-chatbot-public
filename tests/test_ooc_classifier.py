"""Tests for OOCClassifier — 14 categories + Constraint #4 in-scope protection.

Per spec §1.2 + §2.4. Validates DT-1, DT-9, LC-6 (in part).

Test isolation: LLM call is monkeypatched to a stub. NEVER hits Anthropic API.
"""
import pytest

from modules.out_of_context.ooc_classifier import OOCClassifier
from modules.out_of_context.ooc_types import OOCDecision


@pytest.fixture(autouse=True)
def mock_llm_classifier(monkeypatch):
    """Stub LLM call so classifier tests run offline.

    Stub mimics a reasonable hybrid-mode LLM: routes adjacent-service text to
    OOC-ADJACENT-SERVICE with 0.8 confidence; ISO text to OOC-ADJACENT-ISO with
    0.85; rest to NONE.
    """
    def fake_llm(self, text, lang, active_service):
        text_lc = (text or "").lower()
        if any(k in text_lc for k in ["tax consult", "audit firm", "accounting service", "legal counsel", "do you offer", "do you provide"]):
            return "OOC-ADJACENT-SERVICE", 0.8
        if "iso" in text_lc and ("certif" in text_lc or "37001" in text_lc):
            return "OOC-ADJACENT-ISO", 0.85
        if any(k in text_lc for k in ["how are you", "tell me a joke"]):
            return "OOC-CHITCHAT", 0.85
        if any(k in text_lc for k in ["should i hire", "personal advice"]):
            return "OOC-PERSONAL-ADVICE", 0.8
        return "NONE", 0.0

    monkeypatch.setattr(
        "modules.out_of_context.ooc_classifier.OOCClassifier._llm_classify",
        fake_llm,
    )


@pytest.fixture
def cls():
    return OOCClassifier(mode="hybrid")


@pytest.fixture
def cls_keyword():
    return OOCClassifier(mode="keyword")


# ============================================================================
# Strict-keyword categories (deterministic)
# ============================================================================


def test_intent_phrase_freelance_en(cls):
    # DT-1 cold-start OOC
    d = cls.classify("I want to be a freelancer", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-FREELANCE"
    assert d.confidence >= 0.95
    assert d.classifier_mode == "keyword"


def test_intent_phrase_freelance_id(cls):
    d = cls.classify("saya mau jadi freelancer", "id", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-FREELANCE"


def test_intent_phrase_partnership_en(cls):
    d = cls.classify("I want to partner with Acme Services", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-PARTNERSHIP"
    assert d.confidence >= 0.95


def test_intent_phrase_partnership_id(cls):
    d = cls.classify("saya ingin jadi mitra bisnis Acme Services", "id", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-PARTNERSHIP"


def test_mystery_shopper_apply_keyword(cls):
    d = cls.classify("I want to become a mystery shopper", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-MYSTERY-SHOPPER-APPLY"


def test_careers_keyword_with_field_extraction(cls):
    d = cls.classify(
        "I'm looking for a job. I have a background in data analytics, mostly Python",
        "en",
        active_service=None,
    )
    assert d.yes is True
    assert d.label == "OOC-CAREERS"
    # extracted_hint should capture the user's field
    assert d.extracted_hint is not None
    assert "data analytics" in d.extracted_hint.lower()


def test_press_media_keyword(cls):
    d = cls.classify("I have a press inquiry for an article", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-PRESS-MEDIA"


def test_vendor_supplier_keyword(cls):
    d = cls.classify("We are a vendor offering data services", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-VENDOR-SUPPLIER"


def test_complaint_keyword_with_engagement_ref_extraction(cls):
    d = cls.classify(
        "I want to complain about case CASE-2026-0042",
        "en",
        active_service=None,
    )
    assert d.yes is True
    assert d.label == "OOC-COMPLAINT"
    assert d.extracted_hint == "CASE-2026-0042"


# ============================================================================
# LLM-classified fuzzy categories (hybrid mode)
# ============================================================================


def test_adjacent_service_via_llm(cls):
    d = cls.classify("Do you offer tax consulting?", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-ADJACENT-SERVICE"
    assert d.classifier_mode == "llm"
    # extracted_mention should capture what was mentioned
    assert d.extracted_mention is not None


def test_adjacent_iso_via_llm(cls):
    d = cls.classify("Can you provide ISO 37001 certification?", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-ADJACENT-ISO"


def test_chitchat_via_llm(cls):
    d = cls.classify("Tell me a joke please", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-CHITCHAT"


def test_personal_advice_via_llm(cls):
    d = cls.classify("Should I hire a lawyer for my divorce?", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-PERSONAL-ADVICE"


# ============================================================================
# UNCLEAR / too-short input
# ============================================================================


def test_too_short_input_returns_unclear_at_cold_start(cls):
    d = cls.classify("hi", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-UNCLEAR"
    assert d.reason == "too_short"


def test_too_short_input_does_NOT_fire_unclear_during_mid_flow(cls):
    # When active_service is set, short input like "hi" is treated as on-topic
    # (could be acknowledgment / chitchat that doesn't need OOC handling).
    # Constraint #4 protection territory.
    d = cls.classify("hi", "en", active_service="wbs")
    assert d.yes is False


# ============================================================================
# Constraint #4 in-scope protection (DT-9)
# ============================================================================


def test_in_scope_wbs_term_during_wbs_flow_returns_no_ooc(cls):
    # DT-9 — "what's a case handler?" during WBS qualification → NOT OOC
    d = cls.classify(
        "what's a case handler?",
        "en",
        active_service="wbs",
    )
    assert d.yes is False
    assert d.reason == "in_scope_protection"


def test_in_scope_wbs_term_id_during_wbs_flow(cls):
    d = cls.classify(
        "siapa penanggung jawab kasus di WBS?",
        "id",
        active_service="wbs",
    )
    assert d.yes is False
    assert d.reason == "in_scope_protection"


def test_in_scope_ebs_term_during_ebs_flow(cls):
    d = cls.classify(
        "Tell me about background screening",
        "en",
        active_service="ebs",
    )
    assert d.yes is False


def test_in_scope_due_diligence_term_during_dd_flow(cls):
    d = cls.classify(
        "Who is the beneficial owner?",
        "en",
        active_service="due_diligence",
    )
    assert d.yes is False


def test_in_scope_claim_review_term(cls):
    """High_stakes service — parity coverage required."""
    d = cls.classify(
        "Tell me about your claim verification process",
        "en",
        active_service="claim_review",
    )
    assert d.yes is False
    assert d.reason == "in_scope_protection"


def test_in_scope_asset_verification_term(cls):
    """High_stakes service — parity coverage required."""
    d = cls.classify(
        "Can you help with asset recovery?",
        "en",
        active_service="asset_verification",
    )
    assert d.yes is False
    assert d.reason == "in_scope_protection"


def test_in_scope_contact_verification_term(cls):
    """High_stakes service — parity coverage required."""
    d = cls.classify(
        "I need contact information for a missing person",
        "en",
        active_service="contact_verification",
    )
    assert d.yes is False
    assert d.reason == "in_scope_protection"


def test_all_4_high_stakes_services_have_in_scope_protection():
    """Coverage parity check — all 4 OOC_HIGH_STAKES_SERVICES must have banks.

    High_stakes services route to mid_flow_high_stakes shape (P4 escalation
    to investigation team). False-positive OOC on these flows has higher
    consequence than non-high-stakes services, so coverage parity is mandatory.
    """
    from modules.out_of_context.ooc_policies import IN_SCOPE_SERVICE_TERMS
    from core.app_config import Config
    cfg = Config()
    for service_id in cfg.OOC_HIGH_STAKES_SERVICES:
        assert service_id in IN_SCOPE_SERVICE_TERMS, (
            f"High_stakes service {service_id!r} missing from IN_SCOPE_SERVICE_TERMS. "
            f"High_stakes services MUST have in-scope protection banks for parity."
        )


def test_freelance_intent_during_active_service_still_fires_ooc(cls):
    # IMPORTANT: in-scope protection runs AFTER strict-keyword categories.
    # An explicit "I want to be a freelancer" during WBS flow IS OOC — user
    # is genuinely off-topic. In-scope protection must NOT suppress this.
    d = cls.classify(
        "I want to be a freelancer",
        "en",
        active_service="wbs",
    )
    assert d.yes is True
    assert d.label == "OOC-FREELANCE"


def test_unknown_service_in_scope_protection_no_op(cls):
    # If active_service is not in IN_SCOPE_SERVICE_TERMS, protection is no-op.
    # Pass-through to LLM / no_match.
    d = cls.classify(
        "what's a case handler?",
        "en",
        active_service="unknown_service_id",
    )
    # No keyword match, no LLM fire, no in-scope-term bank → no_match
    assert d.yes is False
    assert d.reason in ("no_match", "llm_low_confidence_pass_through")


# ============================================================================
# Mode gating — LLM call MUST be gated by OOC_MODE (watchpoint per user)
# ============================================================================


def test_keyword_mode_never_calls_llm(monkeypatch):
    """Verify _llm_classify is never invoked in keyword mode."""
    called = []

    def spy(self, text, lang, active_service):
        called.append((text, lang, active_service))
        return "OOC-CATCHALL", 0.99  # Would otherwise dominate the result

    monkeypatch.setattr(
        "modules.out_of_context.ooc_classifier.OOCClassifier._llm_classify",
        spy,
    )

    cls = OOCClassifier(mode="keyword")
    # Input that doesn't match any keyword bank
    d = cls.classify("just some random text about weather", "en", active_service=None)

    assert called == [], "LLM was invoked in keyword mode (should be gated)"
    assert d.yes is False  # no match


def test_hybrid_mode_calls_llm_for_residual(monkeypatch):
    called = []

    def spy(self, text, lang, active_service):
        called.append(1)
        return "NONE", 0.0

    monkeypatch.setattr(
        "modules.out_of_context.ooc_classifier.OOCClassifier._llm_classify",
        spy,
    )

    cls = OOCClassifier(mode="hybrid")
    cls.classify("just some random text about weather", "en", active_service=None)
    assert len(called) == 1, "LLM should be called once in hybrid mode for residual classification"


def test_keyword_mode_uses_fuzzy_keyword_banks(cls_keyword):
    # In keyword mode, fuzzy categories fall back to keyword matching
    d = cls_keyword.classify("Do you offer tax consulting?", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-ADJACENT-SERVICE"
    assert d.classifier_mode == "keyword"
    assert d.reason == "fuzzy_keyword"


# ============================================================================
# LLM confidence thresholds (spec §2.4)
# ============================================================================


def test_llm_below_floor_passes_through(monkeypatch):
    def low_conf(self, text, lang, active_service):
        return "OOC-CHITCHAT", 0.3  # below default 0.6 floor

    monkeypatch.setattr(
        "modules.out_of_context.ooc_classifier.OOCClassifier._llm_classify",
        low_conf,
    )

    cls = OOCClassifier(mode="hybrid")
    d = cls.classify("some ambiguous text", "en", active_service=None)
    assert d.yes is False
    assert d.reason == "llm_low_confidence_pass_through"


def test_catchall_below_catchall_floor_passes_through(monkeypatch):
    def catchall_below(self, text, lang, active_service):
        return "OOC-CATCHALL", 0.65  # above 0.6 LLM floor but below 0.7 CATCHALL floor

    monkeypatch.setattr(
        "modules.out_of_context.ooc_classifier.OOCClassifier._llm_classify",
        catchall_below,
    )

    cls = OOCClassifier(mode="hybrid")
    d = cls.classify("some text", "en", active_service=None)
    assert d.yes is False
    assert d.reason == "catchall_below_threshold"


def test_catchall_above_floor_fires(monkeypatch):
    def catchall_high(self, text, lang, active_service):
        return "OOC-CATCHALL", 0.85

    monkeypatch.setattr(
        "modules.out_of_context.ooc_classifier.OOCClassifier._llm_classify",
        catchall_high,
    )

    cls = OOCClassifier(mode="hybrid")
    d = cls.classify("totally unclassifiable input", "en", active_service=None)
    assert d.yes is True
    assert d.label == "OOC-CATCHALL"
