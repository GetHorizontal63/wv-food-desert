"""Bundle processed pipeline outputs into a single web-ready JSON payload.

The frontend loads `web/data/web_bundle.json` at startup. Geometries are
simplified to keep payload size under ~15 MB for GitHub Pages delivery.
"""
from __future__ import annotations
import json
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import PROCESSED, WEB_DATA

SIMPLIFY_TOL = 0.0005


def _gj(path: Path, simplify: bool = True) -> dict | None:
    if not path.exists():
        print(f"[export] skip missing {path.name}")
        return None
    gdf = gpd.read_file(path)
    if simplify and not gdf.empty:
        gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOL, preserve_topology=True)
    return json.loads(gdf.to_json())


def _gj_raw(path: Path) -> dict | None:
    """Pass-through GeoJSON load - preserves string properties (dates etc)
    that geopandas would otherwise coerce to Timestamps."""
    if not path.exists():
        print(f"[export] skip missing {path.name}")
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list | None:
    if not path.exists():
        print(f"[export] skip missing {path.name}")
        return None
    return pd.read_csv(path).to_dict(orient="records")


def _buildings_compact() -> dict | None:
    """Compact residential-buildings payload for step 4.

    The full GeoJSON is ~180 MB (381k polygons). Step 4 renders these as
    1-px canvas dots, so we throw away geometry and emit parallel arrays
    of [lon, lat, mask] where mask is a 5-bit field, bit i = low_access
    in YEARS[i]. Written as its own file so it doesn't bloat the main
    bundle.
    """
    src = PROCESSED / "buildings_residential.geojson"
    if not src.exists():
        print("[export] skip missing buildings_residential.geojson")
        return None
    YEARS = [2005, 2010, 2015, 2020, 2025]
    raw = json.loads(src.read_text(encoding="utf-8"))
    feats = raw.get("features", [])

    drive_src = PROCESSED / "buildings_drive_distances.json"
    drive_2005 = drive_2025 = drive_delta = None
    if drive_src.exists():
        ds = json.loads(drive_src.read_text(encoding="utf-8"))
        if ds.get("n") == len(feats):
            drive_2005 = ds.get("drive_mi_2005")
            drive_2025 = ds.get("drive_mi_2025")
            drive_delta = ds.get("delta_mi")
            print(f"[export] using drive-distance sidecar ({drive_src.name})")
        else:
            print(f"[export] WARN drive sidecar n={ds.get('n')} ≠ features {len(feats)}; ignoring")
    else:
        print("[export] no buildings_drive_distances.json - falling back to crow-flies")

    lons: list[float] = []
    lats: list[float] = []
    masks: list[int] = []
    rural: list[int] = []
    d2005: list[float | None] = []
    d2025: list[float | None] = []
    deltas: list[float | None] = []
    counts = {y: 0 for y in YEARS}
    total = 0
    for orig_i, f in enumerate(feats):
        p = f.get("properties", {}) or {}
        lon = p.get("lon")
        lat = p.get("lat")
        if lon is None or lat is None:
            continue
        m = 0
        for i, y in enumerate(YEARS):
            if p.get(f"low_access_{y}"):
                m |= 1 << i
                counts[y] += 1
        if drive_2005 is not None and drive_2025 is not None:
            d05 = drive_2005[orig_i]
            d25 = drive_2025[orig_i]
            dd = drive_delta[orig_i] if drive_delta is not None else None
        else:
            d05 = p.get("dist_mi_2005")
            d25 = p.get("dist_mi_2025")
            dd = None if (d05 is None or d25 is None) else round(float(d25) - float(d05), 2)
        if d05 is None or d25 is None:
            continue
        d05 = round(float(d05), 2)
        d25 = round(float(d25), 2)
        if dd is None:
            dd = round(d25 - d05, 2)
        else:
            dd = round(float(dd), 2)
        lons.append(round(float(lon), 5))
        lats.append(round(float(lat), 5))
        masks.append(m)
        rural.append(1 if p.get("rural") else 0)
        d2005.append(d05)
        d2025.append(d25)
        deltas.append(dd)
        total += 1

    finite_deltas = [d for d in deltas if d is not None]
    n_worse = sum(1 for d in finite_deltas if d >= 0.5)
    n_better = sum(1 for d in finite_deltas if d <= -0.5)
    n_flat = len(finite_deltas) - n_worse - n_better
    sd = sorted(finite_deltas)
    nd = len(sd)
    median = sd[nd // 2] if nd else 0.0
    p90 = sd[int(nd * 0.9)] if nd else 0.0
    p10 = sd[int(nd * 0.1)] if nd else 0.0
    worse_sorted = sorted(d for d in finite_deltas if d >= 0.5)
    better_sorted = sorted(d for d in finite_deltas if d <= -0.5)
    median_lost = worse_sorted[len(worse_sorted) // 2] if worse_sorted else 0.0
    median_gained = better_sorted[len(better_sorted) // 2] if better_sorted else 0.0
    delta_stats = {
        "n_total": total,
        "n_worse_half_mi": n_worse,
        "n_better_half_mi": n_better,
        "n_flat": n_flat,
        "median_delta_mi": median,
        "p10_delta_mi": p10,
        "p90_delta_mi": p90,
        "median_lost_mi": median_lost,
        "median_gained_mi": median_gained,
        "distance_kind": "drive" if drive_2005 is not None else "crow_flies",
    }

    payload = {
        "years": YEARS,
        "lons": lons,
        "lats": lats,
        "masks": masks,
        "rural": rural,
        "d2005": d2005,
        "d2025": d2025,
        "delta": deltas,
        "total": total,
        "low_access_by_year": counts,
        "delta_stats": delta_stats,
    }
    out = WEB_DATA / "buildings_residential.json"
    text = json.dumps(payload, separators=(",", ":"))
    out.write_text(text, encoding="utf-8")
    js_out = WEB_DATA / "buildings_residential.js"
    js_out.write_text(
        "window.__WV_BUILDINGS_RESIDENTIAL__ = " + text + ";\n",
        encoding="utf-8",
    )
    size_mb = out.stat().st_size / 1_048_576
    print(f"[export] wrote {out} ({size_mb:.2f} MB, {total:,} buildings)")
    return {
        "years": YEARS,
        "total": total,
        "low_access_by_year": counts,
        "delta_stats": delta_stats,
        "file": "buildings_residential.json",
    }


def _hillshade_meta() -> dict | None:
    meta_path = PROCESSED / "hillshade.json"
    png_path = PROCESSED / "hillshade.png"
    if not (meta_path.exists() and png_path.exists()):
        print("[export] skip missing hillshade.png/json (run pipeline.hillshade)")
        return None
    shutil.copy2(png_path, WEB_DATA / "hillshade.png")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def main() -> None:
    bundle = {
        "counties": _gj(PROCESSED / "southern_wv_counties.geojson"),
        "roads": _gj(PROCESSED / "roads.geojson", simplify=False),
        "grocery_current": _gj(PROCESSED / "grocery_current.geojson", simplify=False),
        "grocers_by_year": _gj_raw(PROCESSED / "grocers_by_year.geojson"),
        "dollar_stores": _gj(PROCESSED / "dollar_stores.geojson", simplify=False),
        "isochrones": _gj(PROCESSED / "isochrones.geojson"),
        "food_desert_30min": _gj(PROCESSED / "food_desert_30min.geojson"),
        "food_deserts": _gj_raw(PROCESSED / "food_deserts.geojson"),
        "coal_decline": _gj(PROCESSED / "coal_decline.geojson"),
        "hrsa_shortage": _gj(PROCESSED / "hrsa_shortage.geojson"),
        "intervention_sites": _gj(PROCESSED / "intervention_sites.geojson", simplify=False),
        "population": _csv(PROCESSED / "population_timeseries.csv"),
        "coal_employment": _csv(PROCESSED / "coal_employment.csv"),
        "snap_participation": _gj(PROCESSED / "snap_participation.geojson"),
        "buildings_residential_summary": _buildings_compact(),
        "hillshade": _hillshade_meta(),
    }

    out = WEB_DATA / "web_bundle.json"
    payload = json.dumps(bundle, separators=(",", ":"))
    out.write_text(payload, encoding="utf-8")
    size_mb = out.stat().st_size / 1_048_576
    print(f"[export] wrote {out} ({size_mb:.2f} MB)")

    js_out = WEB_DATA / "web_bundle.js"
    js_out.write_text(
        "window.__WV_FOOD_DESERT_BUNDLE__ = " + payload + ";\n",
        encoding="utf-8",
    )
    print(f"[export] wrote {js_out}")


if __name__ == "__main__":
    main()
