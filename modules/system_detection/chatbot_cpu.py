from flask import Flask
from .sd_controller import sd_bp
# from modules.service_agent.sa_controller import sa_bp
from .sd_vector_repo_cpu import bootstrap_vectorstore
from core.app_config import Config
from modules.sales_slots_update import ssu_bp, register_ssu_scheduler

# from core.gpu_config import log_gpu_status
try:
    from core.gpu_config import log_gpu_status
except Exception:
    log_gpu_status = None

from core.app_logging import get_logger

cfg = Config()
_VECTORSTORE_READY = False

def _ensure_vectorstore():
    global _VECTORSTORE_READY
    if not _VECTORSTORE_READY:
        bootstrap_vectorstore()
        _VECTORSTORE_READY = True

def create_app():
    app = Flask(__name__)
    if cfg.TRUSTED_HOSTS is not None:
        app.config["TRUSTED_HOSTS"] = list(cfg.TRUSTED_HOSTS)
    app.config["JSON_AS_ASCII"] = False

    # # log GPU status once at startup
    # try:
    #     logger = get_logger()
    #     log_gpu_status(logger)
    # except Exception:
    #     print("[gpu] ", log_gpu_status(None), flush=True)

    # log GPU status once at startup (never fail startup)
    try:
        logger = get_logger()
        logger.info(
            {
                "event": "trusted_hosts_config",
                "trusted_hosts": app.config.get("TRUSTED_HOSTS"),
            }
        )
        if log_gpu_status:
            log_gpu_status(logger)
        else:
            logger.info({"event": "gpu_status", "device": "cpu", "cuda_available": False, "gpu_name": None})
    except Exception:
        # absolutely never crash only because GPU check/log failed
        print("[gpu] status check skipped (cpu mode)", flush=True)

    _ensure_vectorstore()
    app.register_blueprint(sd_bp)
    # app.register_blueprint(sa_bp)
    # Register SSU blueprint (manual trigger endpoint) & start its scheduler
    app.register_blueprint(ssu_bp)
    register_ssu_scheduler(app)
    return app

# 👇 add this so Gunicorn can import `app`
app = create_app()

if __name__ == "__main__":
    port = cfg.PORT_CHATBOT
    app.run(host="0.0.0.0", port=port)
