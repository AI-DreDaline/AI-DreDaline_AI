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
│   ├── navigation.py       # Navigation guidance with turns and km checkpoints
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

pip install -r requirements.txt
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
  "start_point": { "lat": 33.4996, "lng": 126.5312},
  "target_km": 8.0,
  "options": {
    "svg_path_index": "auto",
    "svg_samples_per_seg": 80,
    "svg_simplify": 0.0,
    "svg_flip_y": true,
    "canvas_box_frac": 0.60,
    "global_rot_deg": 0,
    "sample_step_m": 60,
    "min_wp_gap_m": 12,
    "graph_radius_m": 5000,
    "return_to_start": true,
    "tol_ratio": 0.08
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

<pre>
 curl -sS -X POST http://127.0.0.1:5001/routes/generate \
 -H "Content-Type: application/json" \
 -d @samples/req_8km.json \
 > result_with_guidance.json

cat result_with_guidance.json | jq '.data.guidance.guidance_points'
</pre>

## 🧭 Guidance_Point Structure

<pre>
{
  "sequence": 1,
  "type": "turn",
  "lat": 33.49907399999999,
  "lng": 126.5315989,
  "direction": "left",
  "angle": -92.7,
  "distance_from_start": 44.4,
  "distance_to_next": 104.4,
  "guidance_id": "TURN_LEFT_50",
  "trigger_distance": 50
}
</pre>

## 📚Guidance Templete
<pre>
GUIDANCE_TEMPLATES = [

    # 기본 회전
    ('TURN_LEFT_15',  '15미터 앞에서 좌회전하세요', 'turn'),
    ('TURN_LEFT_50',  '50미터 앞에서 좌회전하세요', 'turn'),
    ('TURN_RIGHT_15', '15미터 앞에서 우회전하세요', 'turn'),
    ('TURN_RIGHT_50', '50미터 앞에서 우회전하세요', 'turn'),
    ('U_TURN_15',     '15미터 앞에서 유턴하세요', 'turn'),
    ('U_TURN_50',     '50미터 앞에서 유턴하세요', 'turn'),

    # 직진
    ('GO_STRAIGHT_NEXT', '다음 안내까지 직진하세요', 'straight'),

    # 약 / 급 회전
    ('SLIGHT_LEFT',  '약간 왼쪽으로 이동하세요', 'slight'),
    ('SLIGHT_RIGHT', '약간 오른쪽으로 이동하세요', 'slight'),
    ('SHARP_LEFT',   '급하게 좌회전하세요', 'sharp'),
    ('SHARP_RIGHT',  '급하게 우회전하세요', 'sharp'),

    # 러닝 이벤트
    ('RUN_START',  '러닝을 시작합니다. 몸의 긴장을 풀고 적절한 페이스로 출발해보세요', 'event'),
    ('RUN_FINISH', '수고하셨습니다. 러닝을 완료했습니다', 'event'),

    # 진행률
    ('PROGRESS_30', '30% 지점에 도달했습니다. 잘하고 있어요', 'progress'),
    ('PROGRESS_50', '절반 지점에 도착했습니다. 페이스를 유지해보세요', 'progress'),
    ('PROGRESS_80', '80% 지점입니다. 조금만 더 힘내세요', 'progress'),

    # 체크포인트
    ('CHECKPOINT_ARRIVED', '체크포인트에 도착했습니다', 'checkpoint'),
    ('ROUTE_COMPLETE', '경로를 모두 완료했습니다. 고생하셨습니다', 'checkpoint'),

    # 방향 전환 후속 (선택)
    ('TURN_AFTER_LEFT_STRAIGHT',  '좌회전 후 직진하세요', 'turn'),
    ('TURN_AFTER_RIGHT_STRAIGHT', '우회전 후 직진하세요', 'turn'),

    # 코스 이탈
    ('OFF_ROUTE', '경로에서 벗어났습니다. 지도를 확인해주세요', 'alert'),
]
</pre>

