# Environment Variable Reference

Every env key the application reads, grouped by concern. All keys route through
`core/app_config.py` (`Config` dataclass) — do not read env directly in new
code.

Format per key: `KEY` — default — description.

## Image selection & runtime (docker-compose)

| Key | Default | Purpose |
|---|---|---|
| `RAG_REGISTRY_IMAGE` | `registry.gitlab.com/your-group/your-project` | Base image URI in GitLab Registry. Compose builds `${RAG_REGISTRY_IMAGE}/rag-${RAG_FLAVOR}:${RAG_IMAGE_TAG}`. |
| `RAG_FLAVOR` | `cuda` | `cuda` or `cpu`. Picks which runtime stage from `Dockerfile.prod`. |
| `RAG_IMAGE_TAG` | `__COMMIT_SHA__` | Set by CI on deploy; maps to `CI_COMMIT_SHORT_SHA`. |
| `RAG_GPU_COUNT` | `all` | Passed to `device_requests.count` in `docker-compose.yml`. Set to `0` for CPU-only. |
| `NVIDIA_VISIBLE_DEVICES` | `all` | Passed into the container. |
| `NVIDIA_DRIVER_CAPABILITIES` | `compute,utility` | Passed into the container. |

## LLM / embeddings

| Key | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | *(empty)* | OpenAI key — used for embeddings when `EMBEDDINGS_PROVIDER=openai`. |
| `CLAUDE_API_KEY` / `ANTHROPIC_API_KEY` | *(empty)* | Anthropic key. `ANTHROPIC_API_KEY` takes priority; falls back to `CLAUDE_API_KEY`. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Claude model ID. |
| `MAX_OUTPUT_TOKENS` | `500` | Output token cap for main replies. |
| `MAX_TOKENS_BRIEF` | `300` | Brief/summary replies. |
| `MAX_TOKENS_ASK` | `120` | Clarifying-question replies. |
| `LLM_TEMPERATURE` | `0.2` | Anthropic/OpenAI sampling temperature. |
| `LANGUAGE_DETECTOR` | `ensemble` | Language-detection backend selector. |
| `EMBEDDINGS_PROVIDER` | `openai` | `openai` (remote) or `hf` (local Sentence-Transformers). |
| `EMBED_MODEL` | `text-embedding-3-large` | OpenAI embedding model (when provider=openai). |
| `EMBEDDING_MODEL_NAME` | `sentence-transformers/all-MiniLM-L6-v2` | HF model (when provider=hf). |
| `EMBEDDING_DEVICE` | `auto` | `auto` / `cuda` / `cpu`. Resolved by `core/gpu_config.py:resolve_device`. |
| `USE_GPU` | `true` | Master GPU switch. `false` forces CPU regardless. |
| `EMBEDDING_BATCH_SIZE` | `32` | HF embeddings batch size. |
| `DB_BACKEND` | `mongo` | Selects FAQ repository implementation in `infra/app_repo.build_faq_repo`. `mongo` (default) / `postgres` (reserved — raises `NotImplementedError` if selected). Per-2026-05-07 FAQ refactor. |

## History & summarization

