from __future__ import annotations
from flask import Blueprint, request, jsonify
from app.services.svg_service import parse_svg

bp = Blueprint("routes_generate", __name__, url_prefix="/routes")


def _bad(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


@bp.route("/generate", methods=["POST"])
def generate():
    """
    Request JSON
    {
      "svg_text": "<svg ...>...</svg>",
      "target_km": 2.0,
      "start_lng": 126.5312,
      "start_lat": 33.4996,
      "rotate_deg": 0.0,      # (optional)
      "resample_m": 5.0,      # (optional)
      "step_m": 5.0           # (optional, final resample step)
    }
    """
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        return _bad("Invalid JSON body")

    # --- required fields ---
    required = ["svg_text", "target_km", "start_lng", "start_lat"]
    for k in required:
        if k not in data:
            return _bad(f"Missing field: {k}")

    svg_text = str(data.get("svg_text", ""))
    if "<svg" not in svg_text:
        return _bad("svg_text must contain an <svg> tag")

    # numeric casting + range check
    try:
        target_km = float(data.get("target_km"))
        start_lng = float(data.get("start_lng"))
        start_lat = float(data.get("start_lat"))
    except Exception:
        return _bad("target_km/start_lng/start_lat must be numeric")

    if not (0.5 <= target_km <= 50.0):
        return _bad("target_km out of range (0.5~50.0)")

    rotate_deg = float(data.get("rotate_deg", 0.0))
    resample_m = float(data.get("resample_m", 5.0))
    step_m = float(data.get("step_m", 5.0))

    try:
        # 1) SVG → 스케일/회전/시작점 이동/리샘플
        out = parse_svg(
            svg_text=svg_text,
            target_km=target_km,
            start_xy=(start_lng, start_lat),  # (lng, lat) 규약
            resample_m=resample_m,
            rotate_deg=rotate_deg,
            step_m=step_m,
        )

        # 2) 안정된 응답 형태
        resp = {
            "ok": True,
            "target_km": target_km,
            "scale_m_per_unit": float(out["scale_m_per_unit"]),
            "template_length_m": float(out["template_length_m"]),
            "points": out["points"],  # [(lng,lat), ...] 형태의 샘플 좌표
        }
        return jsonify(resp), 200

    except Exception as e:
        # svg 파싱/스케일 도중 에러가 나면 500으로 반환
        return _bad(f"Exception: {type(e).__name__}: {e}", code=500)
