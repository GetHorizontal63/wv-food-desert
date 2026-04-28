"""Greedy set-cover store placement optimization within the food desert zone."""
from __future__ import annotations
import numpy as np
import geopandas as gpd

from .config import PROCESSED

MIN_SPACING_M = 8046
MAX_SITES = 10


def main() -> None:
    pop_path = PROCESSED / "desert_population_blocks.geojson"
    cand_path = PROCESSED / "commercial_parcels_in_desert.geojson"
    if not (pop_path.exists() and cand_path.exists()):
        print("[intervention] inputs missing - placeholder run")
        return

    desert_pop = gpd.read_file(pop_path)
    candidates = gpd.read_file(cand_path)

    cov_path = PROCESSED / "coverage_matrix.npy"
    if not cov_path.exists():
        print("[intervention] coverage_matrix.npy missing - aborting")
        return
    coverage = np.load(cov_path)

    covered = np.zeros(len(desert_pop), dtype=bool)
    selected: list[int] = []

    cand_proj = candidates.to_crs("EPSG:32617")
    for _ in range(MAX_SITES):
        best, best_gain = None, 0
        for i in range(len(candidates)):
            if i in selected:
                continue
            if selected:
                d = cand_proj.iloc[selected].distance(cand_proj.iloc[i].geometry).min()
                if d < MIN_SPACING_M:
                    continue
            gain = int((~covered & coverage[i]).sum())
            if gain > best_gain:
                best, best_gain = i, gain
        if best is None:
            break
        selected.append(best)
        covered |= coverage[best]

    result = candidates.iloc[selected].copy()
    result["pop_served"] = [int(coverage[i].sum()) for i in selected]
    out = PROCESSED / "intervention_sites.geojson"
    result.to_file(out, driver="GeoJSON")
    print(f"[intervention] wrote {out} ({len(result)} sites)")


if __name__ == "__main__":
    main()
