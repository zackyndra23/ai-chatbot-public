# Module — `system_detection`

The chatbot orchestrator. The center of gravity for every user message —
auth, intent classification, retrieval, LLM call, persistence.

> ⚠️ **This module is large** (`sd_service.py` is ~218 KB, `sd_prompts.py`
> ~39 KB, `sd_policies.py` ~21 KB, `sd_repo.py` ~18 KB). This page is a
> skeleton. Deep sections marked **TODO** are filled in incrementally when
> those files are edited — per the documentation freshness rule.

## Submodules

- [`meeting_arrangement`](meeting_arrangement.md) — sales meeting proposal + booking flow, invoked from within system_detection.

## Purpose

Everything the chatbot does on a user turn flows through here:

1. Auth the request (API key + optional website-id).
2. Resolve session + token (local vs. Crisp utilizer).
3. Classify intent (FAQ / meeting / service-agent / OOC).
4. Retrieve relevant FAQ chunks (Chroma).
5. Call the LLM with built prompt (includes history, summary, retrieved
   context).
6. Post-process (language detection, payload shaping, async summary
   refresh).
7. Persist to Mongo `chat_history` (+ optional Google Sheet mirror).

The rest of the chatbot modules are specialist helpers called from here.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `sd_bp` | `sd_controller.py` | Flask blueprint — `POST /rag-assistant/chatbot/claude4sonnet`. |
| `create_app()` | `chatbot.py` | Flask app factory. Registers `sd_bp` + `ssu_bp`, boots vector store, starts SSU scheduler. This is the **production** entrypoint (used by Dockerfile.prod and modal). |
| `create_app()` | `chatbot_cpu.py` | CPU-only variant of the above. |
| `handle_chat(session_id, question, token_id)` | `sd_service.py` | Main orchestrator. **TODO: document branches as touched.** |
| `process_user_message_with_ooc(text, state, dispatcher, ...)` | `sd_orchestrator.py` | Stage 0 OOC Layer A orchestrator (2026-05-13). 6-step pipeline: abandonment → language detection → fallback → suppression-check → OOC dispatch. Split from `sd_service.py` to keep chroma transitive imports out of the orchestration layer. See `docs/modules/out_of_context.md` + `docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md`. |
| `bootstrap_vectorstore()` | `sd_vector_repo.py` | One-time boot of the Chroma retriever singleton. Delegates embedding construction to `sd_vector_legacy._build_embeddings`, which resolves the device via `core.gpu_config.resolve_device()` and emits a single `embeddings_provider_selected` log line (provider, model, device, batch_size) — pair with `log_gpu_status` from `chatbot.py` at startup to confirm GPU passthrough. |
| `append_chat_history_mongo(...)`, `lookup_session_by_token(...)` | `sd_repo.py` | Mongo access. |
| `*` | `sd_nodes.py` | LangGraph nodes (sanitize, intent, retrieve, etc.). |
| `*` | `sd_meeting.py` | Meeting-flow entry shim. |
| `*` | `sd_quotation.py` | Quotation-flow entry shim. |
| `*` | `sd_sa_handoff.py` | Service-agent handoff shim. |
| `*` | `sd_policies.py` | Rules, thresholds, keyword triggers. **TODO: enumerate.** |
| `*` | `sd_prompts.py` | Prompt templates. **TODO: catalog.** |
| `*` | `sd_state.py`, `sd_types.py` | Pydantic state + type hints. |

## HTTP

- `POST /rag-assistant/chatbot/claude4sonnet` — the chatbot endpoint. See [`../../api/chat.md`](../../api/chat.md).

## Controller flow

`sd_controller.chat_entrypoint()`:

1. `_check_api_key()` — 401 if missing/wrong.
2. `_get_website_id_or_error()` — 400 if required but missing.
3. `_parse_json_or_error()` — 400 if not JSON.
4. Extract `session_id`, `question`, `token_id`, `utilizer` from body.
5. `_resolve_session_ids()` — branches on `utilizer` (`local` vs `crisp`).
6. `handle_chat(session_id, question, token_id)` — main orchestrator.
7. `_persist_best_effort()` — append to Mongo chat_history (failure is logged, not raised).
8. Return JSON.

## `handle_chat` data flow (high level)

