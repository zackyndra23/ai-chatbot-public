# API — Token Generate

Two endpoints issued by the standalone `token_generate` Flask service
(`python -m modules.token_generate.generate`). Default port: `PORT_TG=2303`.

Both endpoints accept data flexibly: JSON body, form-encoded, or query string.

## `POST /rag-assistant/user-id-generate`

Issues a new `userId` record for a website, associating it with an `api_key`.

### Auth

No explicit API-key header required on this endpoint. Callers are typically
internal / admin.

### Request

Any of:

**1. JSON body (preferred):**

```json
{
  "websiteId": "acmeservices.example.com",
  "api_key":  "<your-api-key>",
  "name":     "Demo User"
}
```

**2. Form-encoded:**

```
websiteId=acmeservices.example.com&api_key=<your-api-key>&name=Demo+User
```

**3. Query string:**

```
POST /rag-assistant/user-id-generate?websiteId=acmeservices.example.com&api_key=…&name=Zaky
```

### Fields

| Field | Required | Notes |
|---|---|---|
| `websiteId` | yes | Identifies which site this user belongs to. |
| `api_key` | falls back to env `API_KEY` if omitted | The key the client will later present on chat requests. |
| `name` | no | Display name for the user. |

### Response (200)

```json
{
  "status": "ok",
  "websiteId": "acmeservices.example.com",
  "api_key":   "…",
  "name":      "Zaky",
  "userId":    "uid-…",
  "user_id_generated_at": "2026-04-23T10:15:00+07:00"
}
```

### Errors

| Status | Meaning |
|---|---|
| 400 | Missing `websiteId`, or missing `api_key` with no env fallback, or invalid JSON. |
| 500 | Server error (logged as `user-id-generate error`). |

---

## `POST /rag-assistant/session-id-generate`

Issues a new session token for an existing API key.

### Auth

Header `x-api-key: <apiKey>` (name configurable via repo — see
`TokenRepo.api_header_name`).

### Request

**Content-Type:** `text/plain` (or any — the body is treated as raw text).

**Body:** must equal `TRIGGER_TRUE_VALUE` (default `true`).

```
true
```

### Response (200)

```json
{
  "status": "ok",
  "tokenId": "tok-…",
  "token_generated_at": "2026-04-23T10:15:00+07:00"
}
```

### Errors

| Status | Meaning |
|---|---|
| 400 | Body doesn't match `TRIGGER_TRUE_VALUE`, or missing `x-api-key` header. |
| 409 | An active token already exists for this API key. Wait for auto-deactivation or deactivate manually. |

### Token lifecycle

Issued tokens are automatically deactivated by
`modules.token_generate.tg_pipelines.AutoDeactivatePipeline` under these rules:

- `SESSION_IDLE_WITH_HISTORY_SECONDS` (default 600 / 10m) — deactivate if the session had chat activity but has gone idle.
- `SESSION_NO_ACTIVITY_TTL_SECONDS` (default 604800 / 7d) — deactivate if no activity ever.

Scan interval: `CHECK_INTERVAL_SECONDS` (default 60s).

See [`../ops/schedulers.md`](../ops/schedulers.md) and
[`../modules/token_generate.md`](../modules/token_generate.md).

---

## Related config

| Key | Used for |
|---|---|
| `API_KEY` | Default api_key when one isn't sent. |
| `TRIGGER_TRUE_VALUE` | Body required by the session-id endpoint. |
| `MONGO_SESSION` | Collection storing users + tokens. |
| `SESSION_IDLE_WITH_HISTORY_SECONDS` | Auto-deactivate rule. |
| `SESSION_NO_ACTIVITY_TTL_SECONDS` | Auto-deactivate rule. |
| `CHECK_INTERVAL_SECONDS` | Deactivator scan interval. |
| `PORT_TG` | Flask port. |
