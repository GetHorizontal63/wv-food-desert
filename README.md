# Starving Out the Workers: Food Desertification of the Southern WV Coal Fields

An independent data journalism investigation into the collapse of food retail infrastructure across nineteen southern West Virginia counties between 2005 and 2025. The project maps 74 supermarket closures, computes road-network driving distances to the nearest full-service grocer for roughly 382,000 residential structures, polygonizes federal food desert boundaries for 2005 and 2025, and overlays SNAP participation rates to document the paradox at the center of the story: the places with the most households on food assistance are the places with the fewest stores authorized to accept it.

Live site: [wv-food-desert.github.io](https://github.com/GetHorizontal63/wv-food-desert)
Technical walkthrough: [docs/technical_walkthrough.html](docs/technical_walkthrough.html)
Source: [github.com/GetHorizontal63/wv-food-desert](https://github.com/GetHorizontal63/wv-food-desert)

---

## Project Overview

The collapse of coal extraction in southern West Virginia did not produce a managed transition but a structural void. This project documents that collapse using five point-in-time snapshots of USDA-FNS SNAP retailer authorization data (2005, 2010, 2015, 2020, 2025), road-network drive-distance computation via multi-source Dijkstra on the OSM drive graph, and food desert polygonization using FNS dual thresholds applied to actual road distances rather than the straight-line approximations used by the USDA Food Access Research Atlas.

The study area is a selection of 19 counties across southern West Virginia,from Kanawha and Putnam in the northwest to McDowell and Mercer in the south.

---

## Data Sources

| Source | Used For | Access |
|---|---|---|
| USDA-FNS Historical SNAP Retailer Locator (2005-2025) | Retailer snapshots, store closures, replacement events | Manual download |
| US Census TIGER/Line 2020 county boundaries | Study area definition, clip polygon | Public, no key required |
| OpenStreetMap via Overpass API | Road network, drive graph, current grocery points | Public, no key required |
| Microsoft USBuildingFootprints (West Virginia) | Residential building centroids | Public, no key required |
| Mapzen/Nextzen Terrain Tiles via AWS Open Data | Hillshade relief backdrop | Public, no key required |
| US Census ACS 5-year 2018-2022, Table B22003 | SNAP household participation by tract | Public, no key required |
| MSHA Mine Safety open datasets | Coal employment time-series | Public, no key required |
| US Census TIGER/Line 2022 tract boundaries | SNAP choropleth polygons | Public, no key required |

---

## Outputs

### Processed data (`data/processed/`)

| File | Description |
|---|---|
| `southern_wv_counties.geojson` | 19-county study area boundary |
| `grocers_by_year.geojson` | SNAP retailer point features at five snapshot years |
| `buildings_residential.geojson` | 382,000 residential building centroids with access flags |
| `buildings_drive_distances.json` | Parallel arrays of drive distances in 2005 and 2025, and per-home delta |
| `food_deserts.geojson` | FNS desert polygons for 2005, 2025, and persistent coverage |
| `snap_participation.geojson` | ACS SNAP participation rate by Census tract |
| `coal_decline.geojson` | MSHA peak and recent coal employment by county |
| `roads.geojson` | OSM road network for visual rendering |
| `hillshade.png` | Colored relief PNG clipped to study area |
| `hillshade.json` | Bounds metadata for Leaflet imageOverlay |

### Web outputs (`web/data/`)

| File | Description |
|---|---|
| `web_bundle.json` | All polygon and point layers bundled for the frontend |
| `web_bundle.js` | JS shim for file:// access without a local server |
| `buildings_residential.js` | Compact columnar buildings payload (lons, lats, deltas) |
| `hillshade.png` | Copied from processed for frontend delivery |

---

## Frontend

The site is static HTML with no build step. Open `web/index.html` directly or serve from any static host. Map state is driven by an IntersectionObserver watching scrollytelling step elements. The Leaflet map is a non-interactive fixed backdrop; all controls are disabled.

---

## License

Code: MIT. Data: under source licenses. See individual source links above.

Built with Python, GeoPandas, osmnx, Valhalla, Leaflet, D3.