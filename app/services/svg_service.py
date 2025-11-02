# app/services/svg_service.py
from __future__ import annotations
import io
from typing import List, Tuple, Dict
import numpy as np
from shapely.geometry import LineString
from shapely.affinity import scale, rotate, translate
from svgpathtools import svg2paths2, Path

# ======================================================
# 🔹 SVG 파싱 및 처리 유틸
# ======================================================

def _svg_to_linestring(paths: List[Path], resample_m: float = 5.0) -> LineString:
    """SVG Path 객체들을 일정 간격으로 샘플링해 LineString으로 변환"""
    coords = []
    for p in paths:
        n = max(2, int(p.length() / resample_m))
        ts = np.linspace(0, 1, n)
        pts = [p.point(t) for t in ts]
        coords.extend([(pt.real, pt.imag) for pt in pts])
    return LineString(coords)

def _scale_to_target_length(ls: LineString, target_m: float) -> Tuple[LineString, float]:
    """라인을 목표 거리(m)에 맞게 스케일"""
    cur_len = ls.length
    if cur_len == 0:
        raise ValueError("SVG path length is zero.")
    scale_factor = target_m / cur_len
    scaled = scale(ls, xfact=scale_factor, yfact=scale_factor, origin=(0, 0))
    return scaled, scale_factor

def _rotate(ls: LineString, deg: float) -> LineString:
    return rotate(ls, deg, origin=(0, 0), use_radians=False)

def _move_to_start(ls: LineString, start_xy: Tuple[float, float]) -> LineString:
    first_x, first_y = ls.coords[0]
    dx = start_xy[0] - first_x
    dy = start_xy[1] - first_y
    return translate(ls, xoff=dx, yoff=dy)

def _resample(ls: LineString, step_m: float = 5.0) -> LineString:
    """라인을 일정 간격으로 다시 샘플링"""
    if ls.length == 0:
        return ls
    distances = np.arange(0, ls.length, step_m)
    pts = [ls.interpolate(d) for d in distances]
    return LineString([(p.x, p.y) for p in pts])

# ======================================================
# 🔹 외부에서 호출하는 주요 함수
# ======================================================

def parse_svg(svg_text: str, target_km: float, start_xy: Tuple[float, float],
              resample_m: float = 5.0, rotate_deg: float = 0.0, step_m: float = 5.0) -> Dict:
    """
    1. SVG 텍스트 파싱
    2. target_km 길이에 맞게 스케일
    3. 회전 및 시작점 이동
    4. 일정 간격으로 재샘플링
    """
    # 1️⃣ SVG 로드
    paths, attrs, svg_attrs = svg2paths2(io.StringIO(svg_text))
    if not paths:
        raise ValueError("No valid <path> found in SVG")

    # 2️⃣ Path → LineString
    line = _svg_to_linestring(paths, resample_m)

    # 3️⃣ 스케일 조정
    scaled, scale_factor = _scale_to_target_length(line, target_m=target_km * 1000)

    # 4️⃣ 회전
    rotated = _rotate(scaled, rotate_deg)

    # 5️⃣ 시작점 이동
    moved = _move_to_start(rotated, start_xy)

    # 6️⃣ 균일 리샘플링
    resampled = _resample(moved, step_m)

    return {
        "ok": True,
        "scale_m_per_unit": scale_factor,
        "template_length_m": resampled.length,
        "points": list(resampled.coords)
    }
