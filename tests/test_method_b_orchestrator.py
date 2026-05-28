"""Method B orchestrator — 10-step handle_turn integration tests with mocks."""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _make_state(**overrides):
    from modules.service_agent.sa_types import AgentSessionState
    defaults = dict(
        session_id="s-test", service_code="ABMS", question_id="abms.user_role_1",
        service_label="Anti-Bribery Management System", language_code="id",
        language_name="Indonesia",
        qualification_method="natural_qualification",
        turn_index=0, dry_count={}, rescue_attempted=[],
        fallback_skipped_fields=[], answers={},
    )
    defaults.update(overrides)
    return AgentSessionState(**defaults)


def _mock_agent_output(**overrides):
    base = {
        "message": "Boleh saya tahu peran Anda?",
        "field_writes": {},
        "target_field": "abms_user_role",
        "intent_score": "low",
        "off_topic_detected": False,
        "_parse_error": None,
    }
    base.update(overrides)
    return base


class TestHandleTurnNormalPath(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_normal_turn_increments_turn_index(self, mock_kw, mock_rag, mock_agent):
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        # Agent returns valid JSON
        import json as _json
        mock_agent.return_value = _json.dumps(_mock_agent_output())
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state(turn_index=2)
        result = handle_turn(state, user_message="halo", crisp_profile={}, language_code="id")
        self.assertEqual(state.turn_index, 3)

    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_field_writes_applied_to_state(self, mock_kw, mock_rag, mock_agent):
        import json as _json
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            field_writes={"abms_user_role": "Compliance Officer"},
            target_field="abms_user_role",
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(state, user_message="saya compliance officer", crisp_profile={}, language_code="id")
        self.assertEqual(state.answers.get("abms_user_role"), "Compliance Officer")

    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_keyword_fires_returns_picker(self, mock_kw, mock_rag, mock_agent):
        import json as _json
        mock_kw.return_value = (True, "implicit")
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output())
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(state, user_message="janji temu pak", crisp_profile={}, language_code="id")
        self.assertTrue(result.get("picker_offered"))
        self.assertEqual(result.get("picker_offer_reason"), "keyword_implicit")


