# Module — `chat_testing_ui`

Lightweight browser UI for manual QA of the chatbot. Not for end users.

## Purpose

Provide a zero-friction page for testing specific user accounts:

- Render a chat UI keyed by a `<name>` path segment.
- Generate/activate a session token for that user on demand.
- Proxy chat questions to the main chatbot endpoint using the user's stored
  `session_id` and `token_id`.

Useful for sanity-checking conversation flows without needing a real client
website integration.

## Public API

HTTP endpoints (all prefixed per route, no `/aitegrity-core/ui` prefix — mounted under `/aitegrity-core/chatbot/claude4sonnet/ui_testing*`):

| Method | Path | What it does |
|---|---|---|
| GET | `/ui_testing/<name>` | Render the UI for a named user. |
| POST | `/ui_testing_proxy/<name>` | Proxy a `{question: ...}` to the main chatbot. |
| POST | `/ui_testing_activate/<name>` | Issue a new session token for the user. |
| POST | `/ui_testing_shutdown/<name>` | Deactivate the user's active token. |

See [`../api/chat.md`](../api/chat.md#chat-testing-ui-browser) for request/response details.

## Data flow

1. `GET /ui_testing/<name>` → `find_account_by_name()` in Mongo (`api_keys` or crisp_sessions) → render template.
2. Template has a text input + "Ask" button that POSTs to the proxy.
3. Proxy POSTs to `cfg.backend_origin + cfg.base_path` (main chatbot) with the user's session/token.

## Env vars

- `API_KEY` — injected into the proxy's outgoing headers.
- `API_HEADER_NAME` — header name for the outgoing chatbot call.
- `PORT_UI_TEST` — when run as a standalone Flask service.
- `TESTING_WEBSITEID`, `TESTING_APIKEY` — test-mode toggles.

Plus indirect dependencies via `load_ui_config()`, which reads backend origin
and base path from config.

## Dependencies

- Internal: reads Mongo via `core/app_config.py`, calls the chatbot endpoint.
- External: `requests` (to proxy), Jinja2 templates (Flask built-in).

## File map

| File | Purpose |
|---|---|
| `ctu_controller.py` | Flask blueprint + 4 endpoints. |
| `ctu_service.py` | `load_ui_config`, `find_account_by_name`, `deactivate_token_append`, `shutdown_append_direct`, `generate_session_id`. |
| `ui_testing_app.py` | Standalone Flask app runner (`python -m modules.chat_testing_ui.ui_testing_app`). |
| `templates/ui_testing.html` | The UI page. |

## Gotchas

- Two user-document shapes are supported: the newer `crisp_sessions`-style
  (has `user` dict + `sessionId`) and the legacy `api_keys`-style (has
  `userId`). The controller branches on `isinstance(doc.get("user"), dict)`.
- Proxy timeout is hardcoded to 75s in `ctu_controller.py`. Long meeting flows
  may need this bumped.
- A fallback API key is hardcoded inline (`4743f227-…`) for the case where
  env is missing — remove before open-sourcing.

## Extension notes

- To add a new UI page: add a route to `ctu_controller.py`, add a template,
  hook it into `find_account_by_name` or a new lookup function in
  `ctu_service.py`.
- To add a non-proxy action (e.g. clear chat history), add a POST endpoint
  that talks to Mongo directly via `get_mongo_client()` — keep it
  firewall-restricted.
