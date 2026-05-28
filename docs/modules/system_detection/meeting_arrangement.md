# Submodule — `system_detection/meeting_arrangement`

Sales meeting proposal, slot picking, and booking flow. Entered from the main
chatbot when intent classification routes to meeting, or from an explicit
picker.

## Purpose

Lead the user through:

1. Detect intent to book a meeting (via keyword triggers / classifier).
2. Select a candidate sales person based on coverage + availability.
3. Propose `DAYS_PROPOSAL` days of slots.
4. Confirm the user's chosen slot.
5. Book atomically against Mongo (`ma_confirmation`) and the external calendar API.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `ma_controller.*` | `ma_controller.py` | Optional dedicated endpoints (start / propose / confirm). May or may not be registered. |
| `ma_service.*` | `ma_service.py` | Orchestration: parse → pick sales → compose reply. |
| `ma_policies.*` | `ma_policies.py` | Rules: trigger keywords, working-hours windows, lunch breaks, fairness. |
| `ma_prompts.*` | `ma_prompts.py` | LLM prompts for start / propose / confirm / reschedule. |
| `ma_repo.*` | `ma_repo.py` | Mongo access: `sales_profiles`, `sales_slots`, atomic `ma_confirmation` write. |
| `ma_utils.*` | `ma_utils.py` | WIB parse/format, window validation, fairness helpers. |
| `ma_types.*` | `ma_types.py` | Pydantic/TypedDict: `Slot`, `Proposal`, `Candidate`, `Booking`. |

## Data flow

```
user message classified as "meeting" in sd_service
    ↓
sd_meeting.py entry shim
    ↓
ma_service.handle(session_id, user_text, state)
  ├─ parse desired date/time (ma_utils + LLM via ma_prompts)
  ├─ pick candidate sales (ma_repo.find_candidates + ma_policies fairness)
  ├─ fetch slots (MEETING_API_BASE_URL + MEETING_AVAILABILITY_PATH)
  ├─ compose propose-reply (chat_payload picker of slot options)
  └─ on user confirmation:
       ├─ atomic booking (ma_repo + BOOKED_PATH_API)
       ├─ write ma_confirmation record
       └─ compose confirm-reply
    ↓
return chat_turn dict → back to sd_service
```

## Env vars