| Key | Default | Purpose |
|---|---|---|
| `SUMMARY_ASYNC` | `on` | Refresh conversation summary asynchronously after responding. |
| `SUMMARY_ASYNC_DELAY_SEC` | `0.6` | Delay before async summary task kicks off. |
| `HISTORY_SUMMARY_MAX_TOKENS` | `160` (module override: `220` in app_config) | Token cap for rolling summary. |
| `HISTORY_SUMMARY_MAX_PAIRS` | `12` (module override: `20` in app_config) | Max user/bot pairs considered for summary. |
| `HISTORY_SUMMARY_MAX_CHARS` | `2500` | Char cap on summary text. |
| `PROMPT_STORE_MODE` | `text` | `text` / `messages` / `off` — how prompts are audited to Mongo. `off` keeps metadata but nulls `llm_prompt` / `llm_output`. |
| `PROMPT_MAX_CHARS` | `6000` | Cap on stored prompt length (applies to both prompt and response bodies). |
| `PROMPT_AUDIT_BACKEND` | `mongo` | Selects writer in `infra/prompt_audit_repo.py`. `mongo` (default) / `noop` (kill-switch). `postgres` reserved — raises `NotImplementedError`. |
| `PROMPT_AUDIT_QUEUE_SIZE` | `1024` | Bounded queue for the writer thread pool. Drop-on-full (counter `w.dropped`). |
| `PROMPT_AUDIT_WORKERS` | `1` | Worker thread count. Default 1 keeps insert order per process. |
| `INPUT_MAX_PROMPT` | `8000` (was `3000` pre-2026-05-07) | Cap on the **rendered prompt sent to the LLM** (the variable name is misleading — it is NOT a user-input cap). Consumed by `render_incontext_prompt`/`render_outcontext_prompt`/etc. via `_clip(text, max_chars)`. Must be ≥ ~8000 when `CTX_DOCS_FLOOR=4` AND chunks average ~1500 chars, otherwise `_clip` truncates the Context section and fewer than 4 chunks reach the LLM. Lower values reduce input-token cost per turn at the risk of context truncation. |
| `CHAT_HISTORY_SCHEMA` | `allsum` | Schema variant used by `chat_with_history`. |
| `UTILIZER_STATUS` | `local` | `local` / `crisp` — default chat utilizer mode. |

## Mongo (shared)

| Key | Default | Purpose |
|---|---|---|
| `MONGO_URI` | *(required)* | MongoDB connection string. |
| `MONGO_DB` | `faq_automation` | Main application DB. |
| `MONGO_FAQ_UPDATE` | `faq_update_doc` | Collection holding FAQ source chunks. |
| `FIELD_FAQ_TEXT` | `text` | Field name for FAQ text. |
| `CHAT_HISTORY_COLL` | `chat_history` | Per-session chat history collection. |
| `SA_HISTORY_COLL` | `qfc_service_agent` | Service agent flow history. |
| `MAX_DOCS` | `1` | **Dead knob — not consumed anywhere in code.** Safe to remove. |
| `CTX_DOCS_FLOOR` | `4` | Phase 1 (no `sa_service_label`): minimum FAQ docs in the main-prompt context when no service has been picked yet. Grader filters; short-falls are backfilled with top-ranked retrieved candidates. Consumed by the generic `_prepare_rag_context` in `sd_service.py`. |
| `CTX_DOCS_SAME_SERVICE` | `4` | Phase 2 (after `SA_SELECT_*` picker click): this many docs are retrieved with `metadata.service == sa_service_label` filter. Default `4` to keep the main-prompt context at exactly 4 same-service docs. |
| `CTX_DOCS_OTHER_SERVICE` | `0` | Added on top of `CTX_DOCS_SAME_SERVICE` in Phase 2 (service-biased path): this many best-pick docs from other services are appended for cross-reference. Default `0` keeps Phase 2 reply context purely same-service. Total context floor when service is known = `CTX_DOCS_SAME_SERVICE + CTX_DOCS_OTHER_SERVICE` (default 4 + 0 = 4). Helper: `sd_vector_repo.retrieve_service_biased`. |
| `CTX_INFER_SERVICE_FROM_QUERY` | `on` | When `on`, the generic retrieval path (`_prepare_rag_context`) runs a typo-tolerant fuzzy match of service-name tokens against the user's query **before** calling the retriever. If a service is inferred (e.g. "Merket survey" → "Market Survey"), the biased retrieval is used. Set `off` to force plain top-N retrieval regardless of query content. |
| `CTX_INFER_FUZZY_RATIO` | `0.82` | Minimum `difflib.SequenceMatcher.ratio()` for a typo-tolerant word match. Lower values catch more typos but risk false-positives. Examples at 0.82: "merket"≈"market" (0.83, passes), "mysterie"≈"mystery" (0.80, fails). |
| `CTX_PIN_SERVICE_DEFINITION` | `on` | When `on` AND a service is inferred AND the query has explanation intent (e.g. "Tolong jelaskan tentang X", "What is X", "apa itu X"), the canonical "What is X service?" definitional FAQ is pinned to position 0 of the retrieved context — regardless of raw embedding similarity or grader outcome. This guards against cross-lingual queries where the definitional FAQ embeds weakly. Implemented via a targeted `similarity_search` with `filter={"service": X}` and `k=1`. |
| `MONGO_SESSION` | `api_keys` | Collection for issued user tokens + active sessions. |
| `QUERY_RECORDING_COLL` | `query_recording` | Query-audit collection. |
| `DB_CHATBOT` | `integrity_chatbot` | Secondary DB used by calendar/sales features. |
| `PAYLOAD_CALENDAR_COL` | `calendar_payload` | Calendar payloads read by SSU. |
| `MA_CONFIRMATION_COLL` | `ma_confirmation` | Meeting-arrangement confirmation log. |
| `LATE_RESPONDS_COLL` | `late_response_followups` | Late-response follow-up records. |

