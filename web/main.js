/* =====================================================================
   WV Food Desert - main.js
   Leaflet acts as a fixed visual backdrop; IntersectionObserver drives
   per-step layer activation. All map interactions are disabled so the
   reader's scroll always belongs to the narrative.
   ===================================================================== */

const BUNDLE_URL = "web/data/web_bundle.json";

const COLORS = {
  orange: "#EAAA00",       
  orangeDeep: "#C99700",   
  cream: "#F4F1E8",
  creamDim: "#BFC8D4",
  desert: "#7a2a08",
  iso15: "#3b8a3a",
  iso30: "#d49d2a",
  iso45: "#c25218",
  dollar: "#9a4ec2",
  shortage: "#c44",
  intervention: "#3fb27f",
};

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
const map = L.map("map", {
  zoomControl: false,
  attributionControl: true,
  preferCanvas: true,
  zoomSnap: 0,
  zoomDelta: 0.25,
  scrollWheelZoom: false,
  doubleClickZoom: false,
  boxZoom: false,
  dragging: false,
  touchZoom: false,
  keyboard: false,
}).setView([37.8, -81.4], 8);

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
document.getElementById("map").style.background = "#0b0807";

map.createPane("reliefPane");
map.getPane("reliefPane").style.zIndex = 200;
map.getPane("reliefPane").style.pointerEvents = "none";
map.getPane("reliefPane").style.transition = "opacity 600ms ease";

map.createPane("roadsPane");
map.getPane("roadsPane").style.zIndex = 350;
map.getPane("roadsPane").style.pointerEvents = "none";
map.getPane("roadsPane").style.transition = "opacity 600ms ease";

map.createPane("grocerPane");
map.getPane("grocerPane").style.zIndex = 650;
map.getPane("grocerPane").classList.add("leaflet-grocer-pane");

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  subdomains: "abcd",
  maxZoom: 19,
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a> · ' +
    'Terrain: Mapzen Terrain Tiles (AWS Open Data)',
}).addTo(map);

