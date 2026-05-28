from __future__ import annotations

import logging, json
from flask import Blueprint, request, jsonify

from .tg_service import TokenService
from .tg_repo import TokenRepo

bp = Blueprint("token_generate", __name__)

repo = TokenRepo()
svc = TokenService(repo)

log = logging.getLogger(__name__)

@bp.route("/aitegrity-core/user-id-generate", methods=["POST"])
def api_key_generate():
    """
    Terima:
      1) JSON body:            {"websiteId":"..."}
      2) x-www-form-urlencoded: websiteId=...
      3) Query string:         POST /user-id-generate?websiteId=...
    """
    try:
        payload = None

        # --- 1) JSON body (robust: coba beberapa cara) ---
        raw = request.get_data(cache=False, as_text=True) or ""
        payload = None
        try:
            payload = request.get_json(silent=True)
        except Exception:
            payload = None
        if payload is None:
            try:
                payload = json.loads(raw)
            except Exception:
                # fallback: buang BOM + trim
                raw2 = raw.lstrip("\ufeff").strip()
                try:
                    payload = json.loads(raw2)
                except Exception:
                    payload = None

        if not isinstance(payload, dict):
            payload = {}

        # if isinstance(payload, dict) and "website_id" in payload:
        #     website_id = str(payload.get("website_id") or "").strip()

        # --- 2) Form (application/x-www-form-urlencoded / multipart) ---
        if request.form:
            if "websiteId" in request.form and not payload.get("websiteId"):
                payload["websiteId"] = str(request.form.get("websiteId") or "").strip()
            if "api_key" in request.form and not payload.get("api_key"):
                payload["api_key"] = str(request.form.get("api_key") or "").strip()
            if "name" in request.form and not payload.get("name"):                       # << NEW
                payload["name"] = str(request.form.get("name") or "").strip()

        # --- 3) Query string ---
        if request.args:
            if request.args.get("websiteId") and not payload.get("websiteId"):
                payload["websiteId"] = str(request.args.get("websiteId") or "").strip()
            if request.args.get("api_key") and not payload.get("api_key"):
                payload["api_key"] = str(request.args.get("api_key") or "").strip()
            if request.args.get("name") and not payload.get("name"):                     # << NEW
                payload["name"] = str(request.args.get("name") or "").strip()

        result = svc.generate_api_key(payload)
        status = 200 if isinstance(result, dict) and result.get("status") == "ok" else (
            result[1] if isinstance(result, tuple) else 400
        )
        body = result[0] if isinstance(result, tuple) else result
        return jsonify(body), status
    except Exception as e:
        log.exception("user-id-generate error: %s", e)
        return jsonify({"error": "internal_error"}), 500

@bp.route("/aitegrity-core/session-id-generate", methods=["POST"])
def session_id_generate():
    try:
        raw = request.get_data(as_text=True) or ""
        api_key = request.headers.get(repo.api_header_name)
        out = svc.generate_session_id(raw, api_key)
        if isinstance(out, tuple):
            body, code = out
            return jsonify(body), code
        return jsonify(out), 200
    except Exception as e:
        log.exception("session-id-generate error: %s", e)
        return jsonify({"error": "internal_error"}), 500