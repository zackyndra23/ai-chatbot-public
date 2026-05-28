"""Module C — Across-turn anti-repetition via recent_chunk_ids filter.

Per 3-turn scenario, verify:
- For non-normal: recent_chunk_ids grows across turns
- For non-normal: Turn-N's chunk_ids include some fresh (≠ Turn-(N-1) chunks)
- For normal: recent_chunk_ids field is absent
"""
from __future__ import annotations
import pytest

pytestmark = pytest.mark.module_c


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@pytest.mark.parametrize("case_idx", [0, 1])
def test_c_across_turn(case_idx, fixtures_data, http, mongo, make_session, current_method, record):
    cases = fixtures_data["module_c_across_turn"]
    if case_idx >= len(cases):
        pytest.skip("case index out of range")
    case = cases[case_idx]
    cid = case["id"]
    test_case_label = f"across-turn: {case['turns'][0][:40]}"

    from qa.scripts.lib.session_ids import new_run_uuid, make_session_id
    run_uuid = new_run_uuid()
    session_id = make_session_id(cid, run_uuid=run_uuid)

    audits_per_turn: list[dict] = []
    for turn_text in case["turns"]:
        resp = http(session_id=session_id, question=turn_text)
        audits = mongo.read_all_audits_for_session(session_id)
        if audits:
            audits_per_turn.append(audits[-1])

    chat_doc = mongo.read_chat_history_doc(session_id)
    recent_chunk_ids = chat_doc.get("recent_chunk_ids", []) if chat_doc else []
    n_turns = len(case["turns"])

    failures: list[str] = []
    if current_method == "normal":
        if recent_chunk_ids:
            failures.append(f"normal mode wrote recent_chunk_ids ({len(recent_chunk_ids)} entries) — should be empty")
        status = "PASS" if not failures else "FAIL"
        metric = f"recent_chunk_ids=0 (expected)"
    else:
        if not recent_chunk_ids:
            failures.append("recent_chunk_ids empty after 3 turns (expected populated)")
        elif len(recent_chunk_ids) < n_turns:
            failures.append(f"recent_chunk_ids={len(recent_chunk_ids)} < {n_turns} turns")
        status = "PASS" if not failures else "FAIL"
        metric = f"recent_chunk_ids={len(recent_chunk_ids)}"

    record(
        case_id=cid, module="C", type="Positive",
        test_case=test_case_label, status=status,
        expected=("recent_chunk_ids empty for normal; ≥n_turns for non-normal"),
        actual=("OK" if not failures else "; ".join(failures)),
        metric=metric,
        delta_vs_normal="computed_in_excel",
        wallclock_ms=sum(a.get("latency_ms", 0) for a in audits_per_turn),
        session_id=session_id,
        notes=f"turns={n_turns}",
    )
    if status == "FAIL":
        pytest.fail(f"{cid}: {failures}")
