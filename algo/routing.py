# algo/routing.py
from __future__ import annotations
from shapely.geometry import LineString, Point
from typing import List, Optional
import networkx as nx
from .utils import densify_line, thin_points, nearest_node_id_array, nearest_node_id, line_length_km

def build_shape_biased_costs(G_proj, nodes_proj_gdf, shape_line_proj: LineString, lam: float = 0.03, attr_name: str = "shape_cost"):
    def get_xy(nid):
        g = nodes_proj_gdf.loc[nid].geometry; return (g.x, g.y)
    from shapely.geometry import LineString as LS
    for u,v,k,data in G_proj.edges(keys=True, data=True):
        geom = data.get("geometry")
        if geom is None:
            x1,y1 = get_xy(u); x2,y2 = get_xy(v)
            geom = LS([(x1,y1),(x2,y2)]); data["geometry"] = geom
        length = float(data.get("length", geom.length))
        mid = geom.interpolate(0.5, normalized=True)
        dist = float(shape_line_proj.distance(mid))
        data[attr_name] = length * (1.0 + lam * dist)

def sample_anchors(line_proj: LineString, n: int = 10) -> List[Point]:
    return [line_proj.interpolate(i/n, normalized=True) for i in range(n+1)]

def route_via_shape(G_proj, nodes_proj_gdf, line_proj: LineString, step_m: float, min_gap_m: float,
                    center_lat: float, center_lng: float, return_to_start: bool = True, weight_key: str = "length"):
    import osmnx as ox
    from shapely.geometry import Point as ShpPoint
    wps = thin_points(densify_line(line_proj, step=step_m), min_gap=min_gap_m)
    center_proj = ox.projection.project_geometry(ShpPoint(center_lng, center_lat), crs="EPSG:4326", to_crs=nodes_proj_gdf.crs)[0]
    if return_to_start:
        wps = [center_proj] + wps + [center_proj]

    node_xy, node_ids = nearest_node_id_array(nodes_proj_gdf)
    snaps = []
    for p in wps:
        nid = nearest_node_id(node_xy, node_ids, p.x, p.y)
        if not snaps or snaps[-1] != nid: snaps.append(nid)

    rnodes = []
    for a,b in zip(snaps[:-1], snaps[1:]):
        try:
            sp = nx.shortest_path(G_proj, a, b, weight=weight_key)
            rnodes.extend(sp[1:] if (rnodes and rnodes[-1] == sp[0]) else sp)
        except nx.NetworkXNoPath:
            continue
    if not rnodes: return None, None
    coords = nodes_proj_gdf.loc[rnodes].geometry.apply(lambda g: (g.x, g.y)).tolist()
    return rnodes, LineString(coords)

def route_via_anchors(G_proj, nodes_proj_gdf, anchor_points: List[Point], weight_key: str = "shape_cost",
                      start_proj_point: Optional[Point] = None, connect_from_start: bool = True,
                      max_connector_m: float = 600.0, return_to_start: bool = False):
    node_xy, node_ids = nearest_node_id_array(nodes_proj_gdf)
    # anchor snaps
    anchor_nids = []
    for p in anchor_points:
        nid = nearest_node_id(node_xy, node_ids, p.x, p.y)
        if not anchor_nids or anchor_nids[-1] != nid: anchor_nids.append(nid)

    snaps = []
    # short connector
    if start_proj_point is not None and connect_from_start and anchor_nids:
        start_nid = nearest_node_id(node_xy, node_ids, start_proj_point.x, start_proj_point.y)
        def node_xy_of(nid): g = nodes_proj_gdf.loc[nid].geometry; return g.x, g.y
        sx, sy = start_proj_point.x, start_proj_point.y
        dists = [((node_xy_of(n)[0]-sx)**2 + (node_xy_of(n)[1]-sy)**2)**0.5 for n in anchor_nids]
        k = int(__import__("numpy").argmin(dists))
        if dists[k] <= max_connector_m:
            snaps.append(start_nid)
            if start_nid != anchor_nids[k]: snaps.append(anchor_nids[k])

    snaps.extend(anchor_nids)

    if return_to_start and start_proj_point is not None and snaps:
        start_nid = nearest_node_id(node_xy, node_ids, start_proj_point.x, start_proj_point.y)
        if snaps[-1] != start_nid: snaps.append(start_nid)

    rnodes = []
    for a,b in zip(snaps[:-1], snaps[1:]):
        try:
            sp = nx.shortest_path(G_proj, a, b, weight=weight_key)
            rnodes.extend(sp[1:] if (rnodes and rnodes[-1] == sp[0]) else sp)
        except nx.NetworkXNoPath:
            continue
    if not rnodes: return None, None
    coords = nodes_proj_gdf.loc[rnodes].geometry.apply(lambda g: (g.x, g.y)).tolist()
    return rnodes, LineString(coords)
