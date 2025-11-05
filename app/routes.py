from __future__ import annotations
from flask import Blueprint, jsonify, request
from .utils import ASSETS_SVG_DIR
from app.services.svg_service import parse_svg_inline
from adra_core.mapmatch import map_match_osmnx
from adra_core.freefit import free_fit_search
import math

bp = Blueprint("api", __name__)

# -------------------- basics --------------------

@bp.get("/health")
def health():
    return jsonify({"status": "ok"})

@bp.get("/templates")
def templates():
    names = sorted(p.name for p in ASSETS_SVG_DIR.glob("*.svg"))
    return jsonify({"ok": True, "data": {"templates": names}})

# -------------------- geo helpers --------------------

R_EARTH = 6371000.0  # meters

def _meters_to_deg(lat_deg: float, dx_m: float, dy_m: float):
    lat_rad = math.radians(lat_deg)
    dlat = (dy_m / R_EARTH) * (180.0 / math.pi)
    dlng = (dx_m / (R_EARTH * math.cos(lat_rad))) * (180.0 / math.pi)
    return dlng, dlat

def _poly_len_xy(points_xy):
    if not points_xy or len(points_xy) < 2:
        return 0.0
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points_xy, points_xy[1:]):
        dx, dy = x2 - x1, y2 - y1
        total += (dx*dx + dy*dy) ** 0.5
    return total

def _xy_to_lnglat_scaled(points_xy, start_lat, start_lng, scale_m_per_unit, rotation_deg=0.0, center=True):
    if not points_xy:
        return []
    pts = points_xy[:]

    if center:
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        pts = [(x - cx, y - cy) for x, y in pts]

    if rotation_deg:
        th = math.radians(rotation_deg)
        c, s = math.cos(th), math.sin(th)
        pts = [(c*x - s*y, s*x + c*y) for x, y in pts]

    out = []
    for x, y in pts:
        dx_m, dy_m = x * scale_m_per_unit, y * scale_m_per_unit
        dlng, dlat = _meters_to_deg(start_lat, dx_m, dy_m)
        out.append([start_lng + dlng, start_lat + dlat])  # [lng, lat]
    return out

