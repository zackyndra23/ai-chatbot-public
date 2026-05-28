"""Unit tests for vb_per_service — per-service Chroma build + atomic swap."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ---------- _checksum_service ----------

def test_checksum_service_stable_across_chunk_order():
    """Same chunks in different order → same hash."""
    from modules.vector_build import vb_per_service as vps

    # Two doc layouts with identical content, different chunk order
    doc_a = {
        "service_id": "wbs",
        "chunks": [
            {"text": "Q1 about WBS", "service": "WBS", "chunk_index": 0},
            {"text": "Q2 about WBS", "service": "WBS", "chunk_index": 1},
        ],
    }
    doc_b = {
        "service_id": "wbs",
        "chunks": [
            {"text": "Q2 about WBS", "service": "WBS", "chunk_index": 1},
            {"text": "Q1 about WBS", "service": "WBS", "chunk_index": 0},
        ],
    }

    fake_coll = MagicMock()
    fake_coll.find_one = MagicMock(side_effect=[doc_a, doc_b])

    fake_client = MagicMock()
    fake_client.__getitem__ = MagicMock(return_value={"faq_update_doc": fake_coll})

    with patch.object(vps, "MongoClient", lambda *a, **kw: fake_client):
        h1 = vps._checksum_service("wbs")
        h2 = vps._checksum_service("wbs")

    assert h1 == h2, f"checksum unstable across calls: {h1} vs {h2}"
    assert h1.startswith("sha256:")


def test_checksum_service_returns_empty_marker_when_doc_absent():
    """No service doc in Mongo → returns a deterministic empty-marker hash, not error."""
    from modules.vector_build import vb_per_service as vps

    fake_coll = MagicMock()
    fake_coll.find_one = MagicMock(return_value=None)
    fake_client = MagicMock()
    fake_client.__getitem__ = MagicMock(return_value={"faq_update_doc": fake_coll})

    with patch.object(vps, "MongoClient", lambda *a, **kw: fake_client):
        h = vps._checksum_service("does-not-exist")

    assert h.startswith("sha256:")  # deterministic empty hash
    # Two calls with absent doc should return the SAME hash
    with patch.object(vps, "MongoClient", lambda *a, **kw: fake_client):
        h2 = vps._checksum_service("does-not-exist")
    assert h == h2


def test_checksum_service_skips_empty_chunks():
    """Chunks with empty/whitespace text don't contribute to hash."""
    from modules.vector_build import vb_per_service as vps

    doc_with_empty = {
        "service_id": "wbs",
        "chunks": [
            {"text": "real content", "service": "WBS", "chunk_index": 0},
            {"text": "", "service": "WBS", "chunk_index": 1},
            {"text": "   ", "service": "WBS", "chunk_index": 2},
        ],
    }
    doc_without_empty = {
        "service_id": "wbs",
        "chunks": [
            {"text": "real content", "service": "WBS", "chunk_index": 0},
        ],
    }

    fake_coll = MagicMock()
    fake_coll.find_one = MagicMock(side_effect=[doc_with_empty, doc_without_empty])
    fake_client = MagicMock()
    fake_client.__getitem__ = MagicMock(return_value={"faq_update_doc": fake_coll})

    with patch.object(vps, "MongoClient", lambda *a, **kw: fake_client):
        h_with_empty = vps._checksum_service("wbs")
        h_without_empty = vps._checksum_service("wbs")
    assert h_with_empty == h_without_empty


# ---------- _build_collection ----------

