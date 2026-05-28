"""HTTP client for the chatbot endpoint. One method: send_turn()."""
from __future__ import annotations
import os
import time
import requests
from typing import Any


def _api_key() -> str:
    k = os.getenv("API_KEY")
    if not k:
        raise SystemExit("API_KEY env var required (read from .env or shell)")
    return k


def send_turn(
    *,
    base_url: str,
    session_id: str,
    question: str,
    token_id: str | None = None,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """POST one chat turn to the Flask chatbot endpoint.

    Returns the parsed JSON response dict, with an added '__wallclock_ms' field
    measuring the HTTP round-trip duration.
    """
    url = f"{base_url.rstrip('/')}/aitegrity-core/chatbot/claude4sonnet"
    headers = {
        os.getenv("API_HEADER_NAME", "x-api-key"): _api_key(),
        "Content-Type": "application/json",
    }
    # Some envs require an x-website-id header. Auto-attach when configured.
    website_header = os.getenv("WEBSITE_ID_HEADER_NAME", "off")
    website_id = os.getenv("WEBSITE_ID") or os.getenv("TESTING_WEBSITEID")
    if (
        website_header
        and website_header.strip().lower() not in ("off", "disabled", "none")
        and website_id
    ):
        headers[website_header] = website_id
    body = {
        "session_id": session_id,
        "question": question,
        "token_id": token_id or session_id,
        "utilizer": "local",
    }
    t0 = time.perf_counter()
    resp = requests.post(url, json=body, headers=headers, timeout=timeout_s)
    wallclock_ms = int((time.perf_counter() - t0) * 1000)
    resp.raise_for_status()
    data = resp.json()
    data["__wallclock_ms"] = wallclock_ms
    return data