Meeting-specific (full list in [`../../ops/env_reference.md`](../../ops/env_reference.md#meeting-arrangement--sales)):

| Key | Purpose |
|---|---|
| `BOOKED_PATH_API` | Calendar event creation endpoint. |
| `BEARER_TOKEN_CALENDAR_API` | Auth for above. |
| `MEETING_API_BASE_URL` | Meeting user + availability API root. |
| `MEETING_API_BEARER_TOKEN` | Auth. |
| `MEETING_USER_PATH` | e.g. `chat/user`. |
| `MEETING_AVAILABILITY_PATH` | e.g. `sales/availability`. |
| `MEETING_API_TIMEOUT_SECS` | `10` |
| `SALES_EMAIL_API_BASE_URL`, `SALES_COVERAGE_PATH`, `SALES_EMAIL_API_BEARER_TOKEN` | Sales coverage lookup. |
| `DAYS_PROPOSAL` | `7` — days forward to propose. |
| `MAX_OTHER_SLOT_PICKS` | `5` — alternate slot cap. |
| `TIME_CHAT_BORDER` | `15:00` — WIB cutoff for today-vs-tomorrow logic. |
| `HOST_TIME_FORMAT` | `UTC+7` |
| `ORGANIZER_EMAIL` | Default organizer in calendar events. |
| `MEETING_POPUP` | Cadence (int). `0` = off. `N > 0` = show BOOK_A_MEETING picker at SA qualification steps that are multiples of N. See [`../service_agent.md#meeting-picker-book_a_meeting`](../service_agent.md#meeting-picker-book_a_meeting). |
| `MA_CONFIRMATION_COLL` | Mongo collection for confirmation records. |

## Dependencies

- Internal: `modules/chat_payload`, `modules/system_detection/sd_repo` (for chat history), LLM via global config.
- External: `requests` (for calendar + meeting APIs), `pymongo`, Claude SDK.

## File map

| File | Purpose |
|---|---|
| `ma_controller.py` | Optional dedicated endpoints (start/propose/confirm). Not registered by default. |
| `ma_service.py` | Orchestration. |
| `ma_policies.py` | Trigger keywords, working-hours, lunch-break, fairness rules. |
| `ma_prompts.py` | LLM prompt templates. |
| `ma_repo.py` | Mongo + external calendar access. |
| `ma_utils.py` | WIB parse/format, window validation. |
| `ma_types.py` | Pydantic/TypedDict records. |

## Prompt audit instrumentation

All 15 LLM call sites in `ma_service.py` are wrapped with `audit_llm_call`
from `core.app_audit` (route `meeting_arrangement`). Each call writes one
audit row to `query_recording` with prompt, output, tokens, latency, model,
session_id, token_id.

Stage labels used in this submodule:

| Stage | Function | Notes |
|---|---|---|
| `propose_compose` | `_compose_available_confirm_i18n` | Available-slot confirmation reply |
| `propose_compose_v2` | `_compose_available_i18n` | Available-slot intro |
| `headers_compose` | `_compose_unavailable_grouped_i18n` | Date headers (i18n) |
| `alt_compose` | `_compose_unavailable_grouped_i18n` | Lead/subheader/footer (i18n). `_usage` aggregates with `headers_compose`. |
| `confirm_compose` | `_summarize_title` | Confirm-line compose |
| `summary_compose` | `_llm_run_plain` | Generic summary fallback |
| `recap_summary` | recap path | Compose recap summary |
| `recap_note` | recap path | Single-sentence note |
| `propose_inline` | inline propose path | Uses `BRIEF_LLM` (not `ask_llm`) |
| `qualification_inline` | inline qualification | Inline reply inside meeting flow |
| `recap_compose` | recap path | Recap message |
| `title_compose` | title generation | 8-10 word meeting title |
| `intent_check` | intent gate | Single-system-message intent classify |
| `slot_compose` | `llm_parse_day_and_slot` | Day+slot parse (first call) |
| `slot_compose_v2` | `llm_parse_day_and_slot` | Day+slot parse (second call) |

`save_query_recording()` in `ma_repo.py` is now a thin shim delegating to
`core.app_audit.record_llm_call` with `kind="meeting_event"` — its signature
is preserved for any out-of-tree consumers. See
[`../../ARCHITECTURE.md#prompt-audit`](../../ARCHITECTURE.md#prompt-audit).

8 of these sites currently pass `session_id=""` because the helper functions
they live in do not yet receive session/token context. Plumbing those
through the function signatures is tracked as `# TODO(audit): plumb session_id`
in the code.

## Gotchas

- **Two calendar integrations exist side-by-side**: `BOOKED_PATH_API` (for
  actual booking) and `MEETING_API_BASE_URL` (for availability). They're
  different services — don't swap them.
- **`TIME_CHAT_BORDER`** (default `15:00` WIB) controls today-vs-tomorrow
  suggestions — messages received after 15:00 default to suggesting tomorrow.
  This is brittle if you change working hours; keep them in sync.
- **Fairness** distributes proposals across sales people — if you see the
  same sales person winning every time, check `ma_policies.pick_candidate`
  and the Mongo `sales_profiles` weights.
- **Atomic booking** in `ma_repo` uses Mongo's find-and-modify to claim a
  slot — if the calendar API accepts a booking but Mongo update fails, the
  slot is lost. Investigate logs in `meeting_logs` collection.
- **Picker preamble is templated, not LLM-generated.** The 2-sentence
  invitation shown above meeting-slot choices comes from
  `sd_meeting.build_meeting_picker_preamble(...)` (11 languages,
  prefix-match, English fallback). If you change the preamble wording,
  update all 11 branches and the unit tests in
  `tests/test_meeting_picker_i18n.py`.
- **`MAX_OTHER_SLOT_PICKS` semantics are A1+B1.** `N` counts "Other" button
  clicks; the initial picker does not count. With `N=2` the user sees up to
  3 pickers total (initial + 2 after-click). On the `N`-th click, the
  response turn renders the localized Sales-redirect footer
  (`build_meeting_footer(language_code)`) as the picker preamble and omits
  the "Other" button. See `OTHER_PICKED_SLOT` handling in `sd_service.py`
  and the `include_other` kwarg of `build_meeting_choices_now`. Edge case:
  if the next window has no slots at the boundary, the turn falls back to
  a text-only footer message (no picker).

## Known TODOs for this doc

- **Document trigger keywords** in `ma_policies.py` — the list of
  regex/literal triggers that route to this flow.
- **Document `ma_prompts.py` templates** — name → use step → variables.
- **Document slot data shape** — what fields a `Slot`/`Proposal`/`Booking`
  carries through the flow.

## Extension notes

- Adding a new calendar vendor: implement the `ma_repo.calendar_book(...)`
  path with the new API; select at runtime via a new env key.
- Enabling meeting popups: set `MEETING_POPUP=N` (e.g. `2` for every 2 qualification
  steps) and ensure the client-side renderer handles the picker payload. Each
  milestone step shows the picker once — Method A tracks via `popup_shown_steps`
  in `dual_agent_meta`, Method B (2026-05-18) tracks via
  `state.popup_shown_counts`. Method B counts filled flow answers (not strict
  question index) and suppresses the picker when
  `interest_signal == "not_interested"`. See `docs/modules/service_agent.md` for
  the Method B parity write-up.
- **Meeting-intent initial picker (2026-05-18).** When the user expresses
  meeting intent (`is_meeting_request` matches) but no service is selected
  yet, the chatbot now shows the SA validation picker
  (`SA_SELECT_*` + `RS_OTHER_BATCH_*`, clean `"Other Services"` label) on
  route `incontext_service_validation` instead of the legacy MA picker
  (`MA_ARRANGEMENT_*` + `"Other Services (N)"`). Post-pick lands the user in
  qualification (Method A or Method B per `QUALIFICATION_METHOD`) — the
  meeting picker reappears later via `MEETING_POPUP` cadence once enough
  fields are collected. Legacy MA picker code (`plan_meeting_service_picker`,
  `MA_ARRANGEMENT_other_batch*` pagination handler) is retained for stale
  in-flight sessions but no longer reachable for new sessions.
- Expanding the proposal window: `DAYS_PROPOSAL` alone controls it; the rest
  of the flow scales without code changes.
- **Adding a new language.** Add a new `if lang.startswith(...)` branch to
  each of `build_meeting_footer`, `build_meeting_picker_preamble`, and
  `build_other_slot_label` in `sd_meeting.py`. Update
  `tests/test_meeting_picker_i18n.py`'s smoke test to include the new prefix.
- **Changing the Other-button click limit.** Set env var
  `MAX_OTHER_SLOT_PICKS`. `0` or less is not supported (undefined behavior).
