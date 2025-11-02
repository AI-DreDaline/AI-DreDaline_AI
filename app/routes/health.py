from flask import Blueprint, jsonify
bp = Blueprint("health", __name__, url_prefix="/")
@bp.route("health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "ai_algo_server"}), 200
