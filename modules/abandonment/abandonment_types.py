"""Pydantic types for the abandonment handler.

Per spec docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §7.6.
"""
from __future__ import annotations
from typing import Optional

from pydantic import BaseModel


class AbandonmentResult(BaseModel):
    """Result of `AbandonmentHandler.matches()`.

    Fields:
        matched: True if an abandonment trigger phrase was detected
        matched_phrase: the actual phrase matched (for audit / debugging)
        detected_language: 2-char lang code of the keyword bank that hit
        matched_via: "lang_hint_match" if hint bank hit; "cross_lang_fallback"
                     if cross-lang scan found it after hint missed
    """

    matched: bool = False
    matched_phrase: Optional[str] = None
    detected_language: Optional[str] = None
    matched_via: Optional[str] = None
