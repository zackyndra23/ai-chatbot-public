"""Validation for QUALIFICATION_METHOD env knob."""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestQualificationMethodConfig(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("QUALIFICATION_METHOD", None)
        # Patch load_dotenv to prevent .env override during reload(app_config).
        # Stage 2026-05-12: .env now contains QUALIFICATION_METHOD (Phase 2 sync
        # of Stage 4.5 testing setup). Without this patch, load_dotenv(override=True)
        # clobbers test-set os.environ values, defeating env-var wiring tests.
        # Patch target MUST be `dotenv.load_dotenv` (source), NOT
        # `core.app_config.load_dotenv` (alias) — reload(app_config) re-runs
        # `from dotenv import load_dotenv` which would otherwise restore the
        # original function reference and undo a module-alias-level patch.
        self._patcher = patch("dotenv.load_dotenv")
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        if self._saved is not None:
            os.environ["QUALIFICATION_METHOD"] = self._saved

    def test_default_is_two_decision_tree(self):
        from importlib import reload
        from core import app_config
        reload(app_config)
        cfg = app_config.Config()
        self.assertEqual(cfg.QUALIFICATION_METHOD, "two_decision_tree")

    def test_natural_qualification_accepted(self):
        os.environ["QUALIFICATION_METHOD"] = "natural_qualification"
        from importlib import reload
        from core import app_config
        reload(app_config)
        cfg = app_config.Config()
        self.assertEqual(cfg.QUALIFICATION_METHOD, "natural_qualification")

    def test_unknown_value_rejected(self):
        os.environ["QUALIFICATION_METHOD"] = "lazy_evaluator"
        from importlib import reload
        from core import app_config
        with self.assertRaises(SystemExit) as ctx:
            reload(app_config)
        self.assertIn("QUALIFICATION_METHOD", str(ctx.exception))
        self.assertIn("lazy_evaluator", str(ctx.exception))

    def test_case_insensitive(self):
        os.environ["QUALIFICATION_METHOD"] = "Natural_Qualification"
        from importlib import reload
        from core import app_config
        reload(app_config)
        cfg = app_config.Config()
        self.assertEqual(cfg.QUALIFICATION_METHOD, "natural_qualification")


if __name__ == "__main__":
    unittest.main(verbosity=2)
