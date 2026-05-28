# Module — `service_agent`

Structured multi-step service flows — Employment Background Screening (EBS),
quotation, handoff. The "form-wizard" side of the chatbot.

> ⚠️ **This module is large** (`sa_flows.py` is ~132 KB, `sa_prompts.py` is
> ~34 KB, `sa_service.py` is ~20 KB). This page is a skeleton. Deep sections
> marked **TODO** are filled in incrementally when those files are edited —
> per the documentation freshness rule.

## Purpose

Handle structured conversational flows that aren't open-ended RAG Q&A. These
are typically picker-driven: user clicks a choice, chatbot responds with the
next step's picker, etc. Used for EBS intake, quotation requests, and
handoff to human agents.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `sa_bp` | `sa_controller.py` | Flask blueprint — exposes `POST /aitegrity-core/chatbot/claude4sonnet/service-agent`. |
| `INTAgentService(repo)` | `sa_service.py` | Orchestration. Key method: `handle_from_question(session_id, raw_question)`. |
| `ServiceAgentRepo(mongo_client)` | `sa_repo.py` | Mongo access. |
| `*` | `sa_flows.py` | Flow definitions. `FLOW_REGISTRY` has **15 service codes** (2026-05-18): `EBS, DDC, MSG, AST, WBS, FRI, MSY, SKT, CMI, NUI, ACI, PTI, ABMS, KYC, CLI`. Each is built by a `build_<svc>_flow()` function returning `dict[str, QuestionStep]`. Service-code semantics in this file are authoritative — note that `CMI` is **Trademark Investigation** (`service_label="Trademark Investigation"`), `ACI` is **Anti-Counterfeiting**, `CLI` is **Claim Investigation** (FAQ pipeline metadata tag is `"Insurance Investigation"` — see `_DB_ALIAS_OVERRIDES` in `sd_service.py`). Each flow has 15 active questions traversed via `default_next` chain; 3 categories are intentionally commented out (Y/N Context Confirmation gate, Budget question, Contact details — handled by orchestrator classifier and CRISP form respectively). |
| `render_serviceagent_prompt_01`, `render_serviceagent_continue_prompt`, `render_serviceagent_continue_question_prompt`, `render_serviceagent_continue_answerquestion_prompt`, `render_serviceagent_postgate_prompt`, `render_serviceagent_prompt_final`, `_opener_guidance_block`, `_no_echo_and_advance_guidance_block`, `_engagement_nudge_block` | `sa_prompts.py` | LLM prompt templates + shared Sentence-1 opener, no-echo/sales-consultant, and engagement-nudge helpers. **TODO: catalog remaining prompts when touched.** |
| `*` | `sa_policies.py` | Rules/thresholds for flow routing. |
| `AgentSessionState` (Pydantic) | `sa_types.py` | Session state persisted via `ServiceAgentRepo.upsert_state`. Fields: `session_id`, `service_code`, `service_label`, `question_id`, `answers`, `status`, `language_code`, `language_name`, `dual_agent_meta`, `recent_openers`. |
| `SA_DTO` | `sa_dto.py` | Data transfer objects. |

## Opener diversification (Sentence-1 openers)

### Why it exists

In qualification flows the assistant has a strong tendency to start every
reply with the same polite acknowledgment (e.g. `"Baik, ..."` in Indonesian).
After 3–4 turns this reads as robotic. The fix is two cooperating layers:

1. **Prompt layer** — `sa_prompts._opener_guidance_block(language_code, language_name, recent_openers)` injects into every qualification-flow prompt:
   - A curated opener palette in the target language (10 languages pre-populated: `id`, `en`, `ms`, `fr`, `de`, `th`, `ru`, `zh`, `it`, `ja`).
   - A language-specific banned list (`"Baik"`/`"Baiklah"` for `id-*`).
   - A dynamic ban of the last ≤3 openers used this session (via `recent_openers`).
   - Permission for the LLM to skip the opener entirely (~40% of turns).
2. **Runtime layer** — `modules/system_detection/sd_opener_guard.sanitize_opener` runs *after* the LLM reply. If the returned opener is banned or matches the most-recent one, it's **replaced** (not stripped) with the next unused palette entry — deterministic, no second LLM call. The resulting opener is pushed into `AgentSessionState.recent_openers` (kept at last 3) and persisted via `ServiceAgentRepo.upsert_state`.

### Which prompts use it

