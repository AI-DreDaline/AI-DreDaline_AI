# app/services/metrics_service.py
from __future__ import annotations
from typing import List, Tuple
import math
import numpy as np

LngLat = Tuple[float, float]

def haversine_m(a: LngLat, b: LngLat) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    s = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(s))

def _cumdist(pts: List[LngLat]) -> np.ndarray:
    d = [0.0]
    for i in range(1, len(pts)):
        d.append(d[-1] + haversine_m(pts[i-1], pts[i]))
    return np.asarray(d, dtype=float)

def _interp_along(pts: List[LngLat], s: np.ndarray) -> List[LngLat]:
    """누적거리 배열 기준으로 s 지점들에 대해 선분 보간 (경도/위도 선형보간; 짧은 구간 가정)"""
    if len(pts) == 1:
        return pts * len(s)
    d = _cumdist(pts)
    out: List[LngLat] = []
    for t in s:
        j = np.searchsorted(d, t, side="right") - 1
        j = max(0, min(j, len(pts)-2))
        seg = d[j+1] - d[j]
        if seg <= 1e-9:
            out.append(pts[j])
        else:
            r = (t - d[j]) / seg
            lon = pts[j][0] + r * (pts[j+1][0] - pts[j][0])
            lat = pts[j][1] + r * (pts[j+1][1] - pts[j][1])
            out.append((float(lon), float(lat)))
    return out

def resample_equal_count(pts: List[LngLat], count: int) -> List[LngLat]:
    """폴리라인을 동일 개수로 등간격(거리 기준) 샘플링"""
    if not pts:
        return []
    if len(pts) == 1 or count <= 1:
        return [pts[0]] * count
    d = _cumdist(pts)
    total = d[-1]
    if total <= 1e-6:
        return [pts[0]] * count
    s = np.linspace(0.0, total, count)
    return _interp_along(pts, s)

def average_and_max_distance_m(a: List[LngLat], b: List[LngLat]) -> Tuple[float, float]:
    """같은 개수의 점 집합 평균/최대 하버사인 거리(m)"""
    assert len(a) == len(b) and len(a) > 0
    dists = [haversine_m(p, q) for p, q in zip(a, b)]
    return float(np.mean(dists)), float(np.max(dists))

def similarity_score(avg_dist_m: float) -> float:
    """
    0~100 점수. 0m→100점, 60m 평균 오차→~36점, 100m→~18점
    (부드럽고 직관적인 exp 스케일)
    """
    import math
    return round(100.0 * math.exp(-avg_dist_m / 60.0), 1)
