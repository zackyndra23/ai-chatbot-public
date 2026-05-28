"""Unit tests for _prepare_rag_context retrieval count + Phase 1/2 behavior.

Run (pytest available):
    python -m pytest tests/test_retrieval_count.py -v

Run (stdlib only, no pytest):
    python tests/test_retrieval_count.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _doc(content: str, service: str):
    """Build a langchain Document with a metadata.service tag."""
    from langchain_core.documents import Document
    return Document(page_content=content, metadata={"service": service})


def _grader_pass_all(grader, candidates, question):
    """Grader stub: passes every candidate. Mirrors grade_and_filter_yes signature."""
    return list(candidates)


def _grader_reject_all_but_one(grader, candidates, question):
    """Grader stub: passes only the first candidate."""
    return list(candidates[:1]) if candidates else []


class _DummyRetriever:
    """Stand-in for the Chroma retriever returned by get_retriever()."""
    pass


def test_phase1_no_sa_label_returns_4_cross_service():
    """When sa_service_label is None, generic retrieval returns top-K from
    the global KB. Six candidates spanning 3 services → context truncated
    to floor=4 and includes ≥2 services."""
    from modules.system_detection import sd_service as svc_mod

    candidates = [
        _doc("S: A\nQ: q1\nA: a1", "Whistleblowing Hotline"),
        _doc("S: B\nQ: q2\nA: a2", "Market Research"),
        _doc("S: C\nQ: q3\nA: a3", "Whistleblowing Hotline"),
        _doc("S: D\nQ: q4\nA: a4", "Due Diligence"),
        _doc("S: E\nQ: q5\nA: a5", "Market Research"),
        _doc("S: F\nQ: q6\nA: a6", "Whistleblowing Hotline"),
    ]

    fake_cfg = SimpleNamespace(
        CTX_DOCS_SAME_SERVICE=4,
        CTX_DOCS_OTHER_SERVICE=0,
        CTX_DOCS_FLOOR=4,
        FAQ_VERIFICATOR="on",
        CTX_INFER_SERVICE_FROM_QUERY=True,
        CTX_PIN_SERVICE_DEFINITION=True,
    )

    with patch.object(svc_mod, "cfg", fake_cfg), \
         patch.object(svc_mod, "get_retriever", lambda: _DummyRetriever()), \
         patch.object(svc_mod, "retrieve_candidates", lambda r, q: candidates), \
         patch.object(svc_mod, "retrieve_service_biased", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Phase 1 must NOT call biased retrieval"))), \
         patch.object(svc_mod, "grade_and_filter_yes", _grader_pass_all), \
         patch.object(svc_mod, "_infer_service_from_query", lambda q: None), \
         patch.object(svc_mod, "_fetch_service_definition_doc", lambda s: None):
        filtered, ctx_str, related = svc_mod._prepare_rag_context("generic question")

    assert len(filtered) == 4, f"expected 4 docs, got {len(filtered)}"
    services = {d.metadata.get("service") for d in filtered}
    assert len(services) >= 2, f"Phase 1 should span ≥2 services, got {services}"


def test_phase2_with_sa_label_returns_4_same_service():
    """When sa_service_label is set, biased retrieval is used. With
    same_k=4 / other_k=0 it returns 4 docs all from that service."""
    from modules.system_detection import sd_service as svc_mod

    biased_docs = [
        _doc("S: Market Research\nQ: q1\nA: a1", "Market Research"),
        _doc("S: Market Research\nQ: q2\nA: a2", "Market Research"),
        _doc("S: Market Research\nQ: q3\nA: a3", "Market Research"),
        _doc("S: Market Research\nQ: q4\nA: a4", "Market Research"),
    ]

    captured = {}

    def _capture_biased(question, aliases, same_k, other_k):
        captured["aliases"] = aliases
        captured["same_k"] = same_k
        captured["other_k"] = other_k
        return list(biased_docs)

    fake_cfg = SimpleNamespace(
        CTX_DOCS_SAME_SERVICE=4,
        CTX_DOCS_OTHER_SERVICE=0,
        CTX_DOCS_FLOOR=4,
        FAQ_VERIFICATOR="on",
        CTX_INFER_SERVICE_FROM_QUERY=True,
        CTX_PIN_SERVICE_DEFINITION=True,
    )

    with patch.object(svc_mod, "cfg", fake_cfg), \
         patch.object(svc_mod, "retrieve_candidates", lambda r, q: (_ for _ in ()).throw(AssertionError("Phase 2 must NOT call generic retrieval"))), \
         patch.object(svc_mod, "retrieve_service_biased", _capture_biased), \
         patch.object(svc_mod, "grade_and_filter_yes", _grader_pass_all), \
         patch.object(svc_mod, "_service_aliases", lambda s: [s, "MSY"]), \
         patch.object(svc_mod, "_infer_service_from_query", lambda q: None), \
         patch.object(svc_mod, "_fetch_service_definition_doc", lambda s: None):
        filtered, ctx_str, related = svc_mod._prepare_rag_context(
            "any question",
            sa_service_label="Market Research",
        )

    assert len(filtered) == 4, f"expected 4 docs, got {len(filtered)}"
    assert all(d.metadata["service"] == "Market Research" for d in filtered), \
        f"all docs must be Market Research, got {[d.metadata.get('service') for d in filtered]}"
    assert captured["same_k"] == 4 and captured["other_k"] == 0, \
        f"biased call should pass same_k=4 / other_k=0, got {captured}"


def test_pad_to_floor_after_grader_rejection():
    """Grader rejects 3 of 4 candidates → _pad_to_floor backfills from the
    rejected pool to keep floor=4, preserving similarity order."""
    from modules.system_detection import sd_service as svc_mod

    candidates = [
        _doc("S: A\nQ: q1\nA: a1", "Whistleblowing Hotline"),
        _doc("S: B\nQ: q2\nA: a2", "Whistleblowing Hotline"),
        _doc("S: C\nQ: q3\nA: a3", "Market Research"),
        _doc("S: D\nQ: q4\nA: a4", "Due Diligence"),
    ]

    fake_cfg = SimpleNamespace(
        CTX_DOCS_SAME_SERVICE=4,
        CTX_DOCS_OTHER_SERVICE=0,
        CTX_DOCS_FLOOR=4,
        FAQ_VERIFICATOR="on",
        CTX_INFER_SERVICE_FROM_QUERY=True,
        CTX_PIN_SERVICE_DEFINITION=True,
    )

    with patch.object(svc_mod, "cfg", fake_cfg), \
         patch.object(svc_mod, "get_retriever", lambda: _DummyRetriever()), \
         patch.object(svc_mod, "retrieve_candidates", lambda r, q: candidates), \
         patch.object(svc_mod, "grade_and_filter_yes", _grader_reject_all_but_one), \
         patch.object(svc_mod, "_infer_service_from_query", lambda q: None), \
         patch.object(svc_mod, "_fetch_service_definition_doc", lambda s: None):
        filtered, ctx_str, related = svc_mod._prepare_rag_context("question")

    assert len(filtered) == 4, f"floor=4 must be honored after grader rejection, got {len(filtered)}"
    assert filtered[0].page_content == candidates[0].page_content, \
        "first doc should be the grader-passed one"
    contents = [d.page_content for d in filtered]
    assert contents == [c.page_content for c in candidates], \
        f"backfill must preserve similarity order; got {contents}"


def test_phase1_does_not_use_auto_infer_for_bias():
    """Even when _infer_service_from_query matches, Phase 1 (no
    sa_service_label) must NOT call biased retrieval. Auto-infer's
    pin_def behavior should still fire when the query is explanatory."""
    from modules.system_detection import sd_service as svc_mod

    candidates = [
        _doc("S: A\nQ: q1\nA: a1", "Market Research"),
        _doc("S: B\nQ: q2\nA: a2", "Whistleblowing Hotline"),
        _doc("S: C\nQ: q3\nA: a3", "Due Diligence"),
        _doc("S: D\nQ: q4\nA: a4", "Market Research"),
    ]
    def_doc = _doc("S: Market Research\nQ: What is Market Research?\nA: Definition...", "Market Research")

    fake_cfg = SimpleNamespace(
        CTX_DOCS_SAME_SERVICE=4,
        CTX_DOCS_OTHER_SERVICE=0,
        CTX_DOCS_FLOOR=4,
        FAQ_VERIFICATOR="on",
        CTX_INFER_SERVICE_FROM_QUERY=True,
        CTX_PIN_SERVICE_DEFINITION=True,
    )

    with patch.object(svc_mod, "cfg", fake_cfg), \
         patch.object(svc_mod, "get_retriever", lambda: _DummyRetriever()), \
         patch.object(svc_mod, "retrieve_candidates", lambda r, q: candidates), \
         patch.object(svc_mod, "retrieve_service_biased", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Phase 1 must NOT call biased retrieval"))), \
         patch.object(svc_mod, "grade_and_filter_yes", _grader_pass_all), \
         patch.object(svc_mod, "_infer_service_from_query", lambda q: "Market Research"), \
         patch.object(svc_mod, "_is_explanation_intent", lambda q: True), \
         patch.object(svc_mod, "_fetch_service_definition_doc", lambda s: def_doc):
        filtered, ctx_str, related = svc_mod._prepare_rag_context("apa itu market research?")

    assert len(filtered) == 4, f"expected 4 docs, got {len(filtered)}"
    assert filtered[0].page_content == def_doc.page_content, \
        "definitional FAQ should be pinned at position 0 even when bias is decoupled"


def test_phase2_service_with_only_3_chunks():
    """Edge case: biased retrieval returns only 3 docs (service has <4
    chunks). _prepare_rag_context returns 3 docs (no error, no spillover)."""
    from modules.system_detection import sd_service as svc_mod

    biased_docs = [
        _doc("S: Tiny Service\nQ: q1\nA: a1", "Tiny Service"),
        _doc("S: Tiny Service\nQ: q2\nA: a2", "Tiny Service"),
        _doc("S: Tiny Service\nQ: q3\nA: a3", "Tiny Service"),
    ]

    fake_cfg = SimpleNamespace(
        CTX_DOCS_SAME_SERVICE=4,
        CTX_DOCS_OTHER_SERVICE=0,
        CTX_DOCS_FLOOR=4,
        FAQ_VERIFICATOR="on",
        CTX_INFER_SERVICE_FROM_QUERY=True,
        CTX_PIN_SERVICE_DEFINITION=True,
    )

    with patch.object(svc_mod, "cfg", fake_cfg), \
         patch.object(svc_mod, "retrieve_service_biased", lambda *a, **kw: list(biased_docs)), \
         patch.object(svc_mod, "grade_and_filter_yes", _grader_pass_all), \
         patch.object(svc_mod, "_service_aliases", lambda s: [s]), \
         patch.object(svc_mod, "_infer_service_from_query", lambda q: None), \
         patch.object(svc_mod, "_fetch_service_definition_doc", lambda s: None):
        filtered, ctx_str, related = svc_mod._prepare_rag_context(
            "question", sa_service_label="Tiny Service"
        )

    assert len(filtered) == 3, f"expected 3 docs (all that's available), got {len(filtered)}"
    assert all(d.metadata["service"] == "Tiny Service" for d in filtered)


def test_prepare_rag_context_normal_method_unchanged():
    """REDUNDANCY_METHOD=normal MUST NOT change behavior of _prepare_rag_context.
    Output must be byte-identical to pre-patch."""
    from modules.system_detection import sd_service as svc_mod

    candidates = [
        _doc("S: A\nQ: q1\nA: a1", "Whistleblowing Hotline"),
        _doc("S: B\nQ: q2\nA: a2", "Market Research"),
        _doc("S: C\nQ: q3\nA: a3", "Whistleblowing Hotline"),
        _doc("S: D\nQ: q4\nA: a4", "Due Diligence"),
    ]
    fake_cfg = SimpleNamespace(
        CTX_DOCS_SAME_SERVICE=4, CTX_DOCS_OTHER_SERVICE=0, CTX_DOCS_FLOOR=4,
        FAQ_VERIFICATOR="on", CTX_INFER_SERVICE_FROM_QUERY=True,
        CTX_PIN_SERVICE_DEFINITION=True,
        REDUNDANCY_METHOD="normal",  # ← key assertion
    )
    with patch.object(svc_mod, "cfg", fake_cfg), \
         patch.object(svc_mod, "get_retriever", lambda: _DummyRetriever()), \
         patch.object(svc_mod, "retrieve_candidates", lambda r, q: candidates), \
         patch.object(svc_mod, "grade_and_filter_yes", _grader_pass_all), \
         patch.object(svc_mod, "_infer_service_from_query", lambda q: None), \
         patch.object(svc_mod, "_fetch_service_definition_doc", lambda s: None):
        filtered, ctx_str, related = svc_mod._prepare_rag_context("q")
    # Same behavior as the pre-existing Phase-1 test: 4 docs spanning ≥2 services
    assert len(filtered) == 4
    services = {d.metadata.get("service") for d in filtered}
    assert len(services) >= 2


def test_prepare_rag_context_mmr_method_uses_strategy():
    """REDUNDANCY_METHOD=mmr → dispatcher returns docs from strategy module."""
    from modules.system_detection import sd_service as svc_mod

    mmr_docs = [
        _doc("S: X\nQ: qx\nA: ax", "Whistleblowing Hotline"),
        _doc("S: Y\nQ: qy\nA: ay", "Market Research"),
        _doc("S: Z\nQ: qz\nA: az", "Due Diligence"),
        _doc("S: W\nQ: qw\nA: aw", "Background Screening"),
    ]
    fake_cfg = SimpleNamespace(
        CTX_DOCS_SAME_SERVICE=4, CTX_DOCS_OTHER_SERVICE=0, CTX_DOCS_FLOOR=4,
        FAQ_VERIFICATOR="on", CTX_INFER_SERVICE_FROM_QUERY=True,
        CTX_PIN_SERVICE_DEFINITION=True,
        REDUNDANCY_METHOD="mmr",
    )
    with patch.object(svc_mod, "cfg", fake_cfg), \
         patch.object(svc_mod, "get_retriever", lambda: _DummyRetriever()), \
         patch.object(svc_mod, "retrieve_with_strategy", lambda *a, **kw: mmr_docs), \
         patch.object(svc_mod, "grade_and_filter_yes", _grader_pass_all), \
         patch.object(svc_mod, "_infer_service_from_query", lambda q: None), \
         patch.object(svc_mod, "_fetch_service_definition_doc", lambda s: None):
        filtered, ctx_str, related = svc_mod._prepare_rag_context("q")
    # Strategy result flows through unchanged
    assert len(filtered) == 4
    assert filtered[0].metadata["service"] == "Whistleblowing Hotline"


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
    print(f"\nAll tests passed.")
