"""Targeted 3-case QA driver for anti-redundancy methods.

Cases (all FAQ-RAG-routed):
  T1 multi-turn anti-repetition (3 turns same topic)
  T2 within-turn diversity (1 catalog query)
  T3 recap bypass (2 turns: pre + recap)

Usage:
    python qa/scripts/run_targeted_tests.py --method normal --run-dir qa/runs/X
"""
from __future__ import annotations
import argparse, json, os, sys, time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")
if not os.getenv("WEBSITE_ID") and os.getenv("TESTING_WEBSITEID"):
    os.environ["WEBSITE_ID"] = os.environ["TESTING_WEBSITEID"]

from qa.scripts.lib import http_client, mongo_helpers

# FAQ-RAG-routed queries verified during Step 0 dry-run:
T1_TURNS = [
    "apa saja layanan yang ditawarkan RAG Assistant?",
    "tolong sebutkan jenis layanan dari RAG Assistant",
    "apa portfolio layanan yang dimiliki RAG Assistant?",
]
T2_QUERY = "apa saja layanan yang ditawarkan RAG Assistant?"
T3_PRE = "apa saja layanan yang ditawarkan RAG Assistant?"
T3_RECAP = "tolong ulangi penjelasan tadi"


def _extract_chunk_ids_from_audit_or_chat(session_id: str) -> list[str]:
    """Snapshot recent_chunk_ids from chat_history doc."""
    doc = mongo_helpers.read_chat_history_doc(session_id) or {}
    return list(doc.get("recent_chunk_ids") or [])


def _parse_context_qstems(prompt_text: str) -> list[str]:
    stems = []
    in_ctx = False
    for line in (prompt_text or "").splitlines():
        if line.startswith("Context:"):
            in_ctx = True
            continue
        if in_ctx and line.startswith("Q:"):
            stems.append(line[2:].strip()[:80].lower())
    return stems


def _parse_context_services(prompt_text: str) -> list[str]:
    return [l[2:].strip().lower() for l in (prompt_text or "").splitlines() if l.startswith("S:")]


def _audit_latest_for(session_id: str) -> dict:
    return mongo_helpers.read_latest_audit_for_session(session_id) or {}


def _session(prefix: str) -> str:
    return f"qa-tgt-{prefix}-{int(time.time()*1000)}"


def run_t1(base_url, method) -> dict:
    """T1: multi-turn anti-repetition."""
    sid = _session("T1")
    per_turn = []
    for i, q in enumerate(T1_TURNS, 1):
        t0 = time.perf_counter()
        resp = http_client.send_turn(base_url=base_url, session_id=sid, question=q, timeout_s=60)
        wall_ms = int((time.perf_counter() - t0) * 1000)
        audit = _audit_latest_for(sid)
        chunk_ids_in_prompt = []
        prompt_text = str(audit.get("llm_prompt", ""))
        # Extract chunk_ids that ARE in this turn's Context — we can find them
        # via metadata only by querying chat_history doc (which has recent_chunk_ids
        # — but that's the ACCUMULATED list across turns).
        rc_after = _extract_chunk_ids_from_audit_or_chat(sid)
        rm = (audit.get("extras") or {}).get("retrieval_method")
        per_turn.append({
            "turn": i,
            "question": q,
            "route": resp.get("route"),
            "stage": audit.get("stage"),
            "retrieval_method": rm,
            "recent_chunk_ids_after_turn": rc_after.copy(),
            "rc_count": len(rc_after),
            "context_qstems": _parse_context_qstems(prompt_text),
            "context_services": _parse_context_services(prompt_text),
            "wallclock_ms": resp.get("__wallclock_ms"),
        })
    # Compute T1 metric: chunk overlap turn1-vs-turn3
    rc_turn1 = set(per_turn[0]["recent_chunk_ids_after_turn"])
    rc_turn3 = set(per_turn[2]["recent_chunk_ids_after_turn"])
    # Need to figure out per-turn deltas
    rc_turn2_minus_turn1 = set(per_turn[1]["recent_chunk_ids_after_turn"]) - rc_turn1
    rc_turn3_minus_turn2 = rc_turn3 - set(per_turn[1]["recent_chunk_ids_after_turn"])
    return {
        "case": "T1",
        "method": method,
        "session_id": sid,
        "per_turn": per_turn,
        "rc_count_final": len(rc_turn3),
        "rc_growth_turn1_to_3": len(rc_turn3) - len(rc_turn1),
        "rc_new_in_turn2": len(rc_turn2_minus_turn1),
        "rc_new_in_turn3": len(rc_turn3_minus_turn2),
    }


