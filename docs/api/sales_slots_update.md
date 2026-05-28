# API — Sales Slots Update (SSU)

Manual triggers for the SSU job (which normally runs on a scheduler — see
[`../ops/schedulers.md`](../ops/schedulers.md)).

Two flavors exist because SSU is registered in both the Flask chatbot and the
FastAPI admin app:

## `POST /rag-assistant/sales-slots-update`  *(FastAPI — `main.py`)*

### Auth

Header `x-api-key` against any of `X_API_KEY`, `API_KEY`, or `SSU_API_KEY`
(first non-empty wins).

### Request

```http
POST /rag-assistant/sales-slots-update HTTP/1.1
x-api-key: <key>
```

Body is ignored.

### Response (200)

```json
{
  "ok": true,
  "result": {
    "rows": 24,
    "cols": 7,
    "last_run_wib": "2026-04-23T10:15:00+07:00",
    "duration_ms": 1342
  }
}
```

### Errors

| Status | Meaning |
|---|---|
| 401 | Missing or wrong `x-api-key`. |
| 400 | `SSU_FEATURE_ON=false` — the job is disabled. |

---

## `GET /rag-assistant/ssu/run`  or  `POST /rag-assistant/ssu/run`  *(Flask blueprint)*

Registered by `modules/sales_slots_update/ssu_controller.py` as `ssu_bp` —
mounted in the Flask chatbot (`modules/system_detection/chatbot.py`).

### Auth

**None** by default. This is an internal admin endpoint; expose it behind
nginx/firewall.

### Request

Plain `GET` or `POST`. No body required.

### Response (200)

```json
{
  "ok": true,
  "result": {
    "rows": 24,
    "cols": 7,
    "last_run_wib": "2026-04-23T10:15:00+07:00",
    "duration_ms": 1342
  }
}
```

---

## What SSU actually does

Both endpoints invoke `SalesSlotsUpdateService.run_once()`, which:

1. Computes a `days_ahead` window starting at WIB midnight today.
2. Reads Mongo `calendar_payload` and `sales_slots` collections for that window.
3. Builds two matrices:
   - **Aggregate:** count of available sales per `(slot, date)`.
   - **Individual:** `0/1` per `(sales_email, slot, date)`.
4. Writes both to the configured Google Sheets (`SALES_SHEET_NAME` + `INDV_SALES_SHEET_NAME`),
   clearing each sheet first and re-writing.
5. Writes a log row to Mongo — either upsert-last or append based on `SSU_LOG_MODE`.

Idempotent in effect: re-running overwrites the target sheet's contents.

## Related config

Every SSU env key → [`../ops/env_reference.md` → "SSU" section](../ops/env_reference.md#ssu-sales-slots-update--read-via-ssu_utilsread_env_config).

Key ones:

- `SALES_SHEET_ID`, `SALES_SHEET_NAME`, `INDV_SALES_SHEET_NAME` — target sheets.
- `SSU_DAYS_AHEAD` — window size.
- `WORK_START`, `WORK_END` — working-hours gate (for scheduled runs only; manual calls bypass it).
- `SSU_LOG_MODE`, `SSU_LOG_COLL` — logging.
- `GOOGLE_SERVICE_ACCOUNT` — auth.
