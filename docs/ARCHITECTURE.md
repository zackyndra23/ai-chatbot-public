# Architecture

## What the system is

A RAG (Retrieval-Augmented Generation) chatbot platform serving FAQ answers,
out-of-context handling, sales-meeting arrangement, and structured
service-agent flows. Serves client websites via API key + website-id auth.
Indonesian-business-hours aware (WIB / UTC+7). Runs on CUDA GPU in production,
with CPU fallback paths.

## Two entrypoints coexist (important)

This repo ships two running web apps. They serve different purposes and should
not be confused.

| Entrypoint | Framework | Purpose | Run by |
|---|---|---|---|
| `main.py` → `app` | FastAPI | FAQ ingestion endpoint + SSU scheduler + `/health` + chat_testing_ui mount | local dev (`uvicorn main:app`) |
| `modules/system_detection/chatbot.py` → `app` | Flask | The actual user-facing chatbot (`/aitegrity-core/chatbot/claude4sonnet`) + SSU blueprint + scheduler | Docker `prod`, Modal, `python -m modules.system_detection.chatbot` |

`Dockerfile.prod` and `modal_app.py` both launch the Flask chatbot. `main.py` is
primarily a dev/admin surface for FAQ + SSU manual triggers.

> ⚠️ `core/app_controller.py` mixes FastAPI `include_router` and Flask
> `register_blueprint` calls on the same object. It is not imported anywhere
> active. Treat it as legacy.

## Module map

```
modules/
├─ faq_automation/          FAQ source → chunks → Mongo → KB rebuild trigger
├─ vector_build/            Chroma KB build + atomic swap with checksum gate
├─ token_generate/          userId + sessionId issuance, APScheduler auto-deactivate
├─ chat_testing_ui/         Browser UI for QA (Flask blueprint mounted under FastAPI via WSGIMiddleware)
├─ chat_with_history/       Chat history fetch + summary/compaction for prompt building
├─ chat_payload/            Typed payload builders (string / picker / lockpicker messages, chat_turn)
├─ googlesheet_chat_history/  Optional mirror of chat logs to Google Sheets (feature-flagged)
├─ system_detection/        The chatbot orchestrator: intent, retrieval, routing, reply
│  ├─ sd_orchestrator.py    Stage 0 OOC engine — Layer A pipeline (Tasks 11-13, 20-21)
│  └─ meeting_arrangement/  Sales meeting proposal + booking flow
├─ service_agent/           Structured flows (EBS screening, quotation, handoff)
├─ out_of_context/          Stage 0 OOC engine — 14-category classifier + 5 shape renderer
│                           (cold-start + mid_flow_standard / high_stakes / pre_data + escalation_handover)
├─ i18n/                    Centralized translation loader — schema + per-lang YAML
│                           (replaces 13 scattered palette dicts; ~45 schema keys × 15 langs)
├─ abandonment/             Abandonment handler — explicit-state-clear on "never mind" / "cancel"
├─ late_response_followup/  Re-engagement job for users who went idle mid-conversation
└─ sales_slots_update/      Mongo calendar_payload → Google Sheets availability matrix
```

## Request lifecycle (chatbot happy path)

```
 Client (website / Crisp)
      │
      │ POST /aitegrity-core/chatbot/claude4sonnet
      │ Headers: x-api-key, x-website-id (optional), x-token-id (optional)
      │ Body:    { session_id, question, utilizer?, token_id? }
      ▼
 modules/system_detection/sd_controller.py
      │  1. _check_api_key()                  → 401 on mismatch
      │  2. _get_website_id_or_error()        → 400 if required + missing
      │  3. _parse_json_or_error()            → 400 on bad JSON
      │  4. _resolve_session_ids(utilizer)    → crisp vs local resolution via token lookup
      ▼
 sd_service.handle_chat(session_id, question, token_id)
      │  - Stage 0 OOC orchestrator intercept (sd_orchestrator.process_user_message_with_ooc):
      │       Step 0: abandonment check → state clear + ack (if matched)
      │       Step 1: per-turn language detection (sd_policies.detect_language_with_confidence)
      │       Step 2: effective-language resolution + fallback
      │       Step 2.5: suppression-window check (counter > 0 → dispatcher fallthrough)
      │       Step 3-6: OOCContext build → OOCService.handle(ctx) → state mutations + audit
      │  - cold-start wire at sd_service.py:5699+ (Task 20); mid-flow at :5685+ (Task 21)
      │  - non-OOC turns fall through to:
      │  - detect intent (FAQ / meeting / service-agent / OOC-legacy)
      │  - retrieve from Chroma (via sd_vector_repo)
      │  - build prompt (chat_with_history + chat_payload)
      │  - call LLM (Claude / OpenAI per ANTHROPIC_MODEL)
      │  - post-process (async summary refresh if SUMMARY_ASYNC=on)
      ▼
 sd_repo.append_chat_history_mongo() + optional GSheet mirror
      ▼
 JSON response { message, route, related_services, tokens, ... }
```

