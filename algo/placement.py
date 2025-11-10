# algo/placement.py
from __future__ import annotations
import numpy as np
from shapely.geometry import LineString, Point
from shapely.affinity import rotate as shp_rotate, scale as shp_scale, translate as shp_translate

def graph_bounds(nodes_gdf):
    minx, miny, maxx, maxy = nodes_gdf.total_bounds
    return (minx, miny, maxx, maxy)

def place_svg_in_graph_bbox(shape_norm: LineString, nodes_proj_gdf, canvas_frac: float = 0.75, global_rot_deg: float = 0.0):
    minx, miny, maxx, maxy = graph_bounds(nodes_proj_gdf); W, H = (maxx-minx), (maxy-miny)
    cx = minx + (1-canvas_frac)*0.5*W; cy = miny + (1-canvas_frac)*0.5*H
    cw = W*canvas_frac; ch = H*canvas_frac
    coords = np.array(shape_norm.coords, dtype=float)
    xs = cx + coords[:,0]*cw; ys = cy + coords[:,1]*ch
    placed = LineString(list(zip(xs.tolist(), ys.tolist())))
    if abs(global_rot_deg) > 0:
        placed = shp_rotate(placed, angle=global_rot_deg, origin=(placed.centroid.x, placed.centroid.y), use_radians=False)
    return placed

def place_shape_near_start(line_proj: LineString, start_proj_point: Point, alpha: float = 0.6, max_shift_m: float = 1500.0) -> LineString:
    c = line_proj.centroid; vx, vy = (start_proj_point.x - c.x, start_proj_point.y - c.y)
    mag = (vx**2 + vy**2) ** 0.5
    scale = min(alpha, (max_shift_m / mag)) if mag > 1e-9 else 0.0
    return shp_translate(line_proj, xoff=vx * scale, yoff=vy * scale)

def scale_shape(line_proj: LineString, scale: float) -> LineString:
    return shp_scale(line_proj, xfact=scale, yfact=scale, origin=(line_proj.centroid.x, line_proj.centroid.y))
