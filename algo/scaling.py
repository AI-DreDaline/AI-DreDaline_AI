# algo/scaling.py
from __future__ import annotations
from dataclasses import dataclass
from shapely.geometry import LineString, Point
from shapely.affinity import scale as shp_scale
import osmnx as ox
from .utils import line_length_km
from .routing import (
    build_shape_biased_costs, sample_anchors,
    route_via_anchors, route_via_shape
)
from .placement import place_shape_near_start, scale_shape

@dataclass
class FitResult:
    scale_used: float
    route_nodes: list[int]
    route_line_proj: LineString
    actual_km: float
    template_tuned_proj: LineString

def _route_length_km_try(G_proj, nodes_proj_gdf, base_line: LineString, scale: float,
                         step_m: float, min_gap_m: float, center_lat: float, center_lng: float,
                         return_to_start: bool, use_anchors: bool, anchor_count: int,
                         shape_bias_lambda: float, start_proj_point: Point,
                         connect_from_start: bool, max_connector_m: float,
                         proximity_alpha: float, proximity_max_shift_m: float):
    tuned = scale_shape(base_line, scale)
    tuned = place_shape_near_start(tuned, start_proj_point, alpha=proximity_alpha, max_shift_m=proximity_max_shift_m)
    build_shape_biased_costs(G_proj, nodes_proj_gdf, tuned, lam=shape_bias_lambda, attr_name="shape_cost")

    if use_anchors:
        anchors = sample_anchors(tuned, n=anchor_count)
        rn, rl = route_via_anchors(G_proj, nodes_proj_gdf, anchors, weight_key="shape_cost",
                                   start_proj_point=start_proj_point, connect_from_start=connect_from_start,
                                   max_connector_m=max_connector_m, return_to_start=return_to_start)
        if rl is None:
            rn, rl = route_via_shape(G_proj, nodes_proj_gdf, tuned, step_m, min_gap_m, center_lat, center_lng,
                                     return_to_start, weight_key="length")
    else:
        rn, rl = route_via_shape(G_proj, nodes_proj_gdf, tuned, step_m, min_gap_m, center_lat, center_lng,
                                 return_to_start, weight_key="shape_cost")
        if rl is None:
            rn, rl = route_via_shape(G_proj, nodes_proj_gdf, tuned, step_m, min_gap_m, center_lat, center_lng,
                                     return_to_start, weight_key="length")

    if rl is None: return None, None, None
    return rn, rl, line_length_km(rl), tuned

def binary_scale_fit(G_proj, nodes_proj_gdf, mapped_base: LineString, target_km: float, tol_ratio: float,
                     step_m: float, min_gap_m: float, center_lat: float, center_lng: float,
                     return_to_start: bool = True, iters: int = 16,
                     shape_bias_lambda: float = 0.03, anchor_count: int = 12, use_anchors: bool = True,
                     connect_from_start: bool = True, max_connector_m: float = 600.0,
                     proximity_alpha: float = 0.6, proximity_max_shift_m: float = 1500.0) -> FitResult:

    start_proj_point = ox.projection.project_geometry(Point(center_lng, center_lat), crs="EPSG:4326", to_crs=nodes_proj_gdf.crs)[0]

    # initial
    out = _route_length_km_try(G_proj, nodes_proj_gdf, mapped_base, 1.0, step_m, min_gap_m,
                               center_lat, center_lng, return_to_start, use_anchors, anchor_count,
                               shape_bias_lambda, start_proj_point, connect_from_start, max_connector_m,
                               proximity_alpha, proximity_max_shift_m)
    rn0, rl0, km0, tuned0 = out if out != (None, None, None) else (None, None, None, None)
    if rl0 is None:
        for s in [0.5, 0.8, 1.5, 2.0, 2.5]:
            rn0, rl0, km0, tuned0 = _route_length_km_try(G_proj, nodes_proj_gdf, mapped_base, s, step_m, min_gap_m,
                                                         center_lat, center_lng, return_to_start, use_anchors, anchor_count,
                                                         shape_bias_lambda, start_proj_point, connect_from_start, max_connector_m,
                                                         proximity_alpha, proximity_max_shift_m)
            if rl0 is not None: break
        if rl0 is None:
            raise RuntimeError("Failed to obtain initial feasible route for any test scale.")

    ratio = max(0.1, min(10.0, target_km / max(1e-6, km0)))
    lo = max(0.05, ratio / 2.5)
    hi = min(6.0, ratio * 2.5)

    target_min = target_km * (1 - tol_ratio)
    target_max = target_km * (1 + tol_ratio)

    best = (1.0, rn0, rl0, km0, tuned0)

    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        rn, rl, km, tuned = _route_length_km_try(G_proj, nodes_proj_gdf, mapped_base, mid, step_m, min_gap_m,
                                                 center_lat, center_lng, return_to_start, use_anchors, anchor_count,
                                                 shape_bias_lambda, start_proj_point, connect_from_start, max_connector_m,
                                                 proximity_alpha, proximity_max_shift_m)
        if rl is None:
            lo = mid; continue

        if abs(km - target_km) < abs(best[3] - target_km):
            best = (mid, rn, rl, km, tuned)

        if target_min <= km <= target_max:
            best = (mid, rn, rl, km, tuned); break

        if km < target_min: lo = mid
        else: hi = mid

    scale_used, route_nodes, route_line, Lkm, template_tuned = best
    return FitResult(scale_used, route_nodes, route_line, Lkm, template_tuned)
