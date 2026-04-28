"""Drive-time isochrone generation.

Tier 1: local Valhalla instance (per the buildguide's Docker recipe).
Tier 2: OSM road-network shortest-path on travel-time-weighted edges via
        OSMnx + NetworkX. This is the right approach for mountainous WV
        terrain - the network already follows valleys and switchbacks,
        so distances and travel times reflect actual passable routes,
        not Euclidean line-of-sight.
Tier 3: Euclidean buffer surrogate (last-resort, labeled in output).

The graph is cached to data/raw/wv_south_drive.graphml so subsequent runs
do not re-pull from Overpass. Build takes ~2-5 min on first run.
"""
from __future__ import annotations
import math
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import requests
from shapely.geometry import Point, MultiPoint
from shapely.ops import unary_union

from .config import PROCESSED, RAW, VALHALLA_URL

CONTOURS = [15, 30, 45]
RURAL_AVG_KMH = 48
GRAPH_CACHE = RAW / "wv_south_drive.graphml"

_DEG_PER_KM_LAT = 1 / 111.0
_DEG_PER_KM_LON = 1 / (111.0 * math.cos(math.radians(37.5)))


# ---------------------------------------------------------------------
# Tier 1: Valhalla
# ---------------------------------------------------------------------
def _try_valhalla(groceries: gpd.GeoDataFrame) -> list[dict] | None:
    try:
        requests.get(f"{VALHALLA_URL}/status", timeout=2)
    except Exception:
        return None

    feats: list[dict] = []
    for i, row in groceries.iterrows():
        try:
            r = requests.post(
                f"{VALHALLA_URL}/isochrone",
                json={
                    "locations": [{"lon": row.geometry.x, "lat": row.geometry.y}],
                    "costing": "auto",
                    "contours": [{"time": m} for m in CONTOURS],
                    "polygons": True,
                },
                timeout=60,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            print(f"[isochrone] valhalla call {i} failed: {e}")
            continue
        for f in data.get("features", []):
            f["properties"]["source"] = "valhalla"
            feats.append(f)
    return feats


# ---------------------------------------------------------------------
# Tier 2: OSM road network via OSMnx + NetworkX
# ---------------------------------------------------------------------
def _load_or_build_graph(counties_gdf: gpd.GeoDataFrame):
    import osmnx as ox

    if GRAPH_CACHE.exists():
        print(f"[isochrone] loading cached drive graph from {GRAPH_CACHE.name}")
        return ox.load_graphml(GRAPH_CACHE)

    poly = unary_union(counties_gdf.geometry.values).buffer(0.25)
    print("[isochrone] building OSM drive network for southern WV - this can take 2–5 min on first run")
    G = ox.graph_from_polygon(poly, network_type="drive", simplify=True, retain_all=False)
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    ox.save_graphml(G, GRAPH_CACHE)
    print(f"[isochrone] cached graph to {GRAPH_CACHE.name} ({G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges)")
    return G


def _network_isochrones(groceries: gpd.GeoDataFrame, counties: gpd.GeoDataFrame) -> list[dict] | None:
    try:
        import osmnx as ox
    except Exception as e:
        print(f"[isochrone] osmnx unavailable: {e}")
        return None

    try:
        G = _load_or_build_graph(counties)
    except Exception as e:
        print(f"[isochrone] could not build OSM drive graph: {e}")
        return None

    xs = groceries.geometry.x.values
    ys = groceries.geometry.y.values
    try:
        nearest = ox.distance.nearest_nodes(G, X=xs, Y=ys)
    except Exception as e:
        print(f"[isochrone] nearest_nodes failed: {e}")
        return None

    Gs = nx.DiGraph()
    for u, v, data in G.edges(data=True):
        tt = data.get("travel_time")
        if tt is None:
            continue
        if Gs.has_edge(u, v):
            if tt < Gs[u][v]["travel_time"]:
                Gs[u][v]["travel_time"] = tt
        else:
            Gs.add_edge(u, v, travel_time=tt)
    for n, data in G.nodes(data=True):
        if Gs.has_node(n):
            Gs.nodes[n]["x"] = data.get("x")
            Gs.nodes[n]["y"] = data.get("y")

    feats: list[dict] = []
    seen: set = set()
    for src_node in nearest:
        if src_node in seen:
            continue
        seen.add(src_node)
        for minutes in CONTOURS:
            try:
                sub = nx.ego_graph(Gs, src_node, radius=minutes * 60, distance="travel_time")
            except Exception:
                continue
            pts = [(d["x"], d["y"]) for _, d in sub.nodes(data=True) if d.get("x") is not None]
            if len(pts) < 3:
                continue
            hull = MultiPoint([Point(x, y) for x, y in pts]).convex_hull
            hull = hull.buffer(0.005).buffer(-0.003)
            if hull.is_empty:
                continue
            feats.append({
                "type": "Feature",
                "geometry": json.loads(gpd.GeoSeries([hull], crs="EPSG:4326").to_json())["features"][0]["geometry"],
                "properties": {
                    "contour": minutes,
                    "source": "osm_network",
                    "source_node": int(src_node),
                },
            })
    return feats if feats else None


# ---------------------------------------------------------------------
# Tier 3: Euclidean fallback (last resort)
# ---------------------------------------------------------------------
def _buffer_fallback(groceries: gpd.GeoDataFrame) -> list[dict]:
    feats: list[dict] = []
    for _, row in groceries.iterrows():
        for minutes in CONTOURS:
            radius_km = (minutes / 60.0) * RURAL_AVG_KMH
            poly = row.geometry.buffer(
                radius_km * max(_DEG_PER_KM_LAT, _DEG_PER_KM_LON),
                resolution=24,
            )
            feats.append({
                "type": "Feature",
                "geometry": json.loads(gpd.GeoSeries([poly]).to_json())["features"][0]["geometry"],
                "properties": {"contour": minutes, "source": "buffer_fallback"},
            })
    return feats


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------
def main() -> None:
    src = PROCESSED / "grocery_current.geojson"
    if not src.exists():
        print(f"[isochrone] missing {src.name} - run pipeline.retail first")
        return

    groceries = gpd.read_file(src)
    if groceries.empty:
        print("[isochrone] no grocery points; nothing to do")
        return
    counties = gpd.read_file(PROCESSED / "southern_wv_counties.geojson").to_crs("EPSG:4326")

    feats = _try_valhalla(groceries)
    if feats:
        print(f"[isochrone] Valhalla returned {len(feats)} features")
    else:
        print("[isochrone] Valhalla unreachable - trying OSM road-network shortest paths…")
        feats = _network_isochrones(groceries, counties)
        if feats:
            print(f"[isochrone] OSM-network produced {len(feats)} polygons")
        else:
            print("[isochrone] OSM-network unavailable - using Euclidean buffer fallback")
            feats = _buffer_fallback(groceries)

    iso_gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    iso_gdf.to_file(PROCESSED / "isochrones.geojson", driver="GeoJSON")
    print(f"[isochrone] wrote isochrones.geojson ({len(iso_gdf)} polygons)")

    if "contour" in iso_gdf.columns and (iso_gdf["contour"] == 30).any():
        cov = unary_union(iso_gdf[iso_gdf["contour"] == 30].geometry.values)
        union = unary_union(counties.geometry.values)
        desert = union.difference(cov)
        gpd.GeoDataFrame(geometry=[desert], crs="EPSG:4326").to_file(
            PROCESSED / "food_desert_30min.geojson", driver="GeoJSON"
        )
        print("[isochrone] wrote food_desert_30min.geojson")


if __name__ == "__main__":
    main()
