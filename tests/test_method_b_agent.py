"""Method B agent — prompt + LLM invocation + structured output validation."""
from __future__ import annotations
import os, sys, unittest, json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestParseAgentOutput(unittest.TestCase):
    def test_valid_json_parses(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({
            "message": "Boleh saya tahu peran Anda?",
            "field_writes": {"wbs_case_handlers": "Compliance"},
            "target_field": "wbs_case_handlers",
            "intent_score": "medium",
            "off_topic_detected": False,
        })
        out = parse_agent_output(raw)
        self.assertEqual(out["target_field"], "wbs_case_handlers")
        self.assertEqual(out["intent_score"], "medium")
        self.assertFalse(out["off_topic_detected"])

    def test_invalid_json_returns_fallback(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        out = parse_agent_output("not json at all")
        self.assertEqual(out["field_writes"], {})
        self.assertEqual(out["intent_score"], "low")
        self.assertIsNone(out["target_field"])

    def test_missing_required_field_returns_fallback(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({"message": "ok", "field_writes": {}, "target_field": None,
                          "off_topic_detected": False})
        out = parse_agent_output(raw)
        self.assertEqual(out["intent_score"], "low")

    def test_invalid_intent_score_normalized(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({"message": "ok", "field_writes": {}, "target_field": None,
                          "intent_score": "very_high", "off_topic_detected": False})
        out = parse_agent_output(raw)
        self.assertEqual(out["intent_score"], "low")


class TestBuildAgentContext(unittest.TestCase):
    def test_context_has_all_keys(self):
        from modules.service_agent.natural_qual.nq_agent import build_agent_context
        ctx = build_agent_context(
            service_code="WBS",
            flow_field_texts={"wbs_main_objective": "What is the main objective?"},
            filled_answers={"wbs_main_objective": "GDPR"},
            empty_fields=["wbs_company_profile"],
            min_set_resolved={"user_role":"wbs_case_handlers","main_objective":"wbs_main_objective","company_profile":"wbs_company_profile"},
            min_set_complete=False,
            dry_count={"wbs_company_profile": 1},
            fallback_skipped_fields=["wbs_budget_range"],
            crisp_contact_present=True,
            recent_history=[{"q": "halo", "m": "halo, ada yang bisa saya bantu?"}],
            rag_chunks="Context: ...",
            user_message="apa fitur WBS?",
            language_code="id",
        )
        self.assertEqual(ctx["service_code"], "WBS")
        self.assertEqual(ctx["language_code"], "id")
        self.assertTrue(ctx["crisp_contact_present"])
        self.assertIn("wbs_budget_range", ctx["fallback_skipped_fields"])
        self.assertIn("Context: ...", ctx["rag_chunks"])


class TestInterestSignalParse(unittest.TestCase):
    def test_interest_signal_4way_parses_valid(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        for sig in ["interest_answer", "not_interested", "question", "off_topic"]:
            raw = json.dumps({
                "message": "ok",
                "field_writes": {},
                "target_field": None,
                "intent_score": "low",
                "interest_signal": sig,
                "off_topic_detected": (sig == "off_topic"),
            })
            out = parse_agent_output(raw)
            self.assertEqual(out["interest_signal"], sig, f"failed for {sig}")
            self.assertEqual(out["warnings"], [])

    def test_interest_signal_missing_defaults_to_interest_answer(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({
            "message": "ok", "field_writes": {}, "target_field": None,
            "intent_score": "low", "off_topic_detected": False,
        })
        out = parse_agent_output(raw)
        self.assertEqual(out["interest_signal"], "interest_answer")

    def test_interest_signal_invalid_normalizes_to_interest_answer(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({
            "message": "ok", "field_writes": {}, "target_field": None,
            "intent_score": "low",
            "interest_signal": "very_engaged",
            "off_topic_detected": False,
        })
        out = parse_agent_output(raw)
        self.assertEqual(out["interest_signal"], "interest_answer")
        self.assertTrue(any("interest_signal" in w for w in out["warnings"]),
                        f"expected interest_signal warning, got {out['warnings']}")

    def test_off_topic_consistency_force_detected_true(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({
            "message": "ok", "field_writes": {}, "target_field": None,
            "intent_score": "low",
            "interest_signal": "off_topic",
            "off_topic_detected": False,
        })
        out = parse_agent_output(raw)
        self.assertTrue(out["off_topic_detected"])
        self.assertTrue(any("off_topic_detected" in w for w in out["warnings"]))

    def test_off_topic_consistency_force_detected_false(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({
            "message": "ok", "field_writes": {}, "target_field": None,
            "intent_score": "medium",
            "interest_signal": "interest_answer",
            "off_topic_detected": True,
        })
        out = parse_agent_output(raw)
        self.assertFalse(out["off_topic_detected"])
        self.assertTrue(any("off_topic_detected" in w for w in out["warnings"]))

    def test_not_interested_forces_intent_low(self):
        from modules.service_agent.natural_qual.nq_agent import parse_agent_output
        raw = json.dumps({
            "message": "ok", "field_writes": {}, "target_field": None,
            "intent_score": "high",
            "interest_signal": "not_interested",
            "off_topic_detected": False,
        })
        out = parse_agent_output(raw)
        self.assertEqual(out["intent_score"], "low")
        self.assertTrue(any("intent_score" in w for w in out["warnings"]))


class TestVerbatimCheck(unittest.TestCase):
    def test_verbatim_drops_non_matching_write(self):
        from modules.service_agent.natural_qual.nq_agent import _check_verbatim
        corpus = "i'm head of hr at acme"
        writes = {"role": "Head of Human Resources"}
        violations = _check_verbatim(writes, corpus)
        self.assertIn("role", violations)

    def test_verbatim_case_insensitive_accepts(self):
        from modules.service_agent.natural_qual.nq_agent import _check_verbatim
        # caller pre-lowercases corpus; value is compared case-insensitively
        corpus = "i'm hr head"
        writes = {"role": "HR Head"}
        violations = _check_verbatim(writes, corpus)
        self.assertEqual(violations, [])

    def test_verbatim_substring_match_accepts(self):
        from modules.service_agent.natural_qual.nq_agent import _check_verbatim
        corpus = "anyway i'm head of hr at acme corp"
        writes = {"role": "head of HR", "company": "Acme Corp"}
        violations = _check_verbatim(writes, corpus)
        self.assertEqual(violations, [])

    def test_verbatim_skips_empty_values(self):
        from modules.service_agent.natural_qual.nq_agent import _check_verbatim
        violations = _check_verbatim({"role": "", "co": "   "}, "anything")
        self.assertEqual(violations, [])

    def test_verbatim_skips_non_string_values(self):
        from modules.service_agent.natural_qual.nq_agent import _check_verbatim
        violations = _check_verbatim({"x": 123, "y": None}, "anything")
        self.assertEqual(violations, [])

    def test_verbatim_returns_multiple_violations(self):
        from modules.service_agent.natural_qual.nq_agent import _check_verbatim
        corpus = "i mentioned acme only"
        writes = {"a": "not in corpus", "b": "Acme", "c": "definitely missing"}
        violations = _check_verbatim(writes, corpus)
        self.assertIn("a", violations)
        self.assertIn("c", violations)
        self.assertNotIn("b", violations)


class TestFormatHistoryBlock(unittest.TestCase):
    def test_format_history_no_slice_returns_all_turns(self):
        from modules.service_agent.natural_qual.nq_agent import _format_history_block
        turns = [{"q": f"user-msg-{i}", "m": f"bot-msg-{i}"} for i in range(12)]
        block = _format_history_block(turns)
        # All 12 turns should be present (no [-4:] slice)
        for i in range(12):
            self.assertIn(f"user-msg-{i}", block, f"missing user-msg-{i}")
            self.assertIn(f"bot-msg-{i}", block, f"missing bot-msg-{i}")

    def test_format_history_empty_list(self):
        from modules.service_agent.natural_qual.nq_agent import _format_history_block
        self.assertEqual(_format_history_block([]),
                         "(no prior conversation in this session)")

    def test_format_history_accepts_alternate_key_names(self):
        from modules.service_agent.natural_qual.nq_agent import _format_history_block
        turns = [{"question": "halo", "message": "halo, ada yang bisa saya bantu?"}]
        block = _format_history_block(turns)
        self.assertIn("halo", block)


class TestPromptTemplateStage45(unittest.TestCase):
    def _render(self):
        from modules.service_agent.natural_qual.nq_agent import (
            build_agent_context, render_prompt,
        )
        ctx = build_agent_context(
            service_code="WBS",
            flow_field_texts={"wbs_main_objective": "What is the main objective?"},
            filled_answers={},
            empty_fields=["wbs_main_objective"],
            min_set_resolved={
                "user_role": "wbs_case_handlers",
                "main_objective": "wbs_main_objective",
                "company_profile": "wbs_company_profile",
            },
            min_set_complete=False,
            dry_count={},
            fallback_skipped_fields=[],
            crisp_contact_present=False,
            recent_history=[],
            rag_chunks="",
            user_message="halo",
            language_code="id",
        )
        return render_prompt(ctx)

    def test_prompt_has_interest_signal_classification_block(self):
        prompt = self._render()
        self.assertIn("INTEREST SIGNAL CLASSIFICATION", prompt)
        for sig in ["interest_answer", "not_interested", "question", "off_topic"]:
            self.assertIn(sig, prompt, f"missing {sig!r} in classification block")

    def test_prompt_has_off_topic_3_paragraph_rule(self):
        prompt = self._render()
        # Rule 5 mentions 3 paragraphs + \n\n separator requirement
        self.assertIn("3 paragraphs", prompt)
        self.assertIn("\\n\\n", prompt)  # literal "\n\n" appears in rule text

    def test_prompt_has_verbatim_rule_in_field_writes(self):
        prompt = self._render()
        self.assertIn("VERBATIM", prompt)
        self.assertIn("Non-verbatim writes will be programmatically rejected",
                      prompt)

    def test_prompt_has_no_reask_rule(self):
        prompt = self._render()
        self.assertIn("NO RE-ASK FROM HISTORY", prompt)

    def test_prompt_output_format_includes_interest_signal(self):
        prompt = self._render()
        # OUTPUT FORMAT JSON schema mentions interest_signal
        self.assertIn("interest_signal", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
