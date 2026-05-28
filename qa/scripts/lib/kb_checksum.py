"""Read the latest KB build checksum from kb_registry collection."""
from __future__ import annotations
import os
from pymongo import MongoClient
from typing import Any


def read_latest_kb_meta() -> dict[str, Any]:
    """Return {checksum, doc_count, built_at, embedding_label} for the most-recent
    kb_registry record. Raises SystemExit if the collection is empty.
    """
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI env var required")
    db = MongoClient(uri)[os.getenv("MONGO_DB", "faq_automation")]
    coll = os.getenv("KB_META_COLL", "kb_registry")
    doc = db[coll].find_one(sort=[("built_at", -1)])
    if not doc:
        raise SystemExit(
            f"kb_registry collection {coll!r} is empty. Run /knowledgebase-rebuild "
            "before starting QA suite."
        )
    return {
        "checksum": doc.get("checksum") or "",
        "doc_count": int(doc.get("doc_count") or 0),
        "built_at": str(doc.get("built_at") or ""),
        "embedding_label": doc.get("embedding_label") or "",
    }