const legendEl = document.getElementById("legend");
const areaSquaresEl = document.getElementById("area-squares");
const metricEls = {
  counties: document.getElementById("m-counties"),
  groceries: document.getElementById("m-groceries"),
  dollars: document.getElementById("m-dollars"),
  zero: document.getElementById("m-zero"),
  pop: document.getElementById("m-pop"),
};

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
async function loadBundle() {
  if (window.__WV_FOOD_DESERT_BUNDLE__) {
    return window.__WV_FOOD_DESERT_BUNDLE__;
  }
  try {
    const res = await fetch(BUNDLE_URL, { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("[main] web_bundle not available:", err.message);
    legendEl.innerHTML =
      "<h4>Data pending</h4>" +
      "<div style='color:var(--cream-dim)'>Run the Python pipeline and " +
      "<code>pipeline.export</code> to populate <code>web/data/web_bundle.json</code>.</div>";
    return null;
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
const layers = {};

function fmt(n) {
  if (n == null || isNaN(n)) return "-";
  return d3.format(",")(Math.round(n));
}
function setMetric(key, val) {
  if (metricEls[key]) metricEls[key].textContent = val;
}
function setLegend(html) { legendEl.innerHTML = html; }

// ---------- Area-squares panel (step 6) ----------
let _areaSquaresState = null; 

function _pixelsPerMile() {
  if (!map) return 0;
  const c = map.getCenter();
  const p1 = map.latLngToContainerPoint(c);
    const dLng = 1 / (69.172 * Math.cos((c.lat * Math.PI) / 180));
  const p2 = map.latLngToContainerPoint(L.latLng(c.lat, c.lng + dLng));
  return Math.abs(p2.x - p1.x);
}

function _renderAreaSquares() {
  if (!_areaSquaresState || areaSquaresEl.hidden) return;
  const { disappeared_sq_mi: dis, grown_sq_mi: grown } = _areaSquaresState;
  const ppm = _pixelsPerMile();
    let sGrown = Math.sqrt(grown) * ppm;
  let sDis = Math.sqrt(dis) * ppm;
    const MAX = 220;
  if (sGrown > MAX) {
    const k = MAX / sGrown;
    sGrown *= k; sDis *= k;
  }
    const MIN = 8;
  if (sGrown < MIN) {
    const k = MIN / sGrown;
    sGrown *= k; sDis *= k;
  }
  const stageH = Math.max(sGrown, 24) + 4;
  areaSquaresEl.innerHTML =
    "<h4>Area changed, 2005 → 2025</h4>" +
    `<div class='sq-stage' style='height:${stageH}px'>` +
      `<div class='sq-grown' style='width:${sGrown}px;height:${sGrown}px'></div>` +
      `<div class='sq-disappeared' style='width:${sDis}px;height:${sDis}px'></div>` +
    "</div>" +
    "<div class='sq-rows'>" +
      `<span class='sq-swatch' style='background:#E03A3A'></span>` +
      `<span>Desert grown</span>` +
      `<span class='sq-val'>${fmt(grown)} mi²</span>` +
      `<span class='sq-swatch' style='background:#3FA9F5'></span>` +
      `<span>Desert disappeared</span>` +
      `<span class='sq-val'>${fmt(dis)} mi²</span>` +
    "</div>" +
    "<div class='sq-foot'>Squares drawn to current map scale.</div>";
}

function showAreaSquares(stats) {
  if (!stats || stats.grown_sq_mi == null || stats.disappeared_sq_mi == null) {
    hideAreaSquares();
    return;
  }
  _areaSquaresState = stats;
  areaSquaresEl.hidden = false;
  _renderAreaSquares();
}

function hideAreaSquares() {
  _areaSquaresState = null;
  areaSquaresEl.hidden = true;
  areaSquaresEl.innerHTML = "";
}

map.on("zoomend moveend resize", _renderAreaSquares);

function setTerrainVisible(v) {
            const op = v ? 1.0 : 0.0;
  const r = map.getPane("reliefPane"); if (r) r.style.opacity = String(op);
  const rd = map.getPane("roadsPane"); if (rd) rd.style.opacity = String(op);
}

function setRoadsOpacity(o) {
  const rd = map.getPane("roadsPane");
  if (rd) rd.style.opacity = String(o);
}

function setTerrainOpacity(o) {
          const r = map.getPane("reliefPane");
  if (r) r.style.opacity = String(o);
}

function clearAll(keep) {
  const keepSet = keep instanceof Set ? keep : null;
  if (!keepSet || (!keepSet.has("__terrainDim__"))) {
                setTerrainOpacity(1.0);
    setRoadsOpacity(1.0);
  }
  if (!keepSet || !keepSet.has("areaSquares")) hideAreaSquares();
  if (layers.__grocerYearTimer) {
    clearInterval(layers.__grocerYearTimer);
    layers.__grocerYearTimer = null;
  }
  if (layers.__grocerFlashTO) { clearTimeout(layers.__grocerFlashTO); layers.__grocerFlashTO = null; }
  if (layers.__grocerFadeTO) { clearTimeout(layers.__grocerFadeTO); layers.__grocerFadeTO = null; }
  if (layers.__grocerStageTOs) { layers.__grocerStageTOs.forEach((t) => clearTimeout(t)); layers.__grocerStageTOs = null; }
  if (layers.__buildingsTimer) {
    clearInterval(layers.__buildingsTimer);
    layers.__buildingsTimer = null;
  }
  for (const [k, layer] of Object.entries(layers)) {
        if (k === "boundary" || k === "hillshade" || k === "roads") continue;
    if (k.startsWith("__")) continue;
    if (keepSet && keepSet.has(k)) continue;
    if (map.hasLayer(layer)) map.removeLayer(layer);
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function buildLayers(b) {
  if (!b) return;

      if (b.hillshade && b.hillshade.bounds) {
    layers.hillshade = L.imageOverlay(
      "web/data/hillshade.png",
      b.hillshade.bounds,
      { pane: "reliefPane", opacity: 1.0, interactive: false }
    ).addTo(map);
  }

        if (b.roads) {
    const roadStyle = (f) => {
      const cls = f.properties?.road_class;
      if (cls === "primary")
        return { pane: "roadsPane", color: "#FFFFFF", weight: 1.6, opacity: 0.95 };
      if (cls === "secondary")
        return { pane: "roadsPane", color: "#FFFFFF", weight: 1.0, opacity: 0.75 };
      if (cls === "tertiary")
        return { pane: "roadsPane", color: "#FFFFFF", weight: 0.6, opacity: 0.55 };
      return { pane: "roadsPane", color: "#FFFFFF", weight: 0.4, opacity: 0.4 };
    };
    layers.roads = L.geoJSON(b.roads, { style: roadStyle, interactive: false }).addTo(map);
  }

  if (b.counties) {
    layers.boundary = L.geoJSON(b.counties, {
      style: {
        color: COLORS.cream,
        weight: 0,
        opacity: 0,
        fillColor: COLORS.orange,
        fillOpacity: 0.0,
      },
      interactive: false,
    }).addTo(map);
  }

      if (b.coal_decline) {
    const coalScale = d3.scaleSequential(d3.interpolateReds).domain([0, 100]);
    layers.coalDecline = L.geoJSON(b.coal_decline, {
      style: (f) => {
        const p = f.properties || {};
        const peak = +p.peak_emp || 0;
        const pct = +p.pct_change_from_peak || 0; 
        const drop = peak > 0 ? Math.min(100, Math.abs(pct)) : null;
        return {
          color: COLORS.cream,
          weight: 0.4,
          opacity: 0.4,
          fillColor: drop == null ? "#1a1a1a" : coalScale(drop),
          fillOpacity: drop == null ? 0.25 : 0.7,
        };
      },
      onEachFeature: (f, lyr) => {
        const p = f.properties || {};
        if (+p.peak_emp > 0) {
          lyr.bindTooltip(
            `${p.NAME}: peak ${p.peak_emp} miners (${p.peak_year}) → ${p.recent_emp} (${p.recent_year}) = ${Math.round(p.pct_change_from_peak)}%`,
            { sticky: true }
          );
        }
      },
    });
    layers.__coalScale = coalScale;
  }

        if (b.snap_participation) {
    const snapScale = d3.scaleSequential(d3.interpolatePurples).domain([5, 35]);
                layers.snapPct = L.geoJSON(b.snap_participation, {
      renderer: L.canvas({ padding: 0.5 }),
      style: (f) => {
        const v = f.properties?.snap_pct;
        return {
          color: COLORS.cream,
          weight: 0.4,
          opacity: 0.45,
          fillColor: v == null ? "#1a1208" : snapScale(+v),
          fillOpacity: v == null ? 0.0 : 0.78,
        };
      },
      onEachFeature: (f, lyr) => {
        const p = f.properties || {};
        const v = p.snap_pct;
        const lab = p.NAMELSAD || p.GEOID || "Census tract";
        const pct = v == null ? "no data" : `${(+v).toFixed(1)}%`;
        const hh = p.snap_hh != null && p.total_hh != null
          ? `<br/><span style='opacity:0.75'>${(+p.snap_hh).toLocaleString()} of ${(+p.total_hh).toLocaleString()} households</span>`
          : "";
        lyr.bindTooltip(`<strong>${lab}</strong><br/>${pct} on SNAP${hh}`, { sticky: true });
      },
    });
    layers.__snapScale = snapScale;
  }

            
  if (b.grocery_current) {
    layers.grocery = L.geoJSON(b.grocery_current, {
      pointToLayer: (f, ll) =>
        L.circleMarker(ll, {
          radius: 4,
          color: COLORS.cream,
          weight: 1,
          fillColor: COLORS.orange,
          fillOpacity: 0.9,
        }),
    });
  }

            if (b.grocers_by_year && b.counties) {
        const polys = [];
    for (const f of b.counties.features) {
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
    const _ringContains = (pt, ring) => {
      let inside = false;
      const x = pt[0], y = pt[1];
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const xi = ring[i][0], yi = ring[i][1];
        const xj = ring[j][0], yj = ring[j][1];
        const intersect = ((yi > y) !== (yj > y)) &&
          (x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-20) + xi);
        if (intersect) inside = !inside;
      }
      return inside;
    };
    const inStudy = (lon, lat) => {
      for (const { poly, bbox } of polys) {
        if (lon < bbox[0] || lon > bbox[2] || lat < bbox[1] || lat > bbox[3]) continue;
        if (_ringContains([lon, lat], poly[0])) {
          let inHole = false;
          for (let h = 1; h < poly.length; h++) {
            if (_ringContains([lon, lat], poly[h])) { inHole = true; break; }
          }
          if (!inHole) return true;
        }
      }
      return false;
    };

        const studyFeatures = b.grocers_by_year.features.filter((f) => {
      const c = f.geometry?.coordinates;
      return c && inStudy(c[0], c[1]);
    });
    layers.__grocerYearTotals = {};
    for (const yr of [2005, 2010, 2015, 2020, 2025]) {
      layers.__grocerYearTotals[yr] = studyFeatures.filter(
        (f) => f.properties?.snapshot_year === yr
      ).length;
    }
    console.log("[grocers] study-area totals:", layers.__grocerYearTotals);

            const radiusFor = (st) => {
      if (!st) return 3;
      const s = st.toLowerCase();
      if (s.includes("supermarket")) return 8;
      if (s.includes("super")) return 7;
      if (s.includes("large")) return 6;
      if (s.includes("medium")) return 5;
      if (s.includes("small")) return 4;
      return 3; 
    };

            const keyFor = (f) => {
      const c = f.geometry.coordinates;
      const p = f.properties || {};
      return `${(p.name || "").toUpperCase()}|${c[0].toFixed(5)}|${c[1].toFixed(5)}`;
    };

                    const locKey3 = (f) => {
      const c = f.geometry.coordinates;
      return `${c[0].toFixed(3)}|${c[1].toFixed(3)}`;
    };
    const stores = new Map();
    const locByYear = new Map(); 
    for (const f of studyFeatures) {
      const k = keyFor(f);
      const yr = f.properties?.snapshot_year;
      if (!stores.has(k)) {
        stores.set(k, { feature: f, years: new Set(), typeByYear: new Map() });
      }
      const rec = stores.get(k);
      rec.years.add(yr);
      rec.typeByYear.set(yr, f.properties?.store_type || "");
      const lk = locKey3(f);
      if (!locByYear.has(yr)) locByYear.set(yr, new Map());
      const inner = locByYear.get(yr);
      if (!inner.has(lk)) inner.set(lk, new Set());
      inner.get(lk).add(k);
            rec.locKey3 = lk;
    }

        const BASE_COLOR = "#FDD267";        
    const ADDED_COLOR = "#3FE08A";       
    const REMOVED_COLOR = "#7a3a3a";     
    const REPLACED_COLOR = "#F08A2C";    
    const markerByKey = new Map();
    const groupLayer = L.featureGroup();
    for (const [k, rec] of stores) {
      const f = rec.feature;
      const p = f.properties || {};
      const [lon, lat] = f.geometry.coordinates;
      const m = L.circleMarker([lat, lon], {
        pane: "grocerPane",
        radius: radiusFor(p.store_type),
        color: "#1a1208",
        weight: 0.8,
        fillColor: BASE_COLOR,
        fillOpacity: 0.0, 
        opacity: 0.0,
      }).bindTooltip(
        `<strong>${p.name || ""}</strong><br/>${p.store_type || ""}<br/>${p.address || ""}, ${p.city || ""}<br/><span style='opacity:0.7'>Authorized ${p.authorization_date || "?"}${p.end_date ? ". Closed " + p.end_date : ""}</span>`,
        { sticky: true }
      );
      markerByKey.set(k, m);
      m.addTo(groupLayer);
    }
    layers.grocersAll = groupLayer;
    layers.__grocerStores = stores;
    layers.__grocerLocByYear = locByYear;
    layers.__grocerMarkers = markerByKey;
    layers.__grocerRadiusFor = radiusFor;
    layers.__grocerBase = BASE_COLOR;
    layers.__grocerAdded = ADDED_COLOR;
    layers.__grocerRemoved = REMOVED_COLOR;
    layers.__grocerReplaced = REPLACED_COLOR;

                    const supermarketKeys = new Set();
    for (const [k, rec] of stores) {
      let any = false;
      for (const t of rec.typeByYear.values()) {
        const s = (t || "").toLowerCase();
        if (s.includes("supermarket") || s.includes("super store")) {
          any = true;
          break;
        }
      }
      if (any) supermarketKeys.add(k);
    }
    const smGroup = L.featureGroup();
    const smMarkers = new Map();
    for (const k of supermarketKeys) {
      const rec = stores.get(k);
      const f = rec.feature;
      const [lon, lat] = f.geometry.coordinates;
      const m = L.circleMarker([lat, lon], {
        pane: "grocerPane",
        radius: 9,
        color: "#1a1208",
        weight: 1.0,
        fillColor: BASE_COLOR,
        fillOpacity: 0.0,
        opacity: 0.0,
      }).bindTooltip(
        `<strong>${f.properties?.name || ""}</strong><br/>${f.properties?.store_type || ""}<br/>${f.properties?.address || ""}, ${f.properties?.city || ""}`,
        { sticky: true }
      );
      smMarkers.set(k, m);
      m.addTo(smGroup);
    }
    layers.supermarkets = smGroup;
    layers.__smMarkers = smMarkers;
    layers.__smKeys = supermarketKeys;

                const FS_RX = /(supermarket|super store|large grocery|medium grocery|small grocery)/;
    const fsGroup = L.featureGroup();
    let nFs2025 = 0, nSm2025 = 0;
    for (const [, rec] of stores) {
      const t2025 = (rec.typeByYear.get(2025) || "").toLowerCase();
      if (!rec.years.has(2025) || !FS_RX.test(t2025)) continue;
      const f = rec.feature;
      const [lon, lat] = f.geometry.coordinates;
      const isSm = /(supermarket|super store)/.test(t2025);
      if (isSm) nSm2025++;
      nFs2025++;
      L.circleMarker([lat, lon], {
        pane: "grocerPane",
        radius: isSm ? 5 : 3.2,
        color: "#1a1208",
        weight: 1.0,
        fillColor: "#FDD267",
        fillOpacity: 1.0,
        opacity: 1.0,
      })
        .bindTooltip(
          `<strong>${f.properties?.name || ""}</strong><br/>${f.properties?.store_type || ""}<br/>${f.properties?.address || ""}, ${f.properties?.city || ""}`,
          { sticky: true }
        )
        .addTo(fsGroup);
    }
    layers.snapStores = fsGroup;
    layers.__snapStoresCounts = { fs: nFs2025, sm: nSm2025 };
  }

            if (window.__WV_BUILDINGS_RESIDENTIAL__) {
    const data = window.__WV_BUILDINGS_RESIDENTIAL__;
                    const DELTA_CLAMP = 20.0;
    const MID_COLOR = "#b8c2cc"; 
    const greenScale = d3.scaleLinear()
      .domain([0, 1])
      .range([MID_COLOR, "#1e9f4d"])
      .interpolate(d3.interpolateLab);
    const redScale = d3.scaleLinear()
      .domain([0, 1])
      .range([MID_COLOR, "#b00020"])
      .interpolate(d3.interpolateLab);
    const colorScale = (v) => {
      const c = Math.max(-DELTA_CLAMP, Math.min(DELTA_CLAMP, v));
                  const t = Math.sqrt(Math.abs(c) / DELTA_CLAMP); 
      return c < 0 ? greenScale(t) : redScale(t);
    };
                const N = data.lons.length;
    const colors = new Array(N);
    const colorsDim = new Array(N);
    const deltaArr = data.delta || new Array(N).fill(0);
    for (let i = 0; i < N; i++) {
      colors[i] = colorScale(deltaArr[i]);
                        colorsDim[i] = deltaArr[i] > 0.5 ? colors[i] : null;
    }
                    const keepIdx = new Uint32Array(
      (() => { let n = 0; for (let i = 0; i < N; i++) if (colorsDim[i]) n++; return n; })()
    );
    const fadeIdx = new Uint32Array(N - keepIdx.length);
    {
      let kp = 0, fp = 0;
      for (let i = 0; i < N; i++) {
        if (colorsDim[i]) keepIdx[kp++] = i;
        else fadeIdx[fp++] = i;
      }
    }
    const BuildingsCanvasLayer = L.Layer.extend({
      initialize(d, c, cDim, kIdx, fIdx, opts) {
        this._d = d;
        this._colorsBase = c;
        this._colorsDim = cDim;
        this._keepIdx = kIdx;
        this._fadeIdx = fIdx;
                        this._dimT = 0;
        this._dimAnim = null;
        this.options = Object.assign({}, opts || {});
      },
      setDimMode(on, animate = true) {
        const target = on ? 1 : 0;
        if (this._dimAnim) cancelAnimationFrame(this._dimAnim);
        if (!animate || !this._canvas) {
          this._dimT = target;
          if (this._canvas) this._redraw();
          return;
        }
        const start = this._dimT;
        const t0 = performance.now();
        const dur = FADE_MS;
        const tick = (now) => {
          const u = Math.min(1, (now - t0) / dur);
                    const e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
          this._dimT = start + (target - start) * e;
          this._redraw();
          if (u < 1) this._dimAnim = requestAnimationFrame(tick);
          else this._dimAnim = null;
        };
        this._dimAnim = requestAnimationFrame(tick);
      },
      onAdd(map) {
        this._map = map;
        const pane = map.getPane("overlayPane");
        const c = (this._canvas = L.DomUtil.create("canvas", "wv-buildings-canvas"));
        c.style.position = "absolute";
        c.style.pointerEvents = "none";
        c.style.zIndex = "390";
        pane.appendChild(c);
        map.on("moveend zoomend resize viewreset", this._reset, this);
        this._reset();
      },
      onRemove(map) {
        map.off("moveend zoomend resize viewreset", this._reset, this);
        if (this._canvas && this._canvas.parentNode) {
          this._canvas.parentNode.removeChild(this._canvas);
        }
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
        const cs = this._colorsBase;
        const z = m.getZoom();
        const r = z >= 12 ? 0.8 : z >= 10 ? 0.55 : 0.4;
        const bnds = m.getBounds().pad(0.05);
        const minLon = bnds.getWest();
        const maxLon = bnds.getEast();
        const minLat = bnds.getSouth();
        const maxLat = bnds.getNorth();
        const d2 = r * 2;

                        ctx.globalAlpha = 1;
        const ki = this._keepIdx;
        for (let j = 0, K = ki.length; j < K; j++) {
          const i = ki[j];
          const lon = lons[i], lat = lats[i];
          if (lon < minLon || lon > maxLon || lat < minLat || lat > maxLat) continue;
          ctx.fillStyle = cs[i];
          const p = m.latLngToContainerPoint([lat, lon]);
          ctx.fillRect(p.x - r, p.y - r, d2, d2);
        }

                        const fadeAlpha = 1 - this._dimT;
        if (fadeAlpha > 0.001) {
          ctx.globalAlpha = fadeAlpha;
          const fi = this._fadeIdx;
          for (let j = 0, F = fi.length; j < F; j++) {
            const i = fi[j];
            const lon = lons[i], lat = lats[i];
            if (lon < minLon || lon > maxLon || lat < minLat || lat > maxLat) continue;
            ctx.fillStyle = cs[i];
            const p = m.latLngToContainerPoint([lat, lon]);
            ctx.fillRect(p.x - r, p.y - r, d2, d2);
          }
        }
        ctx.globalAlpha = 1;
      },
    });
    layers.buildings = new BuildingsCanvasLayer(data, colors, colorsDim, keepIdx, fadeIdx);
    layers.__buildingsData = data;
    layers.__buildingsColorScale = colorScale;
    layers.__buildingsDeltaClamp = DELTA_CLAMP;
  }

  if (b.dollar_stores) {
    layers.dollar = L.geoJSON(b.dollar_stores, {
      pointToLayer: (f, ll) =>
        L.circleMarker(ll, {
          radius: 3,
          color: COLORS.dollar,
          weight: 0.5,
          fillColor: COLORS.dollar,
          fillOpacity: 0.7,
        }),
    });
  }

  if (b.food_desert_30min) {
    layers.desert = L.geoJSON(b.food_desert_30min, {
      style: {
        color: COLORS.desert,
        weight: 0.5,
        fillColor: COLORS.desert,
        fillOpacity: 0.55,
      },
    });
  }

      if (b.food_deserts && b.food_deserts.features) {
    const COL_05 = "#3FA9F5"; 
    const COL_25 = "#E03A3A"; 
    const COL_BOTH = "#8E44C9"; 
    const f2005 = b.food_deserts.features.find((f) => f.properties?.year === 2005);
    const f2025 = b.food_deserts.features.find((f) => f.properties?.year === 2025);
    const fBoth = b.food_deserts.features.find((f) => f.properties?.year === "persistent");
    if (f2005) {
      layers.desert2005 = L.geoJSON(f2005, {
        style: { color: COL_05, weight: 1.0, fillColor: COL_05, fillOpacity: 0.40 },
        interactive: false,
      });
    }
    if (f2025) {
      layers.desert2025 = L.geoJSON(f2025, {
        style: { color: COL_25, weight: 1.0, fillColor: COL_25, fillOpacity: 0.40 },
        interactive: false,
      });
    }
    if (fBoth) {
      layers.desertBoth = L.geoJSON(fBoth, {
        style: { color: COL_BOTH, weight: 0.6, fillColor: COL_BOTH, fillOpacity: 0.40 },
        interactive: false,
      });
    }
    layers.__desertProps2005 = f2005?.properties || {};
    layers.__desertProps2025 = f2025?.properties || {};
    layers.__desertColors = { c05: COL_05, c25: COL_25, both: COL_BOTH };
    layers.__desertSummary = b.food_deserts._meta?.summary || null;
  }

  if (b.hrsa_shortage) {
    layers.shortage = L.geoJSON(b.hrsa_shortage, {
      style: {
        color: COLORS.shortage,
        weight: 0.6,
        fillColor: COLORS.shortage,
        fillOpacity: 0.25,
      },
    });
  }

  if (b.intervention_sites) {
    layers.intervention = L.geoJSON(b.intervention_sites, {
      pointToLayer: (f, ll) =>
        L.circleMarker(ll, {
          radius: 8,
          color: COLORS.intervention,
          weight: 2,
          fillColor: COLORS.intervention,
          fillOpacity: 0.6,
        }),
    });
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function _padPx(frac = 0.06) {
  return Math.round(window.innerHeight * frac);
}

function _cardPadPx() {
  if (window.innerWidth <= 980) return _padPx(0.06);
  const cardWidth = Math.min(920, window.innerWidth * 0.92);
  const cardLeft = window.innerWidth * 0.04;
  const gutter = 28;
  return Math.round(cardLeft + cardWidth + gutter);
}

function fitWithNarrativeOffset(animate = false, durationS = 0) {
  if (!layers.boundary) return;
  const bounds = layers.boundary.getBounds();
  if (!bounds.isValid()) return;
  const padV = _padPx(0.06);
  const padLeft = _cardPadPx();
  const opts = {
    paddingTopLeft: [padLeft, padV],
    paddingBottomRight: [_padPx(0.04), padV],
    animate,
  };
  if (animate && durationS > 0) {
    map.flyToBounds(bounds, { ...opts, duration: durationS });
  } else {
    map.fitBounds(bounds, opts);
  }
}

function _stepView(step, b) {
  return { kind: "studyArea", padFrac: 0.06 };
}

let _lastViewKey = null;
function applyStepView(step, b, { animate = true } = {}) {
  const v = _stepView(step, b);
    const key = JSON.stringify(v.kind === "feature" ? { k: "f", n: v.feature.properties?.NAME } : v);
  if (key === _lastViewKey) return;
  _lastViewKey = key;

  const dur = animate ? 1.1 : 0;
  if (v.kind === "feature") {
    const tmp = L.geoJSON(v.feature);
    const padV = _padPx(v.padFrac ?? 0.08);
    const padLeft = _cardPadPx();
    const opts = { paddingTopLeft: [padLeft, padV], paddingBottomRight: [_padPx(0.04), padV] };
    if (animate) map.flyToBounds(tmp.getBounds(), { ...opts, duration: dur });
    else map.fitBounds(tmp.getBounds(), { ...opts, animate: false });
  } else {
    fitWithNarrativeOffset(animate, dur);
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
const FADE_MS = 600;
let _fadeToken = 0;

function desiredLayerKeys(step) {
  const want = new Set();
  if (step === 2 && layers.grocersAll) want.add("grocersAll");
  else if (step === 3 && layers.buildings && layers.supermarkets) {
    want.add("buildings"); want.add("supermarkets");
    want.add("__terrainDim__"); 
  } else if (step === 4 && layers.buildings && layers.supermarkets) {
    want.add("buildings"); want.add("supermarkets");
    want.add("__terrainDim__");
  } else if (step === 5 && layers.desert2025) {
    want.add("desert2025");
    if (layers.desert2005) want.add("desert2005");
    if (layers.desertBoth) want.add("desertBoth");
    want.add("areaSquares");
  } else if (step === 6) {
    if (layers.snapPct) want.add("snapPct");
    if (layers.snapStores) want.add("snapStores");
    want.add("__terrainDim__"); 
  }
  return want;
}

function _layerEls(layer) {
  const out = [];
  if (!layer) return out;
  if (layer._path) out.push(layer._path);
  if (layer._image) out.push(layer._image);
  if (layer._canvas) out.push(layer._canvas);
  if (typeof layer.eachLayer === "function") {
    layer.eachLayer((sub) => {
      for (const e of _layerEls(sub)) out.push(e);
    });
  }
  return out;
}
function _setLayerOpacity(layer, v) {
  for (const el of _layerEls(layer)) {
    el.style.opacity = String(v);
  }
}
function _animateLayer(layer, from, to) {
  const els = _layerEls(layer);
  for (const el of els) {
    el.style.opacity = String(to);
    if (typeof el.animate === "function") {
      el.animate(
        [{ opacity: from }, { opacity: to }],
        { duration: FADE_MS, easing: "ease" }
      );
    }
  }
}
function _animatePanel(el, from, to) {
  if (!el) return;
  el.style.opacity = String(to);
  if (typeof el.animate === "function") {
    el.animate(
      [{ opacity: from }, { opacity: to }],
      { duration: FADE_MS, easing: "ease" }
    );
  }
}

function activateStep(step, b) {
  if (!b) return;

    if (step >= 7) return;

  applyStepView(step, b, { animate: true });

  const want = desiredLayerKeys(step);
  const present = new Set();
  for (const [k, layer] of Object.entries(layers)) {
    if (k.startsWith("__")) continue;
    if (k === "boundary" || k === "hillshade" || k === "roads") continue;
    if (map.hasLayer(layer)) present.add(k);
  }
  const leaving = [...present].filter((k) => !want.has(k));
  const entering = [...want].filter((k) => !k.startsWith("__") && !present.has(k));

  const token = ++_fadeToken;

          for (const k of leaving) _animateLayer(layers[k], 1, 0);
  _animatePanel(legendEl, 1, 0);
  if (want.has("areaSquares") || !areaSquaresEl.hidden) {
    _animatePanel(areaSquaresEl, 1, 0);
  }

  setTimeout(() => {
    if (token !== _fadeToken) return;

        _activateStepCore(step, b, want);

            for (const k of entering) {
      if (layers[k]) _animateLayer(layers[k], 0, 1);
    }
    _animatePanel(legendEl, 0, 1);
    _animatePanel(areaSquaresEl, 0, 1);
  }, FADE_MS);
}

function _activateStepCore(step, b, keep) {
  clearAll(keep);

  if (step === 2 && layers.grocersAll) {
                        const yrs = [2005, 2010, 2015, 2020, 2025];
    const totals = layers.__grocerYearTotals || { 2005: 0, 2010: 0, 2015: 0, 2020: 0, 2025: 0 };
    const stores = layers.__grocerStores;
    const markers = layers.__grocerMarkers;
    const locByYear = layers.__grocerLocByYear;
    const radiusFor = layers.__grocerRadiusFor;
    const BASE = layers.__grocerBase;
    const ADDED = layers.__grocerAdded;
    const REMOVED = layers.__grocerRemoved;
    const REPLACED = layers.__grocerReplaced;
    layers.grocersAll.addTo(map);

        const T_HOLD = 1200;       
    const T_CLOSE = 1200;      
    const T_OPEN = 1200;       
    const T_REST = 600;        
    const CYCLE = T_HOLD + T_CLOSE + T_OPEN + T_REST;

    const styleBaseFor = (m, st) => m.setStyle({ radius: radiusFor(st), fillColor: BASE, color: "#1a1208", fillOpacity: 0.92, opacity: 0.95, weight: 0.8 });
    const styleHidden = (m) => m.setStyle({ fillOpacity: 0, opacity: 0 });
    const styleClosing = (m, st) => m.setStyle({ radius: radiusFor(st), fillColor: REMOVED, color: "#FF5050", fillOpacity: 0.55, opacity: 1.0, weight: 2.5 });
    const styleOpening = (m, st) => m.setStyle({ radius: radiusFor(st), fillColor: ADDED, color: ADDED, fillOpacity: 1.0, opacity: 1.0, weight: 2.5 });
    const styleReplacedOut = (m, st) => m.setStyle({ radius: radiusFor(st), fillColor: REPLACED, color: REPLACED, fillOpacity: 0.55, opacity: 1.0, weight: 2.5 });
    const styleReplacedIn = (m, st) => m.setStyle({ radius: radiusFor(st), fillColor: REPLACED, color: REPLACED, fillOpacity: 0.95, opacity: 1.0, weight: 2.5 });

        let cumOpened = 0;
    let cumClosed = 0;
    let cumReplaced = 0;

    const renderLegend = (y, prev, addedN, closedN, replacedN) => {
      const dotC = (color, size = 10) =>
        `<span class='swatch dot' style='background:${color};width:${size}px;height:${size}px;display:inline-block;border-radius:50%;margin-right:6px;vertical-align:middle'></span>`;
            const tl = (() => {
        const w = 220, h = 36, pad = 14;
        const step = (w - pad * 2) / (yrs.length - 1);
        let svg = `<svg width='${w}' height='${h}' style='display:block;margin-top:0.4rem'>`;
        svg += `<line x1='${pad}' y1='${h / 2}' x2='${w - pad}' y2='${h / 2}' stroke='${BASE}' stroke-opacity='0.25' stroke-width='2'/>`;
        const idx = yrs.indexOf(y);
        if (idx > 0) {
          svg += `<line x1='${pad}' y1='${h / 2}' x2='${pad + step * idx}' y2='${h / 2}' stroke='${BASE}' stroke-opacity='0.85' stroke-width='2'/>`;
        }
        yrs.forEach((yr, ix) => {
          const cx = pad + step * ix;
          const isCur = yr === y;
          const r = isCur ? 6 : 3.5;
          const op = isCur ? 1 : 0.35;
          svg += `<circle cx='${cx}' cy='${h / 2}' r='${r}' fill='${BASE}' fill-opacity='${op}'/>`;
          svg += `<text x='${cx}' y='${h - 1}' font-size='10' fill='${BASE}' fill-opacity='${isCur ? 1 : 0.5}' text-anchor='middle' font-weight='${isCur ? 600 : 400}'>${yr}</text>`;
        });
        svg += "</svg>";
        return svg;
      })();
      const deltaRow =
        `<div class='legend-item' style='margin-top:0.3rem;min-height:1.2em'>` +
          (prev == null
            ? `<span style='opacity:0.45'>baseline year</span>`
            : `<span style='color:${ADDED}'>+${addedN} new</span> · ` +
              `<span style='color:#FF7878'>−${closedN} closed</span> · ` +
              `<span style='color:${REPLACED}'>↻${replacedN} replaced</span> ` +
              `<span style='opacity:0.6'>since ${prev}</span>`) +
        "</div>";
      const net = cumOpened - cumClosed;
      setLegend(
        "<div class='legend-group'><h4>SNAP-authorized grocers, 19-county study area</h4>" +
        `<div class='legend-item' style='font-size:2.2rem;font-weight:700;color:${BASE};letter-spacing:0.05em;margin:0.2rem 0;line-height:1;min-height:2.4rem'>${y}</div>` +
        `<div class='legend-item' style='min-height:1.2em'>${totals[y]} active grocery retailers</div>` +
        deltaRow +
        `<div class='legend-item' style='margin-top:0.6rem;padding-top:0.4rem;border-top:1px solid rgba(255,255,255,0.12);font-size:0.85rem'>` +
          `<div style='opacity:0.75'>Cumulative since ${yrs[0]}</div>` +
          `<div style='margin-top:0.15rem;min-height:1.2em'><span style='color:${ADDED}'>+${cumOpened}</span> · ` +
          `<span style='color:#FF7878'>−${cumClosed}</span> · ` +
          `<span style='color:${REPLACED}'>↻${cumReplaced}</span> · ` +
          `<span style='opacity:0.85'>net ${(net >= 0 ? "+" : "") + net}</span></div>` +
        "</div>" +
        tl +
        `<div class='legend-item' style='margin-top:0.6rem;font-size:0.82rem;opacity:0.85'>` +
          dotC(ADDED, 8) + "newly authorized · " + dotC("#FF5050", 8) + "just closed · " + dotC(REPLACED, 8) + "replaced at same parcel" +
        "</div>" +
        `<div class='legend-item' style='font-size:0.78rem;opacity:0.7'>dot size = store category (super store → small grocer → combo/other)</div>` +
        "<div class='legend-item' style='margin-top:0.4rem;font-size:0.75rem;color:var(--cream-dim)'>Source: USDA-FNS SNAP Retailer Locator (2005–2025).</div>" +
        "</div>"
      );
    };

        let i = 0;
    let prevYear = null;
    const initYear = (y) => {
      for (const [k, rec] of stores) {
        const m = markers.get(k);
        if (!m) continue;
        if (rec.years.has(y)) styleBaseFor(m, rec.typeByYear.get(y));
        else styleHidden(m);
      }
      renderLegend(y, null, 0, 0, 0);
    };
    initYear(yrs[0]);

                        const diffWithReplacements = (prev, y) => {
      const addedKeys = [];
      const closedKeys = [];
      for (const [k, rec] of stores) {
        const a = rec.years.has(y);
        const b2 = rec.years.has(prev);
        if (a && !b2) addedKeys.push(k);
        else if (!a && b2) closedKeys.push(k);
      }
      const prevLoc = locByYear.get(prev) || new Map();
      const curLoc = locByYear.get(y) || new Map();
      const replacedOut = new Set();
      const replacedIn = new Set();
      for (const k of closedKeys) {
        const lk = stores.get(k).locKey3;
                        const inCur = curLoc.get(lk);
        const inPrev = prevLoc.get(lk) || new Set();
        if (inCur) {
          for (const otherKey of inCur) {
            if (!inPrev.has(otherKey)) {
              replacedOut.add(k);
              replacedIn.add(otherKey);
            }
          }
        }
      }
      const pureClosed = closedKeys.filter((k) => !replacedOut.has(k));
      const pureAdded = addedKeys.filter((k) => !replacedIn.has(k));
      return {
        addedKeys: pureAdded,
        closedKeys: pureClosed,
        replacedOutKeys: [...replacedOut],
        replacedInKeys: [...replacedIn],
      };
    };

        const runTransition = (prev, y) => {
      const { addedKeys, closedKeys, replacedOutKeys, replacedInKeys } =
        diffWithReplacements(prev, y);

            for (const [k, rec] of stores) {
        if (!rec.years.has(prev) && !rec.years.has(y)) {
          const m = markers.get(k);
          if (m) styleHidden(m);
        }
      }
                  for (const [k, rec] of stores) {
        if (rec.years.has(prev) && rec.years.has(y)) {
          const m = markers.get(k);
          if (m) styleBaseFor(m, rec.typeByYear.get(y));
        }
      }

      const stType = (k, yr) => stores.get(k)?.typeByYear.get(yr) || "";

            const t1 = setTimeout(() => {
        for (const k of closedKeys) {
          const m = markers.get(k);
          if (m) styleClosing(m, stType(k, prev));
        }
        for (const k of replacedOutKeys) {
          const m = markers.get(k);
          if (m) styleReplacedOut(m, stType(k, prev));
        }
      }, T_HOLD);

                  const t2 = setTimeout(() => {
        for (const k of closedKeys) {
          const m = markers.get(k);
          if (m) styleHidden(m);
        }
        for (const k of replacedOutKeys) {
          const m = markers.get(k);
          if (m) styleHidden(m);
        }
        for (const k of addedKeys) {
          const m = markers.get(k);
          if (m) styleOpening(m, stType(k, y));
        }
        for (const k of replacedInKeys) {
          const m = markers.get(k);
          if (m) styleReplacedIn(m, stType(k, y));
        }
      }, T_HOLD + T_CLOSE);

            const t3 = setTimeout(() => {
        for (const k of addedKeys) {
          const m = markers.get(k);
          if (m) styleBaseFor(m, stType(k, y));
        }
        for (const k of replacedInKeys) {
          const m = markers.get(k);
          if (m) styleBaseFor(m, stType(k, y));
        }
      }, T_HOLD + T_CLOSE + T_OPEN);

      layers.__grocerStageTOs = [t1, t2, t3];
                  renderLegend(y, prev, addedKeys.length, closedKeys.length, replacedInKeys.length);
      cumOpened += addedKeys.length;
      cumClosed += closedKeys.length;
      cumReplaced += replacedInKeys.length;
      const t4 = setTimeout(
        () => renderLegend(y, prev, addedKeys.length, closedKeys.length, replacedInKeys.length),
        50
      );
      layers.__grocerStageTOs.push(t4);
    };

        const tick = () => {
      const active = document.querySelector(".step.active");
      if (!active || Number(active.dataset.step) !== 2) {
        clearInterval(layers.__grocerYearTimer);
        layers.__grocerYearTimer = null;
        return;
      }
      const prev = yrs[i];
      i = (i + 1) % yrs.length;
            if (i === 0) {
        cumOpened = 0;
        cumClosed = 0;
        cumReplaced = 0;
        prevYear = null;
        initYear(yrs[0]);
        return;
      }
      const y = yrs[i];
      prevYear = y;
      runTransition(prev, y);
    };
    if (layers.__grocerYearTimer) clearInterval(layers.__grocerYearTimer);
    layers.__grocerYearTimer = setInterval(tick, CYCLE);
  } else if (step === 3 && layers.buildings && layers.supermarkets) {
                    const data = layers.__buildingsData;
    const stats = (data.delta_stats || {});
    const totalBldg = data.total;
    const stores = layers.__grocerStores;
    const smKeys = layers.__smKeys;
    const smMarkers = layers.__smMarkers;
    const SM_BLUE = "#FF8C00";
    const colorScale = layers.__buildingsColorScale;
    const CLAMP = layers.__buildingsDeltaClamp || 5;

                setRoadsOpacity(0);
    setTerrainOpacity(0.25);

    layers.buildings.addTo(map);
    if (layers.buildings.setDimMode) layers.buildings.setDimMode(false);
    layers.supermarkets.addTo(map);

                let nActive = 0, nClosed = 0;
    for (const k of smKeys) {
      const rec = stores.get(k);
      const m = smMarkers.get(k);
      if (!rec || !m) continue;
      const wasFs = (yr) => {
        const t = (rec.typeByYear.get(yr) || "").toLowerCase();
        return t.includes("supermarket") || t.includes("super store");
      };
      const fs2025 = rec.years.has(2025) && wasFs(2025);
      const everFs = [2005, 2010, 2015, 2020, 2025].some((y) => rec.years.has(y) && wasFs(y));
      if (fs2025) {
        m.setStyle({
          fillOpacity: 0.95, opacity: 1.0,
          color: "#2a1a05", fillColor: SM_BLUE, weight: 1.2,
        });
        nActive++;
      } else if (everFs) {
        m.setStyle({
          fillOpacity: 0.0, opacity: 0.95,
          color: SM_BLUE, fillColor: SM_BLUE, weight: 1.6,
        });
        nClosed++;
      } else {
        m.setStyle({ fillOpacity: 0, opacity: 0 });
      }
    }

        const rampW = 220, rampH = 12;
    const stops = [];
    for (let i = 0; i <= 40; i++) {
      const t = i / 40;
      const v = -CLAMP + t * 2 * CLAMP;
      stops.push(`<stop offset='${(t * 100).toFixed(1)}%' stop-color='${colorScale(v)}'/>`);
    }
    const ramp =
      `<svg width='${rampW}' height='${rampH + 14}' style='display:block;margin-top:0.35rem'>` +
        `<defs><linearGradient id='wvDeltaRamp' x1='0%' x2='100%'>${stops.join("")}</linearGradient></defs>` +
        `<rect x='0' y='0' width='${rampW}' height='${rampH}' fill='url(#wvDeltaRamp)'/>` +
        `<text x='0' y='${rampH + 12}' font-size='10' fill='#fff' fill-opacity='0.85'>closer</text>` +
        `<text x='${rampW / 2}' y='${rampH + 12}' font-size='10' fill='#fff' fill-opacity='0.85' text-anchor='middle'>no change</text>` +
        `<text x='${rampW}' y='${rampH + 12}' font-size='10' fill='#fff' fill-opacity='0.85' text-anchor='end'>farther</text>` +
      "</svg>";

    const fmt = d3.format(",");
    const fmtSigned = (v) => (v > 0 ? "+" : "") + v.toFixed(2);
    const nWorse = stats.n_worse_half_mi || 0;
    const nBetter = stats.n_better_half_mi || 0;
    const medLost = stats.median_lost_mi || 0;
    const medGained = stats.median_gained_mi || 0;
    const card = (color, value, label, sub) =>
      `<div style="flex:1;min-width:0;padding:0.45rem 0.55rem;border:1px solid var(--border);background:rgba(0,0,0,0.25)">` +
        `<div style="font-family:var(--font-h2);font-size:26px;line-height:1.05;color:${color};font-weight:700">${fmt(value)}</div>` +
        `<div style="font-size:11px;color:var(--cream-dim);text-transform:uppercase;letter-spacing:0.06em;margin-top:0.2rem;line-height:1.25">${label}</div>` +
        `<div style="font-size:12px;color:${color};margin-top:0.3rem;line-height:1.2"><strong>${sub}</strong> <span style="color:var(--cream-dim);font-weight:400">median</span></div>` +
      "</div>";

    setLegend(
      "<div class='legend-group'>" +
        "<h4>Change in reach to a full-service grocer, 2005 → 2025</h4>" +
                `<div style="display:flex;gap:0.5rem;margin:0.35rem 0 0.2rem">` +
          card("#c4302b", nWorse, "homes ≥ ½ mi farther", `+${medLost.toFixed(2)} mi`) +
          card("#3FE08A", nBetter, "homes ≥ ½ mi closer", `${medGained.toFixed(2)} mi`) +
        "</div>" +
      "</div>" +
            "<div class='legend-group'>" +
        `<div style='font-size:0.78rem;color:var(--cream-dim);text-transform:uppercase;letter-spacing:0.08em'>Driving distance Δ per home</div>` +
        ramp +
      "</div>" +
            "<div class='legend-group'>" +
        `<div class='legend-item' style='margin:0.15rem 0'>` +
          `<span class='swatch dot' style='background:${SM_BLUE};border:1px solid #2a1a05;width:12px;height:12px'></span>` +
          `<span><strong>${nActive}</strong> active supermarkets (2025)</span>` +
        "</div>" +
        `<div class='legend-item' style='margin:0.15rem 0'>` +
          `<span class='swatch dot' style='background:transparent;border:1.5px solid ${SM_BLUE};width:12px;height:12px'></span>` +
          `<span><strong>${nClosed}</strong> closed since 2005</span>` +
        "</div>" +
      "</div>" +
            "<div class='legend-group'>" +
        `<div style='font-size:0.74rem;color:var(--cream-dim);line-height:1.35'>` +
          `Driving distance along the road network from each home to the nearest Supermarket or Super Store ` +
          `(multi-source Dijkstra on the southern-WV OSM drive graph). ` +
          `Homes: Microsoft USBuildingFootprints + OSM use-tags (${fmt(totalBldg)} residential). ` +
          `Color clipped to ±${CLAMP} mi.` +
        "</div>" +
      "</div>"
    );
    if (layers.__buildingsTimer) {
      clearInterval(layers.__buildingsTimer);
      layers.__buildingsTimer = null;
    }
  } else if (step === 4 && layers.buildings && layers.supermarkets) {
                const data = layers.__buildingsData;
    const stats = (data.delta_stats || {});
    const totalBldg = data.total;
    const stores = layers.__grocerStores;
    const smKeys = layers.__smKeys;
    const smMarkers = layers.__smMarkers;
    const SM_ORANGE = "#FF8C00";
    const colorScale = layers.__buildingsColorScale;
    const CLAMP = layers.__buildingsDeltaClamp || 5;

        setRoadsOpacity(0);
    setTerrainOpacity(0.25);

    layers.buildings.addTo(map);
    if (layers.buildings.setDimMode) layers.buildings.setDimMode(true);
    layers.supermarkets.addTo(map);

        let nActive = 0, nClosed = 0;
    for (const k of smKeys) {
      const rec = stores.get(k);
      const m = smMarkers.get(k);
      if (!rec || !m) continue;
      const wasFs = (yr) => {
        const t = (rec.typeByYear.get(yr) || "").toLowerCase();
        return t.includes("supermarket") || t.includes("super store");
      };
      const fs2025 = rec.years.has(2025) && wasFs(2025);
      const everFs = [2005, 2010, 2015, 2020, 2025].some((y) => rec.years.has(y) && wasFs(y));
      if (fs2025) {
                m.setStyle({ fillOpacity: 0, opacity: 0 });
        nActive++;
      } else if (everFs) {
        m.setStyle({ fillOpacity: 0.0, opacity: 0.95, color: SM_ORANGE, fillColor: SM_ORANGE, weight: 1.6 });
        nClosed++;
      } else {
        m.setStyle({ fillOpacity: 0, opacity: 0 });
      }
    }

    const fmt = d3.format(",");
    const nWorse = stats.n_worse_half_mi || 0;
    const medLost = stats.median_lost_mi || 0;
    setLegend(
      "<div class='legend-group'><h4>Where reach got worse</h4>" +
        `<div style="padding:0.5rem 0.6rem;border:1px solid var(--border);background:rgba(0,0,0,0.25);margin-top:0.35rem">` +
          `<div style="font-family:var(--font-h2);font-size:28px;line-height:1.05;color:#c4302b;font-weight:700">${fmt(nWorse)}</div>` +
          `<div style="font-size:11px;color:var(--cream-dim);text-transform:uppercase;letter-spacing:0.06em;margin-top:0.2rem">homes ≥ ½ mi farther in 2025</div>` +
          `<div style="font-size:12px;color:#c4302b;margin-top:0.3rem"><strong>+${medLost.toFixed(2)} mi</strong> <span style="color:var(--cream-dim);font-weight:400">median</span></div>` +
        "</div>" +
      "</div>" +
      "<div class='legend-group'>" +
        `<div class='legend-item' style='margin:0.15rem 0'>` +
          `<span class='swatch dot' style='background:transparent;border:1.5px solid ${SM_ORANGE};width:12px;height:12px'></span>` +
          `<span><strong>${nClosed}</strong> supermarkets closed since 2005</span>` +
        "</div>" +
      "</div>" +
      "<div class='legend-group'>" +
        `<div style='font-size:0.74rem;color:var(--cream-dim);line-height:1.35'>` +
          `Homes whose drive distance improved or barely changed are dimmed; ` +
          `colored homes are those whose nearest supermarket got at least ½ mi farther by road. ` +
          `Total: ${fmt(totalBldg)} residential structures.` +
        "</div>" +
      "</div>"
    );
  } else if (step === 5 && layers.desert2025) {
                layers.desert2025.addTo(map);
    if (layers.desert2005) layers.desert2005.addTo(map);
    if (layers.desertBoth) layers.desertBoth.addTo(map);
    const c = layers.__desertColors || { c05: "#3FA9F5", c25: "#E03A3A", both: "#8E44C9" };
    const p05 = layers.__desertProps2005 || {};
    const p25 = layers.__desertProps2025 || {};
    const pct = (v) => (v == null ? "-" : `${v.toFixed(1)}%`);
    setLegend(
      "<div class='legend-group'><h4>Food deserts (FNS thresholds)</h4>" +
        `<div class='legend-item' style='display:block;font-size:0.78rem;color:var(--cream-dim);line-height:1.3;margin:0.25rem 0 0.45rem'>` +
          `> ½ mi by road inside urban areas<br>` +
          `> 10 mi by road everywhere else` +
        "</div>" +
      "</div>" +
      "<div class='legend-group'>" +
        `<div class='legend-item'>` +
          `<span class='swatch' style='background:${c.c05};opacity:0.6;border:1px solid ${c.c05}'></span>` +
          `<span><strong>2005</strong> only: desert disappeared</span>` +
        "</div>" +
        `<div class='legend-item'>` +
          `<span class='swatch' style='background:${c.c25};opacity:0.6;border:1px solid ${c.c25}'></span>` +
          `<span><strong>2025</strong> only: desert grew</span>` +
        "</div>" +
        `<div class='legend-item'>` +
          `<span class='swatch' style='background:${c.both};opacity:0.6;border:1px solid ${c.both}'></span>` +
          `<span><strong>Both</strong>: persistent desert</span>` +
        "</div>" +
        `<div class='legend-item' style='display:block;font-size:0.74rem;color:var(--cream-dim);line-height:1.3;margin-top:0.4rem'>` +
          `2005: ${pct(p05.pct_of_study)} of land area<br>2025: ${pct(p25.pct_of_study)} of land area` +
        "</div>" +
      "</div>"
    );
    showAreaSquares(layers.__desertSummary);
  } else if (step === 6) {
                    setRoadsOpacity(0);
    setTerrainOpacity(0);
    if (layers.snapPct) layers.snapPct.addTo(map);
    if (layers.snapStores) layers.snapStores.addTo(map);
    const s = layers.__snapScale;
    const counts = layers.__snapStoresCounts || { fs: 0, sm: 0 };
    const fmt = d3.format(",");
    const ramp = (() => {
      const rampW = 220, rampH = 12;
      const stops = [];
      for (let i = 0; i <= 40; i++) {
        const t = i / 40;
        const v = 5 + t * 30; 
        stops.push(`<stop offset='${(t * 100).toFixed(1)}%' stop-color='${s ? s(v) : "#888"}'/>`);
      }
      return (
        `<svg width='${rampW}' height='${rampH + 14}' style='display:block;margin-top:0.35rem'>` +
          `<defs><linearGradient id='wvSnapRamp' x1='0%' x2='100%'>${stops.join("")}</linearGradient></defs>` +
          `<rect x='0' y='0' width='${rampW}' height='${rampH}' fill='url(#wvSnapRamp)'/>` +
          `<text x='0' y='${rampH + 12}' font-size='10' fill='#fff' fill-opacity='0.85'>5%</text>` +
          `<text x='${rampW / 2}' y='${rampH + 12}' font-size='10' fill='#fff' fill-opacity='0.85' text-anchor='middle'>20%</text>` +
          `<text x='${rampW}' y='${rampH + 12}' font-size='10' fill='#fff' fill-opacity='0.85' text-anchor='end'>35%+</text>` +
        "</svg>"
      );
    })();
    const card = (color, value, label, sub) =>
      `<div style="flex:1;min-width:0;padding:0.45rem 0.55rem;border:1px solid var(--border);background:rgba(0,0,0,0.25)">` +
        `<div style="font-family:var(--font-h2);font-size:24px;line-height:1.05;color:${color};font-weight:700">${value}</div>` +
        `<div style="font-size:11px;color:var(--cream-dim);text-transform:uppercase;letter-spacing:0.06em;margin-top:0.2rem;line-height:1.25">${label}</div>` +
        (sub ? `<div style="font-size:12px;color:${color};margin-top:0.3rem;line-height:1.2">${sub}</div>` : "") +
      "</div>";
    setLegend(
      "<div class='legend-group'>" +
        "<h4>Households on SNAP, 2018-2022 (ACS B22003, tracts)</h4>" +
        `<div style="display:flex;gap:0.5rem;margin:0.35rem 0 0.2rem">` +
          card("#9C6BC9", "20.9%", "Study area", "<strong>52,410</strong> SNAP households") +
          card("#9C6BC9", "54.1%", "Highest tract", "McDowell &middot; Tract 9538") +
        "</div>" +
        `<div style='font-size:0.78rem;color:var(--cream-dim);text-transform:uppercase;letter-spacing:0.08em;margin-top:0.5rem'>SNAP enrollment rate (% of households)</div>` +
        ramp +
      "</div>" +
      "<div class='legend-group'>" +
        `<div class='legend-item' style='margin:0.15rem 0'>` +
          `<span class='swatch dot' style='background:#FDD267;border:1px solid #1a1208;width:10px;height:10px'></span>` +
          `<span><strong>${counts.fs}</strong> SNAP-authorized full-service grocers in 2025` +
          (counts.sm ? ` (<strong>${counts.sm}</strong> supermarkets)` : "") +
          `</span>` +
        "</div>" +
        `<div class='legend-item' style='display:block;font-size:0.78rem;color:var(--cream-dim);line-height:1.35;margin-top:0.35rem'>` +
          `Tracts: TIGER 2022, 193 in study area. WV statewide: 16.6%. U.S.: ~12.6%. ` +
          `Pearson <strong>r = -0.56</strong> (county) between SNAP rate and supermarkets per 10k SNAP households.` +
        "</div>" +
      "</div>"
    );
  } else if (step === 1) {
    setLegend(
      "<div class='legend-group'><h4>Study region</h4>" +
      "<div class='legend-item'>17 southern WV counties</div></div>"
    );
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function computeMetrics(b) {
  if (!b) return;
  setMetric("counties", fmt(b.counties?.features?.length));
  setMetric("groceries", fmt(b.grocery_current?.features?.length));
  setMetric("dollars", fmt(b.dollar_stores?.features?.length));
  if (b.counties && b.grocery_current) {
    const withStore = new Set();
    for (const g of b.grocery_current.features) {
      if (g.properties?.NAME) withStore.add(g.properties.NAME);
    }
    const zero = b.counties.features.filter(
      (f) => !withStore.has(f.properties?.NAME)
    ).length;
    setMetric("zero", fmt(zero));
  }
  if (b.population_in_desert != null) {
    setMetric("pop", fmt(b.population_in_desert));
  }
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
(async function boot() {
  const bundle = await loadBundle();
  buildLayers(bundle);
  computeMetrics(bundle);
    applyStepView(1, bundle, { animate: false });
  window.addEventListener("resize", () => {
    _lastViewKey = null;
    const active = document.querySelector(".step.active");
    const step = active ? Number(active.dataset.step) : 1;
    applyStepView(step, bundle, { animate: false });
  });

  const steps = Array.from(document.querySelectorAll(".step"));
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        steps.forEach((s) => s.classList.remove("active"));
        e.target.classList.add("active");
        activateStep(Number(e.target.dataset.step), bundle);
      });
    },
    { threshold: 0.55 }
  );
  steps.forEach((el) => io.observe(el));
  activateStep(1, bundle);
})();
