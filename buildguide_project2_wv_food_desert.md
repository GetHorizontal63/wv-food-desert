# BUILD GUIDE - Project 2
# Food Desertification of the Southern WV Coal Fields

**Status:** Standalone scrollytelling web project  
**Repo:** `github.com/GetHorizontal63/wv-food-desert`  
**Stack:** Python pipeline · GeoPandas · Valhalla · Leaflet · D3 · HTML/CSS/JS  
**Style:** Orange/cream design system (see style guide)  
**Relationship to Project 3:** Self-contained. Referenced and linked from the national atlas but fully independent.

---

## 1. Project Scope

### Geography
All WV counties at the latitude of Kanawha County (Charleston) or south. This includes:

**Kanawha, Boone, Lincoln, Logan, Mingo, McDowell, Wyoming, Mercer, Summers, Monroe, Greenbrier, Pocahontas, Nicholas, Webster, Braxton, Clay, Roane** (verify southern boundary against TIGER county centroids - some edge counties may require judgment call on inclusion).

### Core Argument
The collapse of coal extraction employment in southern WV did not produce a managed economic transition. It produced a structural void. As population fell, retail food infrastructure collapsed faster than population decline alone would predict - a non-linear feedback loop where store closures reduce tax base, which reduces road maintenance and school quality, which accelerates out-migration, which closes more stores. The result is not poverty. It is a food system that has ceased to exist.

### Narrative Sections (10 scrollytelling steps)

| # | Title | Map State |
|---|-------|-----------|
| 1 | The Region | County boundary layer, labeled |
| 2 | Who Left | Population loss choropleth 1950–2020 |
| 3 | The Extraction Economy | Coal employment peak/bust timeline per county |
| 4 | When the Stores Closed | Historical grocery retailer point layer, animated by decade |
| 5 | What Replaced Them | Dollar store density overlay |
| 6 | Drive Time Today | Valhalla isochrones to nearest full-service grocery |
| 7 | The SNAP Paradox | SNAP participation rate vs. authorized SNAP retailer density |
| 8 | McDowell County: Anatomy of a Desert | Deep dive single-county inset |
| 9 | The Compounding Crisis | Food desert + health shortage area overlap |
| 10 | What It Would Take | Modeled intervention - optimal new store placement |

---

## 2. Repository Structure

```
wv-food-desert/
├── pipeline/
│   ├── acquire.py          # Download all raw data
│   ├── population.py       # Census decennial 1950–2020
│   ├── coal.py             # EIA coal employment by county
│   ├── retail.py           # USDA SNAP retailer + InfoUSA processing
│   ├── isochrone.py        # Valhalla drive-time isochrone generation
│   ├── dollar_store.py     # Dollar store location processing
│   ├── snap.py             # SNAP participation data join
│   ├── health.py           # HRSA shortage area overlay
│   ├── intervention.py     # Greedy placement optimization
│   └── export.py           # Bundle to web_bundle.json
├── data/
│   ├── raw/                # Downloaded source files (gitignored)
│   └── processed/          # Pipeline outputs (gitignored except summary JSONs)
├── web/
│   ├── index.html          # Main scrollytelling page
│   ├── style.css           # Orange/cream design system
│   └── main.js             # Leaflet + D3 + IntersectionObserver
├── docs/
│   └── technical_walkthrough.html
└── README.md
```

---

## 3. Data Sources

### 3a. Geography
| Dataset | Source | Format | Notes |
|---------|--------|--------|-------|
| County boundaries | US Census TIGER/Line | Shapefile / GeoJSON | Use 2020 vintage |
| WV state boundary | TIGER | Shapefile | For clipping |
| Roads (primary/secondary) | OpenStreetMap via osmnx | GeoJSON | Filter highway classes |

```python
# acquire.py - county boundaries
import geopandas as gpd
counties = gpd.read_file(
    "https://www2.census.gov/geo/tiger/TIGER2020/COUNTY/tl_2020_us_county.zip"
)
wv = counties[counties["STATEFP"] == "54"]
# Filter southern counties by centroid latitude
wv_proj = wv.to_crs("EPSG:32617")
wv["centroid_lat"] = wv.to_crs("EPSG:4326").geometry.centroid.y
southern_wv = wv[wv["centroid_lat"] <= wv[wv["NAME"] == "Kanawha"]["centroid_lat"].values[0]]
southern_wv.to_file("data/processed/southern_wv_counties.geojson", driver="GeoJSON")
```