def _haversine_m(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R_EARTH * atan2(math.sqrt(a), math.sqrt(1 - a))

def _poly_len_m(coords_lnglat):
    if len(coords_lnglat) < 2:
        return 0.0
    total = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(coords_lnglat, coords_lnglat[1:]):
        total += _haversine_m(lat1, lng1, lat2, lng2)
    return total

# -------------------- main endpoint --------------------

@bp.post("/routes/generate")
def routes_generate():
    """
    Body(JSON):
    {
      "start_point": {"lat": 33.4996, "lng": 126.5312},
      "target_km": 8.0,
      "template_name": "star.svg" | (or "svg": "<svg ...>"),
      "options": {
        "resample_m": 5.0,
        "simplify_tolerance": 0.5,
        "rotation_deg": 0.0,
        "align_mode": "start_locked" | "free_fit",
        "map_match": true,
        "graph_dist_m": 3000,
        "sample_step_m": 60,
        "retune_tolerance": 0.05,
        "retune_max_iter": 3
      }
    }
    """
    # -------- 입력 --------
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": {"code": 400, "message": "Invalid JSON"}}), 400

    start = data.get("start_point") or {}
    if "lat" not in start or "lng" not in start:
        return jsonify({"ok": False, "error": {"code": 400, "message": "start_point.lat and start_point.lng are required"}}), 400
    lat0 = float(start["lat"])
    lng0 = float(start["lng"])

    try:
        target_km = float(data.get("target_km", 2.0))
    except Exception:
        return jsonify({"ok": False, "error": {"code": 400, "message": "target_km must be a number"}}), 400
    if target_km <= 0:
        return jsonify({"ok": False, "error": {"code": 400, "message": "target_km must be > 0"}}), 400
    target_m = target_km * 1000.0

    svg_text = data.get("svg")
    template_name = data.get("template_name")
    if not svg_text and not template_name:
        return jsonify({"ok": False, "error": {"code": 400, "message": "Provide either 'svg' or 'template_name'"}}), 400
    if template_name:
        p = ASSETS_SVG_DIR / template_name
        if not p.exists():
            return jsonify({"ok": False, "error": {"code": 404, "message": f"Template '{template_name}' not found"}}), 404
        svg_text = p.read_text(encoding="utf-8")

    opts = data.get("options", {}) or {}
    resample       = float(opts.get("resample_m", 5.0))
    simplify_tol   = float(opts.get("simplify_tolerance", 0.0))
    rotation_deg   = float(opts.get("rotation_deg", 0.0))
    align_mode     = (opts.get("align_mode") or "start_locked").lower()
    do_match       = bool(opts.get("map_match", True))
    graph_dist_m   = int(opts.get("graph_dist_m", 3000))
    sample_step_m  = int(opts.get("sample_step_m", 60))
    tol_ratio      = float(opts.get("retune_tolerance", 0.05))
    max_iter       = int(opts.get("retune_max_iter", 3))

    # -------- SVG → XY --------
    pts_xy = parse_svg_inline(svg_text, resample_m=resample, simplify_tolerance=simplify_tol)
    if len(pts_xy) < 2:
        return jsonify({"ok": False, "error": {"code": 422, "message": "SVG parsing returned too few points"}}), 422
    L_xy = _poly_len_xy(pts_xy)
    if L_xy <= 0:
        return jsonify({"ok": False, "error": {"code": 422, "message": "Invalid SVG polyline length"}}), 422

    # SVG 'unit' → meter 스케일
    scale_m_per_unit = target_m / L_xy

    # -------- free_fit / start_locked 분기 --------
    used_align_mode = align_mode
    fallback_used = False
    fit_params = None

    if align_mode == "free_fit":
        fit = free_fit_search(
            pts_xy=pts_xy,
            center_lat=lat0, center_lng=lng0,
            base_scale_m_per_unit=scale_m_per_unit,
            graph_dist_m=int(opts.get("graph_dist_m", graph_dist_m)),
            rot_min_deg=float(opts.get("rot_min_deg", -30)),
            rot_max_deg=float(opts.get("rot_max_deg", 30)),
            rot_step_deg=float(opts.get("rot_step_deg", 5)),
            scale_min_ratio=float(opts.get("scale_min_ratio", 0.9)),
            scale_max_ratio=float(opts.get("scale_max_ratio", 1.1)),
            scale_step=float(opts.get("scale_step", 0.05)),
            shift_radius_m=float(opts.get("shift_radius_m", 200)),
            shift_step_m=float(opts.get("shift_step_m", 50)),
        )
        fit_params = fit.get("best_params")
        coords = fit.get("best_coords_lnglat") or []
        if len(coords) < 2:
            # free_fit 실패 → 시작점 고정 폴백
            coords = _xy_to_lnglat_scaled(pts_xy, lat0, lng0, scale_m_per_unit,
                                          rotation_deg=rotation_deg, center=True)
            used_align_mode = "start_locked(fallback)"
            fallback_used = True
    else:
        coords = _xy_to_lnglat_scaled(pts_xy, lat0, lng0, scale_m_per_unit,
                                      rotation_deg=rotation_deg, center=True)

    # -------- 맵매칭 + 후보정 루프 --------
    matched_flag = False
    if do_match:
        coords_mm, length_m = map_match_osmnx(
            coords_lnglat=coords,
            center_lat=lat0, center_lng=lng0,
            graph_dist_m=graph_dist_m, sample_step_m=sample_step_m
        )

        # 목표거리 수렴 루프
        iter_count = 0
        MIN_SCALE, MAX_SCALE = scale_m_per_unit * 0.1, scale_m_per_unit * 10.0
        while length_m > 0 and abs(length_m - target_m) / target_m > tol_ratio and iter_count < max_iter:
            iter_count += 1
            ratio = target_m / max(length_m, 1.0)
            scale_m_per_unit = max(MIN_SCALE, min(MAX_SCALE, scale_m_per_unit * ratio))
            coords = _xy_to_lnglat_scaled(pts_xy, lat0, lng0, scale_m_per_unit,
                                          rotation_deg=rotation_deg, center=True)
            coords_mm, length_m = map_match_osmnx(
                coords_lnglat=coords,
                center_lat=lat0, center_lng=lng0,
                graph_dist_m=graph_dist_m, sample_step_m=sample_step_m
            )

        if len(coords_mm) >= 2:
            coords_final = coords_mm
            final_length = length_m
            matched_flag = True
        else:
            coords_final = coords
            final_length = _poly_len_m(coords_final)
            matched_flag = False
    else:
        coords_final = coords
        final_length = _poly_len_m(coords_final)

    # -------- 응답 --------
    # --- 응답 (시각화용 포함) ---
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "name": f"Template route ~{target_km:.1f}km",
                "matched": matched_flag,
                "align_mode": used_align_mode,
                "fallback_used": fallback_used,
                "fit_params": fit_params
            },
            "geometry": {"type": "LineString", "coordinates": coords_final}
        }]
}

# ⚡ 추가: 템플릿 / free-fit / 최종 맵매칭 선을 모두 반환
    return jsonify({
        "ok": True,
        "data": {
            "geojson": geojson,
            "metrics": {
                "target_km": target_km,
                "route_length_m": final_length,
                "nodes": len(coords_final),
                "scale_m_per_unit": scale_m_per_unit
            },
            # --- 여기 추가 ---
            "template_points": [
                [lng0, lat0] for (lng0, lat0) in _xy_to_lnglat_scaled(
                    pts_xy, lat0, lng0, scale_m_per_unit,
                    rotation_deg=rotation_deg, center=True
                )
            ],
            "route_points": coords if do_match else [],
            "final_points": coords_final
        }
    })
