"""HRSA primary-care HPSA shortage-area overlay clipped to study area.

Auto-fetches HRSA Data Warehouse Primary Care HPSA detail file from:
  https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv

Filters to WV "Designated" HPSAs whose county appears in the study area,
then emits county polygons flagged hpsa_designated=True so the frontend
can paint them.
"""
from __future__ import annotations
import zipfile
import io
from pathlib import Path

import pandas as pd
import geopandas as gpd
import requests

from .config import RAW, PROCESSED


HRSA_URL = "https://data.hrsa.gov/DataDownload/DD_Files/BCD_HPSA_FCT_DET_PC.csv"
HRSA_CACHE = RAW / "hrsa_hpsa_primary_care.csv"


def _fetch_hrsa_csv() -> Path | None:
    if HRSA_CACHE.exists() and HRSA_CACHE.stat().st_size > 0:
        return HRSA_CACHE
    try:
        print(f"[health] downloading {HRSA_URL}")
        r = requests.get(HRSA_URL, timeout=120, headers={"User-Agent": "wv-food-desert/1.0"})
        r.raise_for_status()
        HRSA_CACHE.write_bytes(r.content)
        print(f"[health]   -> {HRSA_CACHE.name} ({HRSA_CACHE.stat().st_size:,} bytes)")
        return HRSA_CACHE
    except Exception as e:
        print(f"[health] HRSA download failed: {e}")
        return None


def _load_csv() -> pd.DataFrame | None:
    p = _fetch_hrsa_csv()
    if p and p.exists():
        return pd.read_csv(p, dtype=str, encoding="latin-1",
                           engine="python", on_bad_lines="skip")
    z = RAW / "hrsa_hpsa_primary_care.zip"
    if z.exists():
        with zipfile.ZipFile(z) as zf:
            csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if csvs:
                with zf.open(csvs[0]) as fh:
                    return pd.read_csv(io.BytesIO(fh.read()), dtype=str)
    return None


def main() -> None:
    counties = gpd.read_file(PROCESSED / "southern_wv_counties.geojson")
    out = PROCESSED / "hrsa_shortage.geojson"

    geo_src = RAW / "hrsa_hpsa_primary_care.geojson"
    if geo_src.exists():
        hpsa = gpd.read_file(geo_src)
        clipped = gpd.overlay(hpsa.to_crs(counties.crs), counties, how="intersection")
        if out.exists():
            out.unlink()
        clipped.to_file(out, driver="GeoJSON")
        print(f"[health] wrote {out.name} ({len(clipped)} polygons from GeoJSON source)")
        return

    df = _load_csv()
    if df is None:
        if out.exists():
            out.unlink()
        gpd.GeoDataFrame(geometry=[], crs=counties.crs).to_file(out, driver="GeoJSON")
        print(f"[health] no HRSA source - wrote empty {out.name}")
        return

    cols = {c.lower(): c for c in df.columns}
    state_col = next((cols[c] for c in cols if "state" in c and "abbr" in c), None)
    name_col = next((cols[c] for c in cols if "common county name" in c), None) \
        or next((cols[c] for c in cols if "county" in c and "name" in c), None)
    status_col = next((cols[c] for c in cols if "hpsa status" in c), None) \
        or next((cols[c] for c in cols if c == "status"), None)
    discipline_col = next((cols[c] for c in cols if "discipline" in c), None)

    if not (state_col and name_col):
        if out.exists():
            out.unlink()
        gpd.GeoDataFrame(geometry=[], crs=counties.crs).to_file(out, driver="GeoJSON")
        print(f"[health] HRSA columns unrecognized: {list(df.columns)[:10]}…")
        return

    wv = df[df[state_col].astype(str).str.upper().str.strip() == "WV"]
    if status_col:
        wv = wv[wv[status_col].astype(str).str.contains("Designated", case=False, na=False)]
    if discipline_col:
        wv = wv[wv[discipline_col].astype(str).str.contains("Primary", case=False, na=False)]

    designated = (
        wv[name_col].dropna().astype(str)
        .str.replace(r",\s*WV.*$", "", regex=True)
        .str.replace(" County", "", regex=False)
        .str.strip()
        .unique()
    )
    flagged = counties[counties["NAME"].isin(designated)].copy()
    flagged["hpsa_designated"] = True
    if out.exists():
        out.unlink()
    if len(flagged):
        flagged.to_file(out, driver="GeoJSON")
    else:
        gpd.GeoDataFrame(geometry=[], crs=counties.crs).to_file(out, driver="GeoJSON")
    print(f"[health] wrote {out.name} ({len(flagged)} of {len(counties)} study counties HPSA-designated)")


if __name__ == "__main__":
    main()
