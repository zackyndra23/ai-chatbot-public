# system_detection/sd_repo.py
import json, os, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from modules.chat_payload.payload_builder import now_wib_iso, default_summarization_meta
from core.app_config import Config  # memicu load_dotenv dari app_config
cfg = Config()

RUNLOG_DIR = Path(os.getenv("RUNLOG_DIR", "run_logs"))
RUNLOG_DIR.mkdir(parents=True, exist_ok=True)

WIB = timezone(timedelta(hours=7))

# def log_run(session_id: str, website_id: str, question: str, result: dict):
def log_run(session_id: str, question: str, result: dict):
    ts = time.strftime("%Y%m%d-%H%M%S")
    fname = RUNLOG_DIR / f"{ts}_{session_id[:8]}.json"
    payload = {
        "session_id": session_id,
        # "website_id": website_id,
        "question": question,
        "result": result,
        "ts": ts
    }
    try:
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # logging shouldn't break the flow
    
def _parse_ts(s: str | None) -> datetime:
    if not isinstance(s, str):
        return datetime.min
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return datetime.min

# 1) UI helper: pilih token aktif terbaru dari array tokenId_records
def pick_active_token(token_records: list[dict]) -> str | None:
    if not token_records:
        return None
    actives = [r for r in token_records if (r.get("status") or "").lower() == "active"]
    if not actives:
        return None
    actives.sort(
        key=lambda r: _parse_ts(r.get("token_deactivated_at") or r.get("token_generated_at")),
        reverse=True,
    )
    return actives[0].get("tokenId")

# 2) Server helper: cari sessionId berdasarkan tokenId (dari koleksi crisp_sessions)
def lookup_session_by_token(token_id: str) -> str | None:
    if not token_id:
        return None
    try:
        mongo_uri = cfg.MONGO_URI
        mongo_db  = cfg.MONGO_DB
        coll_name = os.getenv("CRISP_SESSIONS_COLL", "crisp_sessions")  # <- nama koleksi account UI/CRISP
        if not mongo_uri:
            return None
        cli = MongoClient(mongo_uri)
        col = cli[mongo_db][coll_name]

        # cari dokumen yang memiliki token aktif dengan tokenId = token_id
        doc = col.find_one(
            {"tokenId_records": {"$elemMatch": {"tokenId": token_id, "status": "active"}}},
            {"sessionId": 1}
        ) or col.find_one(
            {"tokenId_records.tokenId": token_id},
            {"sessionId": 1, "tokenId_records": 1}
        )

        if not doc:
            return None
        return (doc.get("sessionId") or doc.get("session_id") or doc.get("session"))
    except Exception:
        return None
    
def has_any_history(session_id: str, token_id: str | None = None) -> bool:
    """True jika dokumen (sessionId[, tokenId]) sudah punya minimal 1 item chat_history."""
    try:
        if not cfg.MONGO_URI or not session_id:
            return False
        cli = MongoClient(cfg.MONGO_URI)
        col = cli[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]

        query = {"sessionId": session_id, "chat_history.0": {"$exists": True}}
        if token_id:  # fokus ke dokumen pasangan sessionId+tokenId
            query["tokenId"] = token_id

        doc = col.find_one(query, {"_id": 1})
        return bool(doc)
    except Exception:
        return False

def _mongo_cli():
    if not cfg.MONGO_URI:
        return None
    return MongoClient(cfg.MONGO_URI, connect=True)

def read_user_nick_from_sessions(session_id: str) -> str | None:
    """Ambil user.nickname dari koleksi sesi (default: crisp_sessions)."""
    if not session_id: return None
    cli = _mongo_cli()
    if not cli: return None
    try:
        coll_name = getattr(cfg, "MONGO_SESSION", "crisp_sessions")
        doc = cli[cfg.MONGO_DB][coll_name].find_one(
            {"sessionId": session_id},
            {"_id": 0, "user.nickname": 1}
        )
        if not doc: return None
        u = doc.get("user") or {}
        nick = (u.get("nickname") or "").strip()
        return nick or None
    except Exception:
        return None
    finally:
        try: cli.close()
        except: pass

def ensure_user_nick_in_sessions(session_id: str, nickname: str | None) -> None:
    """Set user.nickname jika belum ada; tidak overwrite yang sudah ada."""
    if not session_id or not nickname: return
    cli = _mongo_cli()
    if not cli: return
    try:
        coll_name = getattr(cfg, "MONGO_SESSION", "crisp_sessions")
        # update hanya jika field belum ada / kosong
        cli[cfg.MONGO_DB][coll_name].update_one(
            {"sessionId": session_id, "$or": [{"user.nickname": {"$exists": False}}, {"user.nickname": ""}]},
            {"$set": {"user.nickname": nickname}},
            upsert=False
        )
    except Exception:
        pass
    finally:
        try: cli.close()
        except: pass

