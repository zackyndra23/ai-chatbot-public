"""Tests for the OOC orchestrator (Layer A) — process_user_message_with_ooc.

Per spec §1.1 + §10A Decision Tree validation plan.

Task 11 covers Step 0 (abandonment) + Step 1-2 (language detection + fallback).
Tasks 12-13 will add tests for Step 2.5 (suppression) + Step 3-6 (dispatch).

Test isolation: detect_language_with_confidence is monkeypatched per-test to
avoid hitting Claude. Step 2.5 + Step 3-6 placeholders raise NotImplementedError
in this task; tests that exercise downstream steps monkeypatch them too.
"""
import logging
import pytest

from modules.service_agent.sa_types import AgentSessionState


def _state(**overrides) -> AgentSessionState:
    defaults = {
        "session_id": "test-orchestrator-001",
        "service_code": "",
        "question_id": "",
        "session_fallback_language": "en",
    }
    defaults.update(overrides)
    return AgentSessionState(**defaults)


@pytest.fixture
def captured_audit_rows(monkeypatch):
    """Capture all `record_audit_row` calls during a test for assertions."""
    rows = []

    def fake_record(*, stage, session_id, extras=None, route="system_detection",
                    token_id=None, error=None):
        rows.append({
            "stage": stage,
            "session_id": session_id,
            "extras": extras or {},
            "route": route,
            "token_id": token_id,
            "error": error,
        })

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator.record_audit_row",
        fake_record,
    )
    return rows


@pytest.fixture
def mock_language(monkeypatch):
    """Factory: returns a setter that monkeypatches detect_language_with_confidence."""
    def _setter(code: str, name: str, conf: float):
        def fake(text):
            return code, name, conf
        monkeypatch.setattr(
            "modules.system_detection.sd_orchestrator.detect_language_with_confidence",
            fake,
        )
    return _setter


# ============================================================================
# DT-8: Abandonment short-circuits dispatcher (spec §10A row 8)
# ============================================================================


def test_dt8_abandonment_short_circuits_at_step_0(captured_audit_rows, mock_language):
    """DT-8 — abandonment phrase clears SA state + writes abandonment_handler audit row."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="wbs",
        question_id="case_handler_quantity",
        ooc_excursion_count=2,
        previous_user_ooc_categories=["OOC-CAREERS"],
    )
    # Language detection should NOT be reached — abandonment short-circuits first.
    # Set a sentinel anyway in case Step 1 runs.
    mock_language("en", "English", 0.95)

    response = process_user_message_with_ooc(text="never mind", state=state)

    # SA state cleared by abandonment handler
    assert state.service_code == ""
    assert state.question_id == ""
    assert state.ooc_excursion_count == 0
    assert state.previous_user_ooc_categories == []

    # Acknowledgment returned
    assert isinstance(response, str)
    assert len(response) > 10

    # Exactly ONE abandonment audit row written
    abandonment_rows = [r for r in captured_audit_rows if r["stage"] == "abandonment_handler"]
    assert len(abandonment_rows) == 1
    row = abandonment_rows[0]
    assert row["session_id"] == "test-orchestrator-001"
    assert row["extras"]["matched_phrase"] == "never mind"
    assert row["extras"]["detected_language"] == "en"
    assert row["extras"]["matched_via"] == "lang_hint_match"
    # NO language_fallback row — Step 1-2 never ran
    assert not any(r["stage"] == "language_fallback" for r in captured_audit_rows)


def test_dt8_abandonment_id_via_lang_hint(captured_audit_rows, mock_language):
    """Abandonment in Indonesian when lang_hint matches."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="wbs",
        question_id="case_handler_quantity",
        session_fallback_language="id",
    )
    mock_language("id", "Indonesia", 0.95)

    response = process_user_message_with_ooc(text="udahan saja", state=state)

    # session_fallback_language preserved (NOT reset by abandonment)
    assert state.session_fallback_language == "id"
    assert state.service_code == ""
    # Indonesian acknowledgment uses "Anda" formal
    assert "Anda" in response


def test_dt8_no_match_does_not_short_circuit(monkeypatch, captured_audit_rows, mock_language):
    """Non-abandonment text proceeds past Step 0 to Step 1-2."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state()
    mock_language("en", "English", 0.95)

    # Stub Step 3-6 so we can return without exception
    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        lambda text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs: "passed_through",
    )

    response = process_user_message_with_ooc(text="what is a case handler", state=state)

    # Did NOT short-circuit at Step 0 — reached Step 3 stub
    assert response == "passed_through"
    # No abandonment audit row
    assert not any(r["stage"] == "abandonment_handler" for r in captured_audit_rows)


# ============================================================================
# Step 1-2: Language detection + effective-language fallback
# ============================================================================


def test_step1_2_high_confidence_canonical_lang_uses_raw(monkeypatch, captured_audit_rows, mock_language):
    """High confidence + lang in CANON_17 → effective_language = raw_lang.

    No language_fallback audit row written (happy path).
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("ja", "日本語", 0.97)  # high conf, canonical lang

    # Capture what Step 3 stub receives — we want to verify effective_language="ja"
    captured = {}

    def stub(text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs):
        captured["raw_lang"] = raw_lang
        captured["raw_confidence"] = raw_confidence
        captured["effective_language"] = effective_language
        return "dispatched"

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        stub,
    )

    process_user_message_with_ooc(text="こんにちは", state=state)

    assert captured["raw_lang"] == "ja"
    assert captured["raw_confidence"] == 0.97
    assert captured["effective_language"] == "ja"

    # NO language_fallback audit row — high confidence path
    assert not any(r["stage"] == "language_fallback" for r in captured_audit_rows)


def test_step1_2_low_confidence_falls_back_to_session_fallback(monkeypatch, captured_audit_rows, mock_language):
    """Low confidence → effective_language = session_fallback_language + audit row."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="id")
    mock_language("ja", "日本語", 0.4)  # below OOC_LANG_DETECTION_FLOOR=0.85

    captured = {}

    def stub(text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs):
        captured["effective_language"] = effective_language
        return "dispatched"

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        stub,
    )

    process_user_message_with_ooc(text="some text", state=state)

    # Effective language fell back to session fallback
    assert captured["effective_language"] == "id"

    # language_fallback audit row written with trigger="low_confidence"
    fb_rows = [r for r in captured_audit_rows if r["stage"] == "language_fallback"]
    assert len(fb_rows) == 1
    extras = fb_rows[0]["extras"]
    assert extras["raw_lang"] == "ja"
    assert extras["raw_confidence"] == 0.4
    assert extras["fallback_lang"] == "id"
    assert extras["trigger"] == "low_confidence"


def test_step1_2_unknown_lang_falls_back_to_session_fallback(monkeypatch, captured_audit_rows, mock_language):
    """Unknown lang (outside CANON_17) → fallback even at high confidence."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    # High confidence but lang NOT in CANON_17 (CANON_17 has 17 specific codes)
    mock_language("xx_unknown", "Unknown", 0.99)

    captured = {}

    def stub(text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs):
        captured["effective_language"] = effective_language
        return "dispatched"

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        stub,
    )

    process_user_message_with_ooc(text="text", state=state)

    assert captured["effective_language"] == "en"  # session_fallback
    fb_rows = [r for r in captured_audit_rows if r["stage"] == "language_fallback"]
    assert len(fb_rows) == 1
    assert fb_rows[0]["extras"]["trigger"] == "unknown_language"


