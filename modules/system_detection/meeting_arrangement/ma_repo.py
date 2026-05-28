from __future__ import annotations
import os, re
import time, threading
from functools import lru_cache
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from pymongo import MongoClient, ReturnDocument
from core.app_config import Config
from .ma_utils import WIB, windows_from_intervals
from .ma_types import Slot
from collections import defaultdict
import gspread
import requests
from google.oauth2.service_account import Credentials
from modules.googlesheet_chat_history.gsch_client import get_ws_by_id_tab, SheetNotConfigured
from modules.googlesheet_chat_history.gsch_repo import get_sheet_values

cfg = Config()
SLOTS_LABEL_RX = re.compile(r'^\s*(?P<sh>\d{2}):(?P<sm>\d{2})\s*-\s*(?P<eh>\d{2}):(?P<em>\d{2})\s*$')

_IDV_CACHE = {"built_at": 0.0, "ttl": 120.0, "data": {}}  # (day_iso, slot) -> [emails]
# _INDV_TTL   = float(os.getenv("INDV_SHEET_TTL_SEC", "60"))   # default 60s
_INDV_TTL   = cfg.INDV_SHEET_TTL_SEC
# _SHEETS_MIN_INTERVAL = float(os.getenv("SHEETS_MIN_INTERVAL", "0.25"))  # jeda min antar panggilan actual API
_SHEETS_MIN_INTERVAL = cfg.SHEETS_MIN_INTERVAL
_last_sheet_call = 0.0
_cache_lock = threading.Lock()

_STD_LABELS = [
    "09:00 - 10:00","10:00 - 11:00","11:00 - 12:00","12:00 - 13:00",
    "13:00 - 14:00","14:00 - 15:00","15:00 - 16:00","16:00 - 17:00"
]

IDV_SPREADSHEET_ID = cfg.SALES_SHEET_ID
IDV_RANGE_NAME     = cfg.SALES_SHEET_NAME

_SPLIT_PAT = re.compile(r"\s*(?:\|\||\||/|—|-|–|\n)\s*")  # variasi pemisah umum
_IDV_LABEL_RE = re.compile(
    r'^\s*(?P<email>[^—\-]+?)\s*[—\-]\s*(?P<start>\d{2}:\d{2})\s*[-–]\s*(?P<end>\d{2}:\d{2})\s*$'
)

def _cli():
    if not cfg.MONGO_URI: return None
    return MongoClient(cfg.MONGO_URI, connect=True)

def _coll(name_env: str, fallback: str):
    return os.getenv(name_env, fallback)

def list_sales_profiles_by_country(country_code: str) -> List[dict]:
    if not country_code: return []
    cli = _cli()
    if not cli: return []
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_PROFILES_COLL", "sales_profiles")]
        out = []
        for d in col.find({"country": country_code.upper()}, {"_id": 0}):
            em = d.get("salesEmail") or d.get("email")
            if em:
                d["_salesEmail"] = em
                out.append(d)
        return out
    finally:
        try: cli.close()
        except: pass

def read_sales_profile_by_email(sales_email: str) -> Optional[dict]:
    cli = _cli()
    if not cli: return None
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_PROFILES_COLL", "sales_profiles")]
        return col.find_one({"salesEmail": sales_email}, {"_id": 0})
    finally:
        try: cli.close()
        except: pass

def _parse_label_to_wib(day: date, label: str) -> Optional[tuple[datetime, datetime]]:
    m = SLOTS_LABEL_RX.match(str(label))
    if not m: return None
    sh, sm, eh, em = map(int, (m.group("sh"), m.group("sm"), m.group("eh"), m.group("em")))
    s = datetime(day.year, day.month, day.day, sh, sm, tzinfo=WIB)
    e = datetime(day.year, day.month, day.day, eh, em, tzinfo=WIB)
    if s >= e: return None
    return s, e

def get_sales_slots_for_date(sales_email: str, day: date) -> List[Slot]:
    cli = _cli()
    if not cli: return []
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_SLOTS_COLL", "sales_slots2")]
        start_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end_utc   = start_utc + timedelta(days=1)
        doc = col.find_one({"salesEmail": sales_email, "date": {"$gte": start_utc, "$lt": end_utc}}, {"_id":0})
        out: List[Slot] = []
        if not doc: return out
        slots_obj: Dict[str, dict] = doc.get("slots") or {}
        for label, meta in slots_obj.items():
            parsed = _parse_label_to_wib(day, label)
            if not parsed: continue
            st, en = parsed
            available = bool((meta or {}).get("available", False))
            booked = bool((meta or {}).get("booked", False))
            status = "booked" if booked else ("free" if available and not booked else "busy")
            out.append({"start": st, "end": en, "status": status, "label": label})
        out.sort(key=lambda s: s["start"])
        return out
    finally:
        try: cli.close()
        except: pass

def count_booked_for_date(sales_email: str, day: date) -> int:
    return sum(1 for s in get_sales_slots_for_date(sales_email, day) if s["status"] == "booked")

