# API — FAQ Ingestion

Exposed by `modules/faq_automation/faq_controller.py`, mounted on the FastAPI
app in `main.py` (not the Flask chatbot).

## `POST /rag-assistant/faq-automation`

Triggers end-to-end FAQ ingestion: reads Google Sheets → chunks → writes to
Mongo → rebuilds the Chroma KB and atomically swaps `vector_data/current/`.

### Auth

Header `x-api-key: <API_KEY>` (name from `API_HEADER_NAME`, default `x-api-key`).

### Request

| Header | Value |
|---|---|
| `Content-Type` | `text/plain` (required; JSON returns 415) |
| `x-api-key` | from `API_KEY` env |

**Body:** plain text, must equal `TRIGGER_TRUE_VALUE` (default `true`).

```http
POST /rag-assistant/faq-automation HTTP/1.1
x-api-key: <your-api-key>
Content-Type: text/plain

true
```

### Response (200)

**Per-2026-05-07 schema** — N per-service docs, not single legacy doc. Top-level
`doc_id`/`chunks`/`updated_at` removed in favor of the new fields below.

```json
{
  "ok": true,
  "services_updated": 13,
  "services_deleted": [],
  "total_chunks": 499,
  "per_service": [
    {
      "service_id": "whistleblowing-system",
      "service_name": "Whistleblowing Hotline",
      "doc_id": "<uuid4>",
      "chunks_count": 38,
      "updated_at": "2026-05-07T14:30:00.000+07:00",
      "created": false
    }
  ],
  "source": "https://api.acmeservices.example.com:2303/rag-assistant/faq-automation",
  "kb_rebuilt": false,
  "kb_current": "/app/vector_data/current",
  "kb_docs": null,
  "kb_per_service": [
    {"service_id": "whistleblowing-system", "rebuilt": true, "doc_count": 38, "checksum": "sha256:..."},
    {"service_id": "market-survey", "rebuilt": false, "doc_count": 22, "checksum": "sha256:..."}
  ]
}
```

**Field notes:**
- `services_updated` — count of services upserted this run (≤ number of Sheet tabs after `INCLUDE_SHEETS` filter).
- `services_deleted` — list of `service_id`s removed because their tabs are no longer in the Sheet (audit log entry written for each: `{event:"faq_service_deleted", service_id, reason:"absent_in_sheet_at_ingest"}`).
- `total_chunks` — sum of `chunks_count` across all per-service docs upserted.
- `per_service[]` — one entry per upserted service. `created: true` means new doc inserted; `false` means existing doc updated in place.
- `kb_rebuilt` — `false` if checksum unchanged; `true` if KB actually rebuilt. Stable across the per-service refactor (see `vector_build._checksum_source` invariant).
- `source` is reconstructed from `PUBLIC_BASE_URL` + request path, or from the raw request URL when unset.
- `kb_per_service[]` — Stage 3A: per-service Chroma rebuild outcome. Empty array
  in `legacy` mode. In `split`/`dual` mode, one entry per service in the repo
  with `rebuilt: bool` showing whether the collection was actually rebuilt
  (false = checksum unchanged, skip).

### Errors

| Status | Condition |
|---|---|
| 401 | Missing or wrong `x-api-key`. |
| 415 | `Content-Type` is not `text/plain`. |
| 400 | Body does not equal `TRIGGER_TRUE_VALUE`, OR `FAQ_VERIFICATOR` env is disabled, OR slug collision detected (see below). |

#### 400 — slug collision

When two Sheet tabs produce the same `service_id` slug (e.g. `"Service"` and `"service"` both → `"service"`):

```json
{
  "ok": false,
  "reason": "service_id collisions detected",
  "collisions": {"service": ["Service", "service"]}
}
```

**No partial Mongo writes** — collision check fires before any chunking or upsert. Operator must rename one of the conflicting tabs in the Sheet UI to produce a distinct slug, then re-trigger.

### Related config

- `SHEET_ID`, `INCLUDE_SHEETS`, `OUTPUT_TITLE`, `WRAP_WIDTH` — source sheet layout.
- `MONGO_DB`, `MONGO_FAQ_UPDATE` — target Mongo storage. Compound unique index `(marker, service_id)`.
- `DB_BACKEND` — `mongo` (default) / `postgres` (reserved). Selects FAQRepo impl.
- `EMBEDDINGS_PROVIDER`, `EMBED_MODEL`, `EMBEDDING_DEVICE` — KB rebuild.
- `CHROMA_COLLECTION`, `VECTOR_DATA_DIR` — Chroma persistence.
- `FAQ_VERIFICATOR` — feature flag (`on`/`off`).

See [`../ops/env_reference.md`](../ops/env_reference.md).

---

## `POST /rag-assistant/knowledgebase-rebuild`

Rebuilds the Chroma knowledgebase from whatever is currently in Mongo (the
`MONGO_FAQ_UPDATE` collection). **Always forced** — bypasses the checksum gate
used by `/faq-automation`. Does **not** re-fetch from Google Sheets and does
**not** touch Mongo. Use when you want to rebuild the vector index without
re-running the full ingestion (e.g. after changing the embedding model, or
when you suspect the `vector_data/current/` directory is stale but the
checksum hasn't moved).

### Auth

Header `x-api-key: <API_KEY>` (name from `API_HEADER_NAME`, default `x-api-key`).

### Request

| Header | Value |
|---|---|
| `Content-Type` | `text/plain` (required; JSON returns 415) |
| `x-api-key` | from `API_KEY` env |

**Body:** plain text, must equal `TRIGGER_TRUE_VALUE` (default `true`).

```http
POST /rag-assistant/knowledgebase-rebuild HTTP/1.1
x-api-key: <your-api-key>
Content-Type: text/plain

true
```

### Response (200)

```json
{
  "ok": true,
  "rebuilt": true,
  "docs": 499,
  "current": "/app/vector_data/current",
  "meta_id": "…mongo object id…"
}
```

### Errors

| Status | Condition |
|---|---|
| 401 | Missing or wrong `x-api-key`. |
| 415 | `Content-Type` is not `text/plain`. |
| 400 | Body does not equal `TRIGGER_TRUE_VALUE`. |

### Notes

- After a successful rebuild, the running chatbot process (Flask) still holds
  the OLD Chroma index in memory. Restart the chatbot to reload
  `vector_data/current/`.
- This endpoint is implemented inline in `app.py` (not in the FAQ router) —
  consistent with the `/rag-assistant/sales-slots-update` pattern.
- Reuses `modules/vector_build/vb_service.build_and_swap(force=True)`.

---

## `POST /rag-assistant/knowledgebase-rebuild/<service_id>`

**Stage 3A (2026-05-07).** Force rebuild ONE service's Chroma collection. Useful
for hot-fix without rebuilding the whole KB. Requires `KB_BACKEND` in `{split, dual}`.

### Auth / Request

Same as `/rag-assistant/knowledgebase-rebuild`: `x-api-key` header, `Content-Type: text/plain`,
body equal to `TRIGGER_TRUE_VALUE`.

### Response (200)

```json
{
  "ok": true,
  "service_id": "whistleblowing-system",
  "rebuilt": true,
  "doc_count": 38,
  "checksum": "sha256:..."
}
```

### Errors

| Status | Condition |
|---|---|
| 400 | `KB_BACKEND` is `legacy` (per-service rebuild not applicable) |
| 401 | Missing/wrong `x-api-key` |
| 404 | `service_id` not present in FAQ repo (`FAQRepo.list_services()`) |
| 415 | `Content-Type` not `text/plain` |
