"""Building footprints + supermarket-access analysis.

Comprehensive building inventory for the 19-county study area, joining
Microsoft USBuildingFootprints (computer-vision-derived polygons, complete
coverage) with OpenStreetMap building tags (use classification where
available). For each building we then compute crow-flies miles to the
nearest Supermarket / Super Store at five snapshot years (2005-2025) using
USDA-FNS's standard Food Access Research Atlas thresholds:

    - urban  : > 1 mile from nearest supermarket = low access
    - rural  : > 10 miles from nearest supermarket = low access

Outputs:
    data/processed/buildings_residential.geojson
        Centroids of residential buildings only, with classification source
        (osm_residential | osm_other | unknown_ms_only) and per-year
        supermarket_distance_mi + low_access_<year> booleans.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from scipy.spatial import cKDTree
from shapely.geometry import shape, Point
from shapely.ops import unary_union

from .config import PROCESSED, RAW, SOUTHERN_WV_COUNTIES

MS_FOOTPRINTS = RAW / "WestVirginia.geojson"
OSM_BUILDINGS_CACHE = RAW / "osm_buildings_overpass.json"

SNAPSHOT_YEARS = [2005, 2010, 2015, 2020, 2025]
FULL_SERVICE_TYPES = {"Supermarket", "Super Store"}

OSM_RESIDENTIAL_TAGS = {
    "residential", "house", "detached", "apartments", "semidetached_house",
    "terrace", "bungalow", "cabin", "dormitory", "houseboat", "static_caravan",
    "farm", "trailer",
}
OSM_NONRES_TAGS = {
    "commercial", "retail", "industrial", "warehouse", "office", "supermarket",
    "kiosk", "garage", "garages", "parking", "shed", "hangar", "service",
    "barn", "stable", "greenhouse", "silo", "ruins", "school", "university",
    "kindergarten", "college", "hospital", "clinic", "fire_station",
    "government", "civic", "public", "church", "chapel", "cathedral",
    "mosque", "temple", "synagogue", "religious", "monastery", "train_station",
    "transportation", "stadium", "sports_hall", "construction", "roof",
}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ---------------------------------------------------------------------
# Step 1: load study-area boundary
# ---------------------------------------------------------------------
def _load_study_area() -> tuple[gpd.GeoDataFrame, "shapely.geometry.base.BaseGeometry"]:
    """Return (counties_gdf, dissolved_union)."""
    counties_path = PROCESSED / "southern_wv_counties.geojson"
    if not counties_path.exists():
        raise FileNotFoundError(
            f"{counties_path} not found. Run pipeline.acquire first."
        )
    gdf = gpd.read_file(counties_path)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    union = unary_union(gdf.geometry)
    return gdf, union


# ---------------------------------------------------------------------
# Step 2: fetch OSM building polygons with use tags
# ---------------------------------------------------------------------
def _fetch_osm_buildings(bbox: tuple[float, float, float, float]) -> dict:
    """Fetch all `building=*` ways/relations within bbox via Overpass.

    Tiled into ~0.5° chunks to keep individual responses under Overpass's
    ~50 MB / 30s soft limits. Cached to disk; rerun by deleting the cache.
    """
    if OSM_BUILDINGS_CACHE.exists():
        print(f"[buildings] using cached OSM buildings: {OSM_BUILDINGS_CACHE.name}")
        return json.loads(OSM_BUILDINGS_CACHE.read_text(encoding="utf-8"))

    minx, miny, maxx, maxy = bbox
    TILE = 0.5
    elements: list[dict] = []
    seen_ids: set[tuple[str, int]] = set()
    tiles: list[tuple[float, float, float, float]] = []
    y = miny
    while y < maxy:
        x = minx
        while x < maxx:
            tiles.append((x, y, min(x + TILE, maxx), min(y + TILE, maxy)))
            x += TILE
        y += TILE

    print(f"[buildings] fetching OSM buildings in {len(tiles)} tiles "
          f"({TILE}° each)")
    for i, (a, b, c, d) in enumerate(tiles, 1):
        bbox_str = f"{b},{a},{d},{c}"
        query = f"""
