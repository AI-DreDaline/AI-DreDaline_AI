# algo/navigation.py
from __future__ import annotations
from math import atan2, degrees, hypot
from typing import List, Dict
from shapely.geometry import LineString
import osmnx as ox

def _bearing(p1, p2) -> float:
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    ang = degrees(atan2(dx, dy))
    return ang

def _norm_angle(a: float) -> float:
    while a <= -180:
        a += 360
    while a > 180:
        a -= 360
    return a

def build_guidance_points(
    line_proj: LineString,
    crs_proj,
    min_turn_deg: float = 30.0,
    straight_interval_m: float = 100.0,
    trigger_distance: float = 15.0,
) -> Dict:
    """
    최종 경로 LineString(투영 CRS) → guidance_points JSON 구조로 변환.

    반환:
    {
      "guidance_points": [...],
      "total_points": N,
      "total_distance": float
    }
    """
    coords_proj = list(line_proj.coords)
    n = len(coords_proj)
    if n < 2:
        return {"guidance_points": [], "total_points": 0, "total_distance": 0.0}

    # 1) 누적 거리 테이블
    cum_dist = [0.0]
    for i in range(1, n):
        x1, y1 = coords_proj[i-1]
        x2, y2 = coords_proj[i]
        seg_len = hypot(x2 - x1, y2 - y1)
        cum_dist.append(cum_dist[-1] + seg_len)
    total_len_m = cum_dist[-1]

    # 2) 각 segment 방향(heading)
    bearings = []
    for i in range(n - 1):
        b = _bearing(coords_proj[i], coords_proj[i+1])
        bearings.append(b)

    # 3) 턴 후보 찾기
    candidates = []  # (index, direction, angle_deg)
    prev_bearing = bearings[0]
    last_guidance_dist = 0.0

    for i in range(1, n - 1):
        b2 = bearings[i]
        delta = _norm_angle(b2 - prev_bearing)  # 방향 변화
        dist_here = cum_dist[i]

        if abs(delta) >= min_turn_deg:
            direction = "left" if delta < 0 else "right"
            candidates.append((i, direction, delta))
            prev_bearing = b2
            last_guidance_dist = dist_here
        else:
            # 큰 턴은 아니지만 직진 구간이 길 경우 straight 포인트 추가
            if dist_here - last_guidance_dist >= straight_interval_m:
                candidates.append((i, "straight", 0.0))
                last_guidance_dist = dist_here
                prev_bearing = b2

    # 마지막 도착 지점도 straight 느낌으로 하나 찍어도 됨 (선택)
    if not candidates or candidates[-1][0] != n - 1:
        candidates.append((n - 1, "straight", 0.0))

    # 4) 좌표를 WGS84로 변환
    line_ll = ox.projection.project_geometry(line_proj, crs=crs_proj, to_crs="EPSG:4326")[0]
    coords_ll = list(line_ll.coords)

    # 5) guidance_id 생성 로직 (간단 버전)
    def make_guidance_id(direction: str, angle: float, dist_to_next: float) -> str:
        if direction in ("left", "right"):
            bucket = int(round(abs(angle) / 10.0) * 10)  # 10도 단위 버킷
            return f"TURN_{direction.upper()}_{bucket}"
        else:
            # straight는 다음 턴까지 거리 기준으로 버킷
            bucket = int(round(dist_to_next / 10.0) * 10)  # 10m 단위
            return f"GO_STRAIGHT_{bucket}"

    # 6) guidance_points 목록 생성
    guidance_points: List[Dict] = []
    for seq, (idx, direction, angle) in enumerate(candidates, start=1):
        lat, lng = coords_ll[idx][1], coords_ll[idx][0]
        dist_from_start = cum_dist[idx]

        # 다음 포인트까지 거리
        if seq < len(candidates):
            next_idx = candidates[seq][0]  # 다음 candidate의 index
            distance_to_next = cum_dist[next_idx] - dist_from_start
        else:
            distance_to_next = 0.0

        gid = make_guidance_id(direction, angle, distance_to_next)

        guidance_points.append({
            "sequence": seq,
            "lat": lat,
            "lng": lng,
            "direction": direction,
            "angle": round(angle, 1),
            "distance_from_start": round(dist_from_start, 1),
            "distance_to_next": round(distance_to_next, 1),
            "guidance_id": gid,
            "trigger_distance": trigger_distance,
        })

    return {
        "guidance_points": guidance_points,
        "total_points": len(guidance_points),
        "total_distance": round(total_len_m, 1)
    }