Cross-cutting:

- **FAQ updates** come via `POST /aitegrity-core/faq-automation` → `FAQService.run_pipeline` → rebuilds Chroma via `vector_build.build_and_swap` (checksum-gated).
- **Token lifecycle:** issued by `token_generate`, validated by `sd_repo.lookup_session_by_token`, auto-deactivated by APScheduler rules (idle-with-history / no-activity TTL).
- **SSU** runs on an interval scheduler inside both `main.py` and `modules/system_detection/chatbot.py`.

## Stage 0 OOC Engine (2026-05-13)

Out-of-Context (OOC) handling is now a 3-module architecture with state persistence, multi-shape rendering, and 14-category classification. Replaces the prior 2-category keyword footer pattern.

### Components

| Component | Path | Role |
|---|---|---|
| **Orchestrator (Layer A)** | `modules/system_detection/sd_orchestrator.py` | `process_user_message_with_ooc()` entry — 6-step pipeline per spec §1.1. Decoupled from chroma stack via explicit `Dispatcher` Callable injection (Tasks 11 + 20-21). |
| **OOC Module (Layer B)** | `modules/out_of_context/` | `OOCService.handle(ctx)` — classifier + renderer pipeline. 14 categories × 5 shapes (`cold_start`, `mid_flow_standard`, `mid_flow_high_stakes`, `mid_flow_pre_data`, `escalation_handover`). Legacy 2-category `maybe_handle()` preserved via `LEGACY_LABEL_MAP`. |
| **Abandonment Module** | `modules/abandonment/` | `AbandonmentHandler` — explicit state-clear on "never mind" / "udahan saja" with 3-clause `lang_hint` resolution (try hint → cross-lang fallback → false-positive risk note). |
| **i18n Loader** | `modules/i18n/` | Centralized translation registry — `schema.yaml` + per-lang `strings/{code}.yaml`. ~45 keys × 15 langs (en + id verified for Phase 2a; 13 other-lang draft from lift-and-shift). 6-state status enum (verified / draft / needs_revision / missing / stale_re_review / deprecated). |
| **Persistent state** | `modules/service_agent/sa_types.py` (extended) + `modules/service_agent/sa_repo.py` (existing) | 5 OOC fields on `AgentSessionState`: `ooc_excursion_count`, `previous_user_ooc_categories`, `previous_system_meta_actions`, `session_fallback_language`, `ooc_escalation_suppression_remaining`. Persisted via `SA_ENGINE.repo.upsert_state(state)` (`state.model_dump()`). |

### Decoupling pattern (architectural)

`sd_orchestrator.py` exists as a separate module from `sd_service.py` because the latter transitively imports `langchain_chroma` at module load (via `sd_vector_repo` + `sd_retrieval_strategies`). Tests and consumers that don't need the chroma stack should import from `sd_orchestrator.py` directly. The orchestrator depends only on `abandonment`, `out_of_context`, `i18n`, `sd_policies` (language detection helper), `core.app_audit`, `core.app_config`. Verified clean import graph (see `docs/modules/out_of_context.md` Task 11 rationale).

### Audit row taxonomy

Three new stages in `query_recording`:
- `ooc_handler` — normal OOC turn; `extras = OOCAuditMetadata.model_dump()` (~22 fields including `downstream_sd_stage=None`)
- `ooc_suppression_fallthrough` — suppression-window decrement turn; 10 fields including `downstream_route` (6-value enum) + `downstream_sd_stage` (None → "unknown" resolution at write time) + `phase0_legacy_fallback` (Phase 0 cold-start fallback marker)
- `abandonment_handler` — abandonment state-clear turn

See `docs/modules/out_of_context.md` "Audit logging" + "Audit schema — downstream_route extension" for full schemas.

### Env-flag rollback

`OOC_AGENT_ENABLED=off` switches both cold-start (`sd_service.py:5699+`) and mid-flow (`sd_service.py:5683+`) call sites back to the legacy 2-category `OOCService.maybe_handle()` path. Byte-identical to pre-Stage-0 observable behavior. Safety net before Task 23-24 production smoke verifies Stage 0 reliability.

### Phase 0 limitations + Phase 1 follow-ups

See `docs/modules/out_of_context.md`:
- "Deferred Verification (Phase 0)" ledger — 17+ smoke entries for Task 23-24 exercise
- "Known limitations (Phase 0)" — 4 limitations (Romansh partial coverage, OOC state non-persistence at cold-start, suppression-fallthrough at cold-start uses legacy fallback, last-question text English-only)
- "Phase 1 optimization opportunities" — 3 entries (pre-SA OOC classification, quotation logic consolidation, get_state round-trip)
- Spec Appendix D (`docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md`) — corrections D.1–D.7 from implementation discoveries

## Data stores

