"""OOC classifier — 14-category hybrid (keyword + LLM).

Per spec docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §1.2 + §2.4.

Pipeline (per spec §2.4):
    Step 1: too-short input → OOC-UNCLEAR
    Step 2: existing FREELANCE/PARTNERSHIP intent-phrase detection (anchor pattern from
            classify_intent_phrase_strict — preserves backward compat for those 2 categories)
    Step 3: new keyword-strict categories (5 more deterministic: mystery shopper apply,
            careers, press/media, vendor/supplier, complaint)
    Step 4: in-scope protection (Constraint #4) — if active_service AND text matches
            IN_SCOPE_SERVICE_TERMS, return yes=False before any fuzzy classification
    Step 5: LLM classifier for residual fuzzy categories (env-gated by OOC_MODE)
    Step 6: fallback fuzzy keyword match (keyword-only mode)
"""
from __future__ import annotations
import logging
import re
from typing import Optional

from modules.out_of_context.ooc_types import OOCDecision
from modules.out_of_context.ooc_policies import (
    FREELANCE_INTENT_PHRASES,
    PARTNERSHIP_INTENT_PHRASES,
    KEYWORD_CATEGORIES_BY_LANG,
    FUZZY_CATEGORIES_BY_LANG,
    IN_SCOPE_SERVICE_TERMS,
    _norm,
)
from core.app_config import Config

log = logging.getLogger(__name__)

_SHORT_INPUT_TOKENS = frozenset({
    "hi", "hey", "hello", "help", "info", "?", "halo", "hai", "selamat",
})

# Categories whose extracted variables get bidi-wrapped for RTL (D6 row 10).
# Renderer (Task 8) applies the actual wrap; classifier just extracts the value.
_CATEGORIES_WITH_EXTRACTED_MENTION = frozenset({"OOC-ADJACENT-SERVICE"})
_CATEGORIES_WITH_EXTRACTED_HINT_AS_FIELD = frozenset({"OOC-CAREERS"})
_CATEGORIES_WITH_EXTRACTED_HINT_AS_REF = frozenset({"OOC-COMPLAINT"})


