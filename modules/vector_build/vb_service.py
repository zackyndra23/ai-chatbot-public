from __future__ import annotations
import os, shutil, tempfile, hashlib, time, gc, logging
from pathlib import Path
from typing import List, Tuple
from pymongo import MongoClient
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from datetime import datetime, timezone

from core.app_config import Config
cfg = Config()

logger = logging.getLogger(__name__)

# === Semua dari app_config (pusat) ===
ROOT = Path(cfg.VECTOR_DATA_DIR)
CURRENT = Path(cfg.VECTOR_CURRENT_SYMLINK).resolve()
COLL = cfg.CHROMA_COLLECTION
KB_META_COLL = cfg.KB_META_COLL
KB_NAMESPACE = cfg.KB_NAMESPACE


def _release_chromadb_locks() -> None:
    """Force-release process-wide chromadb PersistentClient cache.

    chromadb caches `SharedSystemClient` instances per-persist-directory in
    process state. Even after `del vs; gc.collect()`, these caches keep
    SQLite WAL/journal file handles open on Windows, preventing rmtree on
    just-finished kb_build_* tmpdirs. Calling `clear_system_cache()` drops
    the cache and lets the OS release the file handles.

    Safe no-op if chromadb internals change. Idempotent.
    """
    try:
        from chromadb.api.client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
    except Exception:
        pass
    gc.collect()


def _safe_rmtree(p: Path, retries: int = 5, base_delay: float = 0.5) -> bool:
    """Best-effort rmtree with exponential backoff. Returns True on success.

    Windows file-lock workaround: SQLite WAL/journal handles from a just-finished
    Chroma build can persist in the parent process for several seconds after
    `del vs; gc.collect()`. Standard `shutil.rmtree(p, ignore_errors=True)` then
    silently fails. This helper retries with `gc.collect()` between attempts.
    Delays: 0.5s, 1s, 2s, 4s, 8s — total ~15s worst case.
    """
    if not p.exists():
        return True
    last_err: BaseException | None = None
    for attempt in range(retries):
        try:
            shutil.rmtree(p)
            return True
        except (PermissionError, OSError) as e:
            last_err = e
            if attempt == retries - 1:
                break
            gc.collect()
            time.sleep(base_delay * (2 ** attempt))
    if last_err is not None:
        try:
            logger.warning(
                "vb_service: failed to rmtree %s after %d attempts: %s",
                p, retries, last_err,
            )
        except Exception:
            pass
    return False

def _embedding_label() -> str:
    provider = os.getenv("EMBEDDINGS_PROVIDER", "openai").strip().lower()
    if provider == "openai":
        return f"openai/{cfg.EMBED_MODEL}"
    model_name = os.getenv(
        "EMBEDDING_MODEL_NAME",
        "sentence-transformers/all-MiniLM-L6-v2",
    ).strip()
    return f"hf/{model_name}"

def _build_embeddings():
    """
    Embeddings provider:
    - EMBEDDINGS_PROVIDER=openai  -> remote (no GPU usage)
    - EMBEDDINGS_PROVIDER=hf      -> local (can use CUDA)

    Device selection delegated to core/gpu_config.resolve_device() so USE_GPU +
    EMBEDDING_DEVICE are interpreted identically across vb_service,
    sd_vector_legacy, and log_gpu_status at startup.
    """
    from core.gpu_config import resolve_device

    provider = os.getenv("EMBEDDINGS_PROVIDER", "openai").strip().lower()
    if provider == "openai":
        logger.info({"event": "embeddings_provider_selected", "provider": "openai", "model": cfg.EMBED_MODEL, "caller": "vb_service"})
        return OpenAIEmbeddings(api_key=cfg.OPENAI_API_KEY, model=cfg.EMBED_MODEL)

    from langchain_community.embeddings import HuggingFaceEmbeddings

    model_name = os.getenv(
        "EMBEDDING_MODEL_NAME",
        "sentence-transformers/all-MiniLM-L6-v2"
    ).strip()

    device = resolve_device()
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    # Explicit audit line — confirms what device HF embeddings actually built on
    # (log_gpu_status only reports torch.cuda.is_available, not the call site).
    logger.info({
        "event": "embeddings_provider_selected",
        "provider": "hf",
        "model": model_name,
        "device": device,
        "batch_size": batch_size,
        "caller": "vb_service",
    })

    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device},
        encode_kwargs={"batch_size": batch_size, "normalize_embeddings": True},
    )

