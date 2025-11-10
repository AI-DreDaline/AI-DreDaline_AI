# app.py (변경된 import들 위주)
from __future__ import annotations
from pathlib import Path
from flask import Flask, request, jsonify
from pydantic import ValidationError
import json
import osmnx as ox

from algo.context import Settings, GeneratePayload, Options
from algo.mapmatch import load_graph_cached, project_graph, graph_to_gdfs, project_to_wgs84
from algo.svg_loader import svg_to_polyline
from algo.placement import place_svg_in_graph_bbox
from algo.scaling import binary_scale_fit

SET = Settings(); SET.ensure()
app = Flask(__name__)

def feature_from_line(line_proj, nodes_proj_crs, props):
    line_ll = project_to_wgs84(line_proj, nodes_proj_crs)
    coords = list(line_ll.coords)
    return {"type":"Feature","geometry":{"type":"LineString","coordinates":coords},"properties":props}

@app.post("/routes/generate")
def generate_route():
    try:
        payload = GeneratePayload.model_validate(request.get_json(force=True))
    except ValidationError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    sp = payload.start_point
    opt = payload.options or Options()

    svg_path = (SET.SVG_DIR / payload.template_name).resolve()
    if not svg_path.exists():
        return jsonify({"ok": False, "error": f"SVG not found: {svg_path.name}"}), 404

    G = load_graph_cached(sp.lat, sp.lng, opt.graph_radius_m, SET.CACHE_DIR)
    Gp = project_graph(G)
    nodes_proj, edges_proj = graph_to_gdfs(Gp)

    shape_norm = svg_to_polyline(svg_path=svg_path, path_index=opt.svg_path_index,
                                 samples_per_seg=opt.svg_samples_per_seg, simplify=opt.svg_simplify, flip_y=opt.svg_flip_y)
    mapped = place_svg_in_graph_bbox(shape_norm=shape_norm, nodes_proj_gdf=nodes_proj,
                                     canvas_frac=opt.canvas_box_frac, global_rot_deg=opt.global_rot_deg)

    fit = binary_scale_fit(G_proj=Gp, nodes_proj_gdf=nodes_proj, mapped_base=mapped,
                           target_km=payload.target_km, tol_ratio=opt.tol_ratio,
                           step_m=opt.sample_step_m, min_gap_m=opt.min_wp_gap_m,
                           center_lat=sp.lat, center_lng=sp.lng, return_to_start=opt.return_to_start, iters=opt.iters,
                           shape_bias_lambda=opt.shape_bias_lambda, anchor_count=opt.anchor_count, use_anchors=opt.use_anchors,
                           connect_from_start=opt.connect_from_start, max_connector_m=opt.max_connector_m,
                           proximity_alpha=opt.proximity_alpha, proximity_max_shift_m=opt.proximity_max_shift_m)

    # logs
    try:
        eff_opts = opt.model_dump() if hasattr(opt, "model_dump") else opt.__dict__
        print("[GEN] template_name:", payload.template_name)
        print("[GEN] effective options:", eff_opts)
        print("[GEN] result_km:", round(fit.actual_km, 3), "scale_used:", round(fit.scale_used, 3))
    except Exception:
        pass

    props = {
        "template": payload.template_name,
        "align_mode": "free_fit+anchors",
        "matched": True,
        "fallback_used": False,
        "scale_used": round(fit.scale_used, 3),
        "name": f"Template route ~{payload.target_km:.1f}km"
    }
    feat = feature_from_line(fit.route_line_proj, nodes_proj.crs, props)
    fc = {"type": "FeatureCollection", "features": [feat]}
    metrics = {"nodes": len(fit.route_line_proj.coords), "route_length_m": round(float(fit.actual_km*1000), 3), "target_km": float(payload.target_km)}

    saved_path = None
    if payload.save_geojson:
        out_path = SET.GENERATED_DIR / f"route_{int(round(payload.target_km))}km.geojson"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False, indent=2)
        saved_path = str(out_path)

    return jsonify({"ok": True, "data": {"metrics": metrics, "geojson": fc, "saved": saved_path}}), 200

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