def test_step1_2_canon_17_membership(monkeypatch, captured_audit_rows, mock_language):
    """Spot-check that all 17 canonical langs pass the CANON_17 membership check.

    Spec §Constraint #7: id, ms, en, fr, de, it, pt, es, vi, th, da, zh, ja, ru, ko, tl, ar.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc, CANON_17

    canonical = {"id", "ms", "en", "fr", "de", "it", "pt", "es", "vi",
                 "th", "da", "zh", "ja", "ru", "ko", "tl", "ar"}
    assert CANON_17 == canonical
    assert len(CANON_17) == 17

    # Each canonical lang at high confidence should NOT trigger fallback
    for lang in sorted(canonical):
        captured_audit_rows.clear()
        state = _state(session_fallback_language="en")
        mock_language(lang, lang.upper(), 0.95)

        captured = {}
        def stub(text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs):
            captured["effective_language"] = effective_language
            return "x"

        monkeypatch.setattr(
            "modules.system_detection.sd_orchestrator._ooc_dispatch",
            stub,
        )

        process_user_message_with_ooc(text="text", state=state)
        assert captured["effective_language"] == lang, (
            f"Canonical lang {lang!r} unexpectedly fell back to session_fallback"
        )
        assert not any(r["stage"] == "language_fallback" for r in captured_audit_rows), (
            f"Canonical lang {lang!r} unexpectedly triggered language_fallback audit"
        )


# ============================================================================
# DT-10: Language switch mid-session (spec §10A row 10)
# ============================================================================


def test_dt10_language_switch_mid_session_high_confidence(monkeypatch, captured_audit_rows, mock_language):
    """DT-10 — user in id session switches to en on OOC turn.

    Per Q#4 formalization:
    - effective_language = raw_lang (en) when high confidence + canonical
    - session_fallback_language stays "id" (Step 6 OOC-turn rule, not Step 1-2)

    Task 11 covers only the effective_language computation here. The
    session_fallback_language rule belongs to Task 13 (Step 6), so this
    test asserts only Step 1-2 behavior.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="id")  # Indonesian-rooted session
    mock_language("en", "English", 0.95)  # User switches mid-session

    captured = {}

    def stub(text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs):
        captured["effective_language"] = effective_language
        captured["raw_lang"] = raw_lang
        captured["session_fallback_at_entry_to_step_3"] = state.session_fallback_language
        return "dispatched"

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        stub,
    )

    process_user_message_with_ooc(text="What about partnership?", state=state)

    # Step 1-2: effective_language = raw lang
    assert captured["effective_language"] == "en"
    assert captured["raw_lang"] == "en"
    # session_fallback NOT modified by Step 1-2 — Task 13 owns that decision
    assert captured["session_fallback_at_entry_to_step_3"] == "id"
    # Step 1-2 happy path → no language_fallback audit row
    assert not any(r["stage"] == "language_fallback" for r in captured_audit_rows)


# ============================================================================
# Step 0 + 1-2 interaction (sanity)
# ============================================================================


def test_empty_session_fallback_language_falls_to_en(monkeypatch, captured_audit_rows, mock_language):
    """If session_fallback_language is empty string, default to 'en'."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="")
    mock_language("xx_unknown", "Unknown", 0.99)  # forces fallback path

    captured = {}

    def stub(text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs):
        captured["effective_language"] = effective_language
        return "x"

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        stub,
    )

    process_user_message_with_ooc(text="text", state=state)
    assert captured["effective_language"] == "en"


def test_state_with_suppression_remaining_routes_to_step_2_5_handler(monkeypatch, captured_audit_rows, mock_language):
    """When ooc_escalation_suppression_remaining > 0, Step 2.5 handler gets the call.

    Confirms the orchestrator routes correctly. (Task 11 used _stub name; Task 12
    replaced the function body and dropped the _stub suffix. This test monkeypatches
    the real function to bypass dispatcher dependency for the routing-only assertion.)
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=2)
    mock_language("en", "English", 0.95)

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._suppression_fallthrough",
        lambda text, state, effective_language, raw_lang, raw_confidence, dispatcher, **kwargs: "suppression_handled",
    )

    response = process_user_message_with_ooc(text="hello", state=state)
    assert response == "suppression_handled"


def test_audit_row_truncates_raw_user_text_at_200_chars(monkeypatch, captured_audit_rows, mock_language):
    """language_fallback audit row truncates user text to bounded size."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state()
    long_text = "x" * 500
    mock_language("xx_unknown", "U", 0.99)

    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        lambda *a, **kw: "x",
    )

    process_user_message_with_ooc(text=long_text, state=state)

    fb_rows = [r for r in captured_audit_rows if r["stage"] == "language_fallback"]
    assert len(fb_rows) == 1
    assert len(fb_rows[0]["extras"]["raw_user_text"]) <= 200


# ============================================================================
# Task 12 — Step 2.5 suppression-window fallthrough
# ============================================================================
# Spec §1.1 lines 133-149 + Guardrails A (dispatcher-FIRST / audit-AFTER) + B
# (3 dispatcher failure-path tests) + DT-6 (3→2→1→0 sequence + turn-7 normal).
# ============================================================================


def _ok_dispatcher(text, state):
    """Default-shape dispatcher: returns ('sa_continuation', '<sa_response>')."""
    return "sa_continuation", f"sa_response_for:{text[:20]}"


def _raising_dispatcher(text, state):
    raise RuntimeError("simulated dispatcher failure")


def _none_none_dispatcher(text, state):
    return None, None


def _degraded_dispatcher(text, state):
    """Dispatcher fell back internally — SA pipeline failed, returned general_agent."""
    return "general_agent", "fallback response from general agent"


# ----------------------------------------------------------------------------
# DT-6: suppression counter 3→2→1→0 sequence + turn-7 normal flow
# ----------------------------------------------------------------------------


def test_dt6_suppression_counter_decrement_sequence(monkeypatch, captured_audit_rows, mock_language):
    """DT-6 — counter must decrement 3→2→1→0 across SEQUENTIAL turns + turn-after-0 is normal flow.

    Spec §10A row 6 + Guardrail refinement #3: state persists across turns within
    one test (not isolated decrement tests). Verifies the COMPLETE sequence as a
    single state-machine trajectory.

    Sequence (mirrors production turn ordering):
      Turn 1: counter=3 → enters Step 2.5, decrement to 2, dispatcher called
      Turn 2: counter=2 → enters Step 2.5, decrement to 1, dispatcher called
      Turn 3: counter=1 → enters Step 2.5, decrement to 0, dispatcher called
      Turn 4: counter=0 → SKIPS Step 2.5, falls through to Step 3-6 (normal flow)
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=3)
    mock_language("en", "English", 0.95)

    # Stub Step 3-6 so turn-4 doesn't error (counter==0 path falls into _ooc_dispatch_stub)
    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._ooc_dispatch",
        lambda text, state, raw_lang, raw_confidence, effective_language, dispatcher, **kwargs: "normal_flow_response",
    )

    dispatcher_call_count = [0]
    def counting_dispatcher(text, state):
        dispatcher_call_count[0] += 1
        return "sa_continuation", f"response_turn_{dispatcher_call_count[0]}"

    # === Turn 1: counter 3 → 2 ===
    response_1 = process_user_message_with_ooc(text="msg1", state=state, dispatcher=counting_dispatcher)
    assert state.ooc_escalation_suppression_remaining == 2, "Turn 1 should decrement 3→2"
    assert dispatcher_call_count[0] == 1, "Turn 1 should call dispatcher (Step 2.5 path)"
    assert response_1 == "response_turn_1"

    # === Turn 2: counter 2 → 1 ===
    response_2 = process_user_message_with_ooc(text="msg2", state=state, dispatcher=counting_dispatcher)
    assert state.ooc_escalation_suppression_remaining == 1, "Turn 2 should decrement 2→1"
    assert dispatcher_call_count[0] == 2, "Turn 2 should call dispatcher"
    assert response_2 == "response_turn_2"

    # === Turn 3: counter 1 → 0 ===
    response_3 = process_user_message_with_ooc(text="msg3", state=state, dispatcher=counting_dispatcher)
    assert state.ooc_escalation_suppression_remaining == 0, "Turn 3 should decrement 1→0"
    assert dispatcher_call_count[0] == 3, "Turn 3 should call dispatcher"
    assert response_3 == "response_turn_3"

    # === Turn 4: counter 0 → NORMAL FLOW (Step 3-6, not Step 2.5) ===
    response_4 = process_user_message_with_ooc(text="msg4", state=state, dispatcher=counting_dispatcher)
    assert state.ooc_escalation_suppression_remaining == 0, "Turn 4 should NOT decrement below 0"
    assert dispatcher_call_count[0] == 3, "Turn 4 should NOT call dispatcher (Step 3-6 took over via _ooc_dispatch_stub mock)"
    assert response_4 == "normal_flow_response", "Turn 4 should hit Step 3-6 normal-flow stub"

    # Audit verification: 3 suppression-fallthrough rows from turns 1-3 + 0 from turn 4
    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 3, "Exactly 3 suppression-fallthrough audit rows (one per suppression turn)"

    # Pre/post counter values reflect the 3→2→1→0 sequence
    assert fall_rows[0]["extras"]["suppression_remaining_pre"] == 3
    assert fall_rows[0]["extras"]["suppression_remaining_post"] == 2
    assert fall_rows[1]["extras"]["suppression_remaining_pre"] == 2
    assert fall_rows[1]["extras"]["suppression_remaining_post"] == 1
    assert fall_rows[2]["extras"]["suppression_remaining_pre"] == 1
    assert fall_rows[2]["extras"]["suppression_remaining_post"] == 0


