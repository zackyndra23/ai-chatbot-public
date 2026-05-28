"""In-memory translation registry with verified/draft/missing fallback chain.

See docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §4.3 + §4.4.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional
import logging

log = logging.getLogger(__name__)

RUNTIME_FALLBACK_LANG = "en"

# Status → loader behavior per spec §4.3 6-state enum:
_RENDER_AS_IS_STATUSES = {"verified", "draft", "needs_revision"}
_FALLBACK_TO_EN_STATUSES = {"missing", "deprecated"}
_STALE_STATUS = "stale_re_review"


class MissingKeyError(KeyError):
    """Raised at startup when a required key is absent from a required-lang YAML.

    Distinct from runtime fallback (which logs RUNTIME_FALLBACK and renders English).
    Raised by `I18nLoader.load()` for CRITICAL validation failures.
    """


@dataclass(frozen=True)
class StringEntry:
    """A single (key, lang) translation entry as loaded from YAML."""
    # For string templates: a format-string with {placeholders}.
    # For list-typed entries (e.g., abandonment.trigger_phrases, greeting.palette):
    # this can be a list[str]. Callers that handle list-typed entries should check
    # isinstance(entry.text, list).
    text: Any
    status: str
    reviewer: Optional[str] = None
    reviewed_date: Optional[str] = None
    ai_assisted: bool = False
    baseline_hash: Optional[str] = None


@dataclass
class StringRegistry:
    """In-memory store for all loaded i18n strings + schema metadata + glossary."""
    entries: dict[tuple[str, str], StringEntry] = field(default_factory=dict)
    schema: dict[str, dict] = field(default_factory=dict)

    # Glossary (loaded from glossary.yaml). Each entry maps lang_code → str.
    service_labels: dict[str, dict[str, str]] = field(default_factory=dict)
    field_labels: dict[str, dict[str, str]] = field(default_factory=dict)
    ui_terms: dict[str, dict[str, str]] = field(default_factory=dict)

    def service_label(self, service_id: str, lang: str) -> Optional[str]:
        """Look up a service line label. Falls back to English if lang not in glossary."""
        entry = self.service_labels.get(service_id) or {}
        return entry.get(lang) or entry.get(RUNTIME_FALLBACK_LANG)

    def field_label(self, field_id: str, lang: str) -> Optional[str]:
        """Look up a field label (noun phrase). Falls back to English if lang not in glossary."""
        entry = self.field_labels.get(field_id) or {}
        return entry.get(lang) or entry.get(RUNTIME_FALLBACK_LANG)

    def ui_term(self, term_id: str, lang: str) -> Optional[str]:
        """Look up a common UI term. Falls back to English if lang not in glossary."""
        entry = self.ui_terms.get(term_id) or {}
        return entry.get(lang) or entry.get(RUNTIME_FALLBACK_LANG)

    def t(self, key: str, lang: str, **fmt_kwargs) -> str:
        """Lookup + render. Falls back to English at runtime if (key, lang) missing
        or status indicates absence. Logs RUNTIME_FALLBACK for ops visibility.

        Raises MissingKeyError if neither requested lang nor English have the key.
        """
        entry = self.entries.get((key, lang))

        if entry is None or entry.status in _FALLBACK_TO_EN_STATUSES:
            log.warning(
                "i18n_runtime_fallback",
                extra={
                    "key": key,
                    "requested_lang": lang,
                    "fallback_lang": RUNTIME_FALLBACK_LANG,
                    "reason": "missing_entry" if entry is None else f"status={entry.status}",
                },
            )
            entry = self.entries.get((key, RUNTIME_FALLBACK_LANG))
            if entry is None:
                raise MissingKeyError(
                    f"i18n key {key!r} missing in both {lang!r} and {RUNTIME_FALLBACK_LANG!r}"
                )

        # Log non-verified usage at INFO (ops can dashboard these)
        if entry.status == _STALE_STATUS:
            log.info("i18n_stale_translation_used", extra={"key": key, "lang": lang})
        elif entry.status == "draft":
            log.info("i18n_draft_translation_used", extra={"key": key, "lang": lang})
        elif entry.status == "needs_revision":
            log.info("i18n_needs_revision_translation_used", extra={"key": key, "lang": lang})

        # List-typed entries returned as-is (caller handles selection)
        if isinstance(entry.text, list):
            return entry.text  # type: ignore[return-value]

        try:
            return entry.text.format(**fmt_kwargs)
        except KeyError as e:
            log.error(
                "i18n_placeholder_missing_at_render",
                extra={"key": key, "lang": lang, "missing_placeholder": str(e)},
            )
            raise

    def has(self, key: str, lang: str) -> bool:
        return (key, lang) in self.entries
