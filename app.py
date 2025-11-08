# app.py
from __future__ import annotations
from flask import Flask, request, jsonify
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, Dict, Any
from config import SETTINGS
from algo.svg_route import generate_route_from_svg

app = Flask(__name__)

class StartPoint(BaseModel):
    lat: float
    lng: float

class GenerateOptions(BaseModel):
    align_mode: str = Field(default=SETTINGS.DEFAULTS["align_mode"])
    map_match: bool = Field(default=SETTINGS.DEFAULTS["map_match"])
    graph_dist_m: int = Field(default=SETTINGS.DEFAULTS["graph_dist_m"])
    sample_step_m: float = Field(default=SETTINGS.DEFAULTS["sample_step_m"])
    resample_m: float = Field(default=SETTINGS.DEFAULTS["resample_m"])
    simplify_tolerance: float = Field(default=SETTINGS.DEFAULTS["simplify_tolerance"])

class GeneratePayload(BaseModel):
    template_name: str
    start_point: StartPoint
    target_km: float = Field(gt=0)
    options: Optional[GenerateOptions] = None

def _geojson_feature(coords_latlng, props):
    # GeoJSON 라인스트링 (lon,lat 순)
    line = [[lng, lat] for (lat, lng) in coords_latlng]
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": line},
        "properties": props,
    }

@app.post("/routes/generate")
def generate_route():
    try:
        payload = GeneratePayload.model_validate(request.get_json(force=True))
    except ValidationError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    svg_path = (SETTINGS.SVG_DIR / payload.template_name).resolve()
    if not svg_path.exists():
        return jsonify({"ok": False, "error": f"SVG not found: {svg_path.name}"}), 404

    options = (payload.options.model_dump() if payload.options else {})
    try:
        result = generate_route_from_svg(
            svg_path=svg_path,
            start_point=payload.start_point.model_dump(),
            target_km=payload.target_km,
            options=options,
        )
    except Exception as ex:
        return jsonify({"ok": False, "error": f"{type(ex).__name__}: {ex}"}), 500

    feature = _geojson_feature(result.coords_wgs84, result.properties)
    return jsonify({
        "ok": True,
        "data": {
            "metrics": result.metrics.__dict__,
            "geojson": {
                "type": "FeatureCollection",
                "features": [feature]
            }
        }
    })

if __name__ == "__main__":
    SETTINGS.DATA_DIR.mkdir(exist_ok=True)
    SETTINGS.SVG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host=SETTINGS.HOST, port=SETTINGS.PORT, debug=SETTINGS.DEBUG)
