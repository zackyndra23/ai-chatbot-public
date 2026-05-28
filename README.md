# 🤖 RAG Chatbot v01

## Getting started

Modular Retrieval-Augmented Generation (RAG) chatbot system designed for FAQ automation, token-based session generation, meeting arrangement, and intelligent intent routing.

## Add your files

- [ ] [Create](https://docs.gitlab.com/ee/user/project/repository/web_editor.html#create-a-file) or [upload](https://docs.gitlab.com/ee/user/project/repository/web_editor.html#upload-a-file) files
- [ ] [Add files using the command line](https://docs.gitlab.com/topics/git/add_files/#add-files-to-a-git-repository) or push an existing Git repository with the following command:

```
## 📂 Project Structure

rag_chatbot_v01/
│
├─ modules/
│  └─ faq_automation/
│     ├─ __init__.py
│     ├─ faq_controller.py        # HTTP layer
│     ├─ faq_service.py           # business/orchestration + domain errors
│     ├─ faq_global.py            # konstanta domain-only (bukan ENV)
│     ├─ faq_mongo_repo.py        # akses Mongo (faq_text, faq_chunk)
│     └─ faq_pipelines.py         # ingest/build_index/query steps
│
│  └─ token_generate/
│     ├─ __init__.py
│     ├─ tg_controller.py         # Blueprint: 2 endpoint POST
│     ├─ tg_service.py            # Orkestrasi, validasi trigger
│     ├─ tg_repo.py               # Akses Mongo + index + upsert array nested
│     ├─ tg_pipelines.py          # APScheduler: auto-deactivate
│     ├─ tg_utils.py              # Helper timezone Asia/Jakarta & .env
│     └─ generate.py              # Entry point mandiri (Flask + scheduler)
│
│  └─ chat_testing_ui/
│     ├─ __init__.py
│     ├─ ctu_service.py           # baca env & siapkan header/base-url
│     ├─ ctu_controller.py        # Blueprint + route UI
│     ├─ ui_testing_app.py        
│     └─ templates
│     	  └─ ui_testing.html      # HTML+JS minimal (tanpa simpan apa-apa)
│
│  └─ system_detection/
│     ├─ __init__.py
│     ├─ sd_controller.py         # HTTP/controller tipis utk /chat
│     ├─ sd_service.py            # orchestration "Chat First Classification (CFC)"
│     ├─ sd_prompts.py            # prompt templates utk intent/reformulate/OOC reply
│     ├─ sd_policies.py           # aturan/threshold, keyword trigger meeting, dll
│     ├─ sd_state.py              # Pydantic dataclass utk LangGraph State
│     ├─ sd_nodes.py              # implementasi node LangGraph (sanitize, intent, retrieve, etc.)
│     ├─ sd_router.py             # LangGraph builder + conditional edges
│     ├─ sd_repo.py               # repo utk chat_history, run_logs
│     ├─ sd_vector_repo.py        # adaptor retriever (FAISS/PGVector/etc.)
│     ├─ sd_types.py              # type hints (Chunk, RetrievalHit, etc.)
│     └─ chatbot.py              
│
│        └─ meeting_arrangement/          # <— fitur meeting dipisah rapi di sini
│           ├─ __init__.py
│           ├─ ma_controller.py           # (opsional) endpoint khusus meeting (start/propose/confirm)
│           ├─ ma_service.py              # orkestrasi meeting: parse → pilih sales → compose reply
│           ├─ ma_policies.py             # aturan & trigger: command/keyword; jam kerja; lunch break
│           ├─ ma_prompts.py              # prompt: start, propose, confirm/reschedule
│           ├─ ma_repo.py                 # akses Mongo: sales_profiles, sales_slots (+ booking atomik)
│           ├─ ma_utils.py                # parse/format WIB, validasi window, helper fairness
│           └─ ma_types.py                # Pydantic/TypedDict: Slot, Proposal, Candidate, Booking   
│
│  └─ googlesheet_chat_history/
│     ├─ __init__.py		   
│     ├─ gsch_client.py           # lazy singleton to open the target worksheet (with auto-create)
│     ├─ gsch_repo.py             # row appender (header ensure + coercion)
│     └─ gsch_utils.py            # feature flag (on/off)
│
├─ vector_data/
│   └─ crisp_faq_openai                    
│
├─ secrets/
│   ├─ .env.example
│   └─ sa.json                    # service account Google
│
├─ infra/
│   ├─ app_repo.py                # koneksi Mongo, vector, factory repositories
│   └─ app_http.py                # Session + retry (opsional)
│
├─ core/
│   ├─ app_config.py              # semua env-driven config, termasuk FAQ defaults
│   ├─ app_controller.py          # register blueprints
│   ├─ app_service.py             # build Services (DI)
│   ├─ app_pipelines.py           # build pipelines & adapters
│   ├─ app_logging.py             # global JSON logging
│   └─ app_error.py               # global error handlers & base AppError
│
├─ app.py
├─ gunicorn.py                    
├─ requirements_chatbot_v01.txt
├─ docker-compose.yml
├─ .dockerignore
├─ .gitignore
├─ .gitlab-ci
├─ Dockerfile.dev
└─ Dockerfile.prod

```
cd existing_repo

HEAD
git remote add origin https://gitlab.integrity-asia.com/ai-projects/rag_chatbot_claude_v01_01.git
git branch -M main
git push -uf origin main
```

## Integrate with your tools


HEAD
- [ ] [Set up project integrations](https://gitlab.integrity-asia.com/ai-projects/rag_chatbot_claude_v01_01/-/settings/integrations)

## Collaborate with your team

- [ ] [Invite team members and collaborators](https://docs.gitlab.com/ee/user/project/members/)
- [ ] [Create a new merge request](https://docs.gitlab.com/ee/user/project/merge_requests/creating_merge_requests.html)
- [ ] [Automatically close issues from merge requests](https://docs.gitlab.com/ee/user/project/issues/managing_issues.html#closing-issues-automatically)
- [ ] [Enable merge request approvals](https://docs.gitlab.com/ee/user/project/merge_requests/approvals/)
- [ ] [Set auto-merge](https://docs.gitlab.com/user/project/merge_requests/auto_merge/)

## Test and Deploy

Use the built-in continuous integration in GitLab.

- [ ] [Get started with GitLab CI/CD](https://docs.gitlab.com/ee/ci/quick_start/)
- [ ] [Analyze your code for known vulnerabilities with Static Application Security Testing (SAST)](https://docs.gitlab.com/ee/user/application_security/sast/)
- [ ] [Deploy to Kubernetes, Amazon EC2, or Amazon ECS using Auto Deploy](https://docs.gitlab.com/ee/topics/autodevops/requirements.html)
- [ ] [Use pull-based deployments for improved Kubernetes management](https://docs.gitlab.com/ee/user/clusters/agent/)
- [ ] [Set up protected environments](https://docs.gitlab.com/ee/ci/environments/protected_environments.html)

***

## 2. Create and activate a virtual environment

python -m venv .venv
source .venv/bin/activate     # for Linux/Mac
# or
.\.venv\Scripts\activate      # for Windows

## 3. Install dependencies

pip install -r requirements_chatbot_v01.txt

## 4. Configure .env file
cp secrets/.env.example .env

# 🚀 How to Run

## 🧩 1. Run the FAQ Automation API

Launch the chatbot FAQ module using Uvicorn:
uvicorn app:app --host 0.0.0.0 --port 2303 --reload

This runs the core FAQ automation service for RAG-based question answering.

## 🔑 2. Run the Token Generator (for api_key_user and session_id)

Generate API keys and session tokens for chatbot access:
python -m modules.token_generate.generate

This script handles user token creation, validation scheduling, and auto-expiry management.

## 💬 3. Run the Chat Testing UI

Start the lightweight UI testing interface for chatbot interaction:
python -m modules.chat_testing_ui.ui_testing_app

## 🧠 4. Run the Chatbot API

Launch the main chatbot runtime with full intent detection, retrieval, and meeting orchestration features:
python -m modules.system_detection.chatbot

- Chat First Classification (CFC)
- Meeting Arrangement Agent (Sales Booking)
- Vector-based FAQ retrieval
- Out-of-Context (OOC) response handling

## 🧾 Notes

- Default timezone: Asia/Jakarta
- All modules share .env config via core/app_config.py
- MongoDB, Google Sheets, and vector data are injected via infra/app_repo.py
- LangGraph workflow is used for modular orchestration in system_detection/

## GPU Deployment Notes

- Host must have NVIDIA drivers installed.
- Install NVIDIA Container Toolkit so Docker can run GPU containers.
- docker compose must request GPUs (see `docker-compose.yml`), and set:
  - `NVIDIA_VISIBLE_DEVICES=all`
  - `NVIDIA_DRIVER_CAPABILITIES=compute,utility`
