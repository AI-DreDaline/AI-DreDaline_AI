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
    최종 경로 LineString(투영 CRS)을 받아
    - turn / straight / checkpoint / arrive
    를 모두 포함한 guidance_points 리스트를 만든다.

    반환 구조:
    {
      "guidance_points": [...],
      "total_points": N,
      "total_distance": float
    }

    각 guidance_point 예시:
    {
      "sequence": 1,
      "type": "turn" | "straight" | "checkpoint" | "arrive",
      "km_mark": 1,              # checkpoint일 때만
      "lat": 33.49,
      "lng": 126.53,
      "direction": "left",
      "angle": -65.3,
      "distance_from_start": 120.5,
      "distance_to_next": 28.3,
      "guidance_id": "TURN_LEFT_30",
      "trigger_distance": 15.0,
      "show_pace": true          # checkpoint일 때만
    }
    """
    coords_proj = list(line_proj.coords)
    n = len(coords_proj)
    if n < 2:
        return {
            "guidance_points": [],
            "total_points": 0,
            "total_distance": 0.0
        }

    # 1) 누적 거리 테이블 (m 단위)
    cum_dist = [0.0]
    for i in range(1, n):
        x1, y1 = coords_proj[i - 1]
        x2, y2 = coords_proj[i]
        seg_len = hypot(x2 - x1, y2 - y1)
        cum_dist.append(cum_dist[-1] + seg_len)
    total_len_m = cum_dist[-1]

    # 2) 각 segment 방향(heading)
    bearings = []
    for i in range(n - 1):
        b = _bearing(coords_proj[i], coords_proj[i + 1])
        bearings.append(b)

    # 3) turn / straight 후보 이벤트 추출
    #    -> kind: "turn" | "straight"
    turn_events = []
    prev_bearing = bearings[0]
    last_guidance_dist = 0.0

    for i in range(1, n - 1):
        b2 = bearings[i]
        delta = _norm_angle(b2 - prev_bearing)  # 방향 변화
        dist_here = cum_dist[i]

        if abs(delta) >= min_turn_deg:
            direction = "left" if delta < 0 else "right"
            turn_events.append({
                "kind": "turn",
                "index": i,
                "direction": direction,
                "angle": delta,
                "distance_from_start": dist_here
            })
            prev_bearing = b2
            last_guidance_dist = dist_here
        else:
            # 큰 턴은 아니지만 직진 구간이 지정 길이 이상이면 straight 이벤트 추가
            if dist_here - last_guidance_dist >= straight_interval_m:
                turn_events.append({
                    "kind": "straight",
                    "index": i,
                    "direction": "straight",
                    "angle": 0.0,
                    "distance_from_start": dist_here
                })
                last_guidance_dist = dist_here
                prev_bearing = b2

    # 4) 도착 지점 이벤트 (arrive)
    arrive_event = {
        "kind": "arrive",
        "index": n - 1,
        "direction": "straight",
        "angle": 0.0,
        "distance_from_start": total_len_m
    }
    turn_events.append(arrive_event)

    # 5) 1km 단위 체크포인트 이벤트 생성
    checkpoint_events = []
    total_km = int(total_len_m // 1000.0)  # 8.2km면 1~8km까지 체크포인트 생성
    if total_km > 0:
        cursor = 0
        for km in range(1, total_km + 1):
            target_dist = km * 1000.0

            # cum_dist에서 target_dist 이상이 되는 첫 인덱스를 찾는다
            while cursor < len(cum_dist) and cum_dist[cursor] < target_dist:
                cursor += 1
            if cursor >= len(cum_dist):
                break

            idx = cursor
            checkpoint_events.append({
                "kind": "checkpoint",
                "index": idx,
                "direction": "straight",
                "angle": 0.0,
                "distance_from_start": target_dist,
                "km_mark": km,
            })

    # 6) 이벤트 합쳐서 distance 기준 정렬
    all_events = turn_events + checkpoint_events
    all_events.sort(key=lambda e: e["distance_from_start"])

    # 7) WGS84로 좌표 변환
    line_ll = ox.projection.project_geometry(line_proj, crs=crs_proj, to_crs="EPSG:4326")[0]
    coords_ll = list(line_ll.coords)

    # 8) guidance_id 생성 로직
    def make_guidance_id(kind: str, direction: str, angle: float, dist_to_next: float, km_mark: int | None):
        # checkpoint인 경우
        if kind == "checkpoint":
            return "CHECKPOINT_KM"

        if kind == "arrive":
            return "ROUTE_COMPLETE"

        if direction in ("left", "right"):
            # 각도 10도 단위 버킷
            bucket = int(round(abs(angle) / 10.0) * 10)
            bucket = max(10, min(bucket, 50))  # 10~50 사이로 클램프
            return f"TURN_{direction.upper()}_{bucket}"

        # straight 계열
        if kind == "straight":
            if dist_to_next >= 150:
                return "GO_STRAIGHT_LONG"
            elif dist_to_next >= 80:
                return "GO_STRAIGHT_100"
            else:
                return "GO_STRAIGHT_50"

        # fallback
        return "GO_STRAIGHT_50"

    # 9) guidance_points 구성
    guidance_points: List[Dict] = []
    for seq, e in enumerate(all_events, start=1):
        idx = e["index"]
        kind = e["kind"]
        direction = e["direction"]
        angle = e["angle"]
        dist_from_start = e["distance_from_start"]
        km_mark = e.get("km_mark")

        lat = coords_ll[idx][1]
        lng = coords_ll[idx][0]

        # 다음 이벤트까지 거리
        if seq < len(all_events):
            next_dist = all_events[seq]["distance_from_start"]
            distance_to_next = max(0.0, next_dist - dist_from_start)
        else:
            distance_to_next = 0.0

        guidance_id = make_guidance_id(kind, direction, angle, distance_to_next, km_mark)

        point: Dict = {
            "sequence": seq,
            "type": "checkpoint" if kind == "checkpoint" else ("arrive" if kind == "arrive" else kind),
            "lat": lat,
            "lng": lng,
            "direction": direction,
            "angle": round(angle, 1),
            "distance_from_start": round(dist_from_start, 1),
            "distance_to_next": round(distance_to_next, 1),
            "guidance_id": guidance_id,
            "trigger_distance": trigger_distance,
        }

        # 체크포인트일 때만 추가 필드
        if kind == "checkpoint":
            point["km_mark"] = km_mark
            point["show_pace"] = True

        guidance_points.append(point)

    return {
        "guidance_points": guidance_points,
        "total_points": len(guidance_points),
        "total_distance": round(total_len_m, 1)
    }
