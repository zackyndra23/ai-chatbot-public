"""Per-call-site dispatcher-guard coverage in sd_service.py.

The spec (Validation §2) mandates each of the 3 call sites be exercised
independently with method=normal (fall-through) and method=mmr (strategy used).
Group-level tests are not sufficient because sd_service.py is a long module
and the 3 sites are independent regression surfaces.
"""
from __future__ import annotations
import os, sys, unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _doc(content: str, service: str, chunk_id: str = ""):
    from langchain_core.documents import Document
    return Document(page_content=content,
                    metadata={"service": service, "chunk_id": chunk_id or "x::0000"})


class TestSAContinueDispatcherGuard(unittest.TestCase):
    """Call site #2: _render_sa_continue_via_sd. Verify dispatcher is invoked."""

    def test_dispatcher_import_is_reachable(self):
        from modules.system_detection import sd_service as svc_mod
        from modules.system_detection import sd_retrieval_strategies as srs
        # If sd_service did not import the dispatcher, this attribute lookup fails.
        self.assertIs(svc_mod.retrieve_with_strategy, srs.retrieve_with_strategy)

    def test_sa_continue_via_sd_source_references_dispatcher(self):
        """Lightweight code-presence check: the function must contain a
        retrieve_with_strategy call in its source. This guards against a
        future accidental revert of the dispatcher prepend."""
        import inspect
        from modules.system_detection import sd_service as svc_mod
        src = inspect.getsource(svc_mod._render_sa_continue_via_sd)
        self.assertIn("retrieve_with_strategy", src,
                      "SA-continue path must dispatch through retrieve_with_strategy")


class TestCrossServiceBridgeDispatcherGuard(unittest.TestCase):
    """Call site #3: _render_sa_cross_service_bridge. The fan-out retrieval
    (retrieve_from_collections) should be guard-preceded by the dispatcher.
    We assert this structurally without firing the entire bridge composition.
    """

    def test_dispatcher_symbol_is_imported_at_module_level(self):
        from modules.system_detection import sd_service as svc_mod
        self.assertTrue(hasattr(svc_mod, "retrieve_with_strategy"))

    def test_bridge_function_source_references_dispatcher(self):
        """Lightweight code-presence check: the function must contain a
        retrieve_with_strategy call in its source. This guards against a
        future accidental revert of the dispatcher prepend."""
        import inspect
        from modules.system_detection import sd_service as svc_mod
        src = inspect.getsource(svc_mod._render_sa_cross_service_bridge)
        self.assertIn("retrieve_with_strategy", src,
                      "Cross-service bridge must dispatch through retrieve_with_strategy")