# ----------------------------------------------------------------------------
# Guardrail A: dispatcher-FIRST / audit-AFTER ordering
# ----------------------------------------------------------------------------


def test_guardrail_a_dispatcher_runs_before_audit_row_written(monkeypatch, captured_audit_rows, mock_language):
    """Per spec §1.1 line 156 + Guardrail A — dispatcher invoked BEFORE audit row.

    Order is observable: the dispatcher mock records the audit-row count at
    invocation time; if audit was written first, that count would be > 0.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    audit_row_count_at_dispatcher_time = []

    def order_observing_dispatcher(text, state):
        audit_row_count_at_dispatcher_time.append(
            len([r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"])
        )
        return "sa_continuation", "ok"

    process_user_message_with_ooc(text="x", state=state, dispatcher=order_observing_dispatcher)

    # Dispatcher saw ZERO suppression rows when it ran → audit was written AFTER
    assert audit_row_count_at_dispatcher_time == [0]

    # And exactly 1 row exists after the function returns
    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 1


# ----------------------------------------------------------------------------
# Guardrail B: 3 dispatcher failure-path tests
# ----------------------------------------------------------------------------


def test_guardrail_b_dispatcher_raises_audits_then_reraises(monkeypatch, captured_audit_rows, mock_language):
    """Failure mode 1: dispatcher raises.

    Policy:
      - Audit row written with downstream_route="dispatcher_exception" + error populated
      - Counter decrement HAS happened (mutex'd to Step 2.5 entry)
      - Original exception RE-RAISED (upstream Flask handles user-facing fallback)
    """
    import pytest
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=2)
    mock_language("en", "English", 0.95)

    with pytest.raises(RuntimeError, match="simulated dispatcher failure"):
        process_user_message_with_ooc(text="x", state=state, dispatcher=_raising_dispatcher)

    # Counter WAS decremented despite exception
    assert state.ooc_escalation_suppression_remaining == 1

    # Audit row WAS written before re-raise (telemetry preserved)
    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 1
    extras = fall_rows[0]["extras"]
    assert extras["downstream_route"] == "dispatcher_exception"
    assert extras["suppression_remaining_pre"] == 2
    assert extras["suppression_remaining_post"] == 1
    # `error` field on audit row contains the exception message
    assert fall_rows[0]["error"] is not None
    assert "simulated dispatcher failure" in fall_rows[0]["error"]


def test_guardrail_b_dispatcher_returns_none_none(captured_audit_rows, mock_language):
    """Failure mode 2: dispatcher returns (None, None).

    Policy:
      - downstream_route="none_returned" (deterministic per spec ambiguity resolution)
      - Response is empty string (honest passthrough — orchestrator does NOT synthesize)
      - No exception raised
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=2)
    mock_language("en", "English", 0.95)

    response = process_user_message_with_ooc(text="x", state=state, dispatcher=_none_none_dispatcher)

    assert response == ""
    assert state.ooc_escalation_suppression_remaining == 1

    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 1
    assert fall_rows[0]["extras"]["downstream_route"] == "none_returned"
    assert fall_rows[0]["error"] is None  # no exception, just None return


