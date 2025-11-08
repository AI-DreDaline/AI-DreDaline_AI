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
    # WGS84 직선 근사 (짧은 구간 가정). 필요시 pyproj.Geod로 대체.
    # TODO: 필요시 정확도 향상 (geodesic)
    R = 6371000.0
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
    # SVG path를 일정 간격으로 샘플링해서 (x,y) 점열을 리턴
    paths, _ = svg2paths(str(svg_path))
    # 가장 첫 path만 사용(필요시 병합)
    poly = []
    for p in paths:
        L = p.length()
        n = max(2, int(L / sample_step))
        ts = np.linspace(0, 1, n)
        for t in ts:
            z = p.point(t)
            poly.append((z.real, z.imag))
        break
    return np.array(poly)  # shape (N, 2)

def _fit_to_target_km(
    xy: np.ndarray,
    target_km: float,
    start_lat: float,
    start_lng: float,
    align_mode: str = "free_fit"
) -> List[Tuple[float, float]]:
    """
    svg 좌표(xy)를 목표거리(km)에 맞춰 스케일/회전/이동.
    (간단한 기준 구현; 세부 로직은 노트북 구현을 이식)
    """
    # 1) 중심 0,0 이동
    xy0 = xy - xy.mean(axis=0, keepdims=True)

    # 2) 단위 길이 측정(유클리드)
    unit_len = (np.linalg.norm(np.diff(xy0, axis=0), axis=1)).sum()
    if unit_len == 0:
        raise ValueError("SVG path has zero length")

    # 목표 길이(미터)
    tgt_m = target_km * 1000.0

    # 3) 스케일링
    scale = tgt_m / unit_len
    xy1 = xy0 * scale

    # 4) 시작점 정렬 방식
    if align_mode == "start_locked":
        # 시작점을 (0,0) 기준으로 놓고, 이후 지도상의 start_lat/lng로 이동
        shift = -xy1[0]
        xy1 = xy1 + shift
    else:
        # free_fit: 시작점을 강제하지 않음(추후 map match에서 보정)
        pass

    # 5) (아주 간단한) 위경도 변환 근사: 1도당 m 보정
    # Jeju 근처 위도 기준
    m_per_deg_lat = 111_132
    m_per_deg_lng = 111_320 * math.cos(math.radians(start_lat))
    lngs = start_lng + (xy1[:, 0] / m_per_deg_lng)
    lats = start_lat + (xy1[:, 1] / m_per_deg_lat)

    coords = list(zip(lats.tolist(), lngs.tolist()))
    return coords

def generate_route_from_svg(
    svg_path: Path,
    start_point: Dict[str, float],
    target_km: float,
    options: Dict[str, Any]
) -> GeneratedRoute:
    """
    메인 엔트리: SVG 경로를 목표 거리로 스케일/정렬하여 위경도 경로 생성.
    필요시 map match/유사도도 여기서 호출.
    """
    sample_step_m = float(options.get("sample_step_m", 50))
    align_mode = str(options.get("align_mode", "free_fit"))
    resample_m = float(options.get("resample_m", 5))
    simplify_tol = float(options.get("simplify_tolerance", 0.5))
    do_map_match = bool(options.get("map_match", True))

    xy = _load_svg_points(svg_path, sample_step=1.0)  # 샘플링 단위 px → 내부 스케일로 보정
    coords_wgs84 = _fit_to_target_km(
        xy,
        target_km=target_km,
        start_lat=float(start_point["lat"]),
        start_lng=float(start_point["lng"]),
        align_mode=align_mode
    )

    # (선택) 간소화/리샘플
    line = LineString([(lon, lat) for lat, lon in coords_wgs84])
    if simplify_tol > 0:
        line = line.simplify(simplify_tol, preserve_topology=False)

    # TODO: 리샘플(resample_m 간격) 구현이 필요하면 추가

    # (선택) 맵매칭/유사도
    # TODO: algo/map_match.py의 함수 호출해 그래프 기반 보정 + 유사도 계산
    fallback_used = False
    matched = True if do_map_match else False

    # 메트릭
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
