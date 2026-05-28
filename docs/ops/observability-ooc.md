# OOC Stage 0 — Post-Deploy Observability Cheat Sheet

MongoDB queries for verifying the OOC Response Engine (Stage 0, 2026-05-13) is firing correctly and for surfacing Phase 1 prioritization signals.

## Cross-references

- **Spec:** `docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md` (audit schema §7.4 + Appendix D.5)
- **Module doc:** `docs/modules/out_of_context.md` (Deferred Verification ledger + Phase 0 limitations + Phase 1 optimization opportunities)
- **Smoke recipe:** `qa/smoke/2026-05-13-ooc-stage-0-smoke-recipe.md` (post-deploy verification queue covering 26 ledger entries)

## How to use

Connect to MongoDB during the first 7 days post-deploy:

```powershell
$mongoUri = (Get-Content .env | Select-String "^MONGO_URI=").Line -replace "^MONGO_URI=", ""
mongosh $mongoUri
```

Run the queries below against the `query_recording` collection. Each query has expected output + interpretation guidance.

## Audit row stages — quick reference

| Stage | Written by | When | Schema |
|---|---|---|---|
| `ooc_handler` | `_apply_ooc_turn_and_audit` (`sd_orchestrator.py:687`) | OOC classified + composite rendered | 22 fields, all unconditionally present |
| `ooc_suppression_fallthrough` | `_write_suppression_audit_row` (`sd_orchestrator.py:353`) | `ooc_escalation_suppression_remaining > 0` at Step 2.5 | 10 fields, all unconditionally present |
| `language_fallback` | Orchestrator Step 2 | `raw_confidence < OOC_LANG_DETECTION_FLOOR` OR `raw_lang ∉ CANON_17` | 5 fields |
| `abandonment_handler` | Orchestrator Step 0 | Abandonment phrase matched | 3 fields |

## Queries

### 1. Stage 0 is alive — daily count of `ooc_handler` rows

```js
db.query_recording.aggregate([
  {$match: {stage: "ooc_handler"}},
  {$group: {_id: {$dateToString: {format: "%Y-%m-%d", date: "$timestamp"}}, count: {$sum: 1}}},
  {$sort: {_id: -1}}, {$limit: 7}
])
```

**Expected:** non-zero counts on days with chat traffic. Zero on a busy day = wire-up regression.

### 2. Category distribution — sanity vs expected category weights

