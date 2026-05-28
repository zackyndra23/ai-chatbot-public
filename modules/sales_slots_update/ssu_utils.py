"""
ssu_utils.py — Utility functions for Sales Slots Update.

Provides:
    - Timezone helpers (WIB timezone conversion).
    - Environment variable parsing and normalization.
    - Safe feature toggling via env_bool().
    - Parsing helpers for HH:MM formatted strings.
    - Aggregation of all environment configs required by this module.

All time operations are localized to Asia/Jakarta (WIB).
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo
import gspread
from core.app_config import Config
cfg = Config()

WIB = ZoneInfo("Asia/Jakarta")

def now_wib() -> datetime:
    return datetime.now(tz=WIB)

def env_bool(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None: return default
    return v.strip().lower() in ("1", "true", "yes", "on")

def load_gs_client(readonly: bool = False):
    scopes = ([
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ] if not readonly else [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ])
    creds = cfg.build_google_credentials(scopes)
    return gspread.authorize(creds)

def read_env_config():
    """
    Kumpulkan ENV khusus modul ini. Semuanya optional dengan default aman.
    """
    return {
        "MONGO_URI": os.getenv("MONGO_URI"),
        "MONGO_DB": os.getenv("MONGO_DB"),
        "SALES_SLOTS_COLL": os.getenv("SALES_SLOTS_COLL", "sales_slots2"),
        "INDV_SALES_SHEET_NAME": os.getenv("INDV_SALES_SHEET_NAME", "Sales_Slots2_IDV"),
        "SSU_LOG_COLL": os.getenv("SSU_LOG_COLL", "sales_slots2_update"),
        "SSU_LOG_MODE": os.getenv("SSU_LOG_MODE", "upsert"),
        "SALES_SHEET_ID": os.getenv("SALES_SHEET_ID"),
        "SALES_SHEET_NAME": os.getenv("SALES_SHEET_NAME", "SALES_AVAIL_MATRIX"),
        "WORK_START": os.getenv("WORK_START", "09:00"),
        "WORK_END": os.getenv("WORK_END", "17:00"),
        "SLOTS_UPDATE_DURATION": int(os.getenv("SLOTS_UPDATE_DURATION", "30")),
        "SSU_DAYS_AHEAD": int(os.getenv("SSU_DAYS_AHEAD", "30")),  # opsional
        "SSU_FEATURE_ON": env_bool("SSU_FEATURE_ON", True),
        "GOOGLE_SERVICE_ACCOUNT": os.getenv("GOOGLE_SERVICE_ACCOUNT", "secrets/sa.json"),
    }

def parse_hhmm(s: str):
    hh, mm = s.split(":")
    from datetime import time
    return time(hour=int(hh), minute=int(mm))
