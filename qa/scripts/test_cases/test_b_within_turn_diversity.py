"""Module B — Within-turn diversity per method.

Per question, count distinct Q-stems and distinct services in the Context
section of the prompt. Assert: under mmr/fuzzy/embedding, ≥3 distinct Q-stems
in top-4 chunks.
"""
from __future__ import annotations
import re
import pytest


pytestmark = pytest.mark.module_b


def _parse_context_qstems(prompt_text: str) -> list[str]:
    """Extract every 'Q: ...' line from the Context section of a rendered prompt."""
    stems: list[str] = []
    in_context = False
    for line in (prompt_text or "").splitlines():
        if line.startswith("Context:"):
            in_context = True
            continue
        if in_context and line.startswith("Q:"):
            stems.append(line[2:].strip()[:60].lower())
        if in_context and line.strip() == "" and stems:
            # blank line right after Q-block → safe to stop
            continue
    return stems


def _parse_context_services(prompt_text: str) -> list[str]:
    out: list[str] = []
    for line in (prompt_text or "").splitlines():
        if line.startswith("S:"):
            out.append(line[2:].strip().lower())
    return out


@pytest.mark.parametrize("case_idx", list(range(6)))
def test_b_within_turn_diversity(case_idx, fixtures_data, http, mongo, make_session, current_method, record):
    cases = fixtures_data["module_b_within_turn_diversity"]
    if case_idx >= len(cases):
        pytest.skip("case index out of range")
    case = cases[case_idx]
    cid = case["id"]
    test_case_label = f"diversity: {case['question'][:40]}"

    session_id = make_session(cid)
    resp = http(session_id=session_id, question=case["question"])
    wallclock_ms = resp["__wallclock_ms"]

    audit = mongo.read_latest_audit_for_session(session_id)
    prompt_text = str((audit or {}).get("llm_prompt", "")) if audit else ""

    q_stems = set(_parse_context_qstems(prompt_text))
    services = set(_parse_context_services(prompt_text))

    expected_threshold = 3  # ≥3 distinct Q-stems for non-normal methods
    if current_method == "normal":
        status = "PASS"  # normal is baseline — no diversity requirement, just capture metric
        delta = "N/A"
    else:
        status = "PASS" if len(q_stems) >= expected_threshold else "FAIL"
        delta = "computed_in_excel"  # Excel writer computes Δ vs Normal from raw metrics

    record(
        case_id=cid, module="B", type="Positive",
        test_case=test_case_label, status=status,
        expected=("≥3 distinct Q-stems in Context (for non-normal); metric captured for normal"),
        actual=f"q_stems={len(q_stems)} services={len(services)}",
        metric=f"q_stems={len(q_stems)};services={len(services)}",
        delta_vs_normal=delta,
        wallclock_ms=wallclock_ms,
        session_id=session_id,
        notes=f"chunks: {sorted(services)}",
    )
    if status == "FAIL":
        pytest.fail(f"{cid}: only {len(q_stems)} distinct Q-stems (<{expected_threshold})")
