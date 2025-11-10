# algo/notebook_port.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from pathlib import Path
import math
import pickle
import numpy as np
import networkx as nx
import osmnx as ox
from shapely.geometry import Point, LineString
from shapely.affinity import rotate as shp_rotate, scale as shp_scale, translate as shp_translate

# ---------- OSMnx 기본 설정 ----------
ox.settings.use_cache = True
ox.settings.log_console = False


# =========================
# Geometry / SVG Utilities
# =========================
def project_graph(G):
    """Project to a suitable metric CRS."""
    return ox.project_graph(G)

def graph_bounds(nodes_gdf):
    minx, miny, maxx, maxy = nodes_gdf.total_bounds
    return (minx, miny, maxx, maxy)

def endpoints(ls: LineString):
    coords = np.array(ls.coords)
    return coords[0], coords[-1]

def reorder_lines_min_bridges(lines: List[LineString]) -> Optional[LineString]:
    """
    여러 SVG path 조각을 '최소 연결'로 하나의 경로로 엮는다.
    가장 가까운 종단을 이어붙이며 단일 LineString으로 만든다.
    """
    if not lines:
        return None
    lines = [ls for ls in lines if len(ls.coords) >= 2]
    if not lines:
        return None

    def sort_key(ls):
        s, e = endpoints(ls)
        x, y = min(s[0], e[0]), min(s[1], e[1])
        return (x, y)

    lines = sorted(lines, key=sort_key)
    path = [lines[0]]
    unused = lines[1:]

    while unused:
        _, p_end = endpoints(path[-1])
        best_i, best_rev, best_d = None, False, 1e18
        for i, cand in enumerate(unused):
            s, e = endpoints(cand)
            for rev, comp in [(False, s), (True, e)]:
                d = np.linalg.norm(np.array(p_end) - np.array(comp))
                if d < best_d:
                    best_i, best_rev, best_d = i, rev, d
        nxt = unused.pop(best_i)
        if best_rev:
            nxt = LineString(list(nxt.coords)[::-1])

        merged = list(path[-1].coords) + [list(path[-1].coords)[-1], list(nxt.coords)[0]] + list(nxt.coords)
        path[-1] = LineString(merged)

    return path[0]

def normalize_coords(coords: List[Tuple[float, float]], flip_y=True):
    """
    SVG 좌표를 0..1 박스로 정규화. 필요시 Y축을 뒤집음(웹-SVG 상하 반전 보정).
    """
    arr = np.array(coords, dtype=float)
    if flip_y:
        arr[:, 1] = -arr[:, 1]
    minv = arr.min(axis=0)
    maxv = arr.max(axis=0)
    span = np.where((maxv - minv) == 0, 1, (maxv - minv))
    arr01 = (arr - minv) / span
    return [tuple(map(float, pt)) for pt in arr01]

def svg_to_polyline(svg_path: Path, path_index="auto", samples_per_seg=80, simplify=0.0, flip_y=True) -> LineString:
    """
    SVG를 일정 샘플 간격의 폴리라인(LineString)으로 변환 → 0..1 범위로 정규화.
    """
    from svgpathtools import svg2paths2
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
    if merged is None:
        raise ValueError("No valid path extracted from SVG.")
    norm = normalize_coords(list(merged.coords), flip_y=flip_y)
    return LineString(norm)

def line_length_km(line_proj: LineString) -> float:
    return float(line_proj.length) / 1000.0

def densify_line(line_proj: LineString, step: float) -> List[Point]:
    """투영 좌표계 기준 LineString을 일정 간격으로 촘촘히 샘플링."""
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

def thin_points(pts: List[Point], min_gap: float) -> List[Point]:
    """너무 가까운 포인트는 제거."""
    out = []
    last = None
    for p in pts:
        if last is None or p.distance(last) >= min_gap:
            out.append(p)
            last = p
    return out


