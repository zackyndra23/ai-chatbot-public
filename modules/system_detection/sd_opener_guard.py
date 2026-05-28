"""Opener diversification post-process for qualification-flow replies.

This is the runtime safety net for the Sentence-1 opener guidance defined in
``modules.service_agent.sa_prompts._opener_guidance_block``. If the LLM still
produces a banned or repeated opener despite the prompt guidance, these
helpers swap it deterministically — no second LLM call, no UI changes.

Design notes:
- ``extract_opener``: looks at the first clause of the reply (up to a
  comma/period), rejects anything that looks like a whole sentence, and
  returns the opener string or None.
- ``sanitize_opener``: replaces the opener if it is either (a) banned for
  the language or (b) equal to the most-recent opener in ``recent_openers``.
  The replacement is picked by walking the palette and choosing the first
  entry not in ``recent_openers``.
"""
from __future__ import annotations

import re
from typing import Iterable

from modules.service_agent.sa_prompts import (
    _BANNED_OPENERS_BY_LANG,
    _DEFAULT_OPENER_LANG,
    _OPENER_PALETTE,
)

# Matches a leading short clause ending in a Latin or CJK comma/period.
# Terminator set covers: ASCII `,`/`.`, Japanese/Chinese ideographic comma `、`
# and fullwidth comma `，` (U+FF0C), and CJK period `。`. The opener body
# excludes the same set so we stop at the first punctuation boundary.
# Group 2 captures the actual terminator so we can preserve it when swapping.
_OPENER_PATTERN = re.compile(
    r"^\s*([^,.\n。、，！？!?]{1,40})([,、，.。])\s*(.*)$",
    re.DOTALL | re.UNICODE,
)


def _palette_for(language_code: str | None) -> list[str]:
    lc = (language_code or "").strip().lower()
    for prefix, palette in _OPENER_PALETTE.items():
        if lc.startswith(prefix):
            return list(palette)
    return list(_OPENER_PALETTE[_DEFAULT_OPENER_LANG])


def _banned_for(language_code: str | None) -> set[str]:
    lc = (language_code or "").strip().lower()
    for prefix, words in _BANNED_OPENERS_BY_LANG.items():
        if lc.startswith(prefix):
            return {w.lower() for w in words}
    return set()


def _looks_like_opener(s: str) -> bool:
    if not s:
        return False
    if len(s) > 30:
        return False
    # Latin-script heuristic: ≤5 whitespace-separated tokens.
    # CJK/Thai: no whitespace tokens usually, so the char-length guard above is enough.
    tokens = s.split()
    if len(tokens) > 5:
        return False
    return True


def extract_opener(text: str) -> str | None:
    """Return the leading opener clause of ``text`` if one is present.

    Returns None when the text does not start with a short punctuated clause,
    when the leading clause is too long (i.e. it's really the first full
    sentence), or when the clause is period-terminated with nothing after it
    (the "opener" is then the whole reply, not a useful signal).
    """
    if not text:
        return None
    m = _OPENER_PATTERN.match(text)
    if not m:
        return None
    opener, terminator, rest = m.group(1).strip(), m.group(2), m.group(3)
    if not _looks_like_opener(opener):
        return None
    if terminator in (".", "。") and not rest.strip():
        return None
    return opener


def _pick_replacement(language_code: str | None, recent: Iterable[str]) -> str:
    palette = _palette_for(language_code)
    recent_lower = {(r or "").lower() for r in (recent or [])}
    banned = _banned_for(language_code)
    for opt in palette:
        key = opt.lower()
        if key in recent_lower:
            continue
        if key in banned:
            continue
        return opt
    # Fallback: all palette entries are in ``recent`` (unlikely — palette is
    # ≥8 entries, recent is ≤3). Return the palette head.
    return palette[0]


def sanitize_opener(
    response_text: str,
    recent_openers: list[str],
    language_code: str | None,
) -> str:
    """Deterministically rotate the leading opener when drift is detected.

    Swaps the opener when:
    - It's banned for the current language (e.g. "Baik"/"Baiklah" for id-*), OR
    - It matches the most-recent opener in ``recent_openers``.

    The original terminator (ASCII comma, ideographic comma, fullwidth comma)
    is preserved in the swap so the reply's punctuation stays language-native.

    Otherwise returns ``response_text`` unchanged.
    """
    if not response_text:
        return response_text
    m = _OPENER_PATTERN.match(response_text)
    if not m:
        return response_text
    opener = m.group(1).strip()
    terminator = m.group(2)
    rest = m.group(3)
    if not _looks_like_opener(opener):
        return response_text
    # Short reply like "Baik." with nothing after: don't swap — the opener IS the
    # reply. Better to leave malformed than produce "Oke, " with a trailing comma.
    if terminator in (".", "。") and not rest.strip():
        return response_text

    banned = _banned_for(language_code)
    last_recent = (recent_openers[-1].lower() if recent_openers else "")

    needs_swap = opener.lower() in banned or (
        bool(last_recent) and opener.lower() == last_recent
    )
    if not needs_swap:
        return response_text

    replacement = _pick_replacement(language_code, recent_openers)
    # Preserve the original terminator so CJK replies keep `，`/`、`, etc.
    # Fall back to ", " for period terminators (swapping to a comma reads more natural).
    sep = terminator if terminator in (",", "、", "，") else ","
    # Space after: CJK commas don't usually need a space; ASCII comma does.
    space = " " if sep == "," else ""
    return f"{replacement}{sep}{space}{rest.lstrip()}"
