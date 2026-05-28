# Documentation Index — RAG Chatbot v01

A modular Retrieval-Augmented Generation (RAG) chatbot system: FAQ automation,
token-based session management, intent routing, meeting arrangement, service
agent flows, and out-of-context handling.

## How to use these docs

- **Start here if you're new:** [`ARCHITECTURE.md`](ARCHITECTURE.md) — big picture.
- **Building/fixing a module:** [`modules/<name>.md`](modules/) — one file per module.
- **Calling an endpoint:** [`api/<group>.md`](api/) — auth, request/response schemas.
- **Deploying / running / debugging:** [`ops/`](ops/) — deployment, env reference,
  schedulers, GPU setup, troubleshooting.

## Table of contents

### Big picture
- [Architecture](ARCHITECTURE.md) — system overview, request lifecycle, data flow, components

### Modules
- [`chat_payload`](modules/chat_payload.md) — reusable chat-message payload builders
- [`chat_testing_ui`](modules/chat_testing_ui.md) — lightweight browser UI for QA
- [`chat_with_history`](modules/chat_with_history.md) — conversation history & summary handling
- [`faq_automation`](modules/faq_automation.md) — FAQ ingestion → chunk → KB rebuild
- [`googlesheet_chat_history`](modules/googlesheet_chat_history.md) — optional Sheets mirror of chat logs
- [`late_response_followup`](modules/late_response_followup.md) — re-engagement when users go idle
- [`out_of_context`](modules/out_of_context.md) — OOC classifier + response shaper
- [`sales_slots_update`](modules/sales_slots_update.md) — Mongo → Sheets sales availability sync
- [`service_agent`](modules/service_agent.md) — structured multi-step service flows (EBS, quotation, etc.)
- [`system_detection`](modules/system_detection/index.md) — the main chatbot: intent, retrieval, orchestration
  - [`meeting_arrangement`](modules/system_detection/meeting_arrangement.md) — sales meeting booking flow
- [`token_generate`](modules/token_generate.md) — user API keys + session tokens + auto-deactivate
- [`vector_build`](modules/vector_build.md) — Chroma KB build + atomic swap

### API reference
- [`api/faq.md`](api/faq.md) — FAQ ingestion / KB rebuild trigger
- [`api/chat.md`](api/chat.md) — main chatbot, service-agent, OOC, UI testing proxy
- [`api/token.md`](api/token.md) — userId & sessionId generation
- [`api/sales_slots_update.md`](api/sales_slots_update.md) — manual SSU trigger

### Operations
- [`ops/deployment.md`](ops/deployment.md) — Docker (dev/prod), Modal, GitLab CI
- [`ops/env_reference.md`](ops/env_reference.md) — every `.env` key, grouped by module
- [`ops/schedulers.md`](ops/schedulers.md) — APScheduler jobs + their triggers
- [`ops/gpu_setup.md`](ops/gpu_setup.md) — CUDA / NVIDIA container toolkit
- [`ops/troubleshooting.md`](ops/troubleshooting.md) — known failure modes + fixes

### Design specs
- [`superpowers/specs/`](superpowers/specs/) — brainstorming spec docs (design records)

## Regenerating Word (.docx) exports

`docs/` is canonical markdown, tracked in git. Word exports are generated on
demand to `docs/exports/` (gitignored):

```bash
python scripts/docs_export.py --section all         # everything, one big .docx
python scripts/docs_export.py --section architecture
python scripts/docs_export.py --section modules
python scripts/docs_export.py --section api
python scripts/docs_export.py --section ops
```

Uses `pandoc` if installed (best fidelity), falls back to `python-docx`.

## Keeping docs fresh

See the **"Documentation freshness"** section of `CLAUDE.md` at the repo root,
and the Stop hook at `.claude/hooks/check_docs_drift.sh`. Rule of thumb: when
code in `modules/<X>/` changes, `docs/modules/<X>.md` changes in the same turn.
