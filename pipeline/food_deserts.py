"""Food-desert area polygons for 2005 and 2025.

Definition (per USDA-FNS, simplified to a single distance threshold):

    rural cell  : > 10 miles to the nearest Supermarket / Super Store
    urban cell  : >  0.5 miles to the nearest Supermarket / Super Store

Driving distance, computed along the cached southern-WV OSM drive graph
(``data/raw/wv_south_drive.graphml``) via multi-source Dijkstra.

"Urban" here is defined per-cell using the **U.S. Census Urban Areas**
boundary (TIGER 2020 UAC), not by county membership. A cell is urban
iff its centroid falls inside any Census Urban Area polygon (Charleston,
Beckley, Bluefield, etc.); everything else in the study region is
classified rural and gets the 10-mile threshold. This matches the FNS
methodology far more closely than the previous county-level proxy.

Output GeoJSON:

    data/processed/food_deserts.geojson
        features: [
          { properties: { year: 2005 }, geometry: MultiPolygon },
          { properties: { year: 2025 }, geometry: MultiPolygon },
        ]

Run::

    .\\.venv\\Scripts\\python.exe -u -m pipeline.food_deserts
"""
from __future__ import annotations
import json
import math
import time
from pathlib import Path

import numpy as np
import networkx as nx
import geopandas as gpd
from scipy.spatial import cKDTree
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union
import rasterio
from rasterio.features import shapes as rio_shapes, rasterize as rio_rasterize
from rasterio.transform import from_origin
import osmnx as ox

from .config import PROCESSED, RAW

GRAPH_CACHE = RAW / "wv_south_drive.graphml"
GROCERS_SRC = PROCESSED / "grocers_by_year.geojson"
COUNTIES_SRC = PROCESSED / "southern_wv_counties.geojson"
URBAN_AREAS_CACHE = RAW / "wv_urban_areas.geojson"
TIGER_UAC_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2020/UAC/tl_2020_us_uac10.zip"
)
OUT_PATH = PROCESSED / "food_deserts.geojson"

YEARS = [2005, 2025]
URBAN_THRESHOLD_MI = 0.5
RURAL_THRESHOLD_MI = 10.0
M_PER_MI = 1609.344

GRID_DEG = 0.005


def _load_urban_areas(study_bounds: tuple[float, float, float, float]) -> "gpd.GeoSeries":
    """Census Urban Areas (TIGER 2020 UAC) clipped to the study bounds.

    The full UAC shapefile is ~80 MB; we cache only the WV-relevant
    subset (anything intersecting the study bbox + 0.25° padding).
    """
    if URBAN_AREAS_CACHE.exists():
        ua = gpd.read_file(URBAN_AREAS_CACHE).to_crs(epsg=4326)
        print(f"[deserts] urban-areas cache: {len(ua)} features")
        return ua.geometry
    print(f"[deserts] downloading TIGER 2020 UAC from {TIGER_UAC_URL}")
    t0 = time.time()
    ua_full = gpd.read_file(TIGER_UAC_URL).to_crs(epsg=4326)
    print(f"[deserts] downloaded {len(ua_full):,} UA features "
          f"({time.time() - t0:.1f}s)")
    minx, miny, maxx, maxy = study_bounds
    pad = 0.25
    bbox = box(minx - pad, miny - pad, maxx + pad, maxy + pad)
    ua = ua_full[ua_full.intersects(bbox)].copy()
    print(f"[deserts] kept {len(ua)} UA features intersecting study bbox")
    ua.to_file(URBAN_AREAS_CACHE, driver="GeoJSON")
    print(f"[deserts] cached -> {URBAN_AREAS_CACHE.name}")
    return ua.geometry


def _supermarket_lonlats(year: int) -> list[tuple[float, float]]:
    raw = json.loads(GROCERS_SRC.read_text(encoding="utf-8"))
    out: list[tuple[float, float]] = []
    for f in raw.get("features", []):
        p = f.get("properties", {}) or {}
        if p.get("snapshot_year") != year:
            continue
        t = (p.get("store_type") or "").strip().lower()
        if not ("supermarket" in t or "super store" in t):
            continue
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        out.append((float(coords[0]), float(coords[1])))
    return out


def _to_simple_undirected(G: nx.MultiDiGraph) -> nx.Graph:
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