## Vector / Chroma

| Key | Default | Purpose |
|---|---|---|
| `VECTOR_DATA_DIR` / `VECTORDB_PATH` | `./vector_data` | Persistent Chroma root. |
| `VECTOR_CURRENT_SYMLINK` | `<VECTOR_DATA_DIR>/current` | Swapped to new build on atomic rebuild. |
| `CHROMA_COLLECTION` / `COLLECTION_NAME` | `faq_kb` / `FaQ_ChromaDB_OpenAI` | Chroma collection name. |
| `VECTOR_BACKEND` | `chroma` | Vector store label (metadata only). |
| `KB_META_COLL` | `kb_registry` | Mongo collection for build metadata. |
| `KB_NAMESPACE` | `faq` | Logical namespace for KB builds. |
| `VECTOR_HARD_RESET` | `false` | Force-rebuild KB from scratch. |
| `KB_BACKEND` | `legacy` | Vector-store backend mode (Stage 3A). `legacy` = single Chroma collection (pre-3A); `split` = N per-service collections; `dual` = both, per-service primary + legacy fallback during migration. |
| `KB_DUAL_AB_SAMPLE_RATE` | `0.0` | Fraction of retrieval calls in dual mode that run BOTH backends to log divergence telemetry. `0.0` off, `1.0` every call. |

## API auth / headers

| Key | Default | Purpose |
|---|---|---|
| `API_KEY` | `4743f227-…` | Public chatbot API key. |
| `API_HEADER_NAME` | `x-api-key` | Header name for `API_KEY`. |
| `SERVICE_AGENT_API_KEY` | `0569b455-…` | Internal service-agent API key. |
| `SERVICE_AGENT_API_HEADER_NAME` | `x-service-agent-api-key` | Header for above. |
| `WEBSITE_ID_HEADER_NAME` | `off` | Header name for website ID; `off` disables the requirement. |
| `TRIGGER_TRUE_VALUE` | `true` | Plain-text body required by trigger endpoints (FAQ ingest, session-id gen). |
| `TRUSTED_HOSTS` | *(unset)* | Comma-separated host allowlist for Flask `TRUSTED_HOSTS`. `*` / `off` / `none` / empty disables. |
| `TESTING_WEBSITEID` | `off` | Testing-mode toggle. |
| `TESTING_APIKEY` | *(empty)* | Testing API key for UI. |

## Ports & URLs

| Key | Default | Purpose |
|---|---|---|
| `PORT` | `2303` | Generic fallback port. |
| `PORT_TG` | `2303` | `token_generate` Flask service port. |
| `PORT_UI_TEST` | `2304` | `chat_testing_ui` port (when run standalone). |
| `PORT_CHATBOT` | `2305` | `modules/system_detection/chatbot.py` Flask port. |
| `PUBLIC_BASE_URL` | *(unset)* | Override request-URL reconstruction in FAQ controller (e.g. `https://api.example.com:2303`). |

## Session lifecycle