def _faq_docs_from_mongo() -> Tuple[List[Document], List[str]]:
    client = MongoClient(cfg.MONGO_URI)
    coll = client[cfg.MONGO_DB][cfg.MONGO_FAQ_UPDATE]  # sesuai repo FAQ latest
    docs, ids = [], []
    for d in coll.find({}, {"text": 1, "chunks": 1, "_id": 1}):
        # gunakan CHUNKS yang sudah distandardkan oleh pipeline (S/Q/A)
        doc_id = d.get("_id")
        for i, ch in enumerate(d.get("chunks") or []):
            txt = (ch.get("text") or "").strip()
            if not txt:
                continue
            if doc_id is not None:
                chunk_id = f"{doc_id}::{i:04d}"
            else:
                chunk_id = hashlib.sha1(txt.encode("utf-8")).hexdigest()[:16]
            docs.append(
                Document(
                    page_content=txt,
                    metadata={"service": ch.get("service"), "i": i, "chunk_id": chunk_id},
                )
            )
            ids.append(f"{doc_id}::{i:04d}" if doc_id is not None else chunk_id)
    return docs, ids

def _checksum_source() -> str:
    """Hash content of all FAQ chunks across all per-service docs.

    Stability invariant (post-2026-05-07): same content distributed across
    1 doc OR N docs MUST produce the same hash. Achieved by sorting docs
    by service_id (legacy single-doc with no service_id sorts first by
    None-vs-string ordering convention) and chunks by chunk_index within
    each doc.
    """
    client = MongoClient(cfg.MONGO_URI)
    coll = client[cfg.MONGO_DB][cfg.MONGO_FAQ_UPDATE]
    h = hashlib.sha256()
    cursor = coll.find(
        {},
        {"chunks": 1, "service_id": 1, "_id": 0},
    ).sort("service_id", 1)
    for d in cursor:
        chunks = sorted(
            d.get("chunks") or [],
            key=lambda c: (c.get("service", ""), c.get("chunk_index", 0)),
        )
        for ch in chunks:
            t = (ch.get("text") or "").strip()
            if t:
                h.update(t.encode("utf-8"))
                h.update(b"\n--sep--\n")
    return "sha256:" + h.hexdigest()

def _write_meta(persist_dir: str, doc_count: int, checksum: str):
    client = MongoClient(cfg.MONGO_URI)
    embedding_label = _embedding_label()
    meta = {
        "namespace": KB_NAMESPACE,
        "backend": "chroma",
        "embedding_model": embedding_label,
        "artifact": {"persist_dir": persist_dir, "collection_name": COLL, "doc_count": doc_count},
        "source_version": {"checksum": checksum, "faq_collection": cfg.MONGO_FAQ_UPDATE},
        "built_at": datetime.now(timezone.utc).isoformat(),
        "built_by": "vector_build.vb_service",
    }
    client[cfg.MONGO_DB][KB_META_COLL].insert_one(meta)
    return meta