def read_user_country_from_sessions(session_id: str) -> str | None:
    """Ambil kode negara (ISO alpha-2, diharapkan kapital) dari crisp_sessions.
    Coba di berbagai jalur umum: user.country, location.country, ip_info.country_code, dll.
    """
    if not session_id:
        return None
    cli = _mongo_cli()
    if not cli:
        return None
    try:
        coll_name = getattr(cfg, "MONGO_SESSION", "crisp_sessions")
        doc = cli[cfg.MONGO_DB][coll_name].find_one(
            {"sessionId": session_id},
            {
                "_id": 0,
                "user.country": 1,
            }
        )
        if not doc:
            return None

        def pick(*paths):
            cur = doc
            for p in paths:
                if cur is None:
                    return None
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    return None
            return cur

        candidates = [
            pick("user","country"),
        ]
        for c in candidates:
            if c and isinstance(c, str):
                code = c.strip().upper()
                if 2 <= len(code) <= 3:  # tolerate 2–3 just in case
                    return code[:2]  # normalize to alpha-2
        return None
    finally:
        try: cli.close()
        except: pass

# ---------- Compat wrappers untuk meeting_arrangement & modul lain ----------

def read_user_profile_from_sessions(session_id: str) -> dict:
    """
    Ambil profil user dari koleksi sesi (default: crisp_sessions).
    Return:
      {
        "nickname": str, "email": str, "phone": str,
        "country": str (ISO-2 upper), "region": str, "city": str
      }
    """
    if not session_id:
        return {}
    cli = _mongo_cli()
    if not cli:
        return {}
    try:
        coll_name = getattr(cfg, "MONGO_SESSION", "crisp_sessions")
        doc = cli[cfg.MONGO_DB][coll_name].find_one(
            {"sessionId": session_id},
            {
                "_id": 0,
                "user.nickname": 1, "user.email": 1, "user.phone": 1,
                "user.country": 1, "user.region": 1, "user.city": 1,
            }
        ) or {}
        u = doc.get("user") or {}
        return {
            "nickname": (u.get("nickname") or "").strip(),
            "email":    (u.get("email") or "").strip(),
            "phone":    (u.get("phone") or "").strip(),
            "country":  (u.get("country") or "").strip().upper()[:2],
            "region":   (u.get("region") or "").strip(),
            "city":     (u.get("city") or "").strip(),
        }
    except Exception:
        return {}
    finally:
        try: cli.close()
        except: pass

def extract_message_text(msg) -> str:
    """
    Normalisasi message:
    - jika message sudah string -> return string
    - jika ChatMessage dict -> ambil message["content"]["text"]
    """
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, dict):
            t = content.get("text")
            if isinstance(t, str):
                return t
    return ""


def read_chat_history(session_id: str, token_id: str | None = None, limit: int = 12) -> list[dict]:
    """
    Ambil potongan chat_history terbaru untuk summary/payload kalender.
    Distandarkan ke list of dict:
      [{"question": "...", "message": "...", "related_services": [...]}, ...]
    """
    if not session_id:
        return []
    cli = _mongo_cli()
    if not cli:
        return []
    try:
        col = cli[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]
        key = {"sessionId": session_id}
        if token_id:
            key["tokenId"] = token_id
        doc = col.find_one(key, {"chat_history": {"$slice": -abs(limit)}}) or {}
        out = []
        for r in (doc.get("chat_history") or []):
            out.append({
                "question": r.get("question") or "",
                "message":  extract_message_text(r.get("message")),
                "related_services": r.get("related_services") or [],
                "summarization_meta": r.get("summarization_meta") or {},
            })
        return out
    except Exception:
        return []
    finally:
        try: cli.close()
        except: pass

def read_language_history(session_id: str, token_id: str | None = None, limit: int = 12) -> list[dict]:
    """
    Ambil potongan chat_history terbaru untuk summary/payload kalender.
    Distandarkan ke list of dict.
    """
    if not session_id:
        return []
    cli = _mongo_cli()
    if not cli:
        return []
    try:
        col = cli[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]
        key = {"sessionId": session_id}
        if token_id:
            key["tokenId"] = token_id

        doc = col.find_one(key, {"chat_history": {"$slice": -abs(limit)}}) or {}

        out = []
        for r in (doc.get("chat_history") or []):
            out.append({
                # ✅ INI YANG KRUSIAL UNTUK FALLBACK
                "language_name": (r.get("language_name") or "").strip(),
                # (opsional) kalau suatu saat kamu simpan language_code di chat_history
                "language_code": (r.get("language_code") or "").strip(),
            })
        return out
    except Exception:
        return []
    finally:
        try:
            cli.close()
        except Exception:
            pass

