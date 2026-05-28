"""Unit tests for vb_registry — per-collection meta.json helpers."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_read_collection_meta_returns_none_when_missing(tmp_path: Path | None = None):
    from modules.vector_build.vb_registry import read_collection_meta
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        result = read_collection_meta(Path(td) / "no_such_dir")
    assert result is None


def test_write_then_read_roundtrip():
    from modules.vector_build.vb_registry import read_collection_meta, write_collection_meta
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        coll_dir = Path(td) / "whistleblowing-system"
        coll_dir.mkdir()
        write_collection_meta(coll_dir, service_id="whistleblowing-system",
                              checksum="sha256:abc123", doc_count=38)
        result = read_collection_meta(coll_dir)
    assert result["service_id"] == "whistleblowing-system"
    assert result["checksum"] == "sha256:abc123"
    assert result["doc_count"] == 38
    assert "built_at" in result and isinstance(result["built_at"], str)


def test_list_collections_filters_to_dirs_with_meta():
    from modules.vector_build.vb_registry import list_collections, write_collection_meta
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # service A: has meta
        a = root / "service-a"
        a.mkdir()
        write_collection_meta(a, service_id="service-a", checksum="sha256:a", doc_count=1)
        # service B: dir but no meta (should be skipped)
        (root / "service-b").mkdir()
        # not-a-dir file (should be skipped)
        (root / "stray.txt").write_text("ignore me")
        result = list_collections(root)
    ids = sorted([c["service_id"] for c in result])
    assert ids == ["service-a"]


def test_get_checksum_returns_none_for_missing():
    from modules.vector_build.vb_registry import get_checksum
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        assert get_checksum(Path(td) / "nope") is None


def test_remove_collection_meta_safe_when_missing():
    from modules.vector_build.vb_registry import remove_collection_meta
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # should not raise
        remove_collection_meta(Path(td) / "no_such_dir")


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
