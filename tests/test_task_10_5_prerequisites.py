"""Tests for Task 10.5 prerequisite helpers.

Two helpers added in preparation for Task 11 orchestrator integration:
- `detect_language_with_confidence` (sd_policies.py) — canonical language primitive
- `record_audit_row` (core/app_audit.py) — non-LLM audit row writer

Per spec §1.1 + §7.4 + §9.
"""
import logging
import pytest


# ============================================================================
# detect_language_with_confidence
# ============================================================================


def test_detect_language_with_confidence_empty_text():
    from modules.system_detection.sd_policies import detect_language_with_confidence
    code, name, conf = detect_language_with_confidence("")
    assert code == "en"
    assert conf == 1.0


def test_detect_language_with_confidence_returns_three_tuple():
    """Sanity: signature is (code, name, conf)."""
    from modules.system_detection.sd_policies import detect_language_with_confidence
    result = detect_language_with_confidence("   ")  # whitespace → empty path
    assert isinstance(result, tuple)
    assert len(result) == 3
    code, name, conf = result
    assert isinstance(code, str)
    assert isinstance(name, str)
    assert isinstance(conf, float)
    assert 0.0 <= conf <= 1.0


def test_detect_language_with_confidence_claude_failure_falls_back_to_langid(monkeypatch):
    """When Claude raises, fall back to langid + return langid confidence."""
    from modules.system_detection import sd_policies

    def fake_llm_raises(text):
        raise RuntimeError("simulated Claude failure")

    def fake_langid(text):
        return "id", 0.78

    monkeypatch.setattr(sd_policies, "_detect_language_llm", fake_llm_raises)
    monkeypatch.setattr(sd_policies, "_detect_language_langid", fake_langid)

    code, name, conf = sd_policies.detect_language_with_confidence("test text")
    assert code == "id"
    assert conf == 0.78
    # name is endonym — Indonesian endonym is "Indonesia"
    assert name == "Indonesia"


def test_detect_language_with_confidence_low_llm_confidence_returned_as_is(monkeypatch):
    """Low Claude confidence is returned verbatim — orchestrator (not detector) decides fallback."""
    from modules.system_detection import sd_policies

    def fake_llm_low_conf(text):
        return "fr", "Français", 0.4  # below OOC_LANG_DETECTION_FLOOR (0.85)

    monkeypatch.setattr(sd_policies, "_detect_language_llm", fake_llm_low_conf)

    code, name, conf = sd_policies.detect_language_with_confidence("text")
    assert code == "fr"
    assert conf == 0.4  # exact value returned; orchestrator decides what to do with it


def test_detect_language_with_confidence_claude_high_confidence_surfaces(monkeypatch):
    """Polish item #1: Happy path — high-confidence Claude detection surfaces (code, name, conf_llm) verbatim.

    Spec §1.1 Step 1 requires the raw_confidence value to flow through to the
    orchestrator so it can compare against OOC_LANG_DETECTION_FLOOR. This test
    locks the happy-path surfacing explicitly (not implicitly via the
    return-three-tuple shape test).
    """
    from modules.system_detection import sd_policies

    def fake_llm_high_conf(text):
        return "ja", "日本語", 0.97

    monkeypatch.setattr(sd_policies, "_detect_language_llm", fake_llm_high_conf)

    code, name, conf = sd_policies.detect_language_with_confidence("こんにちは")
    assert code == "ja"
    assert name == "日本語"
    assert conf == 0.97
    # Confidence must be exactly the LLM's value — no rounding, no clamping below 1.0,
    # no transformation. Orchestrator decides what to do with it.


def test_build_language_meta_still_returns_two_tuple(monkeypatch):
    """Backward-compat — `build_language_meta` signature unchanged."""
    from modules.system_detection import sd_policies

    monkeypatch.setattr(
        sd_policies,
        "_detect_language_llm",
        lambda text: ("en", "English", 0.95),
    )
    result = sd_policies.build_language_meta("hello world")
    assert isinstance(result, tuple)
    assert len(result) == 2  # NOT 3 — original signature preserved
    code, name = result
    assert code == "en"


def test_build_language_meta_empty_text_returns_default():
    """Backward-compat — empty path mirrors original behavior."""
    from modules.system_detection.sd_policies import build_language_meta
    code, name = build_language_meta("")
    assert code == "en"


# ============================================================================
# record_audit_row
# ============================================================================


