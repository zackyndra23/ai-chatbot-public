# Deployment

## Targets

Three deploy modes are supported. Pick the one that matches your environment:

1. **Local dev** — run directly with Python.
2. **Docker Compose on a GPU host** — the main production target, driven by GitLab CI.
3. **Modal serverless** — optional, runs the Flask chatbot on a Modal-managed GPU.

## Local dev

Install once:

```bash
python -m venv .venv
source .venv/bin/activate     # Linux/Mac
# or
.\.venv\Scripts\activate      # Windows

pip install -r requirements.cuda.lock   # or requirements.cpu.lock
cp .env.example .env                    # then edit
```

Run components:

```bash
# FastAPI admin app (FAQ ingest + SSU scheduler + health)
uvicorn main:app --host 0.0.0.0 --port 2303 --reload

# The actual user-facing chatbot (Flask)
python -m modules.system_detection.chatbot

# Token-generate service (Flask)
python -m modules.token_generate.generate

# Chat testing UI (Flask)
python -m modules.chat_testing_ui.ui_testing_app
```

Each uses its own port (`PORT_TG`, `PORT_UI_TEST`, `PORT_CHATBOT`) from env.

## Docker

### Images

`Dockerfile.prod` is a multi-stage build with two flavors:

| Stage | Base | Used for |
|---|---|---|
| `deps_cpu` → `runtime_cpu` | `python:3.12-slim` | CPU deployments |
| `deps_cuda` → `runtime_cuda` | `nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04` | GPU deployments (default) |

Both runtime stages run:

```dockerfile
CMD ["gunicorn", "--bind", "0.0.0.0:2300", "modules.system_detection.chatbot:app"]
```

So the container serves the **Flask chatbot app**, not the FastAPI `main.py`. Keep this in mind when debugging "why isn't `/aitegrity-core/faq-automation` working in prod?" — it isn't exposed in the prod container.

`Dockerfile.dev` is simpler (single-stage `python:3.12-slim`) and runs `python main.py` on port 2300 — used when you want the FastAPI admin surface in a container.

### docker-compose.yml

```yaml
services:
  rag_chatbot:
    image: ${RAG_REGISTRY_IMAGE}/rag-${RAG_FLAVOR}:${RAG_IMAGE_TAG}
    env_file: .env
    ports: ["2300:2300"]
    device_requests:
      - driver: nvidia
        count: ${RAG_GPU_COUNT:-0}
        capabilities: ["gpu"]
```

Driven by these env keys — see [`env_reference.md`](env_reference.md):
`RAG_REGISTRY_IMAGE`, `RAG_FLAVOR`, `RAG_IMAGE_TAG`, `RAG_GPU_COUNT`,
`NVIDIA_VISIBLE_DEVICES`, `NVIDIA_DRIVER_CAPABILITIES`.

### Build locally

```bash
# CUDA
docker build -f Dockerfile.prod --target runtime_cuda -t rag-cuda:local .

# CPU
docker build -f Dockerfile.prod --target runtime_cpu -t rag-cpu:local .
```

### Run locally (compose)

```bash
# Point RAG_IMAGE_TAG to :local in .env if testing a local build
docker compose up rag_chatbot
```

## GitLab CI pipeline

`.gitlab-ci.yml` defines two stages:

### Stage: `build`

1. **`lock-deps-cuda`** — ensures `requirements.cuda.lock` exists. If missing,
   runs `pip-compile` with pinned `pip<25` + `pip-tools>=7.4.1,<8`. Publishes
   the lock as a CI artifact (1-week retention).
2. **`deps-image-cuda`** — hashes `requirements.cuda.lock`, checks the
   registry for an existing `rag-deps-cuda:cu121-py312-<hash>` image. If
   absent, builds the `deps_cuda` stage and pushes. Otherwise skips.
