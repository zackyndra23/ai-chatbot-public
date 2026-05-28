"""Extract Method A baseline metrics from production audit + chat_history.

Run before Method B hypothesis test (Section 10G.G2 of spec). Outputs JSON
with reference thresholds for Method B comparison.

Usage:
    python qa/scripts/extract_method_a_baseline.py --session-limit 100
    python qa/scripts/extract_method_a_baseline.py --output qa/runs/method_a_baseline.json
"""
from __future__ import annotations
import argparse, json, os, sys, statistics
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from pymongo import MongoClient


def extract_baseline(session_limit: int = 100) -> dict:
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI required")
    db = MongoClient(uri)[os.getenv("MONGO_DB", "faq_automation")]
    qr = db[os.getenv("QUERY_RECORDING_COLL", "query_recording")]
    ch = db[os.getenv("CHAT_HISTORY_COLL", "chat_history")]

    # Find recent Method A sessions: those with stage="intent_type" rows
    # AND no stage="qualification_b" rows.
    method_a_sessions = qr.distinct("sessionId", {"stage": "intent_type"})
    method_b_sessions = set(qr.distinct("sessionId", {"stage": {"$in": ["qualification_b", "qualification_b_rescue"]}}))
    eligible = [s for s in method_a_sessions if s and s not in method_b_sessions][:session_limit]

    print(f"Found {len(method_a_sessions)} Method A candidate sessions; "
          f"using top {len(eligible)} (limit={session_limit})")

    turn_to_picker = []
    drop_off_count = 0
    keyword_trigger_count = 0
    popup_trigger_count = 0
    latencies_ms = []
    for sid in eligible:
        # Count qualification turns
        audit_rows = list(qr.find({"sessionId": sid, "stage": {"$in": ["intent_type", "intent_interest"]}})
                            .sort("timestamp", 1))
        if not audit_rows:
            continue
        # Did picker fire? Check chat_history for messages with picker choices.
        ch_doc = ch.find_one({"sessionId": sid}) or {}
        turns = ch_doc.get("chat_history") or []
        picker_turn_idx = None
        for i, t in enumerate(turns):
            msg = t.get("message")
            if isinstance(msg, dict) and (msg.get("content") or {}).get("choices"):
                picker_turn_idx = i
                break
        if picker_turn_idx is None:
            drop_off_count += 1
        else:
            turn_to_picker.append(picker_turn_idx + 1)  # 1-indexed
        # Latency per qualification turn (sum of intent_type + intent_interest)
        per_turn = {}
        for row in audit_rows:
            per_turn.setdefault(row.get("turnId") or row.get("sessionId"), 0)
            per_turn[row.get("turnId") or row.get("sessionId")] += int(row.get("latency_ms") or 0)
        latencies_ms.extend(per_turn.values())

    def pct(values, p):
        if not values:
            return 0
        s = sorted(values)
        idx = min(len(s) - 1, int(round((len(s) - 1) * p)))
        return s[idx]

    return {
        "extracted_at": datetime.now().isoformat(),
        "session_count_examined": len(eligible),
        "turn_to_picker_median": int(statistics.median(turn_to_picker)) if turn_to_picker else None,
        "turn_to_picker_mean": round(statistics.mean(turn_to_picker), 2) if turn_to_picker else None,
        "drop_off_rate_pct": round(drop_off_count / len(eligible) * 100, 2) if eligible else None,
        "latency_p50_ms": pct(latencies_ms, 0.50),
        "latency_p95_ms": pct(latencies_ms, 0.95),
        "sample_qualification_turns": len(latencies_ms),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session-limit", type=int, default=100)
    p.add_argument("--output", default=str(REPO_ROOT / "qa" / "runs" / "method_a_baseline.json"))
    args = p.parse_args()

    baseline = extract_baseline(args.session_limit)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baseline, indent=2, default=str), encoding="utf-8")
    print(f"[OK] Baseline written: {out_path}")
    print(json.dumps(baseline, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
