# Module — `googlesheet_chat_history`

Optional mirror of chat history into Google Sheets, for business
visibility/audits. Feature-flagged off by default.

## Purpose

When a chat turn completes and gets written to Mongo `chat_history`, also
append a row to a Google Sheet tab so non-technical stakeholders can browse
conversations without Mongo access.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `flag_enabled() -> bool` | `gsch_utils.py` | Returns True if `GOOGLE_CHAT_HISTORY` env is truthy. Call this before doing any Sheets work. |
| `*` | `gsch_client.py` | Lazy singleton that opens the target worksheet. Auto-creates the tab if missing. |
| `*` | `gsch_repo.py` | Row appender — ensures header row exists, coerces types to Sheets-compatible values. |

## Env vars

| Key | Default | Purpose |
|---|---|---|
| `GOOGLE_CHAT_HISTORY` | `off` | Feature flag. Any of `on` / `1` / `true` / `yes` enables the mirror. |
| `GOOGLE_CHAT_SHEET_ID` | *(unset)* | Target spreadsheet. |
| `GOOGLE_CHAT_SHEET_TAB` | `Chat_History_151025` | Target tab. |
| `GOOGLE_SERVICE_ACCOUNT` | *(required)* | Same SA credentials used elsewhere. |

## Data flow

```
chatbot turn finishes
    ↓
sd_service appends to Mongo (chat_history)
    ↓
if flag_enabled():
    gsch_client.get_worksheet()  (opens/creates tab lazily)
    gsch_repo.append_row(row)    (ensures header, coerces types)
```

## Dependencies

- External: `gspread`, `google-auth`.
- Internal: reads config via `core/app_config.py`.

## File map

| File | Purpose |
|---|---|
| `gsch_client.py` | Lazy worksheet opener (singleton + auto-create tab). |
| `gsch_repo.py` | Row appender with header-ensure + coercion. |
| `gsch_utils.py` | `flag_enabled()` helper. |

## Gotchas

- **Always check `flag_enabled()` first.** Without it, the Sheets client will
  try to open with empty `GOOGLE_CHAT_SHEET_ID` and fail at runtime.
- **Creating `Config()` each call** in `gsch_utils.flag_enabled` is
  intentional — env is re-read every time so toggling the flag without
  restart works. Don't optimize it to a module-level `cfg = Config()`.
- Sheets API is rate-limited (~60 requests/min for default quotas). High-
  traffic deployments should batch or disable the mirror.

## Extension notes

- Adding new columns to the mirror: update `gsch_repo.ensure_header` + the
  row-building logic. Existing rows keep their historical schema — do not
  rewrite.
- Switching to a different export target (e.g. BigQuery): keep `gsch_repo`
  interface, add a new backend behind a second feature flag.
