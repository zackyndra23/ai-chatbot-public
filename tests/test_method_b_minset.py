"""Method B minimum-set resolution (Stage 2026-05-12).

Tests use runtime FLOW_REGISTRY introspection (audit methodology principle —
NOT static regex on sa_flows.py).
"""
from __future__ import annotations
import os, sys, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestResolveMinSet(unittest.TestCase):
    def test_conventional_flow_uses_suffix_priority(self):
        from modules.service_agent.sa_flows import FLOW_REGISTRY
        from modules.service_agent.natural_qual.nq_minset import resolve_min_set
        # ABMS follows convention: abms_user_role / abms_main_objective /
        # abms_client_company_profile
        result = resolve_min_set("ABMS", FLOW_REGISTRY["ABMS"])
        self.assertEqual(result["user_role"], "abms_user_role")
        self.assertEqual(result["main_objective"], "abms_main_objective")
        self.assertEqual(result["company_profile"], "abms_client_company_profile")

    def test_wbs_uses_explicit_override(self):
        from modules.service_agent.sa_flows import FLOW_REGISTRY
        from modules.service_agent.natural_qual.nq_minset import resolve_min_set
        # WBS has no buyer-role field — explicit override uses wbs_case_handlers
        result = resolve_min_set("WBS", FLOW_REGISTRY["WBS"])
        self.assertEqual(result["user_role"], "wbs_case_handlers")
        self.assertEqual(result["main_objective"], "wbs_main_objective")
        self.assertEqual(result["company_profile"], "wbs_company_profile")

    def test_ebs_uses_explicit_override(self):
        from modules.service_agent.sa_flows import FLOW_REGISTRY
        from modules.service_agent.natural_qual.nq_minset import resolve_min_set
        result = resolve_min_set("EBS", FLOW_REGISTRY["EBS"])
        self.assertEqual(result["user_role"], "ebs_user_role")
        self.assertEqual(result["main_objective"], "ebs_project_type")
        self.assertEqual(result["company_profile"], "ebs_company_profile")

    def test_msg_uses_default_convention(self):
        from modules.service_agent.sa_flows import FLOW_REGISTRY
        from modules.service_agent.natural_qual.nq_minset import resolve_min_set
        result = resolve_min_set("MSG", FLOW_REGISTRY["MSG"])
        self.assertEqual(result["user_role"], "msg_user_role")
        self.assertEqual(result["main_objective"], "msg_main_objective")
        self.assertEqual(result["company_profile"], "msg_company_profile")

    def test_all_13_flows_resolve_without_error(self):
        from modules.service_agent.sa_flows import FLOW_REGISTRY
        from modules.service_agent.natural_qual.nq_minset import resolve_min_set
        for flow_code in FLOW_REGISTRY:
            result = resolve_min_set(flow_code, FLOW_REGISTRY[flow_code])
            self.assertEqual(set(result.keys()), {"user_role", "main_objective", "company_profile"})
            for slot, field_name in result.items():
                self.assertTrue(field_name, f"{flow_code}.{slot} resolved to empty string")

    def test_min_set_complete_helper(self):
        from modules.service_agent.natural_qual.nq_minset import is_min_set_complete
        min_set = {"user_role": "wbs_case_handlers", "main_objective": "wbs_main_objective",
                   "company_profile": "wbs_company_profile"}
        # All three filled
        answers_full = {"wbs_case_handlers": "Compliance", "wbs_main_objective": "GDPR compliance",
                        "wbs_company_profile": "FinTech, 500 employees"}
        self.assertTrue(is_min_set_complete(min_set, answers_full))
        # One empty
        answers_partial = {"wbs_case_handlers": "Compliance", "wbs_main_objective": "",
                           "wbs_company_profile": "FinTech"}
        self.assertFalse(is_min_set_complete(min_set, answers_partial))
        # Missing key entirely
        answers_missing = {"wbs_case_handlers": "Compliance"}
        self.assertFalse(is_min_set_complete(min_set, answers_missing))


if __name__ == "__main__":
    unittest.main(verbosity=2)