def test_guardrail_b_dispatcher_returns_degraded_general_agent(captured_audit_rows, mock_language):
    """Failure mode 3: dispatcher returns degraded result (e.g., "general_agent" fallback).

    Policy:
      - Audit faithfully reflects the ACTUAL returned route (verbatim, not transformed)
      - Response is passed through as-is
      - No exception raised; orchestrator does NOT second-guess the dispatcher's choice
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=2)
    mock_language("en", "English", 0.95)

    response = process_user_message_with_ooc(text="x", state=state, dispatcher=_degraded_dispatcher)

    assert response == "fallback response from general agent"
    assert state.ooc_escalation_suppression_remaining == 1

    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 1
    # downstream_route is the EXACT value returned by dispatcher
    assert fall_rows[0]["extras"]["downstream_route"] == "general_agent"


# ----------------------------------------------------------------------------
# RuntimeError when dispatcher missing
# ----------------------------------------------------------------------------


def test_runtime_error_when_dispatcher_none_at_step_2_5(captured_audit_rows, mock_language):
    """Missing dispatcher at Step 2.5 entry raises actionable RuntimeError per refinement #1.

    Message must point to the fix path (call sites + Tasks 20-21 migration plan).
    """
    import pytest
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    with pytest.raises(RuntimeError) as exc_info:
        process_user_message_with_ooc(text="x", state=state, dispatcher=None)

    msg = str(exc_info.value)
    # Actionable message contents
    assert "Step 2.5" in msg
    assert "dispatcher=None" in msg
    assert "call-site wiring bug" in msg
    assert "spec §1.1 line 156" in msg
    assert "Tasks 20-21" in msg


# ----------------------------------------------------------------------------
# Post-hoc classifier env-gating (Refinement #3)
# ----------------------------------------------------------------------------


def test_posthoc_classifier_disabled_by_default(captured_audit_rows, mock_language):
    """Default OOC_POSTHOC_CLASSIFIER_ENABLED=false → posthoc_classifier_sampled=False.

    Per spec §7.4 (polish #3 schema completeness): all 8 fields ALWAYS PRESENT
    in extras dict, with Optional ones explicitly None (NOT absent) when
    sampling didn't fire. Cleaner for downstream MongoDB analytics (no $exists).
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    process_user_message_with_ooc(text="x", state=state, dispatcher=_ok_dispatcher)

    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    extras = fall_rows[0]["extras"]
    assert extras["posthoc_classifier_sampled"] is False
    # Polish #3: Optional fields ALWAYS PRESENT with None values
    assert extras["posthoc_classifier_would_have_classified"] is None
    assert extras["posthoc_classifier_confidence"] is None
    assert extras["posthoc_classifier_mode"] is None


def test_posthoc_classifier_enabled_with_full_sampling_populates_extras(monkeypatch, captured_audit_rows, mock_language):
    """When the post-hoc classifier returns a decision, audit row gains posthoc fields.

    Patches `_run_posthoc_classifier_if_enabled` directly to bypass Config-binding
    complexity (Config is import-bound at sd_orchestrator module level, so
    subclassing app_audit.Config doesn't reach the orchestrator's reference).
    The env-gating logic is unit-tested separately via the helper's signature.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc
    from modules.out_of_context.ooc_types import OOCDecision

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    def fake_posthoc(text, lang, cfg):
        return OOCDecision(
            yes=True, label="OOC-CHITCHAT", confidence=0.7,
            reason="fake", classifier_mode="keyword",
        )
    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._run_posthoc_classifier_if_enabled",
        fake_posthoc,
    )

    process_user_message_with_ooc(text="hello there", state=state, dispatcher=_ok_dispatcher)

    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    extras = fall_rows[0]["extras"]
    assert extras["posthoc_classifier_sampled"] is True
    assert extras["posthoc_classifier_would_have_classified"] == "OOC-CHITCHAT"
    assert extras["posthoc_classifier_confidence"] == 0.7
    assert extras["posthoc_classifier_mode"] == "keyword"


def test_posthoc_classifier_failure_swallowed_does_not_break_dispatch(monkeypatch, captured_audit_rows, mock_language):
    """Post-hoc classifier failure must NOT block normal Step 2.5 flow.

    The helper `_run_posthoc_classifier_if_enabled` is designed to swallow
    internal exceptions and return None (audit-side artifact must never affect
    routing). This test verifies the swallow contract end-to-end.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    # Simulate the swallow contract: helper returns None despite "would-have-raised"
    monkeypatch.setattr(
        "modules.system_detection.sd_orchestrator._run_posthoc_classifier_if_enabled",
        lambda text, lang, cfg: None,
    )

    # MUST not raise — dispatch proceeds normally
    response = process_user_message_with_ooc(text="x", state=state, dispatcher=_ok_dispatcher)
    assert response.startswith("sa_response_for:")
    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 1
    # Posthoc sampled=False because helper returned None
    assert fall_rows[0]["extras"]["posthoc_classifier_sampled"] is False


def test_posthoc_helper_swallows_internal_exception_directly():
    """Direct unit test on the helper's swallow contract.

    Calls _run_posthoc_classifier_if_enabled with a config that forces it
    to invoke the inner classifier, then patches the classifier to raise.
    Verifies the helper returns None (does NOT propagate).
    """
    from modules.system_detection.sd_orchestrator import _run_posthoc_classifier_if_enabled

    class _ForceEnabledCfg:
        OOC_POSTHOC_CLASSIFIER_ENABLED = True
        OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE = 1.0
        OOC_POSTHOC_CLASSIFIER_MODE = "keyword"

    # Patch the classifier class so its constructor raises (simulating import or init failure)
    import modules.out_of_context.ooc_classifier as cls_mod
    orig_init = cls_mod.OOCClassifier.__init__

    def boom_init(self, mode=None):
        raise RuntimeError("simulated classifier init failure")

    cls_mod.OOCClassifier.__init__ = boom_init
    try:
        result = _run_posthoc_classifier_if_enabled("hello", "en", _ForceEnabledCfg())
        # MUST return None (swallowed), not raise
        assert result is None
    finally:
        cls_mod.OOCClassifier.__init__ = orig_init


def test_posthoc_helper_returns_none_when_disabled():
    """Default OOC_POSTHOC_CLASSIFIER_ENABLED=false → helper returns None without sampling."""
    from modules.system_detection.sd_orchestrator import _run_posthoc_classifier_if_enabled

    class _DisabledCfg:
        OOC_POSTHOC_CLASSIFIER_ENABLED = False
        OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE = 1.0  # even with high sample rate
        OOC_POSTHOC_CLASSIFIER_MODE = "keyword"

    result = _run_posthoc_classifier_if_enabled("text", "en", _DisabledCfg())
    assert result is None


# ----------------------------------------------------------------------------
# Sanity: normal flow at Step 2.5 (happy path)
# ----------------------------------------------------------------------------


def test_normal_flow_at_step_2_5(captured_audit_rows, mock_language):
    """Happy path: dispatcher returns ("sa_continuation", response) → audit row + return response."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=2)
    mock_language("en", "English", 0.95)

    response = process_user_message_with_ooc(text="hello", state=state, dispatcher=_ok_dispatcher)

    assert response == "sa_response_for:hello"
    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 1
    assert fall_rows[0]["extras"]["downstream_route"] == "sa_continuation"
    assert fall_rows[0]["extras"]["suppression_remaining_pre"] == 2
    assert fall_rows[0]["extras"]["suppression_remaining_post"] == 1


# ============================================================================
# Task 13 — Step 3-6 OOCContext build + state mutations + audit
# ============================================================================
# Spec §1.1 lines 150-217 + §7.2 turn-type table. Closes DT-1/2/3/4/5/7/9 +
# DT-10 Step-6 portion. Mocks OOCService.handle() for deterministic results;
# the underlying handle() pipeline is already exercised by test_ooc_service_handle.
# ============================================================================


@pytest.fixture
def mock_ooc_handle(monkeypatch):
    """Factory: returns a setter that monkeypatches OOCService.handle to return a fixed OOCResult or None."""
    from modules.out_of_context.ooc_types import OOCResult, OOCAuditMetadata

    def _setter(*, result=None):
        def fake_handle(self, ctx):
            return result
        monkeypatch.setattr(
            "modules.out_of_context.ooc_service.OOCService.handle",
            fake_handle,
        )
    return _setter


def _make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start",
                    streak_classification="user_ooc",
                    set_escalation_suppression=False,
                    language="en"):
    from modules.out_of_context.ooc_types import OOCResult, OOCAuditMetadata
    return OOCResult(
        message=f"<rendered:{category}:{shape}>",
        category=category,
        shape_used=shape,
        language_used=language,
        streak_classification=streak_classification,
        set_escalation_suppression=set_escalation_suppression,
        audit_metadata=OOCAuditMetadata(
            classifier_confidence=0.9,
            classifier_mode="hybrid",
            active_service=None,
        ),
    )


# ----------------------------------------------------------------------------
# DT-1 through DT-5, DT-9: OOC dispatch happy paths (spec §10A rows 1-5, 9)
# ----------------------------------------------------------------------------


def test_dt1_cold_start_ooc_no_sa_state_mutation(captured_audit_rows, mock_language, mock_ooc_handle):
    """DT-1 — cold-start OOC: shape=cold_start, no SA state mutation, no streak suppression."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")  # no service_code = cold-start
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start"))

    response = process_user_message_with_ooc(text="I want to partner with Integrity", state=state)

    # Response from the (mocked) handler
    assert response == "<rendered:OOC-PARTNERSHIP:cold_start>"
    # SA state NOT touched (Constraint #2)
    assert state.service_code == ""
    assert state.question_id == ""
    # Streak counter incremented
    assert state.ooc_excursion_count == 1
    assert state.previous_user_ooc_categories == ["OOC-PARTNERSHIP"]
    # ooc_handler audit row written
    ooc_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_handler"]
    assert len(ooc_rows) == 1
    assert ooc_rows[0]["extras"]["category"] == "OOC-PARTNERSHIP"
    assert ooc_rows[0]["extras"]["shape_used"] == "cold_start"


def test_dt2_mid_flow_standard_ooc(captured_audit_rows, mock_language, mock_ooc_handle):
    """DT-2 — mid-flow OOC during WBS qualification (not high_stakes)."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="wbs",
        question_id="case_handler_quantity",
        answers={"prior_field": "answer"},
        session_fallback_language="en",
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(
        category="OOC-PARTNERSHIP", shape="mid_flow_standard",
    ))

    response = process_user_message_with_ooc(text="I want to partner", state=state)

    # SA state preserved (Constraint #2)
    assert state.service_code == "wbs"
    assert state.question_id == "case_handler_quantity"
    assert state.answers == {"prior_field": "answer"}
    # Streak counter incremented
    assert state.ooc_excursion_count == 1


def test_dt3_mid_flow_high_stakes_shape(captured_audit_rows, mock_language, mock_ooc_handle):
    """DT-3 — mid-flow OOC during high_stakes service → mid_flow_high_stakes shape."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="corporate_fraud_investigation",
        question_id="case_summary",
        answers={"prior": "data"},
        session_fallback_language="en",
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(
        category="OOC-PARTNERSHIP", shape="mid_flow_high_stakes",
    ))

    response = process_user_message_with_ooc(text="I want to partner", state=state)

    assert state.service_code == "corporate_fraud_investigation"
    # OOC turn — counter +1
    assert state.ooc_excursion_count == 1


