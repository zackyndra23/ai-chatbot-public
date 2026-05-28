"""One-time migration: legacy single-doc → N per-service docs.

Idempotent. Safe to run multiple times. Run:

    python -m modules.faq_automation.migrate_split_latest [--dry-run]

Logic:
  1. Find legacy doc: marker:"latest" AND service_id missing.
  2. If absent → no-op.
  3. Group chunks by chunk["service"] → list of (service_name, chunks).
  4. Generate service_id slugs; check for collisions (raises if any).
  5. If --dry-run: print plan, exit.
  6. Otherwise: drop legacy unique index `marker_1`, create new compound
     index, upsert per-service via FAQMongoRepo.upsert_service, delete
     legacy doc.

Use-case: post-deploy, before first /faq-automation trigger that uses
the new code path. Old single-doc must be split or the unique-index
conflict on (marker, service_id) blocks new writes.
"""
from __future__ import annotations
import argparse
import sys
from collections import defaultdict
from datetime import datetime
import pytz

from core.app_config import Config
from .faq_pipelines import make_service_id, _check_collisions


def _migrate_with_collection(coll, *, dry_run: bool, sheet_id: str) -> dict:
    """Core migration logic operating on a passed-in pymongo Collection.

    Separated from the CLI entry point for testability.
    """
    # 1) Find legacy single doc (marker:"latest" AND no service_id field).
    # Scan all marker:"latest" docs and pick the one(s) missing service_id —
    # works for both real pymongo (where $exists query would also work) AND
    # the in-memory test fake (which doesn't understand $exists). This also
    # correctly handles the partial-state edge case (1 legacy + N per-service
    # docs sitting side-by-side after a half-failed prior run): we'd still
    # find the legacy and complete the migration.
    legacy = None
    for d in coll.find({"marker": "latest"}):
        if "service_id" not in d:
            legacy = d
            break
    if not legacy:
        return {"status": "noop", "reason": "no legacy single-doc found", "dry_run": dry_run}

    legacy_chunks = legacy.get("chunks") or []
    if not legacy_chunks:
        return {"status": "abort", "reason": "legacy doc has no chunks", "dry_run": dry_run}

    # 2) Group chunks by service
    by_service: dict[str, list[dict]] = defaultdict(list)
    for ch in legacy_chunks:
        svc = (ch.get("service") or "General").strip()
        by_service[svc].append(ch)

    # 3) Build (service_id, service_name) and check collisions
    pairs = [(make_service_id(name), name) for name in by_service.keys()]
    _check_collisions(pairs)

    plan = []
    for svc_name, chunks in by_service.items():
        svc_id = make_service_id(svc_name)
        plan.append({"service_id": svc_id, "service_name": svc_name, "chunks_count": len(chunks)})

    if dry_run:
        return {
            "status": "dry_run",
            "would_split_into": plan,
            "would_delete": str(legacy.get("_id")),
        }

    # 4) Index migration (idempotent)
    try:
        coll.drop_index("marker_1")
    except Exception:
        pass
    try:
        coll.create_index([("marker", 1), ("service_id", 1)], unique=True, name="idx_marker_service")
    except Exception:
        pass
    try:
        coll.create_index([("service_id", 1)], name="idx_service")
    except Exception:
        pass

    # 5) Upsert per-service docs (mimic FAQMongoRepo.upsert_service shape)
    tz = pytz.timezone("Asia/Jakarta")
    now = datetime.now(tz).isoformat()
    written = []
    from uuid import uuid4

    for svc_name, chunks in by_service.items():
        svc_id = make_service_id(svc_name)
        svc_text = "\n\n".join(ch.get("text", "") for ch in chunks)
        doc_id = str(uuid4())
        coll.update_one(
            {"marker": "latest", "service_id": svc_id},
            {
                "$set": {
                    "service_name": svc_name,
                    "text": svc_text,
                    "chunks": chunks,
                    "chunks_count": len(chunks),
                    "doc_id": doc_id,
                    "updated_at": now,
                    "source_sheet_id": sheet_id,
                },
                "$setOnInsert": {
                    "service_aliases": [],
                    "created_at": now,
                },
            },
            upsert=True,
        )
        written.append({
            "service_id": svc_id,
            "service_name": svc_name,
            "chunks_count": len(chunks),
        })

    # 6) Delete legacy doc
    coll.delete_one({"_id": legacy["_id"]})

    return {
        "status": "migrated",
        "services_written": len(written),
        "deleted_legacy_id": str(legacy["_id"]),
        "details": written,
    }


def migrate(dry_run: bool = False) -> dict:
    """CLI entry point. Loads cfg + opens Mongo + delegates to core logic."""
    from pymongo import MongoClient
    cfg = Config()
    client = MongoClient(cfg.MONGO_URI)
    coll = client[cfg.MONGO_DB][cfg.MONGO_FAQ_UPDATE]
    return _migrate_with_collection(coll, dry_run=dry_run, sheet_id=cfg.SHEET_ID)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy single-doc FAQ to per-service docs")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, no writes")
    args = parser.parse_args()
    res = migrate(dry_run=args.dry_run)
    import json
    print(json.dumps(res, indent=2, default=str))
    if res.get("status") in ("abort",):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
