# algo/svg_loader.py
from __future__ import annotations
from typing import List, Tuple, Optional
import numpy as np
from shapely.geometry import LineString
from svgpathtools import svg2paths2

def endpoints(ls: LineString):
    arr = np.array(ls.coords); return arr[0], arr[-1]

def reorder_lines_min_bridges(lines: List[LineString]) -> Optional[LineString]:
    if not lines: return None
    lines = [ls for ls in lines if len(ls.coords) >= 2]
    if not lines: return None

    def sort_key(ls):
        s, e = endpoints(ls); x, y = min(s[0], e[0]), min(s[1], e[1]); return (x, y)
    lines = sorted(lines, key=sort_key)
    path = [lines[0]]; unused = lines[1:]
    while unused:
        _, p_end = endpoints(path[-1])
        best_i, best_rev, best_d = None, False, 1e18
        for i, cand in enumerate(unused):
            s, e = endpoints(cand)
            for rev, comp in [(False, s), (True, e)]:
                d = np.linalg.norm(np.array(p_end) - np.array(comp))
                if d < best_d: best_i, best_rev, best_d = i, rev, d
        nxt = unused.pop(best_i)
        if best_rev: nxt = LineString(list(nxt.coords)[::-1])
        merged = list(path[-1].coords) + [list(path[-1].coords)[-1], list(nxt.coords)[0]] + list(nxt.coords)
        path[-1] = LineString(merged)
    return path[0]

def normalize_coords(coords: List[Tuple[float, float]], flip_y=True):
    arr = np.array(coords, dtype=float)
    if flip_y: arr[:,1] = -arr[:,1]
    minv = arr.min(axis=0); maxv = arr.max(axis=0); span = np.where((maxv-minv)==0, 1, (maxv-minv))
    arr01 = (arr - minv)/span
    return [tuple(map(float, pt)) for pt in arr01]

def svg_to_polyline(svg_path, path_index="auto", samples_per_seg=80, simplify=0.0, flip_y=True) -> LineString:
    paths, attrs, svg_att = svg2paths2(str(svg_path))
    indices = range(len(paths)) if path_index == "auto" else [int(path_index)]
    parts = []
    for idx in indices:
        p = paths[idx]
        N = max(samples_per_seg * max(1, len(p)), samples_per_seg)
        t = np.linspace(0, 1, int(N))
        xys = [(p.point(tt).real, p.point(tt).imag) for tt in t]
        parts.append(LineString(xys))
    if simplify and simplify > 0:
        parts = [ls.simplify(simplify, preserve_topology=True) for ls in parts]
    merged = reorder_lines_min_bridges(parts)
    if merged is None: raise ValueError("No valid path extracted from SVG.")
    norm = normalize_coords(list(merged.coords), flip_y=flip_y)
    return LineString(norm)
