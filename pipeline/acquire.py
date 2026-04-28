"""Download all publicly-fetchable raw data and build the southern WV
county boundary layer.

Strategy:
  - TIGER county boundaries     → US Census (direct, public, stable)
  - Grocery + dollar-store points → OpenStreetMap via Overpass API
    (free, unauthenticated; the USDA SNAP ArcGIS service now requires
    an API token so it cannot be used unattended)
  - HRSA HPSA designations       → best-effort; skipped gracefully on 404

Sources requiring accounts (NHGIS, MSHA archives) are bypassed by
fallbacks in their respective pipeline stages.
"""
from __future__ import annotations
import sys
from pathlib import Path

import requests
import geopandas as gpd

from .config import RAW, PROCESSED, WV_FIPS, SOUTHERN_WV_COUNTIES

TIGER_COUNTIES_URL = (
    "https://www2.census.gov/geo/tiger/TIGER2020/COUNTY/tl_2020_us_county.zip"
)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

WV_BBOX = (37.20, -82.65, 40.65, -77.72)

OVERPASS_GROCERY_QUERY = """
[out:json][timeout:90];
(
  node["shop"~"^(supermarket|grocery|greengrocer)$"]({s},{w},{n},{e});
  way["shop"~"^(supermarket|grocery|greengrocer)$"]({s},{w},{n},{e});
);
out center tags;
"""

OVERPASS_DOLLAR_QUERY = """
[out:json][timeout:90];
(
  node["name"~"Dollar General|Family Dollar|Dollar Tree",i]({s},{w},{n},{e});
  way["name"~"Dollar General|Family Dollar|Dollar Tree",i]({s},{w},{n},{e});
);
out center tags;
"""


def _stream_download(url: str, dest: Path, chunk: int = 1 << 16) -> bool:
    try:
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as f:
                for c in r.iter_content(chunk):
                    if c:
                        f.write(c)
            tmp.replace(dest)
        size_kb = dest.stat().st_size / 1024
        print(f"[acquire] OK {dest.name} ({size_kb:,.0f} KB)")
        return True
    except Exception as e:
        print(f"[acquire] FAIL {url}: {e}")
        return False


def _overpass(query: str) -> dict | None:
    s, w, n, e = WV_BBOX
    body = query.format(s=s, w=w, n=n, e=e)
    headers = {
        "User-Agent": "wv-food-desert-pipeline/1.0 (research; contact gabriel.cabrera.business@gmail.com)",
        "Accept": "application/json",
    }
    for ep in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(ep, data={"data": body}, headers=headers, timeout=300)
            r.raise_for_status()
            data = r.json()
            print(f"[acquire] Overpass via {ep}: {len(data.get('elements', []))} elements")
            return data
        except Exception as ex:
            print(f"[acquire] Overpass {ep} failed: {ex}")
    return None


def _osm_to_geojson(osm: dict, kind: str) -> dict:
    feats = []
    for el in osm.get("elements", []):
        if el["type"] == "node":
            lon, lat = el.get("lon"), el.get("lat")
        else:
            c = el.get("center") or {}
            lon, lat = c.get("lon"), c.get("lat")
        if lon is None or lat is None:
            continue
        tags = el.get("tags", {})
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "osm_id": el.get("id"),
                "osm_type": el.get("type"),
                "name": tags.get("name"),
                "shop": tags.get("shop"),
                "brand": tags.get("brand"),
                "addr_city": tags.get("addr:city"),
                "kind": kind,
            },
        })
    return {"type": "FeatureCollection", "features": feats}


def build_southern_wv_counties() -> gpd.GeoDataFrame:
    print("[acquire] downloading TIGER county boundaries…")
    counties = gpd.read_file(TIGER_COUNTIES_URL)
    wv = counties[counties["STATEFP"] == WV_FIPS].copy()

    southern = wv[wv["NAME"].isin(SOUTHERN_WV_COUNTIES)].copy()

    out = PROCESSED / "southern_wv_counties.geojson"
    southern.to_file(out, driver="GeoJSON")
    print(f"[acquire] OK {out.name} ({len(southern)} counties)")
    return southern


def fetch_grocery_osm() -> bool:
    print("[acquire] querying Overpass for grocery / supermarket points…")
    data = _overpass(OVERPASS_GROCERY_QUERY)
    if not data:
        return False
    import json
    gj = _osm_to_geojson(data, kind="grocery")
    out = RAW / "osm_grocery_wv.geojson"
    out.write_text(json.dumps(gj), encoding="utf-8")
    print(f"[acquire] OK {out.name} ({len(gj['features'])} features)")
    return True


def fetch_dollar_osm() -> bool:
    print("[acquire] querying Overpass for dollar stores…")
    data = _overpass(OVERPASS_DOLLAR_QUERY)
    if not data:
        return False
    import json
    gj = _osm_to_geojson(data, kind="dollar")
    out = RAW / "osm_dollar_wv.geojson"
    out.write_text(json.dumps(gj), encoding="utf-8")
    print(f"[acquire] OK {out.name} ({len(gj['features'])} features)")
    return True


def main() -> None:
    build_southern_wv_counties()
    fetch_grocery_osm()
    fetch_dollar_osm()
    print()
    print("[acquire] sources skipped (auth / unstable URL) - handled by fallbacks:")
    print("  - NHGIS decennial population  → embedded Census decennial table")
    print("  - MSHA mine employment        → coal stage emits empty placeholder")
    print("  - HRSA HPSA designations      → health stage emits empty placeholder")
    print("  - Valhalla isochrones         → buffer fallback (RURAL_AVG_KMH=48)")


if __name__ == "__main__":
    sys.exit(main())