def book_slot_atomically(sales_email: str, day: date, label: str, session_id: str) -> bool:
    """Safely flip one slot to booked=true, available=false if still free."""
    cli = _cli()
    if not cli: return False
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_SLOTS_COLL", "sales_slots2")]
        start_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end_utc   = start_utc + timedelta(days=1)
        # filter field path "slots.{label}.available"
        field_av = f"slots.{label}.available"
        field_bk = f"slots.{label}.booked"
        field_by = f"slots.{label}.bookedBy"
        field_at = f"slots.{label}.bookedAt"
        q = {
            "salesEmail": sales_email,
            "date": {"$gte": start_utc, "$lt": end_utc},
            field_av: True,
            field_bk: False,
        }
        u = {
            "$set": {field_av: False, field_bk: True, field_by: session_id, field_at: datetime.now(timezone.utc)}
        }
        res = col.find_one_and_update(q, u, return_document=ReturnDocument.AFTER)
        return bool(res)
    finally:
        try: cli.close()
        except: pass

def list_distinct_sales_emails(country: str | None = None) -> list[str]:
    """Ambil daftar sales dari sales_profiles (prioritaskan filter country).
    Jika kosong, fallback ambil distinct dari sales_slots."""
    cli = _cli()
    if not cli: 
        return []
    try:
        db = cli[cfg.MONGO_DB]
        prof_col = db[_coll("SALES_PROFILES_COLL", "sales_profiles")]
        q = {"salesEmail": {"$exists": True, "$ne": None}}
        if country:
            q["country"] = country.upper()
        emails = [d["salesEmail"] for d in prof_col.find(q, {"salesEmail": 1, "_id": 0})]
        if emails:
            return sorted(set(emails))

        slots_col = db[_coll("SALES_SLOTS_COLL", "sales_slots2")]
        distinct = slots_col.distinct("salesEmail")
        return sorted([e for e in distinct if e])
    finally:
        try: cli.close()
        except: pass

def free_labels_for_date(sales_email: str, day: date) -> list[str]:
    """Kembalikan label string yang 'available==true & booked==false'."""
    cli = _cli()
    if not cli:
        return []
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_SLOTS_COLL", "sales_slots2")]
        start_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end_utc   = start_utc + timedelta(days=1)
        doc = col.find_one({"salesEmail": sales_email, "date": {"$gte": start_utc, "$lt": end_utc}}, {"slots": 1, "_id": 0})
        if not doc or not doc.get("slots"):
            return []
        labs = []
        for lab, meta in (doc["slots"] or {}).items():
            if (meta or {}).get("available") and not (meta or {}).get("booked"):
                labs.append(lab)
        return sorted(labs)
    finally:
        try: cli.close()
        except: pass

def labels_covering_window(sales_email: str, day: date, start_wib: datetime, end_wib: datetime) -> list[str]:
    """Kembalikan list label berurutan yang sepenuhnya menutupi [start,end].
    Hanya bekerja jika boundary permintaan tepat di ujung label-label yang ada."""
    slots = get_sales_slots_for_date(sales_email, day)
    # ambil hanya free
    free = [s for s in slots if s["status"] == "free"]
    free.sort(key=lambda s: s["start"])
    # cari chain yang kontinu
    cur = start_wib
    chosen = []
    for s in free:
        if s["start"] == cur and s["end"] <= end_wib:
            chosen.append(s["label"])
            cur = s["end"]
            if cur == end_wib:
                return chosen
    return []

def book_labels_atomically(sales_email: str, day: date, labels: list[str], session_id: str) -> bool:
    """Flip banyak label sekaligus → booked=true, available=false. Gagal total kalau salah satu tidak lagi free."""
    if not labels:
        return False
    cli = _cli()
    if not cli:
        return False
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_SLOTS_COLL", "sales_slots2")]
        start_utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        end_utc   = start_utc + timedelta(days=1)

        # Build query: semua label harus available True & booked False
        q = {
            "salesEmail": sales_email,
            "date": {"$gte": start_utc, "$lt": end_utc},
        }
        for lab in labels:
            q[f"slots.{lab}.available"] = True
            q[f"slots.{lab}.booked"] = False

        # Build update: set semua label jadi booked
        set_fields = {}
        now = datetime.now(timezone.utc)
        for lab in labels:
            set_fields[f"slots.{lab}.available"] = False
            set_fields[f"slots.{lab}.booked"] = True
            set_fields[f"slots.{lab}.bookedBy"] = session_id
            set_fields[f"slots.{lab}.bookedAt"] = now

        res = col.find_one_and_update(q, {"$set": set_fields}, return_document=ReturnDocument.AFTER)
        return bool(res)
    finally:
        try: cli.close()
        except: pass

def read_crisp_user(session_id: str) -> Optional[dict]:
    cli = _cli()
    if not cli: return None
    try:
        col = cli[cfg.MONGO_DB][os.getenv("CRISP_SESSIONS_COLL", "crisp_sessions")]
        doc = col.find_one({"sessionId": session_id}, {"_id":0, "user":1})
        return (doc or {}).get("user")
    finally:
        try: cli.close()
        except: pass

