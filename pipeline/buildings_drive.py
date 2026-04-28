"""Driving distance from each residential building to the nearest
Supermarket / Super Store, in 2005 and 2025.

We need *driving* distance (not crow-flies) because southern WV terrain
forces routes to follow valleys. With 380k homes and ~260 supermarkets
per year, a per-pair routing call is infeasible - instead we build the
WV drive graph once (cached at data/raw/wv_south_drive.graphml by
pipeline.isochrone) and run a multi-source Dijkstra weighted by edge
``length`` (meters). That gives, for every road-network node, the
distance along roads to its nearest supermarket. Each home is then
snapped to its nearest graph node and inherits that distance, plus the
straight-line walk from the building footprint to the snapped node
(small, but kept honest).

Output sidecar: ``data/processed/buildings_drive_distances.json`` with
parallel arrays in the SAME ORDER as features in
``buildings_residential.geojson``::

    {
      "n": 381625,
      "drive_mi_2005": [...],
      "drive_mi_2025": [...],
      "delta_mi": [...]
    }

Run with::

    .\\.venv\\Scripts\\python.exe -u -m pipeline.buildings_drive
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path

import numpy as np
import networkx as nx
from scipy.spatial import cKDTree

import osmnx as ox

from .config import PROCESSED, RAW

GRAPH_CACHE = RAW / "wv_south_drive.graphml"
BUILDINGS_SRC = PROCESSED / "buildings_residential.geojson"
GROCERS_SRC = PROCESSED / "grocers_by_year.geojson"
OUT_PATH = PROCESSED / "buildings_drive_distances.json"

YEARS_TO_COMPUTE = [2005, 2025]
FULL_SERVICE = {"supermarket", "super store"}
M_PER_MI = 1609.344


def _load_graph() -> nx.MultiDiGraph:
    if not GRAPH_CACHE.exists():
        raise FileNotFoundError(
            f"missing {GRAPH_CACHE} - run `python -m pipeline.isochrone` "
            "first to build the cached drive graph"
        )
    print(f"[drive] loading drive graph from {GRAPH_CACHE.name}")
    t0 = time.time()
    G = ox.load_graphml(GRAPH_CACHE)
    print(f"[drive] graph: {G.number_of_nodes():,} nodes, "
          f"{G.number_of_edges():,} edges  ({time.time() - t0:.1f}s)")
    return G


def _to_simple_undirected(G: nx.MultiDiGraph) -> nx.Graph:
    """Collapse to a simple undirected graph keyed by min edge length.

    Driving distance is symmetric for our purposes (we treat the
    network as walkable in both directions), and Dijkstra wants a
    simple graph for fastest performance.
    """
    H = nx.Graph()
    for u, v, data in G.edges(data=True):
        L = data.get("length")
        if L is None:
            continue
        try:
            L = float(L)
        except (TypeError, ValueError):
            continue
        if H.has_edge(u, v):
            if L < H[u][v]["length"]:
                H[u][v]["length"] = L
        else:
            H.add_edge(u, v, length=L)
    for n, data in G.nodes(data=True):
        if H.has_node(n):
            try:
                H.nodes[n]["x"] = float(data["x"])
                H.nodes[n]["y"] = float(data["y"])
            except (KeyError, TypeError, ValueError):
                continue
    return H


def _supermarket_lonlats(year: int) -> list[tuple[float, float]]:
    """Lon/lat of every Supermarket/Super Store active in `year`.

    grocers_by_year.geojson stores one feature per (store, snapshot_year).
    A store is "active in `year`" iff it has a feature whose
    ``snapshot_year`` matches and whose ``store_type`` is in the
    full-service tier.
    """
    raw = json.loads(GROCERS_SRC.read_text(encoding="utf-8"))
    out: list[tuple[float, float]] = []
    for f in raw.get("features", []):
        p = f.get("properties", {}) or {}
        if p.get("snapshot_year") != year:
            continue
        t = (p.get("store_type") or "").strip().lower()
        if not (t.startswith("supermarket") or t.startswith("super store")
                or "supermarket" in t or "super store" in t):
            continue
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        out.append((float(coords[0]), float(coords[1])))
    return out


def _multi_source_dijkstra_distance(
    H: nx.Graph,
    source_nodes: list[int],
) -> dict[int, float]:
    """Distance (meters) from each node in H to its NEAREST source.

    Uses NetworkX's multi-source Dijkstra (single virtual super-source
    semantics) - internally it seeds the priority queue with all
    sources at distance 0.
    """
    if not source_nodes:
        return {}
    dist = nx.multi_source_dijkstra_path_length(H, set(source_nodes), weight="length")
    return dist


def _snap_points_to_nodes(
    coords: list[tuple[float, float]],
    node_ids: np.ndarray,
    node_xy: np.ndarray,
    node_tree: cKDTree,
) -> list[int]:
    """Nearest-node lookup in lon/lat space.

    For southern WV (~38° N), 1° lat ≈ 111 km and 1° lon ≈ 87 km, so
    Euclidean degrees are ~within 25% of true distance - fine for
    snapping homes/stores to the closest road node out of >500k.
    """
    if not coords:
        return []
    pts = np.asarray(coords, dtype=float)
    _, idx = node_tree.query(pts, k=1)
    return node_ids[idx].tolist()


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main() -> None:
    if not BUILDINGS_SRC.exists():
        raise FileNotFoundError(
            f"missing {BUILDINGS_SRC} - run `python -m pipeline.buildings` first"
        )

    print("[drive] loading buildings_residential.geojson")
    t0 = time.time()
    raw = json.loads(BUILDINGS_SRC.read_text(encoding="utf-8"))
    feats = raw.get("features", [])
    home_lonlat: list[tuple[float, float]] = []
    for f in feats:
        p = f.get("properties", {}) or {}
        lon = p.get("lon")
        lat = p.get("lat")
        if lon is None or lat is None:
            home_lonlat.append((float("nan"), float("nan")))
        else:
            home_lonlat.append((float(lon), float(lat)))
    print(f"[drive] {len(home_lonlat):,} buildings ({time.time() - t0:.1f}s)")

    G = _load_graph()
    print("[drive] collapsing to simple undirected graph (by min edge length)")
    t0 = time.time()
    H = _to_simple_undirected(G)
    print(f"[drive] simple graph: {H.number_of_nodes():,} nodes, "
          f"{H.number_of_edges():,} edges  ({time.time() - t0:.1f}s)")
    del G

    node_ids: list[int] = []
    node_xy: list[tuple[float, float]] = []
    for n, d in H.nodes(data=True):
        x = d.get("x")
        y = d.get("y")
        if x is None or y is None:
            continue
        node_ids.append(n)
        node_xy.append((x, y))
    node_ids_arr = np.asarray(node_ids, dtype=np.int64)
    node_xy_arr = np.asarray(node_xy, dtype=float)
    print(f"[drive] building KDTree over {len(node_ids):,} graph nodes")
    node_tree = cKDTree(node_xy_arr)

    print("[drive] snapping homes to nearest road-network node")
    t0 = time.time()
    home_node_idx: list[int] = []
    home_pts = np.asarray(home_lonlat, dtype=float)
    valid_mask = ~np.isnan(home_pts).any(axis=1)
    valid_pts = home_pts[valid_mask]
    _, idx = node_tree.query(valid_pts, k=1)
    full_idx = np.full(len(home_lonlat), -1, dtype=np.int64)
    full_idx[valid_mask] = idx
    print(f"[drive] snapped homes ({time.time() - t0:.1f}s)")

    print("[drive] computing home-to-node residual distance")
    t0 = time.time()
    home_residual_m = np.zeros(len(home_lonlat), dtype=float)
    home_node_id = np.full(len(home_lonlat), -1, dtype=np.int64)
    for i in range(len(home_lonlat)):
        ix = full_idx[i]
        if ix < 0:
            home_residual_m[i] = float("nan")
            continue
        nx_, ny_ = node_xy_arr[ix]
        hx, hy = home_pts[i]
        home_residual_m[i] = _haversine_m(hy, hx, ny_, nx_)
        home_node_id[i] = node_ids_arr[ix]
    print(f"[drive] residuals ({time.time() - t0:.1f}s)")

    out_by_year: dict[int, np.ndarray] = {}
    for year in YEARS_TO_COMPUTE:
        sm = _supermarket_lonlats(year)
        print(f"[drive] {year}: {len(sm)} Supermarket/Super Store points")
        if not sm:
            print(f"[drive] {year}: NO SOURCES - distances will be inf")
            out_by_year[year] = np.full(len(home_lonlat), float("nan"))
            continue
        sm_pts = np.asarray(sm, dtype=float)
        _, sm_idx = node_tree.query(sm_pts, k=1)
        sm_nodes = node_ids_arr[sm_idx].tolist()
        sm_nodes = list(set(sm_nodes))
        print(f"[drive] {year}: {len(sm_nodes)} unique source nodes")
        t0 = time.time()
        dist_by_node = _multi_source_dijkstra_distance(H, sm_nodes)
        print(f"[drive] {year}: Dijkstra reached {len(dist_by_node):,} nodes "
              f"({time.time() - t0:.1f}s)")

        per_home_m = np.full(len(home_lonlat), float("nan"))
        for i in range(len(home_lonlat)):
            nid = int(home_node_id[i])
            if nid < 0:
                continue
            d_node = dist_by_node.get(nid)
            if d_node is None:
                continue
            per_home_m[i] = d_node + home_residual_m[i]
        out_by_year[year] = per_home_m

    drive_2005 = (out_by_year[2005] / M_PER_MI).round(2)
    drive_2025 = (out_by_year[2025] / M_PER_MI).round(2)
    delta = (drive_2025 - drive_2005).round(2)

    def _arr(a: np.ndarray) -> list:
        out: list = []
        for v in a.tolist():
            if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                out.append(None)
            else:
                out.append(round(float(v), 2))
        return out

    payload = {
        "n": len(home_lonlat),
        "drive_mi_2005": _arr(drive_2005),
        "drive_mi_2025": _arr(drive_2025),
        "delta_mi": _arr(delta),
        "weight": "edge length (meters); multi-source Dijkstra over the "
                  "cached OSM drive graph; supermarket/super-store sources "
                  "filtered from grocers_by_year.geojson",
    }

    OUT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    size_mb = OUT_PATH.stat().st_size / 1_048_576
    print(f"[drive] wrote {OUT_PATH.name} ({size_mb:.2f} MB)")

    finite = ~np.isnan(delta)
    if finite.any():
        d = delta[finite]
        n = d.size
        worse = int((d >= 0.5).sum())
        better = int((d <= -0.5).sum())
        flat = n - worse - better
        sd = np.sort(d)
        print()
        print("[drive] DRIVE-DISTANCE Δ (2005 → 2025), miles")
        print(f"            homes covered      : {n:,} of {len(home_lonlat):,}")
        print(f"            ≥ ½ mi farther     : {worse:,}")
        print(f"            ≥ ½ mi closer      : {better:,}")
        print(f"            ~ unchanged        : {flat:,}")
        print(f"            median Δ           : {sd[n // 2]:+.2f} mi")
        print(f"            10th / 90th pct    : {sd[int(n*0.1)]:+.2f} / {sd[int(n*0.9)]:+.2f} mi")
        print(f"            mean drive 2005    : {np.nanmean(drive_2005):.2f} mi")
        print(f"            mean drive 2025    : {np.nanmean(drive_2025):.2f} mi")


if __name__ == "__main__":
    main()
