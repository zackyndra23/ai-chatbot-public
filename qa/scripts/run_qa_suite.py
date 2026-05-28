"""QA suite orchestrator.

Runs pytest 4 times (once per method), aggregates JSONL results, writes
master_test_cases.xlsx. Operator manually flips REDUNDANCY_METHOD in .env
and restarts Flask between methods.

Usage:
    python qa/scripts/run_qa_suite.py                          # all methods, default port
    python qa/scripts/run_qa_suite.py --method mmr             # one method only
    python qa/scripts/run_qa_suite.py --target http://10.30.40.155:2305 --allow-prod
    python qa/scripts/run_qa_suite.py --perf-samples 30        # bump perf sample count
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Load .env into os.environ so subprocesses (pytest) inherit it.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
    # Auto-set WEBSITE_ID for chatbot endpoint if TESTING_WEBSITEID exists.
    if not os.getenv("WEBSITE_ID") and os.getenv("TESTING_WEBSITEID"):
        os.environ["WEBSITE_ID"] = os.environ["TESTING_WEBSITEID"]
except ImportError:
    pass

from qa.scripts.lib import kb_checksum, target_guard
from qa.scripts.lib.excel_writer import write_workbook

METHODS = ("normal", "mmr", "fuzzy", "embedding")


def _confirm_method(method: str, target_url: str) -> None:
    print()
    print("=" * 72)
    print(f"NEXT METHOD: {method}")
    print("=" * 72)
    print(f"  1. Set REDUNDANCY_METHOD={method} in your .env file")
    print(f"  2. Restart Flask (the chatbot process listening on {target_url})")
    print(f"  3. Wait for it to be ready")
    print()
    input("Press ENTER when ready (or Ctrl-C to abort)... ")


def _run_pytest_for_method(method: str, run_dir: Path, target_url: str, perf_samples: int) -> int:
    env = os.environ.copy()
    env["QA_CURRENT_METHOD"] = method
    env["QA_RUN_DIR"] = str(run_dir)
    env["QA_TARGET_URL"] = target_url
    env["QA_PERF_SAMPLES"] = str(perf_samples)
    cmd = [
        sys.executable, "-m", "pytest",
        "qa/scripts/test_cases/",
        "-v", "--tb=short",
        f"--junitxml={run_dir / f'junit_{method}.xml'}",
    ]
    print(f"\n[{method}] running pytest...\n")
    proc = subprocess.run(cmd, env=env)
    return proc.returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--method", default="all", choices=("all",) + METHODS)
    p.add_argument("--target", default=os.getenv("QA_TARGET_URL", "http://localhost:2305"))
    p.add_argument("--allow-prod", action="store_true")
    p.add_argument("--perf-samples", type=int, default=10)
    p.add_argument("--run-dir", default=None,
                   help="Reuse an existing run dir (e.g. for multi-method runs with operator Flask restarts between methods). "
                        "When omitted, a fresh qa/runs/<timestamp>/ is created.")
    p.add_argument("--skip-pytest", action="store_true",
                   help="Skip pytest run; only aggregate existing JSONLs to Excel. Used after a multi-run sequence.")
    args = p.parse_args()

    target_guard.assert_safe_target(args.target, allow_prod=args.allow_prod)

    # KB checksum lock
    kb_meta = kb_checksum.read_latest_kb_meta()
    print(f"KB checksum locked: {kb_meta['checksum']} (doc_count={kb_meta['doc_count']})")

    if args.run_dir:
        run_dir = Path(args.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = REPO_ROOT / "qa" / "runs" / ts
        run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "kb_checksum.json").write_text(json.dumps(kb_meta, indent=2, default=str), encoding="utf-8")
    (run_dir / "run_meta.json").write_text(
        json.dumps({"target": args.target, "started_at": run_dir.name, "perf_samples": args.perf_samples}, indent=2),
        encoding="utf-8",
    )

    rc = 0
    if not args.skip_pytest:
        methods = METHODS if args.method == "all" else (args.method,)
        for m in methods:
            if args.method == "all":
                _confirm_method(m, args.target)
            rc |= _run_pytest_for_method(m, run_dir, args.target, args.perf_samples)

    # Re-verify KB checksum constant
    kb_after = kb_checksum.read_latest_kb_meta()
    if kb_after["checksum"] != kb_meta["checksum"]:
        print(f"\n!!! KB checksum changed mid-run: {kb_meta['checksum']} -> {kb_after['checksum']}", file=sys.stderr)
        rc = 4

    # Aggregate to Excel
    output_xlsx = REPO_ROOT / "qa" / "test-cases" / "master_test_cases.xlsx"
    output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    write_workbook(
        run_dir=run_dir, output_xlsx=output_xlsx,
        kb_meta=kb_meta, target_url=args.target,
    )
    print(f"\n[OK] Workbook written: {output_xlsx}")
    print(f"     Run artifacts:    {run_dir}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
