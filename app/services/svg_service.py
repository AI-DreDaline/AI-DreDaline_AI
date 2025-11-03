# app/services/svg_service.py
from __future__ import annotations
import io
import math
from typing import List, Tuple, Dict

import numpy as np
from shapely.geometry import LineString
from shapely.affinity import scale as shp_scale, rotate as shp_rotate, translate as shp_translate
from shapely.ops import transform as shp_transform
from svgpathtools import svg2paths2, Path
from pyproj import Transformer


def _svg_to_linestring(paths: List[Path], resample_m: float = 5.0) -> LineString:
    """SVG Path들을 균일 샘플링해서 LineString으로 합치기 (임의 단위)"""
    coords = []
    for p in paths:
        # 길이가 0인 세그먼트 방지용
        n = max(2, int(max(p.length(), 1e-6) / max(resample_m, 1e-6)))
        ts = np.linspace(0, 1, n)
        pts = [p.point(t) for t in ts]
        coords.extend([(pt.real, pt.imag) for pt in pts])
    return LineString(coords)


def _scale_to_target_length(ls: LineString, target_m: float) -> Tuple[LineString, float]:
    """현재(단위less) 길이를 target_m(미터)에 맞추는 스케일 팩터 적용"""
    cur_len = ls.length
    if cur_len <= 0:
        raise ValueError("SVG path length is zero.")
    s = target_m / cur_len
    return shp_scale(ls, xfact=s, yfact=s, origin=(0, 0)), s


def _move_first_point_to_origin(ls: LineString) -> LineString:
    """첫 점을 (0,0)으로 이동"""
    x0, y0 = ls.coords[0]
    return shp_translate(ls, xoff=-x0, yoff=-y0)


def _resample_by_step(ls: LineString, step_m: float) -> LineString:
    """등간격(step_m)으로 끝점 포함 재샘플 (모든 점 Point 기반으로 일관 처리)"""
    if ls.length <= 0:
        return ls
    n = max(2, int(np.floor(ls.length / max(step_m, 1e-6))) + 1)
    dists = np.linspace(0.0, ls.length, n)
    coords = []
    for d in dists:
        pt = ls.interpolate(d)  # shapely Point
        coords.append((pt.x, pt.y))
    # 연속 동일 좌표 제거(수치 오차 방지)
    dedup = [coords[0]]
    for x, y in coords[1:]:
        if (x, y) != dedup[-1]:
            dedup.append((x, y))
    return LineString(dedup)


def parse_svg(
    svg_text: str,
    target_km: float,
    start_xy: Tuple[float, float],   # (lng, lat)
    resample_m: float = 5.0,
    rotate_deg: float = 0.0,
    step_m: float = 5.0
) -> Dict:
    """
    파이프라인:
      1) SVG → LineString(임의 단위)
      2) target 길이(미터)로 스케일  ※ 위도 보정 포함(경도 축 수축 보정)
      3) 회전
      4) 첫 점을 원점으로 정렬
      5) EPSG:3857(미터) 좌표계로 시작점(x_m,y_m)만큼 평행이동
      6) (미터 좌표계에서) step_m 간격 리샘플
      7) 경도/위도(EPSG:4326)로 역변환 → 반환
    """
    # 좌표 변환기 준비
    to_m = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
    to_lonlat = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True).transform

    # 1) SVG 파싱
    paths, _, _ = svg2paths2(io.StringIO(svg_text))
    if not paths:
        raise ValueError("No valid <path> found in SVG")

    ls = _svg_to_linestring(paths, resample_m=resample_m)  # 임의단위

    # 2) 위도 보정 포함 target 길이(미터)
    #    경도 방향은 위도에 따라 cos(lat) 비율로 수축되므로 1/cos(lat)로 보정
    lat = float(start_xy[1])
    scale_lon = 1.0 / max(math.cos(math.radians(lat)), 1e-9)  # 안전 분모
    target_m = float(target_km) * 1000.0 * scale_lon

    #    target_m 으로 스케일 (이 시점의 좌표계는 여전히 '임의 단위'지만,
    #    곧 EPSG:3857로 이동하므로 길이 비례만 맞추면 됨)
    ls, scale_factor = _scale_to_target_length(ls, target_m=target_m)

    # 3) 회전
    if abs(rotate_deg) > 1e-9:
        ls = shp_rotate(ls, rotate_deg, origin=(0, 0), use_radians=False)

    # 4) 첫 점을 원점으로
    ls = _move_first_point_to_origin(ls)

    # 5) 시작점(lng,lat)을 EPSG:3857(미터)로 옮겨 평행 이동
    start_lng, start_lat = start_xy
    start_x_m, start_y_m = to_m(start_lng, start_lat)  # (m, m)
    ls = shp_translate(ls, xoff=start_x_m, yoff=start_y_m)

    # 6) 미터 좌표계에서 등간격 리샘플
    ls = _resample_by_step(ls, step_m=step_m)

    # 7) EPSG:4326으로 역변환
    ls_lonlat = shp_transform(to_lonlat, ls)  # (lng, lat)
    points = list(ls_lonlat.coords)

    return {
        "ok": True,
        "scale_m_per_unit": float(scale_factor),
        # 스케일 후 기대 길이(보정 반영). 실제 맵매칭 결과와는 다를 수 있음
        "template_length_m": float(target_m),
        "points": points,
    }
