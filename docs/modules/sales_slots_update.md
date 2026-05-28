# Module — `sales_slots_update` (SSU)

Automated sync of sales availability from Mongo to Google Sheets. Runs on an
interval + exposes a manual-trigger HTTP endpoint.

## Purpose

Keep two Google Sheets worksheets fresh:

1. **Aggregate matrix** (`SALES_SHEET_NAME`) — `count of available sales` per `(slot, date)`.
2. **Individual matrix** (`INDV_SALES_SHEET_NAME`) — `0/1` per `(sales_email, slot, date)`.

Lets sales/ops staff see availability without querying Mongo. Matrices are
cleared and rewritten on each run (idempotent).

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `ssu_bp` | `ssu_controller.py` | Flask blueprint — exposes `GET/POST /rag-assistant/ssu/run`. |
| `SalesSlotsUpdateService()` | `ssu_service.py` | Main orchestration. Key methods: `run_once()`, `compute_window()`, `build_matrix()`, `write_matrix_to_sheet()`, `write_individual_matrix_to_sheet()`. |
| `register_ssu_scheduler(app)` | `ssu_pipelines.py` | Register the APScheduler interval job against the host app/scheduler. |
| `SalesSlotsRepo` | `ssu_repo.py` | Mongo access: `build_matrix_counts`, `build_individual_matrix`, `log_upsert_last`, `log_append`. |
| `read_env_config()`, `parse_hhmm()`, `now_wib()`, `WIB` | `ssu_utils.py` | Env reader + WIB helpers. |

`__init__.py` exports: `ssu_bp`, `SalesSlotsUpdateService`, `register_ssu_scheduler`.

## HTTP

- `POST /rag-assistant/ssu/run` (Flask, no auth) — see [`../api/sales_slots_update.md`](../api/sales_slots_update.md).
- `POST /rag-assistant/sales-slots-update` (FastAPI, in `main.py`, API-key auth).

## Data flow

```
APScheduler tick (every SLOTS_UPDATE_DURATION minutes, WIB work hours only)
    ↓
SalesSlotsUpdateService.run_once()
  ├─ compute_window()                           → today WIB → today+SSU_DAYS_AHEAD
  ├─ repo.build_matrix_counts(start, end)       → {rows, cols, matrix}
  ├─ write_matrix_to_sheet(...)                 → SALES_SHEET_NAME (cleared + rewritten)
  ├─ repo.build_individual_matrix(start, end)   → per-sales 0/1 matrix
  ├─ write_individual_matrix_to_sheet(...)      → INDV_SALES_SHEET_NAME
  └─ repo.log_upsert_last|log_append(log_doc)   → Mongo SSU_LOG_COLL
    ↓
return {rows, cols, last_run_wib, duration_ms}
```

## Env vars

See [`../ops/env_reference.md` → SSU section](../ops/env_reference.md#ssu-sales-slots-update--read-via-ssu_utilsread_env_config).

Most important:

- `SSU_FEATURE_ON` — master switch.
- `SLOTS_UPDATE_DURATION` — interval minutes.
- `WORK_START` / `WORK_END` — working-hours gate (scheduled runs only).
- `SSU_DAYS_AHEAD` — window size.
- `SALES_SHEET_ID`, `SALES_SHEET_NAME`, `INDV_SALES_SHEET_NAME` — targets.
- `GOOGLE_SERVICE_ACCOUNT` / `GOOGLE_SA_PATH` — auth (JSON inline or path).
- `SSU_LOG_MODE` — `upsert` (keep latest only) or `append`.

## Dependencies

- External: `gspread`, `google-auth`, `pymongo`, `apscheduler`.
- Internal: `core/app_config.py` only indirectly — SSU uses its own `read_env_config()`.

## File map

| File | Purpose |
|---|---|
| `ssu_controller.py` | Flask blueprint — manual trigger endpoint. |
| `ssu_service.py` | `SalesSlotsUpdateService` — core business logic. |
| `ssu_repo.py` | Mongo access + log write helpers. |
| `ssu_pipelines.py` | Scheduler registration. |
| `ssu_policies.py` | Rules (working hours parsing, feature toggle). |
| `ssu_utils.py` | Env reader, `parse_hhmm`, `now_wib`, `WIB` constant. |
| `__init__.py` | Re-exports. |

## Gotchas

- Double registration of the scheduler job (both `main.py` and the Flask
  chatbot register it). Harmless due to `replace_existing=True`, but
  overlapping runs shouldn't happen thanks to `max_instances=1`.
- The SA credentials resolver tries several paths (CWD, project root,
  `secrets/sa.json`) — so a relative path can silently resolve to a
  different file than expected. Use absolute paths or inline JSON.
- Sheet format is reapplied on every run; if someone manually styles the
  sheet, their changes get clobbered.
- WIB boundary handling in `compute_window` adds `+1` day to the end date
  so "tomorrow" is always safe — this is intentional.
- `SHEETS_MIN_INTERVAL` throttles Sheets API calls, but the actual rate-
  limiter is elsewhere (gspread). At high scheduler frequency you may still
  hit 429s.

## Extension notes

- Adding a third worksheet view: duplicate the write function, plug it into
  `run_once`, expose a new env key for the worksheet name.
- Switching from count-matrix to something richer (e.g. nested availability
  objects): change `build_matrix_counts` + `write_matrix_to_sheet` together —
  they're coupled on shape.
