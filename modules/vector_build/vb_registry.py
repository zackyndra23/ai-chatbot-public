"""Per-collection meta.json helpers for Stage 3A per-service vector store.

Each Chroma collection directory under vector_data/current/<service_id>/ holds
a small meta.json with {service_id, checksum, doc_count, built_at}. Bootstrap
scans dirs and reads each meta.json to know which collections exist and their
current state.

This is the filesystem-side registry. Mongo kb_registry collection (in
vb_service._write_meta) keeps the audit history. The two are complementary:
- meta.json — fast bootstrap, per-collection self-describing
- Mongo kb_registry — append-only history, queryable across builds
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

META_FILENAME = "meta.json"


def write_collection_meta(
    coll_dir: Path,
    *,
    service_id: str,
    checksum: str,
    doc_count: int,
    built_at: str | None = None,
) -> dict:
    """Write meta.json into the collection directory. Returns the dict written."""
    coll_dir = Path(coll_dir)
    coll_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "service_id": service_id,
        "checksum": checksum,
        "doc_count": int(doc_count),
        "built_at": built_at or datetime.now(timezone.utc).isoformat(),
    }
    (coll_dir / META_FILENAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def read_collection_meta(coll_dir: Path) -> dict | None:
    """Read meta.json from a collection directory. Returns None if absent or unreadable."""
    coll_dir = Path(coll_dir)
    meta_path = coll_dir / META_FILENAME
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_collections(root: Path) -> list[dict]:
    """Scan root dir for subdirectories with valid meta.json. Returns list of meta dicts.

    Each entry is the dict from meta.json plus an added 'path' field.
    Subdirectories without meta.json are silently skipped (could be in-flight
    builds, orphans, or unrelated dirs).
    """
    root = Path(root)
    if not root.exists():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = read_collection_meta(child)
        if meta is None:
            continue
        meta = dict(meta)
        meta["path"] = str(child)
        out.append(meta)
    return out


def get_checksum(coll_dir: Path) -> str | None:
    """Convenience: return current checksum for a collection, None if no meta."""
    meta = read_collection_meta(coll_dir)
    return meta.get("checksum") if meta else None


def remove_collection_meta(coll_dir: Path) -> None:
    """Remove meta.json from a collection directory. Idempotent — no error if absent."""
    coll_dir = Path(coll_dir)
    meta_path = coll_dir / META_FILENAME
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass
