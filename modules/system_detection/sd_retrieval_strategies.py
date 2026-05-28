"""Retrieval-strategy dispatcher for the anti-redundancy stage.

Public API: `retrieve_with_strategy(method, query, *, scope, k, **kwargs)`
returns `None` for `method=normal` (caller falls through to existing retrieval)
or a fully-resolved `list[Document]` for `mmr` / `fuzzy` / `embedding`.

See `docs/superpowers/specs/2026-05-11-anti-redundancy-answer-quality-design.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from core.app_config import Config

cfg = Config()


RetrievalScope = Literal["unbiased", "service_biased", "fan_out"]


@dataclass(frozen=True)
class ResolutionContext:
    """All context dimensions that may influence retrieval-strategy tuning.

    Extensible: add fields here as A/B dimensions grow. Resolvers use only
    the fields they care about; unknown fields are ignored. Default `None`
    on every field keeps existing call sites compatible after additions.
    """
    service_id: Optional[str] = None
    tenant_id: Optional[str] = None
    # Forward-compat fields (unused in v0, reserved for future use):
    channel_id: Optional[str] = None
    user_segment: Optional[str] = None
    time_of_day_utc_hour: Optional[int] = None


def _resolve_mmr_lambda(ctx: ResolutionContext) -> float:
    """v0: ignore ctx, return global cfg. Stage 3C+ swaps in per-tenant lookup."""
    return float(cfg.REDUNDANCY_MMR_LAMBDA)


def _resolve_fuzzy_threshold(ctx: ResolutionContext) -> float:
    """v0: ignore ctx, return global cfg."""
    return float(cfg.REDUNDANCY_FUZZY_THRESHOLD)


def _resolve_embedding_threshold(ctx: ResolutionContext) -> float:
    """v0: ignore ctx, return global cfg."""
    return float(cfg.REDUNDANCY_EMBEDDING_THRESHOLD)


def _mmr_strategy(vectorstore, query: str, *, k: int, ctx: ResolutionContext) -> list:
    """Strategy: MMR over a single vectorstore.

    Returns a list of langchain Documents (≤ k). On Chroma error returns [].
    """
    lam = _resolve_mmr_lambda(ctx)
    fetch_k = max(k, k * int(cfg.REDUNDANCY_MMR_FETCH_K_MULTIPLIER))
    try:
        return vectorstore.max_marginal_relevance_search(
            query, k=k, fetch_k=fetch_k, lambda_mult=lam
        )
    except Exception:
        return []


def _fuzzy_strategy(vectorstore, query: str, *, k: int, ctx: ResolutionContext) -> list:
    """Strategy: similarity_search with over-fetch, then rapidfuzz token-set dedup.

    Over-fetch k*2; pairwise drop docs whose token_set_ratio ≥ threshold
    against any already-kept doc; preserve rank order. Take top-k.
    """
    from rapidfuzz import fuzz

    fetch_k = max(k, k * 2)
    try:
        candidates = vectorstore.similarity_search(query, k=fetch_k)
    except Exception:
        return []

    threshold_pct = _resolve_fuzzy_threshold(ctx) * 100.0  # rapidfuzz returns 0..100
    kept: list = []
    for doc in candidates:
        is_dup = False
        for kept_doc in kept:
            score = fuzz.token_set_ratio(doc.page_content, kept_doc.page_content)
            if score >= threshold_pct:
                is_dup = True
                break
        if not is_dup:
            kept.append(doc)
        if len(kept) >= k:
            break
    return kept


def _embedding_strategy(vectorstore, query: str, *, k: int, ctx: ResolutionContext) -> list:
    """Strategy: similarity_search_with_score over-fetch, then cosine-similarity
    pairwise dedup using the vectorstore's embedding function.

    Embeds candidate texts ONCE and computes pairwise cosine — drops a doc when
    its cosine vs any already-kept doc is ≥ threshold.
    """
    fetch_k = max(k, k * 2)
    try:
        scored = vectorstore.similarity_search_with_score(query, k=fetch_k)
    except Exception:
        return []
    if not scored:
        return []

    threshold = _resolve_embedding_threshold(ctx)
    docs = [d for d, _ in scored]
    embed_fn = getattr(vectorstore, "_embedding_function", None) or getattr(
        vectorstore, "embedding_function", None
    )
    if embed_fn is None:
        # Fallback: distance-only — keep order, no dedup possible.
        return docs[:k]
    try:
        vecs = embed_fn.embed_documents([d.page_content for d in docs])
    except Exception:
        return docs[:k]

    def _cosine(u, v) -> float:
        import math
        dot = sum(a * b for a, b in zip(u, v))
        nu = math.sqrt(sum(a * a for a in u))
        nv = math.sqrt(sum(a * a for a in v))
        if nu == 0 or nv == 0:
            return 0.0
        return dot / (nu * nv)

    kept_docs: list = []
    kept_vecs: list = []
    for doc, vec in zip(docs, vecs):
        is_dup = any(_cosine(vec, kv) >= threshold for kv in kept_vecs)
        if not is_dup:
            kept_docs.append(doc)
            kept_vecs.append(vec)
        if len(kept_docs) >= k:
            break
    return kept_docs


def retrieve_with_strategy(
    method: str,
    query: str,
    *,
    scope: RetrievalScope,
    k: int,
    vectorstore=None,
    ctx: ResolutionContext | None = None,
    **kwargs,
):
    """Strategy dispatcher.

    method == "normal" → returns None (caller falls through to existing retrieval).
    method ∈ {mmr, fuzzy, embedding} → returns list[Document].
    Unknown method → returns None (defensive fallback).
    vectorstore is required for non-normal methods.
    """
    m = (method or "").strip().lower()
    if m == "normal":
        return None
    if vectorstore is None:
        return None
    if ctx is None:
        ctx = ResolutionContext()
    if m == "mmr":
        return _mmr_strategy(vectorstore, query, k=k, ctx=ctx)
    if m == "fuzzy":
        return _fuzzy_strategy(vectorstore, query, k=k, ctx=ctx)
    if m == "embedding":
        return _embedding_strategy(vectorstore, query, k=k, ctx=ctx)
    return None
