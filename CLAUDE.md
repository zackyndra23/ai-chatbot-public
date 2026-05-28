# CLAUDE.md — project guidance for Claude Code

This file is read at session start. It tells Claude the non-obvious rules of this
repository that can't be inferred from code alone.

## Git / GitLab

Do not commit, push, tag, open MRs, or otherwise write to git history or to
GitLab unless the user explicitly asks in the current turn. Edits in the working
tree are fine; the user reviews and commits manually.

## Documentation freshness

Canonical docs live in `docs/`. When you change code in a turn, update the
matching doc in the same turn:

- Edit `modules/<X>/**/*.py` → update `docs/modules/<X>.md`
  (or for `system_detection/`, the right file under `docs/modules/system_detection/`)
- Add / remove / change behavior of an HTTP endpoint → update `docs/api/<group>.md`
- Change / add an env key (in `core/app_config.py`, `.env.example`, or anywhere
  `os.getenv(...)` is added) → update `docs/ops/env_reference.md`
- Add / change an APScheduler job → update `docs/ops/schedulers.md`
- Change Dockerfile, docker-compose.yml, modal_app.py, or .gitlab-ci.yml →
  update `docs/ops/deployment.md`
- Change `core/gpu_config.py` or GPU behavior → update `docs/ops/gpu_setup.md`
- Change `core/app_config.py` architecture-wise (not just adding a key) →
  update `docs/ARCHITECTURE.md` where relevant

**Exceptions (no doc update needed):** typo fixes, dead-code removal,
log-message tweaks, auto-formatter passes, import re-ordering, comment-only
changes. If unsure, update the doc.

**Start-of-turn check when you change code:** ask yourself "which doc page
covers this file?" If you can't answer, the doc page is missing — create it.

The Stop hook at `.claude/hooks/check_docs_drift.sh` will auto-flag
module-to-doc drift. When it fires: update the doc now, or reply noting why the
change is trivial. Do not silently skip.

## How this project is shaped

- **Two entrypoints coexist.** `main.py` (FastAPI) runs the FAQ automation
  endpoint + SSU scheduler on port 2303-ish. `modules/system_detection/chatbot.py`
  (Flask) is what `Dockerfile.prod` and `modal_app.py` actually run — it's the
  user-facing chatbot endpoint. When asked "which is the app?", the answer
  depends on what's deployed. Do not assume.
- **`core/app_controller.py` is broken/legacy.** It mixes FastAPI
  `include_router` with Flask `register_blueprint` on the same object. Not
  imported anywhere active. Don't "fix" it without asking — it may be on a
  removal path.
- **Comments are mixed English + Indonesian.** Follow the surrounding style of
  the file you're editing. Don't translate existing comments.
- **Config is centralized in `core/app_config.py`.** Every env key routes
  through the `Config` dataclass. When adding a key, add it there AND to
  `docs/ops/env_reference.md` in the same turn.

## Running things

- Dev API (FastAPI, FAQ + SSU): `uvicorn main:app --host 0.0.0.0 --port 2303 --reload`
- Chatbot (Flask, prod-style): `python -m modules.system_detection.chatbot`
- Token generate service: `python -m modules.token_generate.generate`
- Chat testing UI: `python -m modules.chat_testing_ui.ui_testing_app`

See `docs/ops/deployment.md` for Docker, Modal, and production specifics.