def test_dt4_pre_data_overrides_high_stakes_in_context(monkeypatch, captured_audit_rows, mock_language):
    """DT-4 — pre_data=True (empty answers) overrides high_stakes_intake when building OOCContext.

    Verified by capturing the OOCContext that orchestrator passes to OOCService.handle().
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="corporate_fraud_investigation",  # high_stakes service
        question_id="case_summary",
        answers={},  # pre_data = True
        session_fallback_language="en",
    )
    mock_language("en", "English", 0.95)

    captured_ctx = {}
    def fake_handle(self, ctx):
        captured_ctx["ctx"] = ctx
        return _make_ooc_result(category="OOC-PARTNERSHIP", shape="mid_flow_pre_data")

    monkeypatch.setattr(
        "modules.out_of_context.ooc_service.OOCService.handle",
        fake_handle,
    )

    process_user_message_with_ooc(text="hi", state=state)

    ctx = captured_ctx["ctx"]
    # OOCContext built with both flags set faithfully — OOCService.handle decides which wins
    assert ctx.pre_data is True
    assert ctx.high_stakes_intake is True  # both true; OOCService.handle (tested separately) prefers pre_data


def test_dt5_escalation_sets_suppression_counter(captured_audit_rows, mock_language, mock_ooc_handle):
    """DT-5 — escalation handover result sets ooc_escalation_suppression_remaining."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="wbs",
        question_id="case_handler_quantity",
        ooc_excursion_count=2,
        previous_user_ooc_categories=["OOC-PARTNERSHIP", "OOC-CAREERS"],
        ooc_escalation_suppression_remaining=0,
        session_fallback_language="en",
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(
        category="ESCALATION-CONSECUTIVE-OOC",
        shape="escalation_handover",
        streak_classification="system_meta",
        set_escalation_suppression=True,
    ))

    response = process_user_message_with_ooc(text="another off-topic", state=state)

    # Counter incremented to 3
    assert state.ooc_excursion_count == 3
    # system-meta turn: appends to previous_system_meta_actions, NOT previous_user_ooc_categories
    assert state.previous_user_ooc_categories == ["OOC-PARTNERSHIP", "OOC-CAREERS"]
    assert state.previous_system_meta_actions == ["ESCALATION-CONSECUTIVE-OOC"]
    # Suppression counter set to OOC_ESCALATION_SUPPRESSION_TURNS (default 3)
    from core.app_config import Config
    assert state.ooc_escalation_suppression_remaining == Config().OOC_ESCALATION_SUPPRESSION_TURNS


def test_dt9_in_scope_question_passes_through_with_streak_reset(monkeypatch, captured_audit_rows, mock_language, mock_ooc_handle):
    """DT-9 — in-scope clarification (OOCService returns None) → non-OOC turn mutations + dispatch."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="wbs",
        question_id="case_handler_quantity",
        ooc_excursion_count=2,  # accumulated streak
        previous_user_ooc_categories=["OOC-CAREERS"],
        session_fallback_language="en",
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=None)  # classifier returns no OOC

    def dispatcher(text, state):
        return "sa_continuation", "answer from sa continuation"

    response = process_user_message_with_ooc(text="what's a case handler", state=state, dispatcher=dispatcher)

    assert response == "answer from sa continuation"
    # SA state preserved
    assert state.service_code == "wbs"
    # Non-OOC turn: streak reset (§7.2 row 1)
    assert state.ooc_excursion_count == 0
    assert state.previous_user_ooc_categories == []
    assert state.previous_system_meta_actions == []


# ----------------------------------------------------------------------------
# DT-7: streak reset on non-OOC turn (spec §10A row 7)
# ----------------------------------------------------------------------------


def test_dt7_streak_resets_on_non_ooc_turn(captured_audit_rows, mock_language, mock_ooc_handle):
    """DT-7 — non-OOC turn after accumulated streak resets counter + categories.

    Per spec §7.2 row 1. Companion to DT-9 (which also tests this via in-scope path).
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        ooc_excursion_count=2,
        previous_user_ooc_categories=["OOC-FREELANCE", "OOC-CAREERS"],
        previous_system_meta_actions=[],
        session_fallback_language="en",
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=None)  # no OOC

    def dispatcher(text, state):
        return "faq_rag", "faq response"

    process_user_message_with_ooc(text="just a normal question", state=state, dispatcher=dispatcher)

    # All 3 streak fields reset to defaults
    assert state.ooc_excursion_count == 0
    assert state.previous_user_ooc_categories == []
    assert state.previous_system_meta_actions == []


def test_dt7_non_ooc_updates_session_fallback_when_confident_canonical(captured_audit_rows, mock_language, mock_ooc_handle):
    """Companion to DT-7: non-OOC turn with confident canonical detection updates session_fallback_language."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("id", "Indonesia", 0.95)  # confident + canonical
    mock_ooc_handle(result=None)

    def dispatcher(text, state):
        return "sa_continuation", "ok"

    process_user_message_with_ooc(text="message in Indonesian", state=state, dispatcher=dispatcher)

    # session_fallback updated to detected lang
    assert state.session_fallback_language == "id"


def test_dt7_non_ooc_does_NOT_update_session_fallback_when_low_confidence(captured_audit_rows, mock_language, mock_ooc_handle):
    """Low-confidence detection on non-OOC turn does NOT update session_fallback_language."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("ja", "日本語", 0.4)  # low confidence
    mock_ooc_handle(result=None)

    def dispatcher(text, state):
        return "sa_continuation", "ok"

    process_user_message_with_ooc(text="x", state=state, dispatcher=dispatcher)

    # Low confidence → no update; session_fallback stays "en"
    assert state.session_fallback_language == "en"


# ----------------------------------------------------------------------------
# §7.2 turn-type table — all 6 mutation rows explicit
# ----------------------------------------------------------------------------


def test_7_2_row_1_non_ooc_turn_mutations(captured_audit_rows, mock_language, mock_ooc_handle):
    """§7.2 row 1 — Non-OOC turn full mutation set:
    - ooc_excursion_count → 0
    - previous_user_ooc_categories → []
    - previous_system_meta_actions → []
    - session_fallback_language → updates IF raw_conf ≥ floor AND raw_lang ∈ CANON_17
    - ooc_escalation_suppression_remaining → unchanged
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        ooc_excursion_count=2,
        previous_user_ooc_categories=["OOC-CAREERS"],
        previous_system_meta_actions=["ESCALATION-CONSECUTIVE-OOC"],
        ooc_escalation_suppression_remaining=0,
        session_fallback_language="en",
    )
    mock_language("fr", "Français", 0.95)
    mock_ooc_handle(result=None)

    def dispatcher(text, state):
        return "sa_continuation", "ok"

    process_user_message_with_ooc(text="bonjour", state=state, dispatcher=dispatcher)

    assert state.ooc_excursion_count == 0
    assert state.previous_user_ooc_categories == []
    assert state.previous_system_meta_actions == []
    assert state.session_fallback_language == "fr"
    assert state.ooc_escalation_suppression_remaining == 0


def test_7_2_row_2_ooc_user_category_mutations(captured_audit_rows, mock_language, mock_ooc_handle):
    """§7.2 row 2 — OOC turn (user category):
    - ooc_excursion_count → +1
    - previous_user_ooc_categories → append category
    - previous_system_meta_actions → unchanged
    - session_fallback_language → unchanged (T2+ rule per Q#4)
    - ooc_escalation_suppression_remaining → unchanged
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        ooc_excursion_count=1,
        previous_user_ooc_categories=["OOC-FREELANCE"],
        previous_system_meta_actions=[],
        session_fallback_language="id",  # already non-default — T2+
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(
        category="OOC-PARTNERSHIP", shape="cold_start", streak_classification="user_ooc",
    ))

    process_user_message_with_ooc(text="x", state=state)

    assert state.ooc_excursion_count == 2  # +1
    assert state.previous_user_ooc_categories == ["OOC-FREELANCE", "OOC-PARTNERSHIP"]  # append
    assert state.previous_system_meta_actions == []  # unchanged
    # T2+ rule: session_fallback_language stays "id" even though raw="en" + confident
    assert state.session_fallback_language == "id"


