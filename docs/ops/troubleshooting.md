# Troubleshooting

Common failure modes and their fixes. Organized by symptom.

## Startup / boot issues

### `RuntimeError: Missing/invalid env or files: SHEET_ID, MONGO_URI, ...`

`Config.validate()` in `core/app_config.py` failed. Missing required env keys
or the service-account file doesn't exist.

- Check `.env` has `SHEET_ID`, `MONGO_URI`, `API_KEY`, `GOOGLE_SERVICE_ACCOUNT` (or `CREDS_PATH`) all set.
- If `GOOGLE_SERVICE_ACCOUNT` is a file path, confirm the file exists.
- If it's inline JSON, confirm it starts with `{` and is valid JSON.

### `NameError: scheduler is not defined` at import time

`core/app_pipelines.py` has an orphan call `register_late_response_followup_job(scheduler)`
at the bottom of the file with no `scheduler` variable in scope. This is a
latent bug. If it fires, either:

- Remove that dangling line, OR
- Import `app_pipelines` only from places that have already set up a scheduler.

Workaround: only import via `build_pipelines`, which doesn't trigger it.

### `gspread.WorksheetNotFound`

Google Sheets auth worked, but the target sheet tab doesn't exist. SSU handles
this by creating the tab (200 rows × 30 cols) when needed. For FAQ, confirm
`OUTPUT_TITLE` matches an existing tab or create it manually.

### `ImportError: cannot import name 'X' from 'modules.Y'`

Most commonly this means you pulled code but didn't run `pip install -r requirements.cuda.lock`.
Or you're on a CPU-only host and a module requires CUDA-only deps.

### Ctrl+C tidak respons / chatbot hang saat shutdown

Symptom: terminal sudah Ctrl+C tapi process tidak exit, harus `taskkill` paksa.

Root cause: ada non-daemon thread di-block pada `queue.get()`. Python interpreter tidak bisa exit selama thread non-daemon masih hidup. Pre-2026-05-07, `infra/prompt_audit_repo.py` punya issue ini (pakai `ThreadPoolExecutor` default).

Fix: writer audit sekarang pakai `threading.Thread(daemon=True)`. Kalau muncul lagi setelahnya, cek thread non-daemon lain — kemungkinan culprit:
- `modules/system_detection/sd_service.py:_SUMMARY_POOL` — `ThreadPoolExecutor(max_workers=1)`. Belum dimigrasi ke daemon, tapi rare karena worker idle dishut down setelah 60s di Python 3.9+.
- Custom code yang spawn `threading.Thread(...)` tanpa `daemon=True`.

Cek thread yang masih hidup saat hang: `python -c "import threading; print([t.name for t in threading.enumerate() if not t.daemon])"`.

## Vector / Chroma issues

### `PermissionError` on Windows when rebuilding KB

Known issue — file locks on `vector_data/current/`. `build_and_swap`
already has retry + copytree fallback. If you still see this:

1. Stop the running app (it holds the Chroma client open).
2. Delete `vector_data/kb_build_*` orphan dirs.
3. Restart and retry the FAQ ingest.

### "KB rebuilt every time even though source didn't change"

Checksum gate in `vector_build.build_and_swap` compares
`KB_META_COLL.source_version.checksum` against a sha256 of all
`faq_update_doc.chunks[].text`. If the checksum differs every run:

- Check whether something is rewriting those chunk records with trivial edits (whitespace?).
- `VECTOR_HARD_RESET=true` forces a rebuild, disable it when not debugging.

### Retrieval returns irrelevant results

- Confirm `vector_data/current/` points at the expected build (check `KB_META_COLL` for the latest record).
- Confirm `COLLECTION_NAME` / `CHROMA_COLLECTION` matches what was written.
- Confirm `EMBEDDINGS_PROVIDER` + `EMBED_MODEL` at query time match what was used at index time. Mixing OpenAI `text-embedding-3-large` with HF `all-MiniLM-L6-v2` is guaranteed bad retrieval.

### `POST /faq-automation` returns `kb_rebuilt: false` but retrieval is broken

