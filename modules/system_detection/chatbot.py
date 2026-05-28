from flask import Flask
from .sd_controller import sd_bp
# from modules.service_agent.sa_controller import sa_bp
from .sd_vector_repo import bootstrap_vectorstore
from core.app_config import Config
from modules.sales_slots_update import ssu_bp, register_ssu_scheduler

from core.gpu_config import log_gpu_status
from core.app_logging import get_logger

cfg = Config()
_VECTORSTORE_READY = False

def _effective_trusted_hosts() -> list[str] | None:
    if cfg.TRUSTED_HOSTS is None:
        return None
    hosts: list[str] = []
    for item in cfg.TRUSTED_HOSTS:
        if item not in hosts:
            hosts.append(item)
        if ":" not in item:
            with_port = f"{item}:{cfg.PORT_CHATBOT}"
            if with_port not in hosts:
                hosts.append(with_port)
    return hosts

def _ensure_vectorstore():
    """Bootstrap Chroma vector store; auto-rebuild from Mongo if empty.

    Boot scenarios this handles:
    - Fresh container, empty volume → Chroma init creates empty DB → auto-rebuild
    - Restart with healthy volume → Chroma loads existing → skip rebuild (fast)
    - Volume corrupt / wrong embedding model → empty count → auto-rebuild
    - Mongo unreachable at startup → log warning, continue with empty KB
      (operator can retry via POST /aitegrity-core/knowledgebase-rebuild)

    The auto-rebuild on first start replaces the previous "deployer must
    manually trigger /knowledgebase-rebuild" workflow. See
    docs/ops/deployment.md for full behavior matrix.
    """
    global _VECTORSTORE_READY
    if _VECTORSTORE_READY:
        return

    bootstrap_vectorstore()

    # Self-heal: if Chroma is empty (count==0), the vectorstore was just
    # initialized into an empty persist dir → rebuild from Mongo source.
    try:
        from .sd_vector_repo import _vectorstore as _vs
        doc_count = 0
        if _vs is not None:
            try:
                doc_count = _vs._collection.count()
            except Exception:
                doc_count = 0

        logger = get_logger() if callable(get_logger) else None

        if doc_count == 0:
            if logger:
                logger.info({"event": "kb_auto_rebuild_start", "reason": "empty_chroma_at_startup"})
            try:
                from modules.vector_build.vb_service import build_and_swap
                result = build_and_swap(force=True)
                if logger:
                    logger.info({
                        "event": "kb_auto_rebuild_done",
                        "rebuilt": result.get("rebuilt"),
                        "docs": result.get("docs"),
                        "orphans_removed": result.get("orphans_removed"),
                    })
                # Re-bootstrap so _vectorstore in-memory points to the freshly
                # built Chroma. Without this, the existing empty handle persists.
                bootstrap_vectorstore()
            except Exception as e:
                # Best-effort: never crash chatbot startup. Operator can
                # trigger manual rebuild via the knowledgebase-rebuild endpoint.
                if logger:
                    logger.warning({
                        "event": "kb_auto_rebuild_failed",
                        "error": f"{type(e).__name__}: {e}",
                        "hint": "POST /aitegrity-core/knowledgebase-rebuild after fixing root cause",
                    })
        else:
            if logger:
                logger.info({"event": "kb_loaded_from_volume", "doc_count": doc_count})
    except Exception:
        # Defensive — never block startup over the self-heal probe itself.
        pass

    _VECTORSTORE_READY = True

def create_app():
    app = Flask(__name__)
    if (trusted_hosts := _effective_trusted_hosts()) is not None:
        app.config["TRUSTED_HOSTS"] = trusted_hosts
    app.config["JSON_AS_ASCII"] = False

    # log GPU status once at startup
    try:
        logger = get_logger()
        logger.info(
            {
                "event": "trusted_hosts_config",
                "trusted_hosts": app.config.get("TRUSTED_HOSTS"),
            }
        )
        log_gpu_status(logger)
    except Exception:
        print("[gpu] ", log_gpu_status(None), flush=True)

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
