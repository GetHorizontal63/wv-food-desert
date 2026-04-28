"""Build decennial population time-series 1950–2020.

Prefers NHGIS extracts in data/raw/nhgis_pop_<YYYY>.csv when present;
otherwise falls back to the embedded `WV_HISTORICAL_POP` table sourced
from public Census Bureau decennial publications.
"""
from __future__ import annotations
import pandas as pd

from .config import RAW, PROCESSED, WV_FIPS, DECADES
from .historical_population import WV_HISTORICAL_POP


def _from_nhgis() -> pd.DataFrame | None:
    frames = []
    for yr in DECADES:
        path = RAW / f"nhgis_pop_{yr}.csv"
        if not path.exists():
            return None
        df = pd.read_csv(path, dtype={"STATEA": str, "COUNTYA": str})
        df = df[df["STATEA"] == WV_FIPS]
        pop_col = next(
            (c for c in df.columns if c.lower().startswith("pop") or c.startswith("A")),
            None,
        )
        if pop_col is None:
            return None
        df = df[["COUNTYA", pop_col]].rename(columns={pop_col: "pop"})
        df["year"] = yr
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else None


def _from_embedded() -> pd.DataFrame:
    rows = []
    for name, fips, by_year in WV_HISTORICAL_POP:
        for yr, pop in by_year.items():
            rows.append({"COUNTYA": fips, "NAME": name, "year": yr, "pop": pop})
    return pd.DataFrame(rows)


def main() -> None:
    df = _from_nhgis()
    source = "NHGIS"
    if df is None:
        df = _from_embedded()
        source = "embedded Census decennial table"

    df = df.sort_values(["COUNTYA", "year"]).reset_index(drop=True)
    df["pct_change_from_1950"] = df.groupby("COUNTYA")["pop"].transform(
        lambda x: (x - x.iloc[0]) / x.iloc[0] * 100
    )
    out = PROCESSED / "population_timeseries.csv"
    df.to_csv(out, index=False)
    print(f"[population] wrote {out.name} ({len(df)} rows, source: {source})")


if __name__ == "__main__":
    main()