3. **`app-image-cuda`** — builds `runtime_cuda` with the deps image as a
   cache-from layer. Pushes:
   - `$CI_REGISTRY_IMAGE/rag-cuda:$CI_COMMIT_SHORT_SHA`
   - `$CI_REGISTRY_IMAGE/rag-cuda:latest`

All `build` jobs trigger on the `Production` branch and any `task/*` branch.

### Stage: `deploy`

**`deploy-to-server`** — runs only on `Production`. Over SSH to the configured
host:

1. Logs into the registry.
2. Updates `RAG_IMAGE_TAG` (and optionally `RAG_FLAVOR`) in the remote `.env`.
3. `docker compose pull rag_chatbot && docker compose up -d rag_chatbot`.

### CI variables required

- `CI_REGISTRY`, `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD`, `CI_REGISTRY_IMAGE` — standard GitLab.
- `REGISTRY_PASSWORD` — passed through for SSH-side docker login.
- `SSH_PRIVATE_KEY`, `SSH_PORT`, `SSH_USER`, `SSH_HOST`, `DEPLOY_DIR` — SSH target.
- `RAG_FLAVOR` — optional, defaults to what's in the remote `.env`.

### Runner tags

All build jobs require runners with tags `[10.30.40.155, Alpine, Docker, Ubuntu]`.
Deploy uses `[10.30.40.155, Shell, Ubuntu]`.

## Modal serverless (optional)

`modal_app.py` (⚠️ gitignored per `.gitignore` — local-only development):

```python
@app.function(
    image=image,
    gpu=modal.gpu.L4(),
    secrets=[modal.Secret.from_name("rag-conflict-fixed-secrets")],
    timeout=60 * 30,
)
@modal.wsgi_app()
def flask_app():
    from modules.system_detection.chatbot import app as flask_app
    return flask_app
```

Deploy:

```bash
modal deploy modal_app.py
```

Secrets live in a Modal secret named `rag-conflict-fixed-secrets`.

## Secrets

- `secrets/.env` — gitignored. Copy from `.env.example`, then fill in keys.
- `secrets/sa.json` — Google service account. Gitignored.
- `.env.modal` — gitignored. Modal-specific overrides.

Never commit any of these. Rotate via your deployment process; do not rotate
by pushing new keys to git.

## Stage 3A rollout (per-service vector store split, 2026-05-07)

Deploy this code with `KB_BACKEND=legacy` (default) — zero behavior change.
Then progress through phases:

| Phase | Operator action | Validation gate |
|---|---|---|
| **0** | Code deployed, `KB_BACKEND=legacy` in production `.env` | Existing smoke pass; no regression |
| **1** | Operator flips `.env` to `KB_BACKEND=dual` and restarts Flask. Both backends build + serve; per-service primary, legacy fallback | `kb_build_divergence` audit event count = 0 over 24h |
| **2** | (Optional) Set `KB_DUAL_AB_SAMPLE_RATE=0.05` for 5% read-time divergence sampling | Read-time divergence rate < 1% |
| **3** | Flip `.env` to `KB_BACKEND=split`. Legacy collection retained on disk but not read | 24-48h observation, no error spike |
| **4** | Cleanup commit: drop `vector_data/legacy/`, remove `sd_vector_legacy.py`, remove dual-mode branches in `vb_service.py` and `sd_vector_repo.py` | Final regression pass |

Rollback at any phase: flip `KB_BACKEND` back to previous value (`dual` → `legacy`,
`split` → `dual`). Disk state for both backends is preserved through phase 4.

If first dual-mode start shows divergence (rare — happens only when Mongo state
has services not in legacy collection or vice versa), run
`POST /aitegrity-core/knowledgebase-rebuild` once to re-sync.

## Data persistence

### `vector_data/` — Chroma vector store (gitignored, container volume)

**Truth source:** `faq_update_doc` collection in MongoDB. `vector_data/` is a
runtime artifact rebuilt from Mongo via
`modules.vector_build.build_and_swap`.

