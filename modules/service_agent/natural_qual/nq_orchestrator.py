"""Method B orchestrator — 10-step per-turn algorithm.

See `docs/superpowers/specs/2026-05-12-qualification-method-toggle-design.md`
Section 6 for the full algorithm.

Public API: handle_turn(state, user_message, crisp_profile, language_code, token_id=None) -> dict
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

from modules.service_agent.sa_types import AgentSessionState
from modules.service_agent.natural_qual.nq_minset import (
    resolve_min_set, is_min_set_complete,
)
from modules.service_agent.natural_qual.nq_policies import (
    compute_picker_decision, render_rescue_message, update_dry_count,
)
from modules.service_agent.natural_qual.nq_agent import (
    build_agent_context, render_prompt, invoke_agent, parse_agent_output,
    _check_verbatim,
)

logger = logging.getLogger(__name__)


def _check_keyword_meeting_intent(user_message: str, language_code: str) -> Tuple[bool, Optional[str]]:
    """Wrap sd_meeting.is_meeting_request, classify keyword kind for taxonomy.

    Returns (keyword_fires, keyword_kind ∈ {"explicit","implicit",None}).
    """
    from modules.system_detection.sd_meeting import is_meeting_request
    if not is_meeting_request(user_message, language_code):
        return False, None
    t = (user_message or "").lower()
    generic_en = ("meeting", "appointment", "schedule a call", "book a call", "book a meeting",
                  "set up a meeting", "talk with your team", "set a meeting", "arrange a meeting")
    if any(k in t for k in generic_en):
        return True, "explicit"
    return True, "implicit"


def _retrieve_rag_context(
    user_message: str, service_label: str, session_id: str, token_id: Optional[str],
    language_code: str,
) -> Tuple[str, List[Any]]:
    """Reuse existing sd_service._prepare_rag_context for FAQ grounding.

    Returns (ctx_str, ctx_docs). On any failure, returns ("", []).
    """
    try:
        from modules.system_detection import sd_service as svc
        rag_query = f"{service_label}. {user_message}".strip() or service_label or "Acme Services service"
        filtered, ctx_str, _related = svc._prepare_rag_context(
            rag_query,
            sa_service_label=service_label,
            session_id=session_id,
            token_id=token_id,
            turn_language_code=language_code,
        )
        return ctx_str or "", filtered or []
    except Exception as e:
        logger.warning("Method B RAG retrieval failed: %s", e)
        return "", []


def _read_recent_chat_history(
    session_id: str, token_id: Optional[str], limit: int = 12,
) -> List[Dict[str, str]]:
    """Fetch recent chat history via sd_repo.read_chat_history.

    Returns a list of `{"q": <user_text>, "m": <bot_text>}` entries, normalized
    from whatever shape the Mongo record uses. Returns `[]` on any failure
    (caller proceeds with empty context — preserves Stage 4 behavior in
    environments without Mongo).

    Window size is controlled here by `limit` — there is NO additional slicing
    in `_format_history_block`.
    """
    try:
        from modules.system_detection.sd_repo import read_chat_history
        rows = read_chat_history(session_id, token_id, limit=limit) or []
        out: List[Dict[str, str]] = []
        for r in rows:
            q = (r.get("question") or r.get("q") or "")
            m = (r.get("message") or r.get("m") or "")
            if isinstance(q, str) and isinstance(m, str) and (q or m):
                out.append({"q": q, "m": m})
        return out
    except Exception as e:
        logger.warning("Method B recent_history fetch failed: %s", e)
        return []


def _build_verbatim_correction_addendum(violations: List[str]) -> str:
    """Construct the prompt addendum injected for the verbatim retry call."""
    fields_csv = ", ".join(violations)
    return (
        "\n\nIMPORTANT CORRECTION: Your previous response had non-verbatim "
        f"field_writes for: {fields_csv}. These values were not present "
        "verbatim (case-insensitive substring) in any user message. "
        "Re-output the FULL JSON object with corrected field_writes — either "
        "REMOVE those fields from field_writes, or REPLACE values with the "
        "EXACT verbatim wording the user used. Preserve all other fields "
        "(message, target_field, intent_score, interest_signal, "
        "off_topic_detected) from your previous response."
    )


def _classify_write_sources(
    field_writes_kept: Dict[str, str],
    current_message: str,
    recent_history: List[Dict[str, str]],
) -> Dict[str, str]:
    """Per-field provenance for committed writes.

    Returns {field_name: "current_message" | "history"} for each entry in
    field_writes_kept whose value matches.

    Stage 4.6 TODO: bump granularity to "history_turn_N" for production
    forensics if lead-profile-value dispute arises. Document in audit query
    consumers before bumping.
    """
    out: Dict[str, str] = {}
    cur_lower = (current_message or "").lower()
    for fname, val in (field_writes_kept or {}).items():
        if not isinstance(val, str) or not val.strip():
            continue
        v = val.strip().lower()
        if v in cur_lower:
            out[fname] = "current_message"
        else:
            out[fname] = "history"
    return out


def _invoke_agent_for_turn(prompt_text: str) -> str:
    """Invoke SA_LLM via nq_agent.invoke_agent. Separated for mocking."""
    from modules.service_agent.sa_service import SA_LLM
    return invoke_agent(prompt_text, SA_LLM)


def _get_flow_field_texts(service_code: str) -> Dict[str, str]:
    """Build {field_name: decision_tree_text} dict from FLOW_REGISTRY."""
    from modules.service_agent.sa_flows import FLOW_REGISTRY
    flow = FLOW_REGISTRY.get(service_code, {})
    out: Dict[str, str] = {}
    for step in flow.values():
        f = getattr(step, "field_name", None)
        if f:
            out[f] = getattr(step, "text", "") or ""
    return out


def _find_rescue_field_step_text(service_code: str, field_name: str) -> str:
    """Return the decision-tree text for the step that owns this field."""
    from modules.service_agent.sa_flows import FLOW_REGISTRY
    flow = FLOW_REGISTRY.get(service_code, {})
    for step in flow.values():
        if getattr(step, "field_name", None) == field_name:
            return getattr(step, "text", "") or ""
    return ""


def handle_turn(
    state: AgentSessionState,
    user_message: str,
    crisp_profile: Dict[str, Any],
    language_code: str,
    token_id: Optional[str] = None,
) -> Dict[str, Any]:
    """One Method B turn. Mutates `state` in-place. Returns turn result dict."""
    # Step 0: increment turn_index FIRST (Fine-tune F)
    state.turn_index = (state.turn_index or 0) + 1
    verbatim_retry_fired = False
    recent_history: List[Dict[str, str]] = []

    # Step 1: resolve min-set
    from modules.service_agent.sa_flows import FLOW_REGISTRY
    flow = FLOW_REGISTRY.get(state.service_code, {})
    min_set = resolve_min_set(state.service_code, flow)
    min_set_fields = [v for v in min_set.values() if v]

    # Step 2: inspect state
    filled = {k for k, v in state.answers.items() if isinstance(v, str) and v.strip()}
    all_field_names = list(_get_flow_field_texts(state.service_code).keys())
    empty_fields = [f for f in all_field_names if f not in filled]
    min_set_complete_pre = is_min_set_complete(min_set, state.answers)

    # Step 3: keyword trigger (cached for step 9)
    keyword_fires, keyword_kind = _check_keyword_meeting_intent(user_message, language_code)

    # Step 4: anti-loop check — find rescue field if any
    # A field qualifies for rescue when: dry_count >= 3 AND not yet in rescue_attempted.
    # Snapshot rescue_attempted BEFORE Step 5 so Step 8 only processes fields that
    # were already awaiting rescue from a PRIOR turn (not the one we add this turn).
    rescue_attempted_pre_turn = set(state.rescue_attempted)
    rescue_field: Optional[str] = None
    for mf in min_set_fields:
        if state.dry_count.get(mf, 0) >= 3 and mf not in state.rescue_attempted:
            rescue_field = mf
            break

    # Step 4.5: retrieve RAG context (always, for grounding)
    rag_ctx_str, _rag_docs = _retrieve_rag_context(
        user_message=user_message,
        service_label=state.service_label,
        session_id=state.session_id,
        token_id=token_id,
        language_code=language_code,
    )

    # Step 5: agent call — UNLESS rescue path
    prompt_applied: str = ""
    if rescue_field is not None:
        # Deterministic rescue: render soft-bridge, skip LLM entirely
        dt_text = _find_rescue_field_step_text(state.service_code, rescue_field)
        assistant_message = render_rescue_message(language_code, dt_text)
        agent_output = {
            "message": assistant_message,
            "field_writes": {},
            "target_field": rescue_field,
            "intent_score": "low",
            "off_topic_detected": False,
            "_parse_error": None,
        }
        if rescue_field not in state.rescue_attempted:
            state.rescue_attempted.append(rescue_field)
        prompt_applied = f"(no LLM — Method B rescue: {rescue_field})"
    else:
        # Fetch chat history for the agent's prompt (Behavior 2 — no re-ask).
        recent_history = _read_recent_chat_history(
            session_id=state.session_id, token_id=token_id, limit=12,
        )
        ctx = build_agent_context(
            service_code=state.service_code,
            flow_field_texts=_get_flow_field_texts(state.service_code),
            filled_answers={k: v for k, v in state.answers.items() if isinstance(v, str) and v.strip()},
            empty_fields=empty_fields,
            min_set_resolved=min_set,
            min_set_complete=min_set_complete_pre,
            dry_count=dict(state.dry_count),
            fallback_skipped_fields=list(state.fallback_skipped_fields),
            crisp_contact_present=bool(crisp_profile.get("email") or crisp_profile.get("phone")),
            recent_history=recent_history,
            rag_chunks=rag_ctx_str,
            user_message=user_message,
            language_code=language_code,
        )
        prompt_text = render_prompt(ctx)
        prompt_applied = prompt_text
        raw = _invoke_agent_for_turn(prompt_text)
        agent_output = parse_agent_output(raw)

        # Step 5.5: Verbatim retry-once for field_writes (Stage 4.5 Behavior 2).
        # Only runs on normal (non-rescue) path. Builds corpus from current
        # message + user "q" entries in recent_history (lowercased), checks
        # each field_writes value as a case-insensitive substring of corpus.
        # On any violation: re-invoke LLM ONCE with correction addendum. If
        # retry response still contains violating writes, drop those fields
        # silently and log at ERROR.
        user_history_text = " ".join((t.get("q") or "") for t in recent_history)
        corpus_lower = (user_message + " " + user_history_text).lower()
        violations = _check_verbatim(agent_output.get("field_writes") or {}, corpus_lower)
        if violations:
            verbatim_retry_fired = True
            addendum = _build_verbatim_correction_addendum(violations)
            retry_prompt = prompt_text + addendum
            raw_retry = _invoke_agent_for_turn(retry_prompt)
            agent_output_retry = parse_agent_output(raw_retry)
            if not agent_output_retry.get("_parse_error"):
                agent_output = agent_output_retry
            # Log the final prompt actually sent to the LLM (incl. retry addendum)
            prompt_applied = retry_prompt
            violations_after = _check_verbatim(
                agent_output.get("field_writes") or {}, corpus_lower,
            )
            for fname in violations_after:
                agent_output["field_writes"].pop(fname, None)
            if violations_after:
                logger.error(
                    "Method B verbatim retry violations remain (fields dropped): %s",
                    violations_after,
                )

    # Step 6: apply field_writes (+ cleanup edge cases)
    # Accept writes for:
    #   - fields known in the active flow (all_field_names)
    #   - fields already present in answers (previously written)
    #   - fields in fallback_skipped_fields (user volunteering previously-skipped data)
    fields_written: List[str] = []
    for fname, value in (agent_output.get("field_writes") or {}).items():
        if (fname in all_field_names
                or fname in state.answers
                or fname in state.fallback_skipped_fields):
            v = (value or "").strip() if isinstance(value, str) else ""
            if v:
                state.answers[fname] = v
                fields_written.append(fname)
                # If user volunteers a previously-skipped field, remove from skip list
                if fname in state.fallback_skipped_fields:
                    state.fallback_skipped_fields.remove(fname)
                # Clear dry_count and rescue_attempted for committed field
                state.dry_count.pop(fname, None)
                if fname in state.rescue_attempted:
                    state.rescue_attempted.remove(fname)

    # Step 7: update dry_count (frozen-not-reset semantics)
    target = agent_output.get("target_field")
    state.dry_count = update_dry_count(state.dry_count, min_set_fields, state.answers, target)

    # Step 8: check rescue-failed post-turn
    # Only check fields that were ALREADY in rescue_attempted before this turn
    # (rescue_attempted_pre_turn snapshot). Fields added THIS turn (rescue_field)
    # get their chance to receive an answer next turn — don't fail them immediately.
    # If a field from a prior rescue turn is still empty → rescue failed.
    # Move to fallback_skipped_fields, clear from dry_count + rescue_attempted.
    fallback_skipped_added: List[str] = []
    for X in list(rescue_attempted_pre_turn):
        v = state.answers.get(X, "")
        if not (isinstance(v, str) and v.strip()):
            state.fallback_skipped_fields.append(X)
            fallback_skipped_added.append(X)
            state.dry_count.pop(X, None)
            if X in state.rescue_attempted:
                state.rescue_attempted.remove(X)

    # Re-compute min_set_complete after field writes
    min_set_complete_post = is_min_set_complete(min_set, state.answers)

    # Step 9: picker decision
    should_offer, reason = compute_picker_decision(
        keyword_fires=keyword_fires,
        keyword_kind=keyword_kind,
        min_set_complete=min_set_complete_post,
        intent_score=agent_output.get("intent_score", "low"),
        turn_index=state.turn_index,
        last_picker_offer_turn=state.last_picker_offer_turn,
        cooldown_turns=2,
    )

    # Step 9.5 (2026-05-18): MEETING_POPUP cadence trigger — parity with
    # Method A. Count filled flow answers; if `answered_count` is a non-zero
    # multiple of MEETING_POPUP and we haven't already fired at this milestone
    # (popup_shown_counts), offer the picker. Cadence takes precedence over
    # "none" but does not override an already-firing reason from keyword /
    # min_set_intent paths above.
    # Suppressed when interest_signal=="not_interested" — pushing a meeting on
    # someone who explicitly declined is counterproductive and is already
    # tested in test_not_interested_no_writes_no_question_no_picker.
    import os as _os
    meeting_popup_every = int(_os.getenv("MEETING_POPUP", "0") or 0)
    if meeting_popup_every > 0 and agent_output.get("interest_signal") != "not_interested":
        answered_count = sum(
            1 for v in state.answers.values()
            if isinstance(v, str) and v.strip()
        )
        shown_set = set(state.popup_shown_counts or [])
        if (
            answered_count > 0
            and answered_count % meeting_popup_every == 0
            and answered_count not in shown_set
        ):
            if not should_offer:
                should_offer = True
                reason = f"meeting_popup_cadence_{answered_count}"
            shown_set.add(answered_count)
            state.popup_shown_counts = sorted(shown_set)

    if should_offer:
        state.last_picker_offer_turn = state.turn_index

    # Step 10: persist last_intent_score (other state already mutated in-place above)
    state.last_intent_score = agent_output.get("intent_score", "low")
    # Stage 4.5: persist last_interest_signal for telemetry parity.
    state.last_interest_signal = agent_output.get("interest_signal", "interest_answer")

    return {
        "assistant_message": agent_output.get("message", ""),
        "picker_offered": should_offer,
        "picker_offer_reason": reason,
        "rescue_fired": rescue_field is not None,
        "rescue_field": rescue_field,
        "agent_output": agent_output,
        "target_field": target,
        "intent_score": agent_output.get("intent_score", "low"),
        "field_writes_count": len(fields_written),
        "fields_written": fields_written,
        "fallback_skipped_added": fallback_skipped_added,
        "min_set_complete": min_set_complete_post,
        "dry_count_snapshot": dict(state.dry_count),
        "rescue_attempted_snapshot": list(state.rescue_attempted),
        "verbatim_retry_fired": verbatim_retry_fired,
        "prompt_applied": prompt_applied,
        # Stage 4.5 audit additions
        "interest_signal": agent_output.get("interest_signal", "interest_answer"),
        "field_writes_sources": _classify_write_sources(
            {f: state.answers[f] for f in fields_written if f in state.answers},
            user_message,
            recent_history,
        ),
        "consistency_warns_count": len(agent_output.get("warnings") or []),
    }
