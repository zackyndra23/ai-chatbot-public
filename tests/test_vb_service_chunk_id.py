"""Verify vb_service._faq_docs_from_mongo emits metadata['chunk_id'].

When the Mongo doc has _id+i, use that. When _id is absent (very-legacy
single doc), fall back to sha1(page_content)[:16].
"""
from __future__ import annotations

import hashlib
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_chunk_id_uses_id_and_index_when_present():
    from modules.vector_build import vb_service

    fake_doc = {
        "_id": "whistleblowing-system",
        "chunks": [
            {"text": "S: WBS\nQ: a\nA: 1", "service": "Whistleblowing System"},
            {"text": "S: WBS\nQ: b\nA: 2", "service": "Whistleblowing System"},
        ],
    }
    fake_coll = MagicMock()
    fake_coll.find.return_value = [fake_doc]
    fake_client = MagicMock()
    fake_client.__getitem__.return_value.__getitem__.return_value = fake_coll

    with patch.object(vb_service, "MongoClient", lambda *a, **kw: fake_client):
        docs, ids = vb_service._faq_docs_from_mongo()

    assert len(docs) == 2
    assert docs[0].metadata["chunk_id"] == "whistleblowing-system::0000"
    assert docs[1].metadata["chunk_id"] == "whistleblowing-system::0001"


def test_chunk_id_falls_back_to_sha1_when_id_missing():
    from modules.vector_build import vb_service

    text = "S: legacy\nQ: x\nA: y"
    fake_doc = {
        # No `_id` field → fall back to sha1.
        "chunks": [{"text": text, "service": "Legacy"}],
    }
    fake_coll = MagicMock()
    fake_coll.find.return_value = [fake_doc]
    fake_client = MagicMock()
    fake_client.__getitem__.return_value.__getitem__.return_value = fake_coll

    with patch.object(vb_service, "MongoClient", lambda *a, **kw: fake_client):
        docs, _ = vb_service._faq_docs_from_mongo()

    expected_sha = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]
    assert docs[0].metadata["chunk_id"] == expected_sha


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS: {name}")
            except AssertionError as e:
                print(f"FAIL: {name} — {e}")
                failures += 1
    raise SystemExit(failures)
