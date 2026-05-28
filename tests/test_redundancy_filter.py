"""Tests for the recent-chunk-ids Mongo I/O + filter logic.

Run (stdlib only, no pytest):
    python tests/test_redundancy_filter.py
"""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestRecentChunkIdsIO(unittest.TestCase):
    def test_get_returns_empty_list_for_missing_doc(self):
        from modules.system_detection import sd_repo

        fake_coll = MagicMock()
        fake_coll.find_one.return_value = None
        fake_client = MagicMock()
        fake_client.__getitem__.return_value.__getitem__.return_value = fake_coll

        with patch.object(sd_repo, "_mongo_cli", return_value=fake_client):
            out = sd_repo.get_recent_chunk_ids("sess1", "tok1")
        self.assertEqual(out, [])

    def test_get_returns_existing_list(self):
        from modules.system_detection import sd_repo
        fake_coll = MagicMock()
        fake_coll.find_one.return_value = {"recent_chunk_ids": ["wbs::0000", "wbs::0001"]}
        fake_client = MagicMock()
        fake_client.__getitem__.return_value.__getitem__.return_value = fake_coll
        with patch.object(sd_repo, "_mongo_cli", return_value=fake_client):
            out = sd_repo.get_recent_chunk_ids("sess1", "tok1")
        self.assertEqual(out, ["wbs::0000", "wbs::0001"])

    def test_update_appends_and_trims_to_window_times_floor(self):
        from modules.system_detection import sd_repo

        fake_coll = MagicMock()
        # Existing list: 18 entries. Append 4 → 22. Cap = 5 × 4 = 20.
        existing = [f"wbs::{i:04d}" for i in range(18)]
        new_ids = ["wbs::0100", "wbs::0101", "wbs::0102", "wbs::0103"]
        fake_coll.find_one.return_value = {"recent_chunk_ids": existing}

        fake_client = MagicMock()
        fake_client.__getitem__.return_value.__getitem__.return_value = fake_coll

        fake_cfg = SimpleNamespace(
            MONGO_URI="mongodb://x",
            MONGO_DB="db",
            CHAT_HISTORY_COLL="chat_history",
            REDUNDANCY_RECENT_CHUNKS_WINDOW=5,
            CTX_DOCS_FLOOR=4,
        )
        with patch.object(sd_repo, "_mongo_cli", return_value=fake_client), \
             patch.object(sd_repo, "cfg", fake_cfg):
            sd_repo.update_recent_chunk_ids("sess1", "tok1", new_ids)

        # Verify update_one called with $set: recent_chunk_ids of length 20
        # and the LATEST entries are at the tail (oldest dropped).
        fake_coll.update_one.assert_called_once()
        call = fake_coll.update_one.call_args
        update_doc = call.args[1] if len(call.args) > 1 else call.kwargs.get("update")
        set_part = update_doc.get("$set") or {}
        result_list = set_part.get("recent_chunk_ids")
        self.assertEqual(len(result_list), 20)
        # Newest 4 should be the last 4 entries
        self.assertEqual(result_list[-4:], new_ids)
        # First 2 of old should be evicted; result starts with existing[2:]
        self.assertEqual(result_list[0], existing[2])


class TestApplyDedupGuidelines(unittest.TestCase):
    def test_appends_three_bullets_at_end_in_english(self):
        from modules.system_detection import sd_prompts
        base = "You are a helpful assistant.\n\nContext:\nS: WBS\nQ: x\nA: y"
        out = sd_prompts.apply_dedup_guidelines(base, "English")
        self.assertTrue(out.startswith(base))  # original prompt preserved exactly
        # Verifies 3 bullets present
        self.assertIn("Do NOT paraphrase the same point", out)
        self.assertIn("do NOT restate it verbatim", out)
        self.assertIn("I don't have that specific information", out)

    def test_works_for_non_english_language(self):
        from modules.system_detection import sd_prompts
        out = sd_prompts.apply_dedup_guidelines("base prompt", "Indonesia")
        self.assertIn("Do NOT paraphrase", out)  # bullets are in English regardless
        # The "language" arg is forwarded so future i18n is possible, but v0 is English.