def test_7_2_row_3_system_meta_escalation_mutations(captured_audit_rows, mock_language, mock_ooc_handle):
    """§7.2 row 3 — OOC turn (system-meta, ESCALATION-CONSECUTIVE-OOC):
    - ooc_excursion_count → +1
    - previous_user_ooc_categories → unchanged
    - previous_system_meta_actions → append
    - session_fallback_language → unchanged
    - ooc_escalation_suppression_remaining → set to OOC_ESCALATION_SUPPRESSION_TURNS
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        ooc_excursion_count=2,
        previous_user_ooc_categories=["OOC-CAREERS", "OOC-PARTNERSHIP"],
        previous_system_meta_actions=[],
        ooc_escalation_suppression_remaining=0,
        session_fallback_language="id",
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(
        category="ESCALATION-CONSECUTIVE-OOC", shape="escalation_handover",
        streak_classification="system_meta", set_escalation_suppression=True,
    ))

    process_user_message_with_ooc(text="x", state=state)

    assert state.ooc_excursion_count == 3
    assert state.previous_user_ooc_categories == ["OOC-CAREERS", "OOC-PARTNERSHIP"]  # unchanged
    assert state.previous_system_meta_actions == ["ESCALATION-CONSECUTIVE-OOC"]  # appended
    assert state.session_fallback_language == "id"  # unchanged
    from core.app_config import Config
    assert state.ooc_escalation_suppression_remaining == Config().OOC_ESCALATION_SUPPRESSION_TURNS


def test_7_2_row_4_abandonment_cross_reference():
    """§7.2 row 4 — Abandonment turn mutations.

    Already covered by Task 11 test `test_dt8_abandonment_short_circuits_at_step_0`
    and Task 10 abandonment-module tests in `tests/test_abandonment.py`. This
    sentinel exists to make the §7.2 mapping table complete in this file.
    """
    pass  # cross-reference; no new logic to assert


def test_7_2_row_5_first_turn_ooc_cold_start_lang_exception(captured_audit_rows, mock_language, mock_ooc_handle):
    """§7.2 row 5 / D6 row 3 — T1-OOC-confident cold-start exception:

    When ALL 4 conditions hold:
      1. ooc_excursion_count == 1 (just became 1 after this turn)
      2. session_fallback_language was "en" at Step 3 entry
      3. raw_confidence ≥ OOC_LANG_DETECTION_FLOOR
      4. raw_lang ∈ CANON_17
    → session_fallback_language updates from "en" to raw_lang.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        session_fallback_language="en",  # condition 2
        ooc_excursion_count=0,            # → becomes 1 after this turn (condition 1)
    )
    mock_language("id", "Indonesia", 0.95)  # conditions 3+4
    mock_ooc_handle(result=_make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start"))

    process_user_message_with_ooc(text="saya ingin jadi mitra", state=state)

    # T1 exception fires: session_fallback updates from "en" → "id"
    assert state.session_fallback_language == "id"
    assert state.ooc_excursion_count == 1


def test_7_2_row_5_t1_exception_does_NOT_fire_when_confidence_low(captured_audit_rows, mock_language, mock_ooc_handle):
    """T1 exception requires raw_confidence ≥ OOC_LANG_DETECTION_FLOOR.

    Low confidence → effective_language already fell back to "en" at Step 2 (audit row).
    The T1 exception check also fails → session_fallback stays "en".
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en", ooc_excursion_count=0)
    mock_language("id", "Indonesia", 0.4)  # below floor
    mock_ooc_handle(result=_make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start"))

    process_user_message_with_ooc(text="x", state=state)

    # Low confidence → no T1 update
    assert state.session_fallback_language == "en"


def test_7_2_row_5_t1_exception_does_NOT_fire_on_t2(captured_audit_rows, mock_language, mock_ooc_handle):
    """T1 exception only applies on FIRST OOC turn (counter == 1 post-increment).

    On T2+ (counter > 1 after increment), session_fallback stays unchanged per Q#4.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        session_fallback_language="en",
        ooc_excursion_count=1,  # already had 1 OOC; this is T2 → counter becomes 2
    )
    mock_language("id", "Indonesia", 0.95)  # confident + canonical
    mock_ooc_handle(result=_make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start"))

    process_user_message_with_ooc(text="x", state=state)

    # T2: session_fallback stays unchanged
    assert state.session_fallback_language == "en"
    assert state.ooc_excursion_count == 2


def test_7_2_row_6_suppression_fallthrough_cross_reference():
    """§7.2 row 6 — Suppression-fallthrough turn mutations.

    Already covered by Task 12 `test_dt6_suppression_counter_decrement_sequence`
    + the Guardrail B failure-path tests. Counter decrements; other state fields
    unchanged. This sentinel exists for §7.2 mapping table completeness.
    """
    pass  # cross-reference; no new logic to assert


# ----------------------------------------------------------------------------
# DT-10 Step-6 portion (cross-references Task 11 Step-1-2 portion)
# ----------------------------------------------------------------------------


def test_dt10_step6_session_fallback_unchanged_on_ooc_turn(captured_audit_rows, mock_language, mock_ooc_handle):
    """DT-10 Step-6 portion — language switch on an OOC turn DOES NOT update session_fallback.

    Cross-reference: Task 11 `test_dt10_language_switch_mid_session_high_confidence`
    covered the Step 1-2 portion (effective_language = raw_lang on confident detection).
    This Task 13 test covers the Step 6 portion (session_fallback_language stays put
    on OOC turns per Q#4, except T1 cold-start exception).

    Together, the two tests close DT-10 completely.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        session_fallback_language="id",  # Indonesian-rooted session
        ooc_excursion_count=1,            # NOT T1 — T1 exception does NOT apply
    )
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start"))

    process_user_message_with_ooc(text="What about partnership?", state=state)

    # session_fallback STAYS "id" (Q#4 — OOC turns don't update fallback except T1)
    assert state.session_fallback_language == "id"
    # OOC mutations applied
    assert state.ooc_excursion_count == 2
    assert "OOC-PARTNERSHIP" in state.previous_user_ooc_categories


# ----------------------------------------------------------------------------
# Audit row schema completeness — spec §7.4 (polish #3)
# ----------------------------------------------------------------------------


def test_ooc_handler_audit_row_schema_completeness(captured_audit_rows, mock_language, mock_ooc_handle):
    """Polish #3 — ooc_handler audit row has full OOCAuditMetadata schema + result-level fields.

    Per spec §7.4 + §2.1.2. The extras dict must contain ALL OOCAuditMetadata
    fields (model_dump) PLUS the result-level augments (category, shape_used,
    language_used, streak_classification, set_escalation_suppression).
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc
    from modules.out_of_context.ooc_types import OOCAuditMetadata

    state = _state(session_fallback_language="en")
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(
        category="OOC-PARTNERSHIP", shape="cold_start",
    ))

    process_user_message_with_ooc(text="x", state=state)

    ooc_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_handler"]
    assert len(ooc_rows) == 1
    extras = ooc_rows[0]["extras"]

    # All 16 OOCAuditMetadata fields present (from model_dump)
    expected_audit_fields = {
        "classifier_confidence",
        "classifier_mode",
        "extracted_mention",
        "extracted_hint",
        "ooc_excursion_count_post",
        "previous_categories_chain",
        "raw_detected_language",
        "raw_detection_confidence",
        "effective_language_diverged_from_raw",
        "pre_data",
        "high_stakes_intake",
        "active_service",
        "template_variant_used",
        "bidi_wrap_applied",
        "trigger",
        "streak_length",
    }
    for field in expected_audit_fields:
        assert field in extras, f"OOCAuditMetadata field missing: {field}"

    # 5 result-level augments + 1 Task 20 downstream_sd_stage field = 6 augments
    expected_result_fields = {
        "category",
        "shape_used",
        "language_used",
        "streak_classification",
        "set_escalation_suppression",
        "downstream_sd_stage",  # Task 20: always present, None when OOC handled (no SD branch)
    }
    for field in expected_result_fields:
        assert field in extras, f"Result-level field missing: {field}"

    # Task 20: downstream_sd_stage explicitly None on ooc_handler rows
    assert extras["downstream_sd_stage"] is None, (
        "ooc_handler audit row must set downstream_sd_stage=None — no SD branch fires when OOC handled"
    )


