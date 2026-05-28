"""Guard against accidentally hitting prod Mongo with QA traffic.

Any non-localhost target requires explicit --allow-prod flag or
QA_ALLOW_PROD=1 env var. Default refuses with a loud error.
"""
from __future__ import annotations
import os
from urllib.parse import urlparse


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


def assert_safe_target(url: str, *, allow_prod: bool) -> None:
    """Raise SystemExit when targeting a non-localhost URL without explicit approval."""
    if is_local(url):
        return
    if allow_prod or os.getenv("QA_ALLOW_PROD") == "1":
        return
    raise SystemExit(
        f"REFUSED: QA target is non-localhost ({url!r}) but --allow-prod not set "
        "and QA_ALLOW_PROD env var not '1'. Aborting to protect prod Mongo from "
        "QA traffic. Re-run with --allow-prod if you really mean it."
    )
