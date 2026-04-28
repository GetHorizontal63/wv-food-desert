"""Process OSM grocery points into the study-area grocery layer.

Reads data/raw/osm_grocery_wv.geojson (produced by pipeline.acquire) and
clips to the southern WV county polygons.

Convenience stores and small "shop=grocery" tagged nodes that are
clearly not full-service (e.g. tagged as gas stations) are filtered.
"""
from __future__ import annotations
import geopandas as gpd

from .config import RAW, PROCESSED

FULL_SERVICE_BRANDS = (
    "kroger", "foodland", "save-a-lot", "save a lot", "aldi", "walmart",
    "shop n save", "shop 'n save", "fas chek", "piggly wiggly", "food city",
    "sam's club", "sams club", "iga ", " iga", "trader joe",
    "weis", "giant eagle", "food lion",
)


def _s(v) -> str:
    if v is None:
        return ""
    try:
        if v != v:
            return ""
    except Exception:
        pass
    return str(v).lower()


def _is_full_service(props: dict) -> bool:
    if _s(props.get("shop")) == "supermarket":
        return True
    haystack = _s(props.get("name")) + " " + _s(props.get("brand"))
    return any(b in haystack for b in FULL_SERVICE_BRANDS)


def main() -> None:
    src = RAW / "osm_grocery_wv.geojson"
    if not src.exists():
        print(f"[retail] missing {src.name} - run pipeline.acquire first")
        gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_file(
            PROCESSED / "grocery_current.geojson", driver="GeoJSON"
        )
        return

    osm = gpd.read_file(src)
    if osm.crs is None:
        osm = osm.set_crs("EPSG:4326")

    full = osm[osm.apply(lambda r: _is_full_service(r.to_dict()), axis=1)].copy()

    counties = gpd.read_file(PROCESSED / "southern_wv_counties.geojson").to_crs("EPSG:4326")
    clipped = gpd.sjoin(
        full, counties[["geometry", "NAME"]], how="inner", predicate="within"
    ).drop(columns=["index_right"], errors="ignore")

    out = PROCESSED / "grocery_current.geojson"
    if clipped.empty:
        gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_file(out, driver="GeoJSON")
    else:
        clipped.to_file(out, driver="GeoJSON")
    print(f"[retail] wrote {out.name} ({len(clipped)} full-service grocery points in study area)")


if __name__ == "__main__":
    main()
