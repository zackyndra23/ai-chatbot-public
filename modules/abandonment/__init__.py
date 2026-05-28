"""Abandonment handler module.

Detects user messages that signal an explicit desire to abandon the
qualification flow ("never mind", "cancel", "udahan saja", etc.) and
clears active SA state. Distinct from OOC — abandonment is a hard reset;
OOC is a re-routing without state clear.

See docs/modules/abandonment.md and
docs/superpowers/specs/2026-05-13-ooc-response-engine-design.md §7.6.
"""
from modules.abandonment.abandonment_service import AbandonmentHandler
from modules.abandonment.abandonment_types import AbandonmentResult

__all__ = ["AbandonmentHandler", "AbandonmentResult"]