class OOCClassifier:
    """Classify a user message into an OOCCategory ∪ {None}.

    Mode (from `OOC_MODE` env via Config):
        - "keyword" — strict-keyword + fuzzy-keyword only, no LLM call
        - "hybrid"  — strict-keyword first, LLM for fuzzy (recommended)
        - "llm"     — LLM-only for fuzzy categories (strict-keyword still fires first)

    The LLM call is ALWAYS gated by mode; never invoked unconditionally.
    """

    def __init__(self, mode: Optional[str] = None):
        self._cfg = Config()
        self.mode = (mode or self._cfg.OOC_MODE).strip().lower()
        if self.mode not in ("keyword", "hybrid", "llm"):
            log.warning(
                "ooc_classifier_invalid_mode_fallback_to_hybrid",
                extra={"requested_mode": self.mode},
            )
            self.mode = "hybrid"

    # ------------------------------------------------------------------ helpers

    def _matches_keywords_dict(
        self, text: str, keywords_dict: dict[str, list[str]], lang: str
    ) -> bool:
        bank = keywords_dict.get(lang) or keywords_dict.get("en", [])
        if not bank:
            return False
        text_lc = _norm(text)
        hits = sum(1 for kw in bank if _norm(kw) in text_lc)
        return hits >= self._cfg.OOC_MIN_KEYWORD_HITS

    def _check_intent_phrases(self, text: str, phrases: tuple[str, ...]) -> bool:
        """Anchor pattern from classify_intent_phrase_strict — phrase must appear in text."""
        text_lc = _norm(text)
        if not text_lc:
            return False
        for phrase in phrases:
            if _norm(phrase) and _norm(phrase) in text_lc:
                return True
        return False

    def _matches_active_service_terms(
        self, text: str, lang: str, active_service: str
    ) -> bool:
        """Constraint #4 in-scope protection.

        Bank intentionally narrow (see IN_SCOPE_SERVICE_TERMS docstring in
        ooc_policies.py). False-positive risk: legitimate qualification term not
        in bank → classifier may fire OOC. Mitigation: tune bank from production
        query_recording analysis.
        """
        per_service = IN_SCOPE_SERVICE_TERMS.get(active_service) or {}
        bank = per_service.get(lang) or per_service.get("en") or []
        if not bank:
            return False
        text_lc = _norm(text)
        return any(_norm(t) in text_lc for t in bank)

    # ------------------------------------------------------------------ LLM

    def _llm_classify(
        self, text: str, lang: str, active_service: Optional[str]
    ) -> tuple[str, float]:
        """LLM classifier for fuzzy categories. Returns (label, confidence).

        Routes through `core.app_audit.record_llm_call` per
        feedback_audit_wrapper_consistency.md. Test-time monkeypatching of this
        method bypasses the LLM call entirely.

        Possible labels:
            OOC-ADJACENT-SERVICE, OOC-ADJACENT-ISO, OOC-PERSONAL-ADVICE,
            OOC-CHITCHAT, OOC-CATCHALL, OOC-UNCLEAR, NONE
        """
        from core.app_audit import record_llm_call
        from langchain_anthropic import ChatAnthropic

        prompt = self._build_llm_prompt(text, lang, active_service)
        try:
            llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
            response = record_llm_call(
                llm=llm,
                prompt=prompt,
                stage="ooc_classifier_llm",
                metadata={"lang": lang, "active_service": active_service},
            )
            raw = (response.content if hasattr(response, "content") else str(response)).strip()
            label, conf_str = raw.split(":", 1)
            return label.strip(), float(conf_str.strip())
        except Exception as e:
            log.warning(
                "ooc_llm_classifier_failure",
                extra={"error": str(e), "lang": lang},
            )
            return "NONE", 0.0

    def _build_llm_prompt(self, text: str, lang: str, active_service: Optional[str]) -> str:
        return (
            "Classify the following user message into ONE of these labels:\n"
            "OOC-ADJACENT-SERVICE | OOC-ADJACENT-ISO | OOC-PERSONAL-ADVICE | "
            "OOC-CHITCHAT | OOC-CATCHALL | OOC-UNCLEAR | NONE\n\n"
            f"Active service context: {active_service or 'none (cold-start)'}\n"
            f"Language: {lang}\n"
            f"Message: {text}\n\n"
            "Respond with only LABEL:CONFIDENCE (e.g., OOC-ADJACENT-SERVICE:0.8). "
            "Use NONE if message is on-topic for the active service or unclassifiable."
        )

    # ------------------------------------------------------------------ extraction

    @staticmethod
    def _extract_engagement_ref(text: str) -> Optional[str]:
        """For OOC-COMPLAINT — find an engagement reference like 'CASE-2026-0042'."""
        m = re.search(r"\b([A-Z]{2,}-\d{4}-\d{3,})\b", text)
        return m.group(1) if m else None

    @staticmethod
    def _extract_field_hint(text: str) -> Optional[str]:
        """For OOC-CAREERS — find user's stated field via 'background in X' / 'experience in X'."""
        m = re.search(
            r"(?:background in|experience in|specializing in|skilled in)\s+([\w\s,]+?)(?:[.!?]|$)",
            text,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else None

    @staticmethod
    def _extract_service_mention(text: str) -> Optional[str]:
        """For OOC-ADJACENT-SERVICE — find the mentioned external service.

        Heuristic via 'offer/provide/menyediakan/menawarkan X'. Limited to
        words/phrases up to 40 chars to avoid runaway matches.
        """
        m = re.search(
            r"(?:offer|provide|do|have|need|require|menyediakan|menawarkan)\s+"
            r"([\w\s]{3,40}?)"
            r"(?:\?|services?|servis|\.|,|$)",
            text,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else None

    # ------------------------------------------------------------------ classify

    def classify(
        self,
        text: str,
        language: str,
        active_service: Optional[str] = None,
    ) -> OOCDecision:
        cfg = self._cfg
        stripped = (text or "").strip()

        # Step 1: too-short input → UNCLEAR (only when no active service)
        if active_service is None and (
            len(stripped) < cfg.OOC_MIN_TEXT_LEN
            or stripped.lower() in _SHORT_INPUT_TOKENS
        ):
            return OOCDecision(
                yes=True,
                label="OOC-UNCLEAR",
                confidence=0.85,
                reason="too_short",
                classifier_mode=self.mode,
            )

        # Step 2: legacy FREELANCE / PARTNERSHIP intent-phrase strict detection
        # (anchor pattern from existing classify_intent_phrase_strict).
        if self._check_intent_phrases(text, FREELANCE_INTENT_PHRASES):
            return OOCDecision(
                yes=True,
                label="OOC-FREELANCE",
                confidence=cfg.OOC_KEYWORD_CONFIDENCE,
                reason="intent_phrase_freelance",
                classifier_mode="keyword",
            )
        if self._check_intent_phrases(text, PARTNERSHIP_INTENT_PHRASES):
            return OOCDecision(
                yes=True,
                label="OOC-PARTNERSHIP",
                confidence=cfg.OOC_KEYWORD_CONFIDENCE,
                reason="intent_phrase_partnership",
                classifier_mode="keyword",
            )

        # Step 3: strict-keyword categories (5 more deterministic)
        for label, kw_dict in KEYWORD_CATEGORIES_BY_LANG:
            if self._matches_keywords_dict(text, kw_dict, language):
                decision = OOCDecision(
                    yes=True,
                    label=label,
                    confidence=cfg.OOC_KEYWORD_CONFIDENCE,
                    reason="keyword_strict",
                    classifier_mode="keyword",
                )
                if label == "OOC-COMPLAINT":
                    decision.extracted_hint = self._extract_engagement_ref(text)
                elif label == "OOC-CAREERS":
                    decision.extracted_hint = self._extract_field_hint(text)
                return decision

        # Step 4: in-scope protection (Constraint #4) — CRITICAL ordering.
        # Run AFTER strict-keyword categories (those represent unambiguous OOC intent
        # like "I want to apply for a job" which should not be suppressed by
        # in-scope protection) but BEFORE fuzzy categories.
        if active_service is not None:
            if self._matches_active_service_terms(text, language, active_service):
                return OOCDecision(
                    yes=False,
                    reason="in_scope_protection",
                    classifier_mode=self.mode,
                )

        # Step 5: LLM classifier for fuzzy categories (env-gated by OOC_MODE).
        # ALWAYS gated — never invoked unconditionally.
        if self.mode in ("hybrid", "llm"):
            llm_label, llm_conf = self._llm_classify(text, language, active_service)
            if llm_label == "NONE" or llm_conf < cfg.OOC_LLM_CONFIDENCE_FLOOR:
                return OOCDecision(
                    yes=False,
                    reason="llm_low_confidence_pass_through",
                    confidence=llm_conf,
                    classifier_mode="llm",
                )
            if llm_label == "OOC-CATCHALL" and llm_conf < cfg.OOC_CATCHALL_FLOOR:
                return OOCDecision(
                    yes=False,
                    reason="catchall_below_threshold",
                    confidence=llm_conf,
                    classifier_mode="llm",
                )
            decision = OOCDecision(
                yes=True,
                label=llm_label,
                confidence=llm_conf,
                reason="llm_classify",
                classifier_mode="llm",
            )
            if llm_label == "OOC-ADJACENT-SERVICE":
                decision.extracted_mention = self._extract_service_mention(text)
            return decision

        # Step 6: keyword-only mode — evaluate fuzzy keyword banks at softer confidence.
        for label, kw_dict in FUZZY_CATEGORIES_BY_LANG:
            if self._matches_keywords_dict(text, kw_dict, language):
                decision = OOCDecision(
                    yes=True,
                    label=label,
                    confidence=cfg.OOC_KEYWORD_CONFIDENCE * 0.8,
                    reason="fuzzy_keyword",
                    classifier_mode="keyword",
                )
                if label == "OOC-ADJACENT-SERVICE":
                    decision.extracted_mention = self._extract_service_mention(text)
                return decision

        return OOCDecision(yes=False, reason="no_match", classifier_mode=self.mode)
