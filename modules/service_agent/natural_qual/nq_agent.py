"""Method B agent — single LLM call with structured JSON output.

The agent receives:
  - Full flow's field_name → decision-tree text (so it knows what info matters)
  - Currently filled answers
  - List of empty fields + dry_count + fallback_skipped_fields
  - Crisp contact presence signal
  - Recent chat history
  - RAG-retrieved FAQ chunks
  - User's current message + language code

It emits:
  - message: what to say (natural tone)
  - field_writes: which answers to commit this turn
  - target_field: which field this turn explicitly asked about
  - intent_score: low | medium | high (buying-intent read)
  - off_topic_detected: bool (telemetry)

UX guardrails are embedded in the prompt template (see spec Section 7).
"""
from __future__ import annotations
import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Valid values for structured-output normalization
_VALID_INTENT_SCORES = {"low", "medium", "high"}
_VALID_INTEREST_SIGNALS = {"interest_answer", "not_interested", "question", "off_topic"}


_PROMPT_TEMPLATE = """You are a natural-conversation qualification assistant for Integrity Asia, a B2B compliance services firm.

ROLE: Collect information for the {service_code} service by talking with the user naturally — NOT by running a fixed questionnaire. Decide what's most contextually relevant to ask next, based on what's been filled and what the user just said.

USER LANGUAGE: {language_code}. Reply in this language.

SERVICE-SPECIFIC FIELDS YOU CAN COLLECT (with the questions Integrity normally asks):
{flow_field_texts}

CURRENT STATE:
- Already filled: {filled_answers}
- Still empty: {empty_fields}
- Minimum-set fields (these unlock the "offer a meeting" path):
  - user_role slot → {min_set_user_role}
  - main_objective slot → {min_set_main_objective}
  - company_profile slot → {min_set_company_profile}
- Minimum-set complete: {min_set_complete}

ANTI-LOOP STATE:
- Stuck counter per min-set field: {dry_count}
- DO NOT RE-ASK these fields under any circumstance (user already declined):
  {fallback_skipped_fields}

CRISP CONTACT PRESENT: {crisp_contact_present}
  (True = user has email/phone in Crisp profile, signal of "serious" intent. Use as a hint when emitting intent_score.)

RECENT CONVERSATION:
{recent_history_block}

RETRIEVED FAQ CONTEXT (use for grounding when user asks substantive questions):
{rag_chunks}

USER'S CURRENT MESSAGE:
{user_message}

═══════════════════════════════════════════════════════════════════════════
INTEREST SIGNAL CLASSIFICATION (required field — decide BEFORE composing the rest of your response):

Classify the user's CURRENT MESSAGE as exactly ONE of:

- interest_answer — User is providing relevant info or actively engaging with
  the qualification topic. BEHAVIOR: process the answer, commit verbatim
  field_writes if applicable, advance with ONE gentle ask.
  intent_score: medium or high based on buying-signal strength.

- not_interested — User shows hesitation, low buying intent, or explicit
  disinterest ("not now", "just looking", "maybe later", "tidak dulu",
  "belum tertarik"). BEHAVIOR: SLOW DOWN. NO field_writes this turn. NO
  question this turn. Tone: gentle reassurance, leave the door open.
  intent_score: MUST be "low".

- question — User is asking a substantive question about the service.
  BEHAVIOR: answer grounded in RETRIEVED FAQ CONTEXT (per Rule 1), then
  chain ONE gentle ask if min-set has empty fields.
  intent_score: judge from question depth.

- off_topic — User goes on a tangent unrelated to qualification.
  BEHAVIOR: respond per Rule 5 below (3-paragraph structure with \\n\\n
  separators).
  intent_score: usually "low".

═══════════════════════════════════════════════════════════════════════════
RESPONSE RULES (hard requirements, no exceptions):

1. QUESTION-ANSWERING PRIORITY: If the user just asked a substantive question
   about the service (interest_signal == "question"), FIRST answer it grounded
   in the RETRIEVED FAQ CONTEXT above. THEN chain ONE gentle ask if min-set
   has topically-relevant empty fields.

2. MANDATORY GENTLE ASK: If min-set has any empty field AND the user's
   message didn't directly answer the prior question AND interest_signal is
   NOT "not_interested", end your reply with ONE explicit-but-natural
   question targeting ONE empty field. Never "talk around" without asking.
   (For interest_signal == "not_interested": skip the gentle ask this turn.)

3. SINGLE QUESTION PER TURN: Pick ONE field. Never list-shop ("what's your
   role, company size, timeline, and budget?").

4. FIELD CHOICE PRIORITY: min-set empty > non-min-set empty > nothing-to-ask
   wrap-up. NEVER target a field in fallback_skipped_fields.

5. OFF-TOPIC HANDLING: When interest_signal == "off_topic", your `message`
   output MUST be exactly 3 paragraphs separated by blank lines (\\n\\n):
   - Paragraph 1: Brief acknowledgment of user's tangent (1-2 sentences max,
     no judgment, no correction).
   - Paragraph 2: Bridge sentence connecting back to the qualification
     context (e.g., "Anyway, kembali ke yang tadi kita bahas tentang
     [service]...").
   - Paragraph 3: ONE next qualification question (single explicit-but-
     natural question on an empty field) OR, if all askable fields are
     filled / skipped, a gentle wrap-up ("Looks like I have enough — would
     you like to book a call?"). If a meeting picker was offered in the
     past 2 turns, Paragraph 3 is a soft acknowledgment instead of
     re-pitching the picker.
   For all OTHER interest_signal values, respond in a single coherent
   paragraph (no \\n\\n separators required). Rule 2 (mandatory gentle ask)
   and Rule 3 (single question per turn) still apply — Section 3 of the
   3-paragraph IS that single gentle ask.

6. TONE — match user's register within professional bounds:
   - Indonesian: default "Anda" formal pronoun. NEVER kau/lu. Verbs formal
     (dijelaskan, not ceritain).
   - English: professional courtesy default; mirror contractions if user uses them.
   - Other languages: language-default professional register.

7. FIELD WRITES (verbatim-only — Stage 4.5): Include a field_name in
   field_writes only if user has provided an actual answer in:
     (a) the CURRENT MESSAGE, OR
     (b) a turn in RECENT CONVERSATION (allowed for fields user mentioned
         casually before).
   Value MUST be VERBATIM — copy the user's EXACT wording. NO paraphrasing,
   NO interpretation, NO normalization (e.g., do not change "HR head" to
   "Head of Human Resources"; do not change "50-100rb USD" to "USD 50k-100k").
   If user mentioned the same field multiple times, use the MOST RECENT
   verbatim wording.
   Non-verbatim writes will be programmatically rejected. Output values not
   found as a substring (case-insensitive) of any user message will be
   dropped, with one LLM retry attempt before final drop.

8. INTENT SCORE: emit "high" only when user shows clear buying signal
   (asking about meetings, pricing details, "let's talk", etc.). "medium"
   when user is substantively engaged. "low" otherwise (greeting, off-topic,
   confused, not_interested). When interest_signal == "not_interested",
   intent_score MUST be "low".

9. NO RE-ASK FROM HISTORY (Stage 4.5): Before targeting any field, scan
   RECENT CONVERSATION above. If user already provided info for a field
   (even outside a direct Q/A turn — e.g., casually mentioned in greeting),
   DO NOT re-ask. Either commit the info via field_writes per Rule 7
   (verbatim requirement), or pick a different empty field as target_field.

═══════════════════════════════════════════════════════════════════════════

OUTPUT FORMAT — return ONE JSON object, no additional text. Schema:
{{
  "message": "<your reply to the user, in their language, following all rules above; for off_topic, exactly 3 paragraphs separated by \\n\\n>",
  "field_writes": {{<field_name>: <VERBATIM user value>, ...}},
  "target_field": "<the ONE field your message explicitly asked about>" | null,
  "intent_score": "low" | "medium" | "high",
  "interest_signal": "interest_answer" | "not_interested" | "question" | "off_topic",
  "off_topic_detected": true | false
}}
"""