def _extract_summarization_meta(convo_rec: dict) -> tuple[str, int, int, str]:
    sm = (convo_rec.get("summarization_meta") or {}) if isinstance(convo_rec, dict) else {}
    summary_applied = sm.get("summary_applied", "-")
    summary_input = int(sm.get("summary_input") or 0)
    summary_output = int(sm.get("summary_output") or 0)
    chat_summarization = sm.get("chat_summarization", "-")
    return summary_applied, summary_input, summary_output, chat_summarization

def _infer_language_code_from_name(language_name: str | None) -> str:
    low = (language_name or "").strip().lower()

    if "indo" in low:
        return "id"
    if "english" in low:
        return "en"
    if "thai" in low:
        return "th"
    if "malay" in low:
        return "ms"
    if "french" in low:
        return "fr"
    if "german" in low or "deutsch" in low:
        return "de"
    if "dutch" in low or "nederlands" in low:
        return "nl"
    if "romanian" in low or "română" in low or "romana" in low:
        return "ro"
    if "japanese" in low or "日本語" in low:
        return "ja"
    if "russian" in low or "рус" in low:
        return "ru"
    if "italian" in low or "italiano" in low:
        return "it"
    if "chinese" in low or "mandarin" in low or "中文" in low:
        return "zh"
    if "vietnamese" in low or "tiếng việt" in low or "viet" in low:
        return "vi"

    return ""

def append_chat_history_mongo(session_id: str, token_id: str | None,
                              question: str, result: dict) -> bool:
    now_iso_wib = datetime.now(WIB).isoformat()
    ts = result.get("ts") or now_iso_wib

    sm = result.get("summarization_meta") or {}
    summary_applied = sm.get("summary_applied") or result.get("summary_applied") or "-"
    summary_input   = int(sm.get("summary_input")   or result.get("summary_input")   or 0)
    summary_output  = int(sm.get("summary_output")  or result.get("summary_output")  or 0)
    chat_summarization = sm.get("chat_summarization") or result.get("chat_summarization") or "-"

    in_tok  = int(result.get("input_token") or 0)
    out_tok = int(result.get("output_token") or 0)

    input_total  = result.get("input_total")
    output_total = result.get("output_total")
    if input_total is None:
        input_total = in_tok + summary_input
    if output_total is None:
        output_total = out_tok + summary_output

    convo_rec = {
        "ts": ts,
        "question": result.get("question", question) or question,
        "message": result.get("message", ""),
        "prompt_applied": result.get("prompt_applied") or "",
        "language_name": result.get("language_name") or "",
        "language_code": result.get("language_code") or _infer_language_code_from_name(result.get("language_name")),
        "user_nick": result.get("user_nick") or "",
        "route": result.get("route") or "",
        "related_services": result.get("related_services") or [],
        "docs_retrieved_count": int(result.get("docs_retrieved_count") or 0),
        "respond_duration": float(result.get("respond_duration") or 0.0),

        "input_token": in_tok,
        "output_token": out_tok,
        "input_total": int(input_total or 0),
        "output_total": int(output_total or 0),

        "summarization_meta": {
            "summary_applied": summary_applied,
            "summary_input": summary_input,
            "summary_output": summary_output,
            "chat_summarization": chat_summarization,
        },
        "extra": result.get("extra") or {},
    }

    ok_mongo = False
    try:
        if not cfg.MONGO_URI:
            raise RuntimeError("MONGO_URI empty")
        client = MongoClient(cfg.MONGO_URI)
        col = client[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]

        key = {"sessionId": session_id, "tokenId": token_id or session_id}
        col.update_one(
            key,
            {
                "$setOnInsert": {**key, "created_at": now_iso_wib},
                "$set": {"updated_at": now_iso_wib},
                "$push": {"chat_history": convo_rec},
            },
            upsert=True
        )
        ok_mongo = True
    except Exception as e:
        print(f"[chat_history][mongo] persist failed: {e}")
    finally:
        try:
            client.close()
        except Exception:
            pass

    # sheet best-effort
    try:
        from modules.googlesheet_chat_history.gsch_utils import flag_enabled
        if flag_enabled():
            from modules.googlesheet_chat_history.gsch_repo import append_chat_history_row

            extra = convo_rec.get("extra") or {}
            dual_agent_meta = (extra.get("dual_agent_meta") or {})

            append_chat_history_row(
                session_id=session_id,
                token_id=token_id or session_id,
                user_nick=convo_rec["user_nick"],
                timestamp_iso=ts,
                summary_applied=summary_applied,
                prompt_applied=convo_rec["prompt_applied"],
                route=convo_rec["route"],
                related_services=convo_rec["related_services"],
                docs_retrieved_count=convo_rec["docs_retrieved_count"],
                question=convo_rec["question"],
                language_name=convo_rec["language_name"],
                message=convo_rec["message"],
                respond_duration=convo_rec["respond_duration"],
                input_token=in_tok,
                output_token=out_tok,
                summary_input=summary_input,
                summary_output=summary_output,
                input_total=convo_rec["input_total"],
                output_total=convo_rec["output_total"],
                chat_summarization=chat_summarization,
                dual_agent_meta=dual_agent_meta,
            )
    except Exception as e:
        print(f"[chat_history][sheet] append failed: {e}")

    return ok_mongo

