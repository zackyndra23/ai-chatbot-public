from __future__ import annotations
import os, sys, logging
from pathlib import Path
from flask import Flask
from dotenv import load_dotenv, dotenv_values
import logging

# 1) Muat .env dari ROOT repo (dan opsional secrets/.env) SEBELUM bikin Config
ROOT = Path(__file__).resolve().parents[2]   # .../rag_conflict_fixed
ENV_CHAIN = [ROOT / ".env", ROOT / "secrets" / ".env"]

for env_path in ENV_CHAIN:
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)

# 2) Baru import/buat Config (agar baca ENV yang barusan dimuat)
from core.app_config import Config
cfg = Config()

# 1) Bersihkan key yang kritikal agar tidak “menang” dari OS env lama
for k in ["MONGO_URI","MONGO_DB","MONGO_SESSION","API_KEYS_COLLECTION",
          "TESTING_BACKEND_ORIGIN","TESTING_BASE_PATH",
          "TOKEN_SVC_ORIGIN","TOKEN_GENERATE_PATH","API_HEADER_NAME"]:
    os.environ.pop(k, None)

try:
    from .ctu_controller import bp as chat_testing_ui_bp
except Exception:
    from ctu_controller import bp as chat_testing_ui_bp

app = Flask(__name__)
app.register_blueprint(chat_testing_ui_bp)

# Optional: nicer DX
app.config["TEMPLATES_AUTO_RELOAD"] = True
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")

if __name__ == "__main__":
    port = cfg.PORT_UI_TEST
    # Log konfigurasi Mongo efektif (tanpa membocorkan password)
    def _mask_uri(uri: str) -> str:
        if not uri: return "(empty)"
        try:
            # sembunyikan credential
            if "@" in uri and "://" in uri:
                scheme, rest = uri.split("://", 1)
                if "@" in rest:
                    creds, host = rest.split("@", 1)
                    return f"{scheme}://***:***@{host}"
        except Exception:
            pass
        return uri
    app.logger.info(
        "Mongo cfg → uri=%s db=%s coll=%s",
        _mask_uri(os.getenv("MONGO_URI","")), os.getenv("MONGO_DB",""), os.getenv("MONGO_SESSION","")
    )
    app.logger.info("Chat Testing UI running on http://0.0.0.0:%s", port)
    app.run(host="0.0.0.0", port=port, debug=False)