# =========================
# Graph IO / Placement
# =========================
def load_graph_cached(center_lat: float, center_lng: float, dist_m: int, cache_dir: Path) -> nx.MultiDiGraph:
    """
    거리 dist_m 반경 도보 네트워크를 캐시/로드.
    cache_dir 는 '디렉토리'여야 함.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"graph_{center_lat:.4f}_{center_lng:.4f}_{dist_m}.pkl"
    fpath = cache_dir / key
    if fpath.exists():
        with open(fpath, "rb") as f:
            return pickle.load(f)
    G = ox.graph_from_point((center_lat, center_lng), dist=dist_m, network_type="walk")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    with open(fpath, "wb") as f:
        pickle.dump(G, f)
    return G

def place_svg_in_graph_bbox(
    shape_norm: LineString,
    nodes_proj_gdf,
    canvas_frac: float = 0.48,
    global_rot_deg: float = 0.0,
) -> LineString:
    """
    그래프 외곽 bbox 안에 SVG(0..1)를 적당한 크기로 스케일 후 회전해 배치.
    """
    minx, miny, maxx, maxy = graph_bounds(nodes_proj_gdf)
    W, H = (maxx - minx), (maxy - miny)

    cx = minx + (1 - canvas_frac) * 0.5 * W
    cy = miny + (1 - canvas_frac) * 0.5 * H
    cw = W * canvas_frac
    ch = H * canvas_frac

    coords = np.array(shape_norm.coords, dtype=float)
    xs = cx + coords[:, 0] * cw
    ys = cy + coords[:, 1] * ch
    placed = LineString(list(zip(xs.tolist(), ys.tolist())))

    if abs(global_rot_deg) > 0:
        placed = shp_rotate(
            placed,
            angle=global_rot_deg,
            origin=(placed.centroid.x, placed.centroid.y),
            use_radians=False,
        )
    return placed


# =========================
# Map Matching Helpers
# =========================
def nearest_node_id_array(nodes_proj_gdf):
    node_xy = np.column_stack([nodes_proj_gdf.geometry.x.values, nodes_proj_gdf.geometry.y.values])
    node_ids = nodes_proj_gdf.index.values
    return node_xy, node_ids

def nearest_node_id(node_xy: np.ndarray, node_ids: np.ndarray, x: float, y: float):
    d2 = (node_xy[:, 0] - x) ** 2 + (node_xy[:, 1] - y) ** 2
    return node_ids[d2.argmin()]

def build_shape_biased_costs(
    G_proj,
    nodes_proj_gdf,
    shape_line_proj: LineString,
    lam: float = 0.03,
    attr_name: str = "shape_cost",
):
    """
    각 엣지에 shape bias 비용을 부여:
    weight = length * (1 + lam * dist_to_shape)
    dist_to_shape: 엣지 중앙점에서 도형 라인까지의 최단거리(미터, 투영 CRS)
    lam을 키우면 도형 근처를 더 선호(0.02~0.06 추천)
    """
    def get_xy(nid):
        g = nodes_proj_gdf.loc[nid].geometry
        return (g.x, g.y)

    for u, v, k, data in G_proj.edges(keys=True, data=True):
        geom = data.get("geometry")
        if geom is None:
            x1, y1 = get_xy(u)
            x2, y2 = get_xy(v)
            geom = LineString([(x1, y1), (x2, y2)])
            data["geometry"] = geom

        length = float(data.get("length", geom.length))
        mid = geom.interpolate(0.5, normalized=True)
        dist = float(shape_line_proj.distance(mid))
        data[attr_name] = length * (1.0 + lam * dist)

def sample_anchors(line_proj: LineString, n: int = 10) -> List[Point]:
    """
    라인 길이를 기준으로 0..1 구간을 n등분해서 포인트 추출.
    별처럼 꼭짓점이 많은 도형은 10~14 추천.
    """
    anchors = []
    for i in range(n + 1):
        anchors.append(line_proj.interpolate(i / n, normalized=True))
    return anchors

def route_via_shape(
    G_proj, nodes_proj_gdf,
    line_proj: LineString,
    step_m: float,
    min_gap_m: float,
    center_lat: float, center_lng: float,
    return_to_start: bool = True,
    weight_key: str = "length",  # <-- 'shape_cost' 사용 가능
):
    """촘촘한 샘플을 전부 잇는 방식(모양 보존력은 낮음 / 백업용)."""
    wps = densify_line(line_proj, step=step_m)
    wps = thin_points(wps, min_gap=min_gap_m)

    center_proj = ox.projection.project_geometry(
        Point(center_lng, center_lat), crs="EPSG:4326", to_crs=nodes_proj_gdf.crs
    )[0]
    if return_to_start:
        wps = [center_proj] + wps + [center_proj]

    node_xy, node_ids = nearest_node_id_array(nodes_proj_gdf)

    snaps = []
    for p in wps:
        nid = nearest_node_id(node_xy, node_ids, p.x, p.y)
        if not snaps or snaps[-1] != nid:
            snaps.append(nid)

    rnodes = []
    for a, b in zip(snaps[:-1], snaps[1:]):
        try:
            sp = nx.shortest_path(G_proj, a, b, weight=weight_key)
            if rnodes and rnodes[-1] == sp[0]:
                rnodes.extend(sp[1:])
            else:
                rnodes.extend(sp)
        except nx.NetworkXNoPath:
            continue

    if not rnodes:
        return None, None

    coords = nodes_proj_gdf.loc[rnodes].geometry.apply(lambda g: (g.x, g.y)).tolist()
    rline = LineString(coords)
    return rnodes, rline


# =========================
# 시작점 '근처' 배치 + 짧은 커넥터
# =========================
def place_shape_near_start(
    line_proj: LineString,
    start_proj_point: Point,
    alpha: float = 0.6,
    max_shift_m: float = 1500.0
) -> LineString:
    """
    도형의 중심을 start 쪽으로 alpha 비율만큼 부드럽게 당긴다.
    max_shift_m 로 이동량 상한도 건다.
    """
    c = line_proj.centroid
    vx, vy = (start_proj_point.x - c.x, start_proj_point.y - c.y)
    mag = (vx**2 + vy**2) ** 0.5
    if mag > 1e-9:
        scale = min(alpha, (max_shift_m / mag))
    else:
        scale = 0.0
    return shp_translate(line_proj, xoff=vx * scale, yoff=vy * scale)

def route_via_anchors(
    G_proj, nodes_proj_gdf,
    anchor_points: List[Point],
    weight_key: str = "shape_cost",
    start_proj_point: Point | None = None,
    connect_from_start: bool = True,
    max_connector_m: float = 600.0,
    return_to_start: bool = False
):
    """
    1) (선택) start → 가장 가까운 앵커까지 '한 번'만 연결(커넥터, 너무 멀면 생략)
    2) 앵커들 사이를 순서대로 최단경로 연결
    3) (선택) 마지막 → start로 닫기
    """
    node_xy, node_ids = nearest_node_id_array(nodes_proj_gdf)

    # 앵커 스냅
    anchor_nids = []
    for p in anchor_points:
        nid = nearest_node_id(node_xy, node_ids, p.x, p.y)
        if not anchor_nids or anchor_nids[-1] != nid:
            anchor_nids.append(nid)

    snaps = []

    # (1) 커넥터: start → 가장 가까운 앵커
    if start_proj_point is not None and connect_from_start and anchor_nids:
        start_nid = nearest_node_id(node_xy, node_ids, start_proj_point.x, start_proj_point.y)

        def node_xy_of(nid):
            g = nodes_proj_gdf.loc[nid].geometry
            return g.x, g.y

        sx, sy = start_proj_point.x, start_proj_point.y
        dists = []
        for nid in anchor_nids:
            x, y = node_xy_of(nid)
            dists.append(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5)
        k = int(np.argmin(dists))

        if dists[k] <= max_connector_m:
            snaps.append(start_nid)
            if start_nid != anchor_nids[k]:
                snaps.append(anchor_nids[k])
        # 너무 멀면 커넥터 생략: 별만 생성

    # (2) 나머지 앵커들 순회
    snaps.extend(anchor_nids)

    # (3) 닫기 옵션
    if return_to_start and start_proj_point is not None and snaps:
        start_nid = nearest_node_id(node_xy, node_ids, start_proj_point.x, start_proj_point.y)
        if snaps[-1] != start_nid:
            snaps.append(start_nid)

    # 최단경로 연결
    rnodes = []
    for a, b in zip(snaps[:-1], snaps[1:]):
        try:
            sp = nx.shortest_path(G_proj, a, b, weight=weight_key)
            if rnodes and rnodes[-1] == sp[0]:
                rnodes.extend(sp[1:])
            else:
                rnodes.extend(sp)
        except nx.NetworkXNoPath:
            continue

    if not rnodes:
        return None, None

    coords = nodes_proj_gdf.loc[rnodes].geometry.apply(lambda g: (g.x, g.y)).tolist()
    return rnodes, LineString(coords)


# =========================
# Fitting (Binary Search)
# =========================
@dataclass
class FitResult:
    scale_used: float
    route_nodes: List[int]
    route_line_proj: LineString
    actual_km: float
    template_tuned_proj: LineString

def _route_length_km_try(
    G_proj, nodes_proj_gdf,
    base_line: LineString,
    scale: float,
    step_m: float,
    min_gap_m: float,
    center_lat: float, center_lng: float,
    return_to_start: bool,
    use_anchors: bool,
    anchor_count: int,
    shape_bias_lambda: float,
    # 새 인자들
    start_proj_point: Point,
    connect_from_start: bool,
    max_connector_m: float,
    proximity_alpha: float,
    proximity_max_shift_m: float,
) -> tuple[Optional[List[int]], Optional[LineString], Optional[float]]:
    """주어진 scale에서 라우팅을 시도하고 길이(km)를 반환."""
    # 1) 스케일
    tuned = shp_scale(
        base_line,
        xfact=scale, yfact=scale,
        origin=(base_line.centroid.x, base_line.centroid.y)
    )

    # 2) 시작점 '근처'로 부드럽게 당기기
    tuned = place_shape_near_start(
        tuned, start_proj_point, alpha=proximity_alpha, max_shift_m=proximity_max_shift_m
    )

    # 3) 도형-근접 비용 부여
    build_shape_biased_costs(G_proj, nodes_proj_gdf, tuned, lam=shape_bias_lambda, attr_name="shape_cost")

    # 4) 라우팅
    if use_anchors:
        anchors = sample_anchors(tuned, n=anchor_count)
        rn, rl = route_via_anchors(
            G_proj, nodes_proj_gdf, anchors, weight_key="shape_cost",
            start_proj_point=start_proj_point,
            connect_from_start=connect_from_start,
            max_connector_m=max_connector_m,
            return_to_start=return_to_start
        )
        if rl is None:
            # 백업: 촘촘 방식 length로
            rn, rl = route_via_shape(
                G_proj, nodes_proj_gdf, tuned,
                step_m, min_gap_m, center_lat, center_lng,
                return_to_start, weight_key="length"
            )
    else:
        rn, rl = route_via_shape(
            G_proj, nodes_proj_gdf, tuned,
            step_m, min_gap_m, center_lat, center_lng,
            return_to_start, weight_key="shape_cost"
        )
        if rl is None:
            rn, rl = route_via_shape(
                G_proj, nodes_proj_gdf, tuned,
                step_m, min_gap_m, center_lat, center_lng,
                return_to_start, weight_key="length"
            )

    if rl is None:
        return None, None, None
    return rn, rl, line_length_km(rl)

def binary_scale_fit(
    G_proj, nodes_proj_gdf,
    mapped_base: LineString,
    target_km: float,
    tol_ratio: float,
    step_m: float,
    min_gap_m: float,
    center_lat: float, center_lng: float,
    return_to_start: bool = True,
    iters: int = 16,
    # 모양 보존 파라미터
    shape_bias_lambda: float = 0.03,
    anchor_count: int = 12,
    use_anchors: bool = True,
    # 시작점 '근처' 배치 + 커넥터 제어
    connect_from_start: bool = True,
    max_connector_m: float = 600.0,
    proximity_alpha: float = 0.6,
    proximity_max_shift_m: float = 1500.0,
) -> FitResult:
    """
    스케일 자동 브래킷 + shape-bias + 앵커 기반 라우팅으로 목표 거리 근접.
    별 모양은 유지하되 시작점 '근처'로 당겨지고,
    필요하면 짧은 커넥터로만 연결.
    """
    start_proj_point = ox.projection.project_geometry(
        Point(center_lng, center_lat), crs="EPSG:4326", to_crs=nodes_proj_gdf.crs
    )[0]

    # 0) 기준 스케일 1.0에서 길이 측정 (초기 해)
    rn0, rl0, km0 = _route_length_km_try(
        G_proj, nodes_proj_gdf, mapped_base, 1.0,
        step_m, min_gap_m, center_lat, center_lng, return_to_start,
        use_anchors, anchor_count, shape_bias_lambda,
        start_proj_point, connect_from_start, max_connector_m,
        proximity_alpha, proximity_max_shift_m
    )
    if rl0 is None:
        # 초기 실패 → 탐색 스케일 집합으로 시도
        test_scales = [0.5, 0.8, 1.5, 2.0, 2.5]
        found = None
        for s in test_scales:
            rn, rl, km = _route_length_km_try(
                G_proj, nodes_proj_gdf, mapped_base, s,
                step_m, min_gap_m, center_lat, center_lng, return_to_start,
                use_anchors, anchor_count, shape_bias_lambda,
                start_proj_point, connect_from_start, max_connector_m,
                proximity_alpha, proximity_max_shift_m
            )
            if rl is not None:
                rn0, rl0, km0 = rn, rl, km
                found = s
                break
        if found is None:
            raise RuntimeError("Failed to obtain initial feasible route for any test scale.")

    # 1) 목표 대비 비율로 브래킷 자동 설정
    ratio = max(0.1, min(10.0, target_km / max(1e-6, km0)))
    lo = max(0.05, ratio / 2.5)
    hi = min(6.0, ratio * 2.5)

    target_min = target_km * (1 - tol_ratio)
    target_max = target_km * (1 + tol_ratio)

    best = (1.0, rn0, rl0, km0, shp_scale(
        mapped_base, xfact=1.0, yfact=1.0,
        origin=(mapped_base.centroid.x, mapped_base.centroid.y)
    ))

    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        rn, rl, km = _route_length_km_try(
            G_proj, nodes_proj_gdf, mapped_base, mid,
            step_m, min_gap_m, center_lat, center_lng, return_to_start,
            use_anchors, anchor_count, shape_bias_lambda,
            start_proj_point, connect_from_start, max_connector_m,
            proximity_alpha, proximity_max_shift_m
        )
        if rl is None:
            # 연결 실패 → 더 크게
            lo = mid
            continue

        # 베스트 갱신
        if abs(km - target_km) < abs(best[3] - target_km):
            best = (mid, rn, rl, km, shp_scale(
                mapped_base, xfact=mid, yfact=mid,
                origin=(mapped_base.centroid.x, mapped_base.centroid.y)
            ))

        # 수렴 체크
        if target_min <= km <= target_max:
            best = (mid, rn, rl, km, shp_scale(
                mapped_base, xfact=mid, yfact=mid,
                origin=(mapped_base.centroid.x, mapped_base.centroid.y)
            ))
            break

        # 이분 탐색 방향
        if km < target_min:
            lo = mid  # 더 크게
        else:
            hi = mid  # 더 작게

    scale_used, route_nodes, route_line, Lkm, template_tuned = best
    return FitResult(scale_used, route_nodes, route_line, Lkm, template_tuned)