| Key | Default | Purpose |
|---|---|---|
| `SESSION_IDLE_WITH_HISTORY_SECONDS` | `600` | Deactivate a session with prior chat after this idle gap. |
| `SESSION_NO_ACTIVITY_TTL_SECONDS` | `604800` | Deactivate a session with no activity after 7d. |
| `CHECK_INTERVAL_SECONDS` | `60` | APScheduler interval for the auto-deactivate scanner. |

## Timezone & scheduling

| Key | Default | Purpose |
|---|---|---|
| `TIMEZONE` | `Asia/Jakarta` | Application-wide timezone. Used by schedulers, log timestamps, WIB conversions. |
| `CRON_HOUR` | `17` | Legacy cron hour (reserved). |
| `CRON_MINUTE` | `30` | Legacy cron minute (reserved). |

## Google Sheets

| Key | Default | Purpose |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT` | *(empty)* | Either JSON inline or path to `sa.json`. |
| `GOOGLE_APPLICATION_CREDENTIALS` / `CREDS_PATH` | `secrets/sa.json` | Fallback SA file. |
| `SHEET_ID` | *(required)* | FAQ source spreadsheet ID. |
| `OUTPUT_TITLE` | `FAQ` | Output worksheet name. |
| `INCLUDE_SHEETS` | *(empty)* | Comma-separated list of source sheets to include; empty = all. |
| `WRAP_WIDTH` | `0` | Text wrap width; `0` = no wrap. |
| `SA_CLIENT_EMAIL` | *(empty)* | Optional SA email (informational). |

## Google Chat-history mirror (optional)

| Key | Default | Purpose |
|---|---|---|
| `GOOGLE_CHAT_HISTORY` | `off` | Feature flag. `on` / `1` / `true` enables. |
| `GOOGLE_CHAT_SHEET_ID` | *(unset)* | Target spreadsheet for mirrored chats. |
| `GOOGLE_CHAT_SHEET_TAB` | `Chat_History_151025` | Target tab name. |

## Meeting arrangement & sales

| Key | Default | Purpose |
|---|---|---|
| `SALES_SHEET_ID` | `1Kz7WIVaNBHmVEX-…` | Sales availability spreadsheet. |
| `SALES_SHEET_NAME` | `Sales_Slots2` | Aggregate matrix worksheet. |
| `INDV_SALES_SHEET_NAME` | `Sales_Slots2_IDV` | Per-sales individual matrix worksheet. |
| `DAYS_PROPOSAL` | `7` | How many days ahead to propose. |
| `INDV_SHEET_TTL_SEC` / `INDV_INDEX_TTL_SEC` | `60` | Cache TTLs for individual sheet. |
| `SHEETS_MIN_INTERVAL` | `0.25` | Throttle between Sheets API calls. |
| `BOOKED_PATH_API` | `http://10.30.112.16:3030/api/calendar/event` | Calendar booking endpoint. |
| `BEARER_TOKEN_CALENDAR_API` | `kmzWa8wa` | Bearer token for calendar API. |
| `SALES_EMAIL_API_BASE_URL` | *(empty)* | Sales coverage API base. |
| `SALES_COVERAGE_PATH` | *(empty)* | Path suffix. Auto-prefixed with `/`. |
| `SALES_EMAIL_API_BEARER_TOKEN` | *(empty)* | Auth bearer. |
| `SALES_EMAIL_API_TIMEOUT_SECS` | `30` | Request timeout. |
| `MEETING_API_BASE_URL` | *(empty)* | Meeting user + availability API. |
| `MEETING_API_BEARER_TOKEN` | *(empty)* | Auth bearer. |
| `MEETING_USER_PATH` | `chat/user` | Relative path. |
| `MEETING_AVAILABILITY_PATH` | `sales/availability` | Relative path. |
| `MEETING_API_TIMEOUT_SECS` | `10` | Request timeout. |
| `MAX_OTHER_SLOT_PICKS` | `5` | Cap on alternative slots offered. |
| `ORGANIZER_EMAIL` | *(empty)* | Default organizer. |
| `TIME_CHAT_BORDER` | `15:00` | WIB cutoff for "today vs tomorrow" slot logic. |
| `HOST_TIME_FORMAT` | `UTC+7` | Display format for slot times. |
| `MEETING_POPUP` | `0` | Cadence for the BOOK_A_MEETING popup inside service-agent qualification. `0` = disabled. `N > 0` = show the picker at qualification steps that are multiples of N (e.g. `2` → steps 2, 4, 6, …). Each qualifying step renders the picker **once**; Method A tracks via `popup_shown_steps` in `dual_agent_meta`, Method B (2026-05-18) tracks via `state.popup_shown_counts`. Method B counts filled flow answers (not strict question index) and suppresses the picker when `interest_signal == "not_interested"`. |

