# Module — `vector_build`

Build and atomically swap the Chroma knowledge base from Mongo FAQ chunks.

## Purpose

Turn current Mongo FAQ chunks into a persistent Chroma store at
`vector_data/current/`. Checksum-gated: skips rebuild if the source content
hasn't changed. Atomic swap: the new index builds under a temp path, then
renames (or copytrees on Windows fallback) to `current/`.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `build_and_swap(force=False)` | `vb_service.py` | Main entry. Returns `{"rebuilt": bool, "docs"?: int, "current": str, "meta_id"?: str, "reason"?: str}`. |
| `*` | `vb_repo.py` | Mongo access helpers for the build. |

HTTP surfaces:

- `POST /aitegrity-core/faq-automation` calls `build_and_swap(force=False)`
  after each ingest (checksum-gated).
- `POST /aitegrity-core/knowledgebase-rebuild` calls `build_and_swap(force=True)`
  directly — use when the source content in Mongo hasn't changed but you need
  the KB rebuilt anyway (e.g. after changing embedding model or reproducing a
  corrupted `vector_data/current/`). See `docs/api/faq.md`.

## Data flow

```
build_and_swap(force=False)
    ↓
_checksum_source()  → sha256 over all FAQ chunks
    ↓
compare against KB_META_COLL latest record (same namespace + embedding model)
    ↓
match & !force → return {"rebuilt": false, "reason": "up-to-date"}
    ↓
_build_embeddings()  → OpenAI OR HuggingFace
                      device resolved via core/gpu_config.resolve_device()
                      logs {event: embeddings_provider_selected, device, ...}
_faq_docs_from_mongo()  → (docs, ids) from MONGO_FAQ_UPDATE
    ↓
Chroma(collection_name=COLL, persist_directory=<tmpdir>)
vs.add_documents(docs, ids=ids)
    ↓
atomic swap tmpdir → vector_data/current/
  - unlink/rmtree old
  - rename (retry 10× on Windows PermissionError)
  - fallback: copytree (dirs_exist_ok)
    ↓
_write_meta(persist_dir, doc_count, checksum)  → KB_META_COLL insert
_cleanup_orphan_build_dirs()  → remove stale kb_build_* dirs
    ↓
return {"rebuilt": true, "docs": N, "current": path, "meta_id": ...}
```

## Env vars

| Key | Default | Purpose |
|---|---|---|
| `VECTOR_DATA_DIR` / `VECTORDB_PATH` | `./vector_data` | Chroma root. |
| `VECTOR_CURRENT_SYMLINK` | `<VECTOR_DATA_DIR>/current` | Target path (directory, not symlink on Windows). |
| `CHROMA_COLLECTION` | `faq_kb` | Collection name. |
| `KB_META_COLL` | `kb_registry` | Mongo collection for build metadata. |
| `KB_NAMESPACE` | `faq` | Logical namespace for KB builds. |
| `EMBEDDINGS_PROVIDER` | `openai` | `openai` or `hf`. |
| `EMBED_MODEL` | `text-embedding-3-large` | OpenAI embedding model. |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | HF fallback. |
| `EMBEDDING_DEVICE` | `auto` | `auto` / `cuda` / `cpu`. |
| `USE_GPU` | `true` | Master GPU switch. |
| `EMBEDDING_BATCH_SIZE` | `32` | HF batch size. |
| `OPENAI_API_KEY` | *(required for provider=openai)* | API key. |
| `MONGO_URI`, `MONGO_DB`, `MONGO_FAQ_UPDATE` | *(required)* | Source of chunks. |
| `VECTOR_HARD_RESET` | `false` | Force-rebuild on next call regardless of checksum. |

## Dependencies

- External: `langchain_chroma`, `langchain_openai`, `langchain_community` (for HF embeddings), `pymongo`, `torch` (GPU detection).
- Internal: `core/app_config.py`, `core/gpu_config.py` (implicitly via device selection).

## File map

| File | Purpose |
|---|---|
| `vb_service.py` | `build_and_swap` + helpers (`_build_embeddings`, `_checksum_source`, `_write_meta`, `_cleanup_orphan_build_dirs`). |
| `vb_repo.py` | Mongo repo helpers (minimal). |

## Gotchas

- **No `__init__.py`** in the directory. Import it as
  `from modules.vector_build.vb_service import build_and_swap` — the implicit
  package works because Python 3 supports namespace packages, but adding an
  `__init__.py` is cleaner.
- **Windows file lock** on `vector_data/current/` during rebuild — handled
  by 10× retry on rename, then copytree fallback. If you still hit it, stop
  the app (it holds the Chroma client) before retrying.