def read_chat_history_doc(session_id: str) -> Optional[dict]:
    cli = _cli()
    if not cli: return None
    try:
        col = cli[cfg.MONGO_DB][os.getenv("CHAT_HISTORY_COLL", "chat_history")]
        return col.find_one({"sessionId": session_id}, {"_id":0, "chat_history":1, "tokenId":1, "created_at":1, "updated_at":1})
    finally:
        try: cli.close()
        except: pass

# Gaining user profile
def get_user_profile(session_id: str) -> dict:
    """
    Ambil user.nickname, email, phone, country, region, city dari crisp_sessions.
    """
    cli = _cli()
    if not cli or not session_id: return {}
    try:
        col = cli[cfg.MONGO_DB][getattr(cfg, "MONGO_SESSION", "crisp_sessions")]
        doc = col.find_one(
            {"sessionId": session_id},
            {"_id":0, "user.nickname":1, "user.email":1, "user.phone":1,
             "user.country":1, "user.region":1, "user.city":1}
        ) or {}
        u = doc.get("user") or {}
        return {
            "nickname": (u.get("nickname") or "").strip(),
            "email": (u.get("email") or "").strip(),
            "phone": (u.get("phone") or "").strip(),
            "country": (u.get("country") or "").strip().upper(),
            "region": (u.get("region") or "").strip(),
            "city": (u.get("city") or "").strip(),
        }
    finally:
        try: cli.close()
        except: pass

def load_chat_history_for_summary(session_id: str, token_id: str | None = None, limit: int = 12) -> list[dict]:
    """
    Tarik N terakhir dari chat_history (koleksi yang sama dipakai logging).
    Format keluaran: [{"q": "...", "a": "...", "services": [...]}, ...]
    """
    cli = _cli()
    if not cli or not session_id: return []
    try:
        col = cli[cfg.MONGO_DB][cfg.CHAT_HISTORY_COLL]
        key = {"sessionId": session_id}
        if token_id:
            key["tokenId"] = token_id
        doc = col.find_one(key, {"chat_history": {"$slice": -abs(limit)}}) or {}
        out = []
        for r in (doc.get("chat_history") or []):
            out.append({
                "q": r.get("question") or "",
                "a": r.get("message") or "",
                "services": r.get("related_services") or []
            })
        return out
    finally:
        try: cli.close()
        except: pass

def log_meeting_debug(session_id: str, token_id: str | None, stage: str, payload: dict):
    """
    Simpan jejak pengambilan keputusan meeting.
    stage: e.g. 'parse', 'business_check', 'selection', 'alternatives', 'final'
    """
    cli = _cli()
    if not cli: 
        return
    try:
        col = cli[cfg.MONGO_DB].get_collection(getattr(cfg, "MEETING_DEBUG_COLL", "meeting_arrangement_logs"))
        doc = {
            "sessionId": session_id,
            "tokenId": token_id,
            "stage": stage,
            "payload": payload,
            "ts": datetime.now(timezone.utc),
        }
        col.insert_one(doc)
    finally:
        try: cli.close()
        except: pass

_DASHES = {"–": "-", "—": "-", "−": "-"}

def _norm_label(lab: str) -> str:
    # Normalize "HH:MM - HH:MM" strictly
    s = (lab or "").strip()
    # unify dashes
    for k,v in _DASHES.items():
        s = s.replace(k, v)
    # collapse spaces around hyphen
    s = s.replace(" - ", " - ")
    # zero-pad hours/minutes if needed
    try:
        L, R = [p.strip() for p in s.split("-")]
        h1,m1 = [int(x) for x in L.split(":")]
        h2,m2 = [int(x) for x in R.split(":")]
        s = f"{h1:02d}:{m1:02d} - {h2:02d}:{m2:02d}"
    except Exception:
        pass
    return s

# soft cache (TTL) to avoid rate limit
_SUMMARY_CACHE = {"at": 0.0, "headers": [], "matrix": {}}

def _read_sales_slots2_summary():
    ttl = cfg.INDV_SHEET_TTL_SEC  # detik
    now = time.time()
    if now - _SUMMARY_CACHE["at"] < ttl and _SUMMARY_CACHE["matrix"]:
        return _SUMMARY_CACHE["headers"], _SUMMARY_CACHE["matrix"]

    sh = _gc_readonly().open_by_key(cfg.SALES_SHEET_ID)
    ws = sh.worksheet(cfg.SALES_SHEET_NAME)
    values = ws.get_all_values()  # row0: ["Slot", YYYY-MM-DD, YYYY-MM-DD, ...]
    if not values or len(values) < 2:
        _SUMMARY_CACHE.update({"at": now, "headers": [], "matrix": {}})
        return [], {}

    headers = [h.strip() for h in values[0][1:]]  # date columns
    matrix = {}
    for row in values[1:]:
        lab = _norm_label(row[0])
        counts = {}
        for i, col in enumerate(headers):
            try:
                counts[col] = int((row[i+1] or "0").strip() or 0)
            except Exception:
                counts[col] = 0
        matrix[lab] = counts

    _SUMMARY_CACHE.update({"at": now, "headers": headers, "matrix": matrix})
    return headers, matrix

