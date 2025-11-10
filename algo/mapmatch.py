# algo/mapmatch.py
from __future__ import annotations
from pathlib import Path
import pickle
import osmnx as ox
import networkx as nx

ox.settings.use_cache = True
ox.settings.log_console = False

def load_graph_cached(center_lat: float, center_lng: float, dist_m: int, cache_dir: Path) -> nx.MultiDiGraph:
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

def project_graph(G):
    return ox.project_graph(G)

def graph_to_gdfs(G_proj):
    return ox.graph_to_gdfs(G_proj)

def project_to_wgs84(geom, nodes_proj_crs):
    return ox.projection.project_geometry(geom, crs=nodes_proj_crs, to_crs="EPSG:4326")[0]
