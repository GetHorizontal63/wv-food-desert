"""Active SNAP-authorized grocery retailers in West Virginia at five
snapshot years, statewide.

Source: USDA Food and Nutrition Service "Historical SNAP Retailer Locator
Data 2005-2025" (zipped CSV). Each retailer row carries an Authorization
Date and an End Date - to materialize a snapshot at year Y we keep rows
where auth_date <= Y-01-01 AND (end_date IS NULL OR end_date >= Y-01-01).

We keep only true grocery retailers - Store Type in:
  - "Supermarket"
  - "Super Store"
  - "Large Grocery Store"
  - "Medium Grocery Store"
  - "Small Grocery Store"
  - "Combination Grocery/Other"
We exclude Convenience Stores, Dollar Stores, Pharmacies, Specialty Stores,
Farmers Markets, Wholesalers, etc.

Output: data/processed/grocers_by_year.geojson
  - Point features only (no count bubbles)
  - properties: snapshot_year, name, store_type, address, city, county,
                authorization_date, end_date
"""
from __future__ import annotations
import json
import zipfile
from pathlib import Path

import pandas as pd

from .config import RAW, PROCESSED


SNAP_ZIP = RAW / "snap_retailers_2005_2025.zip"
SNAPSHOT_YEARS = [2005, 2010, 2015, 2020, 2025]

GROCERY_TYPES = {
    "Supermarket",
    "Super Store",
    "Large Grocery Store",
    "Medium Grocery Store",
    "Small Grocery Store",
    "Combination Grocery/Other",
}


def _parse_dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str).str.strip(), errors="coerce")


def main() -> None:
    if not SNAP_ZIP.exists():
        print(f"[grocers] missing {SNAP_ZIP} - abort")
        return

    with zipfile.ZipFile(SNAP_ZIP) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            df = pd.read_csv(fh, dtype=str, encoding="utf-8", on_bad_lines="skip")

    df.columns = [c.strip() for c in df.columns]
    print(f"[grocers] loaded {len(df):,} retailer rows nationwide")

    df = df[df["State"].astype(str).str.strip().str.upper() == "WV"].copy()
    print(f"[grocers]   {len(df):,} WV retailer rows (all types)")
    df["Store Type"] = df["Store Type"].astype(str).str.strip()
    df = df[df["Store Type"].isin(GROCERY_TYPES)].copy()
    print(f"[grocers]   {len(df):,} WV grocery rows after type filter")

    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df = df[(df["Latitude"].between(37.0, 41.0)) & (df["Longitude"].between(-83.0, -77.0))].copy()
    print(f"[grocers]   {len(df):,} WV grocery rows with usable coordinates")

    df["auth_date"] = _parse_dates(df["Authorization Date"])
    df["end_date"] = _parse_dates(df["End Date"])

    features: list[dict] = []
    for year in SNAPSHOT_YEARS:
        snap_dt = pd.Timestamp(f"{year}-01-01")
        active = df[
            (df["auth_date"].notna()) & (df["auth_date"] <= snap_dt) &
            ((df["end_date"].isna()) | (df["end_date"] >= snap_dt))
        ]
        active = active.drop_duplicates(subset=["Record ID"], keep="first")
        print(f"[grocers]   {year}: {len(active):,} active grocers in WV")
        for _, row in active.iterrows():
            try:
                lon = float(row["Longitude"]); lat = float(row["Latitude"])
            except Exception:
                continue
            street_num = row.get("Street Number")
            street_name = row.get("Street Name")
            sn = str(street_num).strip() if street_num is not None and pd.notna(street_num) else ""
            stn = str(street_name).strip() if street_name is not None and pd.notna(street_name) else ""
            street = f"{sn} {stn}".strip()
            def _s(k):
                v = row.get(k)
                return str(v).strip() if v is not None and pd.notna(v) else ""
            ad = row.get("auth_date"); ed = row.get("end_date")
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "snapshot_year": int(year),
                    "kind": "store_point",
                    "name": _s("Store Name"),
                    "store_type": _s("Store Type"),
                    "address": street,
                    "city": _s("City"),
                    "county": _s("County"),
                    "authorization_date": str(ad.date()) if pd.notna(ad) else None,
                    "end_date": str(ed.date()) if pd.notna(ed) else None,
                    "source": "USDA-FNS SNAP Retailer Locator (historical 2005–2025)",
                },
            })

    fc = {"type": "FeatureCollection", "features": features}
    out = PROCESSED / "grocers_by_year.geojson"
    out.write_text(json.dumps(fc), encoding="utf-8")
    size_kb = out.stat().st_size / 1024
    print(f"\n[grocers] wrote {out.name} ({len(features):,} features, {size_kb:,.0f} KB)")
    by_year: dict[int, int] = {}
    for f in features:
        y = f["properties"]["snapshot_year"]
        by_year[y] = by_year.get(y, 0) + 1
    for y in sorted(by_year):
        print(f"           {y}: {by_year[y]} grocers")


if __name__ == "__main__":
    main()