[out:json][timeout:180];
(
  way["building"]({bbox_str});
  relation["building"]({bbox_str});
);
out tags center;
"""
        for attempt in range(3):
            try:
                t0 = time.time()
                r = requests.post(
                    OVERPASS_URL,
                    data={"data": query},
                    timeout=300,
                    headers={"User-Agent": "WV-FoodDesert/1.0"},
                )
                if r.status_code == 200:
                    break
                print(f"           tile {i}/{len(tiles)}: HTTP {r.status_code}, "
                      f"retry {attempt + 1}/3")
                time.sleep(5 * (attempt + 1))
            except requests.RequestException as e:
                print(f"           tile {i}/{len(tiles)}: {e}, retry {attempt + 1}/3")
                time.sleep(5 * (attempt + 1))
        else:
            print(f"           tile {i}/{len(tiles)}: GIVING UP after 3 attempts")
            continue
        try:
            data = r.json()
        except ValueError:
            print(f"           tile {i}/{len(tiles)}: bad JSON, skipping")
            continue
        new_count = 0
        for el in data.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key in seen_ids:
                continue
            seen_ids.add(key)
            elements.append(el)
            new_count += 1
        print(f"           tile {i}/{len(tiles)}: +{new_count:,} buildings "
              f"(total {len(elements):,}) in {time.time() - t0:.1f}s")
        time.sleep(1.0)

    out = {"elements": elements}
    OSM_BUILDINGS_CACHE.write_text(json.dumps(out), encoding="utf-8")
    print(f"[buildings] cached {len(elements):,} OSM buildings to {OSM_BUILDINGS_CACHE.name}")
    return out


def _osm_buildings_df(osm: dict) -> pd.DataFrame:
    """Flatten Overpass output -> DataFrame with lon, lat, building_tag."""
    rows = []
    for el in osm.get("elements", []):
        tags = el.get("tags") or {}
        bld = tags.get("building")
        if not bld:
            continue
        center = el.get("center") if el.get("type") == "relation" else None
        if center is None:
            lon = el.get("lon"); lat = el.get("lat")
            if lon is None or lat is None:
                center = el.get("center")
                if center:
                    lon = center.get("lon"); lat = center.get("lat")
        else:
            lon = center.get("lon"); lat = center.get("lat")
        if lon is None or lat is None:
            continue
        rows.append({
            "osm_id": el.get("id"),
            "osm_type": el.get("type"),
            "lon": float(lon),
            "lat": float(lat),
            "building_tag": str(bld).lower(),
        })
    return pd.DataFrame(rows)


def _classify_osm_tag(tag: str) -> str:
    """Map an OSM building=* tag to one of:
    'osm_residential' | 'osm_nonres' | 'osm_yes_or_unknown'.
    """
    if tag in OSM_RESIDENTIAL_TAGS:
        return "osm_residential"
    if tag in OSM_NONRES_TAGS:
        return "osm_nonres"
    return "osm_yes_or_unknown"


# ---------------------------------------------------------------------
# Step 3: load + clip MS footprints, compute centroids
# ---------------------------------------------------------------------
def _load_ms_centroids(study_union) -> gpd.GeoDataFrame:
    """Stream MS WV footprints, keep only those whose centroid is inside
    the study area, return GeoDataFrame of centroid Points."""
    if not MS_FOOTPRINTS.exists():
        raise FileNotFoundError(
            f"{MS_FOOTPRINTS} not found. Download Microsoft USBuildingFootprints "
            f"WestVirginia.geojson.zip first."
        )
    print(f"[buildings] loading MS footprints from {MS_FOOTPRINTS.name} (this is large)")
    t0 = time.time()
    minx, miny, maxx, maxy = study_union.bounds
    centroids = []
    feat_count = 0
    kept = 0
    gdf = gpd.read_file(MS_FOOTPRINTS, bbox=(minx, miny, maxx, maxy))
    feat_count = len(gdf)
    print(f"[buildings] MS bbox-prefilter: {feat_count:,} polygons in study bbox "
          f"({time.time() - t0:.1f}s)")
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    cents = gdf.geometry.representative_point()
    inside_mask = cents.within(study_union)
    cents = cents[inside_mask].reset_index(drop=True)
    out = gpd.GeoDataFrame({"geometry": cents}, crs=4326)
    out["lon"] = out.geometry.x
    out["lat"] = out.geometry.y
    print(f"[buildings] MS centroids inside study area: {len(out):,} "
          f"(of {feat_count:,} bbox candidates)")
    return out


# ---------------------------------------------------------------------
# Step 4: spatial join MS centroids -> nearest OSM building tag
# ---------------------------------------------------------------------
def _tag_ms_with_osm(ms: gpd.GeoDataFrame, osm_df: pd.DataFrame) -> gpd.GeoDataFrame:
    """For each MS centroid, find the nearest OSM building (by lon/lat KDTree
    in projected feet-ish units) within 25 m. If found, copy its tag.
    Otherwise the building is 'unknown_ms_only'.
    """
    if osm_df.empty:
        ms["osm_tag"] = None
        ms["classification"] = "unknown_ms_only"
        return ms
    LAT0 = 38.5
    M_PER_DEG_LAT = 111_132.0
    M_PER_DEG_LON = 111_320.0 * np.cos(np.radians(LAT0))

    osm_xy = np.column_stack([
        osm_df["lon"].values * M_PER_DEG_LON,
        osm_df["lat"].values * M_PER_DEG_LAT,
    ])
    ms_xy = np.column_stack([
        ms["lon"].values * M_PER_DEG_LON,
        ms["lat"].values * M_PER_DEG_LAT,
    ])
    tree = cKDTree(osm_xy)
    dists, idxs = tree.query(ms_xy, distance_upper_bound=25.0)
    valid = dists != np.inf
    tags = np.full(len(ms), None, dtype=object)
    tags[valid] = osm_df["building_tag"].values[idxs[valid]]
    ms["osm_tag"] = tags
    ms["classification"] = [
        _classify_osm_tag(t) if t is not None else "unknown_ms_only"
        for t in tags
    ]
    return ms


# ---------------------------------------------------------------------
# Step 5: compute supermarket access per snapshot year
# ---------------------------------------------------------------------
def _load_supermarkets_by_year() -> dict[int, np.ndarray]:
    """Return {year: (N, 2) lon/lat array of full-service grocers}."""
    p = PROCESSED / "grocers_by_year.geojson"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Run pipeline.grocers_by_year first."
        )
    fc = json.loads(p.read_text(encoding="utf-8"))
    by_year: dict[int, list[tuple[float, float]]] = {y: [] for y in SNAPSHOT_YEARS}
    for f in fc["features"]:
        p2 = f.get("properties") or {}
        if p2.get("store_type") not in FULL_SERVICE_TYPES:
            continue
        y = p2.get("snapshot_year")
        if y not in by_year:
            continue
        coords = f["geometry"]["coordinates"]
        by_year[y].append((float(coords[0]), float(coords[1])))
    return {y: np.array(pts, dtype=float) for y, pts in by_year.items() if pts}


def _haversine_min_miles(lon: np.ndarray, lat: np.ndarray,
                         supers_lon: np.ndarray, supers_lat: np.ndarray) -> np.ndarray:
    """For each (lon[i], lat[i]) building, return min haversine distance
    (in miles) to any supermarket in supers_*."""
    R_MI = 3958.7613
    out = np.empty(len(lon), dtype=float)
    chunk = 20_000
    s_lat_r = np.radians(supers_lat)
    s_lon_r = np.radians(supers_lon)
    for start in range(0, len(lon), chunk):
        stop = min(start + chunk, len(lon))
        b_lat_r = np.radians(lat[start:stop])[:, None]
        b_lon_r = np.radians(lon[start:stop])[:, None]
        dlat = s_lat_r[None, :] - b_lat_r
        dlon = s_lon_r[None, :] - b_lon_r
        a = np.sin(dlat / 2) ** 2 + np.cos(b_lat_r) * np.cos(s_lat_r[None, :]) * np.sin(dlon / 2) ** 2
        d = 2 * R_MI * np.arcsin(np.sqrt(a))
        out[start:stop] = d.min(axis=1)
    return out


# ---------------------------------------------------------------------
# Step 6: rural/urban classification per building
# ---------------------------------------------------------------------
def _attach_rural_flag(buildings: gpd.GeoDataFrame, counties: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """USDA Food Access Atlas treats counties under a population-density
    threshold as rural. We simplify and use the US Census urbanized area
    flag at the county level: a county is 'rural' if it has no Census
    Urbanized Area (population >= 50k contiguous). For our southern-WV
    study counties only Kanawha and Raleigh contain UAs (Charleston, Beckley);
    everything else is rural.
    """
    URBAN_COUNTIES = {"Kanawha", "Raleigh"}
    joined = gpd.sjoin(
        buildings, counties[["NAME", "geometry"]], how="left", predicate="within"
    )
    joined = joined[~joined.index.duplicated(keep="first")]
    buildings["county"] = joined["NAME"].values
    buildings["rural"] = ~buildings["county"].isin(URBAN_COUNTIES)
    return buildings


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> None:
    counties, study_union = _load_study_area()
    print(f"[buildings] study area: {len(counties)} counties")

    ms = _load_ms_centroids(study_union)

    bbox = study_union.bounds
    osm = _fetch_osm_buildings(bbox)
    osm_df = _osm_buildings_df(osm)
    print(f"[buildings] OSM buildings parsed: {len(osm_df):,}")
    if not osm_df.empty:
        top = osm_df["building_tag"].value_counts().head(10)
        print("[buildings] top OSM building tags:")
        for tag, n in top.items():
            print(f"           {tag:>20s}  {n:,}")

    ms = _tag_ms_with_osm(ms, osm_df)
    print("[buildings] classification breakdown (all MS centroids in study area):")
    for cls, n in ms["classification"].value_counts().items():
        print(f"           {cls:>22s}  {n:,}")

    res_mask = ms["classification"].isin(
        {"osm_residential", "osm_yes_or_unknown", "unknown_ms_only"}
    )
    res = ms[res_mask].copy().reset_index(drop=True)
    print(f"[buildings] residential candidates after non-residential filter: {len(res):,}")
    print(f"           (excluded {(~res_mask).sum():,} non-residential OSM-tagged buildings)")

    res = _attach_rural_flag(res, counties)
    rural_n = int(res["rural"].sum())
    urban_n = int((~res["rural"]).sum())
    print(f"[buildings] rural buildings: {rural_n:,} · urban: {urban_n:,}")

    supers = _load_supermarkets_by_year()
    print(f"[buildings] supermarket counts by year:")
    for y in SNAPSHOT_YEARS:
        n = len(supers.get(y, []))
        print(f"           {y}: {n}")

    lon = res["lon"].values
    lat = res["lat"].values
    for y in SNAPSHOT_YEARS:
        pts = supers.get(y)
        if pts is None or len(pts) == 0:
            res[f"dist_mi_{y}"] = np.nan
            res[f"low_access_{y}"] = False
            continue
        d = _haversine_min_miles(lon, lat, pts[:, 0], pts[:, 1])
        res[f"dist_mi_{y}"] = d
        threshold = np.where(res["rural"].values, 10.0, 1.0)
        res[f"low_access_{y}"] = d > threshold

    print("\n[buildings] LOW-ACCESS RESIDENTIAL BUILDINGS BY YEAR")
    print("            (USDA standard: >1mi urban or >10mi rural to nearest")
    print("             Supermarket or Super Store)")
    print(f"            total residential: {len(res):,}")
    for y in SNAPSHOT_YEARS:
        n = int(res[f"low_access_{y}"].sum())
        pct = 100.0 * n / max(len(res), 1)
        print(f"            {y}: {n:>7,}  ({pct:5.1f}%)")

    out_path = PROCESSED / "buildings_residential.geojson"
    keep_cols = (
        ["geometry", "lon", "lat", "county", "rural", "classification", "osm_tag"]
        + [f"dist_mi_{y}" for y in SNAPSHOT_YEARS]
        + [f"low_access_{y}" for y in SNAPSHOT_YEARS]
    )
    out = res[keep_cols].copy()
    for y in SNAPSHOT_YEARS:
        out[f"dist_mi_{y}"] = out[f"dist_mi_{y}"].round(2)
    out.to_file(out_path, driver="GeoJSON")
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n[buildings] wrote {out_path.name} ({len(out):,} buildings, {size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
