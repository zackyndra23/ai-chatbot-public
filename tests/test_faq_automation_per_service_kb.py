"""End-to-end test for /faq-automation per-service KB rebuild flow."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_run_pipeline_response_includes_kb_per_service_in_split_mode():
    """When KB_BACKEND=split, run_pipeline response includes kb_per_service array."""
    from modules.faq_automation.faq_service import FAQService

    repo_mock = MagicMock()
    repo_mock.list_services = MagicMock(return_value=[
        {"service_id": "wbs", "service_name": "WBS"},
    ])
    repo_mock.delete_services_not_in = MagicMock(return_value=[])
    repo_mock.upsert_service = MagicMock(return_value={"created": False, "doc_id": "x", "chunks_count": 1})

    pipelines_mock = MagicMock()
    pipelines_mock.build_service_bundles = MagicMock(return_value=[
        MagicMock(service_id="wbs", service_name="WBS", text="...", chunks=[{"text": "q1"}])
    ])

    fake_build_and_swap_result = {
        "backend_mode": "split",
        "per_service": [
            {"service_id": "wbs", "rebuilt": True, "doc_count": 38, "checksum": "sha256:abc"},
        ],
        "orphans_removed": [],
    }

    cfg_mock = MagicMock()
    cfg_mock.KB_BACKEND = "split"

    svc = FAQService(cfg=cfg_mock, repo=repo_mock, pipelines=pipelines_mock)

    fake_bundle = MagicMock()
    fake_bundle.service_id = "wbs"
    fake_bundle.service_name = "WBS"
    fake_bundle.text = "..."
    fake_bundle.chunks = [{"text": "q1"}]

    with patch("modules.faq_automation.faq_service.build_and_swap", lambda force: fake_build_and_swap_result), \
         patch("modules.faq_automation.faq_service.build_service_bundles", return_value=[fake_bundle]):
        result = svc.run_pipeline(source="test")

    assert "kb_per_service" in result, f"missing kb_per_service in {result.keys()}"
    assert result["kb_per_service"] == [
        {"service_id": "wbs", "rebuilt": True, "doc_count": 38, "checksum": "sha256:abc"},
    ]


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
