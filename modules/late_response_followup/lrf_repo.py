from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pymongo import MongoClient, ReturnDocument

from core.app_config import Config

cfg = Config()


def _wib_now() -> datetime:
    return datetime.now(ZoneInfo(cfg.TIMEZONE or "Asia/Jakarta"))


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


class LRFMongoRepo:
    def __init__(self) -> None:
        self.client = MongoClient(cfg.MONGO_URI, connect=True)
        self.db = self.client[cfg.MONGO_DB]
        self.chat_coll = self.db[cfg.CHAT_HISTORY_COLL]
        self.log_coll = self.db[cfg.LATE_RESPONDS_COLL]

        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.chat_coll.create_index([("sessionId", 1), ("tokenId", 1)])
        self.chat_coll.create_index([("updated_at", 1)])

        self.log_coll.create_index(
            [("sessionId", 1), ("tokenId", 1)],
            unique=True,
            name="uniq_session_token_followup",
        )
        self.log_coll.create_index([("status", 1), ("followup_sent", 1)])
        self.log_coll.create_index([("last_chat_ts", 1)])

    def find_idle_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        if cfg.LATE_RESPONDS_FEATURE not in ("1", "true", "yes", "on"):
            return []

        cutoff = _wib_now() - timedelta(seconds=int(cfg.LATE_RESPONDS_TIME or 1800))

        query: dict[str, Any] = {
            "updated_at": {"$lte": cutoff},
        }

        if cfg.LATE_RESPONDS_REQUIRE_CHAT_HISTORY:
            query["chat_history.0"] = {"$exists": True}

        docs = list(
            self.chat_coll.find(
                query,
                {
                    "_id": 0,
                    "sessionId": 1,
                    "tokenId": 1,
                    "websiteId": 1,
                    "updated_at": 1,
                    "chat_history": {"$slice": -1},
                },
            ).limit(limit)
        )

        out: list[dict[str, Any]] = []
        for doc in docs:
            arr = doc.get("chat_history") or []
            if not arr:
                continue

            last_turn = arr[-1] or {}
            session_id = doc.get("sessionId")
            token_id = doc.get("tokenId")

            if not session_id:
                continue

            last_extra = last_turn.get("extra") or {}
            ma_ctx = (last_extra.get("meeting_arrangement") or {}) if isinstance(last_extra, dict) else {}
            meeting_arranged = bool(
                ma_ctx.get("selected_slot")
                or ma_ctx.get("calendar_sent_ok")
                or ma_ctx.get("monday_meeting_sent")
                or str(last_turn.get("route") or "").startswith("meeting_arrangement_")
            )

            out.append(
                {
                    "sessionId": session_id,
                    "tokenId": token_id,
                    "websiteId": doc.get("websiteId"),
                    "updated_at": _to_iso(doc.get("updated_at")),
                    "last_chat_ts": last_turn.get("ts") or _to_iso(doc.get("updated_at")),
                    "last_route": last_turn.get("route") or "",
                    "last_language_name": last_turn.get("language_name") or "English",
                    "last_related_services": last_turn.get("related_services") or [],
                    "last_question": last_turn.get("question") or "",
                    "last_answer": _extract_message_text(last_turn.get("message")),
                    "last_extra": last_extra if isinstance(last_extra, dict) else {},
                    "meeting_arranged": meeting_arranged,
                }
            )
        return out

    def get_followup_log(self, session_id: str, token_id: str | None) -> dict[str, Any] | None:
        return self.log_coll.find_one(
            {"sessionId": session_id, "tokenId": token_id},
            {"_id": 0},
        )

    def upsert_pending_log(self, candidate: dict[str, Any]) -> dict[str, Any]:
        now_iso = _to_iso(_wib_now())
        base_doc = {
            "sessionId": candidate["sessionId"],
            "tokenId": candidate.get("tokenId"),
            "last_chat_ts": candidate.get("last_chat_ts"),
            "last_route": candidate.get("last_route") or "",
            "last_language_name": candidate.get("last_language_name") or "English",
            "last_related_services": candidate.get("last_related_services") or [],
            "followup_sent": False,
            "followup_sent_at": None,
            "followup_count": 0,
            "status": "pending",
            "meeting_arranged": bool(candidate.get("meeting_arranged")),
            "extra": {
                "last_question": candidate.get("last_question") or "",
                "last_answer": candidate.get("last_answer") or "",
                "updated_at_source": candidate.get("updated_at"),
                "log_created_at": now_iso,
            },
        }

        prev = self.get_followup_log(candidate["sessionId"], candidate.get("tokenId"))
        if prev and prev.get("last_chat_ts") == candidate.get("last_chat_ts"):
            return prev

        if prev and prev.get("last_chat_ts") != candidate.get("last_chat_ts"):
            base_doc["followup_count"] = 0

        return self.log_coll.find_one_and_update(
            {"sessionId": candidate["sessionId"], "tokenId": candidate.get("tokenId")},
            {"$set": base_doc},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )

    def mark_sent(
        self,
        *,
        session_id: str,
        token_id: str | None,
        followup_text: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now_iso = _to_iso(_wib_now())
        return self.log_coll.find_one_and_update(
            {"sessionId": session_id, "tokenId": token_id},
            {
                "$set": {
                    "followup_sent": True,
                    "followup_sent_at": now_iso,
                    "status": "sent",
                    "followup_text": followup_text,
                    "outbound_payload": payload or {},
                },
                "$inc": {"followup_count": 1},
            },
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )

    def mark_skipped(
        self,
        *,
        session_id: str,
        token_id: str | None,
        reason: str,
    ) -> dict[str, Any] | None:
        now_iso = _to_iso(_wib_now())
        return self.log_coll.find_one_and_update(
            {"sessionId": session_id, "tokenId": token_id},
            {
                "$set": {
                    "status": "skipped",
                    "skip_reason": reason,
                    "skip_ts": now_iso,
                }
            },
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )

    def append_followup_to_chat_history(
        self,
        *,
        session_id: str,
        token_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        now_dt = _wib_now()
        self.chat_coll.update_one(
            {"sessionId": session_id, "tokenId": token_id},
            {
                "$push": {"chat_history": payload},
                "$set": {"updated_at": now_dt},
                "$setOnInsert": {
                    "sessionId": session_id,
                    "tokenId": token_id,
                    "created_at": now_dt,
                },
            },
            upsert=True,
        )


def _extract_message_text(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, dict):
        content = message.get("content") or {}
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
    return str(message or "").strip()