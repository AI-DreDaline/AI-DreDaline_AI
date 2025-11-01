# app/services/svg_service.py
from __future__ import annotations
from typing import List, Tuple, Optional
import re

# 선택 의존성
try:
    from svgpathtools import svg2paths, parse_path
    _HAS_SVGPATH = True
except Exception:
    _HAS_SVGPATH = False

# ---- public API ----
def parse_svg_inline(svg_text: str, *, resample_m: float = 5.0,
                     simplify_tolerance: float = 0.0, max_points: int = 5000
                     ) -> List[Tuple[float, float]]:
    """<path d='...'>들을 균등 리샘플한 (x,y) 폴리라인으로 반환"""
    ds = _extract_path_d(svg_text)
    if not ds and _HAS_SVGPATH:
        try:
            paths, _ = svg2paths(string=svg_text)
            ds = [p.d() for p in paths if hasattr(p, "d")]
        except Exception:
            pass
    if not ds:
        return [(10,10),(90,10),(90,90),(10,90),(10,10)]  # 안전망

    pts: List[Tuple[float,float]] = []
    for d in ds:
        pts.extend(_resample_path_d(d, resample_m, max_points))
    if len(pts) > max_points:
        pts = pts[:max_points]
    return pts

# ---- internals ----
_PATH_D_RE = re.compile(r'<path[^>]*\sd="([^"]+)"[^>]*>', re.IGNORECASE)

def _extract_path_d(svg_text: str) -> list[str]:
    return _PATH_D_RE.findall(svg_text or "")

def _resample_path_d(d: str, gap: float, max_points: int) -> list[tuple[float,float]]:
    if _HAS_SVGPATH:
        try:
            p = parse_path(d)
            L = p.length()
            if L <= 0: return []
            n = max(2, min(int(L/max(gap,1e-6))+1, max_points))
            ts = [i/(n-1) for i in range(n)]
            return [(complex(p.point(t)).real, complex(p.point(t)).imag) for t in ts]
        except Exception:
            pass
    # 폴백: 숫자만 뽑아 M/L 형태로 해석
    nums = re.findall(r'[-+]?\d*\.?\d+(?:e[-+]?\d+)?', d)
    vals = [float(v) for v in nums]
    out=[]
    for i in range(0, len(vals), 2):
        if i+1 < len(vals): out.append((vals[i], vals[i+1]))
    return out[:max_points]