| Store | What it holds | Notes |
|---|---|---|
| **MongoDB** | `chat_history`, `qfc_service_agent`, `api_keys` (sessions + tokens), `faq_update_doc` (FAQ source chunks), `kb_registry` (Chroma build metadata), `meeting_logs`, `calendar_payload`, `ma_confirmation`, `late_response_followups`, `query_recording`, `sales_slots_log` | Single DB per deployment. Collections chosen via env keys (`*_COLL`). |
| **Chroma (persistent)** | Vector embeddings of FAQ S/Q/A chunks | Stored under `vector_data/<uuid>/`, with a stable symlink/folder `vector_data/current/` swapped atomically on rebuild. |
| **Google Sheets** | (a) FAQ source sheets (read), (b) sales-slots aggregate + individual matrices (write), (c) optional chat-history mirror | Service account auth. Either JSON inline in `GOOGLE_SERVICE_ACCOUNT` or file path. |
| **File system** | `run_logs/`, `secrets/sa.json`, `.env` | `run_logs/` is gitignored. |

## External services

- **Anthropic / OpenAI** — LLM (`ANTHROPIC_MODEL`, default `claude-sonnet-4-6`); embeddings from OpenAI `text-embedding-3-large` or HF local (`sentence-transformers/all-MiniLM-L6-v2`).
  Per-stage model override: `GRADER_MODEL` (default empty → falls back to `ANTHROPIC_MODEL`) — recommended `claude-haiku-4-5-20251001` for the `doc_grader` binary classification stage to cut costs ~5×. The grader runs N times per RAG turn (where N = `CTX_DOCS_SAME_SERVICE + CTX_DOCS_OTHER_SERVICE`, parallelized via ThreadPoolExecutor with `DOC_GRADER_PARALLEL=6` workers). See `docs/modules/system_detection/index.md` "LLM-call auditing" section.
- **Google Sheets API** — via `gspread` + service-account credentials.
- **Monday.com (via n8n webhook)** — triggered from service agent for quotation handoffs. See `MONDAY_PATH` env.
- **Calendar/meeting API** — `BOOKED_PATH_API`, `MEETING_API_BASE_URL` for sales availability + booking.
- **Modal** — optional serverless GPU deploy (`modal_app.py`, `.env.modal`).

## Deployment topology

- **Dev:** `docker-compose up` (single service `rag_chatbot`) or direct `uvicorn main:app`.
- **Prod:** GitLab CI builds a CUDA image via `Dockerfile.prod` (`runtime_cuda` stage), pushes to registry, SSH deploys to `10.30.40.155`-style hosts with `docker compose pull && up -d`.
- **Modal (optional):** `modal_app.py` wraps the Flask chatbot in a Modal WSGI function on an L4 GPU.

See [`ops/deployment.md`](ops/deployment.md) for the full deploy flow.

## Config

All env-driven config flows through `core/app_config.py` (`Config` dataclass).
Do NOT read env directly in new code — extend the dataclass and reference
`cfg.<key>`. When adding a key, mirror it in [`ops/env_reference.md`](ops/env_reference.md).

## Logging

`core/app_logging.py` sets up JSON-to-stdout logging. Level from `LOG_LEVEL`.
Meeting events use a separate `MeetingLogger` that writes to
`<MONGO_DB>.meeting_logs`.

### Prompt audit

Every LLM call across the codebase is wrapped by `core/app_audit.py`'s
`audit_llm_call` context manager (or `record_llm_call` for code paths with
pre-computed values). The wrapper writes one document per call to
`<MONGO_DB>.<QUERY_RECORDING_COLL>` (default `query_recording`) with prompt,
output, token counts, latency, model, route, stage, `session_id`,
`token_id`, plus `timestamp` (UTC ISODate, sortable/indexed) and
`timestamp_wib` (display string `"YYYY-MM-DD HH:MM:SS WIB"`, for raw shell
readability). Writes go through a bounded `ThreadPoolExecutor` in
`infra/prompt_audit_repo.py` — best-effort, fire-and-forget, never blocking
the user-facing turn. Selectable backend via `PROMPT_AUDIT_BACKEND`
(`mongo` / `noop`; `postgres` reserved). Body redaction via
`PROMPT_STORE_MODE=off` keeps metadata but nulls `llm_prompt` / `llm_output`.
Legacy `ma_repo.save_query_recording` is now a thin shim delegating to
`record_llm_call` with `kind="meeting_event"`.

## GPU / device selection

`core/gpu_config.py` picks the embedding device:

- `USE_GPU=false` → forced CPU.
- `EMBEDDING_DEVICE=cuda` and CUDA available → CUDA.
- Otherwise CPU fallback.

TF32 is enabled on Ampere GPUs (e.g. A6000) when available. See [`ops/gpu_setup.md`](ops/gpu_setup.md).

## What to read next

- Building or modifying a module → pick it from [`modules/`](modules/).
- Calling an endpoint → [`api/`](api/).
- Running or deploying → [`ops/deployment.md`](ops/deployment.md).
