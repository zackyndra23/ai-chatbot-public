from __future__ import annotations

import secrets
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection

from .tg_utils import getenv_str, now_local, iso_local, slugify_name

class TokenRepo:
    def __init__(self) -> None:
        mongo_uri = getenv_str("MONGO_URI", "mongodb://localhost:27017")
        mongo_db = getenv_str("MONGO_DB", "integrity_chatbot")
        self.collection_name = getenv_str("MONGO_SESSION", "api_keys")
        self.api_header_name = getenv_str("API_HEADER_NAME", "X-APIKey")

        self.client = MongoClient(mongo_uri)
        self.db = self.client[mongo_db]
        self.col: Collection = self.db[self.collection_name]

        # Indexes
        self.col.create_index(
            [("userId", 1)],
            unique=True,
            name="uniq_user_id_nonnull",
            partialFilterExpression={"userId": {"$type": "string"}}
        )
        self.col.create_index([("api_key", 1)], name="api_key_idx")
        self.col.create_index([("user_id_generated_at", 1)], name="user_id_generated_at_idx")
        # self.col.create_index([("session_id_records.token", 1)], name="session_token_idx")
        # self.col.create_index([("session_id_records.status", 1)], name="session_status_idx")
        self.col.create_index([("tokenId_records.tokenId", 1)], name="session_token_idx")
        self.col.create_index([("tokenId_records.status", 1)], name="session_status_idx")
        self.col.create_index([("websiteId", 1)], name="websiteId_idx")  # NEW: query by website_id if needed
        self.col.create_index([("sessionId", 1)], name="sessionId_idx")

        # (opsional) index legacy biar aman saat transisi:
        self.col.create_index([("api_key_user", 1)], name="legacy_api_key_user_idx")

    # ------------------ API KEY ------------------
    def generate_api_key(self, websiteId: Optional[str], api_key: Optional[str], name: Optional[str] = None) -> Dict[str, Any]:
        slug = slugify_name(name or "", "user")
        base = secrets.token_urlsafe(20)                # ~160-bit
        userId = f"{base}_{slug}"                      # << pattern baru
        userId = userId[:128]                         # batasi panjang

        # pastikan unik (sangat jarang tabrakan, tapi aman)
        while self.col.find_one({"userId": userId}):
            base = secrets.token_urlsafe(21)
            userId = (f"{base}_{slug}")[:128]

        doc: Dict[str, Any] = {
            "websiteId": websiteId,
            "api_key": api_key,
            "name": name,                                # << simpan display name
            "userId": userId,
            "user_id_generated_at": iso_local(now_local()),
            # "session_id_records": []
            "tokenId_records": []
        }
        self.col.insert_one(doc)
        return {
            "websiteId": websiteId,
            "api_key": api_key,
            "name": name,
            "userId": userId,
            "user_id_generated_at": doc["user_id_generated_at"]
        }

    def _selector_for_key(self, key: str) -> dict:
        # cari berdasarkan api_key (baru) ATAU legacy fields
        return {"$or": [
            {"sessionId": key},     # << inilah kuncinya untuk crisp_sessions
            {"api_key": key},
            {"api_key_user": key},  # legacy
            {"userId": key},       # kalau dulu pernah kirim userId di header
        ]}

    def get_by_api_key(self, key: str) -> Optional[Dict[str, Any]]:       
        return self.col.find_one(self._selector_for_key(key))

    # ------------------ SESSION TOKEN ------------------
    def has_active_session(self, key: str) -> bool:
        """
        EFFECTIVE ACTIVE:
        Token dianggap aktif hanya jika event TERBARU untuk tokenId tsb berstatus 'active'.
        (Append 'deactive' tidak mengubah event 'active' lama, tapi harus mematikan token tsb.)
        """
        doc = self.col.find_one(self._selector_for_key(key), {"tokenId_records": 1})
        if not doc:
            return False
        recs = doc.get("tokenId_records") or []

        def _ts(r):
            # pakai timestamp yang paling relevan (deactivate > generate)
            t = r.get("token_deactivated_at") or r.get("token_generated_at")
            if isinstance(t, str):
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00"))
                except Exception:
                    pass
            return datetime.min

        # ambil event TERBARU untuk setiap tokenId
        latest_by_token = {}
        for r in recs:
            tid = r.get("tokenId")
            if not tid:
                continue
            cur = latest_by_token.get(tid)
            if (cur is None) or (_ts(r) > _ts(cur)):
                latest_by_token[tid] = r

        # aktif hanya bila event terbaru-nya 'active'
        return any(r.get("status") == "active" for r in latest_by_token.values())

    def append_active_token(self, key: str) -> Dict[str, Any]:             
        # sessionId = secrets.token_urlsafe(24)
        tokenId = secrets.token_urlsafe(24)
        token_rec = {
            # "sessionId": sessionId,
            "tokenId": tokenId,
            "status": "active",
            "token_generated_at": iso_local(now_local()),
        }
        res = self.col.find_one_and_update(
            self._selector_for_key(key),
            # {"$push": {"session_id_records": token_rec}},
            {"$push": {"tokenId_records": token_rec}},
            return_document=ReturnDocument.AFTER
        )
        if not res:
            raise ValueError("API key not found")
        return token_rec

    # ---------- background scan ----------
    def find_all_with_active_tokens(self) -> List[Dict[str, Any]]:
        cursor = self.col.find(
            # {"session_id_records.status": "active"},
            # {"api_key": 1, "userId": 1, "session_id_records": 1}
            {"tokenId_records.status": "active"},
            {"sessionId": 1, "tokenId_records": 1}
        )
        return list(cursor)

    def deactivate_if_rules_met(self, key: str, token_obj: Dict[str, Any],
                                idle_with_history_s: int,
                                no_activity_ttl_s: int) -> Optional[str]:
        """
        Returns reason string if deactivated; None otherwise.
        """
        def parse(dt_str: Optional[str]) -> Optional[datetime]:
            if not dt_str:
                return None
            try:
                return datetime.fromisoformat(dt_str)
            except Exception:
                try:
                    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                except Exception:
                    return None

        token_gen = parse(token_obj.get("token_generated_at"))
        last_act = parse(token_obj.get("last_activity_at"))
        chat_hist = token_obj.get("chat_history") or []

        now = datetime.now(timezone.utc).astimezone()

        if chat_hist:
            ref = last_act or token_gen
            if ref and (now - ref).total_seconds() >= idle_with_history_s:
                ok = self.col.update_one(
                    {
                        "$and": [
                            self._selector_for_key(key),
                            # {"session_id_records": {"$elemMatch": {"sessionId": token_obj["token"], "status": "active"}}}
                            {"tokenId_records": {"$elemMatch": {"tokenId": token_obj["tokenId"], "status": "active"}}}
                        ]
                    },
                    {"$set": {
                        # "session_id_records.$.status": "deactive",
                        # "session_id_records.$.token_deactivated_at": iso_local(now)
                        "tokenId_records.$.status": "deactive",
                        "tokenId_records.$.token_deactivated_at": iso_local(now)
                    }}
                ).modified_count > 0

                if ok:
                    return "idle_with_history"
        else:
            if token_gen and (now - token_gen).total_seconds() >= no_activity_ttl_s:
                ok = self.col.update_one(
                    {
                        "$and": [
                            self._selector_for_key(key),
                            # {"session_id_records": {"$elemMatch": {"sessionId": token_obj["token"], "status": "active"}}}
                            {"tokenId_records": {"$elemMatch": {"tokenId": token_obj["tokenId"], "status": "active"}}}
                        ]
                    },
                    {"$set": {
                        # "session_id_records.$.status": "deactive",
                        # "session_id_records.$.token_deactivated_at": iso_local(now)
                        "tokenId_records.$.status": "deactive",
                        "tokenId_records.$.token_deactivated_at": iso_local(now)
                    }}
                ).modified_count > 0

                if ok:
                    return "no_activity_ttl"
        return None