## SSU (sales slots update) — read via `ssu_utils.read_env_config`

| Key | Default | Purpose |
|---|---|---|
| `SSU_FEATURE_ON` | `true` | Master switch for SSU scheduled job. |
| `SLOTS_UPDATE_DURATION` | `30` | Interval minutes for SSU job. |
| `WORK_START` / `WORK_END` | `09:00` / `17:00` | Working-hours window (WIB) gate. |
| `SSU_DAYS_AHEAD` | *(set in ssu_utils)* | How many days forward the matrix covers. |
| `SALES_SLOTS_COLL` | *(set in ssu_utils)* | Mongo collection read for slots. |
| `SSU_LOG_COLL` | *(optional)* | Log collection for SSU runs. |
| `SSU_LOG_MODE` | `upsert` | `upsert` (single latest) or `append`. |
| `GOOGLE_SA_PATH` | *(alias)* | Alternate name for SA credentials path. |
| `SSU_API_KEY` / `X_API_KEY` | *(any one)* | Header key for manual SSU trigger via FastAPI. |

## Late response follow-up

| Key | Default | Purpose |
|---|---|---|
| `LATE_RESPONDS_FEATURE` | `off` | Feature flag. |
| `LATE_RESPONDS_TIME` | `1800` | Seconds of silence before triggering a follow-up. |
| `LATE_RESPONDS_CHECK_INTERVAL` | `60` | APScheduler interval for the scan. |
| `LATE_RESPONDS_MAX_PER_SESSION` | `1` | Cap on follow-ups per session. |
| `LATE_RESPONDS_REQUIRE_CHAT_HISTORY` | `1` | If truthy, skip sessions with no prior chat. |

## Monday.com handoff (service-agent quotation)

| Key | Default | Purpose |
|---|---|---|
| `BOARD_ID` | *(empty)* | Monday board ID. |
| `TOPICS` | *(empty)* | Topic filter (CSV or string). |
| `MONDAY_PATH` | `https://n8n.integrity-asia.com/webhook/0f474b33-…` | n8n webhook URL. |
| `MONDAY_KEY` | *(empty)* | Header key. |
| `MONDAY_VALUE` | *(empty)* | Header value. |

## Chunking / retrieval

| Key | Default | Purpose |
|---|---|---|
| `CHUNK_SIZE_CHARS` | `1200` | FAQ chunk size. |
| `CHUNK_OVERLAP_CHARS` | `200` | FAQ chunk overlap. |
| ~~`TOP_K`~~ | — | **Removed (was a dead knob).** Retrieval is governed by `RETRIEVAL_K` (sd_policies.py — generic path fallback) and `CTX_DOCS_SAME_SERVICE` / `CTX_DOCS_OTHER_SERVICE` (service-biased path). |
| `RETRIEVAL_K` | `4` | Phase 1 retrieval k for the unbiased path (no `sa_service_label`). Should be ≥ `CTX_DOCS_FLOOR` so the floor can be honored after grader rejection. Lower = fewer doc_grader LLM calls per turn. |
| `GRADER_MODEL` | *(unset → falls back to `ANTHROPIC_MODEL`)* | Per-stage model override for the per-document `doc_grader` LLM. Recommended `claude-haiku-4-5-20251001` — binary yes/no classification doesn't need Sonnet, ~5× cheaper. |
| `DOC_GRADER_PARALLEL` | `6` | Max concurrent threads for parallel `grade_and_filter_yes`. K-doc grader calls now run concurrently instead of sequentially. Lower if you hit Anthropic rate limits. |

