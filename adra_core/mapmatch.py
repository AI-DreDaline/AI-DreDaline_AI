# adra_core/mapmatch.py
from __future__ import annotations
from typing import List, Tuple
import math
import osmnx as ox
import networkx as nx

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    from math import radians, sin, cos, sqrt, atan2
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2 * R * atan2(sqrt(a), math.sqrt(1 - a))

def _len_haversine(coords: List[Tuple[float, float]]) -> float:
    if len(coords) < 2:
        return 0.0
    tot = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        tot += _haversine_m(y1, x1, y2, x2)
    return tot

def _decimate(coords: List[Tuple[float, float]], step: int = 50) -> List[Tuple[float, float]]:
    """대략 step(m) 간격으로 줄이기 (경험치)."""
    if len(coords) <= 2:
        return coords
    out = [coords[0]]
    acc = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        d = _haversine_m(y1, x1, y2, x2)
        acc += d
        if acc >= step:
            out.append((x2, y2))
            acc = 0.0
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out

def load_walk_graph(center_lat: float, center_lng: float, dist_m: int = 3000):
    G = ox.graph_from_point((center_lat, center_lng),
                            dist=dist_m, network_type="walk", simplify=True)
    # OSMnx 1.7+ : distance 서브모듈로 이동
    from osmnx import distance
    G = distance.add_edge_lengths(G)
    return G

def map_match_osmnx(coords_lnglat: List[Tuple[float, float]],
                    center_lat: float, center_lng: float,
                    graph_dist_m: int = 3000,
                    sample_step_m: int = 60
                    ) -> Tuple[List[Tuple[float,float]], float]:
    """OSMnx 라우팅 기반 간이 맵매칭. 실패 시 원본+거리 반환."""
    if len(coords_lnglat) < 2:
        return coords_lnglat, 0.0

    G = load_walk_graph(center_lat, center_lng, dist_m=graph_dist_m)
    pts = _decimate(coords_lnglat, step=sample_step_m)
    xs = [lng for (lng, _) in pts]
    ys = [lat for (_, lat) in pts]

    # 최근접 노드 시퀀스
    try:
        node_ids = ox.nearest_nodes(G, xs, ys)  # scikit-learn 필요
    except Exception:
        return coords_lnglat, _len_haversine(coords_lnglat)

    seq = []
    for n in node_ids:
        if not seq or seq[-1] != n:
            seq.append(n)
    if len(seq) < 2:
        return coords_lnglat, _len_haversine(coords_lnglat)

    # 노드 간 최단경로 이어붙이기
    path_nodes_total = []
    for u, v in zip(seq, seq[1:]):
        try:
            p = nx.shortest_path(G, u, v, weight="length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        if path_nodes_total and path_nodes_total[-1] == p[0]:
            path_nodes_total += p[1:]
        else:
            path_nodes_total += p

    if len(path_nodes_total) < 2:
        return coords_lnglat, _len_haversine(coords_lnglat)

    coords_mm = []
    for nid in path_nodes_total:
        d = G.nodes[nid]
        coords_mm.append((d["x"], d["y"]))  # (lng, lat)

    if len(coords_mm) > 1500:
        coords_mm = _decimate(coords_mm, step=10)

    length_m = _len_haversine(coords_mm)
    return coords_mm, length_m
