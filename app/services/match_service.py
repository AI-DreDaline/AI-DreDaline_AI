# app/services/match_service.py
from __future__ import annotations
from typing import List, Tuple, Dict
import math
import numpy as np
import networkx as nx
import osmnx as ox
from scipy.spatial import cKDTree

try:
    from osmnx.distance import add_edge_lengths
except Exception:
    add_edge_lengths = None

_GRAPH_CACHE: Dict[str, nx.MultiDiGraph] = {}

def load_ped_graph(center_lat: float, center_lng: float, dist_m: int = 3000) -> nx.MultiDiGraph:
    key = f"{round(center_lat,5)}_{round(center_lng,5)}_{dist_m}"
    if key in _GRAPH_CACHE:
        return _GRAPH_CACHE[key]
    G = ox.graph_from_point((center_lat, center_lng), dist=dist_m, network_type="walk", simplify=True)
    if add_edge_lengths is not None:
        add_edge_lengths(G)
    _GRAPH_CACHE[key] = G
    return G

# --- utils ---

def haversine_m(a: Tuple[float,float], b: Tuple[float,float]) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    s = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(s))

def _haversine_m(a: Tuple[float,float], b: Tuple[float,float]) -> float:
    (lon1, lat1), (lon2, lat2) = a, b
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    s = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(s))

def prune_small_loops(G, route_nodes: List[int], loop_thresh_m: float = 60.0) -> List[int]:
    """경로 내 짧은 루프(되돌아감) 제거"""
    if len(route_nodes) < 3:
        return route_nodes
    cleaned = [route_nodes[0]]
    for n in route_nodes[1:]:
        cleaned.append(n)
        # A,B,A 패턴 제거
        if len(cleaned) >= 3 and cleaned[-1] == cleaned[-3]:
            # 거리도 아주 짧으면(루프) 중간 점 제거
            a = G.nodes[cleaned[-3]]
            b = G.nodes[cleaned[-2]]
            c = G.nodes[cleaned[-1]]
            dab = _haversine_m((a["x"], a["y"]), (b["x"], b["y"]))
            bc  = _haversine_m((b["x"], b["y"]), (c["x"], c["y"]))
            if (dab + bc) <= loop_thresh_m:
                cleaned.pop(-2)  # B 제거
    return cleaned

def throttle_points_by_distance(pts: List[Tuple[float,float]], min_step_m: float) -> List[Tuple[float,float]]:
    """연속 포인트 중 거리가 min_step_m 미만이면 건너뜀 (지그재그 억제)"""
    if not pts:
        return pts
    out = [pts[0]]
    acc = 0.0
    for p in pts[1:]:
        d = haversine_m(out[-1], p)
        acc += d
        if acc >= min_step_m:
            out.append(p)
            acc = 0.0
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out

def _build_node_kdtree(G: nx.MultiDiGraph):
    nodes, data = zip(*G.nodes(data=True))
    xy = np.array([[d["x"], d["y"]] for d in data], dtype=float)  # (lng, lat)
    tree = cKDTree(xy)
    return np.array(nodes), xy, tree

def nearest_node_sequence(G: nx.MultiDiGraph, pts_lnglat: List[Tuple[float, float]]) -> List[int]:
    nodes, xy, tree = _build_node_kdtree(G)
    q = np.array(pts_lnglat, dtype=float)
    _, idx = tree.query(q, k=1)
    seq = [int(nodes[i]) for i in np.atleast_1d(idx)]
    # 연속 중복 제거
    dedup = [seq[0]]
    for n in seq[1:]:
        if n != dedup[-1]:
            dedup.append(n)
    return dedup

def stitch_shortest_paths(G: nx.MultiDiGraph, node_seq: List[int], max_seg_m: float = 1500.0) -> Tuple[List[int], float, List[Tuple[float,float]]]:
    """
    인접 쌍을 최단경로로 이어붙임.
    - max_seg_m: 한 세그먼트가 과도하게 멀면(그래프상) 비정상 연결로 보고 skip
    """
    route: List[int] = []
    total_len = 0.0

    for u, v in zip(node_seq[:-1], node_seq[1:]):
        if u == v:
            if not route:
                route.append(u)
            continue
        try:
            sp = nx.shortest_path(G, u, v, weight="length")
            seg_len = nx.shortest_path_length(G, u, v, weight="length")
            if seg_len > max_seg_m:
                # 너무 먼 연결은 스킵(지그재그/되돌아감 방지)
                continue
        except nx.NetworkXNoPath:
            continue

        if route and route[-1] == sp[0]:
            route.extend(sp[1:])
        else:
            route.extend(sp)
        total_len += seg_len

    coords = []
    for n in route:
        nd = G.nodes[n]
        coords.append((float(nd["x"]), float(nd["y"])))
    route = prune_small_loops(G, route, loop_thresh_m=60.0)
    return route, total_len, coords

# --- public ---

def map_match_points(
    pts_lnglat: List[Tuple[float,float]],
    center_lat: float,
    center_lng: float,
    graph_radius_m: int = 3000,
    match_step_m: float = 80.0,      # 🔑 다운샘플 간격(기본 80m)
    max_seg_m: float = 1500.0        # 🔑 세그먼트 최대 허용 길이
) -> Dict:
    G = load_ped_graph(center_lat, center_lng, dist_m=graph_radius_m)

    # 1) 다운샘플
    pts_thin = throttle_points_by_distance(pts_lnglat, min_step_m=match_step_m)

    # 2) 최근접 노드 시퀀스
    node_seq = nearest_node_sequence(G, pts_thin)

    # 3) 최단경로 스티칭(과도한 세그먼트는 스킵)
    route_nodes, route_len_m, route_coords = stitch_shortest_paths(G, node_seq, max_seg_m=max_seg_m)

    return {
        "matched": bool(route_nodes),
        "route_nodes": route_nodes,
        "route_length_m": route_len_m,
        "route_coords_lnglat": route_coords,
        "used_point_count": len(pts_thin)
    }