Every qualification-flow prompt in `sa_prompts.py` that has a Sentence-1 rule:

- `render_serviceagent_prompt_01` (first turn of a flow)
- `render_serviceagent_continue_prompt` (answer_only continuation)
- `render_serviceagent_continue_question_prompt` (clarification question path)
- `render_serviceagent_continue_answerquestion_prompt` (answer + new question path)
- `render_serviceagent_postgate_prompt` (post-gate continuation)

All accept an optional `recent_openers: list[str] | None` kwarg.

### Where the safety net runs

`modules/system_detection/sd_service.py`, inside the SA continuation block
(around L1656–L1830). The flow is:

```
_recent_openers = list(getattr(state2, "recent_openers", []) or [])
                        ↓
render_serviceagent_<variant>(..., recent_openers=_recent_openers)
                        ↓
msg = BRIEF_LLM.invoke([SystemMessage(content=rendered_prompt), ...])
text = normalize_single_paragraph(msg.content)
                        ↓
text = sanitize_opener(text, _recent_openers, language_code)
new_opener = extract_opener(text)
if new_opener:
    state_fresh = SA_ENGINE.repo.get_state(session_id)
    state_fresh.recent_openers = (_recent_openers + [new_opener])[-3:]
    SA_ENGINE.repo.upsert_state(state_fresh)
```

### Extending the palette

Add a language-code-prefix key to `_OPENER_PALETTE` in `sa_prompts.py`. Keep
each language's palette to 8–13 entries. Order matters — `_pick_replacement`
walks the list and picks the first entry not in `recent_openers`, so put the
most natural openers first.

If a language has a specific "default bland" opener to ban (like `"Baik"` in
Indonesian), add it to `_BANNED_OPENERS_BY_LANG`.

## Engagement escalation (two-layer)

When the dual-agent classifier marks user answers as `not_interest`
(`invalid_count` increments), the assistant does NOT halt qualification and
does NOT show a closing wrap-up. Instead it escalates via two cooperating
layers that fire **every 2 cumulative invalid answers**, controlled by a
`warnings_shown` counter in `dual_agent_meta`.

### Trigger formula

```
should_warn = (invalid_count - 2 * warnings_shown) >= 2
```

- `invalid_count` is **monotonic** — grows without bound across the session.
- `warnings_shown` increments each time the warning layers fire and a
  warning actually landed in the user-visible reply.
- Effect: warning fires at cumulative invalids of 2, 4, 6, 8, … regardless
  of valid answers mixed in between.

### Layer 1 — in-prompt soft nudge (subtle)

