"""Generate a color-shaded relief PNG for the southern WV study area.

Source DEM: AWS Open Data Mapzen / Nextzen Terrain Tiles
  https://s3.amazonaws.com/elevation-tiles-prod/geotiff/{z}/{x}/{y}.tif
Each tile is a 512x512 float32 GeoTIFF in Web Mercator with elevation in
meters. Free, public, no authentication. Mosaic at z=9 gives ~120 m
resolution at WV latitude - plenty for a relief backdrop.

Pipeline:
  1. Download all z=9 terrarium tiles intersecting the study-area bounds.
  2. Mosaic in EPSG:3857 (native tile CRS).
  3. Reproject to EPSG:4326 so Leaflet imageOverlay aligns by lat/lon.
  4. Hillshade (azimuth 315°, altitude 45°).
  5. Hypsometric colormap: dark green valleys → tan → orange ridges → cream peaks.
  6. Multiply color by hillshade for the 3-D effect.
  7. Alpha-mask anything outside the unioned study-area polygon → 0.
  8. Save PNG + JSON bounds metadata for the frontend.

Outputs:
  data/processed/hillshade.png
  data/processed/hillshade.json   ({bounds:[[s,w],[n,e]], ...})
"""
from __future__ import annotations

import json
import math
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
import requests

import geopandas as gpd
from shapely.ops import unary_union

from .config import PROCESSED, RAW

ZOOM = 9
TILE_BASE = "https://s3.amazonaws.com/elevation-tiles-prod/geotiff/{z}/{x}/{y}.tif"
TILE_CACHE = RAW / "terrain_tiles"
OUT_PNG = PROCESSED / "hillshade.png"
OUT_META = PROCESSED / "hillshade.json"


def _lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2.0 ** z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _fetch_tile(z: int, x: int, y: int) -> Path | None:
    TILE_CACHE.mkdir(parents=True, exist_ok=True)
    dest = TILE_CACHE / f"{z}_{x}_{y}.tif"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = TILE_BASE.format(z=z, x=x, y=y)
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[hillshade] tile {z}/{x}/{y} failed: {e}")
        return None
    dest.write_bytes(r.content)
    return dest


