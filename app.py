import os
import logging
from fastapi import FastAPI, Header, HTTPException, Request
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
# --- SSU imports (pakai modul yang sudah kamu buat) ---
from modules.sales_slots_update.ssu_service import SalesSlotsUpdateService
from modules.sales_slots_update.ssu_utils import read_env_config, parse_hhmm, now_wib

from core.app_config import Config
from core.app_logging import setup_logging
from core.app_service import build_services
from core.app_error import register_error_handlers

from modules.faq_automation.faq_controller import router as faq_router

from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from zoneinfo import ZoneInfo

# -------------------------------------------------------------------
# SSU helpers
# -------------------------------------------------------------------
WIB = ZoneInfo("Asia/Jakarta")

def _within_working_hours(dt: datetime, start_str: str, end_str: str) -> bool:
    start = parse_hhmm(start_str)
    end   = parse_hhmm(end_str)
    t = dt.astimezone(WIB).time()
    return (t >= start) and (t <= end)

def _ssu_job():
    """
    Interval job: baca ENV terbaru setiap run (supaya perubahan .env terbaca
    tanpa restart), cek jam kerja, lalu jalankan 1 siklus SSU.
    """
    cfg_env = read_env_config()
    if not cfg_env.get("SSU_FEATURE_ON", True):
        return
    if _within_working_hours(now_wib(), cfg_env["WORK_START"], cfg_env["WORK_END"]):
        try:
            out = SalesSlotsUpdateService().run_once()
            logging.info({"event": "ssu_ok", **out})
        except Exception as e:
            logging.exception(f"[SSU] job error: {e}")

# -------------------------------------------------------------------
# FastAPI app factory
# -------------------------------------------------------------------