def test_build_collection_writes_chroma_to_target_dir():
    """Build a Chroma collection from mock Mongo docs into a target dir."""
    from modules.vector_build import vb_per_service as vps
    import tempfile
    from langchain_core.documents import Document

    fake_docs = [
        ("S: WBS\nQ: q1\nA: a1", "WBS", 0),
        ("S: WBS\nQ: q2\nA: a2", "WBS", 1),
    ]

    # Mock _faq_docs_for_service to return fake docs + ids
    docs_objs = [Document(page_content=t, metadata={"service": s, "i": i}) for t, s, i in fake_docs]
    ids = [f"wbs::{i:04d}" for _, _, i in fake_docs]

    captured = {}

    class _FakeChroma:
        def __init__(self, *, collection_name, persist_directory, embedding_function):
            captured["collection_name"] = collection_name
            captured["persist_directory"] = persist_directory
        def add_documents(self, docs, ids=None):
            captured["doc_count"] = len(docs)
            captured["ids"] = ids

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "wbs-build"
        with patch.object(vps, "_faq_docs_for_service", lambda sid: (docs_objs, ids)), \
             patch.object(vps, "_build_embeddings", lambda: object()), \
             patch.object(vps, "Chroma", _FakeChroma):
            doc_count = vps._build_collection(target, service_id="whistleblowing-system")

    assert doc_count == 2, f"expected 2, got {doc_count}"
    assert captured["persist_directory"] == str(target)
    assert captured["doc_count"] == 2


def test_build_collection_handles_empty_service():
    """Service with no chunks → builds empty Chroma, returns 0."""
    from modules.vector_build import vb_per_service as vps
    import tempfile

    class _FakeChroma:
        def __init__(self, **kw): pass
        def add_documents(self, docs, ids=None):
            raise AssertionError("must NOT be called when no docs")

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "empty-build"
        with patch.object(vps, "_faq_docs_for_service", lambda sid: ([], [])), \
             patch.object(vps, "_build_embeddings", lambda: object()), \
             patch.object(vps, "Chroma", _FakeChroma):
            doc_count = vps._build_collection(target, service_id="some-empty-svc")
    assert doc_count == 0


# ---------- _atomic_swap_per_service ----------

def test_atomic_swap_replaces_current_with_building():
    """Current dir → trash; building dir → current. Both renamed atomically."""
    from modules.vector_build import vb_per_service as vps
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        current = root / "current" / "wbs"
        building = root / "building" / "wbs-uuid"
        trash = root / "trash"
        current.parent.mkdir(parents=True)
        current.mkdir()
        (current / "old_data.txt").write_text("OLD")
        building.parent.mkdir(parents=True)
        building.mkdir()
        (building / "new_data.txt").write_text("NEW")

        vps._atomic_swap_per_service(
            current=current,
            incoming=building,
            trash_root=trash,
        )

        # current now has NEW content
        assert (current / "new_data.txt").read_text() == "NEW"
        assert not (current / "old_data.txt").exists()
        # building dir consumed (renamed away)
        assert not building.exists()


def test_atomic_swap_when_current_does_not_exist_yet():
    """First-build case: current doesn't exist; just rename building → current."""
    from modules.vector_build import vb_per_service as vps
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        current = root / "current" / "newsvc"
        building = root / "building" / "newsvc-uuid"
        trash = root / "trash"
        current.parent.mkdir(parents=True)
        # current does NOT exist yet
        building.parent.mkdir(parents=True)
        building.mkdir()
        (building / "data.txt").write_text("FIRST")

        vps._atomic_swap_per_service(
            current=current,
            incoming=building,
            trash_root=trash,
        )

        assert (current / "data.txt").read_text() == "FIRST"
        assert not building.exists()


# ---------- build_all ----------

