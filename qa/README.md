# QA Harness — Anti-Redundancy Stage (2026-05-11)

End-to-end QA suite exercising all 4 `REDUNDANCY_METHOD` modes against a
running Flask server. Captures diversity / latency / regression metrics and
produces a comparison Excel report.

## Prerequisites

1. **Flask chatbot running** on `http://localhost:2305` (or override via
   `QA_TARGET_URL`).
2. **Mongo & Chroma initialized** — same Mongo URI as the chatbot, KB
   rebuilt via `/aitegrity-core/knowledgebase-rebuild` so every chunk has
   `metadata.chunk_id`.
3. **Env vars set**: `MONGO_URI`, `MONGO_DB`, `API_KEY`, `API_HEADER_NAME`,
   `CHAT_HISTORY_COLL` (or use defaults).
4. **Dev deps installed**:
   `pip install -r requirements-dev.txt`.

## Running the full suite

```bash
python qa/scripts/run_qa_suite.py
```

The orchestrator will, **for each of the 4 methods**:

1. Pause and ask you to set `REDUNDANCY_METHOD=<method>` in `.env` and
   restart Flask.
2. Wait for you to press ENTER.
3. Run pytest against the running server, writing per-test results to
   `qa/runs/<timestamp>/method_<name>.jsonl`.

After all 4 methods complete, an Excel workbook lands at
`qa/test-cases/master_test_cases.xlsx`.

## Targeting non-localhost (staging / prod)

```bash
python qa/scripts/run_qa_suite.py \
  --target http://10.30.40.155:2305 \
  --allow-prod
```

`--allow-prod` is **mandatory** for any non-localhost target. The harness
refuses silently otherwise — this is the production protection rail.

## Single-method runs

```bash
python qa/scripts/run_qa_suite.py --method mmr
```

Skips the "manually restart Flask" prompt (presumes you've already set it up).

## Reading the Excel output

| Sheet | Purpose |
|---|---|
| Summary | Run metadata + total counts per method |
| Test Cases | Catalog of all test scenarios |
| Results — Normal / MMR / Fuzzy / Embedding | Detailed pass/fail per method |
| Comparison | Side-by-side metric delta per case |
| Performance | p50/p95/p99/max latency per method |
| Verdict | Recommendation per method (improved / no change / regressed) |

## Cleaning up QA Mongo state

```bash
python qa/scripts/cleanup_qa_sessions.py --dry-run    # preview
python qa/scripts/cleanup_qa_sessions.py --confirm    # actually delete
```

Filters by `sessionId regex ^qa-` — only QA-prefixed sessions, never real users.

## Troubleshooting

**ConnectionError to localhost:2305** — Flask not running. Start with
`python -m modules.system_detection.chatbot`.

**`KB checksum drifted mid-run`** — someone triggered a KB rebuild while
the harness was running. Wait for it to finish, re-run.

**`extras.retrieval_method = None` on audit** — Flask was restarted but
`REDUNDANCY_METHOD` env var wasn't updated; or Task 20 wiring missing for
a particular code path. Check `.env` and the relevant `audit_llm_call`
site in `sd_service.py`.

**All Module B/C/D tests SKIP under normal** — by design. They only assert
under non-normal methods.
