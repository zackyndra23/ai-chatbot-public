"""Test mode dispatch in vb_service.build_and_swap (Stage 3A)."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_legacy_mode_calls_legacy_path_only():
    """KB_BACKEND=legacy → calls existing single-collection build, no per-service call."""
    from modules.vector_build import vb_service as vb

    with patch.object(vb, "cfg", SimpleNamespace(KB_BACKEND="legacy", VECTOR_DATA_DIR="/tmp",
                                                  VECTOR_CURRENT_SYMLINK="/tmp/current",
                                                  CHROMA_COLLECTION="faq_kb",
                                                  KB_META_COLL="kb_registry",
                                                  KB_NAMESPACE="faq",
                                                  MONGO_URI="x", MONGO_DB="db",
                                                  MONGO_FAQ_UPDATE="faq_update_doc",
                                                  EMBED_MODEL="m", OPENAI_API_KEY="k")), \
         patch.object(vb, "_legacy_build_and_swap_impl", MagicMock(return_value={"rebuilt": True, "docs": 5})) as legacy_mock, \
         patch.object(vb, "_per_service_build_and_swap_impl", MagicMock()) as per_svc_mock:
        result = vb.build_and_swap(force=False)

    legacy_mock.assert_called_once()
    per_svc_mock.assert_not_called()
    assert result["rebuilt"] is True


def test_split_mode_calls_per_service_path_only():
    from modules.vector_build import vb_service as vb

    with patch.object(vb, "cfg", SimpleNamespace(KB_BACKEND="split", VECTOR_DATA_DIR="/tmp",
                                                  VECTOR_CURRENT_SYMLINK="/tmp/current",
                                                  CHROMA_COLLECTION="faq_kb",
                                                  KB_META_COLL="kb_registry",
                                                  KB_NAMESPACE="faq",
                                                  MONGO_URI="x", MONGO_DB="db",
                                                  MONGO_FAQ_UPDATE="faq_update_doc",
                                                  EMBED_MODEL="m", OPENAI_API_KEY="k")), \
         patch.object(vb, "_legacy_build_and_swap_impl", MagicMock()) as legacy_mock, \
         patch.object(vb, "_per_service_build_and_swap_impl", MagicMock(return_value={"per_service": [], "orphans_removed": []})) as per_svc_mock:
        result = vb.build_and_swap(force=False)

    legacy_mock.assert_not_called()
    per_svc_mock.assert_called_once()
    assert "per_service" in result


def test_dual_mode_calls_both_and_logs_divergence():
    from modules.vector_build import vb_service as vb

    legacy_result = {"rebuilt": True, "docs": 100}
    per_svc_result = {
        "per_service": [
            {"service_id": "wbs", "rebuilt": True, "doc_count": 40},
            {"service_id": "ms", "rebuilt": True, "doc_count": 50},
        ],
        "orphans_removed": [],
    }

    audit_logs: list[dict] = []

    with patch.object(vb, "cfg", SimpleNamespace(KB_BACKEND="dual", VECTOR_DATA_DIR="/tmp",
                                                  VECTOR_CURRENT_SYMLINK="/tmp/current",
                                                  CHROMA_COLLECTION="faq_kb",
                                                  KB_META_COLL="kb_registry",
                                                  KB_NAMESPACE="faq",
                                                  MONGO_URI="x", MONGO_DB="db",
                                                  MONGO_FAQ_UPDATE="faq_update_doc",
                                                  EMBED_MODEL="m", OPENAI_API_KEY="k")), \
         patch.object(vb, "_legacy_build_and_swap_impl", MagicMock(return_value=legacy_result)), \
         patch.object(vb, "_per_service_build_and_swap_impl", MagicMock(return_value=per_svc_result)), \
         patch.object(vb, "_audit_divergence", lambda d: audit_logs.append(d)):
        result = vb.build_and_swap(force=False)

    # Both paths called
    assert "per_service" in result
    assert "legacy" in result
    # Divergence detected: legacy=100, per_service total=90
    assert len(audit_logs) == 1
    assert audit_logs[0]["legacy_total"] == 100
    assert audit_logs[0]["per_service_total"] == 90


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
