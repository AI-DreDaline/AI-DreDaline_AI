# algo/graph_io.py
from __future__ import annotations
from pathlib import Path
import pickle
import os
import osmnx as ox

def _cache_key(center_lat: float, center_lng: float, dist_m: int) -> str:
    return f"graph_{center_lat:.4f}_{center_lng:.4f}_{dist_m}.pkl"

def load_graph(cache_dir: Path, center_lat: float, center_lng: float, dist_m: int = 3500):
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(center_lat, center_lng, dist_m)
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
