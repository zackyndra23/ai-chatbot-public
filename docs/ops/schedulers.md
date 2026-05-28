# Schedulers

APScheduler jobs registered by the application. These run in-process, so they
are tied to whichever entrypoint is running.

## Job inventory

| Job ID | Registered in | Trigger | Default | Purpose |
|---|---|---|---|---|
| `ssu_interval_job` | `main.py` | interval minutes | `SLOTS_UPDATE_DURATION` (30) | Rebuild sales-slots Google Sheet matrix from Mongo calendar data. |
| `ssu_interval_job` | `modules/system_detection/chatbot.py` (via `modules/sales_slots_update/ssu_pipelines.register_ssu_scheduler`) | interval minutes | `SLOTS_UPDATE_DURATION` (30) | Same as above — registered a second time when the Flask chatbot launches. |
| `auto_deactivate_scan` | `modules/token_generate/tg_pipelines.py` | interval seconds | `CHECK_INTERVAL_SECONDS` (60) | Deactivate idle session tokens per `SESSION_IDLE_WITH_HISTORY_SECONDS` + `SESSION_NO_ACTIVITY_TTL_SECONDS` rules. Runs in the `token_generate` Flask app only. |
| *(late-response-followup)* | `modules/late_response_followup/lrf_pipelines.register_late_response_followup_job` | interval seconds | `LATE_RESPONDS_CHECK_INTERVAL` (60) | Scan for idle sessions and send a re-engagement message. Gated by `LATE_RESPONDS_FEATURE=on`. |

## Working-hours gate

The SSU job guards each run with a working-hours check (WIB):

```python
if _within_working_hours(now_wib(), cfg_env["WORK_START"], cfg_env["WORK_END"]):
    SalesSlotsUpdateService().run_once()
```

Env keys that gate it:

- `WORK_START` (default `09:00`)
- `WORK_END` (default `17:00`)
- `SSU_FEATURE_ON` (master switch, default `true`)

## APScheduler variants in use

- `BackgroundScheduler` (main.py, token_generate) — threads.
- `AsyncIOScheduler` (imported but not active).

All schedulers use `timezone="Asia/Jakarta"` (or `UTC` in token_generate) via
the `TIMEZONE` env key.

## `max_instances` and `coalesce`

SSU registers with:

```python
scheduler.add_job(..., max_instances=1, coalesce=True, replace_existing=True)
```

So overlapping runs are prevented. If a run takes longer than the interval,
subsequent ticks are coalesced into one.

## Known landmines

- **Double registration.** If both `main.py` (FastAPI) and
  `modules/system_detection/chatbot.py` (Flask) run in the same process — which
  can happen in Modal / certain dev setups — the SSU job is added twice. With
  `replace_existing=True` this is usually harmless, but the second registrant
  wins.
- **`core/app_pipelines.py` calls `register_late_response_followup_job(scheduler)`
  at module-import time** on an undefined `scheduler` variable. This is likely a
  bug — the function is also called from inside `register_background_jobs`. Treat
  the top-level call as dead / broken. See [`ops/troubleshooting.md`](troubleshooting.md).

## Manual triggers

Some scheduled work also has HTTP endpoints for manual triggering:

- `POST /rag-assistant/ssu/run` — SSU via Flask blueprint.
- `POST /rag-assistant/sales-slots-update` — SSU via FastAPI route in `main.py` (requires `x-api-key`).
- `POST /rag-assistant/chatbot/late-response-followup/run` — late-response scan, passing `{"limit": 100}`.

See [`../api/sales_slots_update.md`](../api/sales_slots_update.md) and
[`../api/chat.md`](../api/chat.md).
