"""Mongo read helpers for assertion logic. Read-only."""
from __future__ import annotations
import os
from pymongo import MongoClient
from typing import Any


def _client() -> MongoClient:
    uri = os.getenv("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI env var required")
    return MongoClient(uri)


def _db():
    name = os.getenv("MONGO_DB", "faq_automation")
    return _client()[name]


def read_chat_history_doc(session_id: str, token_id: str | None = None) -> dict[str, Any] | None:
    """Read the per-(sessionId, tokenId) chat_history doc. None when missing."""
    coll = os.getenv("CHAT_HISTORY_COLL", "chat_history")
    key = {"sessionId": session_id, "tokenId": token_id or session_id}
    return _db()[coll].find_one(key)


def read_latest_audit_for_session(session_id: str) -> dict[str, Any] | None:
    """Read the most-recent query_recording entry for this session."""
    coll = os.getenv("QUERY_RECORDING_COLL", "query_recording")
    return _db()[coll].find_one(
        {"sessionId": session_id},
        sort=[("timestamp", -1)],
    )


def read_all_audits_for_session(session_id: str) -> list[dict[str, Any]]:
    """Read every query_recording entry for this session, oldest first."""
    coll = os.getenv("QUERY_RECORDING_COLL", "query_recording")
    return list(_db()[coll].find({"sessionId": session_id}).sort("timestamp", 1))
