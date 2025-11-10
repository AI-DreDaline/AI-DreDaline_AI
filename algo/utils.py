# algo/utils.py
from __future__ import annotations
from shapely.geometry import Point, LineString
import math
import numpy as np

def line_length_km(line_proj: LineString) -> float:
    return float(line_proj.length) / 1000.0

def densify_line(line_proj: LineString, step: float):
    coords = list(line_proj.coords)
    if len(coords) < 2:
        return [Point(*coords[0])]
    acc = [Point(coords[0])]
    remain = 0.0
    for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
        seg_len = math.hypot(x2 - x1, y2 - y1)
        d = remain
        while d + step <= seg_len:
            t = (d + step) / seg_len
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            acc.append(Point(x, y))
            d += step
        remain = (d + step) - seg_len
    if acc[-1] != Point(coords[-1]):
        acc.append(Point(coords[-1]))
    return acc

def thin_points(pts, min_gap):
    out, last = [], None
    for p in pts:
        if last is None or p.distance(last) >= min_gap:
            out.append(p); last = p
    return out

def nearest_node_id_array(nodes_proj_gdf):
    import numpy as np
    node_xy = np.column_stack([nodes_proj_gdf.geometry.x.values, nodes_proj_gdf.geometry.y.values])
    node_ids = nodes_proj_gdf.index.values
    return node_xy, node_ids

def nearest_node_id(node_xy, node_ids, x, y):
    d2 = (node_xy[:,0]-x)**2 + (node_xy[:,1]-y)**2
    return node_ids[d2.argmin()]
