# Module — `out_of_context`

OOC (Out-of-Context) response engine for the chatbot. Detects user messages that fall outside qualification scope, routes them to the appropriate handler or contact, and re-anchors the user to their active qualification flow.

Stage 0 extension (2026-05-13) — see `docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md` for full design.

## Purpose

Two entry points:
- **`OOCService.handle(ctx)`** (NEW, Stage 0): 14-category classifier + 5-shape renderer with explicit `OOCContext` contract. Returns `OOCResult` or `None`.
- **`OOCService.maybe_handle(user_text, language_code)`** (LEGACY): 2-category keyword classifier. Preserved for existing call sites until they migrate.

## Public API

```python
from modules.out_of_context.ooc_service import OOCService
from modules.out_of_context.ooc_types import OOCContext

svc = OOCService()

# Stage 0 entry — explicit data contract
ctx = OOCContext(
    user_text="I want to partner with Integrity",
    user_detected_language="en",
    raw_detected_language="en",
    raw_detection_confidence=0.95,
    active_service=None,            # cold-start vs mid-flow
    current_field_id=None,
    last_question_text=None,
    pre_data=False,
    high_stakes_intake=False,
    previously_seen_OOC_in_session=0,
    previous_user_ooc_categories=[],
    previous_system_meta_actions=[],
    ooc_escalation_suppression_remaining=0,
)
result = svc.handle(ctx)
# result is OOCResult | None
# - None  → message is not OOC; pass through to existing dispatcher
# - OOCResult → render result.message to user; orchestrator applies state mutations

# Legacy entry — keyword-only, freelance/partnership
result_legacy = svc.maybe_handle(user_text="...", language_code="en")
```

## Pipeline (`handle()`, Layer B per spec §1.2)

```
ctx
 │
 ├── B1: OOCClassifier.classify(text, lang, active_service) → OOCDecision
 │     - Step 1: too-short input → OOC-UNCLEAR (cold-start only)
 │     - Step 2: legacy intent-phrase strict (FREELANCE / PARTNERSHIP)
 │     - Step 3: new 5 strict-keyword categories
 │     - Step 4: in-scope protection (Constraint #4) — return yes=False
 │     - Step 5: LLM classifier for fuzzy categories (gated by OOC_MODE)
 │     - Step 6: keyword-only fallback for fuzzy categories
 │
 ├── B2: consecutive-OOC escalation gate
 │     if previously_seen + 1 >= OOC_ESCALATION_THRESHOLD:
 │         return escalation_handover result
 │
 ├── B3: determine shape
 │     - active_service is None     → cold_start
 │     - pre_data                   → mid_flow_pre_data    (overrides high_stakes)
 │     - high_stakes_intake         → mid_flow_high_stakes
 │     - else                       → mid_flow_standard
 │
 ├── B4: OOCRenderer.render(category, shape, lang, vars)
 │     - i18n loader resolves text + applies template_variant_for_lang
 │     - bidi wrap routing assets + extracted vars when RTL lang
 │
 └── B5: assemble OOCResult with typed OOCAuditMetadata
```

## File layout

| File | Responsibility |
|---|---|
| `ooc_types.py` | Pydantic schemas: `OOCContext`, `OOCAuditMetadata`, `OOCDecision`, `OOCResult`. Plus legacy `OOCLabel` + `LEGACY_LABEL_MAP`. |
| `ooc_classifier.py` (NEW) | `OOCClassifier` — 14-category hybrid (keyword + LLM). Constraint #4 in-scope protection via `_matches_active_service_terms`. |
| `ooc_renderer.py` (NEW) | `OOCRenderer` — shape-aware rendering. Calls i18n loader; applies bidi wrap + template_variant_for_lang. |
| `ooc_service.py` | `OOCService.handle()` Layer B pipeline + legacy `maybe_handle()` shim. |
| `ooc_policies.py` | Keyword banks + `IN_SCOPE_SERVICE_TERMS` for Constraint #4 + legacy `OOCPolicies` dataclass. |
| `ooc_controller.py` | (Pre-Stage-0) `OOCController` for legacy callers. Untouched in Stage 0. |
| `ooc_prompts.py` | (Pre-Stage-0) Legacy prompt templates. Untouched in Stage 0. |

## Categories (OOCCategory enum, 14 values)

13 user-facing + 1 system-meta. Keyword banks expanded 2026-05-19 to match
the canonical `Intent_Signal_Examples` table (12 specific categories + 1
catchall). See `modules/out_of_context/ooc_policies.py` — each category has
EN + ID coverage (other languages fall through the LLM classifier in
hybrid/llm mode). Fuzzy categories are checked in order
`ADJACENT-ISO → PERSONAL-ADVICE → CHITCHAT → ADJACENT-SERVICE` (most
specific first; generic `legal advice`/`do you offer` in ADJACENT-SERVICE
would otherwise swallow more specific personal/ISO queries).


