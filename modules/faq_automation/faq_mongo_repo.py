"""FAQ repository — Mongo implementation.

Stores N per-service documents (one per Sheet tab) in cfg.MONGO_FAQ_UPDATE.
Upsert key is the compound (marker, service_id). `service_aliases` and
`created_at` are preserved across upserts via `$setOnInsert`.

See modules/faq_automation/faq_repo.py for the abstract interface.
"""
from __future__ import annotations
from typing import Callable, Dict, List, Optional
from uuid import uuid4
from datetime import datetime
import pytz
from pymongo import MongoClient, ASCENDING

from .faq_repo import FAQRepo


class FAQMongoRepo(FAQRepo):
    """
    Per-service document storage. Each Sheet tab → one Mongo doc with
    fields: marker, service_id, service_name, service_aliases, text,
    chunks, chunks_count, doc_id, created_at, updated_at, source_sheet_id.
    """

    def __init__(
        self,
        uri: str,
        dbname: str,
        coll_name: str,
        timezone: str = "Asia/Jakarta",
        *,
        client_factory: Optional[Callable[[str], object]] = None,
    ):
        if client_factory is not None:
            client = client_factory(uri)
        else:
            client = MongoClient(uri)
        self.col = client[dbname][coll_name]
        self.tz = pytz.timezone(timezone)
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Create the new compound unique index; drop the legacy single-unique
        on `marker` if it exists. Idempotent + best-effort."""
        try:
            self.col.drop_index("marker_1")
        except Exception:
            pass
        try:
            self.col.create_index(
                [("marker", ASCENDING), ("service_id", ASCENDING)],
                unique=True,
                name="idx_marker_service",
            )
        except Exception:
            pass
        try:
            self.col.create_index(
                [("service_id", ASCENDING)],
                name="idx_service",
            )
        except Exception:
            pass

    def _now_iso_wib(self) -> str:
        return datetime.now(self.tz).isoformat()

    # ----------------------- FAQRepo implementation -----------------------

    def upsert_service(
        self,
        *,
        service_id: str,
        service_name: str,
        text: str,
        chunks: List[Dict],
        source_sheet_id: str,
    ) -> Dict:
        now = self._now_iso_wib()
        doc_id = str(uuid4())
        existing = self.col.find_one(
            {"marker": "latest", "service_id": service_id},
            {"_id": 1},
        )
        created = existing is None
        self.col.update_one(
            {"marker": "latest", "service_id": service_id},
            {
                "$set": {
                    "service_name": service_name,
                    "text": text,
                    "chunks": chunks,
                    "chunks_count": len(chunks),
                    "doc_id": doc_id,
                    "updated_at": now,
                    "source_sheet_id": source_sheet_id,
                },
                "$setOnInsert": {
                    "service_aliases": [],
                    "created_at": now,
                },
            },
            upsert=True,
        )
        return {
            "service_id": service_id,
            "service_name": service_name,
            "doc_id": doc_id,
            "chunks_count": len(chunks),
            "updated_at": now,
            "created": created,
        }

    def list_services(self) -> List[Dict]:
        return list(self.col.find({"marker": "latest"}).sort("service_id", ASCENDING))

    def get_service(self, service_id: str) -> Optional[Dict]:
        return self.col.find_one({"marker": "latest", "service_id": service_id})

    def delete_service(self, service_id: str) -> bool:
        res = self.col.delete_one({"marker": "latest", "service_id": service_id})
        return getattr(res, "deleted_count", 0) > 0

    def delete_services_not_in(self, keep_ids: List[str]) -> List[str]:
        # Snapshot which ids would be deleted before deletion (for audit return).
        existing = list(self.col.find(
            {"marker": "latest"},
            {"service_id": 1, "_id": 0},
        ))
        to_delete = [d["service_id"] for d in existing if d.get("service_id") not in set(keep_ids)]
        if not to_delete:
            return []
        self.col.delete_many({
            "marker": "latest",
            "service_id": {"$nin": list(keep_ids)},
        })
        return to_delete

    # ----------------------- Backward-compat shim -----------------------

    def save_latest(self, full_text: str, chunks: List[Dict]) -> Dict:
        """[DEPRECATED] Legacy single-doc API. Out-of-tree callers may still hit this.

        Kept as best-effort shim: groups chunks by `service` field and upserts
        per-service. Emits DeprecationWarning. New code should call
        upsert_service() directly per service.
        """
        import warnings
        warnings.warn(
            "FAQMongoRepo.save_latest is deprecated; use upsert_service per service.",
            DeprecationWarning,
            stacklevel=2,
        )
        from collections import defaultdict
        from .faq_pipelines import make_service_id
        by_service: Dict[str, List[Dict]] = defaultdict(list)
        for ch in chunks:
            svc = (ch.get("service") or "General").strip()
            by_service[svc].append(ch)

        results = []
        for svc_name, svc_chunks in by_service.items():
            svc_id = make_service_id(svc_name)
            svc_text = "\n\n".join(ch.get("text", "") for ch in svc_chunks)
            res = self.upsert_service(
                service_id=svc_id,
                service_name=svc_name,
                text=svc_text,
                chunks=svc_chunks,
                source_sheet_id="",
            )
            results.append(res)
        return {
            "doc_id": results[0]["doc_id"] if results else "",
            "chunks": sum(r["chunks_count"] for r in results),
            "updated_at": results[0]["updated_at"] if results else "",
        }
