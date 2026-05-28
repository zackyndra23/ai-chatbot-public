from __future__ import annotations

from typing import Literal, Optional, Tuple
from flask import Blueprint, request, jsonify, Response

from .sd_service import handle_chat
from .sd_repo import append_chat_history_mongo, lookup_session_by_token
from core.app_config import Config

cfg = Config()
sd_bp = Blueprint("system_detection", __name__)


# ---------- Small helpers (each does one thing) ----------

def _unauthorized(msg: str) -> Tuple[Response, Literal[401]]:
    return jsonify({"error": "unauthorized", "message": msg}), 401

def _bad_request(msg: str) -> Tuple[Response, Literal[400]]:
    return jsonify({"error": "bad_request", "message": msg}), 400

def _ok(payload: dict) -> Tuple[Response, Literal[200]]:
    return jsonify(payload), 200

def _check_api_key() -> Optional[Tuple[Response, Literal[401]]]:
    api_header = getattr(cfg, "API_HEADER_NAME", "x-api-key")
    expected = getattr(cfg, "API_KEY", "4743f227-0b8c-4a22-827d-16d5eb18fb56")

    # pastikan API_KEY wajib ada
    if not expected or not str(expected).strip():
        return _unauthorized("Server misconfigured: API_KEY missing in .env")

    provided = request.headers.get(api_header) or request.headers.get(api_header.lower())
    if not provided or provided.strip() != str(expected).strip():
        return _unauthorized(f"Invalid or missing API key in header '{api_header}'")

    return None

def _get_website_id_or_error():
    header = getattr(cfg, "WEBSITE_ID_HEADER_NAME", "x-website-id")
    # if header name is disabled/empty => optional
    if not header or str(header).strip().lower() in ("off", "disabled", "none"):
        return None, None
    value = request.headers.get(header)
    if not value or not str(value).strip():
        return None, _bad_request(f"Missing required header '{header}'")
    return str(value).strip(), None

def _parse_json_or_error() -> Tuple[dict, Optional[Tuple[Response, Literal[400]]]]:
    if not request.is_json:
        return {}, _bad_request("Content-Type must be application/json")
    try:
        data = request.get_json(silent=False) or {}
    except Exception as e:
        return {}, _bad_request(f"Invalid JSON: {e}")
    return data, None


def _normalize_utilizer(data: dict) -> str:
    raw = data.get("utilizer", getattr(cfg, "UTILIZER_STATUS", "local"))
    return raw.strip().lower() if isinstance(raw, str) else "local"


def _resolve_session_ids(
    utilizer: str,
    session_id: Optional[str],
    token_id: Optional[str]
) -> Tuple[Optional[str], Optional[str], Optional[Tuple[Response, Literal[400]]]]:
    if utilizer == "crisp":
        crisp_sid = request.headers.get("X-Crisp-Session-Id")
        session_id = session_id or crisp_sid
        if not session_id:
            return None, None, _bad_request("missing session_id (X-Crisp-Session-Id)")
        return session_id, (token_id or session_id), None

    # Non-crisp: resolve if missing or equal to token_id
    if (not session_id) or (token_id and session_id == token_id):
        sid = lookup_session_by_token(token_id)
        session_id = sid or session_id or token_id
    return session_id, token_id, None


def _persist_best_effort(session_id: str, token_id: Optional[str], question: str, result: dict) -> bool:
    try:
        return bool(append_chat_history_mongo(session_id, token_id, question, result))
    except Exception as e:
        print(f"[chat_history] error: {e}")
        return False


# ---------- Route (low complexity) ----------

@sd_bp.post("/aitegrity-core/chatbot/claude4sonnet")
def chat_entrypoint() -> (
    Tuple[Response, Literal[401]]
    | Tuple[Response, Literal[400]]
    | Tuple[Response, Literal[200]]
):
    # 1) API key
    api_err = _check_api_key()
    if api_err:
        return api_err

    # 2) Website ID (optional/required by cfg)
    website_id, website_err = _get_website_id_or_error()
    if website_err:
        return website_err

    # 3) JSON
    data, json_err = _parse_json_or_error()
    if json_err:
        return json_err

    # 4) Extract
    session_id = data.get("session_id")
    question = data.get("question")
    token_id = data.get("token_id") or request.headers.get("x-token-id")
    utilizer = _normalize_utilizer(data)

    if not isinstance(question, str) or not question.strip():
        return _bad_request("question is required")

    # 5) Session resolution
    session_id, token_id, sess_err = _resolve_session_ids(utilizer, session_id, token_id)
    if sess_err:
        return sess_err
    if not session_id:
        return _bad_request("session_id is required")

    # 6) Handle chat
    result = handle_chat(session_id=session_id, question=question, token_id=token_id)
    if not isinstance(result, dict):
        result = {"result": str(result)}

    # 7) Persist (best-effort)
    result["_persisted"] = _persist_best_effort(session_id, token_id, question, result)
    result["_website_id"] = website_id

    return _ok(result)
