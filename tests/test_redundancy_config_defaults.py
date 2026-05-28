"""Defaults for the 8 REDUNDANCY_* knobs added in the anti-redundancy stage.

Run (stdlib only, no pytest):
    python tests/test_redundancy_config_defaults.py
"""
from __future__ import annotations
import os, sys, unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestRedundancyConfigDefaults(unittest.TestCase):
    def setUp(self):
        # Clear any pre-existing REDUNDANCY_* env so we test pure defaults.
        self._saved = {k: v for k, v in os.environ.items() if k.startswith("REDUNDANCY_")}
        for k in list(self._saved):
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            os.environ[k] = v

    def test_method_default_is_mmr(self):
        # Default flipped from "normal" to "mmr" on 2026-05-12 after targeted
        # QA run confirmed MMR as the best-performing method on FAQ-RAG path
        # (rc_count_final=11 vs 10/10/0, correct recap bypass, faster latency).
        from importlib import reload
        from core import app_config
        reload(app_config)
        cfg = app_config.Config()
        self.assertEqual(cfg.REDUNDANCY_METHOD, "mmr")

    def test_all_eight_knobs_have_defaults(self):
        from importlib import reload
        from core import app_config
        reload(app_config)
        cfg = app_config.Config()
        self.assertEqual(cfg.REDUNDANCY_METHOD, "mmr")
        self.assertAlmostEqual(cfg.REDUNDANCY_FUZZY_THRESHOLD, 0.85)
        self.assertAlmostEqual(cfg.REDUNDANCY_EMBEDDING_THRESHOLD, 0.92)
        self.assertAlmostEqual(cfg.REDUNDANCY_MMR_LAMBDA, 0.7)
        self.assertEqual(cfg.REDUNDANCY_MMR_FETCH_K_MULTIPLIER, 2)
        self.assertEqual(cfg.REDUNDANCY_RECENT_CHUNKS_WINDOW, 5)
        self.assertEqual(cfg.REDUNDANCY_RECENT_CHUNKS_SPILLOVER, 2)
        self.assertTrue(cfg.REDUNDANCY_RECAP_BYPASS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