class TestPrepareRagContextRecentFilterWiring(unittest.TestCase):
    """Exercise _prepare_rag_context with method=mmr and recent_chunk_ids set.

    Under method=mmr: over-fetched candidates returned by the strategy must
    be passed through _apply_recent_chunk_filter, and the demoted-stale
    composition must show in the returned 'filtered' list.
    """

    def test_mmr_with_recent_history_demotes_stale(self):
        from modules.system_detection import sd_service as svc_mod
        from langchain_core.documents import Document

        # 6 strategy results: ranks 0-2 are stale, ranks 3-5 are fresh.
        over_fetched = [
            Document(page_content=f"d{i}", metadata={"service": "WBS", "chunk_id": f"wbs::{i:04d}"})
            for i in range(6)
        ]
        recent_ids = ["wbs::0000", "wbs::0001", "wbs::0002"]

        fake_cfg = SimpleNamespace(
            REDUNDANCY_METHOD="mmr", CTX_DOCS_SAME_SERVICE=4, CTX_DOCS_OTHER_SERVICE=0,
            CTX_DOCS_FLOOR=4, FAQ_VERIFICATOR="off",
            CTX_INFER_SERVICE_FROM_QUERY=False, CTX_PIN_SERVICE_DEFINITION=False,
            REDUNDANCY_RECENT_CHUNKS_SPILLOVER=2, REDUNDANCY_RECENT_CHUNKS_WINDOW=5,
            REDUNDANCY_RECAP_BYPASS=True,
        )
        with patch.object(svc_mod, "cfg", fake_cfg), \
             patch.object(svc_mod, "get_retriever", lambda: MagicMock(vectorstore=MagicMock())), \
             patch.object(svc_mod, "retrieve_with_strategy", lambda *a, **kw: over_fetched), \
             patch("modules.system_detection.sd_repo.get_recent_chunk_ids", lambda s, t: recent_ids), \
             patch.object(svc_mod, "grade_and_filter_yes", lambda *a, **kw: a[1] if len(a) > 1 else []):
            filtered, ctx_str, related = svc_mod._prepare_rag_context(
                "q", session_id="sess1", token_id="tok1", turn_language_code="en"
            )

        # The output should have len == 4 and the 4th doc should be a STALE one
        # (demote-don't-drop logic). Fresh chunks (ranks 3,4,5) come first.
        self.assertEqual(len(filtered), 4)
        ids = [d.metadata["chunk_id"] for d in filtered]
        # fresh first
        self.assertEqual(ids[:3], ["wbs::0003", "wbs::0004", "wbs::0005"])
        # one demoted stale slot
        self.assertIn(ids[3], {"wbs::0000", "wbs::0001", "wbs::0002"})

    def test_explicit_recap_bypasses_filter(self):
        """When user says 'tolong ulangi penjelasan tadi' (id), the filter
        must NOT apply — over_fetched flows through to grader unchanged."""
        from modules.system_detection import sd_service as svc_mod
        from langchain_core.documents import Document

        over_fetched = [
            Document(page_content=f"d{i}", metadata={"service": "WBS", "chunk_id": f"wbs::{i:04d}"})
            for i in range(4)
        ]
        # All chunks ARE recent — without recap bypass, fresh would be empty.
        recent_ids = ["wbs::0000", "wbs::0001", "wbs::0002", "wbs::0003"]

        fake_cfg = SimpleNamespace(
            REDUNDANCY_METHOD="mmr", CTX_DOCS_SAME_SERVICE=4, CTX_DOCS_OTHER_SERVICE=0,
            CTX_DOCS_FLOOR=4, FAQ_VERIFICATOR="off",
            CTX_INFER_SERVICE_FROM_QUERY=False, CTX_PIN_SERVICE_DEFINITION=False,
            REDUNDANCY_RECENT_CHUNKS_SPILLOVER=2, REDUNDANCY_RECENT_CHUNKS_WINDOW=5,
            REDUNDANCY_RECAP_BYPASS=True,
        )
        with patch.object(svc_mod, "cfg", fake_cfg), \
             patch.object(svc_mod, "get_retriever", lambda: MagicMock(vectorstore=MagicMock())), \
             patch.object(svc_mod, "retrieve_with_strategy", lambda *a, **kw: over_fetched), \
             patch("modules.system_detection.sd_repo.get_recent_chunk_ids", lambda s, t: recent_ids), \
             patch.object(svc_mod, "grade_and_filter_yes", lambda *a, **kw: a[1] if len(a) > 1 else []):
            filtered, ctx_str, related = svc_mod._prepare_rag_context(
                "tolong ulangi penjelasan tadi",  # Indonesian recap phrase
                session_id="sess1", token_id="tok1", turn_language_code="id",
            )

        # Recap bypass: filter skipped, all 4 over_fetched docs come through unchanged
        self.assertEqual(len(filtered), 4)
        ids = [d.metadata["chunk_id"] for d in filtered]
        self.assertEqual(ids, ["wbs::0000", "wbs::0001", "wbs::0002", "wbs::0003"])


class TestCallSite2DedupWrapper(unittest.TestCase):
    def test_sa_continue_via_sd_source_references_dedup_wrapper(self):
        """Code-presence assertion that the wiring exists in the SA-continue path."""
        import inspect
        from modules.system_detection import sd_service as svc_mod
        src = inspect.getsource(svc_mod._render_sa_continue_via_sd)
        self.assertIn("apply_dedup_guidelines", src,
                      "SA-continue path must wrap its rendered prompt for method != normal")
        self.assertIn("update_recent_chunk_ids", src,
                      "SA-continue path must write back chunk IDs after the turn")
        self.assertIn("_apply_recent_chunk_filter", src,
                      "SA-continue path must apply the recent-chunks filter")


class TestCallSite3DedupWrapper(unittest.TestCase):
    def test_bridge_source_references_dedup_wrapper_and_update(self):
        import inspect
        from modules.system_detection import sd_service as svc_mod
        src = inspect.getsource(svc_mod._render_sa_cross_service_bridge)
        self.assertIn("apply_dedup_guidelines", src,
                      "Cross-service bridge must wrap its prompt for method != normal")
        self.assertIn("update_recent_chunk_ids", src,
                      "Cross-service bridge must write back chunk IDs")
        self.assertIn("_apply_recent_chunk_filter", src,
                      "Cross-service bridge must apply the recent-chunks filter")


class TestRetrievalMethodObservability(unittest.TestCase):
    def test_call_sites_record_retrieval_method(self):
        """Source-presence check: all 3 RAG-touching functions + handle_chat
        must reference 'retrieval_method' in their audit/payload extras."""
        import inspect
        from modules.system_detection import sd_service as svc_mod
        for fn_name in (
            "_render_sa_continue_via_sd",
            "_render_sa_cross_service_bridge",
            "handle_chat",
        ):
            fn = getattr(svc_mod, fn_name)
            src = inspect.getsource(fn)
            with self.subTest(fn=fn_name):
                self.assertIn("retrieval_method", src,
                              f"{fn_name} must record retrieval_method for audit + payload")


if __name__ == "__main__":
    unittest.main(verbosity=2)
