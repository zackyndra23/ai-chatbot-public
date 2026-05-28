from __future__ import annotations
import os
import gspread
from google.oauth2.service_account import Credentials
import json
from pathlib import Path
from core.app_config import Config, PROJECT_ROOT

cfg = Config()

# Scope minimal utk Sheets read/write
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_ws_cache = None  # cache worksheet biar nggak open berkali-kali

class SheetNotConfigured(Exception):
    pass

def get_sheet_client(readonly: bool = True):
    scopes = ([
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ] if readonly else [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    creds = cfg.build_google_credentials(scopes)
    return gspread.authorize(creds)

def _resolve_sa_path(raw: str | None) -> str | None:
    """
    Terima raw path (bisa relatif). Kembalikan absolute path pertama yang ada.
    Urutan kandidat:
      1) Jika absolute -> pakai langsung
      2) <PROJECT_ROOT>/<raw>
      3) <cwd>/<raw>
      4) <PROJECT_ROOT>/secrets/sa.json (fallback terakhir)
    """
    candidates = []
    if raw:
        p = Path(raw)
        if p.is_absolute():
            candidates.append(p)
        else:
            candidates.append((Path(PROJECT_ROOT) / raw).resolve())
            candidates.append((Path.cwd() / raw).resolve())
    candidates.append((Path(PROJECT_ROOT) / "secrets" / "sa.json").resolve())
    for c in candidates:
        if c.exists():
            return str(c)
    return None

def _build_credentials():
    raw = (cfg.CREDS_PATH or "").strip()
    if not raw:
        raise SheetNotConfigured("GOOGLE_SERVICE_ACCOUNT empty")
    # Mode JSON inline
    if raw.lstrip().startswith("{"):
        try:
            info = json.loads(raw)
        except Exception as e:
            raise SheetNotConfigured(f"Invalid GOOGLE_SERVICE_ACCOUNT JSON: {e}")
        return Credentials.from_service_account_info(info, scopes=_SCOPES)
    # Mode path file
    cred_path = _resolve_sa_path(raw)
    if not cred_path:
        raise SheetNotConfigured(
            f"GOOGLE_SERVICE_ACCOUNT not found. Tried raw={raw!r} "
            f"(PROJECT_ROOT={PROJECT_ROOT})"
        )
    return Credentials.from_service_account_file(cred_path, scopes=_SCOPES)

def get_worksheet():
    global _ws_cache
    # if _ws_cache is not None:
    #     return _ws_cache

    # ENTING: reset cache biar selalu pakai env terbaru
    _ws_cache = None

    cfg = Config()

    sheet_id = (cfg.GOOGLE_CHAT_SHEET_ID or "").strip()
    sheet_tab = (cfg.GOOGLE_CHAT_SHEET_TAB or "").strip()

    if not sheet_id:
        raise SheetNotConfigured("GOOGLE_CHAT_SHEET_ID empty")

    creds = _build_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(sheet_tab)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=sheet_tab, rows=1000, cols=20)

    _ws_cache = ws
    # print(f"[GSH] target sheet_id={sheet_id} tab={sheet_tab}")
    return ws

def get_ws_by_id_tab(sheet_id: str, tab_name: str):
    """
    Ambil worksheet secara generik berdasarkan sheet_id dan tab_name.
    Tidak pakai cache chat history, jadi aman untuk modul lain.
    """
    if not sheet_id:
        raise SheetNotConfigured("sheet_id is empty")
    creds = _build_credentials()
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        raise SheetNotConfigured(f"Worksheet {tab_name!r} not found in sheet {sheet_id}")
    return ws