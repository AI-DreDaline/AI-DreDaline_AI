from flask import Blueprint, jsonify

bp = Blueprint("health", __name__, url_prefix="/")

@bp.route("health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "flask_reset"}), 200