def test_record_audit_row_writes_doc_to_writer(monkeypatch):
    """Helper writes a doc through the writer singleton."""
    from core import app_audit

    captured = []

    class FakeWriter:
        def write(self, doc):
            captured.append(doc)

    monkeypatch.setattr(app_audit, "_writer_instance", FakeWriter())

    app_audit.record_audit_row(
        stage="ooc_handler",
        session_id="test-001",
        extras={"category": "OOC-PARTNERSHIP", "classifier_mode": "keyword"},
    )

    assert len(captured) == 1
    doc = captured[0]
    assert doc["stage"] == "ooc_handler"
    assert doc["sessionId"] == "test-001"
    assert doc["kind"] == "audit_event"
    assert doc["extras"]["category"] == "OOC-PARTNERSHIP"
    assert doc["schema_version"] == 1


def test_record_audit_row_default_route_is_system_detection(monkeypatch):
    from core import app_audit

    captured = []

    class FakeWriter:
        def write(self, doc):
            captured.append(doc)

    monkeypatch.setattr(app_audit, "_writer_instance", FakeWriter())

    app_audit.record_audit_row(stage="abandonment_handler", session_id="s1", extras={})
    assert captured[0]["route"] == "system_detection"


def test_record_audit_row_swallows_writer_exceptions(monkeypatch, caplog):
    """Audit must NEVER raise into caller — parity with record_llm_call."""
    from core import app_audit

    class RaisingWriter:
        def write(self, doc):
            raise RuntimeError("writer failure simulation")

    monkeypatch.setattr(app_audit, "_writer_instance", RaisingWriter())

    # MUST NOT raise
    app_audit.record_audit_row(
        stage="ooc_suppression_fallthrough",
        session_id="s2",
        extras={"suppression_remaining_pre": 3, "suppression_remaining_post": 2},
    )
    # If we get here, the helper correctly swallowed the exception.


def test_record_audit_row_supports_all_3_stages(monkeypatch):
    """All 3 stages from spec §7.4 must be writable."""
    from core import app_audit

    captured = []

    class FakeWriter:
        def write(self, doc):
            captured.append(doc)

    monkeypatch.setattr(app_audit, "_writer_instance", FakeWriter())

    # Stage 1: ooc_handler with typed OOCAuditMetadata dict
    from modules.out_of_context.ooc_types import OOCAuditMetadata
    m = OOCAuditMetadata(classifier_confidence=0.8, classifier_mode="hybrid")
    app_audit.record_audit_row(
        stage="ooc_handler", session_id="s1", extras=m.model_dump()
    )

    # Stage 2: ooc_suppression_fallthrough
    app_audit.record_audit_row(
        stage="ooc_suppression_fallthrough",
        session_id="s1",
        extras={
            "suppression_remaining_pre": 3,
            "suppression_remaining_post": 2,
            "downstream_route": "sa_continuation",
            "posthoc_classifier_sampled": False,
        },
    )

    # Stage 3: abandonment_handler
    app_audit.record_audit_row(
        stage="abandonment_handler",
        session_id="s1",
        extras={
            "matched_phrase": "never mind",
            "detected_language": "en",
            "matched_via": "lang_hint_match",
            "cleared_service": "wbs",
            "cleared_field": "case_handler_quantity",
        },
    )

    assert len(captured) == 3
    stages = [d["stage"] for d in captured]
    assert stages == ["ooc_handler", "ooc_suppression_fallthrough", "abandonment_handler"]


def test_record_audit_row_writer_singleton_shared_with_record_llm_call(monkeypatch):
    """Parity check: both helpers use the same _get_writer() singleton.

    Validates that overriding _writer_instance affects both helpers identically —
    test-fixture parity per refinement (d).
    """
    from core import app_audit

    captured = []

    class FakeWriter:
        def write(self, doc):
            captured.append(doc)

    monkeypatch.setattr(app_audit, "_writer_instance", FakeWriter())

    # Both helpers should write through the same fake writer
    app_audit.record_audit_row(stage="abandonment_handler", session_id="s1", extras={})
    app_audit.record_llm_call(
        route="r", stage="llm_test", session_id="s1", token_id=None,
        prompt="p", response="r", model="m",
        latency_ms=10, input_tokens=1, output_tokens=2,
    )

    assert len(captured) == 2
    assert captured[0]["kind"] == "audit_event"  # non-LLM
    assert captured[1]["kind"] == "llm_call"      # LLM
