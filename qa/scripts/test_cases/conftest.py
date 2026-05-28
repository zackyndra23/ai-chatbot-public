"""Shared pytest fixtures for the QA harness.

Fixtures:
- `target_url`: from QA_TARGET_URL env, default http://localhost:2305
- `kb_meta`: locked KB checksum at session start
- `kb_checksum_guard`: per-test sentinel that aborts if KB changed mid-run
- `current_method`: the REDUNDANCY_METHOD this pytest invocation is testing
- `http`: namespaced http_client.send_turn wrapper
- `mongo`: mongo_helpers module re-exported
- `fixtures_data`: loaded test_questions.yaml
- `record`: append a result row to the per-method JSONL file
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from qa.scripts.lib import http_client, kb_checksum, mongo_helpers, session_ids, target_guard


@pytest.fixture(scope="session")
def target_url() -> str:
    url = os.getenv("QA_TARGET_URL", "http://localhost:2305")
    allow_prod = os.getenv("QA_ALLOW_PROD") == "1"
    target_guard.assert_safe_target(url, allow_prod=allow_prod)
    return url


@pytest.fixture(scope="session")
def current_method() -> str:
    m = (os.getenv("QA_CURRENT_METHOD") or "").strip().lower()
    if m not in ("normal", "mmr", "fuzzy", "embedding"):
        pytest.exit(
            f"QA_CURRENT_METHOD env var must be one of normal/mmr/fuzzy/embedding "
            f"(got {m!r}). Set it before invoking pytest — usually run_qa_suite.py "
            f"does this for you.",
            returncode=2,
        )
    return m


@pytest.fixture(scope="session")
def kb_meta() -> dict[str, Any]:
    return kb_checksum.read_latest_kb_meta()


@pytest.fixture(autouse=True)
def kb_checksum_guard(kb_meta):
    """Verify KB checksum hasn't drifted between tests. Abort the run if it has."""
    current = kb_checksum.read_latest_kb_meta()
    if current["checksum"] != kb_meta["checksum"]:
        pytest.exit(
            f"KB checksum drifted mid-run: was {kb_meta['checksum']!r}, "
            f"now {current['checksum']!r}. Comparison baseline invalidated. Aborting.",
            returncode=3,
        )


@pytest.fixture(scope="session")
def fixtures_data() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "fixtures" / "test_questions.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def run_dir() -> Path:
    d = os.getenv("QA_RUN_DIR")
    if not d:
        pytest.exit(
            "QA_RUN_DIR env var must be set by the orchestrator. Aborting.",
            returncode=2,
        )
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def http(target_url):
    """Thin wrapper that auto-supplies target_url."""
    def _send(*, session_id: str, question: str, token_id: str | None = None, timeout_s: float = 30.0):
        return http_client.send_turn(
            base_url=target_url, session_id=session_id, question=question,
            token_id=token_id, timeout_s=timeout_s,
        )
    return _send


@pytest.fixture
def mongo():
    return mongo_helpers


@pytest.fixture
def make_session():
    return session_ids.make_session_id


@pytest.fixture
def record(current_method, run_dir):
    """Yield a callable that appends one result row to the per-method JSONL."""
    out = run_dir / f"method_{current_method}.jsonl"
    rows: list[dict[str, Any]] = []

    def _record(**fields):
        fields.setdefault("method", current_method)
        rows.append(fields)

    yield _record

    # Flush at teardown — atomic append per test
    with out.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