`_engagement_nudge_block(language_name)` in `sa_prompts.py`. Injected into
every qualification-flow prompt via the `engagement_nudge: bool = False`
kwarg on the four continuation renderers. The LLM is told to weave a warm,
non-judgmental acknowledgment into ONE of the sentences ("I want to make
sure I understand your needs correctly") — no structural change to the
reply. Subtle — the user reads it as part of the normal qualification
response.

### Layer 2 — post-process appended warning (more visible)

`modules/system_detection/sd_warning_guard.py` appends a blank-line
separated warning block (`\n\n` then warning text) to the assistant's
reply after it returns from `BRIEF_LLM.invoke`. The warning text is
**translated by a small LLM call** (same `BRIEF_LLM`) from a base English
template, so the wording sounds natural in whichever language the user is
using (id/en/ms/fr/de/th/ru/zh/ja/it and beyond — no hardcoded per-language
templates). Falls back to the English base on any LLM failure.

Both layers fire on the same turn at `should_warn = True`. The in-prompt
nudge reinforces softness; the appended block gives the user a more visible
signal that the conversation flagged something.

### Meeting_arrangement is no longer coupled to invalid_count

A previous bug auto-set `ia["meeting_arrangement"] = bool(invalid_count >= 2)`
at the bottom of the dual-agent classifier step in `sd_service.py`. That
line is removed. `advance` decision for qualification is now just
`bool(ia["next_question"] is True)` — qualification always progresses on
every turn. `meeting_arrangement` in `dual_agent_meta` is left as a
False-by-default flag; meeting intent routing happens upstream (keyword /
LLM detection before SA is entered), not inside the SA classifier step.

### Wiring (runtime)

```python
# in sd_service.py, SA continuation block
_warnings_shown = int(ia2.get("warnings_shown", 0) or 0)
_should_warn   = (invalid - 2 * _warnings_shown) >= 2
_engagement_nudge = _should_warn          # Layer 1 (prompt-side)
# ... pass engagement_nudge=_engagement_nudge to the renderer ...

text = normalize_single_paragraph(msg.content)
text = sanitize_opener(text, _recent_openers, language_code)

# Layer 2 (post-process append) — LLM-translated soft warning
if _should_warn and not is_final_gate:
    text = append_invalid_warning(
        text, llm=BRIEF_LLM,
        language_code=language_code, language_name=language_name,
    )
    _warning_appended = True

# Consolidated persistence — bumps warnings_shown by 1 when warning landed
```

### Meeting picker (BOOK_A_MEETING)

Still appears, but only in two situations:

- **Explicit meeting intent** — when `ia["meeting_arrangement"]` is True
  (set by upstream detection, not by invalid_count). Triggers the
  `render_serviceagent_prompt_final` path with a BOOK_A_MEETING-only picker
  (START_NEW_CHAT was removed from `_final_gate_choices`).
- **Cadence-based popup** — the existing `MEETING_POPUP` env knob. When
  `MEETING_POPUP=2`, the BOOK_A_MEETING picker appears alongside the normal
  qualification reply at questions 2, 4, 6, 8, … — **once per step**. If the
  user asks clarifications or stays on the same step across multiple turns,
  the picker does NOT re-render; `popup_shown_steps` in `dual_agent_meta`
  tracks which step indices have already had the popup.

`invalid_count` alone NEVER shows a picker — only the soft nudge + appended
warning.

### State persistence note

There's a dead-write gotcha: `SA_ENGINE.commit_turn` runs **before** the
final reply is composed in `sd_service.py`, so any mutations to
`state2.dual_agent_meta` or `state2.recent_openers` after that don't survive
to the next turn on their own. A consolidated persistence block near the end
of the SA continuation path (look for `_needs_persist` in `sd_service.py`)
re-upserts state with the latest values of `recent_openers`,
`warnings_shown`, `gate_shown`, and `popup_shown_steps` when any of them
changed this turn. **When adding a new session-scoped flag, extend that
block — or the flag will not persist.**

### Junk-data filter on `answers` write (2026-05-08)

`commit_turn` (`sa_service.py:251`) gates the `state.answers[key]` write on
`dual_agent_meta.type ∈ {answer_only, answer_and_question}`. When the
classifier marks user input as `question_only` (e.g. user asks about another
service mid-flow: *"saya juga tertarik dengan EBS, bisa dijelaskan?"*), the
text is NOT committed to the current qualification field. Pre-fix this
polluted leads with non-answer content like
`wbs_user_eligibility: "saya juga tertarik dengan EBS..."`.

Anti-loop force-advance behavior is unchanged: when the user keeps asking
twice in a row, the flow still advances to the next question (per
`dual_agent_meta.next_question`). The fix only affects what gets written
into `answers` — junk no longer pollutes the lead, and skipped questions
remain empty so sales agents see the gap and can follow up.

`dual_agent_meta` itself is still persisted on every turn (it's diagnostic
state, not lead data), so question-class telemetry remains available for
later analysis.

### Cross-service bridge interaction (Stage 3B v0 — 2026-05-08)

When a user mid-qualification mentions a DIFFERENT service explicitly (e.g.,
asking about EBS while in WBS flow), the dispatch in
`sd_service.handle_chat` routes BEFORE `SA_ENGINE.handle_from_question` to a
new `_render_sa_cross_service_bridge` handler. Bridge answers the user using
combined-context retrieval (current + target service) and returns a
stay/switch picker.

If user clicks `SA_STAY_<source>_to_<target>`, a separate handler
`_render_sa_stay_continuation` re-asks the current qualification question
WITHOUT going through `SA_ENGINE.commit_turn` — SA state is untouched, no
classifier call, no answer write. Language resolved via
`_majority_language_from_history` to avoid the `SA_STAY_*` token being
naively detected as English.

If user clicks `SA_SELECT_<target>`, the existing `start_flow` path runs
which REPLACES current SA state with the new service's flow. Multi-service
preservation (`paused_services` array + sales report aggregation) is the
v1+ follow-up.

See [`../superpowers/specs/2026-05-11-stage-3b-v0-cross-service-bridge-design.md`](../superpowers/specs/2026-05-11-stage-3b-v0-cross-service-bridge-design.md) for full retrospective design.

## HTTP

- `POST /aitegrity-core/chatbot/claude4sonnet/service-agent` — see [`../api/chat.md`](../api/chat.md#service-agent).

Auth: `x-service-agent-api-key` (different from the main chatbot's key).

## Entry pattern

Flows are entered via a "picker" `raw_question`:

- `PICKER_Employment_Background_Screening` → start EBS flow.
- `PICKER_EBS_STEP1_...` → continue EBS flow.
- Free text at a step → handled by the per-step prompt.

`INTAgentService.handle_from_question` branches on the `raw_question` prefix
and returns the next `chat_turn` payload.

## Data flow (skeleton)

```
POST /service-agent
  { session_id, question }
    ↓
auth: _check_sa_key()  (SERVICE_AGENT_API_KEY)
    ↓
INTAgentService.handle_from_question(session_id, raw_question)
  ├─ resolve current flow state (via ServiceAgentRepo)
  ├─ branch on picker value / free text
  ├─ call flow implementation (sa_flows.*)
  ├─ build reply payload (chat_payload builders)
  └─ persist state + append to SA_HISTORY_COLL
    ↓
200 { message, route: "service_agent", ... }
```

## Env vars

| Key | Purpose |
|---|---|
| `SERVICE_AGENT_API_KEY` | Endpoint auth. |
| `SERVICE_AGENT_API_HEADER_NAME` | Header name. |
| `SA_HISTORY_COLL` | Mongo collection for SA flow history (default `qfc_service_agent`). |
| `MONDAY_PATH`, `MONDAY_KEY`, `MONDAY_VALUE`, `BOARD_ID`, `TOPICS` | Handoff-to-Monday.com via n8n webhook. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `LLM_TEMPERATURE` | LLM for prompt-driven steps. |

## Dependencies

- Internal: `core/app_config.py`, `infra/app_repo.get_mongo_client`, `modules/chat_payload`.
- External: Claude SDK, `pymongo`, Flask, `requests` (for Monday handoff webhook).

## File map

| File | Rough size | Purpose |
|---|---|---|
| `sa_controller.py` | small | Flask blueprint + auth guard. |
| `sa_service.py` | ~20 KB | `INTAgentService` — orchestration. **TODO: document methods.** |
| `sa_flows.py` | ~132 KB | Per-flow implementations (EBS, quotation, handoff). **TODO: document flows one at a time as touched.** |
| `sa_prompts.py` | ~34 KB | Prompt templates for LLM-driven steps. **TODO: catalog prompts when edited.** |
| `sa_policies.py` | small | Decision thresholds. |
| `sa_repo.py` | small | Mongo access wrapper. |
| `sa_dto.py` | small | DTOs. |
| `sa_types.py` | small | Typed records. |

## Gotchas

- A `SA_ENGINE` singleton is constructed at import time in `sa_controller.py`
  — errors on Mongo connection will surface as import errors, not request
  errors. Keep Mongo connectivity reliable at boot.
- The controller imports `infra.app_repo.get_mongo_client` which creates a
  lazy singleton — shared with other modules.
- `sa_bp` is currently NOT registered in `modules/system_detection/chatbot.py`
  (the registration line is commented out). If you need the service-agent
  endpoint exposed, uncomment `app.register_blueprint(sa_bp)`.
- Picker values are string-typed (`PICKER_XXX`). Typos silently fall through
  to the default handler.

## Known TODOs for this doc

Update these sections as the corresponding files are edited:

- **Enumerate public functions/classes of `sa_flows.py`** — one per flow
  (EBS intake, quotation, handoff). Each with: entry picker, steps,
  terminal payload.
- **Catalog prompt templates in `sa_prompts.py`** — which ones are used at
  which flow step, and what variables they inject.
- **Document `INTAgentService` methods** — `handle_from_question`, plus any
  private routing helpers.

## Extension notes

- Adding a new flow: add a new handler in `sa_flows.py`, a new picker value
  prefix, a route in `INTAgentService.handle_from_question`, and prompts in
  `sa_prompts.py` if LLM-assisted.
- Changing handoff target (Monday → something else): replace the webhook
  call site in `sa_flows.py` and the env keys in `sa_policies.py`.

## Qualification Method Toggle (Stage 2026-05-12)

Two qualification methods coexist behind the `QUALIFICATION_METHOD` env knob:

### Method A: `two_decision_tree` (DEFAULT)

The existing flow — strict-additive preserved. Per qualification turn,
`_render_sa_continue_via_sd` runs:
- **Agent 1 (`stage="intent_type"`)**: classifies user reply as
  `question_only` / `answer_only` / `answer_and_question`.
- **Agent 2 (`stage="intent_interest"`)**: classifies the answer as
  valid / invalid / uninterested.
- `commit_turn` writes the user's answer gated on
  `dual_agent_meta.type ∈ {answer_only, answer_and_question}`.
- `MEETING_POPUP=N` env gates the picker every N qualification questions.
- Independent: `sd_meeting.is_meeting_request` keyword detection (11 langs)
  fires the picker on explicit user requests.

### Method B: `natural_qualification` (opt-in, Stage 2026-05-12)

Single-agent natural-conversation collector. See full design in
`docs/superpowers/specs/2026-05-12-qualification-method-toggle-design.md`.

Key properties:

- **Same field set** as Method A — uses `FLOW_REGISTRY[service_code]`
  unchanged. Lead data shape is identical.
- **One LLM call per turn** vs Method A's two. Latency expected lower except
  when rescue path fires (deterministic, zero LLM calls).
- **Minimum-set picker trigger**: when 3 fields (user_role,
  main_objective, company_profile) are collected AND agent's intent_score
  reads medium/high AND 2-turn cooldown is clear, picker is offered
  proactively. Existing keyword-trigger path remains active.
- **Anti-loop rescue**: when `dry_count[X] ≥ 3` for any min-set field X,
  next turn uses verbatim FLOW_REGISTRY text wrapped in soft-bridge phrasing
  (14-language template, English fallback). No LLM call on rescue turns. If
  rescue still fails to collect, field is added to
  `state.fallback_skipped_fields` (sales sees this in lead profile).
- **Method lock per session**: at first call to `_render_sa_continue_via_sd`
  where `state.qualification_method is None`, env is read once and persisted
  to state. Subsequent turns honor stored value — in-flight sessions stay
  on whichever method they started with.
- **`MEETING_POPUP=N` cadence (2026-05-18)**: Method B now respects the same
  cadence env as Method A. After each turn's writes are applied, the
  orchestrator counts filled flow answers and fires the BOOK_A_MEETING
  picker when `answered_count % MEETING_POPUP == 0` and that milestone is
  not already in `state.popup_shown_counts`. Cadence is OR'd with the
  existing keyword / min-set+intent triggers (any one of them firing → show
  picker). Suppressed when `interest_signal == "not_interested"`. The
  Method B dispatcher (`sd_service.py:_render_sa_continue_via_sd` Method B
  branch) renders a real picker message containing `_book_meeting_choice`
  whenever `turn_result["picker_offered"]` is True — previously the
  message was always plain string and the picker flag only landed in audit.
- **`prompt_applied` audit (2026-05-18)**: `nq_orchestrator.handle_turn`
  returns the actual rendered prompt under key `"prompt_applied"`:
  - Normal turn → full `render_prompt(ctx)` output
  - Verbatim-retry turn → `prompt_text + addendum` (the prompt that was
    actually sent to the LLM on retry)
  - Rescue turn (no LLM) → explicit marker
    `"(no LLM — Method B rescue: <field_name>)"`
  Caller in `sd_service.py:_render_sa_continue_via_sd` wires this into the
  `qualification_b` payload's `prompt_applied` field for parity with Method
  A (which already logged the rendered prompt). Fallback string when key
  missing: `"(no LLM — Method B)"`.

### Module layout (Method B)

| File | Role |
|---|---|
| `modules/service_agent/natural_qual/__init__.py` | Public API: `handle_turn` |
| `nq_orchestrator.py` | 10-step per-turn algorithm (the entry point) |
| `nq_agent.py` | LLM call + structured JSON output parsing |
| `nq_policies.py` | `RESCUE_SOFT_BRIDGE` templates, `compute_picker_decision`, `update_dry_count` |
| `nq_minset.py` | `MIN_SET_PER_FLOW` + suffix-priority resolver |

### State extensions (`AgentSessionState`)

7 new optional fields on `AgentSessionState` (in `sa_types.py`):
- `qualification_method: Literal["two_decision_tree", "natural_qualification"] | None`
- `turn_index: int = 0`
- `dry_count: dict[str, int]` (frozen-not-reset semantics)
- `rescue_attempted: set[str]`
- `fallback_skipped_fields: list[str]`
- `last_intent_score: str | None`
- `last_picker_offer_turn: int | None`

All default to safe values — legacy session docs without these fields are
treated as Method A (`qualification_method=None → "two_decision_tree"`).

### Minimum-set per-flow declaration

10 of 13 flows follow the canonical convention (resolved by `nq_minset.resolve_min_set`
via suffix priority: `_user_role`, `_main_objective`, `_client_company_profile` /
`_company_profile`). 3 flows have explicit overrides for confirmed semantic gaps:

- **WBS**: no buyer-role field — uses `wbs_case_handlers` (closest
  decision-maker-adjacent slot: Compliance/HR/Legal team).
- **EBS**: no main_objective active field — uses `ebs_project_type` (one-shot
  vs ongoing).
- (`*_company_profile` vs `*_client_company_profile` naming variants treated
  as semantically equivalent.)

Contact details deliberately NOT in min-set — `*_contact_details` is commented
out across all 13 flows; contact info is handled by Crisp session profile +
the downstream meeting booking step. Crisp contact existence is fed to Method
B agent as an **intent signal** (`crisp_contact_present: true|false`), not as
a min-set gate.

### Observability

Method B writes one audit row per turn to `query_recording`:
- `stage="qualification_b"` for normal agent turns
- `stage="qualification_b_rescue"` for deterministic rescue turns

Extras include: `method`, `target_field`, `intent_score`,
`dry_count_snapshot`, `rescue_attempted_snapshot`, `picker_offered`,
`picker_offer_reason`, `intent_score_at_offer`, `crisp_contact_present`,
`fallback_skipped_added`, `llm_error`, `llm_error_type`, plus
`retrieval_method` inherited from Stage 2026-05-11 anti-redundancy.

`picker_offer_reason` taxonomy: `keyword_explicit` | `keyword_implicit` |
`min_set_intent_medium` | `min_set_intent_high` | `cooldown_blocked` | `none`.

### Audit methodology principle

All cross-flow field verification (e.g., min-set resolution, regression
checks) MUST use runtime `FLOW_REGISTRY` introspection — NOT static regex
on `sa_flows.py`. The source file contains commented-out declarations that
static grep counts as active; runtime introspection automatically filters
these out. Established during Stage 4 brainstorming (2026-05-12).

### Stage 4.5 — Method B Behavior Tightening (2026-05-12)

Spec: `docs/superpowers/specs/2026-05-12-stage-4-5-method-b-behavior-tightening.md`

Three behaviors layered on top of Stage 4's `natural_qualification` (Method B):

1. **Interest signal classification (4-way)**: agent emits a new
   `interest_signal` field in the output JSON with one of
   `interest_answer | not_interested | question | off_topic`. Branches
   behavior per class — `not_interested` triggers slow-down (no
   field_writes, no question this turn). Parse-layer enforces 3 consistency
   invariants:
   - unknown values normalize to `"interest_answer"` + warning
   - `interest_signal == "off_topic"` ↔ `off_topic_detected == True`
   - `interest_signal == "not_interested"` → `intent_score == "low"`

2. **History recall with verbatim allow-list**: orchestrator now fetches
   `recent_history` via `sd_repo.read_chat_history(limit=12)` and passes
   it through to the agent's prompt (the `recent_history=[]` hardcode
   from Stage 4 is fixed). Agent may commit `field_writes` from history
   mention — but values MUST be verbatim (case-insensitive substring of
   user messages). A retry-once layer + final-drop layer enforce this in
   `nq_orchestrator.handle_turn`. `_format_history_block` slice
   `[-4:]` was removed (window size now controlled at the
   `read_chat_history` call site only).

3. **Off-topic 3-paragraph structure**: when `interest_signal ==
   "off_topic"`, the agent's `message` MUST contain exactly 3 paragraphs
   separated by `\n\n`: ack → bridge → next-question. Orchestrator
   passes the message through unchanged. Picker emission stays
   independent of message format.

**State extensions**: `AgentSessionState.last_interest_signal: Optional[str]`
(parallel to `last_intent_score`, telemetry only).

**Audit row extras** added under existing `qualification_b` /
`qualification_b_rescue` stages:
- `interest_signal: str`
- `verbatim_retry_fired: bool`
- `field_writes_sources: {field_name: "current_message" | "history"}`
- `consistency_warns_count: int`

**Strict-additive guarantee**: `nq_minset.py`, `nq_policies.py`, and the
Method A code path in `sd_service.py` are untouched. Picker decision still
reads `intent_score ∈ {medium, high}` — Stage 4.5 does not change picker
gating logic. All 44 Stage 4 tests pass post-patch (with 1 fixture line
adjustment in `test_user_volunteers_skipped_field_removes_from_skip_list`
to make its mock value verbatim-compatible).

#### Post-implementation BSON fix (2026-05-12)

Stage 4 + 4.5 originally declared `rescue_attempted: set[str] = set()` on
`AgentSessionState` (`sa_types.py:78`). MongoDB BSON cannot encode Python
`set` type, so the first state upsert raised `bson.errors.InvalidDocument`
and every new session returned HTTP 500. Fixed by changing the field to
`List[str]` + replacing set-specific operations in `nq_orchestrator.py`
(`.add` → `.append` with idempotency guard, `.discard` → `if x in list:
list.remove(x)`). Three BSON round-trip regression tests added to
`tests/test_state_extensions.py::TestStateBSONSerializable` to lock in
the contract for any future state field type addition.

#### Dispatcher audit propagation patch (2026-05-12)

Stage 4 dispatcher (`sd_service.py:2228`) emitted Method B chat_history
`extra` with Stage 4 fields only — Stage 4.5's new audit fields from the
orchestrator return dict (`interest_signal`, `verbatim_retry_fired`,
`field_writes_sources`, `consistency_warns_count`, `fields_written`,
`dry_count_snapshot`) were not propagated. Added 6 lines to the
dispatcher's `extra={...}` dict to forward these from `turn_result`.
Without this patch the Stage 4.5 behavioral metrics would be invisible
to audit consumers despite the orchestrator computing them correctly.

#### Validation outcome (2026-05-12)

Stage 4.5 was validated via 4 paired sessions (Method A vs Method B,
identical user scripts, 4 scenarios × 2 languages × 3 services). Result:
**PROCEED to Phase 2** (n≥20 sessions for statistical confidence). Per
G1 pre-registered thresholds — 2/2 measurable win metrics PASS
(Q1 Naturalness Δ=+2.25, Turn-to-picker intent-aware PASS) and 5/5
safety metrics PASS (re-ask 0 vs 8, Q2 off-topic recovery Δ=+3.00,
LLM failure 0%, estimated cost B ≤ 1.1×A, latency p95 in tolerance).

**Deliverables** at `qa/runs/stage4_validation/`:
- `qualificationtest_120526_16h45.xlsx` — 7-tab stakeholder report with
  Tab 6 Performance fully audit-derived (and caveat-tagged where
  estimation is used)
- `known_bugs.md` — Bug #1 (Method A state persist gap), Bug #2 (Method
  B audit telemetry gap), Bug #3 (Haiku doc_grader tokens hardcoded
  zero); cleanup-pass priority order
