"""Per-service Chroma build + atomic swap orchestration (Stage 3A).

Companion to vb_service.py. When KB_BACKEND in {split, dual}, vb_service
delegates per-service build/swap operations here. Each service has its own
Chroma collection at vector_data/current/<service_id>/ with a meta.json
(via vb_registry) for fast bootstrap.

Reuses Windows file-lock workarounds from vb_service:
    _release_chromadb_locks, _safe_rmtree
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

from langchain_chroma import Chroma
from langchain_core.documents import Document
from pymongo import MongoClient

from core.app_config import Config

cfg = Config()
logger = logging.getLogger(__name__)


def _checksum_service(service_id: str) -> str:
    """SHA-256 of one service's FAQ chunk content. Stable across chunk order.

    Returns a deterministic hash even when the service doc is absent from Mongo
    (so callers can compare to detect "service was deleted from Sheet").
    """
    client = MongoClient(cfg.MONGO_URI)
    coll = client[cfg.MONGO_DB][cfg.MONGO_FAQ_UPDATE]
    doc = coll.find_one({"marker": "latest", "service_id": service_id}, {"chunks": 1, "_id": 0})
    h = hashlib.sha256()
    if doc:
        chunks = sorted(
            doc.get("chunks") or [],
            key=lambda c: (c.get("service", ""), c.get("chunk_index", 0)),
        )
        for ch in chunks:
            t = (ch.get("text") or "").strip()
            if t:
                h.update(t.encode("utf-8"))
                h.update(b"\n--sep--\n")
    return "sha256:" + h.hexdigest()


def _faq_docs_for_service(service_id: str) -> Tuple[List[Document], List[str]]:
    """Read one service's chunks from Mongo and convert to langchain Documents.

    Returns (docs, ids). ids encode `<service_id>::<chunk_index_4digit>` for
    deterministic Chroma upsert keys.
    """
    client = MongoClient(cfg.MONGO_URI)
    coll = client[cfg.MONGO_DB][cfg.MONGO_FAQ_UPDATE]
    doc = coll.find_one({"marker": "latest", "service_id": service_id}, {"chunks": 1, "_id": 1})
    docs: List[Document] = []
    ids: List[str] = []
    if not doc:
        return docs, ids
    for i, ch in enumerate(doc.get("chunks") or []):
        txt = (ch.get("text") or "").strip()
        if not txt:
            continue
        docs.append(
            Document(
                page_content=txt,
                metadata={
                    "service": ch.get("service"),
                    "service_id": service_id,
                    "i": i,
                    "chunk_id": f"{service_id}::{i:04d}",
                },
            )
        )
        ids.append(f"{service_id}::{i:04d}")
    return docs, ids


def _build_embeddings():
    """Same provider selection as vb_service._build_embeddings.

    Imported lazily to avoid double-initialization when both modules are loaded.
    """
    from modules.vector_build.vb_service import _build_embeddings as _impl
    return _impl()


def _build_collection(persist_dir: Path, *, service_id: str) -> int:
    """Build a Chroma collection at persist_dir from one service's Mongo chunks.

    Returns the number of docs written. Caller is responsible for atomic-swap
    into the live current/<service_id>/ directory.
    """
    persist_dir = Path(persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)

    docs, ids = _faq_docs_for_service(service_id)
    embeddings = _build_embeddings()
    vs = Chroma(
        collection_name=cfg.CHROMA_COLLECTION,
        persist_directory=str(persist_dir),
        embedding_function=embeddings,
    )
    if docs:
        vs.add_documents(docs, ids=ids)
    return len(docs)


def _atomic_swap_per_service(
    *,
    current: Path,
    incoming: Path,
    trash_root: Path,
) -> None:
    """Atomic-swap one service's collection.

    Steps:
      1. If current exists, rename it to trash_root/<service-name>-<ts>/
      2. Rename incoming → current
      3. (Caller does async cleanup of trash_root)

    Reuses the rename-with-retry-and-copytree-fallback pattern from vb_service.
    Releases chromadb locks first to free SQLite handles on Windows.
    """
    from modules.vector_build.vb_service import _release_chromadb_locks, _safe_rmtree

    current = Path(current)
    incoming = Path(incoming)
    trash_root = Path(trash_root)
    trash_root.mkdir(parents=True, exist_ok=True)

    _release_chromadb_locks()

    # 1) move current → trash (if exists)
    if current.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        trash_target = trash_root / f"{current.name}-{ts}"
        moved = False
        for _ in range(10):
            try:
                current.rename(trash_target)
                moved = True
                break
            except (PermissionError, OSError):
                time.sleep(0.3)
        if not moved:
            # Fallback: copy then delete (Windows lock edge-case)
            shutil.copytree(current, trash_target, dirs_exist_ok=True)
            _safe_rmtree(current)

    # 2) rename incoming → current
    current.parent.mkdir(parents=True, exist_ok=True)
    renamed = False
    for _ in range(10):
        try:
            incoming.rename(current)
            renamed = True
            break
        except (PermissionError, OSError):
            time.sleep(0.3)
    if not renamed:
        # Fallback: copy then delete incoming
        shutil.copytree(incoming, current, dirs_exist_ok=True)
        _safe_rmtree(incoming)

    _release_chromadb_locks()


import uuid


def build_all(
    *,
    services_now: list[dict],
    current_root: Path,
    building_root: Path,
    trash_root: Path,
) -> dict:
    """Rebuild all per-service collections that have changed checksum, plus
    orphan cleanup for services no longer in the repo.

    Args:
        services_now: list of dicts with at least 'service_id' and 'service_name'
                      (typically from FAQRepo.list_services()).
        current_root: Path to vector_data/current/
        building_root: Path to vector_data/building/
        trash_root: Path to vector_data/trash/

    Returns:
        {
            "per_service": [
                {"service_id": str, "rebuilt": bool, "doc_count": int, "checksum": str},
                ...
            ],
            "orphans_removed": [str, ...],
            "orphans_failed": [str, ...],
        }
    """
    from modules.vector_build import vb_registry
    from modules.vector_build.vb_service import _release_chromadb_locks, _safe_rmtree

    current_root = Path(current_root)
    building_root = Path(building_root)
    trash_root = Path(trash_root)
    current_root.mkdir(parents=True, exist_ok=True)
    building_root.mkdir(parents=True, exist_ok=True)
    trash_root.mkdir(parents=True, exist_ok=True)

    services_now_ids = {s["service_id"] for s in services_now}

    # Discover what's already on disk
    existing = vb_registry.list_collections(current_root)
    existing_ids = {c["service_id"] for c in existing}

    per_service_results: list[dict] = []

    # 1) Rebuild changed / new
    for svc in services_now:
        sid = svc["service_id"]
        coll_dir = current_root / sid
        new_checksum = _checksum_service(sid)
        old_checksum = vb_registry.get_checksum(coll_dir)

        if new_checksum == old_checksum:
            per_service_results.append({
                "service_id": sid,
                "rebuilt": False,
                "doc_count": (vb_registry.read_collection_meta(coll_dir) or {}).get("doc_count", 0),
                "checksum": new_checksum,
            })
            continue

        # Build to staging dir
        staging = building_root / f"{sid}-{uuid.uuid4().hex[:8]}"
        try:
            doc_count = _build_collection(staging, service_id=sid)
            _release_chromadb_locks()
            # Atomic swap
            _atomic_swap_per_service(
                current=coll_dir,
                incoming=staging,
                trash_root=trash_root,
            )
            # Write meta.json AFTER swap so it lives at current/<sid>/meta.json
            vb_registry.write_collection_meta(
                coll_dir,
                service_id=sid,
                checksum=new_checksum,
                doc_count=doc_count,
            )
            per_service_results.append({
                "service_id": sid,
                "rebuilt": True,
                "doc_count": doc_count,
                "checksum": new_checksum,
            })
        except Exception as e:
            logger.exception("vb_per_service: build failed for %s: %s", sid, e)
            # Cleanup staging if still around
            if staging.exists():
                _safe_rmtree(staging)
            per_service_results.append({
                "service_id": sid,
                "rebuilt": False,
                "doc_count": 0,
                "checksum": new_checksum,
                "error": str(e),
            })

    # 2) Orphan cleanup — services on disk but not in services_now
    orphans_removed: list[str] = []
    orphans_failed: list[str] = []
    for orphan_id in (existing_ids - services_now_ids):
        orphan_dir = current_root / orphan_id
        _release_chromadb_locks()
        if _safe_rmtree(orphan_dir):
            orphans_removed.append(orphan_id)
        else:
            orphans_failed.append(orphan_id)

    return {
        "per_service": per_service_results,
        "orphans_removed": orphans_removed,
        "orphans_failed": orphans_failed,
    }