def _cleanup_orphan_build_dirs() -> dict:
    """Remove orphan kb_build_* directories from ROOT.

    Returns {"removed": [...], "failed": [...]}. Failures are logged at WARN
    but never raise — cleanup is best-effort. Use `_safe_rmtree` so Windows
    file locks held over from a recent Chroma build get a chance to age out.

    Skips any path that resolves to CURRENT (defensive — shouldn't happen
    given the kb_build_* prefix, but cheap to check).

    Calls `_release_chromadb_locks()` first to drop chromadb's process-wide
    SystemClient cache — without this, rmtree fails on Windows because SQLite
    handles from a just-finished Chroma build remain open.
    """
    _release_chromadb_locks()
    removed: list[str] = []
    failed: list[str] = []
    try:
        current_resolved = CURRENT.resolve()
    except Exception:
        current_resolved = None

    for p in ROOT.glob("kb_build_*"):
        try:
            p_resolved = p.resolve()
        except Exception:
            p_resolved = p
        if current_resolved and p_resolved == current_resolved:
            continue
        if _safe_rmtree(p):
            removed.append(str(p))
        else:
            failed.append(str(p))
    return {"removed": removed, "failed": failed}

def build_and_swap(force: bool = False) -> dict:
    """Mode dispatcher for KB rebuild.

    KB_BACKEND env knob:
      legacy → existing single-collection rebuild (verbatim pre-3A behavior)
      split  → per-service rebuild via vb_per_service.build_all
      dual   → both, with divergence telemetry
    """
    backend = (cfg.KB_BACKEND or "legacy").strip().lower()

    if backend == "legacy":
        return _legacy_build_and_swap_impl(force=force)

    if backend == "split":
        return _per_service_build_and_swap_impl(force=force)

    if backend == "dual":
        legacy_result = _legacy_build_and_swap_impl(force=force)
        per_svc_result = _per_service_build_and_swap_impl(force=force)

        legacy_total = int(legacy_result.get("docs") or 0)
        per_svc_total = sum(s.get("doc_count", 0) for s in per_svc_result.get("per_service", []))

        if legacy_total != per_svc_total:
            _audit_divergence({
                "event": "kb_build_divergence",
                "legacy_total": legacy_total,
                "per_service_total": per_svc_total,
                "delta": legacy_total - per_svc_total,
            })

        return {
            "backend_mode": "dual",
            "legacy": legacy_result,
            "per_service": per_svc_result.get("per_service", []),
            "orphans_removed": per_svc_result.get("orphans_removed", []),
        }

    raise ValueError(f"Unknown KB_BACKEND: {backend!r} (expected legacy|split|dual)")


def _per_service_build_and_swap_impl(force: bool = False) -> dict:
    """Per-service rebuild orchestration.

    `force` argument is honored: when True, every service is rebuilt even if
    checksum unchanged. Implemented by clearing meta.json from each service
    dir before delegating to vb_per_service.build_all (which compares
    checksums).
    """
    from modules.vector_build import vb_per_service, vb_registry
    from infra.app_repo import build_faq_repo

    repo = build_faq_repo(cfg)
    services = repo.list_services()  # list of dicts with service_id, service_name, ...

    current_root = Path(cfg.VECTOR_CURRENT_SYMLINK)
    building_root = Path(cfg.VECTOR_DATA_DIR) / "building"
    trash_root = Path(cfg.VECTOR_DATA_DIR) / "trash"

    if force:
        # Wipe meta.json so checksum comparison always says "stale"
        for s in services:
            coll_dir = current_root / s["service_id"]
            vb_registry.remove_collection_meta(coll_dir)

    return vb_per_service.build_all(
        services_now=services,
        current_root=current_root,
        building_root=building_root,
        trash_root=trash_root,
    )


