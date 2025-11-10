# 🧠 AdraDaline Algorithm Server

Generate GPS-art running routes on real roads from SVG templates.

Input: start point (lat/lng), target distance (km), template (e.g., star.svg).

Output: GeoJSON LineString route (map-matched, distance-fit, shape-preserving).

## 📁 Project Structure

<pre> 
AI-DreDaline_AI/
├── app.py
├── algo/
│   ├── __init__.py
│   ├── context.py          # Settings, Options, payload models, RouteContext
│   ├── svg_loader.py       # SVG → polyline (normalized), multipath support
│   ├── placement.py        # Placement/rotation, start-near proximity, scaling
│   ├── routing.py          # Shape-bias costs, anchors, connector routing
│   ├── scaling.py          # Binary scale fit to target_km
│   ├── mapmatch.py         # Graph load/cache, projection helpers
│   └── utils.py            # Densify/thin points, nearest-node utils, km length
├── data/
│   ├── svg/                # Put templates here (star.svg, heart.svg, …)
│   ├── cache/              # OSM graph cache (graph_*.pkl)
│   └── generated/          # Exported GeoJSON routes
└── README.md
 </pre>

## 🚀 Setup
1) Python & venv
<pre> 
# Python 3.12+
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)

pip install -U pip
pip install Flask pydantic osmnx networkx shapely svgpathtools numpy
</pre>

2) Folder
<pre>
mkdir -p data/svg data/cache data/generated
# put your SVGs into data/svg (e.g., star.svg, heart.svg)

</pre>

3) Run
<pre>
python app.py
# http://127.0.0.1:5001
</pre>

## ⚙️ API
1) POST /routes/generate — Generate route from SVG
Request body
<pre>
{
  "template_name": "star.svg",
  "start_point": { "lat": 33.4996, "lng": 126.5312 },
  "target_km": 8.0,
  "options": {
    "svg_path_index": "auto",
    "svg_samples_per_seg": 80,
    "svg_simplify": 0.0,
    "svg_flip_y": true,

    "canvas_box_frac": 0.75,
    "global_rot_deg": 15,

    "sample_step_m": 60,
    "min_wp_gap_m": 12,
    "graph_radius_m": 7000,
    "return_to_start": true,

    "tol_ratio": 0.08,
    "iters": 16,

    "shape_bias_lambda": 0.045,
    "anchor_count": 10,
    "use_anchors": true,

    "connect_from_start": true,
    "max_connector_m": 450,

    "proximity_alpha": 0.75,
    "proximity_max_shift_m": 2000
  },
  "save_geojson": true
}
</pre>
Response (trimmed)
<pre>
{
  "ok": true,
  "data": {
    "metrics": { "nodes": 340, "route_length_m": 7998.1, "target_km": 8.0 },
    "geojson": { "type": "FeatureCollection", "features": [ { "geometry": { "type": "LineString", "coordinates": [[126.53,33.49], ...] }, "properties": { "template": "star.svg", "align_mode": "free_fit+anchors", "matched": true, "scale_used": 1.382, "name": "Template route ~8.0km" } } ] },
    "saved": "data/generated/route_8km.geojson"
  }
}
</pre>
cURL
<pre>
curl -sS -X POST http://127.0.0.1:5001/routes/generate \
  -H "Content-Type: application/json" \
  -d @req_star_8k.json | jq '.ok, .data.metrics, .data.geojson.features[0].properties'
</pre>