Skip-logic gotcha. `vb_service.build_and_swap` compares `kb_registry.checksum` to source checksum. If they match, returns `up-to-date` without verifying disk state. So if `vector_data/current/` is empty / corrupt / has the wrong build content (e.g. after copy-paste from sibling project dir), the skip path fires and FAQ won't fix it.

**Fix:** call `POST /rag-assistant/knowledgebase-rebuild` (force=True) instead. Curl example:

```
curl.exe -X POST "http://127.0.0.1:2303/rag-assistant/knowledgebase-rebuild" \
  -H "Content-Type: text/plain" \
  -H "x-api-key: <API_KEY>" \
  --data "true"
```

Verify response `kb_current` path — must include the project's CWD suffix (e.g. `_060526`). If it shows a different folder, uvicorn was started from the wrong dir — kill, `cd` to the right project root, restart.

### Updated KB tidak ke-pickup chatbot tanpa restart

Known limitation. `modules/system_detection/sd_vector_repo.bootstrap_vectorstore()` runs once at Flask chatbot startup. The Chroma instance is module-cached. KB rebuilds on disk **don't auto-refresh** the running retriever.

**Workaround:** restart the Flask chatbot (`Ctrl+C` then `python -m modules.system_detection.chatbot`) after every successful KB rebuild.

**Future improvement candidates** (not implemented): polling `kb_registry.built_at` from chatbot + auto-rebootstrap; POST `/reload-kb` endpoint; file watcher on `vector_data/current/`.

### Orphan `kb_build_*` directories accumulate after each rebuild

Pre-2026-05-07 behavior. After `build_and_swap` finishes, leftover tmpdirs were silently ignored (`shutil.rmtree(..., ignore_errors=True)`). On Windows, Chroma's `SharedSystemClient` cache holds SQLite WAL/journal handles open process-wide → rmtree always failed.

**Mitigated** by `_release_chromadb_locks()` + `_safe_rmtree()` in `vb_service.py`. Pre-build cleanup at top of `build_and_swap` clears prior runs' orphans. Worst case: 1 orphan persists at any time (the just-finished build's tmpdir if its handles haven't aged), cleared by next trigger.

If orphans still pile up:
1. Confirm the patched `vb_service.py` is loaded (check for `_safe_rmtree` import).
2. `Get-Process python` — kill any other Python processes that might hold locks on `kb_build_*` files.
3. Manual cleanup once: `Get-ChildItem vector_data\ -Directory -Filter "kb_build_*" | Remove-Item -Recurse -Force`.
4. Trigger one rebuild (endpoint B) to confirm cycle is clean.

### Reply language stuck di bahasa turn pertama / tidak follow input switch

Symptom: User kirim turn 1 mixed/EN → reply EN ✓. Turn 2 user switch ke ID → reply masih EN. Turn 3 EN lagi → reply EN. Reply language LOCKED ke turn pertama.

Pre-2026-05-07 root causes (semua sudah di-fix):

1. **Greeting regex shortcut** (`GREETING_LANG_HINTS` di `sd_policies.py`) — return language EARLY tanpa Claude untuk pesan dimulai dengan "halo"/"hi"/"bonjour" dll. Salah untuk "Halo, can you help with X?". **Removed.**

2. **First-turn lock** (`_get_locked_language_from_history` di `sd_service.py`) — return bahasa dari natural turn pertama, override per-turn detection di 3 call sites. **Removed**, replaced dengan `_majority_language_from_history` yang dipakai sebagai fallback HANYA untuk input technical (BOOK_A_MEETING, picker tokens dll).

3. **SA qualification path tidak terima per-turn detection** — `_render_sa_continue_via_sd` rely pada `state.language_code` yang stale (di-set di turn awal SA flow). **Fixed** dengan tambah parameter `turn_language_code` + `turn_language_name`; caller di handle_chat pass fresh detection.

Kalau symptom muncul LAGI setelah fix di atas:

1. Cek response field `prompt_applied` di `query_recording`:
   ```javascript
   db.query_recording.find({sessionId:"<x>"}, {stage:1, prompt_applied:1, "extras.language_code":1}).sort({timestamp:1})
   ```
   Untuk setiap turn, line `Target language: <X>` harus match input bahasa turn itu. Kalau tidak match → trace langkah berikutnya.

2. Cek `language_code` di response field root — harus berubah per turn mengikuti input.