def create_app() -> FastAPI:
    setup_logging()
    cfg = Config()
    cfg.validate()

    app = FastAPI(title="RAG Chatbot v01 — FAQ + Sales Slots Update")
    app.state.cfg = cfg
    app.state.services = build_services(cfg)

    # ==================== Scheduler ====================
    tz = pytz.timezone(cfg.TIMEZONE)
    scheduler = BackgroundScheduler(timezone=tz)

    # SSU: interval minutes (guard jam kerja di dalam _ssu_job)
    ssu_cfg = read_env_config()
    interval_min = int(ssu_cfg.get("SLOTS_UPDATE_DURATION", 30))
    scheduler.add_job(
        _ssu_job,
        "interval",
        minutes=interval_min,
        id="ssu_interval_job",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.start()
    app.state._scheduler = scheduler

    logging.info(
        "[SSU] Scheduler aktif tiap %s menit | WIB %s-%s | feature_on=%s",
        interval_min, ssu_cfg["WORK_START"], ssu_cfg["WORK_END"], ssu_cfg["SSU_FEATURE_ON"]
    )
    # ====================================================

    # Router FAQ (sudah ada)
    app.include_router(faq_router)  # endpoint: /rag-assistant/faq-automation
    # (ini persis pola yang sudah kamu pakai) :contentReference[oaicite:1]{index=1}

    # ----------------- Endpoint manual KB rebuild -----------------
    @app.post("/rag-assistant/knowledgebase-rebuild")
    async def kb_rebuild_trigger(request: Request, x_api_key: str = Header(None)):
        """
        Manual rebuild of the Chroma knowledgebase from the current Mongo FAQ
        chunks. Bypasses the checksum gate (always rebuilds). Does NOT re-fetch
        from Google Sheets and does NOT touch Mongo.

        Trigger shape matches /rag-assistant/faq-automation:
          Header: x-api-key: <cfg.API_KEY>
          Content-Type: text/plain
          Body: cfg.TRIGGER_TRUE_VALUE   (default "true")
        """
        expected_key = request.app.state.cfg.API_KEY
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Unauthorized")

        ctype = (request.headers.get("content-type") or "").lower()
        if "text/plain" not in ctype:
            raise HTTPException(status_code=415, detail="Content-Type must be text/plain")

        trigger_value = (getattr(request.app.state.cfg, "TRIGGER_TRUE_VALUE", "true") or "true").strip().lower()
        body = (await request.body()).decode("utf-8", errors="ignore").strip().lower()
        if body != trigger_value:
            return JSONResponse(
                {"ok": False, "reason": f"payload must be '{trigger_value}'"},
                status_code=400,
            )

        from modules.vector_build.vb_service import build_and_swap
        result = build_and_swap(force=True)
        return {"ok": True, **result}
    # ---------------------------------------------------------------

    # ----------------- Per-service manual rebuild (Stage 3A) -----------------
    @app.post("/rag-assistant/knowledgebase-rebuild/{service_id}")
    async def kb_rebuild_one_service(
        service_id: str,
        request: Request,
        x_api_key: str = Header(None),
    ):
        """Force rebuild of ONE service's collection.

        Auth/content-type/trigger-value identical to /knowledgebase-rebuild.
        Returns {ok, service_id, rebuilt, doc_count, checksum} on success.
        Only meaningful when KB_BACKEND in {split, dual}.
        """
        expected_key = request.app.state.cfg.API_KEY
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Unauthorized")

        ctype = (request.headers.get("content-type") or "").lower()
        if "text/plain" not in ctype:
            raise HTTPException(status_code=415, detail="Content-Type must be text/plain")

        trigger_value = (getattr(request.app.state.cfg, "TRIGGER_TRUE_VALUE", "true") or "true").strip().lower()
        body = (await request.body()).decode("utf-8", errors="ignore").strip().lower()
        if body != trigger_value:
            return JSONResponse(
                {"ok": False, "reason": f"payload must be '{trigger_value}'"},
                status_code=400,
            )

        cfg_obj = request.app.state.cfg
        backend = (getattr(cfg_obj, "KB_BACKEND", "legacy") or "legacy").strip().lower()
        if backend not in ("split", "dual"):
            return JSONResponse(
                {"ok": False, "reason": f"per-service rebuild requires KB_BACKEND in {{split, dual}}; current: {backend}"},
                status_code=400,
            )

        from modules.vector_build import vb_per_service, vb_registry
        from infra.app_repo import build_faq_repo
        from pathlib import Path

        repo = build_faq_repo(cfg_obj)
        services = repo.list_services()
        match = next((s for s in services if s["service_id"] == service_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail=f"service_id not in repo: {service_id}")

        current_root = Path(cfg_obj.VECTOR_CURRENT_SYMLINK)
        building_root = Path(cfg_obj.VECTOR_DATA_DIR) / "building"
        trash_root = Path(cfg_obj.VECTOR_DATA_DIR) / "trash"

        # Force rebuild by removing meta.json (so checksum compare says "stale")
        vb_registry.remove_collection_meta(current_root / service_id)

        result = vb_per_service.build_all(
            services_now=[match],
            current_root=current_root,
            building_root=building_root,
            trash_root=trash_root,
        )
        per_svc = next((s for s in result["per_service"] if s["service_id"] == service_id), None)

        return {
            "ok": True,
            "service_id": service_id,
            "rebuilt": (per_svc or {}).get("rebuilt", False),
            "doc_count": (per_svc or {}).get("doc_count", 0),
            "checksum": (per_svc or {}).get("checksum"),
        }
    # -----------------------------------------------------------------------

    # ----------------- Endpoint manual SSU -----------------
    @app.post("/rag-assistant/sales-slots-update")
    def ssu_trigger(payload: str = "", x_api_key: str = Header(None)):
        """
        Manual trigger ala FAQ. Wajib header: x-api-key
        """
        # Ambil API key dari env (pakai salah satu; sesuaikan dgn kebijakanmu)
        expected = (
            os.getenv("X_API_KEY")
            or os.getenv("API_KEY")
            or os.getenv("SSU_API_KEY")
        )
        if expected and (x_api_key != expected):
            raise HTTPException(status_code=401, detail="invalid api key")

        cfg_env = read_env_config()
        if not cfg_env.get("SSU_FEATURE_ON", True):
            return JSONResponse({"ok": False, "reason": "SSU_FEATURE_ON=false"}, status_code=400)

        result = SalesSlotsUpdateService().run_once()
        return {"ok": True, "result": result}
    # -------------------------------------------------------

    register_error_handlers(app)
    return app

# uvicorn app:app --host 0.0.0.0 --port 2313 --reload
app = create_app()
