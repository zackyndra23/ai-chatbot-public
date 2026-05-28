from __future__ import annotations
from flask import Blueprint, render_template, request, jsonify
from .ctu_service import (
    load_ui_config,
    find_account_by_name,
    deactivate_token_append,
    shutdown_append_direct,
    generate_session_id,
)

from os import getenv
from core.app_config import Config
cfg = Config()

bp = Blueprint("chat_testing_ui", __name__, template_folder="templates")

@bp.get("/aitegrity-core/chatbot/claude4sonnet/ui_testing/<name>")
def ui_testing(name: str):
    name = (name or "").strip()
    cfg = load_ui_config()
    doc, active_token = find_account_by_name(cfg, name)
    not_found = False if doc else True

    nickname = email = phone = country = region = ""
    session_id = ""
    token_txt  = "USER NOT FOUND" if not_found else (active_token or "Please Generate!")

    if not not_found:
        if isinstance(doc.get("user"), dict):
            u = doc["user"]
            nickname = u.get("nickname", "") or ""
            email    = u.get("email", "") or ""
            phone    = u.get("phone", "") or ""
            country  = u.get("country", "") or ""
            region   = u.get("region", "") or ""
            session_id = (doc.get("sessionId") or "")   # ⬅️ tampilkan apa adanya
        else:
            nickname = (doc.get("name") or "")

    return render_template(
        "ui_testing.html",
        name=name,
        not_found=not_found,
        nickname=nickname,
        email=email,
        phone=phone,
        country=country,
        region=region,
        session_id=session_id,   # ⬅️ baru
        token=token_txt,
        backend_origin=cfg.backend_origin,
        base_path=cfg.base_path,
        bootstrap={
            "name": name,
            "not_found": not_found,
            "token": token_txt,            # untuk enable/disable Ask
            "backend_origin": cfg.backend_origin,
            "base_path": cfg.base_path,
        },
    )

@bp.post("/aitegrity-core/chatbot/claude4sonnet/ui_testing_proxy/<name>")
def ui_testing_proxy(name: str):
    cfg = load_ui_config()
    body = request.get_json(silent=True) or {}
    q = (body.get("question") or "").strip()
    if not q:
        return jsonify({"error": "question is required"}), 400
    doc, active_token = find_account_by_name(cfg, name)
    if not doc:
        return jsonify({"error": "not_found", "detail": f"name '{name}' not found"}), 404
    if not active_token:
        return jsonify({"error": "no_active_token", "detail": "Please generate a token first."}), 428
    
    headers = {
        "Content-Type": "application/json",
        cfg.api_header_name or "x-api-key": getenv("API_KEY", "4743f227-0b8c-4a22-827d-16d5eb18fb56"),  # kirim API_KEY backend dari .env
        # cfg.api_header_name or "x-api-key": "4743f227-0b8c-4a22-827d-16d5eb18fb57",  # kirim API_KEY backend dari .env untuk testing
    }

    import requests
    url = f"{cfg.backend_origin}{cfg.base_path}"
    session_id = doc.get("sessionId")
    resp = requests.post(
        url,
        json={"session_id": session_id, "token_id": active_token, "question": q},
        headers=headers,
        timeout=75,   
    )
    try:
        return jsonify(resp.json()), resp.status_code
    except Exception:
        return resp.text, resp.status_code, {"Content-Type": resp.headers.get("Content-Type", "text/plain")}

@bp.post("/aitegrity-core/chatbot/claude4sonnet/ui_testing_activate/<name>")
def ui_testing_activate(name: str):
    cfg = load_ui_config()
    doc, _ = find_account_by_name(cfg, name)
    if not doc:
        return jsonify({"error": "not_found", "detail": f"name '{name}' not found"}), 404

    # === mode baru: crisp_sessions → header = sessionId ===
    if isinstance(doc.get("user"), dict) and doc.get("sessionId"):
        out = generate_session_id(cfg, doc["sessionId"])
        if "json" in out:
            return jsonify(out["json"]), out["status_code"]
        return out.get("text",""), out["status_code"], {"Content-Type":"text/plain"}

    # === fallback lama (api_keys) → header = userId ===
    user_id = (doc.get("userId") or doc.get("user_id") or "").strip()
    if not user_id:
        return jsonify({"error": "no_user_id", "detail": "userId missing in document"}), 400
    out = generate_session_id(cfg, user_id)
    if "json" in out:
        return jsonify(out["json"]), out["status_code"]
    return out.get("text",""), out["status_code"], {"Content-Type":"text/plain"}

@bp.post("/aitegrity-core/chatbot/claude4sonnet/ui_testing_shutdown/<name>")
def ui_testing_shutdown(name: str):
    cfg = load_ui_config()
    doc, _ = find_account_by_name(cfg, name)
    if not doc:
        return jsonify({"error": "not_found", "detail": f"name '{name}' not found"}), 404

    if isinstance(doc.get("user"), dict) and doc.get("sessionId"):
        ok = shutdown_append_direct(cfg, doc["sessionId"])  # ⬅️ append array baru
        return jsonify({"status": "ok" if ok else "noop"}), 200

    # fallback lama (kalau koleksi lain)
    return jsonify({"status": "noop"}), 200