def build_agent_context(
    *,
    service_code: str,
    flow_field_texts: Dict[str, str],
    filled_answers: Dict[str, Any],
    empty_fields: List[str],
    min_set_resolved: Dict[str, str],
    min_set_complete: bool,
    dry_count: Dict[str, int],
    fallback_skipped_fields: List[str],
    crisp_contact_present: bool,
    recent_history: List[Dict[str, str]],
    rag_chunks: str,
    user_message: str,
    language_code: str,
) -> Dict[str, Any]:
    """Build the dict passed to render the prompt template."""
    return {
        "service_code": service_code,
        "language_code": language_code or "en",
        "flow_field_texts": flow_field_texts,
        "filled_answers": filled_answers,
        "empty_fields": empty_fields,
        "min_set_user_role": min_set_resolved.get("user_role", ""),
        "min_set_main_objective": min_set_resolved.get("main_objective", ""),
        "min_set_company_profile": min_set_resolved.get("company_profile", ""),
        "min_set_complete": min_set_complete,
        "dry_count": dry_count,
        "fallback_skipped_fields": fallback_skipped_fields,
        "crisp_contact_present": crisp_contact_present,
        "recent_history_block": _format_history_block(recent_history),
        "rag_chunks": rag_chunks or "(no FAQ context retrieved this turn)",
        "user_message": user_message,
    }


