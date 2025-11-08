# algo/map_match.py
from __future__ import annotations
from typing import List, Tuple, Optional
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString
from shapely.ops import linemerge

def _shortest_path_coords(G, u, v) -> List[Tuple[float, float]]:
    # u→v 최단경로(길이 기준) 노드열로 구해서 좌표로 펼치기
    nodes = nx.shortest_path(G, u, v, weight="length")
    coords = []
    for a, b in zip(nodes[:-1], nodes[1:]):
        data = min(G.get_edge_data(a, b).values(), key=lambda d: d.get("length", 1))
        geom = data.get("geometry")
        if geom is None:
            coords.extend([(G.nodes[a]["y"], G.nodes[a]["x"]), (G.nodes[b]["y"], G.nodes[b]["x"])])
        else:
            coords.extend([(lat, lon) for lon, lat in geom.coords])
    # 중복 제거
    dedup = []
    for p in coords:
        if not dedup or p != dedup[-1]:
            dedup.append(p)
    return dedup

def map_match_coords(
    coords_wgs84: List[Tuple[float, float]],  # [(lat, lng), ...]
    G,
    step: int = 10
) -> List[Tuple[float, float]]:
    """
    간단 맵매칭: 입력 포인트들을 일정 간격으로 샘플링해
    각 점을 '가장 가까운 노드'에 스냅 → 인접 샘플들 사이를
    최단경로로 연결해서 도로망을 따르는 라인을 만든다.
    step: 샘플링 간격(포인트 개수 기준). 숫자가 클수록 빠르나 정밀도↓
    """
    if len(coords_wgs84) < 2:
        return coords_wgs84

    # 1) 좌표를 일정 간격으로 줄이기
    idxs = list(range(0, len(coords_wgs84), step))
    if idxs[-1] != len(coords_wgs84) - 1:
        idxs.append(len(coords_wgs84) - 1)
    key_pts = [coords_wgs84[i] for i in idxs]

    # 2) 각 점을 그래프의 최근접 노드로 스냅
    snapped_nodes = []
    for lat, lng in key_pts:
        nid = ox.nearest_nodes(G, X=lng, Y=lat)
        snapped_nodes.append(nid)

    # 3) 인접 스냅 노드 쌍 사이를 최단경로로 연결
    matched = []
    for a, b in zip(snapped_nodes[:-1], snapped_nodes[1:]):
        seg = _shortest_path_coords(G, a, b)
        if matched and seg and matched[-1] == seg[0]:
            seg = seg[1:]
        matched.extend(seg)

    return matched
