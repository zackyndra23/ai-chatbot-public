"""Module E — Off-topic question must NOT trigger hallucinated content.

Bot should reply with the apology/handoff phrase (per language), not invent.
Asserts: reply text contains no forbidden_substrings AND contains at least one
expected_substring_any item. Runs across all 4 methods.
"""
from __future__ import annotations
import pytest


pytestmark = pytest.mark.module_e


def _extract_reply(resp: dict) -> str:
    msg = resp.get("message", "")
    if isinstance(msg, dict):
        content = msg.get("content") or {}
        return str(content.get("text") or "")
    return str(msg)


@pytest.mark.parametrize("case_idx", [0, 1])
def test_e_hallucination_guard(case_idx, fixtures_data, http, mongo, make_session, current_method, record):
    cases = fixtures_data["module_e_hallucination_guard"]
    if case_idx >= len(cases):
        pytest.skip("case index out of range")
    case = cases[case_idx]
    cid = case["id"]
    test_case_label = f"hallucination-{case['language']}: {case['question'][:40]}"

    session_id = make_session(cid)
    resp = http(session_id=session_id, question=case["question"])
    reply = _extract_reply(resp).lower()

    forbidden = [s.lower() for s in case.get("forbidden_substrings", [])]
    expected_any = [s.lower() for s in case.get("expected_substrings_any", [])]

    failures: list[str] = []
    found_forbidden = [s for s in forbidden if s in reply]
    if found_forbidden:
        failures.append(f"reply contains forbidden substring(s): {found_forbidden}")
    has_any = any(s in reply for s in expected_any)
    if expected_any and not has_any:
        failures.append(f"reply contains none of expected handoff phrases {expected_any}")

    status = "PASS" if not failures else "FAIL"
    record(
        case_id=cid, module="E", type="Negative",
        test_case=test_case_label, status=status,
        expected=f"no {forbidden} AND any of {expected_any}",
        actual=("OK" if not failures else "; ".join(failures)),
        metric=f"reply_len={len(reply)}",
        delta_vs_normal="N/A",
        wallclock_ms=resp["__wallclock_ms"],
        session_id=session_id,
        notes=case["language"],
    )
    if status == "FAIL":
        pytest.fail(f"{cid}: {failures}")
