from __future__ import annotations

from flask import Blueprint, jsonify, request

from core.app_config import Config
from modules.late_response_followup.lrf_service import LateResponseFollowupService

cfg = Config()

late_response_followup_bp = Blueprint(
    "late_response_followup_bp",
    __name__,
)


@late_response_followup_bp.post("/aitegrity-core/chatbot/late-response-followup/run")
def run_late_response_followup():
    header_name = cfg.API_HEADER_NAME
    expected = cfg.API_KEY
    provided = request.headers.get(header_name, "")

    if expected and provided != expected:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    limit = int(request.json.get("limit", 100)) if request.is_json else 100
    service = LateResponseFollowupService()
    result = service.run_scan(limit=limit)
    return jsonify(result), 200