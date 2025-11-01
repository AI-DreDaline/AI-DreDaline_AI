from __future__ import annotations
from flask import Blueprint, jsonify, request
from .utils import ASSETS_SVG_DIR
from app.services.svg_service import parse_svg_inline
import math
from adra_core.mapmatch import map_match_osmnx


bp = Blueprint("api", __name__)

# -------------------- basic --------------------

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

    # 중심 정렬 (시작점 주변에 모양을 배치)
    if center:
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        pts = [(x - cx, y - cy) for x, y in pts]

    # 회전(도 단위)
    if rotation_deg:
        th = math.radians(rotation_deg)
        c, s = math.cos(th), math.sin(th)
        pts = [(c*x - s*y, s*x + c*y) for x, y in pts]

    # 스케일 → 위경도
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
      "template_name": "star.svg" | (또는 "svg": "<svg ...>"),
      "options": {
        "resample_m": 5.0,
        "simplify_tolerance": 0.5,
        "rotation_deg": 0.0,
        "map_match": true,
        "graph_dist_m": 3000,
        "sample_step_m": 60,
        "retune_tolerance": 0.05,   # 목표 대비 허용 오차(비율) 5%
        "retune_max_iter": 3        # 재스케일-맵매칭 반복 횟수
      }
    }
    """
    # -------- 입력/파라미터 --------
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": {"code": 400, "message": "Invalid JSON"}}), 400

    start = data.get("start_point") or {}
    if "lat" not in start or "lng" not in start:
        return jsonify({"ok": False, "error": {"code": 400, "message": "start_point.lat and start_point.lng are required"}}), 400

    try:
        target_km = float(data.get("target_km", 2.0))
    except Exception:
        return jsonify({"ok": False, "error": {"code": 400, "message": "target_km must be a number"}}), 400
    if target_km <= 0:
        return jsonify({"ok": False, "error": {"code": 400, "message": "target_km must be > 0"}}), 400

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
    do_match       = bool(opts.get("map_match", True))
    graph_dist_m   = int(opts.get("graph_dist_m", 3000))
    sample_step_m  = int(opts.get("sample_step_m", 60))
    tol_ratio      = float(opts.get("retune_tolerance", 0.05))   # 5%
    max_iter       = int(opts.get("retune_max_iter", 3))

    # -------- SVG → XY --------
    pts_xy = parse_svg_inline(svg_text, resample_m=resample, simplify_tolerance=simplify_tol)
    if len(pts_xy) < 2:
        return jsonify({"ok": False, "error": {"code": 422, "message": "SVG parsing returned too few points"}}), 422

    L_xy = _poly_len_xy(pts_xy)
    if L_xy <= 0:
        return jsonify({"ok": False, "error": {"code": 422, "message": "Invalid SVG polyline length"}}), 422

    # SVG 'unit' → meter 스케일
    target_m = target_km * 1000.0
    scale_m_per_unit = target_m / L_xy

    # -------- XY → 위경도 (pre-match) --------
    lat0 = float(start["lat"])
    lng0 = float(start["lng"])
    coords = _xy_to_lnglat_scaled(pts_xy, lat0, lng0, scale_m_per_unit, rotation_deg=rotation_deg, center=True)

    # -------- 맵매칭 + 후보정 루프 --------
    if do_match:
        # 1차 맵매칭
        coords_mm, length_m = map_match_osmnx(
            coords_lnglat=coords,
            center_lat=lat0,
            center_lng=lng0,
            graph_dist_m=graph_dist_m,
            sample_step_m=sample_step_m
        )

        # 거리 오차가 크면 스케일 재조정 + 재맵매칭 반복
        iter_count = 0
        # 안전장치: 스케일 폭주 방지
        MIN_SCALE, MAX_SCALE = scale_m_per_unit * 0.1, scale_m_per_unit * 10.0

        while length_m > 0 and abs(length_m - target_m) / target_m > tol_ratio and iter_count < max_iter:
            iter_count += 1
            # 비례 조정
            ratio = target_m / max(length_m, 1.0)
            scale_m_per_unit = max(MIN_SCALE, min(MAX_SCALE, scale_m_per_unit * ratio))

            # 새 스케일로 좌표 재계산
            coords = _xy_to_lnglat_scaled(pts_xy, lat0, lng0, scale_m_per_unit, rotation_deg=rotation_deg, center=True)

            # 재맵매칭
            coords_mm, length_m = map_match_osmnx(
                coords_lnglat=coords,
                center_lat=lat0,
                center_lng=lng0,
                graph_dist_m=graph_dist_m,
                sample_step_m=sample_step_m
            )

        # 최종 좌표/길이 선택
        coords_final = coords_mm if coords_mm else coords
        final_length = length_m if coords_mm else _poly_len_m(coords_final)

    else:
        # 맵매칭 생략 시: 하버사인으로 길이 계산
        coords_final = coords
        final_length = _poly_len_m(coords_final)

    # -------- 응답 --------
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "name": f"Template route ~{target_km:.1f}km",
                "matched": bool(do_match)
            },
            "geometry": {"type": "LineString", "coordinates": coords_final}
        }]
    }

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
            "template_points": pts_xy,
            "route_points": [[lat, lng] for (lng, lat) in coords_final]
        }
    })

 
 