def get_count_from_summary(day_iso: str, label: str) -> int:
    # day_iso "YYYY-MM-DD" harus match header kolom
    label = _norm_label(label)
    headers, matrix = _read_sales_slots2_summary()
    if not headers or not matrix:
        return 0
    # kalau tanggal belum ada di header, langsung 0
    if day_iso not in headers:
        return 0
    row = matrix.get(label)
    if not row:
        return 0
    return int(row.get(day_iso, 0) or 0)

# Helper Weekley
def summarize_weekly_availability(
    emails: list[str],
    start_day: date,
    duration_min: int,
    days_ahead: int = 7,
    step_min: int = 30,
) -> dict[date, list[dict]]:
    """
    Kembalikan ringkasan availability selama N hari ke depan (mulai BESOK):
    { date: [ { "start": dt_wib, "end": dt_wib, "count_sales": int }, ... ] }
    - Windows digabung lintas sales; count_sales = banyaknya sales yg bisa cover window tsb.
    - Window granular dihasilkan dari gabungan interval FREE tiap sales (windows_from_intervals).
    """
    out: dict[date, list[dict]] = {}
    day0 = start_day + timedelta(days=1)  # mulai besok

    for i in range(days_ahead):
        day_i = day0 + timedelta(days=i)
        # kumpulkan semua kandidat window per-sales lalu hitung berapa sales yg bisa
        window_key_to_count: dict[tuple[str, str], int] = defaultdict(int)

        for em in emails:
            slots = get_sales_slots_for_date(em, day_i)  # WIB, sudah ada di repo (status=free/busy/booked) :contentReference[oaicite:1]{index=1}
            # ambil free intervals panjang
            free_intervals = []
            for s in slots:
                if s.get("status") == "free":
                    free_intervals.append((s["start"], s["end"]))
            if not free_intervals:
                continue

            # windows granular dengan durasi yang sama (step 30m default)
            wins = windows_from_intervals(free_intervals, duration_min=duration_min, step_min=step_min)  # :contentReference[oaicite:2]{index=2}
            for ws, we in wins:
                k = (ws.isoformat(), we.isoformat())
                window_key_to_count[k] += 1

        # susun list dan urutkan kronologis
        items = []
        for (s_iso, e_iso), cnt in window_key_to_count.items():
            s = datetime.fromisoformat(s_iso).astimezone(WIB)
            e = datetime.fromisoformat(e_iso).astimezone(WIB)
            items.append({"start": s, "end": e, "count_sales": int(cnt)})
        items.sort(key=lambda x: x["start"])
        out[day_i] = items
    return out

# util buat key label dari jam WIB (asumsi slot 60 menit) ---
def _label_key_from_range(start_wib: datetime, end_wib: datetime) -> str:
    # contoh: "10:00 - 11:00"
    return f"{start_wib:%H:%M} - {end_wib:%H:%M}"

# cari siapa saja yang AVAILABLE pada window persis itu (tanpa menyebut siapa di layer balasan) ---
def available_sales_on(emails: list[str], d: date, start_wib: datetime, end_wib: datetime) -> list[str]:
    """
    Kembalikan list email sales yang available penuh pada 1 label window (mis. 10:00-11:00).
    Catatan: dokumen slot disimpan per-hari, field 'slots.<label>.available' & 'slots.<label>.booked'.
    """
    cli = _cli() 
    if not cli:
        return []
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_SLOTS_COLL", "sales_slots2")]
        # NORMALISASI tanggal ke UTC-midnight sesuai penyimpanan dokumen
        start_utc = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        end_utc   = start_utc + timedelta(days=1)
        label = _label_key_from_range(start_wib, end_wib)
        q = {
            "date": {"$gte": start_utc, "$lt": end_utc},
            "salesEmail": {"$in": emails},
            f"slots.{label}.available": True,
            f"slots.{label}.booked": False
        }
        cur = col.find(q, {"salesEmail": 1})
        return sorted({doc["salesEmail"] for doc in cur})
    finally:
        try:
            cli.close()
        except:
            pass

