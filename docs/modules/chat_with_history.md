# Module — `chat_with_history`

Conversation-history fetch, rolling summary, and prompt compaction for LLM
calls.

## Purpose

Given a `session_id`, pull prior turns from Mongo, optionally summarize older
turns to stay under a char/token budget, and return a compact transcript the
chatbot can include in its LLM prompt.

## Public API

Key types and functions (under review — the module has its own
local `cwh_config.py`):

| Symbol | File | Purpose |
|---|---|---|
| `cwh_config.Config` | `cwh_config.py` | Local config dataclass duplicating some keys from `core/app_config.py`. |
| `cwh_history.*` | `cwh_history.py` | History fetch + format. |
| `cwh_prompt.*` | `cwh_prompt.py` | Prompt builders that include history. |
| `cwh_repo.*` | `cwh_repo.py` | Mongo access for chat history. |
| `cwh_types.*` | `cwh_types.py` | Typed records for history items. |
| `cwh_utils.*` | `cwh_utils.py` | Time/token helpers. |

## Env vars

Read both by the local `cwh_config.Config` and the global `core/app_config.Config`:

- `UTILIZER_STATUS` — `local` / `crisp`. Changes which collection the history is read from.
- `CHAT_HISTORY_SCHEMA` — `allsum` (default) or other variants controlling summarization strategy.
- `HISTORY_SUMMARY_MAX_CHARS` — cap on summary text size.
- `HISTORY_SUMMARY_MAX_TOKENS` — cap on summary output.
- `HISTORY_SUMMARY_MAX_PAIRS` — max user/bot pairs considered for summary.
- `INPUT_MAX_PROMPT` / `PROMPT_MAX_CHARS` — prompt-size budget.
- `SUMMARY_ASYNC`, `SUMMARY_ASYNC_DELAY_SEC` — async summary refresh.

## Data flow

```
session_id
    ↓
cwh_repo.fetch_history_for_session() → list of chat_turn dicts (Mongo)
    ↓
cwh_history.compact_or_summarize() → trimmed list + summary text
    ↓
cwh_prompt.build_messages() → messages list for LLM call
```

## Dependencies

- `pymongo` — history access.
- `core/app_config.py` — global config.
- Local `cwh_config.py` — module-local config (note: duplicates `UTILIZER_STATUS`).

## File map

| File | Purpose |
|---|---|
| `cwh_config.py` | Local config dataclass — **has duplicated `UTILIZER_STATUS` line, harmless but worth cleaning up**. |
| `cwh_history.py` | History fetch & reduction logic. |
| `cwh_prompt.py` | LLM message/prompt builder including history + summary. |
| `cwh_repo.py` | Mongo reader. |
| `cwh_types.py` | Typed records. |
| `cwh_utils.py` | Time/token helpers. |

## Gotchas

- Summarization is asynchronous by default (`SUMMARY_ASYNC=on`). The prompt
  returned for the current turn may not reflect the freshest summary — it
  catches up on the next turn.
- Local `cwh_config.py` is a second copy of certain keys; keep in sync when
  changing defaults or delete it and call `core.app_config.Config()` directly.

## Extension notes

- Switching summary strategy: add a new mode to `CHAT_HISTORY_SCHEMA` and
  branch in `cwh_history.compact_or_summarize`.
- Switching to a different history store (e.g. Redis): keep the repo
  interface in `cwh_repo.py` and swap its implementation.

> **TODO:** Enumerate the exact public functions/classes of each `cwh_*`
> file as they get touched. Skeleton stays until then so we document as we
> edit (per the freshness rule).

## Naming policy (2026-05-13)

The chatbot has **no finalized production name**. Prompts must refer to
the assistant generically — first-person "I" / "we", or "the chatbot" /
"the assistant" when third-person reference is needed. Do NOT introduce
a product name in prompts (system, human, or examples) until the name is
finalized via product decision.

Historical references to a prior working name were removed across
`cwh_prompt.py` (summarizer system prompt) on 2026-05-13. Any future
addition of a persona name must go through explicit product approval,
not be reintroduced via prompt drift.