| Category | Trigger | Shape variants |
|---|---|---|
| `OOC-PARTNERSHIP` | partnership / mitra / collaboration intent | cold_start + mid_flow_p1 |
| `OOC-FREELANCE` | freelancer applicant | cold_start + mid_flow_p1 |
| `OOC-MYSTERY-SHOPPER-APPLY` | mystery shopper applicant (NOT business commission) | cold_start + mid_flow_p1 |
| `OOC-CAREERS` | full-time / internship job seekers | cold_start + mid_flow_p1 |
| `OOC-ADJACENT-SERVICE` | service Integrity doesn't offer (tax, audit, legal, etc.) | cold_start + mid_flow_p1 |
| `OOC-ADJACENT-ISO` | ISO certification requests → pivot to ABMS E-Learning | cold_start + mid_flow_p1 |
| `OOC-PRESS-MEDIA` | journalists, interview requests | cold_start + mid_flow_p1 |
| `OOC-VENDOR-SUPPLIER` | vendor introductions, procurement | cold_start + mid_flow_p1 |
| `OOC-COMPLAINT` | service-quality concerns | cold_start + mid_flow_p1 |
| `OOC-PERSONAL-ADVICE` | personal legal / financial / health | cold_start + mid_flow_p1 |
| `OOC-CHITCHAT` | casual conversation | cold_start + mid_flow_p1 |
| `OOC-UNCLEAR` | ambiguous / too-short input | cold_start + mid_flow_p1 |
| `OOC-CATCHALL` | unclassifiable but plausibly business-relevant | cold_start + mid_flow_p1 |
| `ESCALATION-CONSECUTIVE-OOC` | streak threshold reached (system-meta) | escalation_handover |

## Shape variants (ShapeUsed enum, 5 values)

- `cold_start` — single paragraph; user has not started qualification
- `mid_flow_standard` — 3 paragraphs (P1 per-category + P2 re-anchor + P3 re-pose)
- `mid_flow_high_stakes` — 4 paragraphs (P1 + P2 + P3 + P4 escalation/urgent)
- `mid_flow_pre_data` — 3 paragraphs (P1 + P2 pre-data + P3 opt-in continuation)
- `escalation_handover` — 3 paragraphs (ack + handover contacts + resume offer)

## Constraint #4 in-scope protection

Critical mid-flow guard: legitimate qualification clarifications during `active_service` flow MUST NOT be re-classified as OOC.

Mechanism: `OOCClassifier._matches_active_service_terms(text, lang, active_service)` checks `IN_SCOPE_SERVICE_TERMS[active_service][lang]` BEFORE the LLM classifier fires.

Bank is intentionally narrow — only unambiguous in-scope terminology. Strict-keyword categories (FREELANCE, PARTNERSHIP, MYSTERY-SHOPPER-APPLY, CAREERS, PRESS-MEDIA, VENDOR-SUPPLIER, COMPLAINT) are evaluated BEFORE in-scope protection — explicit OOC intent during mid-flow still fires.

### Coverage (Phase 0)

**8 of 15 service lines** have explicit in-scope keyword banks:

| Service | Pillar | Tier rationale |
|---|---|---|
| `wbs` | Detection | High-traffic; well-established in-scope terminology |
| `ebs` | Prevention | High-traffic; well-established in-scope terminology |
| `due_diligence` | Prevention | High-traffic; well-established in-scope terminology |
| `mystery_shopping` | Detection | High-traffic; risk of OOC-MYSTERY-SHOPPER-APPLY false-positives |
| `corporate_fraud_investigation` | Mitigation | **High_stakes** (P4 routing) |
| `insurance_claim_investigation` | Mitigation | **High_stakes** (P4 routing) |
| `asset_tracing` | Mitigation | **High_stakes** (P4 routing) |
| `skip_tracing` | Mitigation | **High_stakes** (P4 routing) |

**7 services without explicit banks** — these have NO deterministic Constraint #4 layer:

- `kyc`, `abms_elearning` (Prevention)
- `market_survey` (Detection)
- `non_use_investigation`, `anti_counterfeit_investigation`, `parallel_trading_investigation`, `trademark_investigation` (Brand Protection)

**Coverage gap — explicit framing (per Phase 2 review):**

The in-scope keyword bank (`IN_SCOPE_SERVICE_TERMS[service_id][lang]`) and `OOC_LLM_CONFIDENCE_FLOOR=0.6` are TWO DISTINCT mechanisms — not one:

