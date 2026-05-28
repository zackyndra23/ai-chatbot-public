# Module — `chat_payload`

Typed builders for chat message payloads. Everything the chatbot sends back to
the client goes through these builders so the shape is consistent.

## Purpose

Centralize the "wire format" of chat messages. The rest of the codebase never
constructs `dict` payloads by hand — it calls `build_string_message`,
`build_picker_message`, or `build_chat_turn_payload` and gets a guaranteed
schema.

## Public API

From `payload_builder.py`:

| Function | Returns | Use for |
|---|---|---|
| `build_string_message(text, *, message_id?, choices?, required?)` | `ChatMessage` (type="string") | Plain text reply. Optional inline choices (for soft suggestions). |
| `build_picker_message(text, choices, *, required=False, picker_id?)` | `ChatMessage` (type="picker") | Selectable list — user can dismiss. |
| `build_lockpicker_message(text, choices, *, required=True, picker_id?)` | `ChatMessage` (type="picker") | Selectable list that must be answered. |
| `default_summarization_meta(summary_prompt?)` | `SummarizationMeta` | Empty/default metadata block when no summary was applied. |
| `build_chat_turn_payload(...)` | `dict` (chat_turn envelope) | Top-level per-turn record that includes question, message, route, tokens, timing, summarization meta, etc. |

## Types

From `payload_types.py`:

- `ChatMessage` — `{type: "string" | "picker", content: {...}}`.
- `PickerChoice` — `{value, label, selected}`.
- `SummarizationMeta` — `{summary_applied, summary_input, summary_output, chat_summarization}`.

## Data flow

Callers (primarily `modules/system_detection/sd_service.py` and
`modules/service_agent/sa_flows.py`) build a `ChatMessage` for the current
turn, then wrap it in a `chat_turn` dict via `build_chat_turn_payload`. That
dict is what gets persisted in Mongo `chat_history` and returned to the
client.

## Env vars

None directly.

## Dependencies

Internal: none (standalone data-shape module). External: `pydantic` (v1-style
`.dict()` is assumed — see usage of `x.dict()` for choices).

## File map

| File | Purpose |
|---|---|
| `payload_builder.py` | All `build_*` helpers. |
| `payload_types.py` | Pydantic models for `ChatMessage`, `PickerChoice`, `SummarizationMeta`. |

## Gotchas

- `build_picker_message` and `build_lockpicker_message` are nearly identical — the only difference is `required` defaults (`False` vs `True`). Prefer one over the other for intent clarity.
- Timestamps default to WIB (`now_wib_iso()`), but `ts` can be overridden to keep replay/test runs deterministic.
- `summarization_meta` accepts either a dict, a `SummarizationMeta` instance, or `None` (falls back to `default_summarization_meta()`).

## Extension notes

- Adding a new message type (e.g. "card", "image"): extend `ChatMessage.type` enum in `payload_types.py`, add a `build_card_message` helper, and update the chatbot's renderer (client side) to handle it.
- Adding a new field to `chat_turn`: update `build_chat_turn_payload`'s signature and add it to the returned dict. Downstream consumers tolerate unknown keys (Mongo stores as-is).
