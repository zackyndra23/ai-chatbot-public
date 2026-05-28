# API — Chat

All chat-facing endpoints live on the **Flask** app (`modules/system_detection/chatbot.py`),
which is what `Dockerfile.prod` and `modal_app.py` actually serve. The FastAPI
`main.py` does NOT expose these endpoints.

## Main chatbot

### `POST /aitegrity-core/chatbot/claude4sonnet`

Primary chatbot entrypoint. Handles intent classification (FAQ vs meeting vs
service-agent vs OOC), retrieval, LLM call, and persistence.

#### Auth

- `x-api-key: <API_KEY>` (header name from `API_HEADER_NAME`).
- `x-website-id: <id>` — required if `WEBSITE_ID_HEADER_NAME` is not `off`.
- `x-token-id: <token>` — optional; also accepted in body as `token_id`.

#### Request

```json
{
  "session_id": "sess-abc",          // required (or derivable from token_id)
  "question": "What is EBS?",        // required, non-empty string
  "token_id": "tok-xyz",             // optional; also accepted via x-token-id header
  "utilizer": "local"                // optional; "local" (default) or "crisp"
}
```

#### `utilizer` modes

- **`local`** — standard flow. If `session_id` is missing or equals `token_id`, the server looks up the session from the token.
- **`crisp`** — for Crisp chat integrations. `session_id` is taken from the `X-Crisp-Session-Id` header if not provided. `token_id` falls back to `session_id`.

#### Response (200)

```json
{
  "message": { "type": "string", "content": { "id": "m-...", "text": "…" } },
  "route": "faq",
  "language_name": "English",
  "related_services": [],
  "docs_retrieved_count": 3,
  "respond_duration": 1.42,
  "input_token": 312,
  "output_token": 180,
  "_persisted": true,
  "_website_id": "<echoed>"
}
```

Exact shape depends on `route` (FAQ reply, meeting picker, OOC redirect, etc.).
`_persisted` indicates whether the chat history write succeeded (best-effort).

#### Errors

| Status | Meaning |
|---|---|
| 401 | Missing/wrong API key, or server misconfigured (empty `API_KEY`). |
| 400 | Missing `Content-Type: application/json`, missing required fields, or missing website ID when required. |
| 404 / 428 | (UI testing variants) — user not found or no active token. |

---

## Service agent

### `POST /aitegrity-core/chatbot/claude4sonnet/service-agent`

Structured flows — EBS (Employment Background Screening), quotation, handoff.
Entered via picker values (e.g. `PICKER_Employment_Background_Screening`) or
free-text continuations.

#### Auth

- `x-service-agent-api-key: <SERVICE_AGENT_API_KEY>` (header name from `SERVICE_AGENT_API_HEADER_NAME`).

Uses a **different** key from the main chatbot endpoint.

#### Request

```json
{
  "session_id": "sess-abc",
  "question": "PICKER_Employment_Background_Screening"
}
```

#### Response (200)

Varies by flow step. Typically includes the next picker/string payload from
`modules/chat_payload`.

#### Errors

| Status | Meaning |
|---|---|
| 401 | Missing/wrong service-agent key. |
| 400 | Not JSON, or missing `session_id` / `question`. |

---

## Out-of-context classifier test

### `POST /aitegrity-core/chatbot/ooc-agent/test`

Returns classification for a user utterance — useful for tuning OOC rules.

#### Auth

None (test endpoint).

#### Request

```json
{
  "text": "I want to be a freelancer",
  "language_code": "en"
}
```

`text` or `question` accepted. `language_code` or `lang` accepted; optional.

#### Response (200)

Pydantic v1 `.dict()` of the OOC classification result.

---

## Late-response follow-up

### `POST /aitegrity-core/chatbot/late-response-followup/run`

Manual trigger for the late-response scanner.

#### Auth

`x-api-key: <API_KEY>`.

#### Request

```json
{ "limit": 100 }
```

#### Response (200)

Depends on `LateResponseFollowupService.run_scan`. Typically counts of sessions
processed and follow-ups sent.

---

## Chat testing UI (browser)

Mounted by `modules/chat_testing_ui/ctu_controller.py`. These are for QA, not
for real clients.

### `GET /aitegrity-core/chatbot/claude4sonnet/ui_testing/<name>`

Renders the testing UI for a named user account (from Mongo `api_keys` or
crisp_sessions collection).

### `POST /aitegrity-core/chatbot/claude4sonnet/ui_testing_proxy/<name>`

Proxies a question to the main chatbot endpoint using the user's stored
session + token.

**Body:** `{ "question": "<text>" }` → returns whatever the chatbot returned.

### `POST /aitegrity-core/chatbot/claude4sonnet/ui_testing_activate/<name>`

Activates (issues) a session for the named user.

### `POST /aitegrity-core/chatbot/claude4sonnet/ui_testing_shutdown/<name>`

Deactivates the user's active token.

All UI endpoints return 404 when the named user is not found.

---

## `GET /health`

Returns `{"status": "ok"}`. Only exists on the **FastAPI** `main.py` app.
There's no equivalent on the Flask chatbot — poke a real endpoint to
healthcheck it.
