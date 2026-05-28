"""Diversity eval harness for the anti-redundancy stage.

Manual exploration tool. Prints a per-question table comparing the top-4
chunks returned per method.

Usage:
    python tests/eval_redundancy_diversity.py --method normal
    python tests/eval_redundancy_diversity.py --method mmr
    python tests/eval_redundancy_diversity.py --method fuzzy
    python tests/eval_redundancy_diversity.py --method embedding

Exits 0 always — not a CI gate.
"""
from __future__ import annotations
import argparse, os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 10 hand-labeled questions with expected service label that should appear
# at least once in top-4.
EVAL_QUESTIONS = [
    ("apa itu whistleblowing", "Whistleblowing Hotline"),
    ("bagaimana mencegah fraud", "Whistleblowing Hotline"),
    ("berapa biaya layanan due diligence", "Due Diligence"),
    ("apa itu mystery shopping", "Mystery Shopping"),
    ("market research untuk produk baru", "Market Research"),
    ("background screening karyawan", "Background Check"),
    ("anti-bribery management system", "Anti-Bribery Management System"),
    ("ISO 37001 sertifikasi", "Anti-Bribery Management System"),
    ("audit kepatuhan perusahaan", "Whistleblowing Hotline"),
    ("layanan apa saja yang tersedia", "General"),
]


def _q_stem(page_content: str) -> str:
    """Extract the 'Q: ...' line stem (first 50 chars) for distinctness counting."""
    for line in page_content.split("\n"):
        if line.startswith("Q:"):
            return line[2:].strip()[:50].lower()
    return page_content[:50].lower()


def _service_of(doc) -> str:
    return (doc.metadata or {}).get("service") or "?"


def _run_one(method: str, question: str, expected_service: str) -> dict:
    """Run a single query through the live retrieval pipeline and capture top-4."""
    os.environ["REDUNDANCY_METHOD"] = method
    # Reload Config so env override sticks
    from importlib import reload
    from core import app_config
    reload(app_config)
    # Reload sd_service to pick up new cfg
    from modules.system_detection import sd_service
    reload(sd_service)

    filtered, _ctx, _related = sd_service._prepare_rag_context(question)
    top4 = filtered[:4]
    q_stems = {_q_stem(d.page_content) for d in top4}
    services = {_service_of(d) for d in top4}
    return {
        "question": question,
        "expected_service": expected_service,
        "n_docs": len(top4),
        "distinct_q_stems": len(q_stems),
        "distinct_services": len(services),
        "expected_present": expected_service in services,
        "services": sorted(services),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--method", default="normal", choices=["normal", "mmr", "fuzzy", "embedding"])
    args = p.parse_args()
    print(f"\n=== Eval: method={args.method} ===\n")
    print(f"{'Q':<46} {'docs':>4} {'qstems':>6} {'svcs':>4} {'exp':>3}  services")
    print("-" * 100)
    for q, expected in EVAL_QUESTIONS:
        row = _run_one(args.method, q, expected)
        print(f"{q[:46]:<46} {row['n_docs']:>4} {row['distinct_q_stems']:>6} "
              f"{row['distinct_services']:>4} {('Y' if row['expected_present'] else 'N'):>3}  "
              f"{', '.join(row['services'])}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
