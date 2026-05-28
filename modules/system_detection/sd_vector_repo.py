# import os
# from pathlib import Path
# from langchain_chroma import Chroma
# from langchain_openai import OpenAIEmbeddings
# from core.app_config import Config
# from .sd_policies import RETRIEVAL_K
# cfg = Config()

# _vectorstore = None
# _retriever = None

# def bootstrap_vectorstore():
#     """Load retriever dari snapshot CURRENT yang dibuat oleh vb_service."""
#     global _vectorstore, _retriever
#     persist_dir = cfg.VECTOR_CURRENT_SYMLINK  # ← titik kebenaran
#     Path(persist_dir).mkdir(parents=True, exist_ok=True)
#     embeddings = OpenAIEmbeddings(api_key=cfg.OPENAI_API_KEY)
#     _vectorstore = Chroma(
#         collection_name=cfg.CHROMA_COLLECTION,
#         persist_directory=persist_dir,
#         embedding_function=embeddings,
#     )
#     _retriever = _vectorstore.as_retriever(search_kwargs={"k": RETRIEVAL_K})

# def get_retriever():
#     if _retriever is None:
#         bootstrap_vectorstore()
#     return _retriever

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from langchain_chroma import Chroma
from langchain_core.documents import Document

from core.app_config import Config
from .sd_policies import RETRIEVAL_K

cfg = Config()

# Per-service Chroma clients keyed by service_id.
_vectorstores: dict[str, Chroma] = {}
# Cached backend mode at bootstrap time. One of: "legacy" | "split" | "dual".
_BACKEND_MODE: str = ""
_VECTORSTORE_READY = False

# Backward-compat: pre-3A code uses `_vectorstore` directly. Keep as alias to
# the legacy module's vectorstore for any caller still touching the global.
_vectorstore = None
_retriever = None


def _build_embeddings():
    """Delegate to legacy module so embedding init is shared."""
    from .sd_vector_legacy import _build_embeddings as _impl
    return _impl()


def _open_collection(persist_dir: str) -> Chroma:
    """Open a Chroma client at the given persist_dir."""
    embeddings = _build_embeddings()
    return Chroma(
        collection_name=cfg.CHROMA_COLLECTION,
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )


def bootstrap_vectorstore() -> None:
    """Initialize vectorstore(s) based on cfg.KB_BACKEND.

    legacy → just legacy_vectorstore (single collection)
    split  → _vectorstores dict (per-service collections)
    dual   → both
    """
    global _BACKEND_MODE, _VECTORSTORE_READY, _vectorstore, _retriever

    backend = (cfg.KB_BACKEND or "legacy").strip().lower()
    _BACKEND_MODE = backend

    if backend in ("split", "dual"):
        from modules.vector_build import vb_registry
        current_root = Path(cfg.VECTOR_CURRENT_SYMLINK)
        collections = vb_registry.list_collections(current_root)
        if collections:
            with ThreadPoolExecutor(max_workers=8, thread_name_prefix="kb-boot") as pool:
                futs = {pool.submit(_open_collection, c["path"]): c["service_id"] for c in collections}
                for fut in futs:
                    sid = futs[fut]
                    try:
                        _vectorstores[sid] = fut.result()
                    except Exception as e:
                        # Don't fail bootstrap on one bad collection — log and skip
                        import logging
                        logging.getLogger(__name__).warning(
                            "sd_vector_repo: failed to open collection %s: %s", sid, e
                        )

    if backend in ("legacy", "dual"):
        from .sd_vector_legacy import bootstrap_legacy_vectorstore, get_legacy_vectorstore, get_legacy_retriever
        bootstrap_legacy_vectorstore()
        # Aliases so legacy callers that touch the module-level `_vectorstore`
        # / `_retriever` keep working in dual/legacy mode.
        _vectorstore = get_legacy_vectorstore()
        _retriever = get_legacy_retriever()

    _VECTORSTORE_READY = True


