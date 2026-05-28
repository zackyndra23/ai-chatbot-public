"""Smoke tests for the real modules/i18n/ schema + en.yaml + id.yaml.

These tests load the production i18n directory (not tmp_path) to verify the
schema/YAML contract holds end-to-end. CRITICAL = test failure. WARN/INFO =
counted but not failed (status=draft + status=missing entries WILL log WARN).
"""
from pathlib import Path

import pytest

from modules.i18n import t, validate_all, _reset_registry_for_tests
from modules.i18n.loader import I18nLoader


I18N_DIR = Path(__file__).resolve().parents[1] / "modules" / "i18n"


@pytest.fixture(autouse=True)
def _reset():
    """Reset the singleton registry between tests so each test sees a fresh load."""
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def test_real_schema_has_no_critical_issues():
    report = I18nLoader(base_dir=I18N_DIR).validate()
    critical = report.critical_issues()
    assert critical == [], "CRITICAL issues:\n" + "\n".join(
        f"  {i.key} ({i.lang}): {i.message}" for i in critical
    )


def test_real_loader_constructs_registry_successfully():
    # If CRITICAL issues exist, this raises MissingKeyError
    registry = I18nLoader(base_dir=I18N_DIR).load()
    assert registry is not None
    assert len(registry.entries) > 0


def test_real_schema_has_n_keys():
    """Schema-key count grows as Tasks 14-19 lift palette surfaces into i18n.

    Baseline (Task 4): 38 keys (13 cold_start + 13 mid_flow_p1 + 6 shared paragraphs
                                + 3 escalation + 1 pillar block + 2 abandonment).
    Task 14 added: +1 (greeting.palette).
    Tasks 15-18 will add more (opener, banned forms, rescue, picker labels, meeting).

    Test asserts lower bound (≥ baseline) — exact count grows per task.
    """
    registry = I18nLoader(base_dir=I18N_DIR).load()
    assert len(registry.schema) >= 38, (
        f"Schema key count regressed below Task 4 baseline of 38. "
        f"Got {len(registry.schema)} keys."
    )


def test_real_ooc_partnership_cold_start_renders_en():
    # LC-1 — verified en translation renders with substitution
    out = t(
        "ooc.OOC-PARTNERSHIP.cold_start",
        "en",
        partnership_url="https://example.com/partners",
        indo_email="contact@example.com",
        indo_phone="+1 (555) 010-0100",
        business_hours="Mon-Fri 09:00-18:00 WIB",
    )
    assert "https://example.com/partners" in out
    assert "contact@example.com" in out
    assert "+1 (555) 010-0100" in out
    assert "{" not in out, f"Unsubstituted placeholder in output: {out!r}"


def test_real_ooc_partnership_cold_start_renders_id():
    # Draft id translation renders (LC-1 + draft-status info log)
    out = t(
        "ooc.OOC-PARTNERSHIP.cold_start",
        "id",
        partnership_url="https://example.com/partners",
        indo_email="contact@example.com",
        indo_phone="+1 (555) 010-0100",
        business_hours="Mon-Fri 09:00-18:00 WIB",
    )
    assert "https://example.com/partners" in out
    assert "contact@example.com" in out
    assert "Anda" in out, "Indonesian translation must use 'Anda' formal (spec §4.5)"
    assert "{" not in out


def test_real_ooc_complaint_cold_start_renders_id_with_polymorphic_hint():
    # Spec §7.5 polymorphic extracted_hint → engagement_reference for COMPLAINT
    out = t(
        "ooc.OOC-COMPLAINT.cold_start",
        "id",
        indo_email="contact@example.com",
        indo_phone="+62 21",
        business_hours="Mon-Fri",
        engagement_reference="CASE-2026-0042",
    )
    assert "CASE-2026-0042" in out
    assert "Service Concern" in out  # subject-line tag stays English per Constraint #6


def test_real_pillar_block_renders_en():
    out = t("ooc.service.taxonomy.pillar_block", "en")
    assert "Prevention" in out
    assert "Detection" in out
    assert "Mitigation" in out
    assert "Brand Protection" in out
    assert "Non-Use Investigation" in out  # All 4 Brand Protection lines have Investigation suffix


def test_real_pillar_block_renders_id_bilingual():
    out = t("ooc.service.taxonomy.pillar_block", "id")
    # Pillar names translated (with English in parens per glossary policy)
    assert "Pencegahan" in out
    assert "Deteksi" in out
    assert "Mitigasi" in out
    assert "Perlindungan Merek" in out
    # Service line names stay English
    assert "Background Check" in out
    assert "Whistleblowing Hotline" in out


