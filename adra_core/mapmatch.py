# adra_core/mapmatch.py
from __future__ import annotations
from typing import List, Tuple
import math
import osmnx as ox
import networkx as nx
from shapely.geometry import LineString

def _decimate(coords: List[Tuple[float, float]], step: int = 50) -> List[Tuple[float, float]]:
    """좌표를 일정 간격으로 줄여 라우팅 호출 수를 줄임 (약 50~100m 권장)."""
    if len(coords) <= 2:
        return coords
    out = [coords[0]]
    acc = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(coords, coords[1:]):
        d = _haversine_m(lat1, lng1, lat2, lng2)
        acc += d
        if acc >= step:
            out.append((lng2, lat2))
            acc = 0.0
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    from math import radians, sin, cos, sqrt, atan2
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * atan2(sqrt(a), math.sqrt(1 - a))

def load_walk_graph(center_lat: float, center_lng: float, dist_m: int = 3000):
    """
    중심점 기준 dist_m 반경의 보행자 네트워크 그래프 로드.
    캐시는 osmnx 기본 캐시를 사용( ~/.cache/osmnx ).
    """
    import osmnx as ox
    G = ox.graph_from_point((center_lat, center_lng),
                            dist=dist_m,
                            network_type="walk",
                            simplify=True)
    # 🔥 여기만 수정
    from osmnx import distance
    G = distance.add_edge_lengths(G)
    return G

def map_match_osmnx(coords_lnglat: List[Tuple[float, float]],
                    center_lat: float, center_lng: float,
                    graph_dist_m: int = 3000,
                    sample_step_m: int = 60
                    ) -> Tuple[List[Tuple[float,float]], float]:
    """
    OSMnx 라우팅을 이용한 간이 맵매칭:
      1) 입력 라인을 일정 간격으로 샘플링
      2) 각 점을 최근접 노드로 스냅
      3) 인접 노드 쌍 사이를 최단경로(길이 가중)로 연결
    반환: (도로 위 LineString 좌표[lng,lat], 총 길이[m])
    """
    if len(coords_lnglat) < 2:
        return coords_lnglat, 0.0

    # 그래프 로드
    G = load_walk_graph(center_lat, center_lng, dist_m=graph_dist_m)

    # 1) 디시메이트
    pts = _decimate(coords_lnglat, step=sample_step_m)

    # 2) 최근접 노드 시퀀스
    xs = [lng for (lng, _) in pts]
    ys = [lat for (_, lat) in pts]
    node_ids = ox.nearest_nodes(G, xs, ys)

    # 중복 제거 (같은 노드 연속 등장 방지)
    seq = []
    for n in node_ids:
        if not seq or seq[-1] != n:
            seq.append(n)
    if len(seq) < 2:
        # 그래프 범위를 너무 좁게 잡은 경우 발생
        return coords_lnglat, 0.0

    # 3) 노드 간 최단경로 이어 붙이기
    path_nodes_total = []
    for u, v in zip(seq, seq[1:]):
        try:
            p = nx.shortest_path(G, u, v, weight="length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            # 경로가 끊기면 해당 구간은 스킵(혹은 직선 보간 선택 가능)
            continue
        if path_nodes_total and path_nodes_total[-1] == p[0]:
            path_nodes_total += p[1:]
        else:
            path_nodes_total += p

    # 4) 노드 시퀀스 → 좌표 & 길이
    coords_mm = []
    for nid in path_nodes_total:
        d = G.nodes[nid]
        coords_mm.append((d["x"], d["y"]))  # (lng, lat)

    length_m = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(coords_mm, coords_mm[1:]):
        length_m += _haversine_m(lat1, lng1, lat2, lng2)

    # 간단한 스무딩: 너무 촘촘하면 간격 줄이기
    if len(coords_mm) > 1_500:
        coords_mm = _decimate(coords_mm, step=10)

    return coords_mm, length_m
