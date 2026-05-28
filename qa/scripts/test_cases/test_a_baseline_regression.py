"""Module A — Baseline regression for REDUNDANCY_METHOD=normal.

Structural assertions only (LLM reply text is nondeterministic; we verify
that the new code paths DO NOT execute when method=normal).
"""
from __future__ import annotations
import pytest


pytestmark = pytest.mark.module_a


def _cases(fixtures_data):
    return fixtures_data["module_b_within_turn_diversity"][:3]


@pytest.mark.parametrize("case_idx", [0, 1, 2])
def test_a_baseline_structural(case_idx, fixtures_data, http, mongo, make_session, current_method, record):
    """When method=normal, audit + payload + chat_history must reflect the
    strict-additive guarantee (no recent_chunk_ids, no dedup wrapper)."""
    case = _cases(fixtures_data)[case_idx]
    cid = case["id"].replace("B", "A")  # A01/A02/A03
    test_case_label = f"baseline: {case['question'][:40]}"

    # Only run under normal — SKIP for other methods (orchestrator still
    # invokes pytest per method, so a SKIP record gets written).
    if current_method != "normal":
        record(case_id=cid, module="A", type="Regression",
               test_case=test_case_label, status="SKIP",
               expected="Only normal method runs Module A",
               actual=f"Skipped under {current_method}", metric="", notes="")
        return

    session_id = make_session(cid)
    resp = http(session_id=session_id, question=case["question"])
    wallclock_ms = resp["__wallclock_ms"]

    audit = mongo.read_latest_audit_for_session(session_id)
    chat_doc = mongo.read_chat_history_doc(session_id)

    failures: list[str] = []

    if not audit:
        failures.append("no audit row found")
    else:
        rm = (audit.get("extras") or {}).get("retrieval_method")
        if rm != "normal":
            failures.append(f"audit.extras.retrieval_method = {rm!r}, expected 'normal'")

    if not chat_doc:
        failures.append("no chat_history doc found")
    else:
        if "recent_chunk_ids" in chat_doc:
            failures.append(f"chat_history doc has recent_chunk_ids field (should be absent for normal)")
        turns = chat_doc.get("chat_history") or []
        if turns:
            last_extra = (turns[-1].get("extra") or {})
            rm2 = last_extra.get("retrieval_method")
            if rm2 != "normal":
                failures.append(f"chat_history turn extra.retrieval_method = {rm2!r}, expected 'normal'")

    # Capture chunk_ids for baseline snapshot (future runs can compare)
    chunk_ids: list[str] = []
    if audit:
        chunk_ids = list((audit.get("extras") or {}).get("retrieved_chunk_ids") or [])

    status = "PASS" if not failures else "FAIL"
    record(
        case_id=cid, module="A", type="Regression",
        test_case=test_case_label, status=status,
        expected=("audit.extras.retrieval_method='normal' AND no recent_chunk_ids field "
                  "AND chat_history turn extra.retrieval_method='normal'"),
        actual=("OK" if not failures else "; ".join(failures)),
        metric=f"chunk_ids:{len(chunk_ids)}",
        delta_vs_normal="N/A",
        wallclock_ms=wallclock_ms,
        session_id=session_id,
        notes="baseline snapshot",
    )
    assert not failures, f"Module A baseline regression: {failures}"