### 3b. Population (1950–2020)
| Dataset | Source | Notes |
|---------|--------|-------|
| Decennial census county population | NHGIS (nhgis.org) | Free account required. Download tables: NT001 for each decade 1950–2020 |
| Alternative: Census API | `api.census.gov` | Only goes back to 1990 reliably |

NHGIS is the correct source for pre-1990 data. Download the crosswalk files too - county FIPS codes changed in WV between 1950 and 2020 (none in southern WV, but verify).

```python
# population.py
import pandas as pd

decades = [1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]
# After downloading NHGIS CSV extracts:
dfs = []
for yr in decades:
    df = pd.read_csv(f"data/raw/nhgis_pop_{yr}.csv")
    df = df[df["STATEA"] == "54"]  # WV FIPS
    df["year"] = yr
    df["pop"] = df["population_column_name"]  # varies by extract - check codebook
    dfs.append(df[["COUNTYA", "year", "pop"]])

pop = pd.concat(dfs)
pop["pct_change_from_1950"] = pop.groupby("COUNTYA")["pop"].transform(
    lambda x: (x - x.iloc[0]) / x.iloc[0] * 100
)
pop.to_csv("data/processed/population_timeseries.csv", index=False)
```

### 3c. Coal Employment
| Dataset | Source | Notes |
|---------|--------|-------|
| Coal production by county | EIA Form EIA-7A | Available 1983–present. Prior years use MSHA data |
| MSHA mine employment | MSHA Data Files (arlweb.msha.gov) | Historical employment by mine, with county codes |

```python
# coal.py
import pandas as pd

# MSHA employment data - download from:
# https://arlweb.msha.gov/OpenGovernmentData/OGIMSHA.asp
# File: MinesProdQuarterly.zip
msha = pd.read_csv("data/raw/msha_employment.csv", low_memory=False)
msha_wv = msha[msha["STATE"] == "WV"]
coal_by_county_year = (
    msha_wv[msha_wv["COAL_METAL_IND"] == "C"]
    .groupby(["FIPS_CNTY", "YEAR"])["EMPLOYEE_CNT"]
    .sum()
    .reset_index()
)
coal_by_county_year.to_csv("data/processed/coal_employment.csv", index=False)
```

### 3d. Grocery Retail - Current
| Dataset | Source | Notes |
|---------|--------|-------|
| USDA SNAP authorized retailers | USDA FNS | Updated monthly. Download from `fns.usda.gov/snap/retailer-locator` |
| USDA Food Access Research Atlas | USDA ERS | Census-tract level low-access flags, vehicle access, SNAP |

```python
# retail.py - current SNAP retailer locations
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

snap = pd.read_csv("data/raw/snap_retailer_locator.csv")
snap_wv = snap[snap["State"] == "WV"]

# Filter to food retailers (not just any SNAP-authorized store)
# Store types: "Supermarket", "Grocery Store", "Convenience Store", "Specialty"
grocery_types = ["Supermarket", "Grocery Store", "Combination Grocery/Other"]
full_service = snap_wv[snap_wv["Store Type"].isin(grocery_types)]

geometry = [Point(xy) for xy in zip(full_service["Longitude"], full_service["Latitude"])]
gdf = gpd.GeoDataFrame(full_service, geometry=geometry, crs="EPSG:4326")

# Clip to southern WV counties
counties = gpd.read_file("data/processed/southern_wv_counties.geojson")
gdf_clipped = gpd.sjoin(gdf, counties[["geometry", "NAME"]], how="inner", predicate="within")
gdf_clipped.to_file("data/processed/grocery_current.geojson", driver="GeoJSON")
```

### 3e. Grocery Retail - Historical (Store Closures)
This is the hardest data problem in the project. Options in order of quality:

**Option 1 - InfoUSA / Data Axle historical business database**  
Commercial. University library access may provide this. Provides point locations of businesses by SIC code (5411 = Grocery Stores) with establishment/closure year flags. This is the gold standard for this analysis.

**Option 2 - Reference USA (same underlying data, library access)**  
Same as InfoUSA via public library database access. WV public library system may provide this - check `wvlibrary.org`.

**Option 3 - USDA SNAP retailer archive**  
USDA publishes monthly snapshots. The Wayback Machine has many of these going back to ~2008. Build a scraper against archive.org to reconstruct a time series of SNAP retailer authorizations/de-authorizations. Not perfect - stores can lose SNAP authorization without closing - but usable as a signal.

