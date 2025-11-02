from __future__ import annotations
from flask import Blueprint, request, jsonify
from app.services.svg_service import parse_svg
from app.services.match_service import map_match_points

bp = Blueprint("routes_generate", __name__, url_prefix="/routes")

def _bad(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code

@bp.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        return _bad("Invalid JSON body")

    required = ["svg_text", "target_km", "start_lng", "start_lat"]
    for k in required:
        if k not in data:
            return _bad(f"Missing field: {k}")

    svg_text = str(data["svg_text"])
    if "<svg" not in svg_text:
        return _bad("svg_text must contain an <svg> tag")

    try:
        target_km = float(data["target_km"])
        start_lng = float(data["start_lng"])
        start_lat = float(data["start_lat"])
    except Exception:
        return _bad("target_km/start_lng/start_lat must be numeric")

    if not (0.5 <= target_km <= 50.0):
        return _bad("target_km out of range (0.5~50.0)")

    rotate_deg = float(data.get("rotate_deg", 0.0))
    resample_m = float(data.get("resample_m", 5.0))
    step_m = float(data.get("step_m", 5.0))
    graph_radius_m = int(data.get("graph_radius_m", 3000))

    try:
        # 1) SVG → 포인트(경도/위도 순서로 이동했다고 가정)
        tmpl = parse_svg(
            svg_text=svg_text,
            target_km=target_km,
            start_xy=(start_lng, start_lat),
            resample_m=resample_m,
            rotate_deg=rotate_deg,
            step_m=step_m,
        )
        pts = tmpl["points"]  # [(lng,lat), ...]

        # 2) 맵매칭
        mm = map_match_points(
            pts_lnglat=pts,
            center_lat=start_lat,
            center_lng=start_lng,
            graph_radius_m=graph_radius_m,
        )

        # 3) 응답
        return jsonify({
            "ok": True,
            "matched": mm["matched"],
            "target_km": target_km,
            "template_length_m": float(tmpl["template_length_m"]),
            "scale_m_per_unit": float(tmpl["scale_m_per_unit"]),
            "route_length_m": float(mm["route_length_m"]),
            "route_coords_lnglat": mm["route_coords_lnglat"],
            "route_nodes": mm["route_nodes"],
        }), 200

    except Exception as e:
        return _bad(f"Exception: {type(e).__name__}: {e}", code=500)