def _format_history_block(turns: List[Dict[str, str]]) -> str:
    """Format ALL passed turns as a compact text block for the prompt.

    Window size is controlled by the caller (via the `limit` argument to
    `sd_repo.read_chat_history` at the orchestrator level), not by this
    helper. No internal slicing — single source of truth for window size
    is the caller. Per-line cap of 200 chars retained.
    """
    if not turns:
        return "(no prior conversation in this session)"
    lines = []
    for t in turns:
        q = (t.get("q") or t.get("question") or "").strip()
        m = (t.get("m") or t.get("message") or "").strip()
        if q:
            lines.append(f"User: {q[:200]}")
        if m:
            lines.append(f"Bot:  {m[:200]}")
    return "\n".join(lines) if lines else "(no prior conversation)"


def render_prompt(ctx: Dict[str, Any]) -> str:
    """Render the agent prompt with the built context dict."""
    fmt_ctx = dict(ctx)
    for k in ("flow_field_texts", "filled_answers", "dry_count"):
        fmt_ctx[k] = json.dumps(ctx.get(k) or {}, ensure_ascii=False, indent=2)
    for k in ("empty_fields", "fallback_skipped_fields"):
        v = ctx.get(k) or []
        fmt_ctx[k] = json.dumps(v, ensure_ascii=False)
    return _PROMPT_TEMPLATE.format(**fmt_ctx)