**Option 4 - OSM historical data via ohsome API**  
`ohsome.org` provides time-travel queries on OpenStreetMap history. Query `shop=supermarket` and `shop=grocery` within the study area with a time series. Underrepresents rural stores that were never mapped, but captures closures that were mapped.

Use Options 3 and 4 together as a cross-validation approach if InfoUSA is unavailable.

### 3f. Dollar Store Locations
| Dataset | Source | Notes |
|---------|--------|-------|
| Dollar General store locations | SNAP retailer list (authorized for SNAP) + web scrape | DG is the largest SNAP retailer in rural America by store count |
| Family Dollar / Dollar Tree | Same approach | |

```python
# dollar_store.py
snap = pd.read_csv("data/raw/snap_retailer_locator.csv")
snap_wv = snap[snap["State"] == "WV"]

dollar_stores = snap_wv[snap_wv["Store Name"].str.contains(
    "DOLLAR GENERAL|FAMILY DOLLAR|DOLLAR TREE|DOLLAR EXPRESS",
    case=False, na=False
)]
# These are SNAP-authorized - they sell food but are not full-service groceries
```

### 3g. Drive-Time Isochrones (Valhalla)
Valhalla is a self-hostable open-source routing engine. Do not use Google Maps API - rate limits and cost make it unworkable for county-scale isochrone generation.

```bash
# Install Valhalla via Docker
docker run -dt --name valhalla_wv \
  -p 8002:8002 \
  -v $PWD/valhalla_tiles:/custom_files \
  ghcr.io/gis-ops/docker-valhalla/valhalla:latest

# Download WV OSM extract
wget -O data/raw/west-virginia-latest.osm.pbf \
  https://download.geofabrik.de/north-america/us/west-virginia-latest.osm.pbf

# Build tiles (run inside container or via docker exec)
valhalla_build_config --mjolnir-tile-dir /custom_files/valhalla_tiles \
  --mjolnir-timezone /custom_files/timezones.sqlite \
  --mjolnir-admin /custom_files/admins.sqlite > /custom_files/valhalla.json
valhalla_build_tiles -c /custom_files/valhalla.json data/raw/west-virginia-latest.osm.pbf
```

```python
# isochrone.py
import requests
import geopandas as gpd
from shapely.geometry import shape
import json

VALHALLA_URL = "http://localhost:8002/isochrone"

def get_isochrone(lon, lat, minutes=30):
    payload = {
        "locations": [{"lon": lon, "lat": lat}],
        "costing": "auto",
        "contours": [{"time": minutes}],
        "polygons": True
    }
    r = requests.post(VALHALLA_URL, json=payload)
    r.raise_for_status()
    return r.json()

# Generate isochrone for each full-service grocery store
groceries = gpd.read_file("data/processed/grocery_current.geojson")
isochrones = []
for _, row in groceries.iterrows():
    iso = get_isochrone(row.geometry.x, row.geometry.y, minutes=30)
    for feat in iso["features"]:
        feat["properties"]["store_name"] = row["Store Name"]
        isochrones.append(feat)

iso_gdf = gpd.GeoDataFrame.from_features(isochrones, crs="EPSG:4326")

# Dissolve all 30-min isochrones into single coverage polygon
covered = iso_gdf.dissolve()

# Invert: find county area NOT within 30 minutes of any grocery
counties = gpd.read_file("data/processed/southern_wv_counties.geojson")
county_union = counties.dissolve()
desert_area = county_union.difference(covered)

desert_gdf = gpd.GeoDataFrame(geometry=[desert_area.geometry.values[0]], crs="EPSG:4326")
desert_gdf.to_file("data/processed/food_desert_30min.geojson", driver="GeoJSON")
```

Generate isochrones at 15, 30, and 45 minutes. The desert zone (no grocery within 30 min) is the primary map layer. Render 15-min as "adequate access," 30–45 min as "marginal access," 45+ min as "desert."

### 3h. SNAP Participation Data
| Dataset | Source | Notes |
|---------|--------|-------|
| SNAP participation by county | USDA FNS County-Level SNAP Data | Annual. Download from `fns.usda.gov/pd/supplemental-nutrition-assistance-program-snap` |
| Population denominator | ACS 5-year | For participation rate calculation |

