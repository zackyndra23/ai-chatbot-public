"""FAQ repository abstract interface — Postgres-ready.

Concrete implementation: `modules/faq_automation/faq_mongo_repo.py:FAQMongoRepo`.
Future Postgres impl will subclass FAQRepo similarly. Factory in
`infra/app_repo.py:build_faq_repo` selects backend by `cfg.DB_BACKEND`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class FAQRepo(ABC):
    """Abstract repository for FAQ per-service documents."""

    @abstractmethod
    def upsert_service(
        self,
        *,
        service_id: str,
        service_name: str,
        text: str,
        chunks: list[dict],
        source_sheet_id: str,
    ) -> dict:
        """Upsert one service doc.

        Returns: {service_id, service_name, doc_id, chunks_count, updated_at, created}.
        `created` is True if a new doc was inserted, False if an existing doc was updated.
        Implementation MUST preserve `service_aliases` and `created_at` across upserts
        (use $setOnInsert in Mongo).
        """
        ...

    @abstractmethod
    def list_services(self) -> list[dict]:
        """Return all service docs (full payload). Order: by service_id ascending."""
        ...

    @abstractmethod
    def get_service(self, service_id: str) -> dict | None:
        """Return single service doc or None."""
        ...

    @abstractmethod
    def delete_service(self, service_id: str) -> bool:
        """Delete one service doc by service_id. Returns True if deleted, False if absent."""
        ...

    @abstractmethod
    def delete_services_not_in(self, keep_ids: list[str]) -> list[str]:
        """Reconcile: delete all services whose service_id is NOT in keep_ids.

        Returns: list of deleted service_ids (for audit logging). Empty list if no-op.
        """
        ...