- `transcripts_S1-S4.txt` — rateable surface, AI-assisted rating
  methodology documented in Tab 7
- `gen_excel.py` — regenerator script with all data + ratings inline

**Default switch decision**: deferred to post-Phase-2. Current
production setting `QUALIFICATION_METHOD=natural_qualification` is for
testing phase only. Pre-Phase-2 cleanup pass should fix Bug #2/#3 to
enable rigorous cost reconciliation before scale-up.

## OOC state extensions (2026-05-13)

Five optional fields added to `AgentSessionState` for the OOC engine. See
`docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md` §7.1 + §7.2.

| Field | Type | Default | Purpose |
|---|---|---|---|
| `ooc_excursion_count` | `int ≥ 0` | `0` | Consecutive-OOC streak counter; resets on non-OOC turn |
| `previous_user_ooc_categories` | `list[str]` | `[]` | Categories accumulated during streak; resets on non-OOC turn |
| `previous_system_meta_actions` | `list[str]` | `[]` | System-meta actions (e.g., `ESCALATION-CONSECUTIVE-OOC`); resets on non-OOC turn |
| `session_fallback_language` | `str` | `"en"` | Last confidently-detected language for re-fallback |
| `ooc_escalation_suppression_remaining` | `int ≥ 0` | `0` | Per-user-message countdown after escalation; suppresses OOC classifier during the window |

Strict-additive (all-default) so legacy Mongo documents deserialize cleanly
without migration. The `qualification_method` field added in Stage 2026-05-12
(`Optional[Literal["two_decision_tree", "natural_qualification"]]`) is the prior
reference for additive evolution of this dataclass.