```
handle_chat(session_id, question, token_id)
    ↓
sanitize input (length, HTML, injection guards)
    ↓
detect language (LANGUAGE_DETECTOR)
    ↓
classify intent (LLM + sd_policies)
    ├─ FAQ      → retrieve via sd_vector_repo, generate reply
    ├─ meeting  → delegate to meeting_arrangement/ma_service
    ├─ service  → delegate to service_agent (via sd_sa_handoff)
    ├─ quotation→ delegate to quotation flow
    └─ OOC      → delegate to out_of_context
    ↓
build reply payload (chat_payload builders)
    ↓
async: refresh summary (if SUMMARY_ASYNC=on)
    ↓
return chat_turn dict
```

## `chatbot.py` vs `chatbot_cpu.py`

Two app factories. Differences are device-related — `chatbot_cpu.py` forces
CPU device selection and uses `sd_vector_repo_cpu` (skipping CUDA imports
entirely). Pick one based on your deployment:

| Build | Uses | Module imports |
|---|---|---|
| `Dockerfile.prod` → `runtime_cuda` | `modules.system_detection.chatbot:app` | Full stack (torch, cuda). |
| `Dockerfile.prod` → `runtime_cpu` | Same — the Flask entry is shared; devices branched inside. | Full stack, but `USE_GPU=false` drops to CPU. |
| Modal (`modal_app.py`) | `modules.system_detection.chatbot:app` | Full stack, L4 GPU. |

`chatbot_cpu.py` is a separate explicit CPU-first entry. Consider deleting if
it no longer adds value beyond env-flag-based device selection.

## Env vars

Practically everything. The most important ones here:

- **Auth:** `API_KEY`, `API_HEADER_NAME`, `WEBSITE_ID_HEADER_NAME`, `SERVICE_AGENT_API_KEY`.
- **LLM:** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `MAX_OUTPUT_TOKENS`, `LLM_TEMPERATURE`.
- **Retrieval:** `TOP_K`, `CHROMA_COLLECTION`, `VECTOR_DATA_DIR`.
- **History:** `CHAT_HISTORY_COLL`, `HISTORY_SUMMARY_MAX_*`.
- **Utilizer:** `UTILIZER_STATUS` (default `local`).
- **Trusted hosts:** `TRUSTED_HOSTS`.
- **Port:** `PORT_CHATBOT` (default 2305) for standalone runs.

Full list: [`../../ops/env_reference.md`](../../ops/env_reference.md).

## Dependencies

- Internal: every other module in this repo (this is the orchestrator).
- External: Flask, Claude SDK, langchain-chroma, pydantic, pymongo, apscheduler (indirectly via SSU).

## File map