```js
db.query_recording.aggregate([
  {$match: {stage: "ooc_handler"}},
  {$group: {_id: "$extras.category", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

**Expected weights (qualitative):**
- `OOC-FREELANCE`, `OOC-CAREERS`, `OOC-PARTNERSHIP` — high-volume
- `OOC-PRESS-MEDIA`, `OOC-VENDOR-SUPPLIER` — low-volume
- `ESCALATION-CONSECUTIVE-OOC` — should be RARE (system-meta)

### 3. Shape distribution — verify mid-flow shapes are firing

```js
db.query_recording.aggregate([
  {$match: {stage: "ooc_handler"}},
  {$group: {_id: "$extras.shape_used", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

**Expected:** `cold_start` dominates pre-D.6.1 (since persistence not landed, mid-flow shapes only fire when an SA flow is genuinely active within a single message turn). Once D.6.1 lands, `mid_flow_*` should grow proportional to mid-flow OOC turns.

### 4. Language coverage — verify i18n loader producing non-en responses

```js
db.query_recording.aggregate([
  {$match: {stage: "ooc_handler"}},
  {$group: {_id: "$extras.language_used", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

**Expected:** `id` + `en` dominate. Smaller buckets for `ms`, `vi`, `zh`, `ja`, `th`, etc.

**Watch for:** `extras.language_used` always being `"en"` — would signal i18n loader silently falling back to en for every turn (drift).

### 5. Constraint #4 false-positive monitoring — per `active_service` OOC rate

Use to prioritize Phase 1 in-scope keyword bank expansion for the 7 services without explicit banks (`kyc`, `abms_elearning`, `market_survey`, `non_use_investigation`, `anti_counterfeit_investigation`, `parallel_trading_investigation`, `trademark_investigation`).

```js
db.query_recording.aggregate([
  {$match: {stage: "ooc_handler", "extras.active_service": {$ne: null}}},
  {$group: {_id: "$extras.active_service", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

**Expansion criteria** per `docs/modules/out_of_context.md:175` — add a service's bank when per-service OOC rate during that service's flow ≥1%.

### 6. Escalation health — frequency of consecutive-OOC handover

```js
db.query_recording.find({
  stage: "ooc_handler",
  "extras.category": "ESCALATION-CONSECUTIVE-OOC"
}, {sessionId: 1, timestamp: 1, "extras.previous_categories_chain": 1}).limit(20)
```

**Pre-D.6.1:** count expected = 0 (cold-start streak doesn't accumulate).

**Post-D.6.1:** count > 0 → operator should review `previous_categories_chain` to see which categories chain into escalation most often.

### 7. Phase 0 legacy-fallback path — D.6.2 telemetry (Phase 1 prioritization signal)

```js
db.query_recording.find({
  stage: "ooc_suppression_fallthrough",
  "extras.phase0_legacy_fallback": true
}).count()
```

**Pre-D.6.1:** expected = 0 (suppression counter never accumulates cold-start).

**Once D.6.1 lands AND escalation suppression fires:** this count grows.

**Threshold for D.6.2 prioritization:** ≥10/day = extract cold-start dispatcher (Phase 1 follow-up per spec Appendix D.6.2).

### 8. Suppression dispatcher health — mid-flow Step 2.5 distribution

```js
db.query_recording.aggregate([
  {$match: {stage: "ooc_suppression_fallthrough"}},
  {$group: {_id: "$extras.downstream_route", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

**Expected:** `sa_continuation` dominates (mid-flow suppression dispatcher).

**Alert thresholds:**
- `dispatcher_exception` should be 0 — non-zero = ops alert (dispatcher crashing).
- `none_returned` / `unknown` should be 0 — non-zero = SA engine contract violation.

### 9. Post-hoc classifier sampling — Phase 1 review signal

**Pre-condition:** `OOC_POSTHOC_CLASSIFIER_ENABLED=true` (default `false`).

```js
db.query_recording.find({
  stage: "ooc_suppression_fallthrough",
  "extras.posthoc_classifier_sampled": true,
  "extras.posthoc_classifier_would_have_classified": {$ne: null}
}).count()
```

**Non-zero =** suppression-fallthrough turns that the classifier would have OOC'd.

**If frequent:** reconsider suppression behavior (spec §7.4 Phase 1 review note).

### 10. Language fallback frequency — Step 2 health

```js
db.query_recording.aggregate([
  {$match: {stage: "language_fallback"}},
  {$group: {_id: "$extras.trigger", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

**Expected:** `low_confidence` + `unknown_language` both present.

**Watch for:** `unknown_language` dominant = `OOC_LANG_DETECTION_FLOOR` may be too high, or CANON_17 missing a real-user language (`rm`? `sv`? `hi`?).

### 11. Abandonment handler usage — feature working as intended

```js
db.query_recording.aggregate([
  {$match: {stage: "abandonment_handler"}},
  {$group: {_id: "$extras.matched_via", count: {$sum: 1}}},
  {$sort: {count: -1}}
])
```

`keyword_strict` vs `intent_phrase` balance signals which detection layer is doing the work.

**Watch for:** Zero rows on a busy day = users not abandoning, or abandonment phrases not matching reality (Phase 1 keyword bank expansion).

### 12. Romansh telemetry (Phase 1 retain-vs-drop decision)

```js
db.query_recording.find({
  stage: "ooc_handler",
  "extras.raw_detected_language": "rm"
}).count()
```

**Decision threshold:** <1/week → drop is low-risk per `docs/modules/out_of_context.md` "Romansh retain-vs-drop business decision".

**Note:** the `out_of_context.md` ledger informally refers to this as `detected_language`. The actual queryable field per `OOCAuditMetadata` schema is `raw_detected_language`.

## Schema field reference

### `ooc_handler` extras (22 fields, always present)

From `OOCAuditMetadata` (`modules/out_of_context/ooc_types.py:97-119`):

| Field | Type | Notes |
|---|---|---|
| `classifier_confidence` | float [0, 1] | |
| `classifier_mode` | "keyword" \| "hybrid" \| "llm" | |
| `extracted_mention` | Optional[str] | for OOC-ADJACENT-SERVICE |
| `extracted_hint` | Optional[str] | polymorphic: OOC-CAREERS or OOC-COMPLAINT |
| `ooc_excursion_count_post` | int ≥0 | counter value AFTER mutation |
| `previous_categories_chain` | List[str] | streak history |
| `raw_detected_language` | Optional[str] | pre-fallback detection |
| `raw_detection_confidence` | Optional[float] | |
| `effective_language_diverged_from_raw` | bool | Step 2 fallback signal |
| `pre_data` | bool | active_service set + no answers yet |
| `high_stakes_intake` | bool | active_service in OOC_HIGH_STAKES_SERVICES |
| `active_service` | Optional[str] | None at cold-start |
| `template_variant_used` | Optional[str] | per-lang variant key |
| `bidi_wrap_applied` | bool | RTL wrap fired |
| `trigger` | Optional[str] | |
| `streak_length` | Optional[int] | |

Result-level augmentations (added by `_apply_ooc_turn_and_audit`):

| Field | Type | Notes |
|---|---|---|
| `category` | str | OOCCategory enum value |
| `shape_used` | str | one of 5 shape variants |
| `language_used` | str | final lang after fallback |
| `streak_classification` | "user_ooc" \| "system_meta" | |
| `set_escalation_suppression` | bool | True on ESCALATION row |
| `downstream_sd_stage` | **always None** | sentinel: no SD branch fires when OOC handled |

### `ooc_suppression_fallthrough` extras (10 fields, always present)

From `_write_suppression_audit_row` (`sd_orchestrator.py:390-401`):

| Field | Type | Notes |
|---|---|---|
| `user_text` | str | truncated to 200 chars |
| `suppression_remaining_pre` | int | |
| `suppression_remaining_post` | int | pre - 1 always |
| `downstream_route` | str | one of 6 deterministic values |
| `downstream_sd_stage` | str | hint or `"unknown"` (NOT None) |
| `posthoc_classifier_sampled` | bool | |
| `posthoc_classifier_would_have_classified` | Optional[OOCCategory] | None when not sampled |
| `posthoc_classifier_confidence` | Optional[float] | None when not sampled |
| `posthoc_classifier_mode` | Optional[str] | None when not sampled |
| `phase0_legacy_fallback` | bool | True only on D.6.2 path |

### `downstream_route` — 6 deterministic values

| Value | Source | When |
|---|---|---|
| `sa_continuation` | Spec §1.1 line 164 happy path | Dispatcher returned route=sa_continuation |
| `faq_rag` | Spec §1.1 line 164 happy path | Dispatcher returned route=faq_rag |
| `general_agent` | Spec §1.1 line 164 happy path (incl. dispatcher's own internal-degradation fallback) | Dispatcher returned route=general_agent |
| `none_returned` | Spec extension (Guardrail B) | Dispatcher returned `(None, None)` |
| `unknown` | Spec extension (Guardrail B) | Dispatcher returned `(None, <response>)` |
| `dispatcher_exception` | Spec extension (Guardrail B) | Dispatcher raised; audit row written before re-raise |
