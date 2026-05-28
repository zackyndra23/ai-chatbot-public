"""
ssu_pipelines.py — Background scheduler pipeline for periodic updates.

Implements:
    - APScheduler-based recurring job registration.
    - Time-window guard: only runs during defined working hours (WIB).
    - Reads interval duration and feature toggle from environment variables.
    - Executes SalesSlotsUpdateService().run_once() safely with logging.

This module is intended to be initialized once during app startup
via register_ssu_scheduler(app), ensuring automatic synchronization
every N minutes while the app is running.
"""

from __future__ import annotations
from datetime import datetime
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

from .ssu_service import SalesSlotsUpdateService
from .ssu_utils import read_env_config, parse_hhmm, now_wib

_scheduler: BackgroundScheduler | None = None

def _within_working_hours(now_wib_dt: datetime, work_start, work_end) -> bool:
    t = now_wib_dt.time()
    return (t >= work_start) and (t <= work_end)

def _job():
    cfg = read_env_config()
    if not cfg["SSU_FEATURE_ON"]:
        return
    work_start = parse_hhmm(cfg["WORK_START"])
    work_end   = parse_hhmm(cfg["WORK_END"])
    if _within_working_hours(now_wib(), work_start, work_end):
        try:
            SalesSlotsUpdateService().run_once()
        except Exception as e:
            # log ringan; gunakan logger global kalau ada
            print(f"[SSU] job error: {e}")

def register_ssu_scheduler(app: Flask):
    """
    Dipanggil saat app start (mirip token_generate). 
    Hanya membuat scheduler sekali.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    cfg = read_env_config()
    if not cfg.get("SSU_FEATURE_ON", True):
        try:
            app.logger.info("[SSU] Scheduler disabled by env (SSU_FEATURE_ON=false).")
        except Exception:
            print("[SSU] Scheduler disabled by env (SSU_FEATURE_ON=false).")
        return None

    interval_min = cfg["SLOTS_UPDATE_DURATION"]

    sched = BackgroundScheduler(timezone="Asia/Jakarta")
    sched.add_job(_job, "interval", minutes=interval_min, id="ssu_interval_job", max_instances=1, coalesce=True)
    sched.start()

    # Flask>=3: before_first_request is removed. Log immediately after start.
    try:
        app.logger.info(
            "[SSU] Scheduler aktif setiap %s menit, jam kerja WIB %s-%s | feature_on=%s",
            interval_min, cfg["WORK_START"], cfg["WORK_END"], cfg["SSU_FEATURE_ON"]
        )
    except Exception:
        print(f"[SSU] Scheduler aktif setiap {interval_min} menit, jam kerja WIB {cfg['WORK_START']}-{cfg['WORK_END']} | feature_on={cfg['SSU_FEATURE_ON']}")

    _scheduler = sched
    return _scheduler
