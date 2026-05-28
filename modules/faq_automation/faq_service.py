"""FAQ orchestration service.

Per-2026-05-07 refactor: now writes N per-service docs (one per Sheet tab)
instead of one giant 'latest' doc. Reconciles deleted tabs (services no
longer in the Sheet are dropped from Mongo). Slug collisions raise
ValueError before any Mongo writes.
"""
from __future__ import annotations
import logging
from types import SimpleNamespace

from . import faq_pipelines as pipes
from modules.vector_build.vb_service import build_and_swap
from .faq_pipelines import (
    build_service_bundles,
    build_text,                       # legacy, kept for backward compat
    chunk,                            # legacy, kept for backward compat
    save_latest,                      # legacy, kept for backward compat
    _normalize_chunks_ensure_sqa,
)

logger = logging.getLogger(__name__)


class FAQService:
    def __init__(self, cfg, repo, pipelines=None):
        self.cfg = cfg
        self.repo = repo  # FAQRepo (FAQMongoRepo or future FAQPostgresRepo)
        # `pipelines` is kept for backward compatibility with existing
        # `build_services` wiring; not used by run_pipeline anymore.
        self.pipes = pipelines or SimpleNamespace(
            build_text=build_text,
            chunk=chunk,
            save_latest=save_latest,
            _normalize_chunks_ensure_sqa=_normalize_chunks_ensure_sqa,
        )

    def run_pipeline(self, source: str) -> dict:
        """Read Sheet → split per-service → reconcile → upsert per service → trigger KB rebuild.

        Returns: {ok, services_updated, services_deleted, total_chunks,
                  per_service, source, kb_rebuilt, kb_current, kb_docs}.

        Raises ValueError on slug collisions (caller should map to HTTP 400).
        """
        # 1) Read Sheet → per-service bundles (collision-checked)
        bundles = build_service_bundles(self.cfg)

        # 2) Reconcile: drop services no longer in the Sheet
        keep_ids = [b.service_id for b in bundles]
        deleted_ids = self.repo.delete_services_not_in(keep_ids)
        for sid in deleted_ids:
            try:
                logger.info({
                    "event": "faq_service_deleted",
                    "service_id": sid,
                    "reason": "absent_in_sheet_at_ingest",
                })
            except Exception:
                pass

        # 3) Upsert all current services
        upsert_results: list[dict] = []
        for b in bundles:
            res = self.repo.upsert_service(
                service_id=b.service_id,
                service_name=b.service_name,
                text=b.text,
                chunks=b.chunks,
                source_sheet_id=getattr(self.cfg, "SHEET_ID", ""),
            )
            upsert_results.append(res)

        # 4) Trigger KB rebuild (checksum-gated)
        kb = build_and_swap(force=False)

        # Stage 3A: surface per-service KB rebuild outcome (split / dual mode).
        # In legacy mode, the result dict has no "per_service" key — defaults to [].
        kb_per_service = kb.get("per_service", []) if isinstance(kb, dict) else []

        return {
            "ok": True,
            "services_updated": len(upsert_results),
            "services_deleted": deleted_ids,
            "total_chunks": sum(r["chunks_count"] for r in upsert_results),
            "per_service": upsert_results,
            "source": source,
            "kb_rebuilt": kb.get("rebuilt"),
            "kb_current": kb.get("current"),
            "kb_docs": kb.get("docs"),
            "kb_per_service": kb_per_service,
        }

    async def debug_sheets(self):
        return {
            "ok": True,
            "spreadsheet_id": self.cfg.SHEET_ID,
            "creds_path": self.cfg.CREDS_PATH,
            "include_sheets": list(self.cfg.INCLUDE_SHEETS) if self.cfg.INCLUDE_SHEETS else None,
            "output_title": self.cfg.OUTPUT_TITLE,
        }
