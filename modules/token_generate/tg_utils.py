from __future__ import annotations

import os, re
from datetime import datetime, timezone
from typing import Optional

import pytz  # type: ignore

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None
    
def getenv_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


def getenv_int(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def get_tz() -> object:
    tz_name = getenv_str("TIMEZONE", "Asia/Jakarta")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)  # type: ignore
        except Exception:
            return ZoneInfo("UTC")  # type: ignore
    # fallback for environments without zoneinfo
    try:
        import pytz  # type: ignore
        return pytz.timezone(tz_name)
    except Exception:
        return timezone.utc


def now_local() -> datetime:
    tz = get_tz()
    try:
        return datetime.now(tz)  # type: ignore[arg-type]
    except Exception:
        # pytz fallback
        import pytz  # type: ignore
        return pytz.utc.localize(datetime.utcnow()).astimezone(get_tz())  # type: ignore


def iso_local(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = now_local()
    # ISO 8601 with offset, e.g., 2025-09-10T12:34:56+07:00
    return dt.isoformat()

def slugify_name(name: str, fallback: str = "user") -> str:
    s = (name or "").strip()
    s = re.sub(r"\s+", "_", s)               # spasi -> underscore
    s = re.sub(r"[^A-Za-z0-9_-]", "", s)     # buang karakter asing
    if not s:
        s = fallback
    return s[:40]  # batasi agar userId tidak kepanjangan