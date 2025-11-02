# app/services/match_service.py
from __future__ import annotations
from typing import List, Tuple, Dict
import numpy as np
import networkx as nx
import osmnx as ox
from scipy.spatial import cKDTree

# ✅ 추가: edge length 유틸은 distance 서브모듈에 있어요
try:
    from osmnx.distance import add_edge_lengths  # osmnx >= 1.3
except Exception:
    add_edge_lengths = None  # 아주 구버전 대비

_GRAPH_CACHE: Dict[str, nx.MultiDiGraph] = {}

def load_ped_graph(center_lat: float, center_lng: float, dist_m: int = 3000) -> nx.MultiDiGraph:
    key = f"{round(center_lat,5)}_{round(center_lng,5)}_{dist_m}"
    if key in _GRAPH_CACHE:
        return _GRAPH_CACHE[key]

    G = ox.graph_from_point((center_lat, center_lng), dist=dist_m,
                            network_type="walk", simplify=True)

    # ✅ edge length 보장
    if add_edge_lengths is not None:
        add_edge_lengths(G)
    # 일부 버전은 이미 length가 들어있기도 함(그럼 이 단계는 no-op)

    _GRAPH_CACHE[key] = G
    return G

def _build_node_kdtree(G: nx.MultiDiGraph):
    nodes, data = zip(*G.nodes(data=True))
    # OSMnx 노드는 data["x"]=lng, data["y"]=lat
    xy = np.array([[d["x"], d["y"]] for d in data], dtype=float)
    tree = cKDTree(xy)
    return np.array(nodes), xy, tree

def nearest_node_sequence(G: nx.MultiDiGraph, pts_lnglat: List[Tuple[float, float]]) -> List[int]:
    nodes, xy, tree = _build_node_kdtree(G)
    q = np.array(pts_lnglat, dtype=float)  # [[lng,lat], ...]
    _, idx = tree.query(q, k=1)
    seq = [int(nodes[i]) for i in np.atleast_1d(idx)]
    # 연속 중복 노드 제거
    dedup = [seq[0]]
    for n in seq[1:]:
        if n != dedup[-1]:
            dedup.append(n)
    return dedup

def stitch_shortest_paths(G: nx.MultiDiGraph, node_seq: List[int]) -> Tuple[List[int], float, List[Tuple[float,float]]]:
    """
    인접한 노드쌍을 최단경로로 이어붙여 하나의 경로로 만듦.
    반환: (route_nodes, route_length_m, route_coords_lnglat)
    """
    route: List[int] = []
    for u, v in zip(node_seq[:-1], node_seq[1:]):
        if u == v:
            if not route:
                route.append(u)
            continue
        try:
            sp = nx.shortest_path(G, u, v, weight="length")
        except nx.NetworkXNoPath:
            continue
        if not sp:
            continue
        if route and route[-1] == sp[0]:
            route.extend(sp[1:])
        else:
            route.extend(sp)

    # 길이 합산
    total_len = 0.0
    if len(route) >= 2:
        edge_lengths = ox.utils_graph.get_route_edge_attributes(G, route, "length")
        # get_route_edge_attributes가 edge별 length 리스트를 반환
        total_len = float(sum(edge_lengths)) if isinstance(edge_lengths, list) else float(edge_lengths)

    # 좌표 추출 (lng, lat)
    coords = []
    for n in route:
        nd = G.nodes[n]
        coords.append((float(nd["x"]), float(nd["y"])))
    return route, total_len, coords

def map_match_points(
    pts_lnglat: List[Tuple[float,float]],
    center_lat: float,
    center_lng: float,
    graph_radius_m: int = 3000
) -> Dict:
    G = load_ped_graph(center_lat, center_lng, dist_m=graph_radius_m)
    node_seq = nearest_node_sequence(G, pts_lnglat)
    route_nodes, route_len_m, route_coords = stitch_shortest_paths(G, node_seq)
    return {
        "matched": bool(route_nodes),
        "route_nodes": route_nodes,
        "route_length_m": route_len_m,
        "route_coords_lnglat": route_coords,
    }
