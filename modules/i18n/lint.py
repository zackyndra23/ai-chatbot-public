"""Lint helpers for i18n — RTL bidi wrap + per-lang banned-form detection.

Per spec docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §4.5 + §4.11.
"""
from __future__ import annotations

# Bidi isolate markers per spec §4.11.
# U+2066 LRI = Left-to-Right Isolate (start)
# U+2069 PDI = Pop Directional Isolate (end)
LRI = "⁦"
PDI = "⁩"

# 4 langs in canonical 17-lang set that are RTL.
# (ar is in spec; he/fa/ur listed for future expansion completeness.)
RTL_LANGS = frozenset({"ar", "he", "fa", "ur"})


def is_rtl_lang(lang: str) -> bool:
    return lang in RTL_LANGS


def bidi_wrap_for_rtl(value: str, lang: str) -> str:
    """Wrap a value with bidi isolates when rendering inside an RTL-lang flow.

    Idempotent — does not re-wrap an already-wrapped value.

    Per spec §4.11 + D6 row 10: routing assets (emails, phones, URLs) and
    extracted variables (mentioned_service, when Latin-script) must be wrapped
    so Latin-script content renders LTR within the RTL paragraph flow.

    For non-RTL langs returns the value unchanged — safe to call universally.
    """
    if not is_rtl_lang(lang):
        return value
    if not value:
        return value
    if value.startswith(LRI) and value.endswith(PDI):
        return value
    return f"{LRI}{value}{PDI}"


# Per-lang banned forms (spec §4.5 — 10 lint-enforced languages).
# Detection is informational (WARN-level); does NOT block rendering.
# Format: substring match (case-sensitive for chars where it matters).
BANNED_FORMS: dict[str, list[str]] = {
    "id": [
        # Banned pronouns
        "kamu", "kau", "lu",
        # Banned openers (sentence-initial — spec §4.5)
        "Baik,", "Baiklah,",
        # Informal verb forms
        "dijelasin",
    ],
    "ms": [
        " awak ",
        " kau ",
    ],
    "ja": [
        # Tameguchi markers (rough heuristic)
        "だよ", "だね", "じゃん",
    ],
    "th": [
        # Casual final particles (formal flow uses ครับ)
        "จ้ะ", "จ้า",
    ],
    "ko": [
        # Banmal markers — placeholder; SME refines
        "반말",
    ],
    "zh": [
        # Informal "you" instead of 您
        "你好", "你们",
    ],
    "fr": [
        " tu ", " toi ",
    ],
    "de": [
        " du ", " dich ",
    ],
    "vi": [
        " em ", " bạn ",
    ],
    "ar": [],
}


def detect_banned_forms(text: str, lang: str) -> list[str]:
    """Return list of banned forms found in text. Empty list = clean."""
    banned = BANNED_FORMS.get(lang) or []
    return [b for b in banned if b in text]
