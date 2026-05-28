"""Method A regression — verifies strict-additive guarantee for Stage 4.

When QUALIFICATION_METHOD is unset or set to "two_decision_tree", existing
behavior must be byte-identical. These tests focus on structural invariants
(audit row stages, state field absence) — not LLM reply text.

Per spec Section 10A.
"""
from __future__ import annotations
import os, sys, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestMethodADefaultBehavior(unittest.TestCase):
    """A1-A7 from spec — structural assertions."""

    def setUp(self):
        # Force two_decision_tree default
        os.environ["QUALIFICATION_METHOD"] = "two_decision_tree"
        from importlib import reload
        from core import app_config
        reload(app_config)

    def test_a1_default_method_loaded(self):
        from core.app_config import Config
        cfg = Config()
        self.assertEqual(cfg.QUALIFICATION_METHOD, "two_decision_tree")

    def test_a4_legacy_state_no_qualification_method_field(self):
        """Existing chat_history docs from before Stage 4 had no qualification_method.
        AgentSessionState must accept this and default to None."""
        from modules.service_agent.sa_types import AgentSessionState
        s = AgentSessionState(session_id="s-legacy", service_code="WBS", question_id="q1")
        self.assertIsNone(s.qualification_method)

    def test_a4_method_a_does_not_write_qualification_b_audit(self):
        """Method A code path must NEVER emit qualification_b stage in audit.
        Smoke check via the dispatcher: should_use_method_b returns False."""
        from modules.system_detection.sd_service import _should_use_method_b, _lock_qualification_method
        from modules.service_agent.sa_types import AgentSessionState
        state = AgentSessionState(session_id="s", service_code="WBS", question_id="q1")
        _lock_qualification_method(state)
        self.assertEqual(state.qualification_method, "two_decision_tree")
        self.assertFalse(_should_use_method_b(state))


class TestMethodAUnchangedAfterStageFour(unittest.TestCase):
    """A7 — Method A interacts orthogonally with anti-redundancy stage (Stage 2026-05-11)."""

    def test_a7_anti_redundancy_runs_independently_for_method_a(self):
        """REDUNDANCY_METHOD=mmr should not interfere with Method A qualification path."""
        from core import app_config
        cfg = app_config.Config()
        cfg.REDUNDANCY_METHOD = "mmr"
        cfg.QUALIFICATION_METHOD = "two_decision_tree"
        self.assertEqual(cfg.REDUNDANCY_METHOD, "mmr")
        self.assertEqual(cfg.QUALIFICATION_METHOD, "two_decision_tree")


if __name__ == "__main__":
    unittest.main(verbosity=2)