class TestRescuePath(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_dry_count_3_triggers_rescue_skip_llm(self, mock_kw, mock_rag, mock_agent):
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        # Agent should NOT be called this turn — rescue path is deterministic
        mock_agent.side_effect = AssertionError("agent should NOT be invoked during rescue turn")
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        # ABMS has abms_user_role at order=15
        state = _make_state(dry_count={"abms_user_role": 3})
        result = handle_turn(state, user_message="apa lagi yang harus saya tahu?",
                             crisp_profile={}, language_code="id")
        # Rescue fired
        self.assertIn("abms_user_role", state.rescue_attempted)
        self.assertEqual(result.get("rescue_fired"), True)
        self.assertEqual(result.get("rescue_field"), "abms_user_role")

    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_rescue_failed_marks_fallback_skipped(self, mock_kw, mock_rag, mock_agent):
        import json as _json
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        # Agent emits target=abms_user_role but no field_writes — so still empty
        mock_agent.return_value = _json.dumps(_mock_agent_output())
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        # Field is already in rescue_attempted (from previous turn) AND still empty
        state = _make_state(
            dry_count={"abms_user_role": 3},
            rescue_attempted=["abms_user_role"],
            answers={"abms_user_role": ""},
        )
        result = handle_turn(state, user_message="ngga mau jawab itu", crisp_profile={}, language_code="id")
        # Field added to fallback_skipped_fields, cleared from dry_count + rescue_attempted
        self.assertIn("abms_user_role", state.fallback_skipped_fields)
        self.assertNotIn("abms_user_role", state.dry_count)
        self.assertNotIn("abms_user_role", state.rescue_attempted)


class TestSkipFieldOnVolunteerCleanup(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_user_volunteers_skipped_field_removes_from_skip_list(self, mock_kw, mock_rag, mock_agent):
        import json as _json
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            field_writes={"abms_budget_range": "USD 50k-100k"},
            target_field="abms_budget_range",
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state(
            fallback_skipped_fields=["abms_budget_range"],
        )
        result = handle_turn(state, user_message="oh budgetnya USD 50k-100k", crisp_profile={}, language_code="id")
        self.assertEqual(state.answers.get("abms_budget_range"), "USD 50k-100k")
        # Removed from skip-list since user volunteered
        self.assertNotIn("abms_budget_range", state.fallback_skipped_fields)


class TestRecentHistoryWiring(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator.render_prompt")
    def test_orchestrator_passes_recent_history_to_agent(
        self, mock_render, mock_history, mock_kw, mock_rag, mock_agent,
    ):
        """Regression: nq_orchestrator must NOT hardcode recent_history=[]. It
        must call _read_recent_chat_history and pass the result into the
        prompt context."""
        import json as _json
        captured_ctx = {}

        def capture_ctx(ctx):
            captured_ctx.update(ctx)
            return "rendered-prompt-stub"
        mock_render.side_effect = capture_ctx
        mock_history.return_value = [
            {"q": f"user-msg-{i}", "m": f"bot-msg-{i}"} for i in range(5)
        ]
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output())

        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        handle_turn(state, user_message="halo", crisp_profile={}, language_code="id")

        # Helper was called
        self.assertTrue(mock_history.called,
                        "_read_recent_chat_history must be called")
        # Captured prompt ctx has the formatted block containing all 5 turns
        block = captured_ctx.get("recent_history_block", "")
        self.assertIn("user-msg-0", block, f"first turn missing in block: {block!r}")
        self.assertIn("user-msg-4", block, f"fifth turn missing in block: {block!r}")


class TestVerbatimRetry(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_verbatim_retry_fires_once_on_violation(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        """First agent response has paraphrased value -> retry fires -> second
        response is clean -> field committed correctly."""
        import json as _json
        mock_history.return_value = []
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        # First call: paraphrased value not in user_message
        # Second call: verbatim value present in user_message
        mock_agent.side_effect = [
            _json.dumps(_mock_agent_output(
                field_writes={"abms_user_role": "Head of Compliance"},
                target_field="abms_user_role",
                interest_signal="interest_answer",
                intent_score="medium",
            )),
            _json.dumps(_mock_agent_output(
                field_writes={"abms_user_role": "compliance head"},
                target_field="abms_user_role",
                interest_signal="interest_answer",
                intent_score="medium",
            )),
        ]
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        # user_message contains "compliance head" verbatim, NOT "Head of Compliance"
        result = handle_turn(
            state, user_message="saya compliance head di Acme",
            crisp_profile={}, language_code="id",
        )
        self.assertEqual(mock_agent.call_count, 2, "agent must be called twice (retry)")
        self.assertEqual(state.answers.get("abms_user_role"), "compliance head")
        self.assertTrue(result.get("verbatim_retry_fired"))

    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_verbatim_retry_still_bad_drops_field(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        """Both first and retry responses contain non-verbatim writes -> field
        is dropped silently from field_writes, state.answers unaffected."""
        import json as _json
        mock_history.return_value = []
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.side_effect = [
            _json.dumps(_mock_agent_output(
                field_writes={"abms_user_role": "Head of Compliance"},
                target_field="abms_user_role",
            )),
            _json.dumps(_mock_agent_output(
                field_writes={"abms_user_role": "Compliance Director"},
                target_field="abms_user_role",
            )),
        ]
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(
            state, user_message="saya compliance head di Acme",
            crisp_profile={}, language_code="id",
        )
        self.assertEqual(mock_agent.call_count, 2)
        # Field NOT committed
        self.assertEqual(state.answers.get("abms_user_role", ""), "")
        self.assertTrue(result.get("verbatim_retry_fired"))

    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_verbatim_no_retry_when_clean(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        """First response is already verbatim -> no retry, retry flag False."""
        import json as _json
        mock_history.return_value = []
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            field_writes={"abms_user_role": "compliance officer"},
            target_field="abms_user_role",
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(
            state, user_message="saya compliance officer",
            crisp_profile={}, language_code="id",
        )
        self.assertEqual(mock_agent.call_count, 1)
        self.assertEqual(state.answers.get("abms_user_role"), "compliance officer")
        self.assertFalse(result.get("verbatim_retry_fired"))

    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_verbatim_uses_history_text_too(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        """Value matching history (not current_message) passes verbatim check."""
        import json as _json
        mock_history.return_value = [
            {"q": "halo, saya head of HR di Acme Corp", "m": "halo!"},
        ]
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            field_writes={"abms_user_role": "head of HR"},
            target_field="abms_main_objective",
            interest_signal="interest_answer",
            intent_score="medium",
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(
            state, user_message="iya saya tertarik WBS",
            crisp_profile={}, language_code="id",
        )
        # No retry — value is in history
        self.assertEqual(mock_agent.call_count, 1)
        self.assertEqual(state.answers.get("abms_user_role"), "head of HR")


class TestAuditExtrasAndState(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_audit_extras_populated_after_normal_turn(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        import json as _json
        mock_history.return_value = []
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            field_writes={"abms_user_role": "compliance officer"},
            target_field="abms_user_role",
            interest_signal="interest_answer",
            intent_score="medium",
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(
            state, user_message="saya compliance officer",
            crisp_profile={}, language_code="id",
        )
        # New audit extras present
        self.assertEqual(result.get("interest_signal"), "interest_answer")
        self.assertIn("verbatim_retry_fired", result)
        self.assertIn("field_writes_sources", result)
        self.assertIn("consistency_warns_count", result)
        # State carries last_interest_signal
        self.assertEqual(state.last_interest_signal, "interest_answer")
        # Source classification — value matched current_message
        self.assertEqual(result["field_writes_sources"].get("abms_user_role"),
                         "current_message")

    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_field_writes_sources_marks_history(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        import json as _json
        mock_history.return_value = [
            {"q": "halo, saya head of HR di Acme Corp", "m": "halo!"},
        ]
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            field_writes={"abms_user_role": "head of HR"},
            target_field="abms_main_objective",
            interest_signal="interest_answer",
            intent_score="medium",
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(
            state, user_message="iya saya tertarik WBS",
            crisp_profile={}, language_code="id",
        )
        self.assertEqual(result["field_writes_sources"].get("abms_user_role"),
                         "history")

    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_consistency_warns_count_from_parse(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        """When parse layer normalizes (e.g., not_interested + intent=high), the
        warn count surfaces in audit row."""
        import json as _json
        mock_history.return_value = []
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            interest_signal="not_interested",
            intent_score="high",  # will be forced to low -> 1 warning
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(
            state, user_message="ngga dulu deh",
            crisp_profile={}, language_code="id",
        )
        self.assertGreaterEqual(result.get("consistency_warns_count", 0), 1)
        self.assertEqual(state.last_interest_signal, "not_interested")


class TestNotInterestedBehavior(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_not_interested_no_writes_no_question_no_picker(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        """not_interested -> empty field_writes, null target_field, low intent,
        picker not offered, state.last_interest_signal records the signal."""
        import json as _json
        mock_history.return_value = []
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            field_writes={},
            target_field=None,
            intent_score="low",
            interest_signal="not_interested",
            off_topic_detected=False,
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        # Pre-state: min-set is complete already (so picker conditions could fire
        # if intent were not low) — proves the not_interested branch suppresses
        # picker even when other conditions hold.
        state = _make_state(
            answers={
                "abms_user_role": "compliance officer",
                "abms_main_objective": "audit",
                "abms_company_profile": "Acme",
            },
        )
        result = handle_turn(
            state, user_message="ngga dulu deh, masih cari-cari",
            crisp_profile={}, language_code="id",
        )
        # No new field_writes
        self.assertEqual(result.get("field_writes_count"), 0)
        # target_field stays null
        self.assertIsNone(result.get("target_field"))
        # intent_score is low
        self.assertEqual(result.get("intent_score"), "low")
        # interest_signal recorded
        self.assertEqual(result.get("interest_signal"), "not_interested")
        # Picker NOT offered
        self.assertFalse(result.get("picker_offered"))
        # State carries last_interest_signal
        self.assertEqual(state.last_interest_signal, "not_interested")


class TestOffTopicPassThrough(unittest.TestCase):
    @patch("modules.service_agent.natural_qual.nq_orchestrator._read_recent_chat_history")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._invoke_agent_for_turn")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._retrieve_rag_context")
    @patch("modules.service_agent.natural_qual.nq_orchestrator._check_keyword_meeting_intent")
    def test_off_topic_message_preserves_paragraph_separators(
        self, mock_kw, mock_rag, mock_agent, mock_history,
    ):
        """Agent emits 3-paragraph message with 2 \\n\\n separators —
        orchestrator must not strip / normalize them."""
        import json as _json
        mock_history.return_value = []
        mock_kw.return_value = (False, None)
        mock_rag.return_value = ("", [])
        three_para = (
            "Cuaca memang lagi panas ya.\n\n"
            "Anyway, kembali ke yang tadi kita bahas tentang sistem WBS.\n\n"
            "Apa tujuan utama bisnis Anda untuk implementasi sistem ini?"
        )
        mock_agent.return_value = _json.dumps(_mock_agent_output(
            message=three_para,
            field_writes={},
            target_field="abms_main_objective",
            interest_signal="off_topic",
            intent_score="low",
            off_topic_detected=True,
        ))
        from modules.service_agent.natural_qual.nq_orchestrator import handle_turn
        state = _make_state()
        result = handle_turn(
            state, user_message="iya cuaca panas ya hari ini",
            crisp_profile={}, language_code="id",
        )
        msg = result.get("assistant_message", "")
        self.assertEqual(msg.count("\n\n"), 2,
                         f"expected exactly 2 \\n\\n separators, got message: {msg!r}")
        self.assertIn("Cuaca", msg)
        self.assertIn("Anyway", msg)
        self.assertIn("tujuan utama", msg)
        # Audit field
        self.assertEqual(result.get("interest_signal"), "off_topic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
