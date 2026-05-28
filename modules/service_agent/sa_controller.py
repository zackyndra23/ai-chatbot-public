from __future__ import annotations

from typing import Literal, Tuple, Optional
from flask import Blueprint, request, jsonify, Response
from core.app_config import Config
from .sa_service import INTAgentService
from .sa_repo import ServiceAgentRepo
from infra.app_repo import get_mongo_client

cfg = Config()
sa_bp = Blueprint("service_agent", __name__)

# bikin singleton engine lokal
_sa_repo = ServiceAgentRepo(get_mongo_client())
SA_ENGINE = INTAgentService(repo=_sa_repo)

def _unauthorized(msg: str) -> Tuple[Response, Literal[401]]:
    return jsonify({"error": "unauthorized", "message": msg}), 401

def _bad_request(msg: str) -> Tuple[Response, Literal[400]]:
    return jsonify({"error": "bad_request", "message": msg}), 400

def _check_sa_key() -> Optional[Tuple[Response, Literal[401]]]:
    header_name = getattr(cfg, "SERVICE_AGENT_API_HEADER_NAME", "x-service-agent-api-key")
    expected = getattr(cfg, "SERVICE_AGENT_API_KEY", "")
    if not expected:
        return _unauthorized("Server misconfigured: SERVICE_AGENT_API_KEY missing")
    provided = request.headers.get(header_name) or request.headers.get(header_name.lower())
    if not provided or provided.strip() != str(expected).strip():
        return _unauthorized(f"Invalid or missing Service-Agent API key in header '{header_name}'")
    return None

@sa_bp.post("/aitegrity-core/chatbot/claude4sonnet/service-agent")
def service_agent_entrypoint() -> Tuple[Response, Literal[200]] | Tuple[Response, Literal[400]] | Tuple[Response, Literal[401]]:
    # 1) auth internal
    err = _check_sa_key()
    if err:
        return err

    # 2) parse JSON
    if not request.is_json:
        return _bad_request("Content-Type must be application/json")
    data = request.get_json() or {}

    session_id = data.get("session_id")
    question = data.get("question")

    if not isinstance(session_id, str) or not session_id.strip():
        return _bad_request("session_id is required")
    if not isinstance(question, str) or not question.strip():
        return _bad_request("question is required")

    # 3) di sini kamu bebas:
    #    - question = "PICKER_Employment_Background_Screening" → start flow
    #    - question = "PICKER_EBS_STEP1_..." → lanjutan flow
    result = SA_ENGINE.handle_from_question(session_id=session_id, raw_question=question)

    return jsonify(result), 200