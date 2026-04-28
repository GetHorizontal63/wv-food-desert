/* =====================================================================
   WV Food Desert - explorer page
   Interactive map: full pan/zoom, year selector, color modes, filters,
   layer toggles, store-type filters, live stats.

   Reuses the data shims loaded by index.html when available
   (`window.__WV_FOOD_DESERT_BUNDLE__`, `window.__WV_BUILDINGS_RESIDENTIAL__`),
   otherwise fetches the JSON bundles directly.
   ===================================================================== */
(function () {
"use strict";

const COLORS = {
  gold:     "#EAAA00",
  goldDeep: "#C99700",
  cream:    "#F4F1E8",
  creamDim: "#BFC8D4",
  desert:   "#7a2a08",
  dollar:   "#9a4ec2",
};
const FS_TYPES = ["supermarket", "large grocery", "medium grocery", "small grocery"];
const YEAR_LIST = [2005, 2010, 2015, 2020, 2025];

const state = {
  year: 2025,
  colorMode: "delta",        
  direction: "all",          
  setting: "all",            
  deltaMin: -20,             
  deltaMax:  20,             
  driveMin:  0,              
  driveMax:  60,             
  storeTypes: new Set(["supermarket", "large", "medium", "small"]),
  layers: {
    buildings:    true,
    grocers:      true,
    supermarkets: false,
    counties:     true,
    roads:        false,
    deserts:      false,
    deserts05:    false,
    snap:         false,
    dollar:       false,
    hillshade:    true,
  },
};

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
async function loadBundle() {
  if (window.__WV_FOOD_DESERT_BUNDLE__) return window.__WV_FOOD_DESERT_BUNDLE__;
  const r = await fetch("data/web_bundle.json");
  return r.json();
}
async function loadBuildings() {
  if (window.__WV_BUILDINGS_RESIDENTIAL__) return window.__WV_BUILDINGS_RESIDENTIAL__;
  const r = await fetch("data/buildings_residential.json");
  return r.json();
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
const BuildingsCanvasLayer = L.Layer.extend({
  initialize(d) {
    this._d = d;
    this._visible = new Uint8Array(d.lons.length); 
    this._colors = new Array(d.lons.length).fill("#ffffff");
  },
  setVisibilityAndColors(vis, cols) { this._visible = vis; this._colors = cols; this._redraw(); },
  onAdd(map) {
    this._map = map;
    const pane = map.getPane("overlayPane");
    const c = (this._canvas = L.DomUtil.create("canvas", "wv-explore-canvas"));
    c.style.position = "absolute";
    c.style.pointerEvents = "none";
    c.style.zIndex = "390";
    pane.appendChild(c);
    map.on("moveend zoomend resize viewreset", this._reset, this);
    this._reset();
  },
  onRemove(map) {
    map.off("moveend zoomend resize viewreset", this._reset, this);
    if (this._canvas && this._canvas.parentNode) this._canvas.parentNode.removeChild(this._canvas);
    this._canvas = null;
  },
  _reset() {
    if (!this._canvas) return;
    const m = this._map;
    const size = m.getSize();
    const tl = m.containerPointToLayerPoint([0, 0]);
    L.DomUtil.setPosition(this._canvas, tl);
    this._canvas.width = size.x;
    this._canvas.height = size.y;
    this._redraw();
  },
  _redraw() {
    if (!this._canvas) return;
    const m = this._map;
    const size = m.getSize();
    const ctx = this._canvas.getContext("2d");
    ctx.clearRect(0, 0, size.x, size.y);
    const { lons, lats } = this._d;
    const vis = this._visible, cs = this._colors;
    const z = m.getZoom();
    const r = z >= 12 ? 1.1 : z >= 10 ? 0.8 : 0.55;
    const d2 = r * 2;
    const bnds = m.getBounds().pad(0.05);
    const minLon = bnds.getWest(), maxLon = bnds.getEast();
    const minLat = bnds.getSouth(), maxLat = bnds.getNorth();
    ctx.globalAlpha = 1;
    for (let i = 0, N = lons.length; i < N; i++) {
      if (!vis[i]) continue;
      const lon = lons[i], lat = lats[i];
      if (lon < minLon || lon > maxLon || lat < minLat || lat > maxLat) continue;
      ctx.fillStyle = cs[i];
      const p = m.latLngToContainerPoint([lat, lon]);
      ctx.fillRect(p.x - r, p.y - r, d2, d2);
    }
  },
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
let map, panes;
const layers = {};
let bundle, buildings;
let buildingsLayer = null;
const grocerMarkersByYear = {};   

(async function init() {
  [bundle, buildings] = await Promise.all([loadBundle(), loadBuildings()]);

  map = L.map("map", {
    minZoom: 7,
    maxZoom: 14,
    zoomDelta: 0.25,
    zoomSnap: 0,
    wheelDebounceTime: 30,
    preferCanvas: true,
    attributionControl: false,
    zoomControl: false,
  }).setView([37.8, -81.4], 8);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

    panes = {};
  panes.relief    = map.createPane("reliefPane");      panes.relief.style.zIndex    = "200";
  panes.snap      = map.createPane("snapPane");        panes.snap.style.zIndex      = "300";
  panes.deserts   = map.createPane("desertsPane");     panes.deserts.style.zIndex   = "320";
  panes.county    = map.createPane("countyPane");      panes.county.style.zIndex    = "350";
  panes.roads     = map.createPane("roadsPane");       panes.roads.style.zIndex     = "360";
  panes.dollar    = map.createPane("dollarPane");      panes.dollar.style.zIndex    = "640";
  panes.grocer    = map.createPane("grocerPane");      panes.grocer.style.zIndex    = "650";

  buildHillshade();
  buildCounties();
  buildRoads();
  buildSnap();
  buildDeserts();
  buildDollar();
  buildGrocers();
  buildBuildings();

    if (layers.counties) {
    map.fitBounds(layers.counties.getBounds(), {
      paddingTopLeft: [40, 60],
      paddingBottomRight: [40, 40],
    });
  }

  wireControls();
  recompute();
})().catch((e) => {
  console.error("[explore] init failed", e);
  document.getElementById("map").innerHTML =
    `<div style="padding:2rem;color:#f88;font-family:monospace">Failed to load data: ${e.message}</div>`;
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function buildHillshade() {
  const h = bundle.hillshade;
  if (!h || !h.bounds) return;
  layers.hillshade = L.imageOverlay("data/hillshade.png", h.bounds, {
    pane: "reliefPane",
    opacity: 0.6,
    interactive: false,
  });
  if (state.layers.hillshade) layers.hillshade.addTo(map);
}

function buildCounties() {
  if (!bundle.counties) return;
  layers.counties = L.geoJSON(bundle.counties, {
    pane: "countyPane",
    interactive: true,
    style: {
      color: COLORS.gold,
      weight: 1.0,
      opacity: 0.7,
      fillColor: COLORS.gold,
      fillOpacity: 0.0,
    },
    onEachFeature: (f, lyr) => {
      const n = f.properties?.NAME || f.properties?.county_name || "";
      lyr.bindTooltip(n, { sticky: true });
    },
  });
  if (state.layers.counties) layers.counties.addTo(map);
}

function buildRoads() {
  if (!bundle.roads) return;
  layers.roads = L.geoJSON(bundle.roads, {
    pane: "roadsPane",
    interactive: false,
    style: { color: COLORS.creamDim, weight: 0.5, opacity: 0.45 },
  });
  if (state.layers.roads) layers.roads.addTo(map);
}

function buildSnap() {
  if (!bundle.snap_participation) return;
  const scale = d3.scaleSequential(d3.interpolatePurples).domain([5, 35]);
  layers.snap = L.geoJSON(bundle.snap_participation, {
    pane: "snapPane",
    renderer: L.canvas({ padding: 0.5 }),
    style: (f) => {
      const v = f.properties?.snap_pct;
      return {
        color: COLORS.cream,
        weight: 0.3,
        opacity: 0.4,
        fillColor: v == null ? "#1a1208" : scale(+v),
        fillOpacity: v == null ? 0 : 0.6,
      };
    },
    onEachFeature: (f, lyr) => {
      const p = f.properties || {};
      const v = p.snap_pct;
      lyr.bindTooltip(
        `<strong>${p.NAMELSAD || p.GEOID}</strong><br/>${v == null ? "no data" : (+v).toFixed(1) + "% on SNAP"}`,
        { sticky: true }
      );
    },
  });
  if (state.layers.snap) layers.snap.addTo(map);
}

function buildDeserts() {
  if (!bundle.food_deserts) return;
  const fc = bundle.food_deserts;
  const fc2025 = { type: "FeatureCollection", features: fc.features.filter((f) => f.properties?.year === 2025) };
  const fc2005 = { type: "FeatureCollection", features: fc.features.filter((f) => f.properties?.year === 2005) };
  if (fc2025.features.length) {
    layers.deserts = L.geoJSON(fc2025, {
      pane: "desertsPane",
      style: { color: "#c44", weight: 0.5, fillColor: "#c44", fillOpacity: 0.32 },
    });
    if (state.layers.deserts) layers.deserts.addTo(map);
  }
  if (fc2005.features.length) {
    layers.deserts05 = L.geoJSON(fc2005, {
      pane: "desertsPane",
      style: { color: "#3FA9F5", weight: 0.5, fillColor: "#3FA9F5", fillOpacity: 0.22 },
    });
    if (state.layers.deserts05) layers.deserts05.addTo(map);
  }
}

function buildDollar() {
  if (!bundle.dollar_stores) return;
  layers.dollar = L.geoJSON(bundle.dollar_stores, {
    pane: "dollarPane",
    pointToLayer: (f, ll) =>
      L.circleMarker(ll, {
        pane: "dollarPane",
        radius: 3,
        color: COLORS.dollar,
        weight: 0.5,
        fillColor: COLORS.dollar,
        fillOpacity: 0.7,
      }),
  });
  if (state.layers.dollar) layers.dollar.addTo(map);
}

function buildGrocers() {
  if (!bundle.grocers_by_year || !bundle.counties) return;

      const polys = [];
  for (const f of bundle.counties.features) {
    const g = f.geometry;
    if (!g) continue;
    const rings = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    for (const poly of rings) {
      const outer = poly[0];
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (const [x, y] of outer) {
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
      polys.push({ poly, bbox: [minX, minY, maxX, maxY] });
    }
  }
  const ringContains = (pt, ring) => {
    let inside = false;
    const x = pt[0], y = pt[1];
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1];
      const xj = ring[j][0], yj = ring[j][1];
      if (((yi > y) !== (yj > y)) && (x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-20) + xi)) inside = !inside;
    }
    return inside;
  };
  const inStudy = (lon, lat) => {
    for (const { poly, bbox } of polys) {
      if (lon < bbox[0] || lon > bbox[2] || lat < bbox[1] || lat > bbox[3]) continue;
      if (ringContains([lon, lat], poly[0])) {
        let inHole = false;
        for (let h = 1; h < poly.length; h++) if (ringContains([lon, lat], poly[h])) { inHole = true; break; }
        if (!inHole) return true;
      }
    }
    return false;
  };

  const radiusFor = (st) => {
    const s = (st || "").toLowerCase();
    if (s.includes("supermarket")) return 7;
    if (s.includes("super store") || s.includes("super "))  return 6;
    if (s.includes("large"))  return 5;
    if (s.includes("medium")) return 4;
    if (s.includes("small"))  return 3.2;
    return 2.6;
  };
  const typeKey = (st) => {
    const s = (st || "").toLowerCase();
    if (s.includes("supermarket") || s.includes("super store")) return "supermarket";
    if (s.includes("large"))  return "large";
    if (s.includes("medium")) return "medium";
    if (s.includes("small"))  return "small";
    return "combination";
  };

  for (const yr of YEAR_LIST) {
    const grp = L.featureGroup();
    const fsGrp = L.featureGroup();
    let n = 0;
    for (const f of bundle.grocers_by_year.features) {
      const p = f.properties || {};
      if (p.snapshot_year !== yr) continue;
      const c = f.geometry?.coordinates;
      if (!c || !inStudy(c[0], c[1])) continue;
      const tk = typeKey(p.store_type);
      const m = L.circleMarker([c[1], c[0]], {
        pane: "grocerPane",
        radius: radiusFor(p.store_type),
        color: "#1a1208",
        weight: 0.8,
        fillColor: "#FDD267",
        fillOpacity: 0.95,
        opacity: 1,
      }).bindTooltip(
        `<strong>${p.name || ""}</strong><br/>${p.store_type || ""}<br/>${p.address || ""}, ${p.city || ""}`,
        { sticky: true }
      );
      m.__typeKey = tk;
      grp.addLayer(m);
      if (tk === "supermarket") {
        const halo = L.circleMarker([c[1], c[0]], {
          pane: "grocerPane",
          radius: radiusFor(p.store_type) + 5,
          color: "#FDD267",
          weight: 1.2,
          fillOpacity: 0,
          opacity: 0.8,
          interactive: false,
        });
        fsGrp.addLayer(halo);
      }
      n++;
    }
    grocerMarkersByYear[yr] = { layer: grp, halo: fsGrp, count: n };
  }
  applyGrocerYear();
}

function buildBuildings() {
  buildingsLayer = new BuildingsCanvasLayer(buildings);
  if (state.layers.buildings) buildingsLayer.addTo(map);
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function recompute() {
  if (!buildingsLayer) return;
  const N = buildings.lons.length;
  const vis = new Uint8Array(N);
  const cols = new Array(N);

    const deltaScale = d3.scaleSequential(d3.interpolateRdYlGn)
    .domain([10, -10]); 
  const distScale = d3.scaleSequential(d3.interpolateYlOrRd).domain([0, 25]); 
  const yIdx = YEAR_LIST.indexOf(state.year);
  const yBit = 1 << (yIdx >= 0 ? yIdx : 4);

  let nShown = 0, nWorse = 0, nBetter = 0;
  const dShown = [];
  const ds = buildings.delta;
  const d05 = buildings.d2005;
  const d25 = buildings.d2025;
  const ms = buildings.masks;
  const ru = buildings.rural;

  for (let i = 0; i < N; i++) {
        if (state.setting === "rural" && !ru[i]) continue;
    if (state.setting === "urban" && ru[i])  continue;

    const dv = ds[i];
    const drive = state.year === 2005 ? d05[i] : d25[i]; 

        if (state.direction === "worse"  && !(dv >= 0.5)) continue;
    if (state.direction === "better" && !(dv <= -0.5)) continue;
    if (state.direction === "flat"   && !(dv > -0.5 && dv < 0.5)) continue;

        if (dv < state.deltaMin || dv > state.deltaMax) continue;

        if (drive < state.driveMin) continue;
    if (state.driveMax < 60 && drive > state.driveMax) continue;

        let col;
    if (state.colorMode === "delta") {
      col = deltaScale(Math.max(-10, Math.min(10, dv)));
    } else if (state.colorMode === "d2005") {
      col = distScale(Math.min(25, d05[i]));
    } else if (state.colorMode === "d2025") {
      col = distScale(Math.min(25, d25[i]));
    } else { 
      const isLow = (ms[i] & yBit) !== 0;
      col = isLow ? "#E03A3A" : "#3FE08A";
    }

    vis[i] = 1;
    cols[i] = col;
    nShown++;
    dShown.push(dv);
    if (dv >= 0.5) nWorse++;
    else if (dv <= -0.5) nBetter++;
  }

  buildingsLayer.setVisibilityAndColors(vis, cols);
  updateStats({ nShown, nTotal: N, nWorse, nBetter, dShown });
  updateLegend(deltaScale, distScale);
}

function updateStats({ nShown, nTotal, nWorse, nBetter, dShown }) {
  const fmt = (n) => n.toLocaleString();
  const pct = (a, b) => b > 0 ? `${((a / b) * 100).toFixed(1)}%` : "—";
  document.getElementById("s-shown").textContent  = fmt(nShown);
  document.getElementById("s-total").textContent  = pct(nShown, nTotal);
  document.getElementById("s-worse").textContent  = `${fmt(nWorse)} (${pct(nWorse, nShown)})`;
  document.getElementById("s-better").textContent = `${fmt(nBetter)} (${pct(nBetter, nShown)})`;
  let med = "—";
  if (dShown.length) {
    dShown.sort((a, b) => a - b);
    med = dShown[Math.floor(dShown.length / 2)].toFixed(2) + " mi";
  }
  document.getElementById("s-median").textContent = med;
  const g = grocerMarkersByYear[state.year];
  document.getElementById("s-grocers").textContent = g ? fmt(g.count) : "—";
  updateAppliedFilters();
}

function updateAppliedFilters() {
  const el = document.getElementById("applied-filters");
  if (!el) return;
  const colorLabels = {
    delta: "Δ 2005→2025",
    d2005: "Drive 2005",
    d2025: "Drive 2025",
    lowAccess: "Low-access (year)",
  };
  const dirLabels = {
    all: "All",
    worse: "Worsened ≥ 0.5 mi",
    better: "Improved ≤ -0.5 mi",
    flat: "Roughly unchanged",
  };
  const setLabels = { all: "All", rural: "Rural", urban: "Urban" };
  const dRange = (state.deltaMin <= -20 && state.deltaMax >= 20)
    ? "any"
    : `${(+state.deltaMin).toFixed(1)} to ${(+state.deltaMax).toFixed(1)} mi`;
  const drRange = (state.driveMin <= 0 && state.driveMax >= 60)
    ? "any"
    : `${(+state.driveMin).toFixed(1)} to ${state.driveMax >= 60 ? "∞" : (+state.driveMax).toFixed(1)} mi`;
  const types = Array.from(state.storeTypes);
  const typesLabel = types.length === 0
    ? "none"
    : (types.length >= 4 ? `${types.length} categories` : types.join(", "));
  const rows = [
    ["Year",   String(state.year)],
    ["Color",  colorLabels[state.colorMode] || state.colorMode],
    ["Direction", dirLabels[state.direction] || state.direction],
    ["Setting",   setLabels[state.setting] || state.setting],
    ["Δ range",   dRange],
    ["Drive range", drRange],
    ["Store types", typesLabel],
  ];
  el.innerHTML = rows
    .map(([k, v]) => `<li><span class="k">${k}:</span><span class="v">${v}</span></li>`)
    .join("");
}

function updateLegend(deltaScale, distScale) {
  const el = document.getElementById("explore-legend");
  if (state.colorMode === "delta") {
    const stops = [];
    for (let i = 0; i <= 20; i++) {
      const v = -10 + i; 
      stops.push(`<stop offset='${(i / 20) * 100}%' stop-color='${deltaScale(v)}'/>`);
    }
    el.innerHTML =
      `<svg width='100%' height='14' viewBox='0 0 100 14' preserveAspectRatio='none'>` +
      `<defs><linearGradient id='lgD' x1='0%' x2='100%'>${stops.join("")}</linearGradient></defs>` +
      `<rect x='0' y='0' width='100' height='14' fill='url(#lgD)'/></svg>` +
      `<div class='legend-axis'><span>−10 mi (better)</span><span>0</span><span>+10 mi (worse)</span></div>`;
  } else if (state.colorMode === "d2005" || state.colorMode === "d2025") {
    const stops = [];
    for (let i = 0; i <= 20; i++) {
      const v = (i / 20) * 25;
      stops.push(`<stop offset='${(i / 20) * 100}%' stop-color='${distScale(v)}'/>`);
    }
    const lbl = state.colorMode === "d2005" ? "2005" : "2025";
    el.innerHTML =
      `<svg width='100%' height='14' viewBox='0 0 100 14' preserveAspectRatio='none'>` +
      `<defs><linearGradient id='lgM' x1='0%' x2='100%'>${stops.join("")}</linearGradient></defs>` +
      `<rect x='0' y='0' width='100' height='14' fill='url(#lgM)'/></svg>` +
      `<div class='legend-axis'><span>0 mi</span><span>${lbl} drive</span><span>≥ 25 mi</span></div>`;
  } else {
    el.innerHTML =
      `<div class='legend-row'><span class='swatch' style='background:#E03A3A'></span> Low-access in ${state.year}</div>` +
      `<div class='legend-row'><span class='swatch' style='background:#3FE08A'></span> Has access in ${state.year}</div>` +
      `<div style='font-size:0.7rem;color:var(--cream-dim);margin-top:0.3rem'>FNS thresholds: ½ mi drive (urban) or 10 mi (rural).</div>`;
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function applyLayer(name, on) {
  state.layers[name] = on;
  const lyr = layers[name];
  if (name === "buildings") {
    if (on && buildingsLayer) buildingsLayer.addTo(map);
    else if (buildingsLayer) buildingsLayer.remove();
    return;
  }
  if (name === "grocers" || name === "supermarkets") {
    applyGrocerYear();
    return;
  }
  if (!lyr) return;
  if (on) lyr.addTo(map);
  else lyr.remove();
}

function applyGrocerYear() {
    for (const yr of YEAR_LIST) {
    const g = grocerMarkersByYear[yr];
    if (!g) continue;
    if (g.layer.__attached) { g.layer.remove(); g.layer.__attached = false; }
    if (g.halo.__attached)  { g.halo.remove();  g.halo.__attached  = false; }
  }
  const g = grocerMarkersByYear[state.year];
  if (!g) return;
  if (state.layers.grocers) {
        g.layer.eachLayer((m) => {
      if (state.storeTypes.has(m.__typeKey)) {
        if (!m.__visible) { m.setStyle({ opacity: 1, fillOpacity: 0.95 }); m.__visible = true; }
      } else {
        if (m.__visible !== false) { m.setStyle({ opacity: 0, fillOpacity: 0 }); m.__visible = false; }
      }
    });
    g.layer.addTo(map); g.layer.__attached = true;
  }
  if (state.layers.supermarkets) {
    g.halo.addTo(map); g.halo.__attached = true;
  }
    document.getElementById("s-grocers").textContent = g.count.toLocaleString();
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function wireControls() {
    document.querySelectorAll('.seg').forEach((seg) => {
    const ctl = seg.getAttribute("data-control");
    seg.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      seg.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      const v = b.getAttribute("data-val");
      if (ctl === "year") {
        state.year = +v;
        applyGrocerYear();
        if (state.colorMode === "lowAccess") recompute();
        else recompute();
      } else if (ctl === "colorMode") {
        state.colorMode = v;
        recompute();
      }
    });
  });

    document.getElementById("ctl-direction").addEventListener("change", (e) => {
    state.direction = e.target.value; recompute();
  });
  document.getElementById("ctl-setting").addEventListener("change", (e) => {
    state.setting = e.target.value; recompute();
  });

    wireDualRange("deltaRange", "ctl-delta-min-num", "ctl-delta-max-num", (lo, hi) => {
    state.deltaMin = lo; state.deltaMax = hi; recompute();
  });
  wireDualRange("driveRange", "ctl-drive-min-num", "ctl-drive-max-num", (lo, hi) => {
    state.driveMin = lo; state.driveMax = hi; recompute();
  });

    const layerKeys = [
    ["lyr-buildings", "buildings"],
    ["lyr-grocers", "grocers"],
    ["lyr-supermarkets", "supermarkets"],
    ["lyr-counties", "counties"],
    ["lyr-roads", "roads"],
    ["lyr-deserts", "deserts"],
    ["lyr-deserts05", "deserts05"],
    ["lyr-snap", "snap"],
    ["lyr-dollar", "dollar"],
    ["lyr-hillshade", "hillshade"],
  ];
  for (const [id, key] of layerKeys) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.addEventListener("change", () => applyLayer(key, el.checked));
  }

    document.querySelectorAll(".storeType").forEach((cb) => {
    cb.addEventListener("change", () => {
      const v = cb.getAttribute("data-val");
      if (cb.checked) state.storeTypes.add(v);
      else state.storeTypes.delete(v);
      applyGrocerYear();
    });
  });

  // Layers dropdown toggle
  const layersBtn  = document.getElementById("map-layers-toggle");
  const layersBody = document.getElementById("map-layers-body");
  if (layersBtn && layersBody) {
    layersBtn.addEventListener("click", () => {
      const open = layersBtn.getAttribute("aria-expanded") === "true";
      layersBtn.setAttribute("aria-expanded", String(!open));
      layersBody.hidden = open;
    });
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function wireDualRange(controlName, minInputId, maxInputId, onChange) {
  const wrap = document.querySelector(`.range-dual[data-control="${controlName}"]`);
  if (!wrap) return;
  const lowR  = wrap.querySelector("input.range-low");
  const highR = wrap.querySelector("input.range-high");
  const fill  = wrap.querySelector(".range-fill");
  const minN  = document.getElementById(minInputId);
  const maxN  = document.getElementById(maxInputId);
  const dMin = +wrap.dataset.min, dMax = +wrap.dataset.max, dStep = +wrap.dataset.step || 1;
  const decimals = (String(dStep).split(".")[1] || "").length;

  function clamp(n) {
    if (Number.isNaN(n)) return dMin;
    return Math.max(dMin, Math.min(dMax, n));
  }
  function paint() {
    const lo = +lowR.value, hi = +highR.value;
    const span = dMax - dMin || 1;
    fill.style.left  = ((lo - dMin) / span * 100) + "%";
    fill.style.right = ((dMax - hi) / span * 100) + "%";
        lowR.style.zIndex  = (lo > dMax - (dMax - dMin) * 0.05) ? 5 : 4;
    highR.style.zIndex = 5;
  }
  function emit() {
    paint();
    onChange(+lowR.value, +highR.value);
  }
  function syncFromSliders() {
    let lo = +lowR.value, hi = +highR.value;
    if (lo > hi) { lo = hi; lowR.value = String(lo); }
    minN.value = lo.toFixed(decimals);
    maxN.value = hi.toFixed(decimals);
    emit();
  }
  function syncFromNumbers() {
    let lo = clamp(+minN.value);
    let hi = clamp(+maxN.value);
    if (lo > hi) [lo, hi] = [hi, lo];
    lowR.value  = String(lo);
    highR.value = String(hi);
    minN.value  = lo.toFixed(decimals);
    maxN.value  = hi.toFixed(decimals);
    emit();
  }
  lowR.addEventListener("input",  syncFromSliders);
  highR.addEventListener("input", syncFromSliders);
  minN.addEventListener("change", syncFromNumbers);
  maxN.addEventListener("change", syncFromNumbers);
  minN.addEventListener("keydown", (e) => { if (e.key === "Enter") syncFromNumbers(); });
  maxN.addEventListener("keydown", (e) => { if (e.key === "Enter") syncFromNumbers(); });
  paint();
}

})();
