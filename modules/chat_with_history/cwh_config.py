import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ".env"

load_dotenv(dotenv_path=ENV_FILE, override=True)

@dataclass
class Config:
    UTILIZER_STATUS: str = os.getenv("UTILIZER_STATUS", "local").strip().lower()
    UTILIZER_STATUS: str = os.getenv("UTILIZER_STATUS", "local").strip().lower()
    CHAT_HISTORY_SCHEMA: str = os.getenv("CHAT_HISTORY_SCHEMA", "allsum").strip().lower()
    HISTORY_SUMMARY_MAX_CHARS: int = int(os.getenv("HISTORY_SUMMARY_MAX_CHARS", "500"))
    INPUT_MAX_PROMPT: int = int(os.getenv("INPUT_MAX_PROMPT", os.getenv("PROMPT_MAX_CHARS", "4500")))