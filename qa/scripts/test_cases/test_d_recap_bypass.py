"""Module D — Explicit recap bypass across 4 languages.

For each case: turn-1 pre_turn (normal flow), turn-2 recap phrase.
For non-normal: recent_chunk_ids size must NOT grow on the recap turn.
For normal: recent_chunk_ids absent on both turns.
"""
from __future__ import annotations
import pytest


pytestmark = pytest.mark.module_d


@pytest.mark.parametrize("case_idx", [0, 1, 2, 3])
def test_d_recap_bypass(case_idx, fixtures_data, http, mongo, make_session, current_method, record):
    cases = fixtures_data["module_d_recap_bypass"]
    if case_idx >= len(cases):
        pytest.skip("case index out of range")
    case = cases[case_idx]
    cid = case["id"]
    test_case_label = f"recap-{case['language']}: {case['recap_turn'][:30]}"

    from qa.scripts.lib.session_ids import new_run_uuid, make_session_id
    run_uuid = new_run_uuid()
    session_id = make_session_id(cid, run_uuid=run_uuid)

    # Turn 1: pre_turn
    http(session_id=session_id, question=case["pre_turn"])
    doc1 = mongo.read_chat_history_doc(session_id) or {}
    rc1 = list(doc1.get("recent_chunk_ids") or [])

    # Turn 2: recap phrase
    http(session_id=session_id, question=case["recap_turn"])
    doc2 = mongo.read_chat_history_doc(session_id) or {}
    rc2 = list(doc2.get("recent_chunk_ids") or [])

    failures: list[str] = []
    if current_method == "normal":
        if rc1 or rc2:
            failures.append(f"normal mode wrote recent_chunk_ids (turn1={len(rc1)} turn2={len(rc2)})")
        status = "PASS" if not failures else "FAIL"
        metric = "rc=0 (expected for normal)"
    else:
        # recent_chunk_ids should populate after turn 1 but NOT grow on recap turn.
        if not rc1:
            failures.append("turn1 didn't populate recent_chunk_ids")
        elif len(rc2) != len(rc1):
            failures.append(f"recap turn changed recent_chunk_ids: turn1={len(rc1)}, turn2={len(rc2)} — expected equal")
        status = "PASS" if not failures else "FAIL"
        metric = f"turn1_rc={len(rc1)}, turn2_rc={len(rc2)}"

    record(
        case_id=cid, module="D", type="Boundary",
        test_case=test_case_label, status=status,
        expected="recap turn does NOT mutate recent_chunk_ids (non-normal); both empty for normal",
        actual=("OK" if not failures else "; ".join(failures)),
        metric=metric,
        delta_vs_normal="N/A",
        wallclock_ms=0,
        session_id=session_id,
        notes=f"language={case['language']}",
    )
    if status == "FAIL":
        pytest.fail(f"{cid}: {failures}")