- **Orphan `kb_build_*` cleanup** is now hardened against Windows file locks
  via `_safe_rmtree` (exponential backoff up to ~15s) + `_release_chromadb_locks`
  (drops process-wide `SharedSystemClient` cache so SQLite WAL/journal handles
  release). Cleanup runs both at the START of `build_and_swap` (catches
  prior-run orphans) and at the END (cleans current build's tmpdir). The
  return value of `build_and_swap` now includes `orphans_removed` and
  `orphans_failed` lists for observability. With this in place, orphans
  should bound to 0-1 instead of accumulating per-trigger. **Caveat:** if
  the same Python process holds an active retriever (e.g. the Flask
  chatbot's `_vectorstore` in `sd_vector_repo`) at the moment cleanup runs,
  releasing the cache also drops that retriever's connection — call
  `bootstrap_vectorstore()` again to re-init. The FastAPI rebuild endpoint
  in `app.py` is safe because it doesn't hold a retriever.
- Checksum covers ONLY `chunks[].text`. If you add a new field to chunks and
  want it to trigger a rebuild, include it in `_checksum_source`.
- **Checksum order-stability (post-2026-05-07):** `_checksum_source` is now
  stable across doc-split shapes — same content distributed as 1 legacy doc OR
  N per-service docs produces the same hash. Achieved by sorting docs by
  `service_id` at query time (`.sort("service_id", 1)`) and chunks within each
  doc by `(service, chunk_index)`. Without this, migrating from a single
  legacy FAQ doc to N per-service docs would produce a different checksum on
  the first ingest, triggering a spurious KB rebuild.
- Mixing providers silently poisons retrieval: if you build with
  `EMBEDDINGS_PROVIDER=hf` and query with `=openai`, relevance is garbage.
- **Verifying GPU engaged:** since 2026-05-22, `_build_embeddings` logs
  `{"event": "embeddings_provider_selected", "device": "cuda"|"cpu", ...}`
  every time it's called. Pair with `log_gpu_status` (chatbot.py startup) to
  confirm CUDA passthrough — if `device=cpu` while `USE_GPU=true`, the
  container did NOT receive a GPU (most common cause: empty
  `CUDA_VISIBLE_DEVICES=` in `.env` or unset `RAG_GPU_COUNT` in docker-compose).
  The `KB_META_COLL` records `embedding_label` — check it before mixing.
- The embedding instance has all of `close`, `reset`, `shutdown`, `teardown`
  probed on the client to flush Chroma — if Chroma changes API, update that
  list.

## Extension notes

- Multiple namespaces: `build_and_swap` reads `KB_NAMESPACE` — set a different
  value before calling to maintain separate KBs (e.g. `faq` vs. `legal`).
  You'll need a separate `current/` path per namespace to avoid clobbering.
- Adding a new vector backend (e.g. pgvector): swap `Chroma(...)` for the
  new client, keep the checksum + atomic-swap pattern identical.
- For very large KBs, the `_checksum_source` loop is O(n) on chunk count —
  switch to Mongo's `changeStream` or a `last_updated_at` max for cheap
  drift detection.

## Per-service build (Stage 3A — 2026-05-07)

`vb_per_service.build_all(services_now, current_root, building_root, trash_root)`
orchestrates per-service Chroma rebuilds. For each service in the FAQ repo:

1. Compute `_checksum_service(service_id)` — SHA-256 of that service's chunks
   (stable across chunk order; sorted by `(service, chunk_index)`).
2. Compare to `meta.json` in `current/<service_id>/` (via
   `vb_registry.get_checksum`).
3. If changed: build new Chroma to `building/<service_id>-<uuid>/`,
   atomic-swap into `current/<service_id>/`, write fresh `meta.json`,
   async-cleanup `trash/`.
4. If unchanged: skip — preserves the FAQ-automation skip-logic from Stage 1.

Services on disk but no longer in the repo (orphans) are deleted via
`_safe_rmtree`. Reuses Stage 1 Windows file-lock workarounds
(`_release_chromadb_locks`, `_safe_rmtree`).

`vb_service.build_and_swap` is now a mode dispatcher (Stage 3A). It calls
`_legacy_build_and_swap_impl` (legacy mode, verbatim pre-3A logic) or
`_per_service_build_and_swap_impl` (split/dual mode), or both with divergence
audit (dual mode). Selected via `KB_BACKEND` env knob — see
`docs/ops/env_reference.md` and `docs/ops/deployment.md` for rollout.

`meta.json` schema (per collection dir):

```json
{
  "schema_version": 1,
  "service_id": "whistleblowing-system",
  "checksum": "sha256:...",
  "doc_count": 38,
  "built_at": "2026-05-07T10:30:00+00:00"
}
```

Mongo `kb_registry` collection still receives audit-history entries per build
(unchanged from pre-3A). Bootstrap is filesystem-driven — does not query Mongo.

Module map (Stage 3A additions):

| File | Status | Responsibility |
|---|---|---|
| `vb_registry.py` | New | Read/write per-collection `meta.json` (filesystem-side registry) |
| `vb_per_service.py` | New | Per-service Chroma build + atomic swap + orphan cleanup |
| `vb_service.py` | Modified | `build_and_swap` becomes mode dispatcher; legacy logic moved into `_legacy_build_and_swap_impl` |

See [`../superpowers/specs/2026-05-07-stage-3a-per-service-vector-store-design.md`](../superpowers/specs/2026-05-07-stage-3a-per-service-vector-store-design.md).

## Chunk identity

Every chunk Document produced by the build pipeline carries `metadata["chunk_id"]`
(Stage 2026-05-11) — a stable per-chunk identifier used by retrieval-side
anti-redundancy logic to track which chunks have already been shown to the
user this session.

Format and source per build path:

- **Per-service build** (`vb_per_service._faq_docs_for_service`):
  `<service_id>::<i:04d>` where `i` is the enumeration index in the
  service's `chunks[]` array. Empty chunks are skipped but their index is
  preserved — so the third surviving chunk after one skipped empty chunk
  gets `::0003`, not `::0002`.
- **Legacy single-collection build** (`vb_service._faq_docs_from_mongo`):
  `<doc_id>::<i:04d>` when the Mongo `_id` is present. Falls back to
  `sha1(page_content)[:16]` (16-char hex) when `_id` is absent — covers
  very-legacy single-doc shapes where the Mongo `_id` was not preserved.

Strictly additive — existing chunk content, existing metadata keys
(`service`, `i`, plus `service_id` on the per-service path), and the `ids`
array passed to Chroma's `add_documents(ids=...)` are unchanged.
Pre-2026-05-11 builds without `chunk_id` continue to work; retrieval-side
code falls back to a sha1 hash when the field is missing on a doc.

See [`../superpowers/specs/2026-05-11-anti-redundancy-answer-quality-design.md`](../superpowers/specs/2026-05-11-anti-redundancy-answer-quality-design.md).