def available_sales_on_exact(emails: list[str], d, start_wib, end_wib):
    """
    Hard-gate persis 1 tanggal (equality pada field `date`) dan 1 label.
    Mengembalikan (ok_emails, matched_count, debug_query_dict).
    """
    cli = _cli()
    if not cli:
        return [], 0, {}
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_SLOTS_COLL", "sales_slots2")]

        # EXACT equality ke midnight UTC hari tsb (ISODate("YYYY-MM-DDT00:00:00Z"))
        date_eq_utc = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

        label = f"{start_wib:%H:%M} - {end_wib:%H:%M}"  # pastikan format identik dengan dokumen
        q = {
            "date": date_eq_utc,                      # <— EQUALITY (BUKAN range)
            "salesEmail": {"$in": emails} if emails else {"$exists": True},
            f"slots.{label}.available": True,
            f"slots.{label}.booked": False,
        }

        cur = col.find(q, {"salesEmail": 1})
        ok = sorted({doc["salesEmail"] for doc in cur})
        cnt = col.count_documents(q)

        return ok, int(cnt), {"collection": col.name, "q": {
            "date": date_eq_utc.isoformat(),         # untuk logging yang mudah dibaca
            "salesEmail_in": emails,
            "label": label,
            "cond_available": True,
            "cond_booked": False
        }}
    finally:
        try:
            cli.close()
        except:
            pass

def fetch_sales_pic_by_service(service_label: str) -> dict:
    service_label = (service_label or "").strip()
    if not service_label:
        return {}

    base = (cfg.MEETING_API_BASE_URL or cfg.SALES_EMAIL_API_BASE_URL or "").strip()
    path = (cfg.SALES_COVERAGE_PATH or "").strip()
    token = (cfg.MEETING_API_BEARER_TOKEN or cfg.SALES_EMAIL_API_BEARER_TOKEN or "").strip()
    timeout = int(getattr(cfg, "SALES_EMAIL_API_TIMEOUT_SECS", 10) or 10)

    if not base or not path or not token:
        return {}

    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"service": service_label}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        if resp.status_code != 200:
            return {"raw": {"status": resp.status_code, "text": resp.text[:500]}}
        data = resp.json() if resp.text else {}
    except Exception as e:
        return {"raw": {"error": str(e)}}

    email = (data.get("email") or "").strip()
    name  = (data.get("name") or "").strip()
    if not email and not name:
        return {"raw": data}

    return {"sales_email": email, "sales_name": name, "raw": data}

def fetch_user_profile(session_id: str, website_id: str) -> dict:
    """
    POST {MEETING_API_BASE_URL}/{MEETING_USER_PATH}
    Return dict user: {timezone, nickname, email, phone, locale, ...}
    """
    base = (cfg.MEETING_API_BASE_URL or cfg.SALES_EMAIL_API_BASE_URL or "").strip()
    token = (cfg.MEETING_API_BEARER_TOKEN or cfg.SALES_EMAIL_API_BEARER_TOKEN or "").strip()
    path = (cfg.MEETING_USER_PATH or "chat/user").strip()
    timeout = int(getattr(cfg, "MEETING_API_TIMEOUT_SECS", 10) or 10)

    if not base or not token:
        return {}

    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = {"sessionId": session_id, "websiteId": website_id}

    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json() or {}
        return (data.get("user") or {}) if isinstance(data, dict) else {}
    except Exception:
        return {}
    
