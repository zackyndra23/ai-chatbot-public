"""Method B AgentSessionState extensions (Stage 2026-05-12)."""
from __future__ import annotations
import os, sys, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestStateExtensions(unittest.TestCase):
    def test_defaults_method_b_fields(self):
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(session_id="s", service_code="WBS", question_id="q1")
        self.assertIsNone(s.qualification_method)
        self.assertEqual(s.turn_index, 0)
        self.assertEqual(s.dry_count, {})
        self.assertEqual(s.rescue_attempted, [])
        self.assertEqual(s.fallback_skipped_fields, [])
        self.assertIsNone(s.last_intent_score)
        self.assertIsNone(s.last_picker_offer_turn)

    def test_qualification_method_literal_values(self):
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(session_id="s", service_code="WBS", question_id="q1",
                              qualification_method="natural_qualification")
        self.assertEqual(s.qualification_method, "natural_qualification")
        s2 = AgentSessionState(session_id="s", service_code="WBS", question_id="q1",
                               qualification_method="two_decision_tree")
        self.assertEqual(s2.qualification_method, "two_decision_tree")


class TestLastInterestSignal(unittest.TestCase):
    def test_last_interest_signal_default_none(self):
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(session_id="s1", service_code="ABMS", question_id="q1")
        self.assertIsNone(s.last_interest_signal)

    def test_last_interest_signal_assignable(self):
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(session_id="s1", service_code="ABMS", question_id="q1")
        s.last_interest_signal = "not_interested"
        self.assertEqual(s.last_interest_signal, "not_interested")


class TestStateBSONSerializable(unittest.TestCase):
    """Regression: AgentSessionState must round-trip through BSON.

    Stage 4.5 originally typed rescue_attempted as `set[str]` which Mongo
    cannot encode (bson.errors.InvalidDocument). Server returned HTTP 500
    on every new session before this was fixed to List[str].

    Broader future-proofing: tests below populate ALL Stage 4 + 4.5 schema
    fields and verify BSON round-trip, so any future schema additions that
    introduce non-encodable types are caught at unit-test time.
    """

    def _dump(self, s):
        return s.model_dump() if hasattr(s, "model_dump") else s.dict()

    def test_state_bson_encodable_default(self):
        import bson
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(session_id="s-bson-1", service_code="ABMS", question_id="q1")
        d = self._dump(s)
        try:
            encoded = bson.encode(d)
            decoded = bson.decode(encoded)
        except bson.errors.InvalidDocument as e:
            self.fail(f"Empty AgentSessionState not BSON-encodable: {e}")
        self.assertIsInstance(decoded["rescue_attempted"], list)
        self.assertEqual(decoded["rescue_attempted"], [])

    def test_state_bson_encodable_with_rescue_entries(self):
        import bson
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(session_id="s-bson-2", service_code="ABMS", question_id="q1")
        s.rescue_attempted.append("abms_user_role")
        s.rescue_attempted.append("abms_main_objective")
        d = self._dump(s)
        try:
            encoded = bson.encode(d)
            decoded = bson.decode(encoded)
        except bson.errors.InvalidDocument as e:
            self.fail(f"AgentSessionState with rescue entries not BSON-encodable: {e}")
        self.assertEqual(decoded["rescue_attempted"], ["abms_user_role", "abms_main_objective"])

    def test_state_bson_encodable_all_stage_4_5_fields(self):
        """Populate every Stage 4 + 4.5 field, round-trip through BSON, verify
        all values survive. Catches any future schema addition that introduces
        a non-encodable type."""
        import bson
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(
            session_id="s-bson-3",
            service_code="ABMS",
            question_id="abms.user_role_1",
            service_label="Anti-Bribery Management System",
            language_code="id",
            language_name="Indonesia",
            qualification_method="natural_qualification",
            turn_index=5,
            dry_count={"abms_user_role": 2, "abms_main_objective": 1},
            rescue_attempted=["abms_company_profile"],
            fallback_skipped_fields=["abms_budget_range"],
            last_intent_score="medium",
            last_picker_offer_turn=3,
            last_interest_signal="interest_answer",
            answers={"abms_user_role": "compliance officer"},
        )
        d = self._dump(s)
        try:
            encoded = bson.encode(d)
            decoded = bson.decode(encoded)
        except bson.errors.InvalidDocument as e:
            self.fail(f"AgentSessionState with all fields populated not BSON-encodable: {e}")
        # Spot-check every Stage 4 + 4.5 field survives the round-trip
        self.assertEqual(decoded["qualification_method"], "natural_qualification")
        self.assertEqual(decoded["turn_index"], 5)
        self.assertEqual(decoded["dry_count"], {"abms_user_role": 2, "abms_main_objective": 1})
        self.assertEqual(decoded["rescue_attempted"], ["abms_company_profile"])
        self.assertEqual(decoded["fallback_skipped_fields"], ["abms_budget_range"])
        self.assertEqual(decoded["last_intent_score"], "medium")
        self.assertEqual(decoded["last_picker_offer_turn"], 3)
        self.assertEqual(decoded["last_interest_signal"], "interest_answer")
        self.assertEqual(decoded["answers"], {"abms_user_role": "compliance officer"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
