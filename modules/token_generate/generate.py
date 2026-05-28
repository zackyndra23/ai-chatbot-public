from __future__ import annotations

import os
import logging
from flask import Flask
from dotenv import load_dotenv
from core.app_config import Config  # memicu load_dotenv dari app_config
cfg = Config()

# Load secrets/.env (selaras dengan app_config)
load_dotenv(dotenv_path=os.path.join(os.getcwd(), "secrets", ".env"))

from .tg_controller import bp as tg_bp  # noqa: E402
from .tg_pipelines import AutoDeactivatePipeline  # noqa: E402
from .tg_repo import TokenRepo  # noqa: E402

def create_app() -> Flask:
    app = Flask(__name__)
    # logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s :: %(message)s")

    # register blueprint
    app.register_blueprint(tg_bp)

    # start background pipeline
    repo = TokenRepo()
    auto = AutoDeactivatePipeline(repo)
    auto.start()

    # keep reference (useful for graceful shutdown in some servers)
    app.auto_pipeline = auto  # type: ignore[attr-defined]
    
    return app


if __name__ == "__main__":
    app = create_app()
    host = "0.0.0.0"
    port = cfg.PORT_TG
    app.logger.info("Starting token_generate service on %s:%s", host, port)
    app.run(host=host, port=port)