"""Generate unique QA session IDs to avoid crosstalk with real users."""
from __future__ import annotations
import uuid
from datetime import datetime


def make_session_id(test_id: str, *, run_uuid: str | None = None) -> str:
    """Build session_id of the form 'qa-YYYYMMDD-HHMMSS-<test_id>-<uuid8>'.

    test_id must be the case identifier from the YAML fixture (e.g. 'B01').
    run_uuid: optionally fix the per-run UUID across multiple session IDs in
    the same test (for multi-turn sequences). When omitted, fresh UUID per
    call.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rid = (run_uuid or uuid.uuid4().hex)[:8]
    return f"qa-{ts}-{test_id}-{rid}"


def new_run_uuid() -> str:
    """Fresh 8-char hex token for a logical run (e.g. one test's all turns)."""
    return uuid.uuid4().hex[:8]