## Anti-Redundancy & Answer Quality (2026-05-11; default flipped 2026-05-12)

All knobs share the `REDUNDANCY_*` prefix. **Default `REDUNDANCY_METHOD=mmr`**
(promoted from `"normal"` on 2026-05-12 after targeted QA run — see
`qa/runs/20260512-targeted/` for evidence: rc_count_final=11 vs 10 for
fuzzy/embedding, correct recap bypass, -9% latency vs `normal` on
incontext path). `"normal"` remains available as the runtime kill-switch.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `REDUNDANCY_METHOD` | str | `mmr` | One of `mmr` / `normal` / `fuzzy` / `embedding`. `normal` = byte-identical to pre-patch (runtime kill-switch). |
| `REDUNDANCY_FUZZY_THRESHOLD` | float | `0.85` | rapidfuzz `token_set_ratio` threshold on 0..1. Higher = stricter dedup. Used only when METHOD=fuzzy. |
| `REDUNDANCY_EMBEDDING_THRESHOLD` | float | `0.92` | Cosine-similarity threshold on 0..1. Higher = stricter dedup. Used only when METHOD=embedding. |
| `REDUNDANCY_MMR_LAMBDA` | float | `0.7` | MMR λ — 1.0 = pure relevance, 0.0 = pure diversity. Used only when METHOD=mmr. |
| `REDUNDANCY_MMR_FETCH_K_MULTIPLIER` | int | `2` | `fetch_k = k × multiplier` for MMR's candidate pool. Used only when METHOD=mmr. |
| `REDUNDANCY_RECENT_CHUNKS_WINDOW` | int | `5` | Rolling window in turns; total cap = window × `CTX_DOCS_FLOOR`. Used when METHOD ≠ normal. |
| `REDUNDANCY_RECENT_CHUNKS_SPILLOVER` | int | `2` | Extra over-fetch when `recent_chunk_ids` is non-empty (gives filter headroom). Used when METHOD ≠ normal. |
| `REDUNDANCY_RECAP_BYPASS` | bool | `true` | When true, `say that again` / `ulangi` / etc. bypasses the recent-chunks filter. Used when METHOD ≠ normal. |

## Qualification Method Toggle (2026-05-12)

