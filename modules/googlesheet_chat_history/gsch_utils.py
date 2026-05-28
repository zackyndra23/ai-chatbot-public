from __future__ import annotations
from core.app_config import Config

def flag_enabled() -> bool:
    cfg = Config()  # <-- bikin fresh setiap call
    return str(getattr(cfg, "GOOGLE_CHAT_HISTORY", "off")).strip().lower() in ("1", "true", "on", "yes")
