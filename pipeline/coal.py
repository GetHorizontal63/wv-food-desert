"""Fetch real MSHA coal mine employment for WV counties (1983-present).

Source: U.S. Department of Labor - Mine Safety & Health Administration
Open Government datasets at https://arlweb.msha.gov/OpenGovernmentData/

Two files joined on MINE_ID:
  Mines.zip                       -> mine master (FIPS_CNTY, COAL_METAL_IND, STATE)
  EmploymentProductionDataSet.zip -> annual AVG_EMPLOYEE_CNT, COAL_PRODUCTION per year

Outputs:
  data/processed/coal_employment.csv
    columns: county_fips, county_name, year, employees, production_short_tons
  data/processed/coal_decline.geojson
    per-county features with peak_year, peak_emp, recent_emp, pct_change_from_peak
"""
from __future__ import annotations
import io
import zipfile
from pathlib import Path

import pandas as pd
import geopandas as gpd
import requests

from .config import RAW, PROCESSED

MINES_URL = "https://arlweb.msha.gov/OpenGovernmentData/DataSets/Mines.zip"
EMP_URL = "https://arlweb.msha.gov/OpenGovernmentData/DataSets/MinesProdYearly.zip"

MINES_TXT = RAW / "msha_mines.txt"
EMP_TXT = RAW / "msha_employment_production.txt"


def _download_inner_txt(url: str, out: Path) -> Path:
    """MSHA ships pipe-delimited TXT files inside ZIPs. Cache the inner file."""
    if out.exists() and out.stat().st_size > 0:
        return out
    print(f"[coal] downloading {url}")
    r = requests.get(url, timeout=300, headers={"User-Agent": "wv-food-desert/1.0"})
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = [n for n in z.namelist()
                 if n.lower().endswith(".txt") and "definition" not in n.lower()]
        if not names:
            names = [n for n in z.namelist() if not n.endswith("/")]
        with z.open(names[0]) as f:
            out.write_bytes(f.read())
    print(f"[coal]   -> {out.name} ({out.stat().st_size:,} bytes)")
    return out


def main() -> None:
    mines_path = _download_inner_txt(MINES_URL, MINES_TXT)
    emp_path = _download_inner_txt(EMP_URL, EMP_TXT)

    mines = pd.read_csv(
        mines_path, sep="|", dtype=str, encoding="latin-1",
        engine="python", on_bad_lines="skip",
    )
    emp = pd.read_csv(
        emp_path, sep="|", dtype=str, encoding="latin-1",
        engine="python", on_bad_lines="skip",
    )
    print(f"[coal] mines rows={len(mines):,}")
    print(f"[coal] emp    rows={len(emp):,}")

    state_col = "STATE" if "STATE" in mines.columns else "CURRENT_MINE_STATE"
    coal_col = "COAL_METAL_IND" if "COAL_METAL_IND" in mines.columns else "COMMODITY"
    fips_col = next((c for c in ("FIPS_CNTY_CD", "FIPS_CNTY", "COUNTY_FIPS") if c in mines.columns), None)
    cname_col = next((c for c in ("FIPS_CNTY_NM", "COUNTY_NM", "COUNTY") if c in mines.columns), None)
    if not fips_col:
        raise RuntimeError(f"[coal] no FIPS column in mines: {list(mines.columns)}")

    mines = mines[mines[state_col].astype(str).str.upper().str.strip() == "WV"]
    mines = mines[mines[coal_col].astype(str).str.upper().str.strip() == "C"]
    keep_cols = ["MINE_ID", fips_col]
    if cname_col:
        keep_cols.append(cname_col)
    mines = mines[keep_cols].rename(
        columns={fips_col: "county_fips", **({cname_col: "county_name"} if cname_col else {})}
    )
    mines["county_fips"] = mines["county_fips"].astype(str).str.strip().str.zfill(3)
    if "county_name" not in mines.columns:
        mines["county_name"] = ""
    print(f"[coal] WV coal mines: {len(mines):,}")

    needed = {"MINE_ID", "CALENDAR_YR"}
    if not needed.issubset(emp.columns):
        raise RuntimeError(f"[coal] emp missing cols: {sorted(needed - set(emp.columns))}")
    if "C_M_IND" in emp.columns:
        emp = emp[emp["C_M_IND"].astype(str).str.upper().str.strip() == "C"]
    emp = emp[["MINE_ID", "CALENDAR_YR", "AVG_ANNUAL_EMPL", "ANNUAL_COAL_PROD"]].copy()
    emp["year"] = pd.to_numeric(emp["CALENDAR_YR"], errors="coerce")
    emp["employees"] = pd.to_numeric(emp["AVG_ANNUAL_EMPL"], errors="coerce")
    emp["production_short_tons"] = pd.to_numeric(emp["ANNUAL_COAL_PROD"], errors="coerce")
    emp = emp.dropna(subset=["year"])
    emp = emp.groupby(["MINE_ID", "year"], as_index=False).agg(
        employees=("employees", "sum"),
        production_short_tons=("production_short_tons", "sum"),
    )

    j = emp.merge(mines, on="MINE_ID", how="inner")
    j = j[j["year"] >= 2000]
    j = j.groupby(["county_fips", "county_name", "year"], as_index=False).agg(
        employees=("employees", "sum"),
        production_short_tons=("production_short_tons", "sum"),
    )
    j["year"] = j["year"].astype(int)
    j = j.sort_values(["county_fips", "year"])

    out_csv = PROCESSED / "coal_employment.csv"
    j.to_csv(out_csv, index=False)
    print(f"[coal] wrote {out_csv.name} ({len(j):,} county-years)")

    rows = []
    for fips, grp in j.groupby("county_fips"):
        grp = grp.sort_values("year")
        if grp["employees"].max() <= 0:
            continue
        peak = grp.loc[grp["employees"].idxmax()]
        recent = grp.iloc[-1]
        peak_emp = float(peak["employees"])
        recent_emp = float(recent["employees"])
        pct = ((recent_emp - peak_emp) / peak_emp * 100.0) if peak_emp > 0 else 0.0
        rows.append({
            "county_fips": fips,
            "county_name": str(peak["county_name"]),
            "peak_year": int(peak["year"]),
            "peak_emp": int(peak_emp),
            "recent_year": int(recent["year"]),
            "recent_emp": int(recent_emp),
            "pct_change_from_peak": round(pct, 1),
        })
    summary_df = pd.DataFrame(rows)

    counties_path = PROCESSED / "southern_wv_counties.geojson"
    if counties_path.exists():
        counties = gpd.read_file(counties_path)
        counties["county_fips"] = counties["COUNTYFP"].astype(str).str.zfill(3)
        merged = counties.merge(summary_df, on="county_fips", how="left")
        merged["peak_emp"] = merged["peak_emp"].fillna(0).astype(int)
        merged["recent_emp"] = merged["recent_emp"].fillna(0).astype(int)
        merged["pct_change_from_peak"] = merged["pct_change_from_peak"].fillna(0.0)
        merged["peak_year"] = merged["peak_year"].fillna(0).astype(int)
        merged["recent_year"] = merged["recent_year"].fillna(0).astype(int)
        out_gj = PROCESSED / "coal_decline.geojson"
        if out_gj.exists():
            out_gj.unlink()
        merged.to_file(out_gj, driver="GeoJSON")
        with_coal = (merged["peak_emp"] > 0).sum()
        print(f"[coal] wrote {out_gj.name} ({with_coal} of {len(merged)} counties had MSHA coal)")
    else:
        print("[coal] skip GeoJSON - run pipeline.acquire first")


if __name__ == "__main__":
    main()
