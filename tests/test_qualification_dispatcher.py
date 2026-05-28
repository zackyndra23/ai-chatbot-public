"""Verify Method A vs Method B dispatch + method-lock behavior at SA continuation."""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestQualificationDispatcher(unittest.TestCase):
    def test_state_qualification_method_locked_on_first_call(self):
        """When state.qualification_method is None, env is read once and persisted."""
        from modules.service_agent.sa_service import SA_ENGINE
        from modules.service_agent.sa_types import AgentSessionState
        state = AgentSessionState(session_id="s-lock-1", service_code="WBS", question_id="wbs.availability_countries_1")
        state.qualification_method = None
        with patch.dict(os.environ, {"QUALIFICATION_METHOD": "natural_qualification"}, clear=False):
            from importlib import reload
            from core import app_config
            reload(app_config)
            from modules.system_detection.sd_service import _lock_qualification_method
            _lock_qualification_method(state)
        self.assertEqual(state.qualification_method, "natural_qualification")

    def test_state_qualification_method_honors_existing_value(self):
        """Existing state.qualification_method MUST NOT change on subsequent calls."""
        from modules.service_agent.sa_types import AgentSessionState
        state = AgentSessionState(session_id="s-lock-2", service_code="WBS", question_id="wbs.availability_countries_1")
        state.qualification_method = "two_decision_tree"
        with patch.dict(os.environ, {"QUALIFICATION_METHOD": "natural_qualification"}, clear=False):
            from importlib import reload
            from core import app_config
            reload(app_config)
            from modules.system_detection.sd_service import _lock_qualification_method
            _lock_qualification_method(state)
        self.assertEqual(state.qualification_method, "two_decision_tree")

    def test_dispatcher_routes_to_method_b_when_locked(self):
        from modules.system_detection.sd_service import _should_use_method_b
        from modules.service_agent.sa_types import AgentSessionState
        state = AgentSessionState(session_id="s", service_code="WBS", question_id="q1",
                                  qualification_method="natural_qualification")
        self.assertTrue(_should_use_method_b(state))

    def test_dispatcher_routes_to_method_a_when_locked(self):
        from modules.system_detection.sd_service import _should_use_method_b
        from modules.service_agent.sa_types import AgentSessionState
        state = AgentSessionState(session_id="s", service_code="WBS", question_id="q1",
                                  qualification_method="two_decision_tree")
        self.assertFalse(_should_use_method_b(state))


if __name__ == "__main__":
    unittest.main(verbosity=2)
