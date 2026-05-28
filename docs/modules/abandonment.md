# Module — `abandonment`

Abandonment handler — detects when a user signals explicit desire to abandon the qualification flow and performs a hard state clear.

Stage 0 (2026-05-13) — see `docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md` §7.6.

## Purpose

When a user message contains an unambiguous abandonment phrase ("never mind", "cancel", "udahan saja", "batalkan", etc.), the orchestrator must:

1. Clear all active SA state (service, question, answers, OOC streak fields)
2. Acknowledge the abandonment without promising follow-up
3. NOT terminate the Crisp session — user may start fresh in same session

This is architecturally distinct from `modules/out_of_context/`:
- **Abandonment** = hard reset of SA state
- **OOC** = re-routing to handler / contact while preserving SA state

Both modules run at orchestrator Layer A; abandonment runs at Step 0 BEFORE OOC.

## Public API

```python
from modules.abandonment import AbandonmentHandler

handler = AbandonmentHandler()

# Detection
result = handler.matches(
    text="never mind",
    state=session_state,
    lang_hint=session_state.session_fallback_language,
)
# result is AbandonmentResult: matched, matched_phrase, detected_language, matched_via

# State clear + acknowledgment
if result.matched:
    ack_text = handler.handle(text="never mind", state=session_state)
    # session_state SA fields cleared; session_fallback_language preserved
    # return ack_text to user
```

## `matches()` — 3-clause lang_hint semantics (per spec §7.6)

1. **lang_hint first:** If `lang_hint` is set, try its keyword bank first. Hit → `matched_via="lang_hint_match"`.
2. **Cross-lang fallback:** If hint missed (or hint is None), scan ALL known langs' banks. First hit wins. `matched_via="cross_lang_fallback"`.
3. **False-positive risk note:** Phrases are short ("never mind", "udahan saja") so cross-lang fallback false-positive risk is LOW. Lang-specific banks MUST contain only unambiguous abandonment phrases — never common confirmations like "ok", "yes", "ya", "alright".

Returns `AbandonmentResult(matched, matched_phrase, detected_language, matched_via)`.

## `handle()` — state-clear semantics

Cleared (per spec §7.6):
- `service_code` → `""` (existing required-str field; "" signals cleared)
- `question_id` → `""`
- `answers` → `{}`
- `ooc_excursion_count` → `0`
- `previous_user_ooc_categories` → `[]`
- `previous_system_meta_actions` → `[]`
- `ooc_escalation_suppression_remaining` → `0`

Preserved:
- `session_fallback_language` (user's language context persists across abandonment)

Returns: i18n-rendered `abandonment.acknowledgment.{lang}` where `lang` = `state.session_fallback_language` (falls back to English baseline on missing translation).

## File layout

| File | Responsibility |
|---|---|
| `__init__.py` | Public API exports |
| `abandonment_types.py` | `AbandonmentResult` pydantic schema |
| `abandonment_service.py` | `AbandonmentHandler.matches()` + `.handle()` implementation |

## Keyword banks

Two sources, with priority:

1. **i18n loader** — `abandonment.trigger_phrases.{lang}` (list-typed entry in `modules/i18n/strings/{lang}.yaml`). Production source of truth.
2. **Hardcoded `_FALLBACK_TRIGGERS`** in `abandonment_service.py` — used at very-early init before i18n loads, or as graceful degradation if i18n fails.

Phase 2a banks:
- **en:** `["never mind", "cancel", "forget it", "nvm", "let's stop", "stop", "actually never mind"]`
- **id:** `["udahan saja", "udah dulu", "tidak jadi", "ngga jadi", "batalkan", "batalin", "lupakan", "berhenti", "stop"]`

Phase 2b/2c/2d will populate banks for the other 15 langs via the i18n loader (no code change required).

## Acknowledgment templates

i18n key: `abandonment.acknowledgment` (string template, no placeholders).

- **en (verified):** "No problem — we'll stop here. Whenever you're ready to start fresh, just let me know."
- **id (draft, SME-pending):** "Tidak masalah — kita berhenti di sini. Kapan pun Anda siap memulai dari awal, beri tahu saya."

## Orchestrator integration

Per spec §1.1, the orchestrator Step 0:

```python
abandonment = AbandonmentHandler()
ab_result = abandonment.matches(
    text=user_message,
    state=state,
    lang_hint=state.session_fallback_language,
)
if ab_result.matched:
    ack = abandonment.handle(text=user_message, state=state)
    record_audit_row(stage="abandonment_handler", extras={
        "matched_phrase": ab_result.matched_phrase,
        "detected_language": ab_result.detected_language,
        "matched_via": ab_result.matched_via,
    })
    return ack  # short-circuit; no OOC, no SA dispatch
```

This is implemented in Task 11 (`process_user_message_with_ooc` Step 0).

## Audit logging

Stage `abandonment_handler` in `query_recording` with extras:
- `matched_phrase` — the actual phrase that triggered (forensic context)
- `detected_language` — bank that hit
- `matched_via` — `"lang_hint_match"` or `"cross_lang_fallback"`

Operator query (post-deploy telemetry):

```js
db.query_recording.aggregate([
  {$match: {stage: "abandonment_handler"}},
  {$group: {_id: "$extras.detected_language", count: {$sum: 1}}}
])
```

## Gotchas

- `state.service_code` and `state.question_id` are pydantic `str` fields (no default, no `Optional`). `handle()` sets them to `""` rather than `None` to stay type-compatible. Consumers checking "is this cleared?" should check `not state.service_code` rather than `state.service_code is None`.
- `state.answers = {}` directly reassigns (does NOT use `.clear()`) so consumers holding old references are not surprised by mutation.
- Cross-lang fallback false-positive risk is the main keyword-bank tuning concern. If production telemetry shows abandonment fires on confirmations like "stop" used innocently, narrow the en bank further.
- Crisp session NOT terminated by abandonment — user remains connected and can immediately start a fresh qualification.
