# Module — `faq_automation`

FAQ ingestion pipeline: Google Sheet → per-tab chunks → N per-service Mongo
docs → trigger KB rebuild.

## Purpose

Keep the FAQ knowledge base in sync with a source Google Sheet. Triggered by
`POST /aitegrity-core/faq-automation` (see [`../api/faq.md`](../api/faq.md)),
this module reads the sheet, splits per-tab into `ServiceBundle`s, reconciles
deleted tabs, upserts N per-service docs into Mongo `MONGO_FAQ_UPDATE`, then
asks `vector_build.build_and_swap` to rebuild the Chroma index.

**Schema change (2026-05-07):** Mongo collection now holds N per-service docs
(one per Sheet tab) keyed by compound unique `(marker, service_id)`, instead
of a single legacy doc keyed by `marker` alone. See
[`../superpowers/specs/2026-05-07-faq-per-service-docs-design.md`](../superpowers/specs/2026-05-07-faq-per-service-docs-design.md)
for design rationale.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `router` | `faq_controller.py` | FastAPI `APIRouter` — exposes `POST /aitegrity-core/faq-automation`. |
| `FAQService(cfg, repo, pipelines)` | `faq_service.py` | Orchestration. Key method: `run_pipeline(source)` (per-service flow). Also `debug_sheets()`. |
| `build_service_bundles(cfg)` | `faq_pipelines.py` | Read Sheet → list of `ServiceBundle` (one per tab). Detects slug collisions before any downstream work. |
| `make_service_id(name)` | `faq_pipelines.py` | URL-safe slug from raw tab title. ASCII-fold + lowercase + non-alnum→"-". Raises `ValueError` if empty. |
| `_check_collisions(pairs)` | `faq_pipelines.py` | Raises `ValueError` if two tabs produce the same `service_id`. |
| `_to_txt_single_service(name, qa_pairs, wrap_width)` | `faq_pipelines.py` | Build the S/Q/A blob for ONE Sheet tab. |
| `ServiceBundle` | `faq_pipelines.py` | `@dataclass`: `service_id`, `service_name`, `text`, `chunks`. Output of `build_service_bundles`. |
| `FAQRepo` (ABC) | `faq_repo.py` | Abstract repo interface — 5 methods: `upsert_service`, `list_services`, `get_service`, `delete_service`, `delete_services_not_in`. |
| `FAQMongoRepo(FAQRepo)` | `faq_mongo_repo.py` | Mongo implementation. Compound unique index `(marker, service_id)`; preserves `service_aliases` + `created_at` via `$setOnInsert`. `client_factory` kwarg for test injection. |
| `migrate_split_latest.migrate(dry_run)` | `migrate_split_latest.py` | One-time idempotent migration: legacy single-doc → N per-service docs. CLI: `python -m modules.faq_automation.migrate_split_latest [--dry-run]`. |

Legacy `build_text(cfg)`, `chunk(text)`, `save_latest(...)` are kept for
backward compatibility but no longer used by `run_pipeline`. `FAQMongoRepo.save_latest`
is a deprecation shim that delegates to `upsert_service` per service and
emits `DeprecationWarning`.

## Per-service Mongo doc shape

```jsonc
{
  "marker": "latest",                                       // upsert key (compound with service_id)
  "service_id": "whistleblowing-system",                    // slug; stable across runs
  "service_name": "Whistleblowing System",                  // raw tab title from Sheet (immutable: don't mutate)
  "service_aliases": [],                                     // list[str]; empty on insert; preserved across upserts
  "text": "S: Whistleblowing System\nQ: ...\nA: ...",        // S/Q/A blob, this service only
  "chunks": [
    {"chunk_index": 0, "service": "Whistleblowing System", "text": "S: ...\nQ: ...\nA: ..."}
  ],
  "chunks_count": 38,
  "doc_id": "<uuid4>",                                       // refreshed each upsert
  "created_at": "2026-05-07T10:30:00.000+07:00",            // ISO-8601 WIB; insert-only
  "updated_at": "2026-05-07T10:30:00.000+07:00",            // ISO-8601 WIB; refreshed each upsert
  "source_sheet_id": "<cfg.SHEET_ID>"
}
```

**Indexes:**
- `idx_marker_service` — compound unique `(marker, service_id)`. Primary upsert key.
- `idx_service` — single index on `service_id`. Faster get/delete by id.
- Legacy `marker_1` (single-unique on `marker`) is dropped on first `FAQMongoRepo` init (idempotent — try/except wrap).

## Data flow

```
POST /aitegrity-core/faq-automation (text/plain "true")
        │
        ▼
FAQService.run_pipeline(source=...)
  ├─ build_service_bundles(cfg)
  │  ├─ _read_sheet → N tabs
  │  ├─ make_service_id per tab
  │  ├─ _check_collisions (raises ValueError on dup → controller maps to HTTP 400)
  │  └─ per tab: _to_txt_single_service → _chunk_text_qa → _normalize_chunks_ensure_sqa
  │     → ServiceBundle(service_id, service_name, text, chunks)
  ├─ repo.delete_services_not_in([keep_ids])  → reconciliation
  │     (audit log: {event: "faq_service_deleted", service_id, reason})
  ├─ for each bundle: repo.upsert_service(...)  → N Mongo docs ($set + $setOnInsert)
  └─ build_and_swap(force=False)               → vector_build: rebuild Chroma if checksum changed
        │
        ▼
200 { ok: true, services_updated: N, services_deleted: [...],
      total_chunks, per_service: [{service_id, service_name, doc_id, chunks_count, updated_at, created}],
      source, kb_rebuilt, kb_current, kb_docs,
      kb_per_service: [{service_id, rebuilt, doc_count, checksum}, ...]   // Stage 3A — empty in legacy mode
```

