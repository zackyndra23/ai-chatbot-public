"""Unit tests for retrieve_from_collections (Stage 3A fan-out)."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _doc(content: str, service: str):
    from langchain_core.documents import Document
    return Document(page_content=content, metadata={"service": service})


class _FakeChroma:
    def __init__(self, results: list[tuple]):
        # results: list of (Document, distance) tuples
        self._results = results
    def similarity_search_with_score(self, query, k):
        return self._results[:k]


def test_empty_service_ids_returns_empty_list():
    from modules.system_detection import sd_vector_repo as svr
    with patch.object(svr, "_vectorstores", {}):
        out = svr.retrieve_from_collections([], "any query", total_k=4)
    assert out == []


def test_single_collection_returns_top_k():
    from modules.system_detection import sd_vector_repo as svr
    fake = _FakeChroma([
        (_doc("A", "wbs"), 0.1),
        (_doc("B", "wbs"), 0.2),
        (_doc("C", "wbs"), 0.3),
        (_doc("D", "wbs"), 0.4),
        (_doc("E", "wbs"), 0.5),
    ])
    with patch.object(svr, "_vectorstores", {"whistleblowing-system": fake}):
        out = svr.retrieve_from_collections(["whistleblowing-system"], "q", total_k=4)
    assert len(out) == 4
    assert [d.page_content for d in out] == ["A", "B", "C", "D"]


def test_multi_collection_merge_by_distance():
    from modules.system_detection import sd_vector_repo as svr
    coll_a = _FakeChroma([
        (_doc("A1", "wbs"), 0.10),
        (_doc("A2", "wbs"), 0.40),
    ])
    coll_b = _FakeChroma([
        (_doc("B1", "ms"), 0.15),
        (_doc("B2", "ms"), 0.20),
    ])
    with patch.object(svr, "_vectorstores", {"wbs": coll_a, "ms": coll_b}):
        out = svr.retrieve_from_collections(["wbs", "ms"], "q", total_k=3)
    # Distances ascending: A1=0.10, B1=0.15, B2=0.20, A2=0.40
    assert [d.page_content for d in out] == ["A1", "B1", "B2"]


def test_dedupe_by_content():
    """Two collections both contain a doc with identical page_content; only one returned."""
    from modules.system_detection import sd_vector_repo as svr
    same_text = "Acme Services has offices in ID/TH/MY"
    coll_a = _FakeChroma([(_doc(same_text, "wbs"), 0.10), (_doc("A2", "wbs"), 0.30)])
    coll_b = _FakeChroma([(_doc(same_text, "general"), 0.12), (_doc("B2", "general"), 0.20)])
    with patch.object(svr, "_vectorstores", {"wbs": coll_a, "general": coll_b}):
        out = svr.retrieve_from_collections(["wbs", "general"], "q", total_k=4)
    contents = [d.page_content for d in out]
    assert contents.count(same_text) == 1, f"dedupe failed: {contents}"


def test_missing_collection_skipped_silently():
    """service_id requested but absent from _vectorstores → skip without error."""
    from modules.system_detection import sd_vector_repo as svr
    coll_a = _FakeChroma([(_doc("A1", "wbs"), 0.10)])
    with patch.object(svr, "_vectorstores", {"wbs": coll_a}):
        out = svr.retrieve_from_collections(["wbs", "does-not-exist"], "q", total_k=4)
    assert len(out) == 1
    assert out[0].page_content == "A1"


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS: {name}")
            except AssertionError as e:
                print(f"FAIL: {name}: {e}")
                failures += 1
            except Exception as e:
                print(f"ERROR: {name}: {type(e).__name__}: {e}")
                failures += 1
    if failures:
        sys.exit(1)
    print("\nAll tests passed.")
