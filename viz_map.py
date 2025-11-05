# viz_map.py
from __future__ import annotations
import json, time, pathlib, requests, folium

# === 설정 ===
API = "http://127.0.0.1:5001/routes/generate"   # 서버가 다른 포트면 바꿔줘
FILES = [
    "tests/sample_request_8km.json",
    "tests/sample_request_10km.json",
    "tests/sample_request_15km.json",
]
OUT_HTML = "viz_routes.html"

def post_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    r = requests.post(API, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()

def mid_point(coords):
    # coords: [[lng,lat], ...]
    if not coords: return (33.4996,126.5312)  # fallback (lat,lng)
    lats = [lat for _, lat in coords]
    lngs = [lng for lng, _ in coords]
    return (sum(lats)/len(lats), sum(lngs)/len(lngs))

def km(m): return round(m/1000.0, 3)

def make_popup(metrics: dict, props: dict) -> str:
    rows = []
    for k in ("target_km","route_length_m","nodes","scale_m_per_unit"):
        if k in metrics:
            rows.append(f"<tr><td>{k}</td><td>{metrics[k]}</td></tr>")
    for k in ("align_mode","fallback_used","matched","name"):
        if k in props:
            rows.append(f"<tr><td>{k}</td><td>{props[k]}</td></tr>")
    return "<table>" + "".join(rows) + "</table>"

def add_route_layer(m: folium.Map, name: str, coords: list, color: str, popup_html: str):
    fg = folium.FeatureGroup(name=name, show=True)
    if coords:
        folium.PolyLine([(lat, lng) for (lng, lat) in coords],
                        weight=5, opacity=0.85, color=color).add_to(fg)
        folium.Marker((coords[0][1], coords[0][0]),
                      tooltip=f"{name} start").add_to(fg)
        folium.Marker((coords[-1][1], coords[-1][0]),
                      tooltip=f"{name} end").add_to(fg)
        folium.Popup(popup_html, max_width=350).add_to(fg)
    fg.add_to(m)

def main():
    results = []
    for path in FILES:
        try:
            res = post_json(path)
            assert res.get("ok") is True
            data = res["data"]
            feat = data["geojson"]["features"][0]
            coords = feat["geometry"]["coordinates"]
            props = feat["properties"]
            metrics = data["metrics"]
            results.append({
                "path": path,
                "coords": coords,
                "props": props,
                "metrics": metrics,
                "center": mid_point(coords),
            })
            time.sleep(0.2)
        except Exception as e:
            print(f"[!] Failed: {path} -> {e}")

    if not results:
        raise SystemExit("No results to visualize. Is the API running?")

    # 지도 중심: 첫 결과의 중간점
    center_latlng = results[0]["center"]
    m = folium.Map(location=center_latlng, zoom_start=13, control_scale=True)

    # 컬러 팔레트 (간단히 구분만)
    colors = ["#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#ff7f0e"]

    for i, r in enumerate(results):
        name = pathlib.Path(r["path"]).stem.replace("sample_request_", "")
        km_len = km(r["metrics"].get("route_length_m", 0))
        layer_name = f"{name}  •  {km_len} km"
        popup = make_popup(r["metrics"], r["props"])
        add_route_layer(m, layer_name, r["coords"], colors[i % len(colors)], popup)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(OUT_HTML)
    print(f"[OK] Saved → {OUT_HTML}")

if __name__ == "__main__":
    main()