def test_build_all_rebuilds_only_changed_services():
    """3 services in repo; 1 has changed checksum; only that one rebuilt."""
    from modules.vector_build import vb_per_service as vps
    import tempfile
    import shutil

    rebuilt: list[str] = []

    def _fake_build_collection(persist_dir, *, service_id):
        rebuilt.append(service_id)
        return 5  # doc count

    def _fake_swap(*, current, incoming, trash_root):
        # Simulate: ensure current exists with new content
        current = Path(current)
        current.parent.mkdir(parents=True, exist_ok=True)
        if current.exists():
            shutil.rmtree(current)
        current.mkdir()

    services_in_repo = [
        {"service_id": "service-a", "service_name": "Service A"},
        {"service_id": "service-b", "service_name": "Service B"},
        {"service_id": "service-c", "service_name": "Service C"},
    ]
    # Pre-existing checksums from meta.json
    fake_checksums = {
        "service-a": "sha256:OLD",  # will compute new differs
        "service-b": "sha256:SAME",  # unchanged
        "service-c": None,  # never built before
    }
    # Computed checksums (live, from Mongo)
    new_checksums = {
        "service-a": "sha256:NEW",  # changed
        "service-b": "sha256:SAME",  # unchanged
        "service-c": "sha256:FIRST_BUILD",
    }

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        current_root = root / "current"
        building_root = root / "building"
        trash_root = root / "trash"
        current_root.mkdir()

        # Pre-create a/b/c dirs with meta.json so list_collections finds them
        from modules.vector_build import vb_registry
        for sid, csum in fake_checksums.items():
            if csum is not None:
                d = current_root / sid
                d.mkdir()
                vb_registry.write_collection_meta(d, service_id=sid, checksum=csum, doc_count=5)

        with patch.object(vps, "_build_collection", _fake_build_collection), \
             patch.object(vps, "_atomic_swap_per_service", _fake_swap), \
             patch.object(vps, "_checksum_service", lambda sid: new_checksums[sid]):
            result = vps.build_all(
                services_now=services_in_repo,
                current_root=current_root,
                building_root=building_root,
                trash_root=trash_root,
            )

        rebuilt_ids = sorted([r["service_id"] for r in result["per_service"] if r["rebuilt"]])
        assert rebuilt_ids == ["service-a", "service-c"], f"got {rebuilt_ids}"
        # Service-b should NOT have been rebuilt
        assert "service-b" not in rebuilt


def test_build_all_orphan_cleanup_removes_disk_dir():
    """Service in current/ but NOT in services_now → deleted."""
    from modules.vector_build import vb_per_service as vps
    import tempfile
    import shutil

    services_in_repo = [{"service_id": "kept", "service_name": "Kept"}]

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        current_root = root / "current"
        current_root.mkdir()

        # Pre-create kept (matches repo) + orphan (not in repo)
        from modules.vector_build import vb_registry
        for sid in ["kept", "orphan"]:
            d = current_root / sid
            d.mkdir()
            vb_registry.write_collection_meta(d, service_id=sid, checksum="sha256:x", doc_count=1)

        with patch.object(vps, "_build_collection", lambda *a, **kw: 0), \
             patch.object(vps, "_atomic_swap_per_service", lambda **kw: None), \
             patch.object(vps, "_checksum_service", lambda sid: "sha256:x"):
            result = vps.build_all(
                services_now=services_in_repo,
                current_root=current_root,
                building_root=root / "building",
                trash_root=root / "trash",
            )

        orphan_ids = sorted(result["orphans_removed"])
        assert orphan_ids == ["orphan"], f"got {orphan_ids}"
        # kept dir still on disk
        assert (current_root / "kept").exists()
        # orphan dir gone
        assert not (current_root / "orphan").exists()


def test_faq_docs_for_service_sets_chunk_id_metadata():
    """Every produced Document must have metadata['chunk_id'] = '<service_id>::<4d>'."""
    from modules.vector_build import vb_per_service

    fake_doc = {
        "chunks": [
            {"text": "S: WBS\nQ: q1\nA: a1", "service": "Whistleblowing System"},
            {"text": "S: WBS\nQ: q2\nA: a2", "service": "Whistleblowing System"},
            {"text": "", "service": "Whistleblowing System"},  # skipped
            {"text": "S: WBS\nQ: q3\nA: a3", "service": "Whistleblowing System"},
        ]
    }
    fake_coll = MagicMock()
    fake_coll.find_one.return_value = fake_doc
    fake_client = MagicMock()
    fake_client.__getitem__.return_value.__getitem__.return_value = fake_coll

    with patch.object(vb_per_service, "MongoClient", lambda *a, **kw: fake_client):
        docs, ids = vb_per_service._faq_docs_for_service("whistleblowing-system")

    assert len(docs) == 3, f"expected 3 docs (one empty skipped), got {len(docs)}"
    assert docs[0].metadata.get("chunk_id") == "whistleblowing-system::0000"
    assert docs[1].metadata.get("chunk_id") == "whistleblowing-system::0001"
    # chunks[3] in original list — skip-preservation: index of empty chunk is retained
    assert docs[2].metadata.get("chunk_id") == "whistleblowing-system::0003"
    assert ids == ["whistleblowing-system::0000", "whistleblowing-system::0001", "whistleblowing-system::0003"]


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
