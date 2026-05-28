"""Method B policies — rescue templates, picker decision, dry_count update."""
from __future__ import annotations
import os, sys, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestRescueSoftBridge(unittest.TestCase):
    def test_supported_languages(self):
        from modules.service_agent.natural_qual.nq_policies import (
            RESCUE_SOFT_BRIDGE, render_rescue_message,
        )
        expected_langs = {"en","id","ms","th","vi","da","de","es","fr","it","ja","pt","ru","zh"}
        self.assertEqual(set(RESCUE_SOFT_BRIDGE.keys()), expected_langs)

    def test_render_substitutes_question_text(self):
        from modules.service_agent.natural_qual.nq_policies import render_rescue_message
        msg = render_rescue_message("id", "Berapa jumlah karyawan Anda?")
        self.assertIn("Berapa jumlah karyawan Anda?", msg)
        self.assertIn("konfirmasi langsung", msg)

    def test_unknown_lang_falls_back_to_en(self):
        from modules.service_agent.natural_qual.nq_policies import render_rescue_message
        msg = render_rescue_message("tl", "What's your role?")
        self.assertIn("What's your role?", msg)
        self.assertIn("To keep this moving", msg)


class TestDryCountUpdate(unittest.TestCase):
    def test_filled_field_resets(self):
        from modules.service_agent.natural_qual.nq_policies import update_dry_count
        dry_count = {"wbs_main_objective": 2}
        min_set_fields = ["wbs_main_objective", "wbs_company_profile", "wbs_case_handlers"]
        answers = {"wbs_main_objective": "GDPR", "wbs_company_profile": "", "wbs_case_handlers": ""}
        target = "wbs_company_profile"
        new_count = update_dry_count(dry_count, min_set_fields, answers, target)
        self.assertEqual(new_count.get("wbs_main_objective", 0), 0)

    def test_target_empty_increments(self):
        from modules.service_agent.natural_qual.nq_policies import update_dry_count
        dry_count = {"wbs_main_objective": 1}
        min_set_fields = ["wbs_main_objective", "wbs_company_profile", "wbs_case_handlers"]
        answers = {"wbs_main_objective": "", "wbs_company_profile": "", "wbs_case_handlers": ""}
        target = "wbs_main_objective"
        new_count = update_dry_count(dry_count, min_set_fields, answers, target)
        self.assertEqual(new_count["wbs_main_objective"], 2)

    def test_non_target_empty_frozen(self):
        from modules.service_agent.natural_qual.nq_policies import update_dry_count
        dry_count = {"wbs_main_objective": 2}
        min_set_fields = ["wbs_main_objective", "wbs_company_profile", "wbs_case_handlers"]
        answers = {"wbs_main_objective": "", "wbs_company_profile": "", "wbs_case_handlers": ""}
        target = "wbs_company_profile"
        new_count = update_dry_count(dry_count, min_set_fields, answers, target)
        # main_objective empty + not target → FREEZE (not reset)
        self.assertEqual(new_count["wbs_main_objective"], 2)

    def test_interleaved_dodge_reaches_3(self):
        # Test C5 from spec — freeze semantics specifically
        from modules.service_agent.natural_qual.nq_policies import update_dry_count
        min_set_fields = ["X", "Y", "Z"]
        dc: dict[str, int] = {}
        dc = update_dry_count(dc, min_set_fields, {"X":"","Y":"","Z":""}, "X")
        self.assertEqual(dc.get("X", 0), 1)
        dc = update_dry_count(dc, min_set_fields, {"X":"","Y":"answer","Z":""}, "Y")
        self.assertEqual(dc.get("X", 0), 1)  # frozen
        dc = update_dry_count(dc, min_set_fields, {"X":"","Y":"answer","Z":""}, "X")
        self.assertEqual(dc.get("X", 0), 2)
        dc = update_dry_count(dc, min_set_fields, {"X":"","Y":"answer","Z":"answer"}, "Z")
        self.assertEqual(dc.get("X", 0), 2)  # frozen
        dc = update_dry_count(dc, min_set_fields, {"X":"","Y":"answer","Z":"answer"}, "X")
        self.assertEqual(dc.get("X", 0), 3)  # rescue time


class TestPickerDecision(unittest.TestCase):
    def test_keyword_always_fires(self):
        from modules.service_agent.natural_qual.nq_policies import compute_picker_decision
        should, reason = compute_picker_decision(
            keyword_fires=True, keyword_kind="implicit",
            min_set_complete=False, intent_score="low",
            turn_index=5, last_picker_offer_turn=4,
        )
        self.assertTrue(should)
        self.assertEqual(reason, "keyword_implicit")

    def test_min_set_intent_medium_fires_when_cooldown_ok(self):
        from modules.service_agent.natural_qual.nq_policies import compute_picker_decision
        should, reason = compute_picker_decision(
            keyword_fires=False, keyword_kind=None,
            min_set_complete=True, intent_score="medium",
            turn_index=5, last_picker_offer_turn=None,
        )
        self.assertTrue(should)
        self.assertEqual(reason, "min_set_intent_medium")

    def test_cooldown_blocks_min_set_path(self):
        from modules.service_agent.natural_qual.nq_policies import compute_picker_decision
        should, reason = compute_picker_decision(
            keyword_fires=False, keyword_kind=None,
            min_set_complete=True, intent_score="high",
            turn_index=5, last_picker_offer_turn=4,
        )
        self.assertFalse(should)
        self.assertEqual(reason, "cooldown_blocked")

    def test_cooldown_clears_at_2_turn_gap(self):
        from modules.service_agent.natural_qual.nq_policies import compute_picker_decision
        should, reason = compute_picker_decision(
            keyword_fires=False, keyword_kind=None,
            min_set_complete=True, intent_score="medium",
            turn_index=6, last_picker_offer_turn=4,
        )
        self.assertTrue(should)
        self.assertEqual(reason, "min_set_intent_medium")

    def test_intent_low_blocks_min_set_path(self):
        from modules.service_agent.natural_qual.nq_policies import compute_picker_decision
        should, reason = compute_picker_decision(
            keyword_fires=False, keyword_kind=None,
            min_set_complete=True, intent_score="low",
            turn_index=5, last_picker_offer_turn=None,
        )
        self.assertFalse(should)
        self.assertEqual(reason, "none")

    def test_keyword_bypasses_cooldown(self):
        from modules.service_agent.natural_qual.nq_policies import compute_picker_decision
        should, reason = compute_picker_decision(
            keyword_fires=True, keyword_kind="explicit",
            min_set_complete=False, intent_score="low",
            turn_index=4, last_picker_offer_turn=3,
        )
        self.assertTrue(should)
        self.assertEqual(reason, "keyword_explicit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
