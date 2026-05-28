from __future__ import annotations

import logging
from apscheduler.schedulers.background import BackgroundScheduler

from .tg_repo import TokenRepo
from .tg_utils import getenv_int

log = logging.getLogger(__name__)


class AutoDeactivatePipeline:
    def __init__(self, repo: TokenRepo) -> None:
        self.repo = repo
        self.scheduler = BackgroundScheduler(timezone="UTC")

        self.idle_with_history_s = getenv_int("SESSION_IDLE_WITH_HISTORY_SECONDS", 600)   # 10m
        self.no_activity_ttl_s    = getenv_int("SESSION_NO_ACTIVITY_TTL_SECONDS", 604800) # 7d
        self.interval_s           = getenv_int("CHECK_INTERVAL_SECONDS", 60)

    def _scan_once(self) -> None:
        try:
            docs = self.repo.find_all_with_active_tokens()  # sudah benar
            for d in docs:
                # tambahkan sessionId sebagai kandidat key
                key_for_doc = d.get("api_key") or d.get("userId") or d.get("api_key_user") or d.get("sessionId")
                if not key_for_doc:
                    continue
                for tok in d.get("tokenId_records", []):
                    if tok.get("status") != "active":
                        continue
                    reason = self.repo.deactivate_if_rules_met(
                        key_for_doc, tok,
                        self.idle_with_history_s,
                        self.no_activity_ttl_s
                    )
                    if reason:
                        log.info("Deactivated session token for key=%s reason=%s", key_for_doc, reason)
        except Exception as e:
            log.exception("Auto-deactivate scan error: %s", e)

    def start(self) -> None:
        self.scheduler.add_job(self._scan_once, "interval", seconds=self.interval_s,
                               id="auto_deactivate_scan", max_instances=1, coalesce=True)
        self.scheduler.start()

    def shutdown(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass