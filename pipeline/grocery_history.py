"""Grocery store establishment counts by WV county, year-over-year.

Source: U.S. Census Bureau County Business Patterns (CBP)
NAICS code 4451 = "Grocery Stores" (Supermarkets + Convenience stores).
Subset 445110 = "Supermarkets and Other Grocery (except Convenience) Stores"
is the closest match to "full-service grocery." CBP publishes ESTAB
(establishment count) annually by county.

CBP NAICS coding switched from NAICS2002 (1998-2002) → NAICS2007 (2003-2007)
→ NAICS2012 (2008-2017) → NAICS2017 (2018+). The 4451/445110 codes are
stable across all of these vintages so we just request both and use whichever
is non-null.

API: https://api.census.gov/data/{year}/cbp  (no key required)

Output: data/processed/grocery_history.csv
  county_fips, county_name, year, estab_4451, estab_445110
plus: data/processed/grocery_history.geojson
  per-county features with first_year, last_year, estab_first, estab_last,
  pct_change, trajectory (sparkline-friendly array of {year, estab_445110})
"""
from __future__ import annotations
import json
import time

import pandas as pd
import geopandas as gpd
import requests

from .config import PROCESSED, WV_FIPS


YEARS = list(range(1998, 2023))

NAICS_VARS = ["NAICS2017", "NAICS2012", "NAICS2007", "NAICS2002"]


def _fetch_year(year: int) -> pd.DataFrame | None:
    """Pull NAICS=4451 and NAICS=445110 establishment counts for WV counties."""
    base = f"https://api.census.gov/data/{year}/cbp"
    rows_per_naics: dict[str, pd.DataFrame] = {}
    for naics_value in ("4451", "445110"):
        ok = False
        for var in NAICS_VARS:
            url = f"{base}?get=ESTAB,NAME,{var}&for=county:*&in=state:{WV_FIPS}&{var}={naics_value}"
            try:
                r = requests.get(url, timeout=30, headers={"User-Agent": "wv-food-desert/1.0"})
                if r.status_code != 200:
                    continue
                data = r.json()
            except Exception:
                continue
            if not data or len(data) < 2:
                continue
            header, *body = data
            df = pd.DataFrame(body, columns=header)
            df["year"] = year
            df["naics_value"] = naics_value
            df["estab"] = pd.to_numeric(df["ESTAB"], errors="coerce")
            df["county_fips"] = df["county"].str.zfill(3)
            rows_per_naics[naics_value] = df[["county_fips", "NAME", "year", "naics_value", "estab"]]
            ok = True
            break
        if not ok:
            pass
    if not rows_per_naics:
        return None
    out = pd.concat(rows_per_naics.values(), ignore_index=True)
    return out


def main() -> None:
    print(f"[grocery] fetching CBP {YEARS[0]}–{YEARS[-1]} for WV NAICS 4451/445110…")
    frames = []
    for y in YEARS:
        df = _fetch_year(y)
        if df is not None and len(df):
            frames.append(df)
            print(f"[grocery]   {y}: {len(df)} county-NAICS rows")
        else:
            print(f"[grocery]   {y}: no data")
        time.sleep(0.15)

    if not frames:
        print("[grocery] no CBP data fetched - abort")
        return

    long = pd.concat(frames, ignore_index=True)
    wide = long.pivot_table(
        index=["county_fips", "NAME", "year"],
        columns="naics_value", values="estab", aggfunc="first",
    ).reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={"4451": "estab_4451", "445110": "estab_445110", "NAME": "county_name"})
    for c in ("estab_4451", "estab_445110"):
        if c not in wide.columns:
            wide[c] = pd.NA
    wide = wide[["county_fips", "county_name", "year", "estab_4451", "estab_445110"]]

    csv_out = PROCESSED / "grocery_history.csv"
    wide.to_csv(csv_out, index=False)
    print(f"[grocery] wrote {csv_out.name} ({len(wide):,} county-years)")

    rows = []
    for fips, grp in wide.groupby("county_fips"):
        grp = grp.sort_values("year")
        grp["estab"] = grp["estab_445110"].combine_first(grp["estab_4451"])
        valid = grp.dropna(subset=["estab"])
        if valid.empty:
            continue
        first = valid.iloc[0]; last = valid.iloc[-1]
        e0 = float(first["estab"]); e1 = float(last["estab"])
        pct = ((e1 - e0) / e0 * 100.0) if e0 > 0 else 0.0
        traj = [
            {"year": int(r["year"]), "estab": int(r["estab"])}
            for _, r in valid.iterrows()
        ]
        rows.append({
            "county_fips": fips,
            "county_name": str(first["county_name"]),
            "first_year": int(first["year"]),
            "last_year": int(last["year"]),
            "estab_first": int(e0),
            "estab_last": int(e1),
            "pct_change": round(pct, 1),
            "trajectory_json": json.dumps(traj),
        })
    summary_df = pd.DataFrame(rows)

    counties_path = PROCESSED / "southern_wv_counties.geojson"
    if counties_path.exists():
        counties = gpd.read_file(counties_path)
        counties["county_fips"] = counties["COUNTYFP"].astype(str).str.zfill(3)
        merged = counties.merge(summary_df, on="county_fips", how="left")
        for c in ("estab_first", "estab_last", "first_year", "last_year"):
            merged[c] = merged[c].fillna(0).astype(int)
        merged["pct_change"] = merged["pct_change"].fillna(0.0)
        merged["trajectory_json"] = merged["trajectory_json"].fillna("[]")
        out_gj = PROCESSED / "grocery_history.geojson"
        if out_gj.exists():
            out_gj.unlink()
        merged.to_file(out_gj, driver="GeoJSON")
        with_data = (merged["estab_first"] > 0).sum()
        print(f"[grocery] wrote {out_gj.name} ({with_data} of {len(merged)} counties had CBP grocery data)")


if __name__ == "__main__":
    main()
