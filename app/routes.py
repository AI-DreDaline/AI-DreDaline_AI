from flask import Blueprint, jsonify, request
from .utils import ASSETS_SVG_DIR

bp = Blueprint("api", __name__)

@bp.get("/health")
def health():
    return jsonify({"status":"ok"})

@bp.get("/templates")
def templates():
    names = sorted(p.name for p in ASSETS_SVG_DIR.glob("*.svg"))
    return jsonify({"ok": True, "data": {"templates": names}})

@bp.post("/routes/generate")
def routes_generate():
    data = request.get_json(force=True) or {}
    start = data.get("start_point") or {}
    if "lat" not in start or "lng" not in start:
        return jsonify({"ok": False, "error": {"code":400,"message":"start_point.lat/lng required"}}), 400
    if not (data.get("template_name") or data.get("svg")):
        return jsonify({"ok": False, "error": {"code":400,"message":"template_name or svg required"}}), 400

    # 목업 응답 (추후 실제 로직 대체)
    geojson = {
        "type":"FeatureCollection",
        "features":[{
            "type":"Feature",
            "properties":{"name":"mock"},
            "geometry":{"type":"LineString","coordinates":[
                [start["lng"], start["lat"]],
                [start["lng"]+0.001, start["lat"]],
                [start["lng"]+0.001, start["lat"]+0.001],
                [start["lng"], start["lat"]+0.001]
            ]}
        }]
    }
    return jsonify({"ok": True, "data": {"geojson": geojson}})
