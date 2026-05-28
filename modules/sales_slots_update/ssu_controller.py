"""
ssu_controller.py — HTTP controller (Flask Blueprint) for manual execution.

Defines a lightweight REST endpoint:
    /aitegrity-core/ssu/run

Purpose:
    - Allow manual triggering of the Sales Slots Update process.
    - Useful for debugging, manual QA, or ad-hoc refresh outside of scheduler.

Response includes:
    - Number of rows/columns processed.
    - Last run timestamp in WIB timezone.
"""

from flask import Blueprint, jsonify
from .ssu_service import SalesSlotsUpdateService

ssu_bp = Blueprint("sales_slots_update", __name__, url_prefix="/aitegrity-core/ssu")

@ssu_bp.route("/run", methods=["POST", "GET"])
def run_now():
    svc = SalesSlotsUpdateService()
    result = svc.run_once()
    return jsonify({"ok": True, "result": result})