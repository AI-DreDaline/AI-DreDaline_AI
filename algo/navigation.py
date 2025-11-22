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
    trigger_distance: float = 15.0,  # 기본값 (턴 제외한 이벤트용)
) -> Dict:
    """
    최종 경로 LineString(투영 CRS)을 받아
    - turn(50m/15m 안내 2개씩)
    - straight
    - checkpoint(1km마다)
    - progress(30%, 50%, 80%)
    - arrive
    를 모두 포함한 guidance_points 리스트를 만든다.
    """

    coords_proj = list(line_proj.coords)
    n = len(coords_proj)
    if n < 2:
        return {
            "guidance_points": [],
            "total_points": 0,
            "total_distance": 0.0
        }

    # 1) 누적 거리 (m)
    cum_dist = [0.0]
    for i in range(1, n):
        x1, y1 = coords_proj[i - 1]
        x2, y2 = coords_proj[i]
        seg_len = hypot(x2 - x1, y2 - y1)
        cum_dist.append(cum_dist[-1] + seg_len)
    total_len_m = cum_dist[-1]

    # 2) 세그먼트 각도
    bearings = []
    for i in range(n - 1):
        b = _bearing(coords_proj[i], coords_proj[i + 1])
        bearings.append(b)

    # 3) turn / straight 이벤트 추출
    events = []  # kind: "turn" | "straight" | "checkpoint" | "progress" | "arrive"
    prev_bearing = bearings[0]
    last_guidance_dist = 0.0

    for i in range(1, n - 1):
        b2 = bearings[i]
        delta = _norm_angle(b2 - prev_bearing)
        dist_here = cum_dist[i]

        if abs(delta) >= min_turn_deg:
            direction = "left" if delta < 0 else "right"
            events.append({
                "kind": "turn",
                "index": i,
                "direction": direction,
                "angle": delta,
                "distance_from_start": dist_here
            })
            prev_bearing = b2
            last_guidance_dist = dist_here
        else:
            # 일정 거리 이상 직진 구간이면 straight 이벤트
            if dist_here - last_guidance_dist >= straight_interval_m:
                events.append({
                    "kind": "straight",
                    "index": i,
                    "direction": "straight",
                    "angle": 0.0,
                    "distance_from_start": dist_here
                })
                last_guidance_dist = dist_here
                prev_bearing = b2

    # 4) 도착 이벤트
    events.append({
        "kind": "arrive",
        "index": n - 1,
        "direction": "straight",
        "angle": 0.0,
        "distance_from_start": total_len_m
    })

    # 5) 1km 체크포인트 이벤트
    total_km = int(total_len_m // 1000.0)
    if total_km > 0:
        cursor = 0
        for km in range(1, total_km + 1):
            target_dist = km * 1000.0
            while cursor < len(cum_dist) and cum_dist[cursor] < target_dist:
                cursor += 1
            if cursor >= len(cum_dist):
                break
            idx = cursor
            events.append({
                "kind": "checkpoint",
                "index": idx,
                "direction": "straight",
                "angle": 0.0,
                "distance_from_start": target_dist,
                "km_mark": km
            })

    # 6) 그림 완성률 progress 이벤트 (30%, 50%, 80%)
    progress_pcts = [30, 50, 80]
    cursor_p = 0
    for pct in progress_pcts:
        target_dist = total_len_m * (pct / 100.0)
        # 도착 지점이랑 거의 겹치면(예: 100%) 스킵
        if target_dist >= total_len_m * 0.99:
            continue
        while cursor_p < len(cum_dist) and cum_dist[cursor_p] < target_dist:
            cursor_p += 1
        if cursor_p >= len(cum_dist):
            break
        idx = cursor_p
        events.append({
            "kind": "progress",
            "index": idx,
            "direction": "straight",
            "angle": 0.0,
            "distance_from_start": target_dist,
            "progress_pct": pct
        })

    # 7) 거리 기준으로 정렬
    events.sort(key=lambda e: e["distance_from_start"])

    # 8) 좌표 WGS84 변환
    line_ll = ox.projection.project_geometry(line_proj, crs=crs_proj, to_crs="EPSG:4326")[0]
    coords_ll = list(line_ll.coords)

    # 9) guidance_id 생성 함수
    def make_guidance_id(e, dist_to_next: float) -> str:
        kind = e["kind"]
        direction = e["direction"]
        angle = e["angle"]
        km_mark = e.get("km_mark")
        progress_pct = e.get("progress_pct")

        # 체크포인트 (km 단위)
        if kind == "checkpoint":
            return "CHECKPOINT_KM"

        # 완성률 안내
        if kind == "progress":
            if progress_pct == 30:
                return "PROGRESS_30"
            if progress_pct == 50:
                return "PROGRESS_50"
            if progress_pct == 80:
                return "PROGRESS_80"
            return "PROGRESS_30"

        # 도착
        if kind == "arrive":
            return "ROUTE_COMPLETE"

        # 턴: 여기서는 나중에 50m/15m 용으로 stage별로 별도 처리할 거라 기본값만 둠
        if kind == "turn":
            # 기본 값 (실제로는 아래에서 stage별로 덮어씀)
            if direction in ("left", "right"):
                base = "LEFT" if direction == "left" else "RIGHT"
                return f"TURN_{base}_50"

        # 직진 계열
        if kind == "straight":
            if dist_to_next >= 150:
                return "GO_STRAIGHT_LONG"
            elif dist_to_next >= 80:
                return "GO_STRAIGHT_100"
            else:
                return "GO_STRAIGHT_50"

        # fallback
        return "GO_STRAIGHT_50"

    # 10) guidance_points 만들기
    guidance_points: List[Dict] = []

    for i, e in enumerate(events):
        idx = e["index"]
        kind = e["kind"]
        dist_from_start = e["distance_from_start"]

        lat = coords_ll[idx][1]
        lng = coords_ll[idx][0]

        if i < len(events) - 1:
            next_dist = events[i + 1]["distance_from_start"]
            distance_to_next = max(0.0, next_dist - dist_from_start)
        else:
            distance_to_next = 0.0

        base_point: Dict = {
            # sequence는 일단 나중에 일괄 지정
            "type": "checkpoint" if kind == "checkpoint" else (
                "progress" if kind == "progress" else
                "arrive" if kind == "arrive" else
                kind  # turn / straight
            ),
            "lat": lat,
            "lng": lng,
            "direction": e["direction"],
            "angle": round(e["angle"], 1),
            "distance_from_start": round(dist_from_start, 1),
            "distance_to_next": round(distance_to_next, 1),
            # guidance_id, trigger_distance는 아래에서 타입별로 세팅
        }

        # 체크포인트 (1km마다)
        if kind == "checkpoint":
            base_point["km_mark"] = e["km_mark"]
            base_point["show_pace"] = True
            base_point["guidance_id"] = make_guidance_id(e, distance_to_next)
            base_point["trigger_distance"] = trigger_distance  # 예: 10~15m 전
            guidance_points.append(base_point)
            continue

        # 완성률 progress 이벤트
        if kind == "progress":
            base_point["progress_pct"] = e["progress_pct"]
            base_point["guidance_id"] = make_guidance_id(e, distance_to_next)
            base_point["trigger_distance"] = trigger_distance  # 즉시 or 약간 전
            guidance_points.append(base_point)
            continue

        # 도착
        if kind == "arrive":
            base_point["guidance_id"] = make_guidance_id(e, distance_to_next)
            base_point["trigger_distance"] = trigger_distance
            guidance_points.append(base_point)
            continue

        # 턴: 50m / 15m 두 번 생성
        if kind == "turn":
            # 50m 전 예고
            p50 = base_point.copy()
            p50["guidance_id"] = f"TURN_{'LEFT' if e['direction']=='left' else 'RIGHT'}_50"
            p50["trigger_distance"] = 50.0
            guidance_points.append(p50)

            # 15m 전 확정 안내
            p15 = base_point.copy()
            p15["guidance_id"] = f"TURN_{'LEFT' if e['direction']=='left' else 'RIGHT'}_15"
            p15["trigger_distance"] = 15.0
            guidance_points.append(p15)
            continue

        # straight: 한 번만 생성
        if kind == "straight":
            base_point["guidance_id"] = make_guidance_id(e, distance_to_next)
            base_point["trigger_distance"] = trigger_distance
            guidance_points.append(base_point)
            continue

    # 11) sequence 부여
    for seq, p in enumerate(guidance_points, start=1):
        p["sequence"] = seq

    return {
        "guidance_points": guidance_points,
        "total_points": len(guidance_points),
        "total_distance": round(total_len_m, 1)
    }
