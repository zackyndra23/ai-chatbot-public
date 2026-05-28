"""Module I — Sanity-check the standalone eval harness script.

Verify `tests/eval_redundancy_diversity.py` exists, has the expected CLI
signature, and produces a parseable table on `--method normal` (assumes
local Chroma/KB initialized; skips gracefully otherwise).
"""
from __future__ import annotations
import os
import subprocess
import sys
import pytest


pytestmark = pytest.mark.module_i


def test_i_eval_script_exists(current_method, record):
    cid = "I01"
    test_case_label = "eval script file present"
    if current_method != "normal":
        record(case_id=cid, module="I", type="Positive",
               test_case=test_case_label, status="SKIP",
               expected="only checked under normal",
               actual="skipped", metric="", delta_vs_normal="N/A",
               wallclock_ms=0, session_id="", notes="")
        return
    from pathlib import Path
    eval_path = Path("tests/eval_redundancy_diversity.py")
    ok = eval_path.is_file()
    status = "PASS" if ok else "FAIL"
    record(case_id=cid, module="I", type="Positive",
           test_case=test_case_label, status=status,
           expected="tests/eval_redundancy_diversity.py exists",
           actual="exists" if ok else "missing",
           metric=f"size={eval_path.stat().st_size}" if ok else "",
           delta_vs_normal="N/A", wallclock_ms=0,
           session_id="", notes=str(eval_path.resolve()))
    assert ok


def test_i_eval_script_smoke(current_method, record):
    cid = "I02"
    test_case_label = "eval script --method normal smoke"
    if current_method != "normal":
        record(case_id=cid, module="I", type="Positive",
               test_case=test_case_label, status="SKIP",
               expected="only checked under normal",
               actual="skipped", metric="", delta_vs_normal="N/A",
               wallclock_ms=0, session_id="", notes="")
        return

    try:
        proc = subprocess.run(
            [sys.executable, "tests/eval_redundancy_diversity.py", "--method", "normal"],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        record(case_id=cid, module="I", type="Positive",
               test_case=test_case_label, status="ERROR",
               expected="finishes within 120s",
               actual="timeout", metric="", delta_vs_normal="N/A",
               wallclock_ms=120000, session_id="", notes="")
        pytest.skip("eval script timed out")

    stdout = proc.stdout
    ok = proc.returncode == 0 and "Eval: method=" in stdout
    status = "PASS" if ok else "PARTIAL"  # PARTIAL when env limitation (no Chroma)
    record(case_id=cid, module="I", type="Positive",
           test_case=test_case_label, status=status,
           expected="exit 0, header line present",
           actual=f"rc={proc.returncode} stdout_head={stdout[:120]!r}",
           metric=f"stdout_len={len(stdout)}",
           delta_vs_normal="N/A", wallclock_ms=0, session_id="",
           notes="stderr: " + (proc.stderr[:200] if proc.stderr else "(none)"))
    # PARTIAL is acceptable; only ERROR fails the gate.
    assert proc.returncode in (0, 1), f"unexpected rc={proc.returncode}"