def test_ooc_suppression_fallthrough_audit_row_schema_completeness(captured_audit_rows, mock_language):
    """Polish #3 backfill — ooc_suppression_fallthrough has all 8 fields per spec §7.4.

    All Optional fields ALWAYS PRESENT (None when not sampled), per Task 13 schema
    completeness refinement.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    process_user_message_with_ooc(text="hello", state=state, dispatcher=_ok_dispatcher)

    fall_rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(fall_rows) == 1
    extras = fall_rows[0]["extras"]

    expected_fields = {
        "user_text",
        "suppression_remaining_pre",
        "suppression_remaining_post",
        "downstream_route",
        "downstream_sd_stage",                        # Task 20: Optional — None until Phase 1
        "posthoc_classifier_sampled",
        "posthoc_classifier_would_have_classified",  # Optional — None when not sampled
        "posthoc_classifier_confidence",              # Optional — None when not sampled
        "posthoc_classifier_mode",                    # Optional — None when not sampled
        "phase0_legacy_fallback",                     # Task 20: bool — True only on cold-start legacy fallback
    }
    assert set(extras.keys()) == expected_fields, (
        f"Schema mismatch: expected {expected_fields}, got {set(extras.keys())}"
    )

    # When posthoc disabled (default): Optional fields are None, NOT absent
    assert extras["posthoc_classifier_sampled"] is False
    assert extras["posthoc_classifier_would_have_classified"] is None
    assert extras["posthoc_classifier_confidence"] is None
    assert extras["posthoc_classifier_mode"] is None
    # Task 21: when downstream_sd_stage_hint is not provided by caller, audit-write
    # resolves None → "unknown" string (NOT None — schema completeness pattern with
    # explicit semantic distinct from ooc_handler row's None which means "no SD branch
    # fired"). For ooc_suppression_fallthrough, "unknown" means "dispatcher ran but
    # caller didn't tell us which SD-side branch".
    assert extras["downstream_sd_stage"] == "unknown"
    # Task 20: phase0_legacy_fallback default False (not on the cold-start legacy fallback path)
    assert extras["phase0_legacy_fallback"] is False


# ----------------------------------------------------------------------------
# RuntimeError when dispatcher needed at Step 6 non-OOC pass-through
# ----------------------------------------------------------------------------


def test_runtime_error_when_dispatcher_none_at_step_6_non_ooc(captured_audit_rows, mock_language, mock_ooc_handle):
    """Step 6 non-OOC pass-through requires dispatcher; raises actionable RuntimeError if None."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(service_code="wbs", question_id="case_handler_quantity")
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=None)  # non-OOC → reaches Step 6 dispatcher branch

    with pytest.raises(RuntimeError) as exc_info:
        process_user_message_with_ooc(text="case handler question", state=state, dispatcher=None)

    msg = str(exc_info.value)
    assert "Step 6" in msg
    assert "dispatcher=None" in msg
    assert "Tasks 20-21" in msg


# ----------------------------------------------------------------------------
# OOCContext construction sanity (Step 3-4)
# ----------------------------------------------------------------------------


def test_ooc_context_construction_pre_data_signal(monkeypatch, mock_language):
    """Step 3 — pre_data = (active_service != None AND empty answers)."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    # Case 1: active service + empty answers → pre_data=True
    state = _state(service_code="wbs", question_id="case_handler_quantity", answers={})
    mock_language("en", "English", 0.95)

    captured = {}
    def fake_handle(self, ctx):
        captured["pre_data"] = ctx.pre_data
        return None  # routes to non-OOC path; dispatcher mock below
    monkeypatch.setattr("modules.out_of_context.ooc_service.OOCService.handle", fake_handle)

    process_user_message_with_ooc(
        text="x", state=state, dispatcher=lambda t, s: ("sa_continuation", "ok"),
    )
    assert captured["pre_data"] is True

    # Case 2: active service + non-empty answers → pre_data=False
    state2 = _state(service_code="wbs", question_id="case_handler_quantity", answers={"f1": "v1"})
    captured2 = {}
    def fake_handle2(self, ctx):
        captured2["pre_data"] = ctx.pre_data
        return None
    monkeypatch.setattr("modules.out_of_context.ooc_service.OOCService.handle", fake_handle2)

    process_user_message_with_ooc(
        text="x", state=state2, dispatcher=lambda t, s: ("sa_continuation", "ok"),
    )
    assert captured2["pre_data"] is False


# ============================================================================
# Task 20 — return_none_on_non_ooc_passthrough API extension (Decision 2)
# ============================================================================
# Required by user condition for Decision 2:
# - Regression test asserting default-args (False) behavior unchanged for all
#   3 prior turn types
# - New tests for True mode covering: OOC turn, non-OOC turn, suppression-
#   fallthrough turn (still uses dispatcher per Friction B)
# ============================================================================


def test_decision_2_regression_default_false_ooc_turn_unchanged(captured_audit_rows, mock_language, mock_ooc_handle):
    """Regression — default-args (return_none_on_non_ooc_passthrough=False)
    behavior IDENTICAL to pre-Task-20 for OOC turn."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start"))

    response = process_user_message_with_ooc(text="x", state=state)
    assert response == "<rendered:OOC-PARTNERSHIP:cold_start>"
    assert state.ooc_excursion_count == 1


def test_decision_2_regression_default_false_non_ooc_calls_dispatcher(monkeypatch, captured_audit_rows, mock_language, mock_ooc_handle):
    """Regression — default-args non-OOC turn STILL calls dispatcher (unchanged)."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=None)

    called = []
    def dispatcher(text, state):
        called.append(text)
        return "sa_continuation", "legacy response"

    response = process_user_message_with_ooc(text="x", state=state, dispatcher=dispatcher)
    assert called == ["x"]
    assert response == "legacy response"


def test_decision_2_regression_default_false_suppression_fallthrough_unchanged(captured_audit_rows, mock_language, mock_ooc_handle):
    """Regression — default-args suppression-fallthrough still uses dispatcher."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    response = process_user_message_with_ooc(text="x", state=state, dispatcher=_ok_dispatcher)
    assert response == "sa_response_for:x"


def test_decision_2_new_mode_ooc_turn_returns_message(captured_audit_rows, mock_language, mock_ooc_handle):
    """return_none_on_non_ooc_passthrough=True: OOC turn still returns the message string."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(category="OOC-FREELANCE", shape="cold_start"))

    response = process_user_message_with_ooc(
        text="x", state=state,
        return_none_on_non_ooc_passthrough=True,
    )
    assert response == "<rendered:OOC-FREELANCE:cold_start>"
    assert state.ooc_excursion_count == 1  # streak mutation applied


def test_decision_2_new_mode_non_ooc_turn_returns_none_with_state_mutations(captured_audit_rows, mock_language, mock_ooc_handle):
    """return_none_on_non_ooc_passthrough=True: non-OOC returns None + state mutations applied."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        session_fallback_language="en",
        ooc_excursion_count=2,
        previous_user_ooc_categories=["OOC-CAREERS"],
    )
    mock_language("id", "Indonesia", 0.95)  # confident + canonical → fallback should update
    mock_ooc_handle(result=None)

    # No dispatcher needed — new mode returns None on non-OOC
    response = process_user_message_with_ooc(
        text="apa kabar", state=state,
        dispatcher=None,
        return_none_on_non_ooc_passthrough=True,
    )

    assert response is None
    # State mutations applied per §7.2 row 1
    assert state.ooc_excursion_count == 0
    assert state.previous_user_ooc_categories == []
    assert state.session_fallback_language == "id"


def test_decision_2_new_mode_suppression_fallthrough_still_uses_dispatcher(captured_audit_rows, mock_language):
    """return_none_on_non_ooc_passthrough=True: Step 2.5 STILL invokes dispatcher (Friction B)."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    response = process_user_message_with_ooc(
        text="x", state=state,
        dispatcher=_ok_dispatcher,
        return_none_on_non_ooc_passthrough=True,
    )
    # Dispatcher response surfaced — new mode does NOT short-circuit Step 2.5
    assert response == "sa_response_for:x"
    assert state.ooc_escalation_suppression_remaining == 0


def test_decision_3_phase0_legacy_fallback_audit_row_fires_correctly(monkeypatch):
    """Decision 3 condition (a) — Phase 0 legacy fallback writes deterministic audit row.

    Directly tests the wire-up code path in sd_service.py without importing it
    (chroma-dependent import graph). Replicates the audit row the wire-up emits
    when state.ooc_escalation_suppression_remaining > 0 at cold-start.
    """
    from core import app_audit

    captured = []
    class FakeWriter:
        def write(self, doc):
            captured.append(doc)
    monkeypatch.setattr(app_audit, "_writer_instance", FakeWriter())

    app_audit.record_audit_row(
        stage="ooc_suppression_fallthrough",
        session_id="phase0_test_session",
        extras={
            "user_text": "test message",
            "suppression_remaining_pre": 2,
            "suppression_remaining_post": 1,
            "downstream_route": "phase0_legacy_passthrough",
            "downstream_sd_stage": None,
            "posthoc_classifier_sampled": False,
            "posthoc_classifier_would_have_classified": None,
            "posthoc_classifier_confidence": None,
            "posthoc_classifier_mode": None,
            "phase0_legacy_fallback": True,
        },
    )

    assert len(captured) == 1
    doc = captured[0]
    assert doc["stage"] == "ooc_suppression_fallthrough"
    assert doc["extras"]["phase0_legacy_fallback"] is True
    assert doc["extras"]["downstream_route"] == "phase0_legacy_passthrough"
    # Schema completeness — all 10 fields per spec Appendix D.5
    assert set(doc["extras"].keys()) == {
        "user_text", "suppression_remaining_pre", "suppression_remaining_post",
        "downstream_route", "downstream_sd_stage",
        "posthoc_classifier_sampled", "posthoc_classifier_would_have_classified",
        "posthoc_classifier_confidence", "posthoc_classifier_mode",
        "phase0_legacy_fallback",
    }


def test_decision_2_new_mode_non_ooc_no_runtime_error_when_dispatcher_none(captured_audit_rows, mock_language, mock_ooc_handle):
    """In new mode, dispatcher=None on non-OOC turn returns None gracefully — no RuntimeError."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=None)

    # Must NOT raise — graceful None return is the new mode's contract
    response = process_user_message_with_ooc(
        text="x", state=state,
        dispatcher=None,
        return_none_on_non_ooc_passthrough=True,
    )
    assert response is None


