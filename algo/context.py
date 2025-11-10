# algo/context.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# ===== Pydantic schemas (app.py와 동일 인터페이스 유지) =====
class StartPoint(BaseModel):
    lat: float
    lng: float

class Options(BaseModel):
    # SVG
    svg_path_index: str | int = Field(default="auto")
    svg_samples_per_seg: int = 80
    svg_simplify: float = 0.0
    svg_flip_y: bool = True

    # Placement
    canvas_box_frac: float = 0.75
    global_rot_deg: float = 0.0

    # Routing / Graph
    sample_step_m: float = 60.0
    min_wp_gap_m: float = 12.0
    graph_radius_m: int = 7000
    return_to_start: bool = True

    # Fitting
    tol_ratio: float = 0.08
    iters: int = 16

    # Shape preservation
    shape_bias_lambda: float = 0.045
    anchor_count: int = 10
    use_anchors: bool = True

    # Start-near + connector
    connect_from_start: bool = True
    max_connector_m: float = 450.0
    proximity_alpha: float = 0.75
    proximity_max_shift_m: float = 2000.0

class GeneratePayload(BaseModel):
    template_name: str
    start_point: StartPoint
    target_km: float = Field(gt=0)
    options: Optional[Options] = None
    save_geojson: Optional[bool] = False

# ===== Runtime settings =====
@dataclass
class Settings:
    DATA_DIR: Path = Path("data")
    SVG_DIR: Path = DATA_DIR / "svg"
    CACHE_DIR: Path = DATA_DIR / "cache"
    GENERATED_DIR: Path = DATA_DIR / "generated"

    def ensure(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.SVG_DIR.mkdir(parents=True, exist_ok=True)
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.GENERATED_DIR.mkdir(parents=True, exist_ok=True)

# ===== Central route context =====
@dataclass
class RouteContext:
    SET: Settings
    payload: GeneratePayload
    opt: Options

    # late-bound at runtime
    G = None           # graph
    G_proj = None      # projected graph
    nodes_proj = None  # gdf
    edges_proj = None  # gdf

    def svg_path(self) -> Path:
        return (self.SET.SVG_DIR / self.payload.template_name).resolve()