3. Trace path: kalau bahasa tidak switch saat user pindah bahasa, kemungkinan ada compose path lain (di `ma_service.py` meeting flow, di service-agent-specific logic) yang masih pakai `state.language_code` sebagai primary source. Per `project_language_flow` memory, semua compose path harus thread per-turn `language_code` sebagai parameter — bukan baca dari state.

### `kb_current` path tidak match folder uvicorn

Symptom: `POST /faq-automation` response `kb_current` mengandung path folder LAIN (mis. `rag_conflict_fixed/` instead of `rag_conflict_fixed_060526/`).

Root cause: `cfg.VECTOR_CURRENT_SYMLINK = "./vector_data/current"` di-resolve relatif ke CWD saat `vb_service.py` di-import. Kalau uvicorn di-start dari folder yang salah, `vector_data/` operations target folder itu — bukan project Anda saat ini.

**Fix:** kill uvicorn, `cd` ke project root yang benar, lalu start ulang. Verify dengan response — path harus mengandung folder yang Anda mau.

## FAQ ingestion issues (post-2026-05-07 per-service refactor)

### `400 Bad Request` with `"reason": "service_id collisions detected"`

Two tabs in the source Google Sheet produced the same `service_id` slug
(e.g. `"Service"` + `"service"` → both `"service"`, or `"Market Research"` + `"market research"` → both `"market-survey"`). Ingestion aborts **before any Mongo writes** — partial state never created.

**Response body:**
```json
{
  "ok": false,
  "reason": "service_id collisions detected",
  "collisions": {"service": ["Service", "service"]}
}
```

**Fix:** rename one of the conflicting tabs in the Sheet UI to produce a distinct slug. Any non-letter difference works:
- `"Service"` vs `"Services"`
- `"Market Research"` vs `"Market Researchs"`
- `"Service"` vs `"Service A"`

Re-trigger `POST /rag-assistant/faq-automation`. Should succeed.

### Service deleted unexpectedly from Mongo

If a `service_id` appears in `services_deleted` of the FAQ-automation response, that tab is **no longer in the source Sheet** (or is excluded by `INCLUDE_SHEETS` filter). Reconciliation is by-design — Sheet is source of truth.

App log will show:
```json
{"event": "faq_service_deleted", "service_id": "<slug>", "reason": "absent_in_sheet_at_ingest"}
```

**Fix:** re-add the tab to the Sheet (or remove it from `INCLUDE_SHEETS` exclusion), re-trigger `POST /rag-assistant/faq-automation`. The service will be re-created with new `created_at` timestamp and fresh `service_aliases: []`. **Manual aliases edited via Mongo CLI before deletion are lost** — that's the trade-off of hard-delete reconciliation.

### Migration script reports `"status": "noop"` but you expect a split

Means there's no legacy single-doc to migrate (already migrated, or the collection is empty). Verify:

```javascript
// Mongo shell
db.faq_update_doc.find({"marker":"latest", "service_id": {"$exists": false}}).count()
// 0 = already migrated, 1 = legacy doc still present
```

If `count == 0` and you expected `1`: the migration already ran at some point. Check:
```javascript
db.faq_update_doc.countDocuments({"marker":"latest"})
// Should be N (number of service tabs) after migration
```

Re-trigger normal ingest via `POST /rag-assistant/faq-automation` if you want a fresh sync from Sheet.

### Migration script reports `"status": "abort"` (legacy has no chunks)

The legacy single doc exists but has empty `chunks` array. Ingest must have failed mid-write previously, OR an admin manually cleared chunks.

**Fix:** trigger `POST /rag-assistant/faq-automation` to re-ingest from Sheet (this will create per-service docs directly via the new code path), then verify legacy doc is gone (or run `migrate_split_latest` to clean it up — should be no-op since no chunks to split).

### `_checksum_source` produces different hash before vs after migration

Should be identical for identical content (regression invariant). If different:

1. Check `_checksum_source` sort key: must be `.sort("service_id", 1)` AND chunk-internal sort by `(service, chunk_index)`. Plan said `chunk_index` only — verify production code uses tuple key.
2. Check legacy doc's chunks for content drift (operator manually edited?).
3. Check migration script — does it preserve chunk content verbatim, no normalization?

