# Module — `late_response_followup`

Re-engagement for sessions that went idle mid-conversation. Sends a follow-up
message if the user hasn't responded within a configured window.

## Purpose

Automated "are you still there?" nudge. Useful for lead capture —
conversations that stall often resume with one small re-engagement prompt.

Feature-flagged off by default.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `late_response_followup_bp` | `lrf_controller.py` | Flask blueprint. |
| `LateResponseFollowupService` | `lrf_service.py` | Orchestration. Key method: `run_scan(limit=100)`. |
| `LRFMongoRepo` | `lrf_repo.py` | Mongo access. |
| `register_late_response_followup_job(scheduler)` | `lrf_pipelines.py` | Register the APScheduler job. |

Exports in `__init__.py`:

```python
from .lrf_controller import late_response_followup_bp
from .lrf_service import LateResponseFollowupService
from .lrf_repo import LRFMongoRepo
```

## HTTP

`POST /rag-assistant/chatbot/late-response-followup/run` — manual trigger.
Auth: `x-api-key`. Body: `{"limit": 100}`. See [`../api/chat.md`](../api/chat.md#late-response-follow-up).

## Data flow

```
APScheduler tick (every LATE_RESPONDS_CHECK_INTERVAL)
    ↓
LateResponseFollowupService.run_scan(limit=...)
  ├─ repo.find_idle_sessions()     → sessions with last_ts older than LATE_RESPONDS_TIME
  ├─ filter by has_history?        → LATE_RESPONDS_REQUIRE_CHAT_HISTORY
  ├─ filter by per-session cap     → LATE_RESPONDS_MAX_PER_SESSION
  ├─ send follow-up message        → via chatbot reply path
  └─ record follow-up in Mongo     → LATE_RESPONDS_COLL
```

## Env vars

| Key | Default | Purpose |
|---|---|---|
| `LATE_RESPONDS_FEATURE` | `off` | Master switch. |
| `LATE_RESPONDS_TIME` | `1800` (30 min) | Idle threshold in seconds. |
| `LATE_RESPONDS_CHECK_INTERVAL` | `60` | Scan frequency in seconds. |
| `LATE_RESPONDS_MAX_PER_SESSION` | `1` | Cap per session. |
| `LATE_RESPONDS_REQUIRE_CHAT_HISTORY` | `1` | If truthy, skip sessions with no prior chat. |
| `LATE_RESPONDS_COLL` | `late_response_followups` | Log collection. |

## Dependencies

- Internal: `core/app_config.py`, `core/app_logging.py`, chat-history fetch.
- External: `pymongo`, `apscheduler`.

## File map

| File | Purpose |
|---|---|
| `lrf_controller.py` | Manual-trigger blueprint. |
| `lrf_service.py` | `LateResponseFollowupService` + scan logic. |
| `lrf_repo.py` | Mongo access for idle-session discovery + follow-up logging. |
| `lrf_pipelines.py` | Scheduler registration. |
| `lrf_prompts.py` | Message template(s) for the follow-up. |
| `lrf_types.py` | Typed records. |
| `__init__.py` | Re-exports. |

## Prompt audit instrumentation

`LateResponseFollowupService.generate_followup_text` wraps its `FOLLOWUP_LLM.invoke`
call with `audit_llm_call` from `core.app_audit` (stage `lrf_compose`,
route `late_response_followup`). Each follow-up message generation writes one
audit row to the `query_recording` collection with prompt, output, tokens,
latency, model, and the candidate's `sessionId` / `tokenId`. The function's
return tuple `(text, prompt, in_tok, out_tok, latency_seconds)` is preserved
by reading `ctx.input_tokens`, `ctx.output_tokens`, and
`ctx.latency_ms / 1000.0` after the CM exits. See
[`../ARCHITECTURE.md#prompt-audit`](../ARCHITECTURE.md#prompt-audit) for the
subsystem overview.

## Gotchas

- **`register_late_response_followup_job` is called twice** in the codebase:
  once inside `build_pipelines`/`register_background_jobs` (correctly) and
  once at module-top of `core/app_pipelines.py` with an undefined
  `scheduler` — latent import-time error. See
  [`../ops/troubleshooting.md`](../ops/troubleshooting.md).
- Per-session cap counts ALL follow-ups ever (not per-day). To reset,
  manually clear the `LATE_RESPONDS_COLL` entries for that session.
- Only fires when the Flask chatbot (or a service that registers the job) is
  running — not in the FAQ-only FastAPI admin app.

## Extension notes

- To add a second follow-up (e.g. 2 hours after the first): increase
  `LATE_RESPONDS_MAX_PER_SESSION` and add delta logic in
  `LateResponseFollowupService.run_scan` using the log collection's
  timestamps.
- Message copy lives in `lrf_prompts.py` — language-aware branching can be
  added there based on the session's detected language.
