# adra_core/freefit.py
from __future__ import annotations
from typing import List, Tuple
import math
import osmnx as ox
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

def _meters_to_deg(lat_deg: float, dx_m: float, dy_m: float):
    R = 6371000.0
    lat_rad = math.radians(lat_deg)
    dlat = (dy_m / R) * (180.0 / math.pi)
    dlng = (dx_m / (R * math.cos(lat_rad))) * (180.0 / math.pi)
    return dlng, dlat

def _xy_to_lnglat_scaled_rot_shift(
    pts_xy: List[Tuple[float, float]],
    center_lat: float, center_lng: float,
    scale_m_per_unit: float,
    rotation_deg: float = 0.0,
    shift_dx_m: float = 0.0,
    shift_dy_m: float = 0.0,
    centerize: bool = True,
):
    """SVG xy → 위경도 (lng,lat) 좌표 변환 (스케일/회전/평행이동)"""
    if not pts_xy:
        return []
    pts = pts_xy[:]
    if centerize:
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        pts = [(x - cx, y - cy) for x, y in pts]
    if rotation_deg:
        th = math.radians(rotation_deg)
        c, s = math.cos(th), math.sin(th)
        pts = [(c * x - s * y, s * x + c * y) for x, y in pts]
    out = []
    for x, y in pts:
        dx_m, dy_m = x * scale_m_per_unit + shift_dx_m, y * scale_m_per_unit + shift_dy_m
        dlng, dlat = _meters_to_deg(center_lat, dx_m, dy_m)
        out.append((center_lng + dlng, center_lat + dlat))
    return out

def _build_edge_tree_projected(G_proj):
    edges = []
    for u, v, data in G_proj.edges(keys=False, data=True):
        if "geometry" in data:
            geom = data["geometry"]
        else:
            x1, y1 = G_proj.nodes[u]["x"], G_proj.nodes[u]["y"]
            x2, y2 = G_proj.nodes[v]["x"], G_proj.nodes[v]["y"]
            geom = LineString([(x1, y1), (x2, y2)])
        edges.append(geom)
    return STRtree(edges), edges

def _sample_every(seq: List, max_samples: int = 250) -> List:
    if len(seq) <= max_samples:
        return seq
    step = max(1, len(seq) // max_samples)
    return seq[::step]

def _frange(a: float, b: float, step: float, include_end: bool = False):
    vals = []
    if step == 0:
        return [a]
    x = a
    if a < b:
        while x < b:
            vals.append(round(x, 6))
            x += abs(step)
    else:
        while x > b:
            vals.append(round(x, 6))
            x -= abs(step)
    if include_end and (not vals or vals[-1] != b):
        vals.append(round(b, 6))
    return vals

def _mean_nearest_distance(points_xy: List[Tuple[float, float]], edge_tree: STRtree) -> float:
    """평균 최근접 거리 계산 (None/NaN 방어)"""
    if not points_xy:
        return float("inf")
    total = 0.0
    count = 0
    for x, y in points_xy:
        p = Point(x, y)
        try:
            geom = edge_tree.nearest(p)
            if geom is None:
                continue
            d = p.distance(geom)
            if math.isnan(d):
                continue
            total += d
            count += 1
        except Exception:
            continue
    if count == 0:
        return float("inf")
    return total / count

def free_fit_search(
    pts_xy: List[Tuple[float, float]],
    center_lat: float, center_lng: float,
    base_scale_m_per_unit: float,
    *,
    graph_dist_m: int = 3000,
    rot_min_deg: float = -30.0,
    rot_max_deg: float = 30.0,
    rot_step_deg: float = 5.0,
    scale_min_ratio: float = 0.9,
    scale_max_ratio: float = 1.1,
    scale_step: float = 0.05,
    shift_radius_m: float = 200.0,
    shift_step_m: float = 50.0,
) -> dict:
    """지도 위 (스케일/회전/평행이동) 그리드 탐색 → 평균 최근접 거리 최소 조합"""
    # 그래프 로드 + 투영
    G = ox.graph_from_point((center_lat, center_lng),
                            dist=graph_dist_m, network_type="walk", simplify=True)
    from osmnx import projection, distance
    G = distance.add_edge_lengths(G)
    Gp = projection.project_graph(G)
    edge_tree, _ = _build_edge_tree_projected(Gp)
    target_crs = Gp.graph.get("crs")

    rot_vals   = _frange(rot_min_deg, rot_max_deg, rot_step_deg)
    scale_vals = _frange(scale_min_ratio, scale_max_ratio, scale_step, include_end=True)
    shift_vals = _frange(-shift_radius_m, shift_radius_m, shift_step_m)

    best_cost = float("inf")
    best_params = None
    best_coords_ll = None

    # 탐색 루프
    from osmnx.projection import project_geometry
    for rot in rot_vals:
        for s_ratio in scale_vals:
            scale_m = base_scale_m_per_unit * s_ratio
            coords_ll = _xy_to_lnglat_scaled_rot_shift(
                pts_xy, center_lat, center_lng,
                scale_m_per_unit=scale_m, rotation_deg=rot, centerize=True
            )
            line_ll = LineString(coords_ll)
            line_xy, _ = project_geometry(line_ll, to_crs=target_crs)
            pts_proj = _sample_every(list(line_xy.coords), max_samples=200)

            for dx in shift_vals:
                for dy in shift_vals:
                    shifted = [(x + dx, y + dy) for (x, y) in pts_proj]
                    cost = _mean_nearest_distance(shifted, edge_tree)
                    if cost < best_cost:
                        best_cost = cost
                        best_params = {"scale": scale_m, "rot_deg": rot, "dx_m": dx, "dy_m": dy}
                        best_coords_ll = _xy_to_lnglat_scaled_rot_shift(
                            pts_xy, center_lat, center_lng,
                            scale_m_per_unit=scale_m, rotation_deg=rot,
                            shift_dx_m=dx, shift_dy_m=dy, centerize=True
                        )

    if not best_coords_ll:
        return {"best_params": best_params or {}, "best_coords_lnglat": [], "graph_crs": target_crs}
    return {"best_params": best_params, "best_coords_lnglat": best_coords_ll, "graph_crs": target_crs}
