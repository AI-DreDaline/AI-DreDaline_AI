# config.py
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

class Settings:
    DEBUG = True
    HOST = "127.0.0.1"
    PORT = 5001

    DATA_DIR = BASE_DIR / "data"
    SVG_DIR = DATA_DIR / "svg"
    CACHE_DIR = DATA_DIR / "cache"

    # 스케일/리샘플/간소화 등 기본값
    DEFAULTS = {
        "align_mode": "free_fit",         # "free_fit" | "start_locked"
        "map_match": True,
        "graph_dist_m": 3500,
        "sample_step_m": 50,
        "resample_m": 5,
        "simplify_tolerance": 0.5,
        "similarity": {"enable": True, "method": "hausdorff"}  # 예시
    }

SETTINGS = Settings()
