"""Unit tests for SA commit_turn junk-data filter (2026-05-08 patch).

Pre-fix bug: when user input is classified as `question_only` (asking instead
of answering, e.g. mid-WBS-flow asking about EBS), the user message was still
written into `state.answers[current_field]` — polluting lead data with
non-answer content like 'saya juga tertarik dengan EBS...'

Fix: gate `state.answers[key]` write on `dual_agent_meta.type` being
answer_only or answer_and_question.

Run (stdlib only, no pytest):
    python tests/test_sa_commit_turn_junk_filter.py
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _make_engine_with_state(*, current_q_field="wbs_user_eligibility", existing_answer=""):
    """Build a fake SA engine + state for testing commit_turn in isolation."""
    from modules.service_agent.sa_service import INTAgentService
    from modules.service_agent.sa_types import AgentSessionState

    state = AgentSessionState(
        session_id="test-session",
        service_code="WBS",
        service_label="Whistleblowing Hotline",
        question_id="wbs.user_eligibility_2",
        status="ongoing on wbs.user_eligibility_2",
        answers={current_q_field: existing_answer} if existing_answer else {},
        dual_agent_meta={},
    )

    fake_repo = MagicMock()
    fake_repo.get_state = MagicMock(return_value=state)
    fake_repo.upsert_state = MagicMock()

    # Fake flow with one step
    fake_step = MagicMock()
    fake_step.field_name = current_q_field
    fake_step.id = "wbs.user_eligibility_2"
    fake_step.text = "Who should use the channel?"
    fake_step.default_next = "wbs.channels_3"
    fake_step.next_if = None

    engine = INTAgentService(repo=fake_repo, llm_client=MagicMock())
    flow_dict = {"wbs.user_eligibility_2": fake_step, "wbs.channels_3": fake_step}

    return engine, state, fake_repo, flow_dict


def _patch_flow(engine, flow_dict):
    """Patch FLOW_REGISTRY in sa_service module."""
    import modules.service_agent.sa_service as svc
    return patch.dict(svc.FLOW_REGISTRY, {"WBS": flow_dict})


def test_question_only_does_not_pollute_answers():
    """Bug case: user asks about EBS while in WBS qualification → no junk write."""
    engine, state, repo, flow = _make_engine_with_state()
    extra = {"dual_agent_meta": {"type": "question_only", "next_question": False}}

    with _patch_flow(engine, flow):
        result = engine.commit_turn(
            session_id="test-session",
            user_answer="saya juga tertarik dengan EBS, bisa dijelaskan?",
            extra=extra,
            advance=False,
        )

    assert result["ok"] is True
    # Critical assertion: the answers field should NOT contain user's question
    val = state.answers.get("wbs_user_eligibility", "")
    assert val == "" or val is None or val == {}, \
        f"junk write detected: wbs_user_eligibility={val!r}"


def test_question_only_with_force_advance_no_junk_write():
    """Anti-loop case: 2nd question_only forces advance — but still no answer write."""
    engine, state, repo, flow = _make_engine_with_state()
    extra = {"dual_agent_meta": {"type": "question_only", "next_question": True}}

    with _patch_flow(engine, flow):
        result = engine.commit_turn(
            session_id="test-session",
            user_answer="saya ingin pindah ke EBS dulu, bagaimana?",
            extra=extra,
            advance=True,
        )

    assert result["ok"] is True
    # Anti-loop: status SHOULD advance
    assert "channels_3" in state.status, f"expected status advance, got {state.status}"
    # But answers[key] for the SKIPPED step should still be empty
    val = state.answers.get("wbs_user_eligibility", "")
    assert val == "" or val is None or val == {}, \
        f"force-advance should not write junk; got {val!r}"


def test_answer_only_writes_answer_normally():
    """Sanity: real answer is committed."""
    engine, state, repo, flow = _make_engine_with_state()
    extra = {"dual_agent_meta": {"type": "answer_only", "next_question": True, "interest_label": "valid"}}

    with _patch_flow(engine, flow):
        result = engine.commit_turn(
            session_id="test-session",
            user_answer="Indonesia",
            extra=extra,
            advance=True,
        )

    assert result["ok"] is True
    assert state.answers.get("wbs_user_eligibility") == "Indonesia", \
        f"answer_only should write; got {state.answers.get('wbs_user_eligibility')!r}"


def test_answer_and_question_writes_answer():
    """User gives answer + question → answer text still committed."""
    engine, state, repo, flow = _make_engine_with_state()
    extra = {"dual_agent_meta": {"type": "answer_and_question", "next_question": True}}

    with _patch_flow(engine, flow):
        result = engine.commit_turn(
            session_id="test-session",
            user_answer="hanya karyawan internal, omong-omong apa beda dengan EBS?",
            extra=extra,
            advance=True,
        )

    assert result["ok"] is True
    val = state.answers.get("wbs_user_eligibility", "")
    assert val and "karyawan internal" in str(val), \
        f"answer_and_question should write user_answer; got {val!r}"


def test_empty_user_answer_no_write():
    """Defensive: empty user_answer should not create empty entry."""
    engine, state, repo, flow = _make_engine_with_state()
    extra = {"dual_agent_meta": {"type": "answer_only", "next_question": True}}

    with _patch_flow(engine, flow):
        result = engine.commit_turn(
            session_id="test-session",
            user_answer="   ",
            extra=extra,
            advance=False,
        )

    val = state.answers.get("wbs_user_eligibility", "")
    assert val == "" or val is None, \
        f"empty answer should not be committed; got {val!r}"


def test_dual_agent_meta_persisted_even_when_no_answer_write():
    """dual_agent_meta should be saved to state even on question_only turns
    (it's diagnostic data, not lead data)."""
    engine, state, repo, flow = _make_engine_with_state()
    dam = {"type": "question_only", "next_question": False, "warnings_shown": 0}
    extra = {"dual_agent_meta": dam}

    with _patch_flow(engine, flow):
        engine.commit_turn(
            session_id="test-session",
            user_answer="why?",
            extra=extra,
            advance=False,
        )

    assert state.dual_agent_meta == dam, \
        f"dual_agent_meta must persist; got {state.dual_agent_meta!r}"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS: {name}")
            except AssertionError as e:
                print(f"FAIL: {name}: {e}")
                failures += 1
            except Exception as e:
                print(f"ERROR: {name}: {type(e).__name__}: {e}")
                failures += 1
    if failures:
        sys.exit(1)
    print("\nAll tests passed.")