### 3i. Health Shortage Areas
| Dataset | Source | Notes |
|---------|--------|-------|
| HRSA HPSA designations | HRSA Data Warehouse | `data.hrsa.gov` - Primary Care HPSA shapefile |
| Hospital locations | CMS Provider of Services | Filter to WV, cross-reference with Sheps Center closure list |

---

## 4. Pipeline Execution Order

```bash
python -m pipeline.acquire          # Download all raw data
python -m pipeline.population       # Census 1950–2020 time series
python -m pipeline.coal             # MSHA employment time series
python -m pipeline.retail           # SNAP retailer + USDA FARA processing
python -m pipeline.dollar_store     # Dollar store classification
python -m pipeline.isochrone        # Valhalla drive-time generation (slow - ~20 min)
python -m pipeline.snap             # SNAP participation rate joins
python -m pipeline.health           # HRSA shortage area overlay
python -m pipeline.intervention     # Greedy store placement optimization
python -m pipeline.export           # Bundle all layers to web_bundle.json
```

---

## 5. Intervention Analysis (Section 10)

Reuse the greedy set-cover logic from the mesh project, adapted for food access:

- **Universe:** Census block group centroids weighted by population in food desert zone
- **Candidate sites:** Parcels zoned commercial/retail within desert zone (from county GIS or OpenStreetMap `landuse=commercial`)
- **Coverage metric:** Population within 30-minute drive-time of candidate site (Valhalla isochrone)
- **Constraint:** Minimum 5-mile spacing between selected sites (prevent clustering in one town)
- **Output:** Ranked list of 5–10 optimal new store locations with population served, estimated demand, and nearest existing community anchor (school, fire station, library)

```python
# intervention.py - simplified greedy loop
import geopandas as gpd
import numpy as np

desert_pop = gpd.read_file("data/processed/desert_population_blocks.geojson")
candidates = gpd.read_file("data/processed/commercial_parcels_in_desert.geojson")

# Pre-compute: which block groups does each candidate cover within 30 min?
# (Use Valhalla isochrones per candidate, then spatial join to block groups)
# This produces a boolean matrix: candidates x block_groups

covered = np.zeros(len(desert_pop), dtype=bool)
selected = []

for round_n in range(10):
    best_idx = None
    best_gain = 0
    for i, cand in candidates.iterrows():
        if i in selected:
            continue
        # Check spacing constraint
        if selected:
            sel_geom = candidates.loc[selected].to_crs("EPSG:32617")
            cand_geom = candidates.loc[[i]].to_crs("EPSG:32617")
            min_dist = sel_geom.distance(cand_geom.iloc[0].geometry).min()
            if min_dist < 8046:  # 5 miles in meters
                continue
        gain = (~covered & coverage_matrix[i]).sum()
        if gain > best_gain:
            best_gain = gain
            best_idx = i
    if best_idx is None:
        break
    selected.append(best_idx)
    covered |= coverage_matrix[best_idx]

result = candidates.loc[selected].copy()
result["pop_served"] = [coverage_matrix[i].sum() for i in selected]
result.to_file("data/processed/intervention_sites.geojson", driver="GeoJSON")
```

---

## 6. McDowell County Deep Dive (Section 8)

McDowell County is the anchor case study. It has the highest food insecurity rate in WV and one of the highest in the continental US. Produce dedicated outputs:

- Population: 100,000 (1950) → ~19,000 (2020)
- Grocery stores: documented count by decade (use InfoUSA/SNAP archive)
- Current full-service groceries: likely 1–2 for the entire county
- Drive-time to nearest grocery from each census block group centroid
- Dollar store count vs. grocery store count ratio
- SNAP participation rate
- Median household income vs. WV median vs. national median

These become the county profile card rendered in the scrollytelling sidebar at Section 8.

---

## 7. Frontend Architecture

### HTML Structure (follows mesh project pattern)
```
index.html
├── .hero (full-screen title section)
├── .story (two-column grid)
│   ├── .left (scrollytelling narrative - 10 .step articles)
│   └── .right
│       └── .map-shell (position: fixed)
│           ├── #map (Leaflet)
│           ├── .metrics (live metrics panel)
│           └── .legend
└── docs/technical_walkthrough.html
```

### CSS
Apply the orange/cream design system from the style guide. Key mappings:

