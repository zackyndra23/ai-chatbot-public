"""OOC engine Layer A orchestrator — entry point for OOC-aware request routing.

Stage 0 (2026-05-13). See
docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §1.1 for the
canonical Layer A pseudocode this module implements verbatim.

================================================================================
WHY A SEPARATE MODULE FROM sd_service.py
================================================================================

The original plan (docs/superpowers/plans/2026-05-13-ooc-response-engine.md,
Task 11) specified placing `process_user_message_with_ooc()` inside
`sd_service.py`. During Task 11 implementation that target proved
unworkable in the test environment:

    `sd_service.py` imports `sd_vector_repo` + `sd_retrieval_strategies` at
    module top-level. Those pull in `langchain_chroma`, which is not installed
    in some environments (including the current test env — pre-existing
    `test_qualification_dispatcher.py` ImportError failures flagged during
    Task 1 are the same root cause).

The orchestration concern (Tasks 11-13) is logically independent of vector
retrieval (Phase 1/Phase 2 RAG). Coupling them in one module is an
architectural smell. Splitting them:
- Lets orchestrator tests run without the full chroma stack
- Lets Tasks 12-13 use the same test scaffolding without growing import-graph
  surface area
- Preserves strict-additive guarantee TRIVIALLY — `sd_service.py` is not
  touched at all
- Tasks 20-21 wire this entry into the existing dispatcher at
  `sd_service.py:5701` (cold-start) and `:1622` (mid-flow) via
  `from .sd_orchestrator import process_user_message_with_ooc`

Plan deviation captured in
docs/superpowers/plans/2026-05-13-ooc-response-engine.md (per Task 11
milestone) so future implementers see the decision rationale.

================================================================================
SCOPE
================================================================================

Task 11 (this module's initial implementation): Steps 0-2 verbatim.
Tasks 12-13 (in-place edits to this module): Steps 2.5 + 3-6.
Tasks 20-21 (call-site wiring in sd_service.py): no edits here.

Existing call sites at `sd_service.py:5701` + `:1622` continue using the
legacy `OOCService.maybe_handle()` until Tasks 20-21 migrate them. This
module is exercised only by its own tests until then.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

from modules.abandonment import AbandonmentHandler
from modules.out_of_context.ooc_service import OOCService  # noqa: F401  (used by Task 13)
from modules.out_of_context.ooc_types import OOCContext   # noqa: F401  (used by Task 13)
from core.app_audit import record_audit_row
from core.app_config import Config
from modules.system_detection.sd_policies import detect_language_with_confidence

log = logging.getLogger(__name__)


# Canonical 17-language set per spec §Constraint #7.
# `raw_lang` falling outside this set triggers session_fallback per Step 2.
CANON_17 = frozenset({
    "id", "ms", "en", "fr", "de", "it", "pt", "es", "vi",
    "th", "da", "zh", "ja", "ru", "ko", "tl", "ar",
})


# =============================================================================
# Dispatcher contract (Task 12 — (a.2) Callable parameter injection)
# =============================================================================
# The orchestrator delegates non-OOC requests to the existing dispatcher in
# `sd_service.py`. Because `sd_service.py` carries the chroma stack at import
# time (the architectural reason for splitting this file), we DO NOT import
# from it. Instead, callers pass the dispatcher as a Callable at runtime.
#
# Tasks 20-21 wire the real dispatcher at `sd_service.py:5701` (cold-start)
# and `:1622` (mid-flow). Tests pass a mock callable per scenario.
#
# Contract per spec §1.1 line 156:
#   input:  (text: str, state: AgentSessionState)
#   output: (downstream_route: str | None, response: str | None)
#   downstream_route ∈ {"sa_continuation", "faq_rag", "general_agent"} on
#   normal completion. Failure modes covered explicitly in `_suppression_fallthrough`.
# =============================================================================

Dispatcher = Callable[[str, "object"], Tuple[Optional[str], Optional[str]]]


def process_user_message_with_ooc(
    text: str,
    state,
    dispatcher: Optional[Dispatcher] = None,
    return_none_on_non_ooc_passthrough: bool = False,
    downstream_sd_stage_hint: Optional[str] = None,
) -> Optional[str]:
    """OOC-aware orchestrator entry — Layer A per spec §1.1.

    Wraps an incoming user message with: abandonment check (Step 0), fresh
    language detection (Step 1), effective-language resolution + fallback
    (Step 2), suppression-window check (Step 2.5, Task 12), and OOC
    classification + state mutations + audit logging (Steps 3-6, Task 13),
    falling through to the existing dispatcher when the message is not OOC.

    Args:
        text: raw user message
        state: AgentSessionState (session_id, service_code,
               session_fallback_language, ooc_excursion_count,
               ooc_escalation_suppression_remaining, etc.)
        dispatcher: optional Callable for the existing SA continuation /
               FAQ-RAG / General agent pipeline.

               Required when Step 2.5 is reached (suppression counter > 0
               on entry).

               Required when Step 6 is reached AND
               return_none_on_non_ooc_passthrough=False (the default), because
               the orchestrator forwards to the dispatcher on non-OOC turns.

               Tests for Step 0 / Step 1-2 / abandonment paths may omit this;
               orchestrator raises a RuntimeError with explicit guidance if
               downstream steps need the dispatcher and it wasn't provided.
        return_none_on_non_ooc_passthrough: if True (Task 20 wire-up mode),
               the non-OOC pass-through path at Step 6 returns `None` to the
               caller INSTEAD of invoking the dispatcher. The caller is then
               responsible for continuing its own pipeline. State mutations
               (streak reset + session_fallback update) are still applied
               before returning None. Step 2.5 STILL requires a dispatcher
               in this mode — suppression-fallthrough is a "dispatched"
               outcome by definition.

    Behavioral contract by mode:

      return_none_on_non_ooc_passthrough=False (default, pre-Task-20 behavior):
        - OOC turn:               returns the rendered response message (str)
        - Non-OOC turn:           applies state mutations, invokes dispatcher,
                                  returns dispatcher's response (str)
        - Suppression-fallthrough: invokes dispatcher, returns dispatcher's
                                  response (str)
        Return type: `str` (never None)

      return_none_on_non_ooc_passthrough=True (Task 20 cold-start wire-up):
        - OOC turn:               returns the rendered response message (str)
        - Non-OOC turn:           applies state mutations, returns `None`.
                                  Caller continues its own pipeline.
        - Suppression-fallthrough: invokes dispatcher (unchanged), returns
                                  dispatcher's response (str)
        Return type: `Optional[str]` (None on non-OOC pass-through)

    Returns the response message string, or None when
    return_none_on_non_ooc_passthrough=True AND the message classified non-OOC.
    """
    cfg = Config()

    # === STEP 0: Abandonment short-circuit (spec §1.1 lines 112-116) ===
    abandonment = AbandonmentHandler()
    ab_result = abandonment.matches(
        text=text,
        state=state,
        lang_hint=state.session_fallback_language,
    )
    if ab_result.matched:
        ack = abandonment.handle(text=text, state=state)
        record_audit_row(
            stage="abandonment_handler",
            session_id=state.session_id,
            extras={
                "matched_phrase": ab_result.matched_phrase,
                "detected_language": ab_result.detected_language,
                "matched_via": ab_result.matched_via,
            },
        )
        return ack

    # === STEP 1: Per-turn fresh language detection (spec §1.1 lines 118-120) ===
    # Per memory `feedback_language_detection`: no cache, no lock-to-first-turn.
    raw_lang, _raw_name, raw_confidence = detect_language_with_confidence(text)
    session_fallback_language = state.session_fallback_language or "en"

    # === STEP 2: Effective language resolution (spec §1.1 lines 122-131) ===
    if raw_confidence < cfg.OOC_LANG_DETECTION_FLOOR or raw_lang not in CANON_17:
        effective_language = session_fallback_language
        trigger = (
            "low_confidence"
            if raw_confidence < cfg.OOC_LANG_DETECTION_FLOOR
            else "unknown_language"
        )
        record_audit_row(
            stage="language_fallback",
            session_id=state.session_id,
            extras={
                "raw_user_text": (text or "")[:200],  # truncate for audit-row size
                "raw_lang": raw_lang,
                "raw_confidence": raw_confidence,
                "fallback_lang": session_fallback_language,
                "trigger": trigger,
            },
        )
    else:
        effective_language = raw_lang

    # === STEP 2.5: Suppression-window check (spec §1.1 lines 133-149) ===
    if state.ooc_escalation_suppression_remaining > 0:
        return _suppression_fallthrough(
            text, state, effective_language, raw_lang, raw_confidence, dispatcher,
            downstream_sd_stage_hint=downstream_sd_stage_hint,
        )

    # === STEP 3-6: OOC dispatch + state mutations (spec §1.1 lines 150-217) ===
    return _ooc_dispatch(
        text, state, raw_lang, raw_confidence, effective_language, dispatcher,
        return_none_on_non_ooc_passthrough=return_none_on_non_ooc_passthrough,
    )


# =============================================================================
# Step 2.5 — Suppression-window fallthrough (Task 12)
# =============================================================================
# Per spec §1.1 lines 133-149 + Guardrail A (dispatcher-FIRST / audit-AFTER).
#
# Sequence:
#   1. Decrement counter (always — mutex'd to entering Step 2.5)
#   2. Compute pre/post counter values for audit
#   3. Run post-hoc classifier if env-enabled (sampled)
#   4. Invoke dispatcher (FIRST per Guardrail A)
#   5. Write audit row with downstream_route populated (AFTER per Guardrail A)
#   6. Return dispatcher response
#
# Dispatcher failure-mode policy (per Guardrail B):
#   - dispatcher raises:           audit downstream_route="dispatcher_exception"
#                                  + error=str(exc); RE-RAISE original exception
#                                  (upstream Flask handles user-facing fallback;
#                                  swallowing here would hide ops signal)
#   - dispatcher returns (None, None): audit downstream_route="none_returned";
#                                       return "" (honest passthrough)
#   - dispatcher returns degraded result (e.g., ("general_agent", "fallback")):
#                                       audit downstream_route reflects ACTUAL
#                                       returned route faithfully (verbatim);
#                                       return response as-is
#
# Audit row downstream_route is ALWAYS deterministic — one of 6 values:
#   "sa_continuation" | "faq_rag" | "general_agent"   (3 normal dispatcher returns
#                                                       — spec §1.1 line 164 happy paths)
#   "none_returned"                                    (dispatcher returned None,None)
#   "unknown"                                          (dispatcher returned None route
#                                                       with non-None response — guard)
#   "dispatcher_exception"                             (dispatcher raised)
#
# The 3 failure-mode values (none_returned / unknown / dispatcher_exception) are
# a SPEC EXTENSION beyond §1.1 line 164's enumeration, justified by Guardrail B's
# requirement to handle dispatcher failure modes explicitly. See full rationale
# in docs/modules/out_of_context.md "Audit schema — downstream_route extension".
# =============================================================================


def _suppression_fallthrough(
    text: str,
    state,
    effective_language: str,
    raw_lang: str,
    raw_confidence: float,
    dispatcher: Optional[Dispatcher],
    downstream_sd_stage_hint: Optional[str] = None,
) -> str:
    """Spec §1.1 Step 2.5 — dispatcher FIRST, audit AFTER per Guardrail A.

    `downstream_sd_stage_hint` (Task 21): caller-provided SD-side stage label
    to record in the audit row. When None, resolves to "unknown" at audit-write
    time (NOT None — schema completeness pattern; ooc_handler audit row is the
    only stage that writes None for this field, signaling "no SD branch fires").
    """
    cfg = Config()

    # (1) Decrement counter — always, mutex'd to entering this branch
    state.ooc_escalation_suppression_remaining -= 1
    suppression_pre = state.ooc_escalation_suppression_remaining + 1
    suppression_post = state.ooc_escalation_suppression_remaining

    # (3) Post-hoc classifier (env-gated per Refinement #3, sampled)
    posthoc_result = _run_posthoc_classifier_if_enabled(text, effective_language, cfg)

    # Require dispatcher at this point — Tasks 20-21 wire from sd_service.py
    if dispatcher is None:
        raise RuntimeError(
            "process_user_message_with_ooc reached Step 2.5 with dispatcher=None. "
            "This indicates a call-site wiring bug. Pass dispatcher=_sa_continuation_dispatcher "
            "when state.ooc_escalation_suppression_remaining > 0 or state.service_code is set. "
            "See spec §1.1 line 156 + sd_service.py:5701/:1622 migration plan in Tasks 20-21."
        )

    # (4) Invoke dispatcher FIRST per Guardrail A
    downstream_route: Optional[str]
    dispatcher_response: Optional[str]
    dispatch_error: Optional[str] = None
    try:
        downstream_route, dispatcher_response = dispatcher(text, state)
    except Exception as exc:
        # Dispatcher exception: audit BEFORE re-raise so telemetry is preserved
        dispatch_error = f"{type(exc).__name__}: {exc}"
        _write_suppression_audit_row(
            state=state,
            user_text=text,
            pre=suppression_pre,
            post=suppression_post,
            downstream_route="dispatcher_exception",
            posthoc=posthoc_result,
            error=dispatch_error,
            downstream_sd_stage=downstream_sd_stage_hint,
        )
        log.error(
            "ooc_suppression_dispatcher_exception",
            extra={
                "session_id": state.session_id,
                "error": dispatch_error,
                "suppression_remaining_post": suppression_post,
            },
        )
        raise  # propagate to upstream Flask error handler

    # Normalize dispatcher return shape into deterministic downstream_route
    if downstream_route is None and dispatcher_response is None:
        downstream_route_recorded = "none_returned"
        response = ""
    elif downstream_route is None:
        # Got a response but no route — synthesize "unknown" for audit faithfulness
        downstream_route_recorded = "unknown"
        response = dispatcher_response or ""
    else:
        # Normal case (incl. degraded e.g., "general_agent" fallback) — record verbatim
        downstream_route_recorded = downstream_route
        response = dispatcher_response or ""

    # (5) Audit row AFTER dispatcher returns per Guardrail A
    _write_suppression_audit_row(
        state=state,
        user_text=text,
        pre=suppression_pre,
        post=suppression_post,
        downstream_route=downstream_route_recorded,
        posthoc=posthoc_result,
        error=None,
        downstream_sd_stage=downstream_sd_stage_hint,
    )

    # (6) Return response
    return response


def _write_suppression_audit_row(
    *,
    state,
    user_text: str,
    pre: int,
    post: int,
    downstream_route: str,
    posthoc,
    error: Optional[str],
    downstream_sd_stage: Optional[str] = None,
    phase0_legacy_fallback: bool = False,
) -> None:
    """Compose + persist the ooc_suppression_fallthrough audit row.

    Schema per spec §7.4 + Appendix D.5 (Task 20 additions) — extras dict has
    10 fields ALWAYS PRESENT (Optional ones explicitly None, NOT absent —
    cleaner for downstream MongoDB analytics that doesn't need $exists clauses):

        user_text                                 (truncated to 200 chars)
        suppression_remaining_pre                 (int)
        suppression_remaining_post                (int)
        downstream_route                          (str — one of 6 deterministic values)
        downstream_sd_stage                       (Optional[str] — Task 20: SD-side stage
                                                   from dispatcher; None until Phase 1)
        posthoc_classifier_sampled                (bool)
        posthoc_classifier_would_have_classified  (Optional[OOCCategory])
        posthoc_classifier_confidence             (Optional[float])
        posthoc_classifier_mode                   (Optional[str])
        phase0_legacy_fallback                    (bool — Task 20: True when cold-start
                                                   suppression hit the legacy fallback path
                                                   per spec Appendix D.6 Phase 0 limitation)
    """
    # Per Task 21: None → "unknown" resolution at audit-write time.
    # Caller didn't pass downstream_sd_stage_hint → record "unknown" (not None).
    # Schema-completeness pattern preserved (always present); semantic differs
    # from ooc_handler row's None (which means "no SD branch fired").
    sd_stage_recorded = downstream_sd_stage if downstream_sd_stage is not None else "unknown"
    extras: dict = {
        "user_text": (user_text or "")[:200],
        "suppression_remaining_pre": pre,
        "suppression_remaining_post": post,
        "downstream_route": downstream_route,
        "downstream_sd_stage": sd_stage_recorded,
        "posthoc_classifier_sampled": posthoc is not None,
        "posthoc_classifier_would_have_classified": posthoc.label if posthoc else None,
        "posthoc_classifier_confidence": posthoc.confidence if posthoc else None,
        "posthoc_classifier_mode": posthoc.classifier_mode if posthoc else None,
        "phase0_legacy_fallback": phase0_legacy_fallback,
    }
    record_audit_row(
        stage="ooc_suppression_fallthrough",
        session_id=state.session_id,
        extras=extras,
        error=error,
    )


def _run_posthoc_classifier_if_enabled(text: str, lang: str, cfg):
    """Env-gated post-hoc classifier per spec Refinement #3.

    Returns OOCDecision when:
      - OOC_POSTHOC_CLASSIFIER_ENABLED=true AND
      - sampling random < OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE
    Returns None otherwise (the common case; default OOC_POSTHOC_CLASSIFIER_ENABLED=false).

    Result is purely audit-side — does NOT influence routing.
    """
    if not cfg.OOC_POSTHOC_CLASSIFIER_ENABLED:
        return None
    import random
    if random.random() > cfg.OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE:
        return None
    try:
        from modules.out_of_context.ooc_classifier import OOCClassifier
        return OOCClassifier(mode=cfg.OOC_POSTHOC_CLASSIFIER_MODE).classify(
            text=text, language=lang, active_service=None,
        )
    except Exception as e:
        log.warning(
            "ooc_posthoc_classifier_failure_swallowed",
            extra={"error": str(e), "lang": lang},
        )
        return None


# =============================================================================
# Dispatcher route mapping reference (Task 20 / spec Appendix D.5)
# =============================================================================
# The cold-start dispatcher (Tasks 20-21) branches into 4 SD-side stages but
# the Dispatcher contract returns one of 3 route values. Mapping:
#
#   SD-side stage           → dispatcher downstream_route
#   ----------------------  → -------------------------
#   self_introduction       → general_agent
#   greeting                → general_agent
#   sa_compose              → sa_continuation  (see B3 NAMING NOTE below)
#   misc_compose_1          → faq_rag
#
# B3 NAMING NOTE: `sa_compose` maps to `sa_continuation`. The contracted value
# originates from spec's mid-flow design where SA is already active. At
# cold-start, sa_compose INITIATES SA rather than continues, so the name is
# semantically awkward but closest. The downstream_sd_stage field
# disambiguates for analytics — operators see both the dispatcher route
# ("sa_continuation") and the actual SD-side stage ("sa_compose").
# See spec Appendix D.5 + Decision 1 sub-decision rationale.
#
# Phase 0 only writes downstream_sd_stage=None to audit rows because the
# cold-start dispatcher is deferred (spec Appendix D.6.2). Phase 1 will
# populate the actual SD-side stage from the dispatcher's return.
# =============================================================================


# =============================================================================
# Steps 3-6 — OOC dispatch + state mutations (Task 13)
# =============================================================================
# Per spec §1.1 lines 150-217 + §7.2 turn-type mutation table.
#
# Pipeline:
#   Step 3: Load SA state + compute pre_data / high_stakes_intake
#   Step 4: Build OOCContext (Approach 3 data contract)
#   Step 5: Invoke OOCService.handle(ctx)
#   Step 6: Branch on result
#     - None → Non-OOC turn (§7.2 row 1):
#         * reset ooc_excursion_count = 0
#         * reset previous_user_ooc_categories = []
#         * reset previous_system_meta_actions = []
#         * update session_fallback_language IF confident detection
#         * pass-through to existing dispatcher (Tasks 20-21 wire real dispatcher)
#     - OOCResult → OOC turn:
#         * increment ooc_excursion_count
#         * append to previous_user_ooc_categories (§7.2 row 2) OR
#           previous_system_meta_actions (§7.2 row 3) per streak_classification
#         * if set_escalation_suppression: set ooc_escalation_suppression_remaining
#           to OOC_ESCALATION_SUPPRESSION_TURNS (§7.2 row 3)
#         * T1-OOC-confident cold-start exception (§7.2 row 5 / D6 row 3):
#           if ooc_excursion_count == 1 AND session_fallback_language at entry == "en"
#           AND raw_confidence >= floor AND raw_lang in CANON_17 →
#           update session_fallback_language = raw_lang
#         * audit row stage="ooc_handler" with OOCAuditMetadata.model_dump() extras
#         * return result.message
#
# Constraint #2: do NOT clear active SA state on OOC turns
# Constraint #3: do NOT increment invalid_count
# Q#4 formalization: do NOT update session_fallback_language on OOC turns
#                   (except T1 exception D6 row 3)
# =============================================================================


def _ooc_dispatch(
    text: str,
    state,
    raw_lang: str,
    raw_confidence: float,
    effective_language: str,
    dispatcher: Optional[Dispatcher],
    return_none_on_non_ooc_passthrough: bool = False,
) -> Optional[str]:
    """Spec §1.1 Steps 3-6 — OOCContext build + classify + state mutations + audit.

    When return_none_on_non_ooc_passthrough=True, the non-OOC Step 6 branch
    applies state mutations and returns None instead of invoking dispatcher.
    """
    cfg = Config()

    # === STEP 3: Load session + SA state ===
    active_service = state.service_code if state.service_code else None
    current_field_id = state.question_id if (state.question_id and active_service) else None
    answers = state.answers or {}
    pre_data = active_service is not None and len(answers) == 0
    # `high_stakes_intake` from OOC_HIGH_STAKES_SERVICES env tuple (single source of truth
    # per spec §6.3). FLOW_REGISTRY.get(...).get("high_stakes_intake", False) from spec
    # would always be False because no flow defines that field — env knob is authoritative.
    high_stakes_intake = (
        active_service is not None and active_service in cfg.OOC_HIGH_STAKES_SERVICES
    )

    last_question_text = _resolve_question_text(active_service, current_field_id)

    # Snapshot session_fallback_language at Step 3 entry. Used by T1 exception
    # check at Step 6 (must compare against the value BEFORE any potential update).
    session_fallback_at_entry = state.session_fallback_language or "en"

    # === STEP 4: Build OOCContext ===
    ctx = OOCContext(
        user_text=text,
        user_detected_language=effective_language,
        raw_detected_language=raw_lang,
        raw_detection_confidence=raw_confidence,
        session_fallback_language=session_fallback_at_entry,
        active_service=active_service,
        current_field_id=current_field_id,
        last_question_text=last_question_text,
        pre_data=pre_data,
        high_stakes_intake=high_stakes_intake,
        previously_seen_OOC_in_session=state.ooc_excursion_count or 0,
        previous_user_ooc_categories=list(state.previous_user_ooc_categories or []),
        previous_system_meta_actions=list(state.previous_system_meta_actions or []),
        ooc_escalation_suppression_remaining=state.ooc_escalation_suppression_remaining or 0,
    )

    # === STEP 5: Invoke OOC module (Layer B) ===
    result = OOCService().handle(ctx)

    # === STEP 6: Branch on result ===
    if result is None:
        return _apply_non_ooc_turn_and_dispatch(
            text=text,
            state=state,
            raw_lang=raw_lang,
            raw_confidence=raw_confidence,
            dispatcher=dispatcher,
            return_none_on_passthrough=return_none_on_non_ooc_passthrough,
        )
    return _apply_ooc_turn_and_audit(
        result=result,
        state=state,
        raw_lang=raw_lang,
        raw_confidence=raw_confidence,
        session_fallback_at_entry=session_fallback_at_entry,
    )


def _apply_non_ooc_turn_and_dispatch(
    *,
    text: str,
    state,
    raw_lang: str,
    raw_confidence: float,
    dispatcher: Optional[Dispatcher],
    return_none_on_passthrough: bool = False,
) -> Optional[str]:
    """Spec §7.2 row 1 — Non-OOC turn mutations + pass-through to existing dispatcher.

    When return_none_on_passthrough=True (Task 20 wire-up mode), applies state
    mutations and returns None instead of invoking dispatcher. Caller continues
    its own pipeline. State mutation contract is identical in both modes.
    """
    cfg = Config()

    # §7.2 row 1 mutations (identical in both modes)
    state.ooc_excursion_count = 0
    state.previous_user_ooc_categories = []
    state.previous_system_meta_actions = []

    # session_fallback_language updates only on confident, canonical detection
    if raw_confidence >= cfg.OOC_LANG_DETECTION_FLOOR and raw_lang in CANON_17:
        state.session_fallback_language = raw_lang

    # Task 20 wire-up mode: caller continues their own pipeline; no dispatcher call.
    if return_none_on_passthrough:
        return None

    # Default mode: dispatch to existing SA continuation / FAQ-RAG / General agent
    if dispatcher is None:
        raise RuntimeError(
            "process_user_message_with_ooc reached Step 6 non-OOC passthrough with dispatcher=None. "
            "This indicates a call-site wiring bug. Pass dispatcher=_sa_continuation_dispatcher "
            "when state.ooc_escalation_suppression_remaining > 0 or state.service_code is set. "
            "See spec §1.1 line 156 + sd_service.py:5701/:1622 migration plan in Tasks 20-21."
        )

    try:
        _route, response = dispatcher(text, state)
    except Exception as exc:
        log.error(
            "ooc_non_ooc_dispatcher_exception",
            extra={
                "session_id": state.session_id,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        raise  # propagate to upstream Flask error handler

    return response or ""


def _apply_ooc_turn_and_audit(
    *,
    result,
    state,
    raw_lang: str,
    raw_confidence: float,
    session_fallback_at_entry: str,
) -> str:
    """Spec §7.2 rows 2/3/5 — OOC turn mutations + audit row + T1 exception."""
    cfg = Config()

    # Increment streak counter (§7.2 rows 2/3)
    state.ooc_excursion_count = (state.ooc_excursion_count or 0) + 1

    # Append to category chain based on streak classification
    if result.streak_classification == "user_ooc":
        # §7.2 row 2: append category to user list
        state.previous_user_ooc_categories = list(state.previous_user_ooc_categories or []) + [
            result.category
        ]
    else:  # "system_meta" — e.g., ESCALATION-CONSECUTIVE-OOC
        # §7.2 row 3: append to system-meta list
        state.previous_system_meta_actions = list(state.previous_system_meta_actions or []) + [
            result.category
        ]

    # §7.2 row 3: set suppression counter on escalation handover
    if result.set_escalation_suppression:
        state.ooc_escalation_suppression_remaining = cfg.OOC_ESCALATION_SUPPRESSION_TURNS

    # T1-OOC-confident cold-start exception (§7.2 row 5 / spec D6 row 3)
    # ALL 4 conditions must hold:
    #   1. This is the FIRST OOC turn of the session (counter just became 1)
    #   2. session_fallback was the default "en" at entry (never confidently set)
    #   3. raw confidence ≥ OOC_LANG_DETECTION_FLOOR
    #   4. raw_lang ∈ CANON_17
    if (
        state.ooc_excursion_count == 1
        and session_fallback_at_entry == "en"
        and raw_confidence >= cfg.OOC_LANG_DETECTION_FLOOR
        and raw_lang in CANON_17
    ):
        state.session_fallback_language = raw_lang

    # Audit row — ooc_handler stage with full OOCAuditMetadata + Task 20 additions
    audit_extras: dict = (
        result.audit_metadata.model_dump() if result.audit_metadata is not None else {}
    )
    # Augment with result-level fields not in OOCAuditMetadata schema
    audit_extras["category"] = result.category
    audit_extras["shape_used"] = result.shape_used
    audit_extras["language_used"] = result.language_used
    audit_extras["streak_classification"] = result.streak_classification
    audit_extras["set_escalation_suppression"] = result.set_escalation_suppression
    # Task 20 — downstream_sd_stage always present in ooc_handler audit row (None: no SD
    # branch fires when OOC is handled — spec §7.4 + Appendix D.5 schema-completeness pattern)
    audit_extras["downstream_sd_stage"] = None

    record_audit_row(
        stage="ooc_handler",
        session_id=state.session_id,
        extras=audit_extras,
    )

    return result.message


def _resolve_question_text(active_service: Optional[str], current_field_id: Optional[str]) -> str:
    """Resolve the text of the last unanswered SA question for {last_question} placeholder.

    Uses `FLOW_REGISTRY[service][field_id].text`. FLOW_REGISTRY text is English-only
    in the current schema; per-language translation of question text is a future
    improvement (would require glossary expansion in i18n). For now the renderer
    embeds the English text into the localized P3 paragraph — acceptable for
    Phase 0 since the same question was presented in English originally.
    """
    if not active_service or not current_field_id:
        return ""
    try:
        from modules.service_agent.sa_flows import FLOW_REGISTRY
        flow = FLOW_REGISTRY.get(active_service) or {}
        step = flow.get(current_field_id)
        if step is None:
            return ""
        return getattr(step, "text", "") or ""
    except Exception as e:
        log.warning(
            "ooc_resolve_question_text_failure_swallowed",
            extra={
                "service": active_service,
                "field": current_field_id,
                "error": str(e),
            },
        )
        return ""