`QUALIFICATION_METHOD` selects the qualification flow algorithm for SA flows
(after user clicks `SA_SELECT` picker). Default `two_decision_tree` (existing
behavior, strict-additive guarantee). `natural_qualification` is opt-in and
adds a single-agent natural-conversation collector — see
[`../modules/service_agent.md#qualification-method-toggle-stage-2026-05-12`](../modules/service_agent.md#qualification-method-toggle-stage-2026-05-12)
for the full algorithm.

| Key | Type | Default | Purpose |
|---|---|---|---|
| `QUALIFICATION_METHOD` | str | `two_decision_tree` | One of `two_decision_tree` / `natural_qualification`. Validated at startup (invalid value falls back to default). Method locked per session at first SA continuation dispatch — flipping env does not affect in-flight sessions. |

## Feature flags

| Key | Default | Purpose |
|---|---|---|
| `FAQ_VERIFICATOR` | `on` | Whether the FAQ ingest endpoint accepts the trigger. `off` returns 400. |

## Source files

| Key | Default | Purpose |
|---|---|---|
| `SOURCE_FILE` | `/app/data/text/FAQ_for_Vertex_AI_Metabot.txt` | Text source for RAG (legacy / optional). |
| `WEBSITE_ID` | *(empty)* | Optional fixed website ID for single-tenant deploys. |

## Logging

| Key | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Root logger level. |

---

When adding a new env key: add it to `core/app_config.py`'s `Config` dataclass
AND append a row to the right section above, in the same turn.

---

## OOC engine (Stage 0, 2026-05-13)

See `docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md` §6.3 for full design context. All values consumed via `core/app_config.Config`.

| Key | Type | Default | Range / values | Effect |
|---|---|---|---|---|
| `OOC_AGENT_ENABLED` | bool | `on` | on/off | Master switch. `off` disables OOC classification entirely (messages fall through to existing dispatcher). |
| `OOC_MODE` | str | `hybrid` | keyword \| hybrid \| llm | Classifier mode. `hybrid` = keyword-strict for high-confidence categories + LLM fallback for fuzzy ones (recommended). |
| `OOC_MIN_KEYWORD_HITS` | int | `1` | 1-3 | Minimum keyword matches before a keyword-strict category fires. |
| `OOC_MIN_TEXT_LEN` | int | `3` | 1-10 | Minimum text length (chars after strip). Shorter → return UNCLEAR. |
| `OOC_ESCALATION_THRESHOLD` | int | `3` | 2-5 | Consecutive OOC turns before human-handover escalation. Default 3 = escalate ON the 3rd consecutive OOC. |
| `OOC_ESCALATION_SUPPRESSION_TURNS` | int | `3` | 1-10 | Per-user-message countdown after escalation fires. While > 0, OOC classifier skipped; message falls through. |
| `OOC_LLM_CONFIDENCE_FLOOR` | float | `0.6` | 0.3-0.9 | Below this LLM-classifier confidence, treat as "no OOC". |
| `OOC_CATCHALL_FLOOR` | float | `0.7` | 0.5-0.95 | Higher bar for CATCHALL specifically (misclassifying on-topic as CATCHALL is worse UX than UNCLEAR fallthrough). |
| `OOC_KEYWORD_CONFIDENCE` | float | `0.95` | 0.8-1.0 | Confidence assigned to strict keyword-bank matches. |
| `OOC_LANG_DETECTION_FLOOR` | float | `0.85` | 0.7-0.95 | Below this language-detection confidence, fall back to `session_fallback_language` (state-persisted). |
| `OOC_FREELANCER_URL` | str | `https://www.integrity-indonesia.com/freelancer/` | URL | Routing URL inserted into OOC-FREELANCE cold-start / mid-flow templates as `{freelancer_url}` placeholder. Pre-Stage-0 knob, mirrored into `Config` per spec §6.3. |
| `OOC_PARTNER_URL` | str | `https://www.integrity-indonesia.com/partner/` | URL | Routing URL inserted into OOC-PARTNERSHIP cold-start / mid-flow templates as `{partnership_url}` placeholder. Pre-Stage-0 knob, mirrored into `Config` per spec §6.3. |
| `OOC_HIGH_STAKES_SERVICES` | CSV tuple | `corporate_fraud_investigation,insurance_claim_investigation,asset_tracing,skip_tracing` | CSV of service IDs | Triggers `mid_flow_high_stakes` shape (adds P4 escalation paragraph with senior contact / urgent routing). |
| `OOC_ALLOWED_LOCALES` | CSV tuple | `()` (empty = all) | CSV of lang codes | Restricts effective_language to listed langs. Empty = all 17 canonical allowed. |
| `OOC_POSTHOC_CLASSIFIER_ENABLED` | bool | `false` | true/false | Refinement #3. When enabled, samples suppression-fallthrough turns to log "would have classified" data for Phase 1 tuning. |
| `OOC_POSTHOC_CLASSIFIER_SAMPLE_RATE` | float | `0.1` | 0.0-1.0 | Fraction of suppression-fallthrough turns sampled when enabled. |
| `OOC_POSTHOC_CLASSIFIER_MODE` | str | `keyword` | keyword \| hybrid \| llm | Mode for the post-hoc classifier (cheaper than primary `OOC_MODE` is the typical choice). |

**Routing-asset note:** `OOC_FREELANCER_URL` and `OOC_PARTNER_URL` (rows above) are the only OOC routing URLs sourced from env. Other routing assets (emails, phone numbers, business hours, additional URLs) live in the `ROUTING_ASSETS` constant in `modules/out_of_context/ooc_service.py` because they are immutable across translations (Constraint #6) and version-controlled with the renderer.