def main() -> None:
    if not GRAPH_CACHE.exists():
        raise FileNotFoundError(f"missing {GRAPH_CACHE} - run pipeline.isochrone first")
    if not COUNTIES_SRC.exists():
        raise FileNotFoundError(f"missing {COUNTIES_SRC} - run pipeline.acquire first")
    if not GROCERS_SRC.exists():
        raise FileNotFoundError(f"missing {GROCERS_SRC} - run pipeline.grocers_by_year first")

    print("[deserts] loading counties")
    counties = gpd.read_file(COUNTIES_SRC).to_crs(epsg=4326)
    study_union = unary_union(counties.geometry.values)
    study_bounds = study_union.bounds

    ua_geoms = _load_urban_areas(study_bounds)
    urban_union = unary_union(list(ua_geoms.values)).intersection(study_union)
    if urban_union.is_empty:
        print("[deserts] WARNING: no urban areas inside study region - "
              "everything will be classified rural")

    print("[deserts] loading drive graph")
    t0 = time.time()
    G = ox.load_graphml(GRAPH_CACHE)
    print(f"[deserts] graph: {G.number_of_nodes():,} nodes, "
          f"{G.number_of_edges():,} edges  ({time.time() - t0:.1f}s)")
    print("[deserts] collapsing to simple undirected graph")
    H = _to_simple_undirected(G)
    del G

    node_ids: list[int] = []
    node_xy: list[tuple[float, float]] = []
    for n, d in H.nodes(data=True):
        x = d.get("x"); y = d.get("y")
        if x is None or y is None:
            continue
        node_ids.append(n)
        node_xy.append((x, y))
    node_ids_arr = np.asarray(node_ids, dtype=np.int64)
    node_xy_arr = np.asarray(node_xy, dtype=float)
    print(f"[deserts] KDTree over {len(node_ids):,} nodes")
    node_tree = cKDTree(node_xy_arr)

    minx, miny, maxx, maxy = study_bounds
    minx = math.floor(minx / GRID_DEG) * GRID_DEG
    miny = math.floor(miny / GRID_DEG) * GRID_DEG
    maxx = math.ceil(maxx / GRID_DEG) * GRID_DEG
    maxy = math.ceil(maxy / GRID_DEG) * GRID_DEG
    nx_cols = int(round((maxx - minx) / GRID_DEG))
    ny_rows = int(round((maxy - miny) / GRID_DEG))
    print(f"[deserts] grid {nx_cols} x {ny_rows} = {nx_cols * ny_rows:,} cells "
          f"at {GRID_DEG}° (~{GRID_DEG * 69:.2f} mi)")

    transform = from_origin(minx, maxy, GRID_DEG, GRID_DEG)
    col_centers = minx + (np.arange(nx_cols) + 0.5) * GRID_DEG
    row_centers = maxy - (np.arange(ny_rows) + 0.5) * GRID_DEG
    cx, cy = np.meshgrid(col_centers, row_centers)
    cells_lonlat = np.stack([cx.ravel(), cy.ravel()], axis=1)

    print("[deserts] rasterizing study-area + Census-urban-area masks")
    study_mask = rio_rasterize(
        [(study_union, 1)],
        out_shape=(ny_rows, nx_cols),
        transform=transform,
        fill=0,
        dtype="uint8",
        all_touched=True,
    ).astype(bool)
    if urban_union.is_empty:
        urban_mask = np.zeros_like(study_mask)
    else:
        urban_mask = rio_rasterize(
            [(urban_union, 1)],
            out_shape=(ny_rows, nx_cols),
            transform=transform,
            fill=0,
            dtype="uint8",
            all_touched=True,
        ).astype(bool) & study_mask
    print(f"[deserts] urban cells in study: {int(urban_mask.sum()):,} / "
          f"{int(study_mask.sum()):,}  "
          f"({100.0 * urban_mask.sum() / max(1, study_mask.sum()):.1f}%)")

    flat_study = study_mask.ravel()
    valid_idx = np.where(flat_study)[0]
    print(f"[deserts] snapping {len(valid_idx):,} in-study cells to road nodes")
    t0 = time.time()
    _, snap_idx = node_tree.query(cells_lonlat[valid_idx], k=1)
    cell_node_ids = np.full(len(flat_study), -1, dtype=np.int64)
    cell_node_ids[valid_idx] = node_ids_arr[snap_idx]
    print(f"[deserts] snapped ({time.time() - t0:.1f}s)")

    desert_features = []

    for year in YEARS:
        sm = _supermarket_lonlats(year)
        print(f"[deserts] {year}: {len(sm)} supermarket sources")
        if not sm:
            continue
        sm_pts = np.asarray(sm, dtype=float)
        _, sm_snap = node_tree.query(sm_pts, k=1)
        sm_nodes = list(set(node_ids_arr[sm_snap].tolist()))
        print(f"[deserts] {year}: {len(sm_nodes)} unique source nodes")
        t0 = time.time()
        dist_by_node = nx.multi_source_dijkstra_path_length(
            H, set(sm_nodes), weight="length"
        )
        print(f"[deserts] {year}: Dijkstra reached {len(dist_by_node):,} nodes "
              f"({time.time() - t0:.1f}s)")

        cell_dist_mi = np.full(len(flat_study), np.nan, dtype=float)
        for i in valid_idx:
            nid = int(cell_node_ids[i])
            d_m = dist_by_node.get(nid)
            if d_m is None:
                cell_dist_mi[i] = float("inf")
            else:
                cell_dist_mi[i] = d_m / M_PER_MI
        cell_dist = cell_dist_mi.reshape((ny_rows, nx_cols))

        is_desert = np.zeros((ny_rows, nx_cols), dtype=bool)
        urban_cells = study_mask & urban_mask
        rural_cells = study_mask & ~urban_mask
        with np.errstate(invalid="ignore"):
            is_desert[urban_cells] = cell_dist[urban_cells] > URBAN_THRESHOLD_MI
            is_desert[rural_cells] = cell_dist[rural_cells] > RURAL_THRESHOLD_MI

        n_des = int(is_desert.sum())
        n_total = int(study_mask.sum())
        pct = 100.0 * n_des / max(1, n_total)
        print(f"[deserts] {year}: {n_des:,} desert cells / {n_total:,} "
              f"in-study  ({pct:.1f}%)")

        polys = []
        for geom, val in rio_shapes(
            is_desert.astype("uint8"),
            mask=is_desert,
            transform=transform,
            connectivity=8,
        ):
            if val != 1:
                continue
            polys.append(shape(geom))
        if not polys:
            print(f"[deserts] {year}: no polygons (skipping)")
            continue

        merged = unary_union(polys)
        merged = merged.intersection(study_union)
        merged = merged.simplify(GRID_DEG * 0.4, preserve_topology=True)
        if merged.is_empty:
            continue

        desert_features.append({
            "type": "Feature",
            "properties": {
                "year": year,
                "n_cells": n_des,
                "pct_of_study": round(pct, 2),
                "urban_threshold_mi": URBAN_THRESHOLD_MI,
                "rural_threshold_mi": RURAL_THRESHOLD_MI,
            },
            "geometry": mapping(merged),
        })

    summary: dict = {}
    if desert_features:
        from shapely.geometry import shape as _sh
        ALBERS = "EPSG:5070"
        study_gs = gpd.GeoSeries([study_union], crs="EPSG:4326").to_crs(ALBERS)
        study_sq_mi = float(study_gs.iloc[0].area / (M_PER_MI ** 2))
        summary["study_sq_mi"] = round(study_sq_mi, 1)

        geoms_by_year: dict[int, "object"] = {}
        for f in desert_features:
            y = f["properties"]["year"]
            g = _sh(f["geometry"])
            g_proj = gpd.GeoSeries([g], crs="EPSG:4326").to_crs(ALBERS).iloc[0]
            sq_mi = float(g_proj.area / (M_PER_MI ** 2))
            f["properties"]["area_sq_mi"] = round(sq_mi, 1)
            geoms_by_year[y] = g
            summary[f"desert_sq_mi_{y}"] = round(sq_mi, 1)

        if 2005 in geoms_by_year and 2025 in geoms_by_year:
            g05 = geoms_by_year[2005]
            g25 = geoms_by_year[2025]
            disappeared = g05.difference(g25)
            grown = g25.difference(g05)
            persistent = g05.intersection(g25)
            for label, g in (("disappeared", disappeared), ("grown", grown),
                             ("persistent", persistent)):
                if g.is_empty:
                    summary[f"{label}_sq_mi"] = 0.0
                else:
                    gp = gpd.GeoSeries([g], crs="EPSG:4326").to_crs(ALBERS).iloc[0]
                    summary[f"{label}_sq_mi"] = round(
                        float(gp.area / (M_PER_MI ** 2)), 1
                    )
            if not persistent.is_empty:
                desert_features.append({
                    "type": "Feature",
                    "properties": {
                        "year": "persistent",
                        "area_sq_mi": summary["persistent_sq_mi"],
                    },
                    "geometry": mapping(
                        persistent.simplify(GRID_DEG * 0.4, preserve_topology=True)
                    ),
                })
            print(f"[deserts] study area: {summary['study_sq_mi']:,.0f} sq mi")
            print(f"[deserts] 2005 desert: {summary['desert_sq_mi_2005']:,.0f} sq mi")
            print(f"[deserts] 2025 desert: {summary['desert_sq_mi_2025']:,.0f} sq mi")
            print(f"[deserts] disappeared: {summary['disappeared_sq_mi']:,.1f} sq mi")
            print(f"[deserts] grown:       {summary['grown_sq_mi']:,.1f} sq mi")
            print(f"[deserts] persistent:  {summary['persistent_sq_mi']:,.1f} sq mi")

    out = {
        "type": "FeatureCollection",
        "features": desert_features,
        "_meta": {
            "grid_deg": GRID_DEG,
            "urban_threshold_mi": URBAN_THRESHOLD_MI,
            "rural_threshold_mi": RURAL_THRESHOLD_MI,
            "urban_classification": "Census 2020 Urban Areas (TIGER UAC)",
            "method": "multi-source Dijkstra over OSM drive graph",
            "summary": summary,
        },
    }
    OUT_PATH.write_text(json.dumps(out), encoding="utf-8")
    size_mb = OUT_PATH.stat().st_size / 1_048_576
    print(f"[deserts] wrote {OUT_PATH.name} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