| Variable | Usage |
|----------|-------|
| `--orange: #EA6020` | Active step border, section headings, metric values |
| `--cream: #FFF5ED` | Primary text on dark backgrounds |
| `--text-dark: #3A1A08` | Body text inside content panels |
| `--font-h1: Bahnschrift SemiBold` | Hero title, TOC numbers, section labels |
| `--font-h2: Bahnschrift SemiCondensed` | Section headings inside steps |
| `--font-body: Bahnschrift Light` | Step paragraph text |

The body background uses the radial gradient / repeating linear gradient stack from the style guide. The `.step` panels use `background: rgba(20, 20, 20, 0.72)` with `backdrop-filter: blur(2px)` for readability over the map (same approach as mesh project but rendered with cream/orange accents instead of yellow).

### Map Layer Activation by Step

| Step | Layers Added |
|------|-------------|
| 1 | County boundaries, county name labels |
| 2 | Population loss choropleth (D3 color scale: cream → orange-deep) |
| 3 | Coal employment time-series chart in sidebar + county shading by peak employment year |
| 4 | Grocery store points colored by decade of closure (animate via D3 timer) |
| 5 | Dollar store density heatmap overlay |
| 6 | Drive-time isochrone polygons (15/30/45 min bands) |
| 7 | SNAP participation choropleth + retailer density dot overlay |
| 8 | Zoom to McDowell County, inset panel with county stats |
| 9 | HRSA shortage area overlay (hatched pattern on top of desert zones) |
| 10 | Intervention sites (pulsing markers at selected locations) |

### D3 Population Sparklines
Each county gets a sparkline rendered in D3 showing population 1950–2020. These appear on hover over county polygons and in the McDowell deep-dive card.

```javascript
function sparkline(container, data, width = 120, height = 40) {
  const svg = d3.select(container).append("svg")
    .attr("width", width).attr("height", height);
  const x = d3.scaleLinear()
    .domain(d3.extent(data, d => d.year)).range([0, width]);
  const y = d3.scaleLinear()
    .domain([0, d3.max(data, d => d.pop)]).range([height, 0]);
  const line = d3.line().x(d => x(d.year)).y(d => y(d.pop));
  svg.append("path").datum(data)
    .attr("fill", "none")
    .attr("stroke", "#EA6020")
    .attr("stroke-width", 1.5)
    .attr("d", line);
}
```

---

## 8. Metrics Panel

Display these live metrics, updated per step:

| Metric | Source |
|--------|--------|
| Full-service groceries | Count of grocery_current.geojson features |
| Dollar stores | Count of dollar_store features |
| Population in desert | Sum of block group population in food_desert_30min zone |
| SNAP participation rate | County average for study region |
| Counties with zero grocery | Count of counties with no full-service grocery |

---

## 9. Technical Walkthrough Page

`docs/technical_walkthrough.html` - mirrors the mesh project's walkthrough structure. Cover:

1. Data sources and acquisition
2. Population time-series construction (NHGIS crosswalk methodology)
3. SNAP retailer classification (what counts as full-service vs. convenience)
4. Valhalla isochrone generation and parameters
5. Food desert zone construction (inverse of isochrone union)
6. Dollar store substitution analysis
7. Greedy intervention placement algorithm
8. McDowell County case study methodology

---

## 10. Colophon / About

```
Contact:     gabriel.cabrera.business@gmail.com
Source:      github.com/GetHorizontal63/wv-food-desert
Companion:   Rural America: A Domestic Third World Nation (Project 3)
Licensing:   Code MIT · Data under source licenses
Data:        USDA FNS · USDA ERS FARA · NHGIS · MSHA · HRSA · OSM · Census TIGER
Built With:  Python · GeoPandas · Valhalla · Leaflet · D3
```

---

## 11. Deployment Checklist

- [ ] All pipeline stages run clean end-to-end
- [ ] `web_bundle.json` under 15 MB (simplify geometries if needed - use `shapely.simplify` with 0.0005 deg tolerance)
- [ ] Valhalla isochrones validated against known ground truth (drive Welch, WV to nearest Kroger manually)
- [ ] McDowell County stats verified against USDA FARA published figures
- [ ] Dollar store vs. grocery count ratio independently verifiable
- [ ] Mobile responsive (map stacks above narrative on <980px)
- [ ] Technical walkthrough links correctly from colophon
- [ ] GitHub README includes data provenance table and pipeline execution instructions
- [ ] Cross-link to Project 3 live and correct

---

*This project is self-contained. Project 3 references this work in its Appalachian food access chapter but does not depend on this pipeline's outputs.*