def run_t2(base_url, method) -> dict:
    """T2: within-turn diversity."""
    sid = _session("T2")
    t0 = time.perf_counter()
    resp = http_client.send_turn(base_url=base_url, session_id=sid, question=T2_QUERY, timeout_s=60)
    wall_ms = int((time.perf_counter() - t0) * 1000)
    audit = _audit_latest_for(sid)
    prompt_text = str(audit.get("llm_prompt", ""))
    qstems = _parse_context_qstems(prompt_text)
    services = _parse_context_services(prompt_text)
    rm = (audit.get("extras") or {}).get("retrieval_method")
    return {
        "case": "T2",
        "method": method,
        "session_id": sid,
        "question": T2_QUERY,
        "route": resp.get("route"),
        "stage": audit.get("stage"),
        "retrieval_method": rm,
        "distinct_qstems": len(set(qstems)),
        "distinct_services": len(set(services)),
        "qstems_sample": qstems[:4],
        "services_sample": list(set(services))[:4],
        "wallclock_ms": resp.get("__wallclock_ms"),
    }


def run_t3(base_url, method) -> dict:
    """T3: recap bypass."""
    sid = _session("T3")
    # T3.T1 pre-turn
    resp1 = http_client.send_turn(base_url=base_url, session_id=sid, question=T3_PRE, timeout_s=60)
    rc_after_t1 = _extract_chunk_ids_from_audit_or_chat(sid)
    a1 = _audit_latest_for(sid)
    rm1 = (a1.get("extras") or {}).get("retrieval_method")
    # T3.T2 recap turn
    resp2 = http_client.send_turn(base_url=base_url, session_id=sid, question=T3_RECAP, timeout_s=60)
    rc_after_t2 = _extract_chunk_ids_from_audit_or_chat(sid)
    a2 = _audit_latest_for(sid)
    rm2 = (a2.get("extras") or {}).get("retrieval_method")
    rc_grew = len(rc_after_t2) > len(rc_after_t1)
    reply_text = resp2.get("message", {})
    if isinstance(reply_text, dict):
        reply_text = (reply_text.get("content") or {}).get("text", "")
    return {
        "case": "T3",
        "method": method,
        "session_id": sid,
        "pre_turn_rc_count": len(rc_after_t1),
        "recap_turn_rc_count": len(rc_after_t2),
        "rc_grew_on_recap": rc_grew,
        "rm_pre": rm1,
        "rm_recap": rm2,
        "recap_reply_first200": reply_text[:200] if isinstance(reply_text, str) else str(reply_text)[:200],
        "wallclock_ms_recap": resp2.get("__wallclock_ms"),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--method", required=True, choices=["normal", "mmr", "fuzzy", "embedding"])
    p.add_argument("--target", default="http://localhost:2305")
    p.add_argument("--run-dir", required=True)
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{args.method}] Running T1...")
    t1 = run_t1(args.target, args.method)
    print(f"  T1 rc_count_final={t1['rc_count_final']}, growth={t1['rc_growth_turn1_to_3']}")
    print(f"[{args.method}] Running T2...")
    t2 = run_t2(args.target, args.method)
    print(f"  T2 distinct_qstems={t2['distinct_qstems']}, services={t2['distinct_services']}, route={t2['route']}, rm={t2['retrieval_method']!r}")
    print(f"[{args.method}] Running T3...")
    t3 = run_t3(args.target, args.method)
    print(f"  T3 pre={t3['pre_turn_rc_count']} recap={t3['recap_turn_rc_count']} grew={t3['rc_grew_on_recap']}")

    out_path = run_dir / f"targeted_{args.method}.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for row in (t1, t2, t3):
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    print(f"[{args.method}] Written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
