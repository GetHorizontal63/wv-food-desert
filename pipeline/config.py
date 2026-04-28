"""Shared paths and constants for the pipeline."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
WEB_DATA = ROOT / "web" / "data"

WV_FIPS = "54"

SOUTHERN_WV_COUNTIES = [
    "Kanawha", "Boone", "Lincoln", "Logan", "Mingo", "McDowell", "Wyoming",
    "Mercer", "Summers", "Monroe", "Greenbrier", "Pocahontas", "Nicholas",
    "Webster", "Braxton", "Clay", "Roane", "Fayette", "Raleigh",
]

DECADES = [1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]

VALHALLA_URL = "http://localhost:8002"

for _p in (RAW, PROCESSED, WEB_DATA):
    _p.mkdir(parents=True, exist_ok=True)
