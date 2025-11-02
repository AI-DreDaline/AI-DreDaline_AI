from flask import Blueprint, request, jsonify
from app.services.svg_service import parse_svg

bp = Blueprint("routes_generate", __name__, url_prefix="/routes")

@bp.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.get_json()
        svg_text = data.get("svg_text")
        target_km = float(data.get("target_km", 2.0))
        start_lng = float(data.get("start_lng", 126.5312))
        start_lat = float(data.get("start_lat", 33.4996))

        result = parse_svg(svg_text, target_km, (start_lng, start_lat))
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