class TestIsExplicitRecap(unittest.TestCase):
    """Each language gets one positive + one negative case to guard against
    false-positive substring matches."""

    POSITIVE_CASES = [
        ("id", "tolong ulangi penjelasan tadi"),
        ("id", "bisa diulang lagi?"),
        ("ms", "boleh ulang semula?"),
        ("en", "say that again please"),
        ("en", "can you repeat that?"),
        ("en", "explain again"),
        ("fr", "répétez s'il vous plaît"),
        ("fr", "redites-le"),
        ("de", "wiederholen Sie bitte"),
        ("it", "ripeti per favore"),
        ("pt", "repita por favor"),
        ("es", "repita por favor"),
        ("vi", "lặp lại đi"),
        ("th", "พูดอีกที"),
        ("da", "gentag venligst"),
        ("zh", "再说一遍"),
        ("ja", "もう一度説明してください"),
        ("ru", "повторите пожалуйста"),
    ]
    # Negative cases: words that contain matching roots but mean something else.
    NEGATIVE_CASES = [
        ("id", "saya merasa berulang kali tertarik"),  # 'berulang' contains 'ulang' but root form
        ("id", "apa itu whistleblowing system"),
        ("en", "tell me about your services"),
        ("en", "again is not what I want here"),  # word boundary edge
        ("fr", "bonjour"),
        ("ja", "サービスについて教えて"),
        ("zh", "请告诉我服务详情"),
    ]

    def test_positives(self):
        from modules.system_detection.sd_service import _is_explicit_recap
        for lang, text in self.POSITIVE_CASES:
            with self.subTest(lang=lang, text=text):
                self.assertTrue(
                    _is_explicit_recap(text, lang),
                    f"Expected recap detection for {lang}: {text!r}"
                )

    def test_negatives(self):
        from modules.system_detection.sd_service import _is_explicit_recap
        for lang, text in self.NEGATIVE_CASES:
            with self.subTest(lang=lang, text=text):
                self.assertFalse(
                    _is_explicit_recap(text, lang),
                    f"Expected NO recap detection for {lang}: {text!r}"
                )

    def test_empty_input_is_false(self):
        from modules.system_detection.sd_service import _is_explicit_recap
        self.assertFalse(_is_explicit_recap("", "id"))
        self.assertFalse(_is_explicit_recap(None, "id"))

    def test_unknown_language_does_not_crash(self):
        from modules.system_detection.sd_service import _is_explicit_recap
        # Unknown language code → fall back to English patterns
        self.assertTrue(_is_explicit_recap("say that again", "zz"))
        self.assertFalse(_is_explicit_recap("hello", "zz"))


def _doc_with_id(text: str, chunk_id: str):
    from langchain_core.documents import Document
    return Document(page_content=text, metadata={"chunk_id": chunk_id})


class TestApplyRecentChunkFilter(unittest.TestCase):
    def test_all_fresh_returns_top_floor(self):
        from modules.system_detection.sd_service import _apply_recent_chunk_filter
        candidates = [_doc_with_id(f"d{i}", f"wbs::{i:04d}") for i in range(6)]
        recent = ["wbs::9999"]  # nothing in candidates matches
        out = _apply_recent_chunk_filter(candidates, recent, floor=4)
        self.assertEqual(len(out), 4)
        self.assertEqual([d.metadata["chunk_id"] for d in out],
                         ["wbs::0000", "wbs::0001", "wbs::0002", "wbs::0003"])

    def test_mixed_demotes_stale_to_tail(self):
        from modules.system_detection.sd_service import _apply_recent_chunk_filter
        # Ranks 0,1,2 stale; ranks 3,4,5 fresh. Floor=4 → fresh first (3,4,5)
        # then stale at position 4 (rank 0 demoted).
        candidates = [_doc_with_id(f"d{i}", f"wbs::{i:04d}") for i in range(6)]
        recent = ["wbs::0000", "wbs::0001", "wbs::0002"]
        out = _apply_recent_chunk_filter(candidates, recent, floor=4)
        self.assertEqual(len(out), 4)
        ids = [d.metadata["chunk_id"] for d in out]
        # Fresh ones (3,4,5) come first in original rank order, then one stale
        self.assertEqual(ids[:3], ["wbs::0003", "wbs::0004", "wbs::0005"])
        # 4th slot filled from stale (rank-0 demoted)
        self.assertEqual(ids[3], "wbs::0000")

    def test_all_stale_returns_floor_from_stale(self):
        """Filter must never drop below floor — return stale rather than truncate."""
        from modules.system_detection.sd_service import _apply_recent_chunk_filter
        candidates = [_doc_with_id(f"d{i}", f"wbs::{i:04d}") for i in range(6)]
        recent = [f"wbs::{i:04d}" for i in range(6)]  # all candidates are stale
        out = _apply_recent_chunk_filter(candidates, recent, floor=4)
        self.assertEqual(len(out), 4)
        # All 4 are stale, preserved in rank order
        self.assertEqual([d.metadata["chunk_id"] for d in out],
                         ["wbs::0000", "wbs::0001", "wbs::0002", "wbs::0003"])


class TestExtractChunkIdsFromDocs(unittest.TestCase):
    def test_extracts_metadata_chunk_id(self):
        from modules.system_detection.sd_service import _extract_chunk_ids_from_docs
        docs = [_doc_with_id("a", "wbs::0000"), _doc_with_id("b", "wbs::0001")]
        self.assertEqual(_extract_chunk_ids_from_docs(docs), ["wbs::0000", "wbs::0001"])

    def test_skips_docs_without_chunk_id(self):
        from langchain_core.documents import Document
        from modules.system_detection.sd_service import _extract_chunk_ids_from_docs
        docs = [_doc_with_id("a", "wbs::0000"), Document(page_content="b", metadata={}),
                _doc_with_id("c", "wbs::0002")]
        self.assertEqual(_extract_chunk_ids_from_docs(docs), ["wbs::0000", "wbs::0002"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