**Why gitignored:** embeddings are model-specific (HF `MiniLM-L6` ≠ OpenAI
`text-embedding-3-large` ≠ etc.). Committing builds from one env breaks
retrieval on another env. Truth lives in Mongo; Chroma is regenerated.

**Why also `.dockerignore`:** images shouldn't ship stale binary
(3-50 MB). Image build copies code; Chroma is built per-deploy by the
container itself.

**Persistence between container restarts:** docker-compose mounts a named
volume `rag_chroma_data:/app/vector_data`. Restarting the container preserves
the build (fast cold-start). Removing the volume forces a rebuild on next
start.

### Auto-rebuild on first start (self-heal)

`modules/system_detection/chatbot.py:_ensure_vectorstore` checks Chroma doc
count after `bootstrap_vectorstore()`. If 0 (empty volume, first run, corrupt
state, or wrong embedding model), it calls `build_and_swap(force=True)`
automatically and re-bootstraps. **Deployer no longer needs to manually
trigger `/knowledgebase-rebuild` after deploy.**

Boot scenario matrix:

| Scenario | Behavior |
|---|---|
| Fresh container, fresh volume | bootstrap → empty count → auto-rebuild → re-bootstrap → ready |
| Restart, healthy volume | bootstrap → loaded count > 0 → log `kb_loaded_from_volume` → fast start |
| Restart, corrupt volume | bootstrap → empty count → auto-rebuild → ready |
| Mongo unreachable at startup | bootstrap → empty count → auto-rebuild fails → log warning, continue with empty KB. Operator retries via `POST /aitegrity-core/knowledgebase-rebuild` after fixing connectivity. |
| FAQ source updated mid-deploy | Auto-rebuild only on EMPTY Chroma. To pick up content updates: trigger `POST /aitegrity-core/faq-automation` (Sheet → Mongo → KB) or `/knowledgebase-rebuild` (Mongo → KB only). |

### Manual rebuild endpoints (FastAPI side)

- `POST /aitegrity-core/faq-automation` — full pipeline: Google Sheet → Mongo
  → KB. Skips KB build if checksum unchanged. Use after editing the FAQ
  Sheet.
- `POST /aitegrity-core/knowledgebase-rebuild` — KB-only, force=True. Use
  when Mongo source is fine but Chroma state is corrupt (e.g. mid-deploy
  recovery).

Auth + body for both: header `x-api-key: <cfg.API_KEY>`,
Content-Type `text/plain`, body literal `true` (= `cfg.TRIGGER_TRUE_VALUE`).

### Hot-reload limitation

The Flask chatbot caches `_vectorstore` in process memory at startup
(`bootstrap_vectorstore()` runs once). KB rebuilds **do not auto-refresh**
the running chatbot. To pick up rebuild output:
- Restart the chatbot container (`docker compose restart rag_chatbot`), OR
- Future improvement (not yet implemented): polling endpoint /
  `/reload-kb` / file watcher.

### Other persistent data

- `run_logs/` — gitignored, grows at runtime.
- `context/` — gitignored, local chat-context notes.
- `secrets/` — gitignored + dockerignored. Mounted at runtime via
  `./secrets:/app/secrets:ro` in docker-compose, OR provided as inline JSON
  via `GOOGLE_SERVICE_ACCOUNT` env (then the volume mount can be removed).

## Health checks

- `GET /health` exists on the FastAPI `main.py` (returns `{"status": "ok"}`).
- No dedicated health endpoint on the Flask chatbot — use the existing
  `/aitegrity-core/chatbot/claude4sonnet` endpoint with a throwaway API key to
  get a 401, which proves the app is up.

## Rollback

Rolling back via GitLab CI is manual:

1. Re-tag the previous known-good SHA: `docker pull <registry>/rag-cuda:<old-sha>` on the host.
2. Update `RAG_IMAGE_TAG` in the host `.env` to `<old-sha>`.
3. `docker compose up -d rag_chatbot`.

There is no automatic rollback trigger; the deploy job always deploys the
newest push.