def _hillshade(arr: np.ndarray, azimuth_deg: float = 315.0, altitude_deg: float = 45.0,
               cellsize: float = 120.0) -> np.ndarray:
    az = np.deg2rad(360.0 - azimuth_deg + 90.0)
    alt = np.deg2rad(altitude_deg)
    x, y = np.gradient(arr, cellsize)
    slope = np.arctan(np.hypot(x, y))
    aspect = np.arctan2(-x, y)
    shaded = (np.sin(alt) * np.cos(slope) +
              np.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    return np.clip(shaded, 0, 1)


def _hypsometric(elev: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Terrain-ish colormap tuned for a dark UI: dark green valleys -> orange ridges.
    Stops match the Wood County mesh project exactly."""
    if valid.sum() == 0:
        return np.zeros(elev.shape + (3,), dtype=np.float32)
    lo = float(np.nanpercentile(elev[valid], 2))
    hi = float(np.nanpercentile(elev[valid], 98))
    t = np.clip((elev - lo) / max(hi - lo, 1e-6), 0, 1)
    stops = np.array([
        [20,  30,  50],
        [30,  60,  50],
        [70,  90,  55],
        [140, 110, 65],
        [200, 120, 55],
        [245, 200, 120],
    ], dtype=np.float32)
    pos = np.array([0.0, 0.20, 0.45, 0.65, 0.82, 1.0])
    r = np.interp(t, pos, stops[:, 0])
    g = np.interp(t, pos, stops[:, 1])
    b = np.interp(t, pos, stops[:, 2])
    return np.stack([r, g, b], axis=-1) / 255.0


def main() -> None:
    counties_path = PROCESSED / "southern_wv_counties.geojson"
    if not counties_path.exists():
        print(f"[hillshade] missing {counties_path.name} - run pipeline.acquire first")
        return
    counties = gpd.read_file(counties_path).to_crs("EPSG:4326")
    study_poly = unary_union(counties.geometry.values)
    minx, miny, maxx, maxy = study_poly.bounds
    halo = 0.05
    minx -= halo; miny -= halo; maxx += halo; maxy += halo

    x0, y1 = _lonlat_to_tile(minx, miny, ZOOM)
    x1, y0 = _lonlat_to_tile(maxx, maxy, ZOOM)
    tiles_xy = [(x, y) for x in range(min(x0, x1), max(x0, x1) + 1)
                for y in range(min(y0, y1), max(y0, y1) + 1)]
    print(f"[hillshade] need {len(tiles_xy)} terrarium tiles at z={ZOOM}")

    paths: list[Path] = []
    for x, y in tiles_xy:
        p = _fetch_tile(ZOOM, x, y)
        if p:
            paths.append(p)
    if not paths:
        print("[hillshade] no tiles downloaded - aborting")
        return

    srcs = [rasterio.open(p) for p in paths]
    mosaic, mosaic_transform = merge(srcs)
    src_crs = srcs[0].crs
    src_dtype = mosaic.dtype
    src_height, src_width = mosaic.shape[1], mosaic.shape[2]
    for s in srcs:
        s.close()

    dst_crs = "EPSG:4326"
    src_left, src_bottom = mosaic_transform * (0, src_height)
    src_right, src_top = mosaic_transform * (src_width, 0)
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs, dst_crs, src_width, src_height,
        left=src_left, bottom=src_bottom, right=src_right, top=src_top,
    )
    dem = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
    reproject(
        source=mosaic[0],
        destination=dem,
        src_transform=mosaic_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.bilinear,
        src_nodata=-32768,
        dst_nodata=np.nan,
    )

    west = dst_transform.c
    north = dst_transform.f
    px = dst_transform.a
    py = dst_transform.e
    col0 = max(0, int((minx - west) / px))
    col1 = min(dst_width, int((maxx - west) / px))
    row0 = max(0, int((maxy - north) / py))
    row1 = min(dst_height, int((miny - north) / py))
    dem = dem[row0:row1, col0:col1]
    crop_west = west + col0 * px
    crop_north = north + row0 * py
    crop_height, crop_width = dem.shape
    crop_transform = from_bounds(
        crop_west, crop_north + crop_height * py,
        crop_west + crop_width * px, crop_north,
        crop_width, crop_height,
    )

    inside = geometry_mask(
        [study_poly.__geo_interface__],
        out_shape=dem.shape,
        transform=crop_transform,
        invert=True,
    )

    mid_lat = (miny + maxy) / 2.0
    cellsize_m = abs(px) * 111_320.0 * math.cos(math.radians(mid_lat))
    valid = ~np.isnan(dem) & inside
    filled = np.where(np.isnan(dem), float(np.nanmedian(dem)), dem)
    shade = _hillshade(filled, cellsize=cellsize_m)
    color = _hypsometric(filled, valid)
    shaded_rgb = color * (0.35 + 0.65 * shade[..., None])
    shaded_rgb = np.clip(shaded_rgb, 0, 1)

    alpha = inside.astype(np.float32)
    rgba = np.concatenate([shaded_rgb, alpha[..., None]], axis=-1)
    rgba8 = (np.clip(rgba, 0, 1) * 255).astype(np.uint8)

    from PIL import Image
    Image.fromarray(rgba8, mode="RGBA").save(OUT_PNG, optimize=True)

    south = crop_north + crop_height * py
    east = crop_west + crop_width * px
    meta = {
        "bounds": [[south, crop_west], [crop_north, east]],
        "width": int(crop_width),
        "height": int(crop_height),
        "cellsize_m": round(float(cellsize_m), 2),
        "source": "Mapzen / Nextzen Terrain Tiles via AWS Open Data",
    }
    OUT_META.write_text(json.dumps(meta, indent=2))
    print(f"[hillshade] wrote {OUT_PNG.name} ({crop_width}×{crop_height}) + {OUT_META.name}")


if __name__ == "__main__":
    main()
