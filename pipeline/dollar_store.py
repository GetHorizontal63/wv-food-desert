"""Clip OSM dollar-store points to study counties."""
from __future__ import annotations
import geopandas as gpd

from .config import RAW, PROCESSED


def main() -> None:
    src = RAW / "osm_dollar_wv.geojson"
    if not src.exists():
        print(f"[dollar_store] missing {src.name}")
        gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_file(
            PROCESSED / "dollar_stores.geojson", driver="GeoJSON"
        )
        return

    osm = gpd.read_file(src)
    if osm.crs is None:
        osm = osm.set_crs("EPSG:4326")

    counties = gpd.read_file(PROCESSED / "southern_wv_counties.geojson").to_crs("EPSG:4326")
    clipped = gpd.sjoin(
        osm, counties[["geometry", "NAME"]], how="inner", predicate="within"
    ).drop(columns=["index_right"], errors="ignore")

    out = PROCESSED / "dollar_stores.geojson"
    if clipped.empty:
        gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").to_file(out, driver="GeoJSON")
    else:
        clipped.to_file(out, driver="GeoJSON")
    print(f"[dollar_store] wrote {out.name} ({len(clipped)} stores in study area)")


if __name__ == "__main__":
    main()