def fetch_sales_availability(first_date: str, second_date: str, email: str, timezone: str) -> dict:
    """
    POST {MEETING_API_BASE_URL}/{MEETING_AVAILABILITY_PATH}
    Return raw response: {salesEmail, timezone, available_slots:[...]}
    """
    base = (cfg.MEETING_API_BASE_URL or cfg.SALES_EMAIL_API_BASE_URL or "").strip()
    token = (cfg.MEETING_API_BEARER_TOKEN or cfg.SALES_EMAIL_API_BEARER_TOKEN or "").strip()
    path = (cfg.MEETING_AVAILABILITY_PATH or "sales/availability").strip()
    timeout = int(getattr(cfg, "MEETING_API_TIMEOUT_SECS", 10) or 10)

    if not base or not token:
        return {}

    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    body = {
        "first_date": first_date,
        "second_date": second_date,
        "email": email,
        "available": True,
        "booked": False,
        "timezone": timezone,
    }

    try:
        r = requests.post(url, json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json() or {}
    except Exception:
        return {}

def get_last_service_context_from_history(session_id: str, token_id: str | None, limit: int = 50) -> dict:
    """
    Scan chat_history (latest -> oldest) to find extra.service_label and extra.sales_email.
    Return: {"service_label": str, "sales_email": str, "sales_name": str}
    """
    try:
        doc = read_chat_history_doc(session_id=session_id, token_id=token_id)  # sudah ada di ma_repo kamu
    except Exception:
        doc = None

    if not doc:
        return {}

    history = doc.get("chat_history") or []
    for turn in reversed(history[-limit:]):
        extra = (turn.get("extra") or {})
        service_label = (extra.get("service_label") or "").strip()
        sales_email = (extra.get("sales_email") or "").strip()
        sales_name = (extra.get("sales_name") or "").strip()
        if service_label and sales_email:
            ctx = {
                "service_label": service_label,
                "sales_email": sales_email,
                "sales_name": sales_name,
            }
            if extra:
                ctx["extra"] = extra
            return ctx

    return {}

# akses sheet individual availability
def _gc_readonly():
    """Client gspread read-only menggunakan credential dari .env (JSON inline atau path)."""
    creds = cfg.build_google_credentials([
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ])
    return gspread.authorize(creds)

# (Jika ada varian _gc() untuk write, gunakan scope write)
def _gc():
    creds = cfg.build_google_credentials([
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    return gspread.authorize(creds)

def _read_individual_matrix_fresh():
    # PANGGIL API SEKALI (hati2 quota)
    global _last_sheet_call
    now = time.monotonic()
    wait = _SHEETS_MIN_INTERVAL - (now - _last_sheet_call)
    if wait > 0:
        time.sleep(wait)
    sh = _gc_readonly().open_by_key(cfg.SALES_SHEET_ID)
    ws = sh.worksheet(cfg.INDV_SALES_SHEET_NAME)  # atau nama sheet kamu
    data = ws.get_all_values()  # 1 request
    _last_sheet_call = time.monotonic()
    headers = data[0] if data else []
    matrix  = data[1:] if len(data) > 1 else []
    return headers, matrix

def read_individual_matrix_cached():
    with _cache_lock:
        now = time.monotonic()
        # gunakan cache jika masih valid
        if (now - _IDV_CACHE["ts"]) <= _INDV_TTL and _IDV_CACHE["headers"] is not None:
            return _IDV_CACHE["headers"], _IDV_CACHE["matrix"]
        try:
            headers, matrix = _read_individual_matrix_fresh()
            _IDV_CACHE.update({"ts": now, "headers": headers, "matrix": matrix})
        except Exception:
            # kalau gagal refresh (mis. 429), gunakan cache lama jika ada
            if _IDV_CACHE["headers"] is not None:
                return _IDV_CACHE["headers"], _IDV_CACHE["matrix"]
            raise  # tidak ada cache sama sekali → naikan error
        return headers, matrix

def build_availability_index():
    """
    Return dict: { (day_iso, slot_label): [emails...] }
    Dihitung dari cached INDV matrix agar zero-extra-API.
    """
    headers, matrix = read_individual_matrix_cached()
    # cari index kolom yang perlu: "date", "email", dan kolom slot (e.g. "09:00 - 10:00")
    def _col_idx(name):
        try:
            return headers.index(name)
        except ValueError:
            return -1

    date_idx  = _col_idx("date")
    email_idx = _col_idx("salesEmail")  # sesuaikan dengan header real
    # Simpan mapping label->idx
    slot_cols = {}
    for i, h in enumerate(headers):
        if " - " in h and ":" in h:  # deteksi label slot
            slot_cols[h.strip()] = i

    idx = {}
    for row in matrix:
        if date_idx < 0 or email_idx < 0:
            continue
        d_iso = (row[date_idx] or "").strip()
        email = (row[email_idx] or "").strip()
        if not d_iso or not email:
            continue
        for lab, ci in slot_cols.items():
            if ci < len(row):
                val = (row[ci] or "").strip().lower()
                # anggap "1" / "true" / "available" sebagai available
                if val in ("1", "true", "available", "yes", "y"):
                    idx.setdefault((d_iso, lab), []).append(email)
    return idx

def pick_least_available_weekly_from_sheet(base_date, ok_emails, days: int = 7) -> str | None:
    """Pilih sales dengan jumlah 1 paling sedikit di 7 hari kerja ke depan."""
    headers, matrix = read_individual_matrix_cached()
    d = base_date
    target_dates = []
    while len(target_dates) < days:
        if d.weekday() < 5:
            iso = d.strftime("%Y-%m-%d")
            if iso in headers:
                target_dates.append(iso)
        d += timedelta(days=1)

    score = {}
    for (label, col), val in matrix.items():
        if col in target_dates and val == 1:
            email = label.split(" — ")[0].strip()
            if email in ok_emails:
                score[email] = score.get(email, 0) + 1

    if not score:
        return None
    ranked = sorted(score.items(), key=lambda x: (x[1], x[0]))  # jumlah avail paling sedikit, lalu abjad
    return ranked[0][0]

#Penyimpanan database query tracking
def save_query_recording(
    *,
    session_id: str,
    token_id: str | None,
    route: str,
    stage: str,
    question: str | None = None,
    query_dict: dict | None = None,
    result_summary: dict | None = None,
    llm_prompt: str | None = None,
    llm_output: str | None = None,
    extras: dict | None = None,
):
    """[DEPRECATED] Thin shim — delegates to core.app_audit.record_llm_call.

    Preserves the legacy meeting-arrangement event shape by routing the
    `query`/`result`/`question` fields into `extras` and stamping
    `kind="meeting_event"`. New code should call `record_llm_call` or
    `audit_llm_call` directly.
    """
    from core.app_audit import record_llm_call

    merged_extras = dict(extras or {})
    if query_dict is not None:
        merged_extras["query"] = query_dict
    if result_summary is not None:
        merged_extras["result"] = result_summary
    if question is not None:
        merged_extras["question"] = question

    record_llm_call(
        route=route,
        stage=stage,
        session_id=session_id,
        token_id=token_id,
        prompt=llm_prompt,
        response=llm_output or "",
        model=None,                 # legacy callers don't supply model
        latency_ms=0,               # legacy callers don't time
        input_tokens=0,
        output_tokens=0,
        extras=merged_extras,
        kind="meeting_event",
    )

def available_sales_on_exact(emails: list[str], d, start_wib, end_wib):
    """
    Hard-gate persis 1 tanggal (equality pada field `date`) dan 1 label.
    Mengembalikan (ok_emails, matched_count, debug_query_dict).
    """
    cli = _cli()
    if not cli:
        return [], 0, {}
    try:
        col = cli[cfg.MONGO_DB][_coll("SALES_SLOTS_COLL", "sales_slots2")]

        # EXACT equality ke midnight UTC hari tsb (ISODate("YYYY-MM-DDT00:00:00Z"))
        date_eq_utc = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

        label = f"{start_wib:%H:%M} - {end_wib:%H:%M}"  # pastikan format identik dengan dokumen
        q = {
            "date": date_eq_utc,                      # <— EQUALITY (BUKAN range)
            "salesEmail": {"$in": emails} if emails else {"$exists": True},
            f"slots.{label}.available": True,
            f"slots.{label}.booked": False,
        }

        cur = col.find(q, {"salesEmail": 1})
        ok = sorted({doc["salesEmail"] for doc in cur})
        cnt = col.count_documents(q)

        return ok, int(cnt), {"collection": col.name, "q": {
            "date": date_eq_utc.isoformat(),         # untuk logging yang mudah dibaca
            "salesEmail_in": emails,
            "label": label,
            "cond_available": True,
            "cond_booked": False
        }}
    finally:
        try:
            cli.close()
        except:
            pass

# Meeting arrangement new version, googlesheet integration
def upsert_ma_confirmation(*,
    session_id: str,
    token_id: str | None,
    user_email: str | None,
    day: date,
    start_wib: datetime,
    end_wib: datetime,
    selected_sales_email: str | None,
    status: str
) -> bool:
    """
    Simpan ringkasan permintaan meeting:
    key = (sessionId, day, start, end) — agar idempotent.
    status: "available" | "booked" | "day_off"
    """
    cli = _cli()
    if not cli:
        return False
    try:
        col = cli[cfg.MONGO_DB][os.getenv("MA_CONFIRMATION_COLL","ma_confirmation")]
        key = {
            "sessionId": session_id,
            "date": day.isoformat(),
            "start": start_wib.isoformat(),
            "end": end_wib.isoformat(),
        }
        doc = {
            **key,
            "tokenId": token_id,
            "user_email": (user_email or ""),
            "selected_sales_email": (selected_sales_email or None),
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        col.update_one(key, {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        return True
    except Exception:
        return False
    finally:
        try: cli.close()
        except: pass

def save_calendar_payload(session_id: str,
                          token_id: str | None,
                          payload: dict,
                          status: str = "draft",
                          sales_accumulation: dict | None = None):
    """
    Simpan payload kalender ke koleksi PAYLOAD_CALENDER_COL (default: 'calendar_payload').
    Format payload mengikuti:
    {
        "calendarId": str,
        "summary": str,
        "description": str,
        "start": "...+07:00",
        "end":   "...+07:00",
        "timeZone": "Asia/Jakarta",
        "attendees": [ {"email": ...}, ... ]
    }
    """
    cli = _cli()
    if not cli:
        return False

    try:
        col_name = os.getenv("PAYLOAD_CALENDAR_COL", "calendar_payload")
        col = cli[cfg.MONGO_DB][col_name]

        doc = {
            "sessionId": session_id,
            "tokenId": token_id,
            "status": status,  # e.g. 'draft' | 'posted' | 'failed'
            "payload": payload,
            "sales_accumulation": sales_accumulation or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # kalau sudah ada payload yang sama (same session, start, end), replace
        key = {
            "sessionId": session_id,
            "tokenId": token_id,
            "payload.start": payload.get("start"),
            "payload.end": payload.get("end"),
        }

        col.update_one(key, {"$set": doc}, upsert=True)
        return True

    except Exception as e:
        print(f"[save_calendar_payload] ERROR: {e}")
        return False

    finally:
        try:
            cli.close()
        except:
            pass

_STD_LABELS = [
    "09:00 - 10:00","10:00 - 11:00","11:00 - 12:00","12:00 - 13:00",
    "13:00 - 14:00","14:00 - 15:00","15:00 - 16:00","16:00 - 17:00"
]

def _working_days_list_inclusive(start_date: date, n_days: int = 7) -> list[date]:
    out, cur = [], start_date
    while len(out) < n_days:
        if cur.weekday() < 5:  # Mon..Fri
            out.append(cur)
        cur += timedelta(days=1)
    return out

def accumulate_weekly_availability_from_sheet(start_date: date,
                                              candidate_emails: list[str],
                                              labels: list[str] | None = None,
                                              n_workdays: int = 7) -> dict[str, int]:
    """
    Hitung total ketersediaan per sales di tab ringkasan (Sales_Slots2_IDV) untuk
    7 hari kerja mulai start_date. Satu slot '1' dihitung 1 poin.
    """
    labels = labels or _STD_LABELS
    acc = {em: 0 for em in candidate_emails}
    for d in _working_days_list_inclusive(start_date, n_workdays):
        day_iso = d.strftime("%Y-%m-%d")
        for lab in labels:
            try:
                ok = get_sales_available_from_sheet(day_iso, lab) or []
            except Exception:
                ok = []
            if not ok:
                continue
            s_ok = set(ok)
            for em in candidate_emails:
                if em in s_ok:
                    acc[em] += 1
    return acc

def pick_most_available_weekly_from_sheet(target_date: date, ok_emails: list[str], n_workdays: int = 7):
    """
    Pilih sales dengan jumlah available terbanyak selama n_workdays hari kerja dari target_date.
    Jika sama → pilih berdasar abjad.
    """
    if not ok_emails:
        return None, {}

    # hitung akumulasi (1 = available, 0 = booked)
    acc = get_weekly_availability_counts(target_date, ok_emails, days=n_workdays)
    if not acc:
        return None, {}

    # urutkan dari paling banyak → paling sedikit, lalu abjad
    ranked = sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))
    selected = ranked[0][0]
    return selected, acc

_DASH_SPLIT = re.compile(r"\s+[–—-]\s+")  # en dash, em dash, hyphen
_SLOT_NORM  = re.compile(r"\s*-\s*")

def _normalize_slot(label: str) -> str:
    """
    Samakan jadi 'HH:MM - HH:MM' (pakai spasi di kiri-kanan '-').
    Terima variasi '09:00-10:00', '09:00 – 10:00', dst.
    """
    s = (label or "").strip()
    s = s.replace("–", "-").replace("—", "-")
    s = _SLOT_NORM.sub(" - ", s)  # pastikan ada spasi kiri-kanan
    # pad kiri/kanan agar tepat 5 char (HH:MM)
    try:
        a, b = [t.strip() for t in s.split("-")]
        if len(a) == 4: a = "0" + a
        if len(b) == 4: b = "0" + b
        return f"{a} - {b}"
    except Exception:
        return s

@lru_cache(maxsize=1)
def _load_indv_index_cached():
    """
    Baca tab Sales_Slots2_IDV dari spreadsheet SALES_SHEET_ID
    untuk membangun index (day_iso, slot) -> [email...]
    """
    sheet_id = cfg.SALES_SHEET_ID  # ✅ pakai SALES_SHEET_ID, bukan SHEET_ID
    tab_name = cfg.INDV_SALES_SHEET_NAME or "Sales_Slots2_IDV"

    rows = get_sheet_values(sheet_id, tab_name) or []
    if not rows:
        print(f"[IDV] gagal baca {tab_name} dari spreadsheet {sheet_id}")
        return {}

    header = rows[0]
    date_cols = {j: h for j, h in enumerate(header) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(h).strip())}
    idx = {}

    for row in rows[1:]:
        if not row or not row[0]:
            continue
        label = str(row[0]).strip()
        m = re.match(r"^([^—]+)—\s*(\d{2}:\d{2}\s*-\s*\d{2}:\d{2})", label)
        if not m:
            continue
        email = m.group(1).strip().replace(" ", "")
        slot  = re.sub(r"\s*-\s*", " - ", m.group(2).strip())
        for j, d_iso in date_cols.items():
            if j < len(row) and str(row[j]).strip() == "1":
                key = (d_iso, slot)
                idx.setdefault(key, set()).add(email)

    return {k: sorted(v) for k, v in idx.items()}

def get_sales_available_from_sheet(day_iso: str, slot_label: str) -> list[str]:
    """Ambil daftar e-mail yang available untuk (tanggal, slot) dari index IDV."""
    idx = _load_indv_index_cached()
    slot = _normalize_slot(slot_label)
    ems = idx.get((day_iso, slot), []) or []
    return sorted(ems)

def get_weekly_availability_counts(start_date: date,
                                   emails: list[str],
                                   days: int = 7) -> dict[str, int]:
    """
    Jumlahkan availability (=1) per sales untuk N hari kerja (Mon–Fri),
    dimulai dari start_date (inklusif), mengacu ke tab IDV.
    """
    idx = _load_indv_index_cached()
    if not idx:
        return {e: 0 for e in emails}

    # daftar tanggal kerja
    cur = start_date
    date_list: list[str] = []
    while len(date_list) < days:
        if cur.weekday() < 5:
            date_list.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    # semua slot yang diketahui di index
    all_slots = sorted({k[1] for k in idx.keys()})

    counts = {e: 0 for e in emails}
    for d_iso in date_list:
        for slot in all_slots:
            ems = set(idx.get((d_iso, slot), []) or [])
            if not ems:
                continue
            for e in emails:
                if e in ems:            # ← penting: hanya tambah jika e memang available
                    counts[e] += 1
    return counts