def _audit_divergence(payload: dict) -> None:
    """Log a kb_build_divergence event to Mongo audit collection."""
    try:
        client = MongoClient(cfg.MONGO_URI)
        client[cfg.MONGO_DB][KB_META_COLL].insert_one({
            **payload,
            "namespace": KB_NAMESPACE,
            "built_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        logger.exception("vb_service: failed to write divergence audit row")


def _legacy_build_and_swap_impl(force: bool = False) -> dict:
    """Legacy single-collection rebuild — verbatim pre-3A behavior."""
    ROOT.mkdir(parents=True, exist_ok=True)

    # Pre-build cleanup: prior run's tmpdir may have lingered because Windows
    # SQLite file-locks weren't released in time for the in-call rmtree.
    # By now (a fresh process call later), they should be cold and removable.
    pre_cleanup = _cleanup_orphan_build_dirs()

    checksum = _checksum_source()
    embedding_label = _embedding_label()

    # Jika sudah ada CURRENT & meta sama → skip
    meta_col = MongoClient(cfg.MONGO_URI)[cfg.MONGO_DB][KB_META_COLL]
    latest = meta_col.find_one(
        {
            "namespace": KB_NAMESPACE,
            "backend": "chroma",
            "embedding_model": embedding_label,
        },
        sort=[("built_at", -1)],
    )
    if (not force) and latest and latest.get("source_version", {}).get("checksum") == checksum:
        return {
            "rebuilt": False,
            "reason": "up-to-date",
            "current": str(CURRENT),
            "orphans_removed": pre_cleanup["removed"],
            "orphans_failed": pre_cleanup["failed"],
        }

    # 1) build di temp (absolut)
    tmpdir = Path(tempfile.mkdtemp(prefix="kb_build_", dir=str(ROOT))).resolve()
    embeddings = _build_embeddings()
    vs = Chroma(collection_name=COLL, persist_directory=str(tmpdir), embedding_function=embeddings)

    docs, ids = _faq_docs_from_mongo()
    if docs:
        vs.add_documents(docs, ids=ids)
        # flush kalau client mendukung:
        try:
            if hasattr(vs, "_client") and hasattr(vs._client, "persist"):
                vs._client.persist()
        except Exception:
            pass
        # coba tutup/bersihin koneksi internal kalau ada
        for attr in ("close", "reset", "shutdown", "teardown"):
            try:
                fn = getattr(vs, attr, None) or getattr(getattr(vs, "_client", None), attr, None)
                if callable(fn):
                    fn()
            except Exception:
                pass

    # Lepas semua referensi biar lock hilang di Windows
    del vs
    gc.collect()
    # Drop chromadb's process-wide SystemClient cache so SQLite WAL/journal
    # file handles get released. Without this the just-finished tmpdir can't
    # be rmtree'd later — handles persist for the lifetime of the process.
    _release_chromadb_locks()
    time.sleep(0.2)  # beri napas sejenak


    # 2) atomic swap → CURRENT (Windows-safe dengan retry + fallback)
    #    - hapus CURRENT kalau ada
    if CURRENT.exists() or CURRENT.is_symlink():
        if CURRENT.is_symlink() or CURRENT.is_file():
            try:
                CURRENT.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            shutil.rmtree(CURRENT, ignore_errors=True)

    #    - coba rename dengan retry
    rename_ok = False
    for _ in range(10):
        try:
            tmpdir.rename(CURRENT)
            rename_ok = True
            break
        except PermissionError:
            time.sleep(0.3)
        except OSError:
            time.sleep(0.3)

    #    - fallback: copytree kalau rename masih gagal (Windows lock edge-case)
    if not rename_ok:
        CURRENT.mkdir(parents=True, exist_ok=True)
        shutil.copytree(tmpdir, CURRENT, dirs_exist_ok=True)
        # bersihkan tmpdir — pakai _safe_rmtree dengan retries supaya tidak silently
        # tertinggal kalau Chroma SQLite handle masih open di Windows.
        _safe_rmtree(tmpdir)

    meta = _write_meta(str(CURRENT), len(docs), checksum)
    post_cleanup = _cleanup_orphan_build_dirs()   # ← bersihin orphan temp dirs
    # Gabungkan pre + post cleanup hasil supaya caller bisa lihat semuanya.
    all_removed = list(set(pre_cleanup["removed"] + post_cleanup["removed"]))
    all_failed = list(set(pre_cleanup["failed"] + post_cleanup["failed"]))
    return {
        "rebuilt": True,
        "docs": len(docs),
        "current": str(CURRENT),
        "meta_id": str(meta.get("_id")),
        "orphans_removed": all_removed,
        "orphans_failed": all_failed,
    }
