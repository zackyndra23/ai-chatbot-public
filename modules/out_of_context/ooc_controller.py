from __future__ import annotations

from flask import Blueprint, request, jsonify
from core.app_config import Config
from .ooc_service import OOCService

cfg = Config()

ooc_bp = Blueprint("ooc_agent", __name__)

@ooc_bp.route("/rag-assistant/chatbot/ooc-agent/test", methods=["POST"])
def ooc_test():
    """
    Body:
    {
      "text": "I want to be a freelancer",
      "language_code": "en"  # optional
    }
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or data.get("question") or "").strip()
    language_code = (data.get("language_code") or data.get("lang") or "").strip() or None

    svc = OOCService()
    res = svc.classify(user_text=text, language_code=language_code)

    # jsonifiable (pydantic v1)
    return jsonify(res.dict())