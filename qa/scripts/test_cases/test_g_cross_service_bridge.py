"""Module G — Cross-service bridge with anti-redundancy filter.

Multi-turn flow:
  T1: send domain question, receive SA_SELECT picker
  T2: click SA_SELECT_<target> to enter SA flow
  T3: answer first qualification question
  T4: ask about a DIFFERENT service (cross-service trigger)

Assert (mmr only): T4 audit has route='sa_cross_service_bridge' AND
extras.retrieval_method='mmr' AND chat_history doc has populated recent_chunk_ids.
"""
from __future__ import annotations
import pytest


pytestmark = pytest.mark.module_g


def test_g_cross_service(fixtures_data, http, mongo, make_session, current_method, record):
    cases = fixtures_data["module_g_cross_service"]
    if not cases:
        pytest.skip("no module_g fixtures")
    case = cases[0]
    cid = case["id"]
    test_case_label = f"cross-service-bridge: {case['target_short_label']}"

    if current_method == "normal":
        # Normal still flows through the bridge but doesn't filter — record but PASS.
        pass

    from qa.scripts.lib.session_ids import new_run_uuid, make_session_id
    run_uuid = new_run_uuid()
    session_id = make_session_id(cid, run_uuid=run_uuid)

    # T1: trigger handoff via domain question
    http(session_id=session_id, question="Saya tertarik dengan whistleblowing system")
    # T2: click SA_SELECT picker value
    http(session_id=session_id, question=case["handoff_value"])
    # T3: answer Q1
    http(session_id=session_id, question=case["q1_answer"])
    # T4: cross-service trigger
    resp4 = http(session_id=session_id, question=case["cross_service_question"])

    audits = mongo.read_all_audits_for_session(session_id)
    last_bridge = next((a for a in reversed(audits) if a.get("stage") == "sa_cross_service_bridge"), None)
    chat_doc = mongo.read_chat_history_doc(session_id)

    failures: list[str] = []
    if not last_bridge:
        failures.append("no audit row with stage=sa_cross_service_bridge found")
    else:
        rm = (last_bridge.get("extras") or {}).get("retrieval_method")
        if rm != current_method:
            failures.append(f"bridge audit retrieval_method={rm!r}, expected {current_method!r}")

    if current_method != "normal":
        rc = (chat_doc or {}).get("recent_chunk_ids") or []
        if not rc:
            failures.append("recent_chunk_ids empty after bridge turn (non-normal)")

    status = "PASS" if not failures else "FAIL"
    record(
        case_id=cid, module="G", type="Positive",
        test_case=test_case_label, status=status,
        expected="bridge audit + filter active under non-normal",
        actual=("OK" if not failures else "; ".join(failures)),
        metric=f"audits={len(audits)}, has_bridge={bool(last_bridge)}",
        delta_vs_normal="N/A",
        wallclock_ms=resp4["__wallclock_ms"],
        session_id=session_id,
        notes="4-turn flow",
    )
    if status == "FAIL":
        pytest.fail(f"{cid}: {failures}")