If you confirm content is identical but hash differs → bug in `_checksum_source`. File issue + revert migration via `vector_build/migrate_*` (if present) or restore Mongo backup.

## Auth / request issues

### 401 "Invalid or missing API key"

- `API_KEY` in `.env` doesn't match the `x-api-key` header.
- `API_HEADER_NAME` is set to a different name and the client is still sending `x-api-key`.
- Internal service-agent endpoint uses `SERVICE_AGENT_API_KEY` + `x-service-agent-api-key` — different from the main one.

### 400 "Missing required header 'x-website-id'"

`WEBSITE_ID_HEADER_NAME` is not `off`. Either send the header or set
`WEBSITE_ID_HEADER_NAME=off` in `.env` for testing.

### 415 "Content-Type must be text/plain" (FAQ endpoint)

`POST /rag-assistant/faq-automation` is a trigger endpoint that expects a
plain-text body equal to `TRIGGER_TRUE_VALUE` (default `true`). Send:

```
Content-Type: text/plain

true
```

Not JSON.

### 409 "Active token exists"

`POST /rag-assistant/session-id-generate` refuses to issue a new session while
an active one exists for the same API key. Either:

- Wait for the auto-deactivator (runs every `CHECK_INTERVAL_SECONDS`).
- Hit the manual deactivate path in the UI testing endpoints.
- Shorten `SESSION_IDLE_WITH_HISTORY_SECONDS` for testing.

## GPU / embeddings

See [`gpu_setup.md`](gpu_setup.md) "Troubleshooting" section.

### OpenAI embedding rate limits

If `EMBEDDINGS_PROVIDER=openai` and you hit 429s during FAQ ingest:

- Reduce FAQ source size (fewer chunks per run).
- Switch to `EMBEDDINGS_PROVIDER=hf` for ingest (slower but unmetered).

## Scheduler issues

### SSU job never fires

1. Is `SSU_FEATURE_ON=true`?
2. Is the current WIB time within `WORK_START`–`WORK_END`?
3. Is an entrypoint actually running that registered the job? (`main.py` OR `modules/system_detection/chatbot.py`)
4. Check logs for `"event": "ssu_ok"` or exceptions.

### Auto-deactivate scanner not running

Only runs inside the `token_generate` Flask service (`python -m modules.token_generate.generate`).
If you run only the main chatbot, tokens won't auto-expire.

### Late-response follow-up doing nothing

- `LATE_RESPONDS_FEATURE=on`?
- `LATE_RESPONDS_TIME` (seconds since last message) elapsed?
- `LATE_RESPONDS_REQUIRE_CHAT_HISTORY` is default-on; sessions without prior chat are skipped.
- Per-session cap: `LATE_RESPONDS_MAX_PER_SESSION` (default 1).

## Logging

### "Where are my logs?"

- stdout, JSON lines (configured in `core/app_logging.py`).
- Meeting events also write to Mongo collection `meeting_logs`.
- `run_logs/` directory — local runtime logs, gitignored.

### Adjusting verbosity

`LOG_LEVEL=DEBUG` in `.env`. Restart the process — logging is configured once.

## Deployment / CI

### GitLab CI `lock-deps-cuda` fails with API mismatch

Fixed by pinning `pip<25` and `pip-tools>=7.4.1,<8`. If you see it return, the
pin was reverted — see `.gitlab-ci.yml`.

### `deploy-to-server` SSH fails with "Host key verification failed"

The job uses `-o StrictHostKeyChecking=accept-new`, which accepts new hosts
but rejects changed keys. If the target host was re-provisioned, you need to
clear its entry from the CI runner's known_hosts, or switch to
`StrictHostKeyChecking=no` (less secure).

### "Container runs but endpoint returns 500"

- Check Mongo connectivity from inside the container.
- Check `nvidia-smi` inside the container if GPU-dependent.
- Check logs for the `gpu_status` event at startup — tells you whether the container saw the GPU.

## Data integrity

### Chat history duplicated across sessions

`session_id` resolution: if the client sends only `token_id`, the server looks
up the matching session. Make sure you're not reusing `session_id` across
different `token_id`s. See `_resolve_session_ids` in `sd_controller.py`.
