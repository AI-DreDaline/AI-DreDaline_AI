# algo/svg_route.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, List, Tuple
from pathlib import Path
import math
import numpy as np
from shapely.geometry import LineString
from shapely.ops import substring
from svgpathtools import svg2paths
from config import SETTINGS
from algo.gragh_io import load_graph
from algo.map_match import map_match_coords


@dataclass
class RouteMetrics:
    nodes: int
    route_length_m: float
    scale_m_per_unit: float
    target_km: float


@dataclass
class GeneratedRoute:
    coords_wgs84: List[Tuple[float, float]]
    metrics: RouteMetrics
    properties: Dict[str, Any]


def _euclid_length_meters(points: List[Tuple[float, float]]) -> float:
    """Approximately calculate the length in meters using haversine formula."""
    R = 6371000.0  # Earth's radius in meters
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points[:-1], points[1:]):
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        total += 2 * R * math.asin(math.sqrt(a))
    return total


def _load_svg_points(svg_path: Path, sample_step: float = 1.0) -> np.ndarray:
    """Load SVG and sample along its path to get (x, y) points."""
    paths, _ = svg2paths(str(svg_path))
    poly = []
    for p in paths:
        L = p.length()
        n = max(2, int(L / sample_step))
        ts = np.linspace(0, 1, n)
        for t in ts:
            z = p.point(t)
            poly.append((z.real, z.imag))
        break  # Only first path by default
    return np.array(poly)


def _fit_to_target_km(
    xy: np.ndarray,
    target_km: float,
    start_lat: float,
    start_lng: float,
    align_mode: str = "free_fit"
) -> List[Tuple[float, float]]:
    """Scale and align SVG (x,y) points to target kilometers and map to WGS84."""
    xy0 = xy - xy.mean(axis=0, keepdims=True)
    unit_len = (np.linalg.norm(np.diff(xy0, axis=0), axis=1)).sum()
    if unit_len == 0:
        raise ValueError("SVG path has zero length")

    tgt_m = target_km * 1000.0
    scale = tgt_m / unit_len
    xy1 = xy0 * scale

    if align_mode == "start_locked":
        shift = -xy1[0]
        xy1 = xy1 + shift

    m_per_deg_lat = 111_132
    m_per_deg_lng = 111_320 * math.cos(math.radians(start_lat))
    lngs = start_lng + (xy1[:, 0] / m_per_deg_lng)
    lats = start_lat + (xy1[:, 1] / m_per_deg_lat)

    return list(zip(lats.tolist(), lngs.tolist()))


def generate_route_from_svg(
    svg_path: Path,
    start_point: Dict[str, float],
    target_km: float,
    options: Dict[str, Any]
) -> GeneratedRoute:
    """Main entry: Generate WGS84 route from an SVG template with map matching."""
    sample_step_m = float(options.get("sample_step_m", 50))
    align_mode = str(options.get("align_mode", "free_fit"))
    resample_m = float(options.get("resample_m", 5))
    simplify_tol = float(options.get("simplify_tolerance", 0.5))
    do_map_match = bool(options.get("map_match", True))
    graph_dist_m = int(options.get("graph_dist_m", 3500))

    xy = _load_svg_points(svg_path, sample_step=1.0)
    coords_wgs84 = _fit_to_target_km(
        xy,
        target_km=target_km,
        start_lat=float(start_point["lat"]),
        start_lng=float(start_point["lng"]),
        align_mode=align_mode
    )

    line = LineString([(lon, lat) for lat, lon in coords_wgs84])
    if simplify_tol > 0:
        line = line.simplify(simplify_tol, preserve_topology=False)

    fallback_used = False
    matched = False

    if do_map_match:
        try:
            G = load_graph(SETTINGS.CACHE_DIR, start_point["lat"], start_point["lng"], dist_m=graph_dist_m)
            matched_coords = map_match_coords(coords_wgs84, G, step=10)
            if len(matched_coords) > 1:
                coords_wgs84 = matched_coords
                matched = True
        except Exception:
            fallback_used = True
            matched = False

    route_len_m = _euclid_length_meters(coords_wgs84)
    scale_m_per_unit = route_len_m / max(1, len(coords_wgs84))

    metrics = RouteMetrics(
        nodes=len(coords_wgs84),
        route_length_m=route_len_m,
        scale_m_per_unit=scale_m_per_unit,
        target_km=target_km,
    )

    props = {
        "align_mode": f"{align_mode}(fallback)" if fallback_used else align_mode,
        "fallback_used": fallback_used,
        "fit_params": {},
        "matched": matched,
        "name": f"Template route ~{target_km:.1f}km"
    }

    return GeneratedRoute(
        coords_wgs84=coords_wgs84,
        metrics=metrics,
        properties=props
    )
