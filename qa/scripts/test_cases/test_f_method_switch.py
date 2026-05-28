"""Module F — Verify runtime kill-switch: audit + payload reflect current method.

Single question per method. Assert: audit.extras.retrieval_method matches the
expected current method AND chat_history turn extra.retrieval_method matches.
"""
from __future__ import annotations
import pytest


pytestmark = pytest.mark.module_f


def test_f_method_switch(fixtures_data, http, mongo, make_session, current_method, record):
    cases = fixtures_data["module_f_method_switch"]
    if not cases:
        pytest.skip("no module_f fixtures")
    case = cases[0]
    cid = case["id"]
    test_case_label = f"method-switch: {current_method}"

    session_id = make_session(f"{cid}-{current_method}")
    resp = http(session_id=session_id, question=case["question"])
    audit = mongo.read_latest_audit_for_session(session_id)
    chat_doc = mongo.read_chat_history_doc(session_id)

    failures: list[str] = []
    if not audit:
        failures.append("no audit row")
    else:
        rm = (audit.get("extras") or {}).get("retrieval_method")
        if rm != current_method:
            failures.append(f"audit.extras.retrieval_method={rm!r}, expected {current_method!r}")

    if not chat_doc or not chat_doc.get("chat_history"):
        failures.append("no chat_history doc / turns")
    else:
        last_turn = chat_doc["chat_history"][-1]
        rm2 = (last_turn.get("extra") or {}).get("retrieval_method")
        if rm2 != current_method:
            failures.append(f"chat_history turn extra.retrieval_method={rm2!r}, expected {current_method!r}")

    status = "PASS" if not failures else "FAIL"
    record(
        case_id=cid, module="F", type="Positive",
        test_case=test_case_label, status=status,
        expected=f"both audit and chat_history record retrieval_method={current_method!r}",
        actual=("OK" if not failures else "; ".join(failures)),
        metric=f"method={current_method}",
        delta_vs_normal="N/A",
        wallclock_ms=resp["__wallclock_ms"],
        session_id=session_id,
        notes="kill-switch verification",
    )
    assert not failures, f"{cid}: {failures}"
