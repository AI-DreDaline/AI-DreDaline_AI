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


def _classify_turn(angle_deg: float) -> str:
    """
    각도(변화량, 절대값 기준)에 따라 턴 타입 분류.
    반환: 'ignore' | 'slight' | 'normal' | 'sharp' | 'u_turn'
    """
    a = abs(angle_deg)

    if a < 20:
        return "ignore"
    elif a < 45:
        return "slight"
    elif a < 120:
        return "normal"
    elif a < 160:
        return "sharp"
    else:
        return "u_turn"


def build_guidance_points(
    line_proj: LineString,
    crs_proj,
    min_turn_deg: float = 20.0,    # 최소 턴 감지 기준 (위 _classify_turn과 일관되게)
    straight_interval_m: float = 100.0,
    trigger_distance: float = 15.0,
) -> Dict:
    """
    최종 경로 LineString(투영 CRS)을 받아
    guidance_points 리스트를 생성한다.

    guidance_point 예시:
    {
      "sequence": 1,
      "type": "turn" | "straight" | "checkpoint" | "progress" | "arrive",
      "lat": 33.49,
      "lng": 126.53,
      "direction": "left",
      "angle": -75.3,
      "distance_from_start": 450.2,
      "distance_to_next": 120.5,
      "guidance_id": "TURN_LEFT_50",
      "trigger_distance": 50.0,
      "km_mark": 1,          # checkpoint일 때
      "progress_pct": 50,    # progress일 때
      "show_pace": true      # checkpoint일 때
    }
    """

    coords_proj = list(line_proj.coords)
    n = len(coords_proj)
    if n < 2:
        return {
            "guidance_points": [],
            "total_points": 0,
            "total_distance": 0.0,
        }

    # 1) 누적 거리 (m)
    cum_dist = [0.0]
    for i in range(1, n):
        x1, y1 = coords_proj[i - 1]
        x2, y2 = coords_proj[i]
        seg_len = hypot(x2 - x1, y2 - y1)
        cum_dist.append(cum_dist[-1] + seg_len)
    total_len_m = cum_dist[-1]

    # 2) 세그먼트 방향 각도
    bearings = []
    for i in range(n - 1):
        b = _bearing(coords_proj[i], coords_proj[i + 1])
        bearings.append(b)

    # 3) turn / straight 기본 이벤트 추출
    events = []  # kind: "turn" | "straight" | "checkpoint" | "progress" | "arrive"
    prev_bearing = bearings[0]
    last_straight_marker = 0.0

    for i in range(1, n - 1):
        b2 = bearings[i]
        delta = _norm_angle(b2 - prev_bearing)
        dist_here = cum_dist[i]

        turn_type = _classify_turn(delta)

        if turn_type != "ignore":
            direction = "left" if delta < 0 else "right"
            events.append({
                "kind": "turn",
                "index": i,
                "direction": direction,
                "angle": delta,
                "distance_from_start": dist_here,
                "turn_type": turn_type,   # slight / normal / sharp / u_turn
            })
            prev_bearing = b2
            last_straight_marker = dist_here
        else:
            # 큰 턴은 아니지만 직진이 길어지면 straight 이벤트 하나 찍기
            if dist_here - last_straight_marker >= straight_interval_m:
                events.append({
                    "kind": "straight",
                    "index": i,
                    "direction": "straight",
                    "angle": 0.0,
                    "distance_from_start": dist_here,
                })
                last_straight_marker = dist_here
                prev_bearing = b2

    # 4) 도착 이벤트
    events.append({
        "kind": "arrive",
        "index": n - 1,
        "direction": "straight",
        "angle": 0.0,
        "distance_from_start": total_len_m,
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
                "km_mark": km,
            })

    # 6) 진행률 이벤트 (30 / 50 / 80%)
    progress_pcts = [30, 50, 80]
    cursor_p = 0
    for pct in progress_pcts:
        target_dist = total_len_m * (pct / 100.0)
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
            "progress_pct": pct,
        })

    # 7) 거리 기준 정렬
    events.sort(key=lambda e: e["distance_from_start"])

    # 8) 좌표 WGS84로 변환
    line_ll = ox.projection.project_geometry(
        line_proj, crs=crs_proj, to_crs="EPSG:4326"
    )[0]
    coords_ll = list(line_ll.coords)

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

        # 공통 필드 기본값
        base = {
            "type": (
                "checkpoint" if kind == "checkpoint" else
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
        }

        # 체크포인트
        if kind == "checkpoint":
            point = base.copy()
            point["km_mark"] = e["km_mark"]
            point["show_pace"] = True
            point["guidance_id"] = "CHECKPOINT_ARRIVED"
            point["trigger_distance"] = trigger_distance
            guidance_points.append(point)
            continue

        # 진행률
        if kind == "progress":
            point = base.copy()
            pct = e["progress_pct"]
            if pct == 30:
                gid = "PROGRESS_30"
            elif pct == 50:
                gid = "PROGRESS_50"
            elif pct == 80:
                gid = "PROGRESS_80"
            else:
                gid = "PROGRESS_30"
            point["progress_pct"] = pct
            point["guidance_id"] = gid
            point["trigger_distance"] = trigger_distance
            guidance_points.append(point)
            continue

        # 도착
        if kind == "arrive":
            point = base.copy()
            point["guidance_id"] = "ROUTE_COMPLETE"
            point["trigger_distance"] = trigger_distance
            guidance_points.append(point)
            continue

        # 직진 구간 안내 (긴 직진 구간만 이벤트 있음)
        if kind == "straight":
            point = base.copy()
            point["guidance_id"] = "GO_STRAIGHT_NEXT"
            point["trigger_distance"] = trigger_distance
            guidance_points.append(point)
            continue

        # 턴: turn_type에 따라 템플릿 매핑
        if kind == "turn":
            turn_type = e["turn_type"]  # slight / normal / sharp / u_turn
            direction = e["direction"]  # left / right

            # 1) SLIGHT : 15m 한 번
            if turn_type == "slight":
                p = base.copy()
                p["guidance_id"] = "SLIGHT_LEFT" if direction == "left" else "SLIGHT_RIGHT"
                p["trigger_distance"] = 15.0
                guidance_points.append(p)

            # 2) NORMAL : 50m / 15m 두 단계
            elif turn_type == "normal":
                p50 = base.copy()
                p50["guidance_id"] = (
                    "TURN_LEFT_50" if direction == "left" else "TURN_RIGHT_50"
                )
                p50["trigger_distance"] = 50.0
                guidance_points.append(p50)

                p15 = base.copy()
                p15["guidance_id"] = (
                    "TURN_LEFT_15" if direction == "left" else "TURN_RIGHT_15"
                )
                p15["trigger_distance"] = 15.0
                guidance_points.append(p15)

            # 3) SHARP : 50m 예고 + 15m 급회전
            elif turn_type == "sharp":
                p50 = base.copy()
                p50["guidance_id"] = (
                    "TURN_LEFT_50" if direction == "left" else "TURN_RIGHT_50"
                )
                p50["trigger_distance"] = 50.0
                guidance_points.append(p50)

                p15 = base.copy()
                p15["guidance_id"] = "SHARP_LEFT" if direction == "left" else "SHARP_RIGHT"
                p15["trigger_distance"] = 15.0
                guidance_points.append(p15)

            # 4) U_TURN : 50m / 15m 유턴 템플릿
            elif turn_type == "u_turn":
                p50 = base.copy()
                p50["guidance_id"] = "U_TURN_50"
                p50["trigger_distance"] = 50.0
                guidance_points.append(p50)

                p15 = base.copy()
                p15["guidance_id"] = "U_TURN_15"
                p15["trigger_distance"] = 15.0
                guidance_points.append(p15)

            continue

    # 9) sequence 부여
    for seq, p in enumerate(guidance_points, start=1):
        p["sequence"] = seq

    return {
        "guidance_points": guidance_points,
        "total_points": len(guidance_points),
        "total_distance": round(total_len_m, 1),
    }