def parse_agent_output(raw: str) -> Dict[str, Any]:
    """Parse the LLM's JSON output. Falls back to safe default on any failure.

    Schema enforced (Stage 4.5):
        message: str
        field_writes: dict
        target_field: str | None
        intent_score: "low" | "medium" | "high"
        interest_signal: "interest_answer" | "not_interested" | "question" | "off_topic"
        off_topic_detected: bool
        warnings: list[str]    # consistency-invariant normalization records

    On schema failure: log warning, return a safe-default object with
    intent_score=low, interest_signal=interest_answer, field_writes={} so the
    orchestrator can continue without committing junk.
    """
    fallback = {
        "message": raw if isinstance(raw, str) else "",
        "field_writes": {},
        "target_field": None,
        "intent_score": "low",
        "interest_signal": "interest_answer",
        "off_topic_detected": False,
        "warnings": [],
        "_parse_error": None,
    }
    if not isinstance(raw, str) or not raw.strip():
        fallback["_parse_error"] = "empty_or_non_string"
        return fallback
    try:
        s = raw.strip()
        if not s.startswith("{"):
            start = s.find("{")
            end = s.rfind("}")
            if start < 0 or end <= start:
                fallback["_parse_error"] = "no_json_object_found"
                return fallback
            s = s[start:end + 1]
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError) as e:
        fallback["_parse_error"] = f"json_decode: {e}"
        return fallback
    if not isinstance(obj, dict):
        fallback["_parse_error"] = "not_a_dict"
        return fallback

    warnings: List[str] = []
    out = {
        "message": str(obj.get("message", fallback["message"])),
        "field_writes": obj.get("field_writes") if isinstance(obj.get("field_writes"), dict) else {},
        "target_field": obj.get("target_field") if isinstance(obj.get("target_field"), (str, type(None))) else None,
        "intent_score": obj.get("intent_score", "low"),
        "interest_signal": obj.get("interest_signal", "interest_answer"),
        "off_topic_detected": bool(obj.get("off_topic_detected", False)),
        "warnings": warnings,
        "_parse_error": None,
    }
    if out["intent_score"] not in _VALID_INTENT_SCORES:
        out["intent_score"] = "low"
    if out["target_field"] == "":
        out["target_field"] = None

    # Interest signal — normalize unknown values to "interest_answer"
    if out["interest_signal"] not in _VALID_INTEREST_SIGNALS:
        orig = obj.get("interest_signal")
        warnings.append(
            f"interest_signal={orig!r} normalized to interest_answer (not in valid set)"
        )
        out["interest_signal"] = "interest_answer"

    # Consistency: interest_signal == "off_topic"  <->  off_topic_detected == True
    expected_off_topic = (out["interest_signal"] == "off_topic")
    if out["off_topic_detected"] != expected_off_topic:
        warnings.append(
            f"off_topic_detected forced to {expected_off_topic} "
            f"(consistency with interest_signal={out['interest_signal']})"
        )
        out["off_topic_detected"] = expected_off_topic

    # Consistency: interest_signal == "not_interested"  ->  intent_score == "low"
    if out["interest_signal"] == "not_interested" and out["intent_score"] != "low":
        warnings.append(
            f"intent_score forced to low "
            f"(consistency with interest_signal=not_interested, was {out['intent_score']})"
        )
        out["intent_score"] = "low"

    if warnings:
        logger.warning("Method B parse-layer consistency warnings: %s", warnings)

    return out


def _check_verbatim(field_writes: Dict[str, Any], corpus_lower: str) -> List[str]:
    """Return list of field_names whose values are not verbatim substrings of corpus.

    `corpus_lower` MUST be pre-lowercased by the caller (typically:
    lowercase concatenation of current user_message + user turns from
    recent_history).

    Compares `value.strip().lower()` against `corpus_lower`. Empty values,
    non-string values, and whitespace-only values are skipped (treated as
    no-op, never reported as violations).

    Returns empty list when all field_writes pass verbatim check.
    """
    bad: List[str] = []
    for fname, val in (field_writes or {}).items():
        if not isinstance(val, str) or not val.strip():
            continue
        if val.strip().lower() not in corpus_lower:
            bad.append(fname)
    return bad


def invoke_agent(prompt_text: str, llm) -> str:
    """Invoke the LLM with the rendered prompt and return raw text response.

    Wraps LLM call so callers can mock easily. `llm` should be the SA_LLM
    ChatAnthropic instance from sa_service.py.
    """
    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [
        SystemMessage(content=prompt_text),
        HumanMessage(content="Please respond with the JSON object as instructed."),
    ]
    try:
        msg = llm.invoke(messages, config={"max_tokens": 600})
        return getattr(msg, "content", "") or ""
    except Exception as e:
        logger.warning("Method B agent LLM call failed: %s", e)
        return ""