| Mechanism | What it does | Where it fires |
|---|---|---|
| In-scope keyword bank (Constraint #4 deterministic layer) | Pre-LLM. If text matches `IN_SCOPE_SERVICE_TERMS[active_service][lang]`, classifier returns `yes=False` with `reason="in_scope_protection"` — no LLM call, no further classification | `ooc_classifier.py` Step 4 |
| `OOC_LLM_CONFIDENCE_FLOOR` (general classifier threshold) | Post-LLM. If LLM returns OOC label with confidence < 0.6, classifier returns `yes=False` with `reason="llm_low_confidence_pass_through"` | `ooc_classifier.py` Step 5 |

For the 7 deferred services, mid-flow false-positive protection rests on:
1. **Classifier conservatism when `active_service != None`** — the LLM prompt passes `active_service` as context (`ooc_classifier.py` `_build_llm_prompt`), and the LLM is asked to return `NONE` if the message is "on-topic for the active service". This is the LLM's judgment, not a deterministic bank match.
2. The 0.6 confidence threshold as a secondary check on the LLM's output.

Neither is equivalent to a deterministic in-scope-term match. The 7 services are exposed to LLM misclassification false-positives in a way the 8 covered services are NOT.

**Rationale for the gap:** Phase 0 MVP scope. Writing per-service in-scope keyword banks is high-effort (requires SME-level vocabulary curation per service per language). Phase 0 prioritizes:
1. **Parity for all 4 `OOC_HIGH_STAKES_SERVICES`** — high consequence of false-positive OOC on a P4-routing flow. Locked by `test_all_4_high_stakes_services_have_in_scope_protection`.
2. **Highest-traffic Prevention/Detection services** that drive most qualification volume.

**TODO — Phase 1 monitoring (per spec §6.1 process gate):** after deployment, query `query_recording` for per-`active_service` `ooc_handler` rate; expansion priority order is determined by which deferred service shows the highest false-positive OOC rate. Suggested operator query:

```js
db.query_recording.aggregate([
  {$match: {stage: "ooc_handler", "extras.active_service": {$ne: null}}},
  {$group: {_id: "$extras.active_service", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

**Expansion criteria:** add a service's bank when production telemetry shows ≥1% false-positive OOC rate during that service's flow. Per spec §6.1 + §12 Risks, this is a Phase 1 empirical-tuning activity, NOT pre-deploy work.

## Env knobs

See `docs/ops/env_reference.md` "OOC engine" section for the 17 knobs.

Key behavior toggles:
- `OOC_MODE` — keyword / hybrid / llm (default: hybrid)
- `OOC_ESCALATION_THRESHOLD` — default 3 (escalate ON 3rd consecutive OOC)
- `OOC_ESCALATION_SUPPRESSION_TURNS` — default 3 (per-user-message countdown)
- `OOC_LLM_CONFIDENCE_FLOOR` — default 0.6
- `OOC_CATCHALL_FLOOR` — default 0.7 (higher than general LLM floor)

## Audit logging

Every successful `handle()` call writes a `query_recording` audit row with stage `ooc_handler` and full `OOCAuditMetadata` payload. Schema-validated (pydantic v2). ValidationError logs at `error` severity WITH raw_data — silent degradation = undetected schema drift.

See operator query examples in `docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md` §9.

### Audit schema — `downstream_route` extension (Task 12 / spec §1.1 line 164)

The `ooc_suppression_fallthrough` audit row's `extras.downstream_route` field has **6 deterministic values** in the implementation, expanding the spec's 3-value enumeration:

| Value | Source | When emitted |
|---|---|---|
| `sa_continuation` | spec §1.1 line 164 (happy path) | Dispatcher returned route="sa_continuation" |
| `faq_rag` | spec §1.1 line 164 (happy path) | Dispatcher returned route="faq_rag" |
| `general_agent` | spec §1.1 line 164 (happy path — incl. dispatcher's own internal-degradation fallback) | Dispatcher returned route="general_agent" |
| `none_returned` | **Spec extension** (Guardrail B failure-mode policy) | Dispatcher returned `(None, None)` |
| `unknown` | **Spec extension** (Guardrail B failure-mode policy) | Dispatcher returned `(None, <response>)` — defensive guard |
| `dispatcher_exception` | **Spec extension** (Guardrail B failure-mode policy) | Dispatcher raised — audit row written with `error` field populated BEFORE re-raise |

**Why the extension:** Spec §1.1 line 164 enumerates the 3 happy-path dispatcher routes but does not address dispatcher failure modes (raise / None-return / partial-return). Guardrail B during Task 12 review required explicit handling for all three failure modes with deterministic audit values. The 3 added values are policy refinement, not behavioral departure — happy-path semantics from §1.1 are unchanged.

**Dispatcher exception propagation policy (Task 12):**
- Dispatcher raises → audit row written FIRST with `downstream_route="dispatcher_exception"` and `error=str(exc)`, THEN original exception re-raised to upstream Flask handler. Counter decrement already happened (mutex'd to Step 2.5 entry).
- Dispatcher returns `(None, None)` → audit `downstream_route="none_returned"`; empty string returned to user (honest passthrough).
- Dispatcher returns degraded `(general_agent, "fallback")` → audit reflects route VERBATIM; response passed through as-is; no orchestrator-side transformation.

Source-of-truth comment block in `modules/system_detection/sd_orchestrator.py` (`_suppression_fallthrough` definition) enumerates all 6 values + rationale. Verified by `test_guardrail_b_*` tests in `tests/test_ooc_decision_tree.py`.

## Strict-additive guarantee (Approach 3)

The Stage 0 changes EXTEND the pre-existing 2-category module:
- Legacy `OOCLabel` Literal preserved (`"freelance" | "partnership" | "none"`)
- Legacy `maybe_handle()` method preserved with original signature
- Legacy fields on `OOCResult` (`triggered`, `decision`, `route`, `debug`) preserved with defaults
- `LEGACY_LABEL_MAP` translates old labels → new categories for migrating call sites

Existing call sites in `sd_service.py:5701` (cold-start) and `sd_service.py:1622` (mid-flow append-footer) continue working until they migrate to `process_user_message_with_ooc()` per Tasks 20-21.

## Gotchas

- LLM call is **always env-gated** by `OOC_MODE`. Never invoked unconditionally. Tests verify this via `test_keyword_mode_never_calls_llm`.
- `OOCResult` has NO `update_session_fallback_language` field (removed per spec revision Minor #1). Orchestrator owns state mutation. Tested via `test_ooc_result_does_not_have_update_session_fallback_language_field`.
- Polymorphic `extracted_hint`: single OOCDecision field, rendered as `{user_field_hint}` for OOC-CAREERS or `{engagement_reference}` for OOC-COMPLAINT (mutually exclusive — only one category fires per turn).
- Auto bidi wrap controlled by `auto_bidi_wrap_extracted_vars` schema flag per category. Routing-asset placeholders ALWAYS wrap in RTL flows (immutability per Constraint #6).
- `template_variant_for_lang` schema field can override the base YAML lookup with `<key>_<variant>`. Checked BEFORE per-lang fallback.

## Deferred Verification (Phase 0 — to be exercised at Tasks 23-24)

This ledger tracks behaviors NOT exercised by automated tests in the current chroma-untestable environment. Each entry is a smoke-test scenario to run in the chroma-enabled env at Tasks 23-24 (or expanded validation phase). When new wire-up tasks introduce additional unverified behaviors, append entries here.

| # | What needs verification | Introduced by | Smoke step | Expected pass criteria |
|---|---|---|---|---|
| 1 | Stage 0 wire-up at `sd_service.py:5701` produces valid chat-turn payload | Task 20 | Recipe Step 1: POST cold-start OOC "I want to partner with Integrity" | Response has `route="ooc_agent_stage_0"`, partnership URL + Indo email in text, no `{` placeholders |
| 2 | Cold-start OOC in Indonesian renders correctly via i18n loader | Task 20 | Recipe Step 2: POST "saya ingin jadi freelancer" | Indonesian text with "Anda" formal pronoun, `route="ooc_agent_stage_0"`, freelancer URL substituted |
| 3 | Decision 2 `return_none_on_non_ooc_passthrough=True` produces correct pass-through with real handle_chat | Task 20 | Recipe Step 3: POST non-OOC cold-start ("tell me about your services") | Response routes through RAG/picker (`route="system_detection"`); NO `ooc_handler` audit row for this session |
| 4 | `OOC_AGENT_ENABLED=off` rollback is byte-identical to pre-Task-20 behavior | Task 20 (Decision 4) | Recipe Step 4: Set `OOC_AGENT_ENABLED=off`, restart, POST partnership intent | Response has `route="ooc_agent"` (legacy, NOT `"ooc_agent_stage_0"`), legacy English partnership template, NO `ooc_handler` audit row |
| 5 | Stage 0 classifier does NOT false-positive on benign cold-start text | Task 20 (Decision 2 + Constraint #4) | Recipe Step 5: POST "what is whistleblowing" | Response is RAG/picker (NOT OOC); NO `ooc_handler` audit row |
| 6 | `ooc_handler` audit row schema fields (incl. Task 20 additions `downstream_sd_stage`) reach Mongo correctly | Task 20 | After Step 1, query `db.query_recording.find({sessionId, stage: "ooc_handler"})` | All 22 audit fields present in `extras` dict; `downstream_sd_stage` is `null` |
| 7 | `ooc_suppression_fallthrough` audit row schema (10 fields incl. `phase0_legacy_fallback`) reaches Mongo correctly | Task 20 (Decision 3) | After persistence wire-up (Phase 1), simulate `suppression_remaining > 0` at cold-start | Audit row has `phase0_legacy_fallback=true`, all 10 fields present, `downstream_route="phase0_legacy_passthrough"` |
| 8 | D.6.1 persistence gap behavior — orchestrator state mutations are discarded post-turn in Phase 0 | Task 20 (D.6.1 limitation) | Trigger 3 consecutive cold-start OOC turns; verify escalation does NOT fire (counter resets between messages) | NO `ooc_handler` row with `streak_classification="system_meta"` or `category="ESCALATION-CONSECUTIVE-OOC"` — counter never accumulates |
| 9 | Mid-flow OOC composite REPLACES SA reply when Stage 0 fires (Task 21 architectural shift per spec Q#5) | Task 21 | Active SA flow + send "I want to be a freelancer": verify response is 3-paragraph composite, NOT SA reply + footer | Response is mid_flow_standard composite (P1+P2+P3); `route` may stay as SA's original but `message.content.text` shows composite; audit `ooc_handler` row has `shape_used="mid_flow_standard"` |
| 10 | Mid-flow state persistence end-to-end — orchestrator mutations persist across messages via SA_ENGINE.repo | Task 21 (Decision 1 d2) | 3 consecutive mid-flow OOC turns: verify counter reaches 3 + escalation fires on 3rd | Audit row on 3rd OOC turn has `category="ESCALATION-CONSECUTIVE-OOC"`, `streak_classification="system_meta"`, `set_escalation_suppression=True`. Mongo doc shows `ooc_excursion_count=3`. |
| 11 | Mid-flow suppression dispatcher integration — closure captures SA reply correctly | Task 21 (Decision 4) | After mid-flow escalation in step 10, send 1 more message in same session: verify counter decrements to 2, response is SA reply (NOT composite), audit row records `downstream_sd_stage="sa_compose"` | Suppression audit row: `downstream_route="sa_continuation"`, `downstream_sd_stage="sa_compose"`, `suppression_remaining_pre=3`, `suppression_remaining_post=2`. Counter persists. |
| 12 | Q#5 latent infrastructure intact — `_build_sa_post_footer` helper body unchanged for future secondary-OOC | Task 21 (Decision 5) | Verify `_build_sa_post_footer` source body unchanged from pre-Task-21 (only invocation gated). Future Q#5 secondary-OOC work can re-enable it. | Source diff: `_build_sa_post_footer` body byte-identical pre/post Task 21. Only call site at `:5685` is conditionally gated. |
| 13 | Double-fire prevention — flag=on prevents Stage 0 composite + legacy OOC append from both firing | Task 21 (Decision 5) | Send mid-flow message that triggers BOTH Stage 0 OOC + intent-phrase match (e.g., "saya mau jadi freelancer" during active flow) | Audit `ooc_handler` row exists (Stage 0 fired). Response text contains composite ONLY — NOT composite + appended legacy OOC reply. `_build_sa_post_footer` not invoked (verified by absence of legacy-style "{url}" template artifacts). |
| 14 | Flag=off byte-identical legacy behavior at mid-flow — no double quotation, no Stage 0 interference | Task 21 (Decision 5 corrected) | Set `OOC_AGENT_ENABLED=off`, restart, send mid-flow message with both quotation request AND intent phrase | Single quotation footer + single legacy OOC footer appended to SA reply (byte-identical to pre-Task-21). `_build_sa_quotation_footer` NOT invoked. NO `ooc_handler` or `ooc_suppression_fallthrough` audit rows. |
| 14b | Explicit runtime quotation-footer count assertion (Task 23 attention note from Task 21 review) | Task 21 (User review) | Send a mid-flow quotation request ("berapa biaya untuk EBS?") in flag=off mode; count occurrences of the quotation-footer signature string in response | Quotation footer string appears EXACTLY ONCE in response (not 0, not 2). Confirms structural mutual exclusivity translates to runtime mutual exclusivity. Operator query: regex-count of quotation-template fragments in `query_recording.message`. |
| 15 | `downstream_sd_stage_hint` API kwarg backward-compat (Tasks 11-13 callers work without modification) | Task 21 (Decision 4) | All 246 existing tests pass without signature update — verified pre-deploy | Tests pass (already verified). Production-side: any internal caller that omits the kwarg gets `downstream_sd_stage="unknown"` in audit row. |
| 16 | Mid-flow extra Mongo round-trip on `get_state` (Phase 1 optimization opportunity) | Task 21 (Phase 1 ledger) | Instrumentation: count `get_state` invocations per session-turn | Phase 1 telemetry to be added; decision driven by observed DB latency. |
| 17 | Greeting palette renders correctly in Indonesian via i18n loader | Task 14 | Mid-session POST with empty service state, `language_code=id` (first turn) | Response opens with one of 12 lifted id phrases from `greeting.palette[id]` (e.g., "Halo", "Hai", "Selamat pagi"); NOT "Hello" or legacy English |
| 18 | Opener guidance block renders with id banned-forms gating in flag-on | Task 15 | Trigger SA Sentence-1 in Indonesian via active service flow with confirmed user msg | Response opener is one of the 13 lifted id palette entries; "Baik" / "Baiklah" do NOT appear; flag-on path verified |
| 19 | Rescue soft-bridge renders mid-flow when natural-qual triggers | Task 16 | Drive Method B natural-qual rescue path (3 consecutive empty turns on same min-set field) in id session | Response contains "Biar saya bisa lanjut bantu, boleh saya konfirmasi langsung —" prefix + the field's decision-tree question text (q placeholder substituted) |
| 20 | Picker labels render correctly via i18n in user lang (4 keys × 14 langs) | Task 17 | Hit cross-service bridge in Indonesian session (SA_STAY picker) — verify both stay + switch labels | stay label: "Lanjut {current_service}", switch label: "Pindah ke {target_service}"; both with {current_label}/{target_label} substituted per i18n template |
| 21 | Meeting footer renders correctly via i18n in supported langs | Task 18 | Send meeting-arrangement intent ("jadwalkan meeting") in id session | Response includes `meeting.footer.id` text with "tim Sales" + "+62 21" + "info@integrity-asia.com" |
| 22 | Romansh (rm) partial coverage exercises gracefully | Task 18 (Phase 0 limitation) | Synthetic rm session — send meeting intent | Footer text in Romansh; greeting/opener/rescue/picker labels in English (fall-back per CANON_17 exclusion) |
| 23 | `build_meeting_picker_preamble` legacy path STILL serves correctly (not yet migrated) | Task 18 (deferred per Phase 0 limitation) | Session reaches meeting-arrangement picker preamble | Preamble text in user lang via legacy if/elif chain; no i18n loader call attempted |
| 24 | Picker helpers (`_book_meeting_label`, `_other_services_label`, `_stay_switch_labels`) inline safety fallback triggers correctly when i18n raises | Task 19 partial | Force i18n loader unavailable (test fixture or break schema temporarily) | Helpers return inline English baseline ("Schedule a meeting", "Other Services", "Continue X" / "Switch to Y") — no exception escapes; no crash |
| 25 | Legacy palette dicts retained — `_GREETING_PALETTE` / `_OPENER_PALETTE` / `_BANNED_OPENERS_BY_LANG` / `RESCUE_SOFT_BRIDGE` still importable + non-empty | Task 19 partial | Source-level grep + Python import smoke | All 4 dicts still in source with DEPRECATED-marker comment; Phase 1 cleanup tracked as separate ledger entry |

## Phase 1 optimization opportunities (surfaced during Task 21)

Not limitations — design costs accepted in Phase 0 with clear migration path for Phase 1.

### Pre-SA OOC classification at mid-flow

**Where:** `modules/system_detection/sd_service.py:5683+` (Task 21 wire-up).

**Current behavior (Phase 0):** Mid-flow uses post-SA intercept. SA engine produces a reply; if Stage 0 then classifies OOC, the SA reply is **discarded** (overwritten by composite). Compute cost: SA LLM call ran for nothing on OOC mid-flow turns.

**Phase 1 optimization:** classifier-only pre-check BEFORE SA runs. If classifier returns OOC: skip SA entirely + run full orchestrator render. If non-OOC: run SA normally. Estimated savings: `~mid_flow_OOC_rate × SA_token_cost` per session per OOC turn.

**Telemetry signal (operator query):**
```js
// Count of audit rows where stage=ooc_handler AND prior turn had SA continuation
// (signals wasted SA compute on OOC mid-flow turn)
db.query_recording.aggregate([
  {$match: {stage: "ooc_handler", "extras.active_service": {$ne: null}}},
  {$group: {_id: "$extras.active_service", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

Phase 1 prioritization decided by per-active_service mid-flow OOC rate × estimated wasted token count. Phase 0 baseline: 0% savings; Phase 1 target depends on telemetry.

### Quotation logic consolidation between helpers

**Where:** `modules/system_detection/sd_service.py` — `_build_sa_quotation_footer` (Task 21 new helper) + `_build_sa_post_footer` (preserved per Q#5 latent infrastructure).

**Current behavior (Phase 0):** Quotation logic is duplicated across the two helpers. The new helper runs when `OOC_AGENT_ENABLED=on`; the old helper runs only when flag=off. Decision 5 preserves the old helper body unchanged for Q#5 future secondary-OOC detection.

**Phase 1 optimization:** consolidate when Q#5 secondary-OOC scope is fully defined. Either:
- Refactor old `_build_sa_post_footer` to delegate to new `_build_sa_quotation_footer` for quotation block (then add OOC-specific logic on top), OR
- Drop the new helper if Q#5 secondary-OOC requires the combined quotation+OOC behavior to stay together.

Decision deferred to Q#5 scoping in Phase 1.

### Romansh (`rm`) retain-vs-drop business decision

**Where:** `modules/system_detection/sd_meeting.py` (3 surfaces with Romansh translations lifted into `modules/i18n/strings/rm.yaml` at `status=draft` during Task 18).

**Current state:** Romansh is NOT in CANON_17 per spec §Constraint #7. Existing translations were lifted as-is (lift-and-shift policy) to avoid quality regression for Romansh users on meeting surfaces. Other surfaces fall back to English (see Known Limitations entry above).

**Resolution direction:**
- **Retain:** Extend CANON_17 to 18 langs (add `"rm"`). Add Romansh to OOC translation coverage (Phase 2b/c/d work). Update spec §Constraint #7 + i18n schema `required_for` lists.
- **Drop:** Remove Romansh from `sd_meeting.py` palette + delete `rm.yaml`. Reroute Romansh users to English at the SA layer.

**Decision criteria:** is Romansh a strategic locale for Integrity? Business owner input needed.

**Telemetry:** count of sessions with `detected_language` starting with `"rm"` in `query_recording` over the next month. If <1 session/week, drop is low-risk.

### Legacy palette dicts retained as Phase 0 safety net (Task 19 partial)

**Where:** `modules/system_detection/sd_prompts.py::_GREETING_PALETTE`, `modules/service_agent/sa_prompts.py::_OPENER_PALETTE` + `_BANNED_OPENERS_BY_LANG`, `modules/service_agent/natural_qual/nq_policies.py::RESCUE_SOFT_BRIDGE`.

**Current behavior (Phase 0):** Task 19 deleted the legacy if/elif chains inside picker-label + meeting-surface helpers (sd_service.py, sd_meeting.py — these are inline if/elif, low risk to remove). Task 19 KEPT the 4 legacy palette dicts (above) as runtime safety net during Phase 0.

**Why retained:** i18n loader is brand new + not yet smoke-tested in production. Removing the dicts now means helpers raise if the loader fails at runtime (bad YAML, infra issue). Inline safety-fallback code in each helper references these dicts. Keeping them costs minimal LoC (~150 lines of dead-ish code) but provides resilience.

**Phase 1 follow-up:** after Task 23-24 production smoke verifies i18n loader works reliably, delete the 4 retained dicts + replace the helper fallback branches with inline hardcoded English baselines (e.g., `palette = ["Hello"]` for greeting fallback). Estimated cleanup: ~150 LoC removed, ~30 LoC fallback replacement, +5 regression tests.

### `build_meeting_picker_preamble` migration deferred (Task 18 partial)

**Where:** `modules/system_detection/sd_meeting.py:216-` (`build_meeting_picker_preamble`).

**Current behavior (Phase 0):** Task 18 migrated 2 of 3 sd_meeting.py surfaces (`build_meeting_footer` + `build_other_slot_label`) to i18n loader. `build_meeting_picker_preamble` left UNCHANGED in the legacy if/elif chain.

**Why deferred:** the preamble template has per-lang structural variants — `nick_phrase` and `svc_phrase` are interpolated at different positions per language (e.g., Indonesian: "Saya dengan senang hati akan berdiskusi lebih lanjut{svc_phrase}{nick_phrase}" but other langs put them differently). Clean placeholder lift requires either:
- New schema field `template_variant_for_lang` (already exists from Task 8 — see spec D.6 row 11) applied per-lang to a sibling variant key, OR
- Multi-key approach: separate keys for the "with-nick", "with-svc", "with-both", "with-neither" combinations per lang

**Phase 1 follow-up:** define and execute the careful refactor for picker_preamble. Estimate: ~150 LoC schema/YAML/consumer + 8 tests. Defer pending Phase 1 SME availability for template-variant validation across 10 langs.

**Telemetry:** `build_meeting_picker_preamble` continues to serve correctly via legacy if/elif. No user-facing UX impact in Phase 0.

### Mid-flow extra Mongo round-trip on `get_state`

**Where:** `modules/system_detection/sd_service.py:5683+` (Task 21 wire-up) + SA engine internals.

**Current behavior (Phase 0):** Task 21 wire-up calls `SA_ENGINE.repo.get_state(session_id)` to load pydantic state for orchestrator interaction. The SA engine also loads its own state copy internally via `self.repo.get_state(session_id)` during turn processing. Two Mongo reads per mid-flow turn for the same doc.

**Phase 1 optimization:** consolidate via either:
- Passing the loaded pydantic state through `handle_from_question`'s handoff_bundle, OR
- Caching state at `handle_chat` scope (single read; both SA engine and orchestrator read from cache).

**Telemetry:** count `get_state` invocations per session-turn (would need new instrumentation in `sa_repo.py`). Decide based on per-request DB latency at scale.

## Known limitations (Phase 0 — surfaced during Tasks 13 + 20)

### Romansh (`rm`) partial coverage (surfaced during Task 14-19 pre-flight)

Users whose detected language is Romansh receive meeting-arrangement surfaces (footer, picker preamble, keyword detection) translated per legacy `sd_meeting.py` palette, but ALL other surfaces (greeting, opener, rescue, picker labels, OOC responses) fall back to English. Romansh is NOT in CANON_17 per spec §Constraint #7, so the OOC orchestrator's language fallback gate routes Romansh detection to `session_fallback_language` (typically `en`).

**Current state:** Partial — meeting surfaces in Romansh, everything else in English.

**Resolution path:** Phase 1 business-owner decision on retain (extend CANON_17 to 18 langs) vs drop (remove Romansh from sd_meeting.py palette). Tracked in Phase 1 follow-up ledger below.

### OOC state NOT persisted across messages (Task 20)

**Where:** `modules/system_detection/sd_service.py:5699+` (Stage 0 wire-up at cold-start). Each message instantiates a fresh `AgentSessionState`; orchestrator state mutations apply during the turn but are discarded after.

**Functional impact:**
- Streak counter never accumulates → DT-5 escalation cannot fire at cold-start
- `session_fallback_language` resets to `"en"` every message → T1-OOC-confident cold-start exception is effectively no-op
- Suppression counter resets to 0 every message → suppression-fallthrough at cold-start cannot fire (defensive code in D.6.2 path is unreachable in Phase 0)

**Telemetry path:** `query_recording` per-stage counts; once persistence lands, expect `ooc_handler` rows with `streak_classification=system_meta` (ESCALATION-CONSECUTIVE-OOC) to start appearing, and `ooc_suppression_fallthrough` rows with `phase0_legacy_fallback=true` to appear.

**Phase 1 follow-up:** wire OOC-state Mongo persistence keyed by `session_id`. Extend `sa_state` doc OR new `ooc_session_state` collection. Spec cross-ref: Appendix D.6.1.

### Suppression-fallthrough at cold-start uses Phase 0 legacy fallback (Task 20)

**Where:** `modules/system_detection/sd_service.py:5727+` (defensive code path inside the Stage 0 wire-up). If `state.ooc_escalation_suppression_remaining > 0` at cold-start (only possible after persistence lands per above limitation), the wire-up writes a `phase0_legacy_fallback=true` audit row and falls through to RAG without invoking either Stage 0 orchestrator or legacy `OOCService.maybe_handle()`.

**Why:** Step 2.5 in the orchestrator requires a `Dispatcher` Callable. The cold-start dispatcher would be the entire `:5739+` RAG/picker pipeline (~650 LoC of `handle_chat`). Extracting it requires touching chroma-coupled internals untestable in current env. Deferred to Phase 1.

**Telemetry query (Phase 1+):**
```js
db.query_recording.find({
  stage: "ooc_suppression_fallthrough",
  "extras.phase0_legacy_fallback": true
}).count()
```
Per-day count decides Phase 1 prioritization. Spec cross-ref: Appendix D.6.2.

**Phase 1 follow-up:** extract `:5739+` cold-start pipeline into `_run_cold_start_pipeline_after_ooc(text, state) -> tuple[route, response]` helper; pass as dispatcher to orchestrator's Step 2.5.

### Last-question text is English-only in mid-flow P2 re-orientation

**Where:** `modules/system_detection/sd_orchestrator.py::_resolve_question_text` — reads `FLOW_REGISTRY[service][field_id].text` which is English-only in the current `sa_flows` schema.

**Visible UX:** An Indonesian user mid-WBS-qualification who triggers an OOC response gets:
- P1 (per-category preamble): rendered in Indonesian ✅
- P2 (re-orientation): "Returning to your <span lang=id>Sistem Whistleblowing (WBS)</span> qualification — you were just at the <span lang=id>Jumlah Penanggung Jawab Kasus</span> step." ✅ (service + field labels translated via glossary)
- P3 (re-pose of last question): `"Jadi, untuk melanjutkan dari tempat kita berhenti — How many case handlers do you currently have?"` ⚠️ (re-pose text in Indonesian + question text in English — visible inconsistency)

**Why not fixed now:** `FLOW_REGISTRY` is keyed by field-id only; question text is a single string per field. Phase 0 made the pragmatic choice: re-pose English question literal inside a localized P3 template. The same question was originally asked in English to the user, so the re-pose is at least faithful to what they saw.

**Resolution direction (Phase 1 follow-up):**
- **Option A — Multi-lang question text in `FLOW_REGISTRY`:** Extend `QuestionStep` to `text_by_lang: dict[str, str]` or add a parallel `i18n` lookup keyed by `flow.{service}.{field}.question`. Largest blast-radius but cleanest end state.
- **Option B — Runtime LLM translation at orchestrator level:** `_resolve_question_text(service, field, lang)` calls Claude to translate the English question to user's language before injection. Cheaper to build, but adds 1 LLM call per mid-flow OOC turn.
- **Option C — Leave as-is and accept the gap:** Document expectation; Phase 1 telemetry from `query_recording` decides if user-reported UX issue rate justifies fix work.

Cross-reference: docstring of `_resolve_question_text` in `sd_orchestrator.py` explains the constraint inline and points back to this section. `tests/test_ooc_decision_tree.py::test_ooc_context_construction_*` exercise the OOCContext build path that consumes this; no test asserts P3 text language because that would require fixing it first.

## Testing conventions

### Monkeypatching `_`-prefixed internal functions is test-coupled (acknowledged)

The OOC orchestrator tests in `tests/test_ooc_decision_tree.py` monkeypatch several internal helpers (`_ooc_dispatch`, `_suppression_fallthrough`, `_run_posthoc_classifier_if_enabled`) to isolate concerns. This couples tests to internal function names — a rename triggers a test-target sweep.

**Policy (Phase 0):** when renaming an `_`-prefixed helper in `sd_orchestrator.py`, grep `tests/test_ooc_decision_tree.py` for the old name and update both the `monkeypatch.setattr(target_path, ...)` strings AND the lambda/def signature lines if the renamed function's parameter list also changed. Task 13 (`_ooc_dispatch_stub` → `_ooc_dispatch` rename) needed 8 monkeypatch target updates + 6 lambda/def signature updates.

**Phase 1+ improvement direction (not urgent):** extract testable seams (dependency injection for dispatcher already done in Task 12; could do the same for the post-hoc classifier helper to make tests target an interface rather than a function name). Defer until either (a) a refactor causes pain, or (b) the orchestrator grows additional internal helpers that need similar isolation.
