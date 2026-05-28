"""Delete all QA-prefixed sessions (sessionId starts with 'qa-').

Use when QA chat_history docs accumulate and you want to keep Mongo tidy.
DOES NOT touch production sessions (real sessionIds don't start with 'qa-').

Usage:
    python qa/scripts/cleanup_qa_sessions.py --dry-run     # show what would be deleted
    python qa/scripts/cleanup_qa_sessions.py --confirm     # actually delete
"""
from __future__ import annotations
import argparse
import os
import sys
from pymongo import MongoClient


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--confirm", action="store_true")
    args = p.parse_args()

    uri = os.getenv("MONGO_URI")
    if not uri:
        print("MONGO_URI env required", file=sys.stderr)
        return 2

    db = MongoClient(uri)[os.getenv("MONGO_DB", "faq_automation")]
    ch_coll = db[os.getenv("CHAT_HISTORY_COLL", "chat_history")]
    qr_coll = db[os.getenv("QUERY_RECORDING_COLL", "query_recording")]

    ch_filter = {"sessionId": {"$regex": "^qa-"}}
    qr_filter = {"sessionId": {"$regex": "^qa-"}}

    ch_n = ch_coll.count_documents(ch_filter)
    qr_n = qr_coll.count_documents(qr_filter)
    print(f"chat_history QA docs: {ch_n}")
    print(f"query_recording QA docs: {qr_n}")

    if args.dry_run:
        print("(dry-run — nothing deleted)")
        return 0

    ch_res = ch_coll.delete_many(ch_filter)
    qr_res = qr_coll.delete_many(qr_filter)
    print(f"deleted: chat_history={ch_res.deleted_count} query_recording={qr_res.deleted_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
