"""Centralized i18n loader for the chatbot.

Public API:
    t(key, lang, **fmt_kwargs)  -> rendered string (or list for list-typed entries)
    validate_all()              -> ValidationReport
    _get_registry()             -> StringRegistry (lazy-initialized singleton; tests use this)

Loads schema.yaml + strings/{lang}.yaml at first call. Validates placeholder
contracts + required-key coverage at startup. Refuses to start on CRITICAL
validation failures; logs WARN/INFO and continues otherwise.

See docs/modules/i18n.md + docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §4.
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from modules.i18n.registry import (
    StringRegistry,
    StringEntry,
    MissingKeyError,
    RUNTIME_FALLBACK_LANG,
)
from modules.i18n.loader import I18nLoader, ValidationReport, ValidationIssue

__all__ = [
    "StringRegistry",
    "StringEntry",
    "MissingKeyError",
    "RUNTIME_FALLBACK_LANG",
    "I18nLoader",
    "ValidationReport",
    "ValidationIssue",
    "t",
    "service_label",
    "field_label",
    "ui_term",
    "validate_all",
]

_REGISTRY: Optional[StringRegistry] = None


def _i18n_base_dir() -> Path:
    return Path(__file__).resolve().parent


def _get_registry() -> StringRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = I18nLoader(base_dir=_i18n_base_dir()).load()
    return _REGISTRY


def _reset_registry_for_tests() -> None:
    """Reset the singleton — used by test isolation."""
    global _REGISTRY
    _REGISTRY = None


def t(key: str, lang: str, **fmt_kwargs):
    """Render an i18n key in the requested language.

    Returns str for normal entries; returns list for list-typed entries
    (e.g., abandonment.trigger_phrases, greeting.palette). Caller checks type.
    """
    return _get_registry().t(key, lang, **fmt_kwargs)


def service_label(service_id: str, lang: str) -> Optional[str]:
    """Look up a service line label from glossary.yaml. Falls back to English."""
    return _get_registry().service_label(service_id, lang)


def field_label(field_id: str, lang: str) -> Optional[str]:
    """Look up a field label (noun phrase) from glossary.yaml. Falls back to English."""
    return _get_registry().field_label(field_id, lang)


def ui_term(term_id: str, lang: str) -> Optional[str]:
    """Look up a common UI term from glossary.yaml. Falls back to English."""
    return _get_registry().ui_term(term_id, lang)


def validate_all() -> ValidationReport:
    """Run schema + per-lang validation. Used by startup hook or CI."""
    return I18nLoader(base_dir=_i18n_base_dir()).validate()