def get_retriever():
    """Backward-compat: return legacy retriever (used by Phase 1 generic path
    in legacy/dual modes; in split mode this falls through to legacy if available)."""
    if _retriever is None and _BACKEND_MODE in ("legacy", "dual"):
        bootstrap_vectorstore()
    return _retriever


def retrieve_from_collections(service_ids: list[str], query: str, total_k: int) -> list[Document]:
    """Fan-out query to N service collections, merge by similarity distance, return top-K.

    Approach A (per spec): each collection contributes top-`total_k` candidates,
    all merged and sorted by ascending distance, top-`total_k` returned.
    Dedupe by page_content hash before final sort.
    """
    if not service_ids:
        return []
    scored: list[tuple[float, Document]] = []
    for sid in service_ids:
        vs = _vectorstores.get(sid)
        if vs is None:
            continue
        try:
            for doc, dist in vs.similarity_search_with_score(query, k=total_k):
                scored.append((dist, doc))
        except Exception:
            continue
    seen: set[int] = set()
    deduped: list[tuple[float, Document]] = []
    for dist, doc in scored:
        key = hash(doc.page_content)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((dist, doc))
    deduped.sort(key=lambda x: x[0])
    return [doc for _, doc in deduped[:total_k]]


def _resolve_alias_to_service_id(service_label) -> str | None:
    """Map an alias / canonical label to a service_id slug.

    Examples:
      "WBS" → "whistleblowing-system"
      "Whistleblowing System" → "whistleblowing-system"
      ["WBS", "Whistleblowing System"] → "whistleblowing-system"

    Returns None if no match found among loaded collections.
    """
    if isinstance(service_label, str):
        candidates = [service_label]
    else:
        candidates = [s for s in (service_label or []) if isinstance(s, str)]

    # Lazy import so this module doesn't depend on faq_pipelines at import time
    from modules.faq_automation.faq_pipelines import make_service_id

    for cand in candidates:
        sid = make_service_id(cand) if cand else None
        if sid and sid in _vectorstores:
            return sid
    # Fallback: maybe input is already a service_id
    for cand in candidates:
        if cand and cand in _vectorstores:
            return cand
    return None


def _service_filter(service_aliases):
    """Backward-compat shim — delegates to legacy filter helper."""
    from .sd_vector_legacy import _legacy_service_filter
    return _legacy_service_filter(service_aliases)


def retrieve_service_biased(question: str, service_label, same_k: int = 4, other_k: int = 2):
    """Public API. Backward-compat signature.

    Internal dispatch:
      legacy → _legacy_retrieve_biased
      split / dual → resolve alias, query that collection (k=same_k), fan-out
                     others (total_k=other_k), merge, return same+other.
                     dual mode falls back to legacy if collection not found.
    """
    if not _VECTORSTORE_READY:
        bootstrap_vectorstore()

    if _BACKEND_MODE == "legacy":
        from .sd_vector_legacy import legacy_retrieve_service_biased
        return legacy_retrieve_service_biased(question, service_label, same_k=same_k, other_k=other_k)

    # split or dual
    target_id = _resolve_alias_to_service_id(service_label)

    if target_id is None:
        if _BACKEND_MODE == "dual":
            from .sd_vector_legacy import legacy_retrieve_service_biased
            return legacy_retrieve_service_biased(question, service_label, same_k=same_k, other_k=other_k)
        # split: no service in particular → unbiased fan-out across ALL collections
        return retrieve_from_collections(list(_vectorstores.keys()), question, total_k=same_k + other_k)

    # Same-service docs from target collection
    target_vs = _vectorstores[target_id]
    try:
        same = target_vs.similarity_search(question, k=same_k)
    except Exception:
        same = []

    # Cross-service docs via fan-out across other collections
    other = []
    if other_k > 0:
        other_ids = [sid for sid in _vectorstores if sid != target_id]
        other = retrieve_from_collections(other_ids, question, total_k=other_k)

    return same + other
