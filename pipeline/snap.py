"""SNAP household participation by Census tract from ACS 5-year.

Source: U.S. Census Bureau ACS 5-year detailed table B22003
  "Receipt of Food Stamps/SNAP in the Past 12 Months by Poverty Status"
  B22003_001E = households (universe)
  B22003_002E = households that received SNAP
B22003 is published at tract level.

API: https://api.census.gov/data/{year}/acs/acs5  (no key required)

Outputs:
  data/processed/snap_participation.csv          (tract-level)
  data/processed/snap_participation.geojson      (TIGER tract polygons,
                                                  clipped to study counties)
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd
import geopandas as gpd
import requests

from .config import PROCESSED, WV_FIPS


ACS_YEAR = 2022
URL = (
    f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
    "?get=NAME,B22003_001E,B22003_002E"
    f"&for=tract:*&in=state:{WV_FIPS}%20county:*"
)
TIGER_TRACTS_URL = (
    f"https://www2.census.gov/geo/tiger/TIGER{ACS_YEAR}/TRACT/"
    f"tl_{ACS_YEAR}_{WV_FIPS}_tract.zip"
)


def _study_county_fips() -> set[str]:
    """3-digit COUNTYFP values for the 19-county study region."""
    counties_path = PROCESSED / "southern_wv_counties.geojson"
    if counties_path.exists():
        cdf = gpd.read_file(counties_path)
        return set(cdf["COUNTYFP"].astype(str).str.zfill(3))
    return set()


def main() -> None:
    print(f"[snap] fetching ACS {ACS_YEAR} B22003 tracts for WV…")
    r = requests.get(URL, timeout=120, headers={"User-Agent": "wv-food-desert/1.0"})
    r.raise_for_status()
    rows = r.json()
    header, *data = rows
    df = pd.DataFrame(data, columns=header)
    df["state"] = df["state"].str.zfill(2)
    df["county"] = df["county"].str.zfill(3)
    df["tract"] = df["tract"].str.zfill(6)
    df["GEOID"] = df["state"] + df["county"] + df["tract"]
    df["total_hh"] = pd.to_numeric(df["B22003_001E"], errors="coerce").fillna(0).astype(int)
    df["snap_hh"] = pd.to_numeric(df["B22003_002E"], errors="coerce").fillna(0).astype(int)
    df["snap_pct"] = (
        df["snap_hh"] / df["total_hh"].replace(0, pd.NA) * 100
    ).astype("Float64").round(1)

    study = _study_county_fips()
    if study:
        before = len(df)
        df = df[df["county"].isin(study)].copy()
        print(f"[snap] clipped to study counties: {before} -> {len(df)} tracts")

    df = df[["GEOID", "NAME", "state", "county", "tract", "total_hh", "snap_hh", "snap_pct"]].rename(
        columns={"NAME": "tract_name"}
    )

    csv_out = PROCESSED / "snap_participation.csv"
    df.to_csv(csv_out, index=False)
    print(f"[snap] wrote {csv_out.name} ({len(df)} tracts)")

    print(f"[snap] downloading TIGER {ACS_YEAR} tract polygons for WV…")
    tr = requests.get(TIGER_TRACTS_URL, timeout=180, headers={"User-Agent": "wv-food-desert/1.0"})
    tr.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(tr.content))
    tracts_path = PROCESSED / f"tl_{ACS_YEAR}_{WV_FIPS}_tract"
    tracts_path.mkdir(parents=True, exist_ok=True)
    zf.extractall(tracts_path)
    shp = next(tracts_path.glob("*.shp"))
    tracts = gpd.read_file(shp).to_crs(epsg=4326)
    tracts["GEOID"] = tracts["GEOID"].astype(str)
    if study:
        tracts = tracts[tracts["COUNTYFP"].astype(str).str.zfill(3).isin(study)].copy()
    print(f"[snap] tract polygons in study: {len(tracts)}")

    merged = tracts.merge(
        df[["GEOID", "total_hh", "snap_hh", "snap_pct"]],
        on="GEOID",
        how="left",
    )
    keep = ["GEOID", "STATEFP", "COUNTYFP", "TRACTCE", "NAMELSAD",
            "total_hh", "snap_hh", "snap_pct", "geometry"]
    merged = merged[[c for c in keep if c in merged.columns]]

    out_gj = PROCESSED / "snap_participation.geojson"
    if out_gj.exists():
        out_gj.unlink()
    merged.to_file(out_gj, driver="GeoJSON")
    print(f"[snap] wrote {out_gj.name} ({len(merged)} tracts)")

    valid = merged.dropna(subset=["snap_pct"])
    if len(valid):
        tot_snap = int(valid["snap_hh"].sum())
        tot_hh = int(valid["total_hh"].sum())
        overall = round(100 * tot_snap / tot_hh, 1) if tot_hh else None
        print(f"[snap] study area: {tot_snap:,} SNAP households of {tot_hh:,} ({overall}%)")
        top = valid.sort_values("snap_pct", ascending=False).head(5)
        for _, row in top.iterrows():
            name = row.get("NAMELSAD", row["GEOID"])
            print(f"[snap]   {name} ({row['GEOID']}): {row['snap_pct']}%")


if __name__ == "__main__":
    main()
