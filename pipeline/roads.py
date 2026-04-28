"""Road network for the study area: primary, secondary, tertiary.

Source: OpenStreetMap via Overpass API. We pull `highway` ways tagged
motorway/trunk/primary/secondary/tertiary (plus `*_link` ramps for the
top three classes) within the bounding box of the 19 study counties,
then clip to the union polygon so we don't render roads outside the
narrative frame.

Output: data/processed/roads.geojson with a `road_class` property:
  "primary"      = motorway, trunk, primary  (heaviest)
  "secondary"    = secondary
  "tertiary"     = tertiary
  "unclassified" = unclassified                (lightest, rural connectors)
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import requests
import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import unary_union

from .config import RAW, PROCESSED


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

CACHE = RAW / "osm_roads_overpass.json"


def _overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """bbox = (south, west, north, east)"""
    s, w, n, e = bbox
    return f"""
[out:json][timeout:240];
(
  way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link)$"]({s},{w},{n},{e});
  way["highway"~"^(secondary|secondary_link)$"]({s},{w},{n},{e});
  way["highway"="tertiary"]({s},{w},{n},{e});
  way["highway"="unclassified"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;
""".strip()


def _classify(hwy: str) -> str | None:
    if not hwy:
        return None
    h = hwy.lower()
    if h in {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"}:
        return "primary"
    if h in {"secondary", "secondary_link"}:
        return "secondary"
    if h == "tertiary":
        return "tertiary"
    if h == "unclassified":
        return "unclassified"
    return None


def _fetch_overpass(query: str) -> dict:
    if CACHE.exists() and CACHE.stat().st_size > 0:
        print(f"[roads] using cache {CACHE.name}")
        return json.loads(CACHE.read_text(encoding="utf-8"))
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            print(f"[roads] querying {url} …")
            r = requests.post(url, data={"data": query}, timeout=240,
                              headers={"User-Agent": "wv-food-desert/1.0"})
            r.raise_for_status()
            data = r.json()
            CACHE.write_text(json.dumps(data), encoding="utf-8")
            print(f"[roads]   -> cached {CACHE.name} ({len(data.get('elements', []))} elements)")
            return data
        except Exception as e:
            print(f"[roads]   {url} failed: {e}")
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"all overpass endpoints failed: {last_err}")


def main() -> None:
    counties_path = PROCESSED / "southern_wv_counties.geojson"
    if not counties_path.exists():
        print("[roads] missing southern_wv_counties.geojson - abort")
        return
    counties = gpd.read_file(counties_path).to_crs(4326)
    minx, miny, maxx, maxy = counties.total_bounds
    bbox = (miny, minx, maxy, maxx)

    data = _fetch_overpass(_overpass_query(bbox))

    nodes = {el["id"]: (el["lon"], el["lat"]) for el in data["elements"] if el["type"] == "node"}
    rows = []
    for el in data["elements"]:
        if el["type"] != "way":
            continue
        cls = _classify((el.get("tags") or {}).get("highway"))
        if not cls:
            continue
        coords = [nodes[nid] for nid in el.get("nodes", []) if nid in nodes]
        if len(coords) < 2:
            continue
        rows.append({
            "road_class": cls,
            "name": (el.get("tags") or {}).get("name"),
            "ref": (el.get("tags") or {}).get("ref"),
            "geometry": LineString(coords),
        })

    if not rows:
        print("[roads] no ways extracted - abort")
        return

    roads = gpd.GeoDataFrame(rows, geometry="geometry", crs=4326)
    print(f"[roads] {len(roads):,} ways before clip "
          f"(primary={(roads.road_class=='primary').sum()}, "
          f"secondary={(roads.road_class=='secondary').sum()}, "
          f"tertiary={(roads.road_class=='tertiary').sum()}, "
          f"unclassified={(roads.road_class=='unclassified').sum()})")

    study_poly = unary_union(counties.geometry.values)
    roads = roads[roads.intersects(study_poly)].copy()
    roads["geometry"] = roads.geometry.intersection(study_poly)
    roads = roads[~roads.geometry.is_empty].copy()

    def _to_lines(geom):
        if geom is None or geom.is_empty:
            return None
        gt = geom.geom_type
        if gt in ("LineString", "MultiLineString"):
            return geom
        if gt == "GeometryCollection":
            lines = [g for g in geom.geoms if g.geom_type in ("LineString", "MultiLineString")]
            if not lines:
                return None
            from shapely.geometry import MultiLineString
            return lines[0] if len(lines) == 1 else MultiLineString(
                [g for ln in lines for g in (ln.geoms if ln.geom_type == "MultiLineString" else [ln])]
            )
        return None

    roads["geometry"] = roads.geometry.apply(_to_lines)
    roads = roads[roads.geometry.notna()].copy()
    roads = roads[~roads.geometry.is_empty].copy()
    print(f"[roads] {len(roads):,} ways after clip")

    out = PROCESSED / "roads.geojson"
    if out.exists():
        out.unlink()
    roads.to_file(out, driver="GeoJSON")
    size_kb = out.stat().st_size / 1024
    print(f"[roads] wrote {out.name} ({size_kb:,.0f} KB)")


if __name__ == "__main__":
    main()
