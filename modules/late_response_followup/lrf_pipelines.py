from __future__ import annotations

from core.app_config import Config
from modules.late_response_followup.lrf_service import LateResponseFollowupService

cfg = Config()


def register_late_response_followup_job(scheduler) -> None:
    if cfg.LATE_RESPONDS_FEATURE not in ("1", "true", "yes", "on"):
        return

    scheduler.add_job(
        func=_run_lrf_job,
        trigger="interval",
        seconds=int(cfg.LATE_RESPONDS_CHECK_INTERVAL or 60),
        id="late_response_followup_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )


def _run_lrf_job() -> None:
    service = LateResponseFollowupService()
    service.run_scan(limit=100)