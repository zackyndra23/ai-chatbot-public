from __future__ import annotations

from typing import Any, TypedDict


class LRFSessionCandidate(TypedDict, total=False):
    sessionId: str
    tokenId: str | None
    websiteId: str | None
    updated_at: str
    last_chat_ts: str
    last_route: str
    last_language_name: str
    last_related_services: list[str]
    last_question: str
    last_answer: str
    last_extra: dict[str, Any]
    meeting_arranged: bool


class LRFFollowupLog(TypedDict, total=False):
    sessionId: str
    tokenId: str | None
    last_chat_ts: str
    last_route: str
    last_language_name: str
    last_related_services: list[str]
    followup_sent: bool
    followup_sent_at: str | None
    followup_count: int
    status: str
    followup_text: str
    meeting_arranged: bool
    extra: dict[str, Any]