## Env vars

| Key | Why |
|---|---|
| `SHEET_ID`, `INCLUDE_SHEETS`, `OUTPUT_TITLE`, `WRAP_WIDTH` | Source sheet identity + layout. |
| `GOOGLE_SERVICE_ACCOUNT` / `CREDS_PATH` | Google API auth. |
| `MONGO_URI`, `MONGO_DB`, `MONGO_FAQ_UPDATE` | Mongo storage. |
| `DB_BACKEND` | `mongo` (default) / `postgres` (reserved — raises `NotImplementedError`). Selects FAQRepo impl in `infra/app_repo.build_faq_repo`. |
| `API_KEY`, `API_HEADER_NAME` | Endpoint auth. |
| `TRIGGER_TRUE_VALUE` | Required body value (default `true`). |
| `FAQ_VERIFICATOR` | Feature flag to enable/disable the endpoint. |
| `PUBLIC_BASE_URL` | Optional base for `source` URL reconstruction. |

## Dependencies

- Internal: `modules/vector_build` (for KB rebuild), `infra/app_repo` (factory).
- External: `gspread`, `google-auth`, `pymongo`, `pytz`, FastAPI.

## File map

| File | Purpose |
|---|---|
| `faq_controller.py` | FastAPI endpoint (auth, content-type gate, trigger-value check, call service). |
| `faq_service.py` | `FAQService` class — orchestrates per-service pipeline + KB rebuild. |
| `faq_pipelines.py` | `make_service_id`, `_check_collisions`, `_to_txt_single_service`, `build_service_bundles`, `ServiceBundle`, plus legacy `build_text`/`chunk`/`save_latest`/`_normalize_chunks_ensure_sqa`/`_chunk_text_qa`. |
| `faq_repo.py` | `FAQRepo` abstract base class (Postgres-ready). |
| `faq_mongo_repo.py` | `FAQMongoRepo(FAQRepo)` — Mongo implementation with compound index migration. |
| `migrate_split_latest.py` | One-time migration CLI: legacy single-doc → N per-service docs. |
| `__init__.py` | Empty package init. |

## Gotchas

- **Endpoint requires `Content-Type: text/plain`, not JSON.** Easy to miss.
- **`FAQ_VERIFICATOR`** can silently disable ingestion — check logs for `FAQ_VERIFICATOR is disabled` if requests are returning 400.
- **Slug collision** (HTTP 400): two tabs that produce the same `service_id` (e.g. `"Service"` and `"service"`) raise `ValueError` → controller maps to HTTP 400. Operator must rename one tab in the Sheet UI. **No partial Mongo writes.** See [`../ops/troubleshooting.md`](../ops/troubleshooting.md).
- **Tab deletion**: dropping a tab from the Sheet causes the corresponding service doc to be **deleted from Mongo** on the next ingest. Logged as `{"event":"faq_service_deleted","service_id":"..."}`. Recovery = re-add the tab + re-trigger.
- **`service_aliases`**: empty list on first insert, **preserved across upserts** via `$setOnInsert`. Manual edits via Mongo CLI persist. No UI for editing yet.
- The KB rebuild is checksum-gated; if Sheet content didn't change, `kb_rebuilt: false` and Chroma isn't touched. Stable across the per-service refactor (see `vector_build._checksum_source` invariant).
- **Stage 3A response field `kb_per_service[]`**: per-service Chroma rebuild outcome. Empty `[]` in `KB_BACKEND=legacy` mode. In `split`/`dual` mode, one entry per service in the repo with `rebuilt: bool`, `doc_count: int`, `checksum: str`. Source: `vb_service.build_and_swap` returns `per_service` array → `run_pipeline` surfaces it as `kb_per_service`. See [`../modules/vector_build.md`](vector_build.md) "Per-service build" section.
- **Migration script must be run ONCE** after deploying this code if the database still has the legacy single doc:
  ```bash
  python -m modules.faq_automation.migrate_split_latest --dry-run   # plan
  python -m modules.faq_automation.migrate_split_latest             # apply
  ```
  Idempotent — safe to run multiple times. Detects the legacy doc by absence of the `service_id` field. After migration, the legacy doc is deleted.
- **Slug stability after Sheet rename**: renaming a tab in the Sheet (e.g. `"Whistleblowing System"` → `"WBS"`) changes the slug → old doc appears in `services_deleted`, new doc gets created. **Manual edits to `service_aliases` on the old doc are lost.** Operator can use `service_aliases` for rename equivalence (intended use) or accept the trade-off.
- If `build_and_swap` returns while Chroma files are still locked (Windows), it falls back to copytree — slower but works. See [`../ops/troubleshooting.md`](../ops/troubleshooting.md).

## Extension notes

- **Add a second source (e.g. another sheet, a PDF):** extend `build_service_bundles` to merge multiple sources, preserving `source_sheet_id` per bundle. The repo schema is multi-sheet ready via the `source_sheet_id` field.
- **Per-topic filtering:** chunks already carry `service` field via `_normalize_chunks_ensure_sqa`. Chroma indexes on `metadata.service` — filter at retrieval time via `sd_vector_repo.retrieve_service_biased`.
- **Postgres backend:** subclass `FAQRepo` with `FAQPostgresRepo`, register in `infra/app_repo.build_faq_repo` for `DB_BACKEND=postgres`. The interface is intentionally minimal (5 methods) to keep the swap one-pluggable.
- **Soft-delete instead of hard-delete:** add `deleted_at` field to schema, change `delete_services_not_in` to set the field instead of removing docs. Caller (`run_pipeline`) doesn't need to change. Audit history preserved at the cost of query-side filtering.
