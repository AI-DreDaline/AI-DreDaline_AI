from __future__ import annotations
from flask import Blueprint, request, jsonify
from app.services.svg_service import parse_svg
from app.services.match_service import map_match_points
from app.services.metrics_service import (
    resample_equal_count, average_and_max_distance_m, similarity_score
)

bp = Blueprint("routes_generate", __name__, url_prefix="/routes")

def _bad(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code

@bp.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        return _bad("Invalid JSON body")

    for k in ["svg_text","target_km","start_lng","start_lat"]:
        if k not in data:
            return _bad(f"Missing field: {k}")

    svg_text = str(data["svg_text"])
    if "<svg" not in svg_text:
        return _bad("svg_text must contain an <svg> tag")

    try:
        target_km  = float(data["target_km"])
        start_lng  = float(data["start_lng"])
        start_lat  = float(data["start_lat"])
    except Exception:
        return _bad("target_km/start_lng/start_lat must be numeric")

    if not (0.5 <= target_km <= 50.0):
        return _bad("target_km out of range (0.5~50.0)")

    # --- params ---
    resample_m     = float(data.get("resample_m", 5.0))
    step_m         = float(data.get("step_m", 5.0))
    graph_radius_m = int(data.get("graph_radius_m", 6000))
    match_step_m   = float(data.get("match_step_m", 130.0))
    max_seg_m      = float(data.get("max_seg_m", 1000.0))

    auto_tune      = bool(data.get("auto_tune", True))
    tune_iters     = int(data.get("tune_iters", 3))
    tune_tol_pct   = float(data.get("tune_tol_pct", 0.08))

    # --- angle search options ---
    auto_angle_search = bool(data.get("auto_angle_search", True))
    angle_candidates  = data.get("angle_candidates") or list(range(0, 360, 30))  # 0,30,...,330

    def run_once(cur_target_km: float, rotate_deg: float):
        """한 번의 SVG→매칭→메트릭 실행"""
        tmpl = parse_svg(
            svg_text=svg_text,
            target_km=cur_target_km,
            start_xy=(start_lng, start_lat),
            resample_m=resample_m,
            rotate_deg=rotate_deg,
            step_m=step_m,
        )
        tmpl_pts = tmpl["points"]

        mm = map_match_points(
            pts_lnglat=tmpl_pts,
            center_lat=start_lat,
            center_lng=start_lng,
            graph_radius_m=graph_radius_m,
            match_step_m=match_step_m,
            max_seg_m=max_seg_m,
        )

        A = resample_equal_count(tmpl_pts, 200)
        B = resample_equal_count(mm.get("route_coords_lnglat", []), 200) if mm.get("route_coords_lnglat") else []
        if A and B:
            avg_d, max_d = average_and_max_distance_m(A, B)
            sim = similarity_score(avg_d)
        else:
            avg_d, max_d, sim = float("inf"), float("inf"), 0.0

        route_len_m = float(mm.get("route_length_m", 0.0))
        target_m    = cur_target_km * 1000.0
        err_m       = route_len_m - target_m
        err_pct     = (err_m / target_m) if target_m > 0 else 0.0

        return {
            "ok": True,
            "matched": bool(mm.get("matched", False)),
            "target_km": cur_target_km,
            "rotate_deg": rotate_deg,
            "template_length_m": float(tmpl["template_length_m"]),
            "scale_m_per_unit": float(tmpl["scale_m_per_unit"]),
            "route_length_m": route_len_m,
            "route_coords_lnglat": mm.get("route_coords_lnglat", []),
            "route_nodes": mm.get("route_nodes", []),
            "similarity": {
                "avg_dist_m": None if avg_d == float("inf") else round(avg_d, 2),
                "max_dist_m": None if max_d == float("inf") else round(max_d, 2),
                "score_0to100": sim,
            },
            "length_error": {
                "error_m": round(err_m, 2),
                "error_pct": round(err_pct * 100.0, 2),
            },
        }

    # --- length auto-tune + angle search ---
    best = None
    cur_target = target_km
    for _ in range(max(1, tune_iters)):
        # 각도 후보 평가
        results = []
        if auto_angle_search:
            for ang in angle_candidates:
                res = run_once(cur_target, ang)
                # 유사도 ↑, 길이오차 ↓ 를 함께 고려한 스코어
                penalty = abs(res["length_error"]["error_pct"])  # %
                score = res["similarity"]["score_0to100"] - 0.6 * penalty
                results.append((score, res))
            results.sort(key=lambda x: x[0], reverse=True)
            best_iter = results[0][1]
        else:
            best_iter = run_once(cur_target, float(data.get("rotate_deg", 0.0)))

        best = best_iter
        # 길이 수렴 체크
        if not auto_tune or abs(best["length_error"]["error_pct"]) <= (tune_tol_pct * 100.0):
            break
        # 다음 타깃 스케일 보정
        route_len = max(1e-6, best["route_length_m"])
        cur_target = cur_target * ( (cur_target*1000.0) / route_len )


    # 반환
    best["iterations"] = tune_iters
    return jsonify(best), 200