def read_chat_history_full(session_id: str, token_id: str | None = None, limit: int = 200) -> list[dict]:
    """
    Ambil chat_history lebih lengkap (untuk reset pipeline).
    Minimal harus bawa: question, message (raw), related_services, extra, language_name/code.
    """
    if not session_id:
        return []
    cli = _mongo_cli()
    if not cli:
        return []
    try:
        col = cli[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]
        key = {"sessionId": session_id}
        if token_id:
            key["tokenId"] = token_id

        doc = col.find_one(key, {"chat_history": {"$slice": -abs(limit)}}) or {}
        out: list[dict] = []
        for r in (doc.get("chat_history") or []):
            out.append({
                "question": r.get("question") or "",
                "message": r.get("message"),  # raw
                "related_services": r.get("related_services") or [],
                "extra": r.get("extra") or {},
                "language_name": (r.get("language_name") or "").strip(),
                "language_code": (r.get("language_code") or "").strip(),
                "route": (r.get("route") or "").strip(),
                "ts": r.get("ts"),
            })
        return out
    except Exception:
        return []
    finally:
        try:
            cli.close()
        except Exception:
            pass


# === Anti-Redundancy: recent_chunk_ids rolling window ===========================
# Stored as a top-level sibling field on the chat_history collection's
# per-(sessionId, tokenId) document, alongside the existing `chat_history` array.
# Piggybacks on the same update_one call pattern used by append_chat_history_mongo.
# See docs/superpowers/specs/2026-05-11-anti-redundancy-answer-quality-design.md §3.

def get_recent_chunk_ids(session_id: str, token_id: str | None) -> list[str]:
    """Read the per-session recent_chunk_ids list. Empty when missing."""
    if not session_id:
        return []
    cli = _mongo_cli()
    if cli is None:
        return []
    try:
        col = cli[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]
        key = {"sessionId": session_id, "tokenId": token_id or session_id}
        doc = col.find_one(key, {"recent_chunk_ids": 1, "_id": 0}) or {}
        ids = doc.get("recent_chunk_ids") or []
        return [str(x) for x in ids if x]
    except Exception:
        return []
    finally:
        try:
            cli.close()
        except Exception:
            pass


def update_recent_chunk_ids(session_id: str, token_id: str | None, new_ids: list[str]) -> None:
    """Append new chunk IDs to the rolling window, trimmed to WINDOW × FLOOR.

    Idempotent re-appends of the same ID are tolerated (the cap protects us).
    """
    if not session_id or not new_ids:
        return
    cli = _mongo_cli()
    if cli is None:
        return
    try:
        col = cli[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]
        key = {"sessionId": session_id, "tokenId": token_id or session_id}
        existing_doc = col.find_one(key, {"recent_chunk_ids": 1, "_id": 0}) or {}
        existing = list(existing_doc.get("recent_chunk_ids") or [])
        combined = existing + [str(x) for x in new_ids if x]
        cap = int(getattr(cfg, "REDUNDANCY_RECENT_CHUNKS_WINDOW", 5)) * int(getattr(cfg, "CTX_DOCS_FLOOR", 4))
        if cap > 0 and len(combined) > cap:
            combined = combined[-cap:]
        col.update_one(
            key,
            {"$set": {"recent_chunk_ids": combined}, "$setOnInsert": {**key}},
            upsert=True,
        )
    except Exception:
        pass
    finally:
        try:
            cli.close()
        except Exception:
            pass
