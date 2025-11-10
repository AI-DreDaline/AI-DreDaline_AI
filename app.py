# app.py
from __future__ import annotations
from pathlib import Path
from typing import Optional
import json

from flask import Flask, request, jsonify
from pydantic import BaseModel, Field, ValidationError
import osmnx as ox

from algo.notebook_port import (
    svg_to_polyline,
    place_svg_in_graph_bbox,
    load_graph_cached,
    project_graph,
    binary_scale_fit,
    line_length_km,
)

# ------------------------
# Settings
# ------------------------
class Settings:
    HOST = "127.0.0.1"
    PORT = 5001
    DEBUG = True

    DATA_DIR = Path("data")
    SVG_DIR = DATA_DIR / "svg"
    CACHE_DIR = DATA_DIR / "cache"
    GENERATED_DIR = DATA_DIR / "generated"

SET = Settings()
SET.DATA_DIR.mkdir(parents=True, exist_ok=True)
SET.SVG_DIR.mkdir(parents=True, exist_ok=True)
SET.CACHE_DIR.mkdir(parents=True, exist_ok=True)
SET.GENERATED_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)

# ------------------------
# Schemas
# ------------------------
class StartPoint(BaseModel):
    lat: float
    lng: float

class Options(BaseModel):
    # --- SVG / placement ---
    svg_path_index: str | int = Field(default="auto")
    svg_samples_per_seg: int = Field(default=80)
    svg_simplify: float = Field(default=0.0)
    svg_flip_y: bool = Field(default=True)
    canvas_box_frac: float = Field(default=0.48)
    global_rot_deg: float = Field(default=0.0)

    # --- sampling / graph ---
    sample_step_m: float = Field(default=50.0)
    min_wp_gap_m: float = Field(default=10.0)
    graph_radius_m: int = Field(default=3500)
    return_to_start: bool = Field(default=True)

    # --- fitting ---
    tol_ratio: float = Field(default=0.05)
    iters: int = Field(default=16)

    # --- shape preservation (new) ---
    shape_bias_lambda: float = Field(default=0.03, ge=0.0)  # 0.02~0.06 권장
    anchor_count: int = Field(default=12, ge=3, le=40)
    use_anchors: bool = Field(default=True)

    # --- start-near placement + connector (new) ---
    connect_from_start: bool = Field(default=True)
    max_connector_m: float = Field(default=600.0, ge=0.0)
    proximity_alpha: float = Field(default=0.6, ge=0.0, le=1.0)
    proximity_max_shift_m: float = Field(default=1500.0, ge=0.0)

class GeneratePayload(BaseModel):
    template_name: str
    start_point: StartPoint
    target_km: float = Field(gt=0)
    options: Optional[Options] = None
    save_geojson: Optional[bool] = False

# ------------------------
# Helpers
# ------------------------
def feature_from_line(line_proj, nodes_proj_crs, props):
    # project to WGS84
    line_ll = ox.projection.project_geometry(line_proj, crs=nodes_proj_crs, to_crs="EPSG:4326")[0]
    coords = list(line_ll.coords)  # [(lon,lat), ...]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": props,
    }

# ------------------------
# Routes
# ------------------------
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

    # 1) Graph load (cached) & project
    G = load_graph_cached(sp.lat, sp.lng, opt.graph_radius_m, SET.CACHE_DIR)
    Gp = project_graph(G)
    nodes_proj, edges_proj = ox.graph_to_gdfs(Gp)

    # 2) SVG → normalized polyline → place in graph bbox
    shape_norm = svg_to_polyline(
        svg_path=svg_path,
        path_index=opt.svg_path_index,
        samples_per_seg=opt.svg_samples_per_seg,
        simplify=opt.svg_simplify,
        flip_y=opt.svg_flip_y,
    )
    mapped = place_svg_in_graph_bbox(
        shape_norm=shape_norm,
        nodes_proj_gdf=nodes_proj,
        canvas_frac=opt.canvas_box_frac,
        global_rot_deg=opt.global_rot_deg,
    )

    # 3) Fit (auto bracket + shape-bias + anchors + start-near/connector)
    fit = binary_scale_fit(
        G_proj=Gp,
        nodes_proj_gdf=nodes_proj,
        mapped_base=mapped,
        target_km=payload.target_km,
        tol_ratio=opt.tol_ratio,
        step_m=opt.sample_step_m,
        min_gap_m=opt.min_wp_gap_m,
        center_lat=sp.lat,
        center_lng=sp.lng,
        return_to_start=opt.return_to_start,
        iters=opt.iters,
        # new controls
        shape_bias_lambda=opt.shape_bias_lambda,
        anchor_count=opt.anchor_count,
        use_anchors=opt.use_anchors,
        connect_from_start=opt.connect_from_start,
        max_connector_m=opt.max_connector_m,
        proximity_alpha=opt.proximity_alpha,
        proximity_max_shift_m=opt.proximity_max_shift_m,
    )

    # server-side logs (useful for tuning)
    try:
        print("[GEN] template_name:", payload.template_name)
        # Pydantic v2
        eff_opts = opt.model_dump() if hasattr(opt, "model_dump") else opt.__dict__
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

    metrics = {
        "nodes": len(fit.route_line_proj.coords),
        "route_length_m": round(float(fit.actual_km * 1000), 3),
        "target_km": float(payload.target_km)
    }

    saved_path = None
    if payload.save_geojson:
        out_path = SET.GENERATED_DIR / f"route_{int(round(payload.target_km))}km.geojson"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False, indent=2)
        saved_path = str(out_path)

    return jsonify({"ok": True, "data": {"metrics": metrics, "geojson": fc, "saved": saved_path}}), 200


if __name__ == "__main__":
    app.run(host=SET.HOST, port=SET.PORT, debug=SET.DEBUG)