def test_real_abandonment_trigger_phrases_returns_list():
    phrases_en = t("abandonment.trigger_phrases", "en")
    phrases_id = t("abandonment.trigger_phrases", "id")
    assert isinstance(phrases_en, list)
    assert isinstance(phrases_id, list)
    assert "never mind" in phrases_en
    assert "udahan saja" in phrases_id


def test_real_abandonment_acknowledgment_renders():
    ack_en = t("abandonment.acknowledgment", "en")
    ack_id = t("abandonment.acknowledgment", "id")
    assert isinstance(ack_en, str)
    assert isinstance(ack_id, str)
    assert "Anda" in ack_id  # Formal Indonesian


def test_real_shared_paragraphs_render_en():
    p2 = t(
        "ooc.midflow.p2_standard_with_field", "en",
        active_service_label="Whistleblowing Hotline (WBS)",
        current_field_label="Number of Case Handlers",
    )
    assert "Whistleblowing Hotline (WBS)" in p2
    assert "Number of Case Handlers" in p2

    p3 = t("ooc.midflow.p3_repose", "en", last_question="How many handlers?")
    assert "How many handlers?" in p3


def test_real_escalation_handover_renders_en():
    p1 = t("ooc.escalation.acknowledgment", "en")
    assert len(p1) > 20  # has content

    p2 = t(
        "ooc.escalation.handover_contacts", "en",
        indo_phone="+62 21", indo_email="x@y", my_sg_phone="+60", my_sg_email="y@z",
        th_vn_phone="+66", th_vn_email="z@w", business_hours="Mon-Fri",
    )
    assert "Indonesia" in p2
    assert "Malaysia" in p2
    assert "Thailand" in p2

    p3 = t("ooc.escalation.resume_offer", "en", active_service_label="WBS")
    assert "WBS" in p3


# ============================================================================
# Glossary (Task 5)
# ============================================================================


def test_glossary_service_label_en():
    from modules.i18n import _get_registry
    reg = _get_registry()
    assert reg.service_label("wbs", "en") == "Whistleblowing Hotline (WBS)"


def test_glossary_service_label_id_bilingual():
    from modules.i18n import _get_registry
    reg = _get_registry()
    assert reg.service_label("wbs", "id") == "Sistem Whistleblowing (WBS)"


def test_glossary_service_label_unknown_lang_falls_back_to_en():
    from modules.i18n import _get_registry
    reg = _get_registry()
    # 'ja' not in Phase 2a glossary — should fall back to en per spec §4.9
    assert reg.service_label("wbs", "ja") == "Whistleblowing Hotline (WBS)"


def test_glossary_service_label_unknown_id_returns_none():
    from modules.i18n import _get_registry
    reg = _get_registry()
    assert reg.service_label("nonexistent_service", "en") is None


def test_glossary_all_15_service_lines_present_en():
    from modules.i18n import _get_registry
    reg = _get_registry()
    expected = {
        "wbs", "ebs", "due_diligence", "kyc", "abms_elearning",
        "mystery_shopping", "market_research",
        "compliance_audit", "claim_review",
        "asset_verification", "contact_verification",
        "non_use_investigation", "anti_counterfeit_investigation",
        "parallel_trading_investigation", "trademark_investigation",
    }
    for sid in expected:
        label = reg.service_label(sid, "en")
        assert label is not None, f"Missing en service_label for {sid}"


def test_glossary_field_label_returns_noun_phrase_en():
    from modules.i18n import _get_registry
    reg = _get_registry()
    # Per spec §4.9 — field labels must be noun phrases (no verb-prefixed labels)
    label = reg.field_label("case_handler_quantity", "en")
    assert label == "Number of Case Handlers"


def test_glossary_field_label_id():
    from modules.i18n import _get_registry
    reg = _get_registry()
    label = reg.field_label("case_handler_quantity", "id")
    assert label == "Jumlah Penanggung Jawab Kasus"


def test_glossary_field_label_unknown_returns_none():
    from modules.i18n import _get_registry
    reg = _get_registry()
    assert reg.field_label("nonexistent_field", "en") is None


def test_glossary_ui_term_returns_translation():
    from modules.i18n import _get_registry
    reg = _get_registry()
    assert reg.ui_term("qualification", "en") == "qualification"
    assert reg.ui_term("qualification", "id") == "kualifikasi"
