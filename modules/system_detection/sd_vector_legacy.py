"""Legacy single-collection retrieval path (pre-Stage-3A).

Verbatim extraction of `bootstrap_vectorstore`, `get_retriever`,
`retrieve_service_biased`, `_service_filter`, `_build_embeddings` from
sd_vector_repo.py. Used when KB_BACKEND=legacy or as fallback in dual mode.

This module owns its own private `_legacy_vectorstore` and `_legacy_retriever`
state — separate from sd_vector_repo's per-service `_vectorstores` dict.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from langchain_chroma import Chroma

from core.app_config import Config
from core.gpu_config import resolve_device
from .sd_policies import RETRIEVAL_K

cfg = Config()
logger = logging.getLogger(__name__)

_legacy_vectorstore = None
_legacy_retriever = None


def _build_embeddings():
    """Embeddings provider — same logic as pre-3A sd_vector_repo._build_embeddings.

    Device selection is delegated to core/gpu_config.resolve_device() so that
    USE_GPU + EMBEDDING_DEVICE are interpreted identically here, in vb_service,
    and in log_gpu_status() at startup.
    """
    provider = os.getenv("EMBEDDINGS_PROVIDER", "openai").strip().lower()

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        logger.info({"event": "embeddings_provider_selected", "provider": "openai", "model": cfg.EMBED_MODEL})
        return OpenAIEmbeddings(api_key=cfg.OPENAI_API_KEY, model=cfg.EMBED_MODEL)

    from langchain_community.embeddings import HuggingFaceEmbeddings

    model_name = os.getenv("EMBEDDING_MODEL_NAME", "sentence-transformers/all-MiniLM-L6-v2").strip()
    device = resolve_device()
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    # Explicit one-line audit so ops can confirm GPU actually engaged. Pairs
    # with log_gpu_status() — that one only reports torch.cuda.is_available;
    # this one reports the device HuggingFaceEmbeddings was actually built on.
    logger.info({
        "event": "embeddings_provider_selected",
        "provider": "hf",
        "model": model_name,
        "device": device,
        "batch_size": batch_size,
        "caller": "sd_vector_legacy",
    })
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": device},
        encode_kwargs={"batch_size": batch_size, "normalize_embeddings": True},
    )


def bootstrap_legacy_vectorstore() -> None:
    global _legacy_vectorstore, _legacy_retriever
    persist_dir = cfg.VECTOR_CURRENT_SYMLINK
    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    embeddings = _build_embeddings()
    _legacy_vectorstore = Chroma(
        collection_name=cfg.CHROMA_COLLECTION,
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )
    _legacy_retriever = _legacy_vectorstore.as_retriever(search_kwargs={"k": RETRIEVAL_K})


def get_legacy_retriever():
    if _legacy_retriever is None:
        bootstrap_legacy_vectorstore()
    return _legacy_retriever


def get_legacy_vectorstore():
    if _legacy_vectorstore is None:
        bootstrap_legacy_vectorstore()
    return _legacy_vectorstore


def _legacy_service_filter(service_aliases):
    if not service_aliases:
        return None
    if isinstance(service_aliases, str):
        return {"service": service_aliases}
    aliases = [s for s in service_aliases if s]
    if not aliases:
        return None
    if len(aliases) == 1:
        return {"service": aliases[0]}
    return {"service": {"$in": aliases}}


def legacy_retrieve_service_biased(question, service_label, *, same_k=4, other_k=2):
    """Pre-3A retrieve_service_biased logic. Verbatim from sd_vector_repo.py."""
    if _legacy_vectorstore is None:
        bootstrap_legacy_vectorstore()

    if isinstance(service_label, str):
        aliases = [service_label.strip()] if service_label and service_label.strip() else []
    else:
        aliases = [s.strip() for s in (service_label or []) if s and s.strip()]

    if not aliases:
        return _legacy_vectorstore.similarity_search(question, k=same_k + other_k)

    svc_filter = _legacy_service_filter(aliases)

    try:
        same_docs = _legacy_vectorstore.similarity_search(question, k=same_k, filter=svc_filter)
    except Exception:
        same_docs = []

    other_docs = []
    if other_k > 0:
        try:
            other_filter = (
                {"service": {"$nin": aliases}} if len(aliases) > 1
                else {"service": {"$ne": aliases[0]}}
            )
            other_docs = _legacy_vectorstore.similarity_search(question, k=other_k, filter=other_filter)
        except Exception:
            try:
                pool = _legacy_vectorstore.similarity_search(
                    question, k=(other_k + len(aliases)) * 4 + 8,
                )
                alias_set = set(aliases)
                same_contents = {d.page_content for d in same_docs}
                for d in pool:
                    if d.page_content in same_contents:
                        continue
                    if (d.metadata or {}).get("service") in alias_set:
                        continue
                    other_docs.append(d)
                    if len(other_docs) >= other_k:
                        break
            except Exception:
                other_docs = []

    return same_docs + other_docs
