# Module — `token_generate`

User identity + session token issuance. Standalone Flask service plus a
scheduled auto-deactivate pipeline.

## Purpose

Two responsibilities:

1. **Issue `userId`** for a website+API-key pair (`/user-id-generate`).
2. **Issue session tokens** to an existing user (`/session-id-generate`).
3. **Automatically deactivate** idle or stale sessions per configured TTLs.

## Public API

| Symbol | File | Purpose |
|---|---|---|
| `create_app()` | `generate.py` | Builds the Flask app, registers blueprint, starts the auto-deactivate scheduler. |
| `bp` (Blueprint) | `tg_controller.py` | Two endpoints: user-id + session-id. |
| `TokenService(repo)` | `tg_service.py` | Business logic: `generate_api_key(payload)`, `generate_session_id(raw_body, key_header_value)`. |
| `TokenRepo` | `tg_repo.py` | Mongo access (append active token, deactivate, find-all, has_active_session). |
| `AutoDeactivatePipeline(repo)` | `tg_pipelines.py` | APScheduler-based idle-scanner. Key methods: `start()`, `shutdown()`. |
| `getenv_str`, `getenv_int` | `tg_utils.py` | Env read helpers with timezone awareness. |

## HTTP

- `POST /aitegrity-core/user-id-generate` — see [`../api/token.md`](../api/token.md).
- `POST /aitegrity-core/session-id-generate` — see [`../api/token.md`](../api/token.md).

## Standalone run

```bash
python -m modules.token_generate.generate
```

Starts on `PORT_TG` (default 2303). Loads `secrets/.env` in addition to the
project `.env`.

## Data flow (session-id)

```
POST /aitegrity-core/session-id-generate
    (x-api-key header, body="true")
    ↓
TokenService.generate_session_id
  ├─ validate body == TRIGGER_TRUE_VALUE
  ├─ repo.has_active_session(api_key)   → 409 if active
  └─ repo.append_active_token(api_key)  → { tokenId, token_generated_at }
    ↓
200 { status, tokenId, token_generated_at }
```

## Auto-deactivate scanner

`AutoDeactivatePipeline.start()` registers an APScheduler job that runs every
`CHECK_INTERVAL_SECONDS`:

1. `repo.find_all_with_active_tokens()` — users with at least one `active` token.
2. For each active token, `repo.deactivate_if_rules_met(...)`:
   - If session had chat activity and `idle_with_history_s` elapsed → deactivate.
   - If session never had activity and `no_activity_ttl_s` elapsed → deactivate.

Logs `Deactivated session token for key=... reason=...` per deactivation.

## Env vars

| Key | Default | Purpose |
|---|---|---|
| `PORT_TG` | `2303` | Flask port. |
| `API_KEY` | `4743f227-…` | Default API key when body doesn't provide one. |
| `API_HEADER_NAME` | `x-api-key` | Header name for session-id endpoint. |
| `TRIGGER_TRUE_VALUE` | `true` | Required plain-text body value. |
| `MONGO_URI`, `MONGO_DB`, `MONGO_SESSION` | *(required)* | User/token storage. |
| `SESSION_IDLE_WITH_HISTORY_SECONDS` | `600` | Deactivate after 10m idle if chat history exists. |
| `SESSION_NO_ACTIVITY_TTL_SECONDS` | `604800` | Deactivate after 7d of no activity. |
| `CHECK_INTERVAL_SECONDS` | `60` | Scanner interval. |

## Dependencies

- External: Flask, pymongo, apscheduler, python-dotenv.
- Internal: `core/app_config.py`.

## File map

| File | Purpose |
|---|---|
| `generate.py` | Standalone Flask app factory + `__main__`. |
| `tg_controller.py` | Endpoints: `api_key_generate`, `session_id_generate`. Accepts JSON / form / query. |
| `tg_service.py` | `TokenService` — orchestrate, validate, call repo. |
| `tg_repo.py` | Mongo ops — issue token, deactivate, lookup, check active. |
| `tg_pipelines.py` | `AutoDeactivatePipeline` — APScheduler job. |
| `tg_utils.py` | Env readers + timezone (Asia/Jakarta) helpers. |
| `__init__.py` | Empty init. |

## Gotchas

- Scanner runs in UTC (`BackgroundScheduler(timezone="UTC")`), but business
  rules are time-delta based (seconds), so timezone doesn't matter for
  correctness — just for log readability.
- `has_active_session` uses an effective-active check, NOT raw `$elemMatch
  status:active` — so stale records with `status=active` but expired
  timestamps still get a fresh token on re-request.
- 409 on an active token is intentional: one token per API key at a time.
  Change this only if multi-device support is wanted.
- Scanner runs ONLY in the `token_generate` Flask process — if you run the
  main chatbot separately and never run `token_generate`, tokens never
  auto-expire. See [`../ops/troubleshooting.md`](../ops/troubleshooting.md).

## Extension notes

- To allow multiple concurrent sessions per user: change `has_active_session`
  to a count-based gate, and update deactivate rules accordingly.
- To add token scopes/roles: extend `append_active_token` to accept a
  `scopes` arg; enforce scopes in whichever endpoint checks the token.
- Standalone mode uses basic logging (not the JSON logger from
  `core/app_logging.py`). Consider unifying.
