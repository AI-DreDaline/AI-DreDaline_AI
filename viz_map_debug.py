# viz_map_debug.py
from __future__ import annotations
import json, pathlib, requests, folium, time

API = "http://127.0.0.1:5001/routes/generate"
FILES = [
    "tests/sample_request_8km.json",
    "tests/sample_request_10km.json",
    "tests/sample_request_15km.json",
]
OUT_HTML = "viz_routes_debug.html"

def post_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    r = requests.post(API, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()

def mid_point(coords):
    if not coords: return (33.4996, 126.5312)
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

def add_route_layer(m, name, coords, color, popup_html, weight=5, dash=False):
    fg = folium.FeatureGroup(name=name, show=True)
    if coords:
        folium.PolyLine(
            [(lat, lng) for (lng, lat) in coords],
            weight=weight, opacity=0.9, color=color,
            dash_array="10,6" if dash else None
        ).add_to(fg)
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
            coords_final = feat["geometry"]["coordinates"]
            props = feat["properties"]
            metrics = data["metrics"]
            coords_template = data.get("template_points", [])
            coords_route = data.get("route_points", [])
            results.append({
                "path": path,
                "coords_final": coords_final,
                "coords_template": coords_template,
                "coords_route": coords_route,
                "props": props,
                "metrics": metrics,
                "center": mid_point(coords_final),
            })
            time.sleep(0.3)
        except Exception as e:
            print(f"[!] Failed {path}: {e}")

    if not results:
        raise SystemExit("No results to visualize. API might not be running.")

    center_latlng = results[0]["center"]
    m = folium.Map(location=center_latlng, zoom_start=13, control_scale=True)
    palette = ["#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#ff7f0e"]

    for i, r in enumerate(results):
        name = pathlib.Path(r["path"]).stem.replace("sample_request_", "")
        color = palette[i % len(palette)]
        km_len = km(r["metrics"].get("route_length_m", 0))
        popup = make_popup(r["metrics"], r["props"])

        # 회색 점선: 템플릿
        if r["coords_template"]:
            add_route_layer(m, f"{name} - Template", r["coords_template"], "#777777", "Template (original SVG)", weight=2, dash=True)
        # 연한색: free-fit 정합 후
        if r["coords_route"]:
            add_route_layer(m, f"{name} - FreeFit", r["coords_route"], "#99ccff", "FreeFit adjusted", weight=3)
        # 진한색: 최종 맵매칭
        add_route_layer(m, f"{name} - Final", r["coords_final"], color, popup, weight=5)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(OUT_HTML)
    print(f"[OK] Saved → {OUT_HTML}")

if __name__ == "__main__":
    main()
