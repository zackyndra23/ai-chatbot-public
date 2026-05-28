from __future__ import annotations
from modules.token_generate.tg_utils import now_local, iso_local
import os, requests
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from pymongo import MongoClient
import logging, re
from datetime import datetime
from pathlib import Path
from dotenv import dotenv_values

@dataclass
class UiConfig:
    backend_origin: str
    base_path: str
    mongo_uri: str
    mongo_db: str
    mongo_coll: str
    token_svc_origin: str
    token_generate_path: str
    token_deactivate_path: str
    api_header_name: str
    default_session_id: str = os.getenv("TESTING_SESSION_ID", "")

def _force_env_from_secrets():
    # Cari secrets/.env relatif ke project root (dua level di atas file ini)
    here = Path(__file__).resolve()
    project_root = here.parents[2]   # .../rag_chatbot_v01_01
    env_file = project_root / "secrets" / ".env"
    if env_file.exists():
        os.environ.update(dotenv_values(env_file))

def load_ui_config() -> UiConfig:
    _force_env_from_secrets()  # pastikan sebelum baca os.getenv(*)
    return UiConfig(
        backend_origin=os.getenv("TESTING_BACKEND_ORIGIN", ""),
        base_path=os.getenv("TESTING_BASE_PATH", "/rag-assistant/chatbot/claude4sonnet"),
        mongo_uri=os.getenv("MONGO_URI", ""),
        mongo_db=os.getenv("MONGO_DB", "chatbot"),
        mongo_coll=os.getenv("MONGO_SESSION", os.getenv("API_KEYS_COLLECTION", "crisp_sessions")),
        token_svc_origin=os.getenv("TOKEN_SVC_ORIGIN", "http://localhost:2303"),
        token_generate_path=os.getenv("TOKEN_GENERATE_PATH", "/rag-assistant/session-id-generate"),
        token_deactivate_path=os.getenv("TOKEN_DEACTIVATE_PATH", "/rag-assistant/token-deactivate-append"),
        api_header_name=os.getenv("API_HEADER_NAME", "x-api-key"),
    )

# def _mongo_client(cfg: UiConfig) -> MongoClient:
#     return MongoClient(cfg.mongo_uri, connect=True)

def _mongo_client(cfg: UiConfig) -> MongoClient:
    # print("DEBUG: using URI", cfg.mongo_uri)
    return MongoClient(cfg.mongo_uri, connect=True)

def find_account_by_name(cfg: UiConfig, name: str):
    key = (name or "").strip()

    # Regex: anchor + toleransi spasi kiri/kanan, case-insensitive
    # contoh: "  INT521  " tetap ketemu
    patt = re.compile(rf"^\s*{re.escape(key)}\s*$", re.IGNORECASE)

    with _mongo_client(cfg) as cli:
        col = cli[cfg.mongo_db][cfg.mongo_coll]
        # print("DEBUG: DB", cfg.mongo_db, "COLL", cfg.mongo_coll, "count", col.count_documents({}))

        doc = None

        # 1) Tipe baru: cari by user.nickname (exact & regex)
        doc = col.find_one({"user.nickname": key}) or col.find_one({"user.nickname": {"$regex": patt.pattern, "$options": "i"}})

        # 2) Fallback lain yang sering dipakai user:
        if not doc:
            doc = (col.find_one({"sessionId": key})
                   or col.find_one({"user.email": {"$regex": patt.pattern, "$options": "i"}})
                   or col.find_one({"user.phone": {"$regex": patt.pattern, "$options": "i"}}))

        if not doc:
            logging.getLogger("chat_testing_ui").warning("account not found: key=%s (db=%s coll=%s)", key, cfg.mongo_db, cfg.mongo_coll)
            return None, None

        # --- Ambil token aktif untuk crisp_sessions (hormati record deactive terbaru) ---
        if "user" in doc and "sessionId" in doc:
            recs = (doc.get("tokenId_records") or [])
            from datetime import datetime
            def _ts(r):
                t = r.get("token_deactivated_at") or r.get("token_generated_at")
                if isinstance(t, str):
                    try:
                        return datetime.fromisoformat(t.replace("Z","+00:00"))
                    except Exception:
                        pass
                return datetime.min

            latest_by_token = {}
            for r in recs:
                tid = r.get("tokenId")
                if not tid:
                    continue
                cur = latest_by_token.get(tid)
                if (cur is None) or (_ts(r) > _ts(cur)):
                    latest_by_token[tid] = r

            # Ambil token yang 'latest'-nya masih active
            for r in sorted(latest_by_token.values(), key=_ts, reverse=True):
                if r.get("status") == "active":
                    return doc, r.get("tokenId")
            return doc, None

# --- helper ACTIVATE (tetap pakai path generate yang sama) ---
def generate_session_id(cfg: UiConfig, header_value: str) -> Dict[str, Any]:
    url = f"{cfg.token_svc_origin}{cfg.token_generate_path}"
    resp = requests.post(url, data="true",
                         headers={cfg.api_header_name: header_value, "Content-Type": "text/plain"},
                         timeout=30)
    try:
        return {"status_code": resp.status_code, "json": resp.json()}
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}
    
# --- helper SHUTDOWN (append semantics via endpoint baru) ---
def deactivate_token_append(cfg: UiConfig, session_id: str) -> Dict[str, Any]:
    url = f"{cfg.token_svc_origin}{cfg.token_deactivate_path}"
    resp = requests.post(url, data="", headers={cfg.api_header_name: session_id}, timeout=30)
    try:
        return {"status_code": resp.status_code, "json": resp.json()}
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}
    
def shutdown_append_direct(cfg: UiConfig, session_id: str) -> bool:
    with _mongo_client(cfg) as cli:
        col = cli[cfg.mongo_db][cfg.mongo_coll]
        doc = col.find_one({"sessionId": session_id}, {"tokenId_records": 1})
        if not doc:
            return False
        recs = doc.get("tokenId_records") or []
        from datetime import datetime
        def _ts(r):
            t = r.get("token_generated_at")
            if isinstance(t, str):
                try:
                    return datetime.fromisoformat(t.replace("Z","+00:00"))
                except Exception:
                    pass
            return datetime.min
        actives = [r for r in recs if (r or {}).get("status") == "active" and r.get("tokenId")]
        if not actives:
            return True  # nothing to do
        actives.sort(key=_ts, reverse=True)
        a = actives[0]
        rec = {
            "tokenId": a["tokenId"],
            "status": "deactive",
            # "token_generated_at": a.get("token_generated_at"),
            "token_deactivated_at": iso_local(now_local()),
            "reason": "ui_shutdown",
        }
        col.update_one({"sessionId": session_id}, {"$push": {"tokenId_records": rec}})
        return True