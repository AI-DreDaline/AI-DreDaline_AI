from pathlib import Path

ASSETS_SVG_DIR = Path(__file__).resolve().parent.parent / "assets" / "svg"
ASSETS_SVG_DIR.mkdir(parents=True, exist_ok=True)