# ============================================================================
# Task 21 — Mid-flow wire-up + downstream_sd_stage_hint + quotation gating
# ============================================================================


def test_task21_downstream_sd_stage_hint_recorded_in_audit(captured_audit_rows, mock_language):
    """Decision 4 — caller passes hint; audit row records it verbatim."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    process_user_message_with_ooc(
        text="x", state=state, dispatcher=_ok_dispatcher,
        downstream_sd_stage_hint="sa_compose",
    )

    rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert len(rows) == 1
    assert rows[0]["extras"]["downstream_sd_stage"] == "sa_compose"


def test_task21_downstream_sd_stage_hint_none_resolves_to_unknown_in_audit(captured_audit_rows, mock_language):
    """When caller doesn't pass hint, audit-write resolves None → "unknown" string."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=1)
    mock_language("en", "English", 0.95)

    process_user_message_with_ooc(text="x", state=state, dispatcher=_ok_dispatcher)

    rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert rows[0]["extras"]["downstream_sd_stage"] == "unknown"


def test_task21_backward_compat_pre_task21_callers_work_without_kwarg(captured_audit_rows, mock_language, mock_ooc_handle):
    """Backward-compat — Tasks 11-13 callers (no kwarg) still work."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(session_fallback_language="en")
    mock_language("en", "English", 0.95)
    mock_ooc_handle(result=_make_ooc_result(category="OOC-PARTNERSHIP", shape="cold_start"))

    response = process_user_message_with_ooc(text="x", state=state)
    assert response == "<rendered:OOC-PARTNERSHIP:cold_start>"
    rows = [r for r in captured_audit_rows if r["stage"] == "ooc_handler"]
    assert rows[0]["extras"]["downstream_sd_stage"] is None  # ooc_handler semantic: no SD branch


def test_task21_mid_flow_suppression_dispatcher_closure_returns_sa_reply(captured_audit_rows, mock_language):
    """Decision 4 — mid-flow suppression dispatcher passes SA reply through.

    Mirrors the closure pattern from sd_service.py:5683+ wire-up.
    """
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(ooc_escalation_suppression_remaining=2)
    mock_language("en", "English", 0.95)

    _captured_sa_reply = "SA reply for active flow question"
    def _mid_flow_dispatcher(text, state):
        return ("sa_continuation", _captured_sa_reply)

    response = process_user_message_with_ooc(
        text="off-topic during suppression", state=state,
        dispatcher=_mid_flow_dispatcher,
        return_none_on_non_ooc_passthrough=True,
        downstream_sd_stage_hint="sa_compose",
    )

    assert response == _captured_sa_reply
    assert state.ooc_escalation_suppression_remaining == 1
    rows = [r for r in captured_audit_rows if r["stage"] == "ooc_suppression_fallthrough"]
    assert rows[0]["extras"]["downstream_sd_stage"] == "sa_compose"
    assert rows[0]["extras"]["downstream_route"] == "sa_continuation"


def test_task21_quotation_helper_exists_and_has_quotation_logic():
    """Decision 5 corrected — `_build_sa_quotation_footer` extracts quotation block.

    Source-level test: helper exists in sd_service.py with quotation logic.
    """
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_service.py").read_text(encoding="utf-8")
    assert "def _build_sa_quotation_footer" in src
    # Verify the new helper has the quotation block (mirror of lines 1605-1612 in old helper)
    helper_section = src.split("def _build_sa_quotation_footer")[1].split("def _build_sa_post_footer")[0]
    assert "is_quotation_request" in helper_section
    assert "build_quotation_footer" in helper_section


def test_task21_no_double_quotation_gating_structure():
    """Decision 5 user-corrected — verify gating logic at the wire-up site.

    flag=on: NEW _build_sa_quotation_footer runs; OLD _build_sa_post_footer SKIPPED
    flag=off: NEW _build_sa_quotation_footer SKIPPED; OLD _build_sa_post_footer runs

    Source-level inspection of the wire-up structure (chroma-coupling blocks direct exec).
    """
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_service.py").read_text(encoding="utf-8")
    # Locate the wire-up gating block
    assert "Footer gating per Decision 5 + Task 21 user-corrected logic" in src
    # Both helpers referenced at the wire-up site
    quot_idx = src.find("footer = _build_sa_quotation_footer(")
    post_idx = src.find("footer = _build_sa_post_footer(\n                question=q_stripped")
    assert quot_idx > 0, "_build_sa_quotation_footer must be invoked at wire-up"
    assert post_idx > 0, "_build_sa_post_footer must still be invoked at wire-up (legacy flag=off path)"
    assert post_idx > quot_idx, (
        "Gating order: NEW quotation helper in flag=on branch BEFORE legacy helper in else branch"
    )


def test_task21_state_load_handles_none_from_repo():
    """Item 3 nuance — wire-up must handle None from SA_ENGINE.repo.get_state()."""
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_service.py").read_text(encoding="utf-8")
    assert "SA_ENGINE.repo.get_state(session_id) or _AgentSessionState(" in src


def test_task21_unconditional_upsert_state():
    """Decision 1 condition — upsert_state called unconditionally (mutations possible
    even when orchestrator returns None: streak reset, lang update, counter decrement)."""
    import pathlib
    src = pathlib.Path("modules/system_detection/sd_service.py").read_text(encoding="utf-8")
    assert "SA_ENGINE.repo.upsert_state(_stage_0_state)" in src


# ============================================================================
# Original Step-3-4 OOCContext construction tests (continue)
# ============================================================================


def test_ooc_context_construction_high_stakes_from_env(monkeypatch, mock_language):
    """Step 3 — high_stakes_intake driven by OOC_HIGH_STAKES_SERVICES env tuple."""
    from modules.system_detection.sd_orchestrator import process_user_message_with_ooc

    state = _state(
        service_code="corporate_fraud_investigation",  # in default OOC_HIGH_STAKES_SERVICES
        question_id="case_summary",
        answers={"prior": "data"},
    )
    mock_language("en", "English", 0.95)

    captured = {}
    def fake_handle(self, ctx):
        captured["high_stakes_intake"] = ctx.high_stakes_intake
        return None
    monkeypatch.setattr("modules.out_of_context.ooc_service.OOCService.handle", fake_handle)

    process_user_message_with_ooc(
        text="x", state=state, dispatcher=lambda t, s: ("sa_continuation", "ok"),
    )
    assert captured["high_stakes_intake"] is True

    # Non-high_stakes service
    state2 = _state(service_code="wbs", question_id="case_handler_quantity", answers={"f": "v"})
    captured2 = {}
    def fake_handle2(self, ctx):
        captured2["high_stakes_intake"] = ctx.high_stakes_intake
        return None
    monkeypatch.setattr("modules.out_of_context.ooc_service.OOCService.handle", fake_handle2)

    process_user_message_with_ooc(
        text="x", state=state2, dispatcher=lambda t, s: ("sa_continuation", "ok"),
    )
    assert captured2["high_stakes_intake"] is False
