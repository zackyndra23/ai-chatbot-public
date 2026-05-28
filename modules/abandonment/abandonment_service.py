"""Abandonment handler — detects explicit qualification abandonment phrases
and clears active SA state.

Per spec docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §7.6.

This module is architecturally distinct from `modules/out_of_context/` (per
spec §Architecture Overview point 4). Abandonment is a hard reset of SA state;
OOC is a re-routing without state clear.

Orchestrator invokes AbandonmentHandler at Step 0, BEFORE language detection
or OOC classification. A match short-circuits the entire pipeline.
"""
from __future__ import annotations
import logging
from typing import Optional

from modules.abandonment.abandonment_types import AbandonmentResult
from modules.i18n import _get_registry

log = logging.getLogger(__name__)


# Hardcoded fallback trigger phrases (used when i18n loader doesn't have
# the abandonment.trigger_phrases entry for a lang, or to avoid an i18n
# dependency at very-early init). Production deployment relies on i18n YAML.
_FALLBACK_TRIGGERS: dict[str, list[str]] = {
    "en": ["never mind", "cancel", "forget it", "nvm", "let's stop", "stop", "actually never mind"],
    "id": [
        "udahan saja", "udah dulu", "tidak jadi", "ngga jadi",
        "batalkan", "batalin", "lupakan", "berhenti", "stop",
    ],
}


class AbandonmentHandler:
    """Detect abandonment phrases + clear active SA state.

    Stateless service — instantiate once per request or reuse a singleton.
    """

    def _trigger_phrases_for(self, lang: str) -> list[str]:
        """Resolve trigger phrases for a lang.

        Source priority:
        1. i18n loader entry `abandonment.trigger_phrases` for `lang` (list-typed)
        2. Hardcoded _FALLBACK_TRIGGERS for `lang`
        3. Empty list (unknown lang)
        """
        # Try i18n loader (entries dict is keyed by (key, lang))
        try:
            registry = _get_registry()
            entry = registry.entries.get(("abandonment.trigger_phrases", lang))
            if entry is not None and isinstance(entry.text, list) and entry.text:
                return [str(p) for p in entry.text]
        except Exception as e:
            log.warning(
                "abandonment_i18n_load_failed_using_fallback",
                extra={"lang": lang, "error": str(e)},
            )

        return _FALLBACK_TRIGGERS.get(lang, [])

    def _all_known_langs(self) -> list[str]:
        """Languages with hardcoded fallback banks. Used for cross-lang fallback scan."""
        return list(_FALLBACK_TRIGGERS.keys())

    def matches(
        self,
        *,
        text: str,
        state,  # AgentSessionState — typed loosely to avoid circular import
        lang_hint: Optional[str] = None,
    ) -> AbandonmentResult:
        """Detect abandonment phrases via per-lang keyword bank (i18n loader).

        lang_hint semantics (per spec §7.6 final revision — 3 clauses):
          1. If lang_hint is not None: try lang_hint's keyword bank FIRST.
             If hit: return matched=True with detected_language=lang_hint
             and matched_via="lang_hint_match".
          2. If no hit (or lang_hint is None): cross-lang fallback scan
             across ALL known langs' keyword banks. First hit wins;
             detected_language reflects the matching bank;
             matched_via="cross_lang_fallback".
          3. Phrases are short ("never mind", "cancel", "udahan saja") so
             cross-lang fallback false-positive risk is low. Lang-specific
             keyword banks must contain only unambiguous abandonment phrases
             (NOT common words like "ok" or "go" that overlap with other
             meanings across languages).

        Returns AbandonmentResult(matched, matched_phrase, detected_language,
        matched_via). When matched=False, all other fields are None.
        """
        text_lc = (text or "").lower().strip()
        if not text_lc:
            return AbandonmentResult(matched=False)

        # Clause 1: lang_hint first
        if lang_hint:
            for phrase in self._trigger_phrases_for(lang_hint):
                if phrase.lower() in text_lc:
                    return AbandonmentResult(
                        matched=True,
                        matched_phrase=phrase,
                        detected_language=lang_hint,
                        matched_via="lang_hint_match",
                    )

        # Clause 2: cross-lang fallback scan
        for lang in self._all_known_langs():
            if lang == lang_hint:
                continue  # already checked
            for phrase in self._trigger_phrases_for(lang):
                if phrase.lower() in text_lc:
                    return AbandonmentResult(
                        matched=True,
                        matched_phrase=phrase,
                        detected_language=lang,
                        matched_via="cross_lang_fallback",
                    )

        return AbandonmentResult(matched=False)

    def handle(self, *, text: str, state) -> str:
        """Clear SA state + return localized acknowledgment.

        State mutations (per spec §7.6):
            Cleared:
                - service_code     → "" (existing required-str field)
                - question_id      → ""
                - answers          → {}
                - ooc_excursion_count                → 0
                - previous_user_ooc_categories       → []
                - previous_system_meta_actions       → []
                - ooc_escalation_suppression_remaining → 0
            Preserved:
                - session_fallback_language

        Returns: i18n `abandonment.acknowledgment.{lang}` rendered text.
        target_lang resolved from state.session_fallback_language.
        """
        target_lang = (getattr(state, "session_fallback_language", None) or "en")

        # Clear SA state. Pydantic v2 with default validate_assignment=False:
        # direct attribute assignment bypasses re-validation, so we can clear
        # required str fields to "" (a valid value of correct type).
        state.service_code = ""
        state.question_id = ""
        state.answers = {}

        # Clear OOC streak + suppression (per spec §7.2 row 4 — Abandonment turn)
        state.ooc_excursion_count = 0
        state.previous_user_ooc_categories = []
        state.previous_system_meta_actions = []
        state.ooc_escalation_suppression_remaining = 0

        # Preserve session_fallback_language (explicit no-op for clarity)
        # state.session_fallback_language UNCHANGED

        # Render acknowledgment via i18n
        try:
            from modules.i18n import t
            return t("abandonment.acknowledgment", target_lang)
        except Exception as e:
            log.warning(
                "abandonment_acknowledgment_i18n_failed_using_fallback",
                extra={"lang": target_lang, "error": str(e)},
            )
            return _FALLBACK_ACK.get(target_lang, _FALLBACK_ACK["en"])


# Hardcoded fallback acknowledgments (used if i18n unavailable at runtime).
_FALLBACK_ACK: dict[str, str] = {
    "en": "No problem — we'll stop here. Whenever you're ready to start fresh, just let me know.",
    "id": "Tidak masalah — kita berhenti di sini. Kapan pun Anda siap memulai dari awal, beri tahu saya.",
}