| File | Rough size | Purpose |
|---|---|---|
| `chatbot.py` | small | Flask app factory — production entrypoint. |
| `chatbot_cpu.py` | small | CPU-only variant. |
| `sd_controller.py` | ~5 KB | `/chatbot/claude4sonnet` endpoint + helpers. |
| `sd_service.py` | ~218 KB | `handle_chat` + all orchestration. **TODO: break into subsections.** |
| `sd_prompts.py` | ~39 KB | LLM prompt templates. **TODO: catalog.** |
| `sd_policies.py` | ~21 KB | Rules, thresholds, keyword triggers. **TODO: enumerate.** |
| `sd_repo.py` | ~18 KB | Mongo access. |
| `sd_vector_repo.py` | small | Chroma retriever wrapper (CUDA-capable). |
| `sd_vector_repo_cpu.py` | small | Chroma retriever wrapper (CPU-only). |
| `sd_opener_guard.py` | small | Post-process safety net for Sentence-1 openers: `extract_opener`, `sanitize_opener`. Used inside the SA continuation block of `sd_service.py` — swaps banned/repeated openers deterministically. See [`../service_agent.md#opener-diversification-sentence-1-openers`](../service_agent.md#opener-diversification-sentence-1-openers). |
| `sd_warning_guard.py` | small | Post-process appended warning for engagement escalation. `append_invalid_warning()` translates a soft English base warning into the target language via a small `BRIEF_LLM` call, then appends it with a `\n\n` separator. Fires once every 2 cumulative invalids (see `warnings_shown` counter). Falls back to English on LLM failure. See [`../service_agent.md#engagement-escalation-two-layer`](../service_agent.md#engagement-escalation-two-layer). |
| `sd_nodes.py` | small | LangGraph nodes (sanitize/intent/retrieve/etc.). |
| `sd_meeting.py` | ~9 KB | Meeting-flow entry shim into `meeting_arrangement`. |
| `sd_quotation.py` | ~8 KB | Quotation flow entry. |
| `sd_sa_handoff.py` | ~5 KB | Handoff to `service_agent`. |
| `sd_state.py`, `sd_types.py` | tiny | Pydantic state + type hints. |
| `__init__.py` | empty | Package marker. |
| `meeting_arrangement/` | subdir | See [`meeting_arrangement.md`](meeting_arrangement.md). |

## Prompt audit instrumentation

All 18 LLM call sites in `sd_service.py` are wrapped with `audit_llm_call` from
`core.app_audit`. The wrapper is observational only — it records route, stage,
session/token IDs, prompt, response text, token counts, latency, and model to
the audit collection. It never changes application behavior and never raises.

Stage labels used in this file:

| Stage | LLM | Location |
|---|---|---|
| `history_summary` | `SUM_LLM` | `_call_llm_text_sum` |
| `already_booked_reply` | `BRIEF_LLM` | `_maybe_build_already_booked_result` |
| `route_c_compose` | `BRIEF_LLM` | `_render_sa_continue_via_sd` (completed gate) |
| `intent_type` | `ASK_LLM` | `_render_sa_continue_via_sd` (type classifier, Method A only) |
| `intent_interest` | `ASK_LLM` | `_render_sa_continue_via_sd` (interest classifier, Method A only) |
| `rag_main_reply` | `BRIEF_LLM` | `_render_sa_continue_via_sd` (main reply) |
| `qualification_b` | `SA_LLM` | `_render_sa_continue_via_sd` (Method B turn — `natural_qualification` only) |
| `qualification_b_rescue` | *(none)* | `_render_sa_continue_via_sd` (Method B deterministic rescue — zero LLM calls) |
| `reset_message` | `BRIEF_LLM` | `_render_reset_text` |
| `route_g_compose` | `BRIEF_LLM` | `handle_chat` (already-booked-in-MA warning) |
| `rag_main_reply_v2` | `BRIEF_LLM` | `handle_chat` (meeting-intent service picker — initial; route `incontext_service_validation`, picker emits `SA_SELECT_*` + `RS_OTHER_BATCH_*`, post-pick goes to SA qualification — 2026-05-18). `RS_OTHER_BATCH_*` pagination handler uses `read_chat_history_full` (not slim `read_chat_history`) so the raw picker dict is available for base-turn detection when `related_services` is empty. |
| `rag_main_reply_v3` | `BRIEF_LLM` | `handle_chat` (MA picker batch — legacy `MA_ARRANGEMENT_other_batch*` pagination; stale-session compat only after 2026-05-18) |
| `qualification_reply` | `BRIEF_LLM` | `handle_chat` (SA_SELECT reply) |
| `sa_path_1` | `BRIEF_LLM` | `handle_chat` (SA active + already-booked) |
| `sa_path_2` | `BRIEF_LLM` | `handle_chat` (SA active + pick-slot) |
| `ask_long` | `ASK_LLM` | `handle_chat` (self-introduction guard) |
| `ask_long_v2` | `ASK_LLM` | `handle_chat` (greeting guard) |
| `sa_compose` | `BRIEF_LLM` | `handle_chat` (direct SA start — 1-service) |
| `misc_compose_1` | `BRIEF_LLM` | `handle_chat` (RAG in/out-context main reply) |
| `misc_compose_2` | `BRIEF_LLM` | `handle_chat_history` |

See [`../../ARCHITECTURE.md#prompt-audit`](../../ARCHITECTURE.md#prompt-audit)
for the subsystem overview and
[`../../superpowers/specs/2026-05-06-prompt-audit-generalization-design.md`](../../superpowers/specs/2026-05-06-prompt-audit-generalization-design.md)
for the design rationale. Stages from `sd_warning_guard.py` (`warning_translate`),
`sd_policies.py` (`language_detect`), and `sd_nodes.py` (`doc_grader`) also write
to the same audit collection.

### Language detection — per-turn fresh, no lock

Each user turn is detected via Claude (`build_language_meta` in `sd_policies.py`,
default `LANGUAGE_DETECTOR=claude`). Pipeline:

1. `handle_chat` calls `build_language_meta(question)` — fresh Claude call per turn.
2. For natural input → trust this detection. Reply language follows input EACH turn.
3. For technical inputs only (`BOOK_A_MEETING`, `PICKED_SLOT_*`, picker tokens — no
   natural language to detect) → fallback to `_majority_language_from_history`
   (counts language across non-technical history turns, returns most common).
4. Detected `language_code` / `language_name` is **threaded as parameter** through
   every compose path. Notably `_render_sa_continue_via_sd` accepts `turn_language_code`
   and `turn_language_name` — these win over `state.language_code` (which is stale
   from SA flow start).
5. The `{language_name}` placeholder in `sd_prompts.py` `render_*` templates gets
   filled with the per-turn value, so the LLM sees `Target language: <X>` matching
   input language each turn.

**Removed 2026-05-07 (anti-patterns):**
- `GREETING_LANG_HINTS` regex shortcut (`sd_policies.py:73`) — returned language
  by prefix without calling Claude. Misclassified mixed input.
- `_get_locked_language_from_history` (sd_service.py) — returned first-turn
  language as override. Locked reply language across the entire conversation.

**Rule for new compose paths:** never rely on `state.language_code` as primary;
always thread per-turn detection as a parameter. See
`docs/ops/troubleshooting.md` "Reply language stuck" entry +
`feedback_language_detection` / `project_language_flow` memory.

### Doc grader — parallel + Haiku tier

`doc_grader` now runs **in parallel via ThreadPoolExecutor** (`sd_nodes.grade_and_filter_yes`
+ `_grade_one_doc`) instead of sequentially — up to `DOC_GRADER_PARALLEL=6` (env)
threads. Same number of LLM calls, but wall-clock latency drops from
sum-of-K to max-of-K. Default model for the grader is overridable via
`GRADER_MODEL` env (recommended Haiku for cost savings; binary classification
doesn't need Sonnet quality). Per-stage retrieval tuning lives in
`CTX_DOCS_SAME_SERVICE` / `CTX_DOCS_OTHER_SERVICE` (and `RETRIEVAL_K` in
`sd_policies.py` for unbiased fallback path) — `TOP_K` config field was
removed as it had zero consumers.

### Retrieval Phase 1 / Phase 2 (2026-05-07)

The chatbot has two retrieval modes, keyed by SA flow state:

**Phase 1 — generic, cross-service.** Active when `sa_state.service_label`
is not set (no `SA_SELECT_*` picker click yet for the session). Code path:
`handle_chat:5160-5171` calls `_prepare_rag_context(question)` (no
`sa_service_label` argument), which uses unbiased `retrieve_candidates`
over the whole KB. Floor = `CTX_DOCS_FLOOR` (4 by default). The query may
span multiple services; the resulting picker offers cross-service options.

**Phase 2 — service-biased, single-service.** Active after `SA_SELECT_*`
picker click writes `sa_state.service_label`. Subsequent turns flow into
the SA-active branch at `handle_chat:4909`, which calls
`_render_sa_continue_via_sd` (or, for the immediate `SA_SELECT_*` echo
turn, an inline retrieval block at `handle_chat:4645`). Both sites call
`retrieve_service_biased` directly — they do NOT route through
`_prepare_rag_context`. Both read `same_k = cfg.CTX_DOCS_SAME_SERVICE` (4)
/ `other_k = cfg.CTX_DOCS_OTHER_SERVICE` (0) so the env tweak alone
achieves Phase 2 behavior with no code change at those sites. Returns 4
docs all from the picked service.

Phase 2 is **sticky per session**: once `sa_state.service_label` is
written, every subsequent turn with that session_id stays in Phase 2
until the user starts a new session.

`_infer_service_from_query` is decoupled from retrieval bias — it only
feeds definitional FAQ pinning (`pin_def` path) inside
`_prepare_rag_context`. A fuzzy-match on the user's query no longer
silently locks Phase 1 to one service.

**Edge case — service with <4 chunks.** When biased retrieval (Phase 2)
returns fewer than 4 docs because the picked service has limited FAQs,
`_prepare_rag_context` returns those (e.g., 3) and does NOT spill over to
other-service docs. The "always 4" guarantee holds only when the picked
service has ≥4 chunks. Verified by `tests/test_retrieval_count.py::test_phase2_service_with_only_3_chunks`.

**Prompt budget interaction.** The 4-chunk Context section is sent to the
LLM by `render_incontext_prompt` (Phase 1) or the SA prompt assembler
(Phase 2). Both call `_clip(text, max_chars=cfg.INPUT_MAX_PROMPT)`. With
`INPUT_MAX_PROMPT < ~8000` and Phase 1 General-service chunks averaging
~1500 chars each, `_clip` truncates the Context section before all 4
reach the LLM. Default raised to `8000` post-2026-05-07. See
[`../../ops/env_reference.md`](../../ops/env_reference.md#L54)
under `INPUT_MAX_PROMPT`.

### Per-service vector store (Stage 3A — 2026-05-07)

The single Chroma collection has been split into N per-service collections,
one per service slug. `_vectorstores: dict[str, Chroma]` holds one client per
service; bootstrap loads them in parallel via daemon-thread `ThreadPoolExecutor`.

`KB_BACKEND` env knob switches dispatch:
- `legacy` — pre-3A behavior, single collection (rollback)
- `split` — per-service collections only (target)
- `dual` — both, per-service primary, legacy fallback (migration window)

New low-level API: `retrieve_from_collections(service_ids: list[str], query, total_k)`.
Phase 1 cross-service uses this with all loaded collections; Stage 3B (cross-service
classifier) and Stage 3C (multi-tenant filter) will pass narrower lists.

`retrieve_service_biased` keeps its public signature; internal dispatches on
`_BACKEND_MODE` and resolves alias → `service_id` slug.

Hot-reload at per-service granularity: `_vectorstores[service_id] = new_client`
swaps a single collection without Flask restart. Solves the long-standing
limitation noted in `project_kb_pipeline` memory.

See [`../../superpowers/specs/2026-05-07-stage-3a-per-service-vector-store-design.md`](../../superpowers/specs/2026-05-07-stage-3a-per-service-vector-store-design.md).

### Cross-service bridge (Stage 3B v0 — 2026-05-08)

When a user mid-qualification asks about a DIFFERENT service, the chatbot no
longer says *"informasi belum tersedia"*. Instead, it pulls FAQ chunks from
BOTH the current service's KB and the asked-about service's KB, composes a
brief answer using the combined context, and offers a stay-or-switch picker.

Flow in `handle_chat` SA-active branch:

1. `_detect_cross_service_target(user_question, current_service_code, current_service_label)`
   — strict substring match against `SA_POL.VALUE_TO_FLOW_CODE` keys and
   `SERVICE_LABEL_CODE_MAP` values. Short labels (≤4 chars) word-boundary checked
   to avoid false positives like "AST" in "fast". Returns target info or None.
2. If target detected → `_render_sa_cross_service_bridge`:
   - Fan-out retrieval via Stage 3A `retrieve_from_collections([current_id, target_id], total_k=4)`.
   - LLM call with combined context, instructing it to briefly answer the
     cross-service question + ask "stay or switch?".
   - Append picker with two choices.

**Picker value format:**
- `SA_STAY_<source_value_code>_to_<target_value_code>` — user declines switch
- `SA_SELECT_<target_value_code>` — user accepts switch
- Both values are self-documenting (parseable without DB lookup).

**Picker labels** — 14 languages via `_stay_switch_labels(language_code, current, target)`. Standard coverage applies across all picker label generators (`_book_meeting_label`, `_other_services_label`, `_stay_switch_labels`, `_stay_ack_phrase`); see `feedback_picker_label_languages` memory.

**SA_STAY click handler** — `_render_sa_stay_continuation` intercepts BEFORE
`SA_ENGINE.handle_from_question`. No LLM call. Deterministic ack from
`_stay_ack_phrase` table (14 languages) + current qualification question text.
SA state untouched. Language resolved via `_majority_language_from_history`
(not from the technical SA_STAY_* token).

**Known limitation (Stage 3B v1+ follow-up):** when user accepts switch via
`SA_SELECT_<target>`, current service's partial qualification state is
REPLACED by the new flow (existing `start_flow` behavior). Multi-service lead
preservation via `paused_services: list[dict]` + Monday/Gmail aggregation is
the next planned iteration.

See `project_stage_3b_v0_cross_service_bridge` memory for full design notes
and `feedback_picker_value_format` for the value encoding convention.

### Greeting palette — programmatic random pick (2026-05-08)

First-turn greetings are pre-selected from `_GREETING_PALETTE` in
`sd_prompts.py` via `_pick_greeting(language_code, seed)`. The picked phrase
is injected as a fixed instruction (`"Open EXACTLY with this greeting: '<x>'"`)
so the LLM defers to the chosen text instead of gravitating to one safe
phrase per language.

Coverage: 14 languages (id/ms/en/fr/de/it/pt/es/vi/th/da/zh/ja/ru), 8-12
phrases each. Adding a new language only needs an entry in `_GREETING_PALETTE`
— no other code change.

All callers of `_salutation_rule` (6 in `sd_prompts.py`, 6 in
`service_agent/sa_prompts.py`) MUST pass `language_code=language_code` —
else the picker falls back to the English palette regardless of detected
chat language.

## Gotchas

- **`core/app_controller.py` is NOT used.** It references `ssu_bp` and
  `late_response_followup_bp` via Flask-style `register_blueprint` on a
  FastAPI app (broken). The actual registration lives in
  `chatbot.py:create_app()`.
- **SSU scheduler registration** happens in `chatbot.py:create_app()` —
  if you swap entrypoints, you need to re-register it.
- **Trusted hosts** are parsed from the `TRUSTED_HOSTS` env via
  `core.app_config._parse_trusted_hosts`. Special values: `*`, `off`, `none`,
  `disabled` all disable the check. Non-host:port entries get auto-expanded
  with `:PORT_CHATBOT`.
- **Vector store bootstrap is one-shot** — `_VECTORSTORE_READY` is a module
  global that flips True on first call. Reload requires a process restart.

## Known TODOs for this doc

Update these as the corresponding files are touched:

- **Break `sd_service.py` into functional sections** — sanitization, intent,
  retrieval, reply generation, persistence. Each with its entry function,
  inputs, outputs.
- **Catalog `sd_prompts.py`** — name → template → variables → where used.
- **Enumerate `sd_policies.py`** — list thresholds + keyword triggers with
  their env-key counterparts.
- **Document `sd_nodes.py` LangGraph nodes** — one line per node:
  `sanitize_node`, `intent_node`, `retrieve_node`, etc.

## First-turn routing rule

When `first_turn` is true (no prior history for the session), `handle_chat`
**always** routes through RAG retrieval + the service-validation picker. The
self-introduction guard (`is_self_introduction`) and pure-greeting guard
(`is_greeting`) are bypassed on the first turn, even for inputs like
`"i am looking for a laptop"` or `"halo"`. This guarantees the user sees a
service-selection picker as the very first AI response, instead of being
answered conversationally.

The guard order in `sd_service.handle_chat`:

1. Meeting-arrangement (always honored)
2. SA continuation (always honored)
3. OOC agent (always honored)
4. **Self-introduction** — *only when `not first_turn`*
5. **Greeting** — *only when `not first_turn`*
6. RAG pipeline → service-validation picker (default for first turn)

## Qualification method dispatch (Stage 2026-05-12)

`_render_sa_continue_via_sd` runs a small prepend block at function entry that
routes to one of two qualification implementations based on
`state.qualification_method`:

- `two_decision_tree` (DEFAULT): existing Method A logic below the prepend
  runs unchanged (2 classifier agents per turn — `intent_type` +
  `intent_interest`). Strict-additive guarantee preserved.
- `natural_qualification` (opt-in): control delegates to
  `modules.service_agent.natural_qual.handle_turn` (1 LLM call per turn,
  deterministic rescue at `dry_count ≥ 3`, proactive picker on minimum-set +
  intent). Returns a `qualification_b`-routed payload and exits early.

Two helpers live just above the function:

- `_lock_qualification_method(state)` — reads `QUALIFICATION_METHOD` env once
  and writes to `state.qualification_method` on first dispatch. Idempotent on
  subsequent calls; protects in-flight sessions from mid-flight method
  switches when operator flips env.
- `_should_use_method_b(state)` — returns True iff
  `state.qualification_method == "natural_qualification"`.

See [`../service_agent.md#qualification-method-toggle-stage-2026-05-12`](../service_agent.md#qualification-method-toggle-stage-2026-05-12)
for the full Method B algorithm, state extensions, and policy module layout.

## Service-validation seed

When the RAG retrieval surfaces multiple candidate services (or only `General`/
nothing), the chatbot shows the user a service-selection picker. The seed text
that gets fed to the LLM as the picker preamble is now phrased as an open
question to invite engagement instead of giving a robotic instruction:

- `sd_service.py` (`service_validation_seed`): *"To help me guide you better, which service are you exploring today?"*
- `sd_sa_handoff.compose_confirm_question`:
  - **id-\***: *"Yuk, biar saya bantu lebih akurat — layanan apa yang sedang Anda cari?"*
  - **en-\***: *"To help you better, which service are you exploring today?"*

The LLM rephrases this naturally per language, but the seed sets the tone:
question-style, conversational, and aligned with the formal `Anda` rule for
Indonesian/Malay.

## Prompt personalization rules

The LLM is instructed by `_personalization_rule` in `sd_prompts.py` to:

- **Never mention the user's name in any sentence body.** The user's nickname
  is allowed only inside `_salutation_rule` on the first turn (one greeting
  with the name, e.g. *"Halo, Yudhi!"*); after that the name must not appear
  anywhere — not as a vocative, not at the start, not at the end.
- **For Indonesian (`id-*`) and Malay (`ms-*`)**, address the user with the
  formal pronoun `"Anda"`. Casual forms (`kamu`, `kau`, `lu`, `lo`, `engkau`)
  are explicitly forbidden in the prompt instruction.

The `You may use either the plain name ("{nickname}").` line that previously
sat in every prompt template body has been removed — it conflicted with the
no-name rule and caused the LLM to repeat the user's name throughout each
reply.

## Extension notes

- To add a new intent route: add classification logic in `sd_service.handle_chat`
  (or upstream LangGraph node) + a new delegate function, register the
  response payload path.
- To add a new retrieval backend: implement the same interface as
  `sd_vector_repo.py` and switch via `VECTOR_BACKEND`.
- To add a new utilizer (e.g. `whatsapp`): extend `_resolve_session_ids` in
  `sd_controller.py`.

## Anti-Redundancy & Answer Quality (2026-05-11; default flipped 2026-05-12)

Strict-additive layer for reducing within-turn and across-turn answer
redundancy. **Default is `REDUNDANCY_METHOD=mmr`** (promoted from `"normal"`
on 2026-05-12 after targeted QA — see evidence in
`qa/runs/20260512-targeted/`). `"normal"` is preserved as the byte-identical
runtime kill-switch.

Spec: [`../../superpowers/specs/2026-05-11-anti-redundancy-answer-quality-design.md`](../../superpowers/specs/2026-05-11-anti-redundancy-answer-quality-design.md).
Plan: [`../../superpowers/plans/2026-05-11-anti-redundancy-answer-quality.md`](../../superpowers/plans/2026-05-11-anti-redundancy-answer-quality.md).

### Method selector

`REDUNDANCY_METHOD` env knob picks one of:

- `mmr` (DEFAULT) — Chroma `max_marginal_relevance_search`. Strongest
  anti-repetition on FAQ-RAG path: rc_count_final=11 over 3-turn flow
  (vs 10 for fuzzy/embedding, 0 for normal); -9% latency vs normal.
- `normal` — pre-patch behavior, byte-identical. Runtime kill-switch.
- `fuzzy` — `similarity_search` + `rapidfuzz.token_set_ratio` post-filter.
  Best when redundancy is lexical (paraphrases share tokens).
- `embedding` — `similarity_search_with_score` + cosine-similarity post-filter.
  Best when redundancy is semantic (different wording, same meaning).

The dispatcher is `sd_retrieval_strategies.retrieve_with_strategy(method, ...)`;
it returns `None` for `normal` and a `list[Document]` for the three others.
All three call sites in `sd_service.py` are guarded by a one-line dispatcher
prepend.

### Module map

| File | Role |
|---|---|
| `sd_retrieval_strategies.py` | **New module.** Dispatcher contract `retrieve_with_strategy(method, query, *, scope, k, vectorstore, ctx)`. Defines `ResolutionContext` frozen dataclass + 3 resolver functions for forward-compat per-context tuning. |
| `sd_repo.py` | Two new functions: `get_recent_chunk_ids(session_id, token_id)` and `update_recent_chunk_ids(session_id, token_id, new_ids)`. Read/write a top-level `recent_chunk_ids` field on the existing `chat_history` doc (same key tuple, no extra Mongo round-trip). |
| `sd_prompts.py` | New `apply_dedup_guidelines(rendered_text, language_name)` wrapper that appends 3 anti-redundancy bullets at the end of a rendered prompt. Existing `render_*_prompt` functions UNTOUCHED. |
| `sd_service.py` | New helpers `_is_explicit_recap` (14-language regex), `_apply_recent_chunk_filter` (demote-don't-drop), `_extract_chunk_ids_from_docs`. Dispatcher guard + filter + wrapper + writeback wired at three call sites: `_prepare_rag_context` (via `handle_chat`), `_render_sa_continue_via_sd`, `_render_sa_cross_service_bridge`. |

### Recent-chunks filter (across-turn)

Active when `method != "normal"`. Per-session `recent_chunk_ids` list stored
as a sibling field on the `chat_history` doc (keyed by `sessionId, tokenId`).

- Over-fetch: `CTX_DOCS_FLOOR + REDUNDANCY_RECENT_CHUNKS_SPILLOVER` candidates.
- Partition into fresh (chunk_id ∉ recent) and stale (chunk_id ∈ recent).
- Compose final K: fresh first, then top up from stale (demoted to tail).
- Never drops below floor.
- After turn renders, append actually-used chunk IDs (cap = window × floor).

### Explicit-recap bypass

`_is_explicit_recap(question, language_code)` matches "say that again" /
"ulangi" / etc. in 14 languages: id, ms, en, fr, de, it, pt, es, vi, th, da,
zh, ja, ru (English fallback for unknown codes). Word-boundary regex per
language to avoid false positives like Indonesian "berulang".

When true: the filter is skipped AND `recent_chunk_ids` is NOT updated this
turn — user explicitly wanted what was already shown.

### Prompt-template wrapper

`sd_prompts.apply_dedup_guidelines` appends 3 anti-redundancy bullets to the
END of an already-rendered prompt. Applied only when `method != "normal"`.
Existing `render_*_prompt` functions remain byte-identical for the normal path.

### Forward-compat resolver hooks

`ResolutionContext` dataclass (in `sd_retrieval_strategies.py`) carries
`service_id`, `tenant_id`, plus reserved slots for `channel_id`,
`user_segment`, `time_of_day_utc_hour`. Three resolver functions accept
`ctx: ResolutionContext` and return the strategy param (λ / threshold).
v0 implementation ignores `ctx` and returns the global cfg value;
Stage 3C+ can swap in per-tenant / per-service lookups without changing
call-site signatures.

### Observability

Every retrieval-touching turn logs `retrieval_method` to:
- `query_recording.extras.retrieval_method` (audit row).
- `chat_history.chat_history[].extra.retrieval_method` (per-turn payload).

Including `normal` value — enables future "how many turns used the default
this week" analyses without code change.

### Eval harness

`tests/eval_redundancy_diversity.py` — manual exploration CLI:

```
python tests/eval_redundancy_diversity.py --method <normal|mmr|fuzzy|embedding>
```

Prints a per-question table across 10 hand-labeled questions: top-4 chunks,
distinct Q-stems count, distinct services count, expected-service-present
flag. Not a CI gate; exit code is always 0. Useful for tuning
`REDUNDANCY_MMR_LAMBDA` / `REDUNDANCY_FUZZY_THRESHOLD` /
`REDUNDANCY_EMBEDDING_THRESHOLD` per method.

## Naming policy (2026-05-13)

The chatbot has **no finalized production name**. Prompts in
`sd_prompts.py` (and every other prompt-bearing module) must refer to
the assistant generically — first-person "I" / "we", or "the chatbot" /
"the assistant" when third-person reference is needed. Do NOT introduce
a product name in prompts (system, human, or examples) until the name is
finalized via product decision.

Historical references to a prior working name were removed from
`sd_prompts.py` on 2026-05-13 (1 active guardrail line + 7 commented-out
historical blocks). Any future addition of a persona name must go
through explicit product approval, not be reintroduced via prompt drift.
