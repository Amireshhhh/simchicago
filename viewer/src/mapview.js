// 2D map mode: a light, Google-Maps-like view built with MapLibre GL from self-hosted City of
// Chicago data (no third-party tiles, no keys). Layers: streets by class, community areas, CTA
// network, near-live vehicles (observed), simulated residents (simulated), benches (observed,
// mixed sources). Labels are an HTML overlay (no glyph server needed).
import * as maplibregl from 'maplibre-gl';
import { bestShape, playbackTime, trackPosition, snapshotAge, bearingDeg } from './core.js';

const fmtClock = iso => { try { return new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit', second: '2-digit' }); } catch { return ''; } };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const THEMES = {
  real: { water: '#aad3f0', land: '#f3f1ec', city: '#f7f5f0', areaLine: '#c9c3b6', areaFill: 'rgba(0,0,0,0)', casing: '#d8d3c8',
    s4: '#ffffff', s3: '#ffffff', s2: '#ffe9a8', s1: '#f8b55c', s9: '#f8c98a', river: '#aad3f0', bus: '#7a8aa0', label: '#3c4250', labelHalo: '#ffffff',
    resident: 0.9, text: '#1f2633' },
  neon: { water: '#0b0418', land: '#12061f', city: '#160828', areaLine: '#5b2a7a', areaFill: 'rgba(0,0,0,0)', casing: '#12061f',
    s4: '#3a1d63', s3: '#00b8d4', s2: '#ff2bd6', s1: '#f5ff3b', s9: '#ff8af0', river: '#1f0f4a', bus: '#6a4c9c', label: '#f2d9ff', labelHalo: '#12061f',
    resident: 1, text: '#f6ecff' },
};

const ACT = { home: '#9bb0c6', work: '#3f7be0', school: '#29a3d6', aftercare: '#29a3d6', shop: '#e89b1d', social: '#e0559a', leisure: '#2fae6b', errand: '#b59a2a', wait: '#9bb0c6' };

function style(t) {
  const w = (z0, w0, z1, w1) => ['interpolate', ['exponential', 1.6], ['zoom'], z0, w0, z1, w1];
  return {
    version: 8,
    sources: {
      land: { type: 'geojson', data: 'data/map/land.json' },
      areas: { type: 'geojson', data: 'data/map/areas.json' },
      streets: { type: 'geojson', data: 'data/map/streets.json', tolerance: 0.5 },
      cta: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      live: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      residents: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      benches: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      rstops: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      safety: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
      mystop: { type: 'geojson', data: { type: 'FeatureCollection', features: [] } },
    },
    layers: [
      { id: 'water', type: 'background', paint: { 'background-color': t.water } },
      { id: 'land', type: 'fill', source: 'land', paint: { 'fill-color': t.land } },
      { id: 'city', type: 'fill', source: 'areas', paint: { 'fill-color': t.city } },
      { id: 'river', type: 'line', source: 'streets', filter: ['==', ['get', 'c'], 'RIV'], paint: { 'line-color': t.river, 'line-width': w(10, 1.5, 16, 14) } },
      { id: 'areas-line', type: 'line', source: 'areas', paint: { 'line-color': t.areaLine, 'line-width': 1, 'line-dasharray': [3, 2] } },
      { id: 'st-minor-case', type: 'line', source: 'streets', minzoom: 13, filter: ['in', ['get', 'c'], ['literal', ['4', '5', 'E', '7']]],
        paint: { 'line-color': t.casing, 'line-width': w(13, 1.6, 18, 16) } },
      { id: 'st-minor', type: 'line', source: 'streets', minzoom: 12, filter: ['in', ['get', 'c'], ['literal', ['4', '5', 'E', '7']]],
        paint: { 'line-color': t.s4, 'line-width': w(12, 0.4, 18, 13) } },
      { id: 'st-coll', type: 'line', source: 'streets', minzoom: 11, filter: ['==', ['get', 'c'], '3'], paint: { 'line-color': t.s3, 'line-width': w(11, 0.6, 18, 16) } },
      { id: 'st-art-case', type: 'line', source: 'streets', filter: ['==', ['get', 'c'], '2'], paint: { 'line-color': t.casing, 'line-width': w(10, 1.6, 18, 22) } },
      { id: 'st-art', type: 'line', source: 'streets', filter: ['==', ['get', 'c'], '2'], paint: { 'line-color': t.s2, 'line-width': w(10, 1, 18, 18) } },
      { id: 'st-ramp', type: 'line', source: 'streets', minzoom: 12, filter: ['==', ['get', 'c'], '9'], paint: { 'line-color': t.s9, 'line-width': w(12, 1, 18, 10) } },
      { id: 'st-exp', type: 'line', source: 'streets', filter: ['==', ['get', 'c'], '1'], paint: { 'line-color': t.s1, 'line-width': w(9, 1.6, 18, 26) } },
      { id: 'cta-bus', type: 'line', source: 'cta', filter: ['==', ['get', 'kind'], 'bus'], layout: { visibility: 'none' },
        paint: { 'line-color': t.bus, 'line-width': w(10, 0.6, 17, 3), 'line-opacity': 0.7 } },
      { id: 'cta-rail-case', type: 'line', source: 'cta', filter: ['==', ['get', 'kind'], 'rail'], paint: { 'line-color': '#ffffff', 'line-width': w(9, 3, 17, 10), 'line-opacity': 0.8 } },
      { id: 'cta-rail', type: 'line', source: 'cta', filter: ['==', ['get', 'kind'], 'rail'], paint: { 'line-color': ['get', 'color'], 'line-width': w(9, 2, 17, 7) } },
      { id: 'stations', type: 'circle', source: 'cta', filter: ['==', ['get', 'kind'], 'station'],
        paint: { 'circle-radius': w(10, 2, 17, 7), 'circle-color': '#ffffff', 'circle-stroke-color': '#222a36', 'circle-stroke-width': 1.5 } },
      // crash safety (W4): expressways grey (not CPD jurisdiction) and serious-crash sites by EB score
      { id: 'safety-expressway', type: 'line', source: 'streets', layout: { visibility: 'none' }, filter: ['in', ['get', 'c'], ['literal', ['1', '9']]],
        paint: { 'line-color': '#8a8f98', 'line-width': w(9, 2, 17, 14), 'line-opacity': 0.85 } },
      { id: 'safety', type: 'circle', source: 'safety', layout: { visibility: 'none' },
        paint: { 'circle-radius': ['interpolate', ['linear'], ['get', 'eb'], 0, 2, 2, 4, 6, 8, 15, 13],
          'circle-color': ['interpolate', ['linear'], ['get', 'eb'], 0, '#f3c26b', 2, '#e8802e', 5, '#d6342c', 10, '#7a0d2a'],
          'circle-opacity': 0.85, 'circle-stroke-color': ['case', ['get', 'top100'], '#111827', '#ffffff'], 'circle-stroke-width': ['case', ['get', 'top100'], 2, 0.6] } },
      { id: 'benches', type: 'circle', source: 'benches', minzoom: 12, paint: { 'circle-radius': w(12, 1.8, 18, 6), 'circle-color': ['get', 'color'], 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 0.8 } },
      { id: 'residents', type: 'circle', source: 'residents', paint: { 'circle-radius': w(10, 2, 17, 6), 'circle-color': ['get', 'color'], 'circle-opacity': t.resident,
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 0.6 } },
      { id: 'rstops', type: 'circle', source: 'rstops', minzoom: 11, paint: { 'circle-radius': w(11, 2.5, 17, 7), 'circle-color': '#ffffff',
        'circle-stroke-color': ['get', 'color'], 'circle-stroke-width': w(11, 1.2, 17, 3) } },
      { id: 'mystop', type: 'circle', source: 'mystop', paint: { 'circle-radius': w(10, 7, 17, 14), 'circle-color': '#111827', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 3 } },
      { id: 'live-follow', type: 'circle', source: 'live', filter: ['==', ['get', 'f'], 1], paint: { 'circle-radius': w(10, 13, 17, 26), 'circle-color': 'rgba(0,179,255,0.12)', 'circle-stroke-color': '#00b3ff', 'circle-stroke-width': 3 } },
      // vehicle icons, drawn on demand (styleimagemissing): a round pictogram below zoom 13, a badge
      // with the route or line and a direction arrow from zoom 13
      { id: 'live-arrow', type: 'symbol', source: 'live', minzoom: 13, filter: ['>=', ['get', 'brg'], 0],
        layout: { 'icon-image': ['get', 'arrow'], 'icon-rotate': ['get', 'brg'], 'icon-rotation-alignment': 'map', 'icon-offset': [0, -15],
          'icon-allow-overlap': true, 'icon-ignore-placement': true, 'icon-size': w(13, 0.8, 17, 1.1) } },
      { id: 'live', type: 'symbol', source: 'live', maxzoom: 13,
        layout: { 'icon-image': ['get', 'glyph'], 'icon-allow-overlap': true, 'icon-ignore-placement': true, 'symbol-sort-key': ['get', 'f'],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 9, 0.45, 11, 0.62, 13, 0.85] } },
      { id: 'live-badge', type: 'symbol', source: 'live', minzoom: 13,
        layout: { 'icon-image': ['get', 'badge'], 'icon-allow-overlap': true, 'icon-ignore-placement': true, 'symbol-sort-key': ['get', 'f'],
          'icon-size': w(13, 0.85, 17, 1.15) } },
    ],
  };
}

const LINE_NAME = { Red: 'Red', Blue: 'Blue', Brn: 'Brown', G: 'Green', Org: 'Orange', P: 'Purple', Pink: 'Pink', Y: 'Yellow' };
function lum(hex) { const n = parseInt(hex.slice(1), 16), c = [n >> 16, (n >> 8) & 255, n & 255].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }
/** Pictogram of a bus (side view) or a train (front view), fg colour, in a box of size u at (x, y). */
function pictogram(g, mode, x, y, u, fg, bg) {
  g.fillStyle = fg; g.strokeStyle = fg;
  const rr = (a, b, w, h, r) => { g.beginPath(); g.roundRect(a, b, w, h, r); g.fill(); };
  if (mode === 'train') {
    rr(x + u * 0.2, y + u * 0.08, u * 0.6, u * 0.72, u * 0.14);
    g.fillStyle = bg; rr(x + u * 0.29, y + u * 0.18, u * 0.42, u * 0.24, u * 0.05);
    g.beginPath(); g.arc(x + u * 0.35, y + u * 0.6, u * 0.055, 0, 7); g.arc(x + u * 0.65, y + u * 0.6, u * 0.055, 0, 7); g.fill();
    g.lineWidth = u * 0.07; g.beginPath(); g.moveTo(x + u * 0.3, y + u * 0.95); g.lineTo(x + u * 0.38, y + u * 0.8); g.moveTo(x + u * 0.7, y + u * 0.95); g.lineTo(x + u * 0.62, y + u * 0.8); g.stroke();
  } else {
    rr(x + u * 0.08, y + u * 0.2, u * 0.84, u * 0.56, u * 0.12);
    g.fillStyle = bg; for (let i = 0; i < 3; i++) rr(x + u * (0.16 + i * 0.22), y + u * 0.29, u * 0.17, u * 0.17, u * 0.03);
    g.fillStyle = fg; g.beginPath(); g.arc(x + u * 0.28, y + u * 0.8, u * 0.1, 0, 7); g.arc(x + u * 0.72, y + u * 0.8, u * 0.1, 0, 7); g.fill();
    g.fillStyle = bg; g.beginPath(); g.arc(x + u * 0.28, y + u * 0.8, u * 0.045, 0, 7); g.arc(x + u * 0.72, y + u * 0.8, u * 0.045, 0, 7); g.fill();
  }
}
/** Draw a vehicle image for an id "glyph|mode|color", "badge|mode|label|color" or "arrow|color". */
export function vehicleImage(id, R = 2) {
  const [kind, a, b, c] = id.split('|');
  const cv = document.createElement('canvas'), g = cv.getContext('2d');
  if (kind === 'arrow') {
    cv.width = cv.height = 14 * R; g.scale(R, R); g.fillStyle = a; g.strokeStyle = '#ffffff'; g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(7, 1); g.lineTo(13, 12); g.lineTo(7, 9); g.lineTo(1, 12); g.closePath(); g.fill(); g.stroke();
  } else if (kind === 'glyph') {
    const color = b, S = 26; cv.width = cv.height = S * R; g.scale(R, R);
    g.fillStyle = color; g.strokeStyle = '#ffffff'; g.lineWidth = 2.2;
    g.beginPath(); g.arc(S / 2, S / 2, S / 2 - 1.5, 0, 7); g.fill(); g.stroke();
    const fg = lum(color) > 0.45 ? '#111827' : '#ffffff';
    pictogram(g, a, S * 0.2, S * 0.2, S * 0.6, fg, color);
  } else {
    const mode = a, label = b, color = c, H = 24;
    g.font = '700 13px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    const tw = Math.ceil(g.measureText(label).width), W = H + tw + 10;
    cv.width = W * R; cv.height = H * R; g.scale(R, R);
    g.font = '700 13px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    g.fillStyle = color; g.strokeStyle = '#ffffff'; g.lineWidth = 2;
    g.beginPath(); g.roundRect(1, 1, W - 2, H - 2, mode === 'train' ? 6 : 11); g.fill(); g.stroke();
    const fg = lum(color) > 0.45 ? '#111827' : '#ffffff';
    pictogram(g, mode, 4, 4, H - 8, fg, color);
    g.fillStyle = fg; g.textBaseline = 'middle'; g.fillText(label, H - 1, H / 2 + 0.5);
  }
  return { width: cv.width, height: cv.height, data: new Uint8Array(g.getImageData(0, 0, cv.width, cv.height).data.buffer) };
}

export function createMap(el, { theme = 'real', originUtm, toLonLat, onReady } = {}) {
  maplibregl.setWorkerUrl(new URL('./maplibre-gl-worker.mjs', import.meta.url).href);
  let t = THEMES[theme] || THEMES.real;
  const map = new maplibregl.Map({ container: el, style: style(t), center: [-87.66, 41.86], zoom: 10.6, minZoom: 9, maxZoom: 18.5,
    attributionControl: false, dragRotate: false, pitchWithRotate: false });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-left');
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'Streets, areas: City of Chicago · CTA GTFS & Bus/Train Tracker · not affiliated with CTA · Benches: © OpenStreetMap contributors (ODbL), CTA' }), 'bottom-right');

  // HTML label overlay
  const labelEl = document.createElement('div'); labelEl.className = 'map-labels'; el.appendChild(labelEl);
  let labels = [];
  fetch('data/map/labels.json').then(r => r.json()).then(j => { labels = j.features; drawLabels(); }).catch(() => {});
  function drawLabels() {
    const z = map.getZoom(), b = map.getBounds(), out = [], used = [];
    const W = el.clientWidth, H = el.clientHeight;
    for (const f of labels) {
      const p = f.properties, [lon, lat] = f.geometry.coordinates;
      if (!b.contains([lon, lat])) continue;
      const isArea = p.c === 'area';
      if (isArea && z > 14.5) continue;
      if (!isArea && z < (p.c === '1' ? 11.5 : 13.2)) continue;
      const q = map.project([lon, lat]);
      if (q.x < 0 || q.y < 0 || q.x > W || q.y > H) continue;
      const wpx = p.n.length * (isArea ? 7.2 : 6.4) + 8;
      if (used.some(u => Math.abs(u[0] - q.x) < (u[2] + wpx) / 2 && Math.abs(u[1] - q.y) < 16)) continue;
      used.push([q.x, q.y, wpx]);
      let ang = isArea ? 0 : p.a; if (ang > 90) ang -= 180; if (ang < -90) ang += 180;
      out.push(`<span class="ml ${isArea ? 'area' : 'st c' + p.c}" style="transform:translate(${q.x.toFixed(0)}px,${q.y.toFixed(0)}px) translate(-50%,-50%) rotate(${(-ang).toFixed(0)}deg)">${esc(p.n)}</span>`);
      if (out.length > 160) break;
    }
    labelEl.innerHTML = out.join('');
  }
  map.on('move', drawLabels); map.on('resize', drawLabels);

  map.on('styleimagemissing', e => { if (!map.hasImage(e.id) && /^(glyph|badge|arrow)\|/.test(e.id)) map.addImage(e.id, vehicleImage(e.id), { pixelRatio: 2 }); });
  // popups
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: true, maxWidth: '280px', className: 'mpop' });
  const tip = (layer, html) => {
    map.on('click', layer, e => { const f = e.features[0]; popup.setLngLat(e.lngLat).setHTML(html(f.properties)).addTo(map); });
    map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
  };
  const vehicleClick = e => {
    const p = e.features[0].properties, isF = followed.has(p.id);
    const el = document.createElement('div');
    el.innerHTML = `<b>${p.mode === 'train' ? 'Train' : 'Bus'} · route ${esc(p.route)}</b><br>${esc(p.dest ? 'to ' + p.dest : '')}<br><span class="fine">Position reported ${esc(fmtClock(p.t))} Chicago time${p.dly === 'true' || p.dly === true ? ' · flagged delayed by CTA' : ''}</span><br>`;
    const b = document.createElement('button'); b.className = 'ghost small'; b.textContent = isF ? 'Stop following' : (followed.size >= 10 ? 'Following 10 already' : 'Follow');
    b.disabled = !isF && followed.size >= 10;
    b.onclick = () => { isF ? unfollow(p.id) : follow(p.id); popup.remove(); };
    el.appendChild(b);
    popup.setLngLat(e.lngLat).setDOMContent(el).addTo(map);
  };
  for (const id of ['live', 'live-badge']) {
    map.on('click', id, vehicleClick);
    map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
  }
  let onStop = () => {};
  map.on('click', 'rstops', e => { const p = e.features[0].properties; onStop(p.id); });
  map.on('mouseenter', 'rstops', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'rstops', () => { map.getCanvas().style.cursor = ''; });
  tip('stations', p => `<b>${esc(p.name)}</b><br><span class="fine">'L' station · scheduled (GTFS)</span>`);
  tip('residents', p => `<b>Synthetic resident</b><br>${esc(p.kind)}${p.mode ? ' · ' + esc(p.mode) : ''}<br><span class="fine">Simulated, not a real person</span>`);
  let safetyMeta = null;
  tip('safety', p => `<b>${esc(p.name || (p.type === 'intersection' ? 'Intersection' : 'Street segment'))}</b><br>
    Serious crashes 2018-2024: ${p.k} fatal (Vision Zero) + ${p.a} incapacitating; ${p.crashes} crashes of any severity<br>
    Empirical-Bayes score ${(+p.eb).toFixed(2)}${p.top100 === true || p.top100 === 'true' ? ' · top 100' : ''}<br>
    ${p.volume === true || p.volume === 'true' ? '' : '<b>Crash concentration</b>: no traffic count here, so this is not a rate per vehicle.<br>'}
    <span class="fine">${safetyMeta ? `Source: ${esc(safetyMeta.source)}. Data through ${esc(safetyMeta.data_through)} (downloaded ${esc(safetyMeta.downloaded)}; Vision Zero from ${esc(safetyMeta.vision_zero_starts)}). Method: ${esc(safetyMeta.method)}. Ranking test on 2025: ${safetyMeta.test.pass ? 'passed' : 'failed (empirical Bayes did not beat raw counts)'}.` : ''}</span>`);
  tip('safety-expressway', () => `<b>Expressway or ramp</b><br>Not CPD jurisdiction: not ranked in the crash layer.`);
  tip('benches', p => `<b>${esc(p.kind || 'Bench')}</b><br><span class="fine">Source: ${esc(p.source)}${p.note ? ' · ' + esc(p.note) : ''}</span>`);
  tip('cta-rail', p => `<b>${esc(p.name)}</b><br><span class="fine">CTA 'L' · scheduled (GTFS)</span>`);
  tip('cta-bus', p => `<b>Bus ${esc(p.route)} ${esc(p.name)}</b><br><span class="fine">Scheduled (GTFS)</span>`);

  let ready = false, ctaData = null;
  const lineColor = {};
  const ctaP = fetch('data/map/cta.json').then(r => r.json()).then(j => { ctaData = j; for (const f of j.features) if (f.properties.kind === 'rail') lineColor[f.properties.route] = f.properties.color; });
  map.on('load', async () => { await ctaP.catch(() => {}); if (ctaData) map.getSource('cta').setData(ctaData); ready = true; drawLabels(); onReady && onReady(); });

  function setTheme(name) {
    t = THEMES[name] || THEMES.real;
    if (!ready) { map.once('load', () => setTheme(name)); return; }
    const set = (id, prop, v) => { if (map.getLayer(id)) map.setPaintProperty(id, prop, v); };
    set('water', 'background-color', t.water); set('land', 'fill-color', t.land); set('city', 'fill-color', t.city);
    set('river', 'line-color', t.river); set('areas-line', 'line-color', t.areaLine);
    set('st-minor-case', 'line-color', t.casing); set('st-art-case', 'line-color', t.casing);
    set('st-minor', 'line-color', t.s4); set('st-coll', 'line-color', t.s3); set('st-art', 'line-color', t.s2);
    set('st-exp', 'line-color', t.s1); set('st-ramp', 'line-color', t.s9); set('cta-bus', 'line-color', t.bus);
    el.dataset.theme = name;
  }
  setTheme(theme);

  function setVisible(id, on) {
    const ids = { bus: ['cta-bus'], rail: ['cta-rail', 'cta-rail-case', 'stations'], live: ['live', 'live-badge', 'live-arrow', 'live-follow'], residents: ['residents'], safety: ['safety', 'safety-expressway'],
      streets: ['st-minor', 'st-minor-case', 'st-coll', 'st-art', 'st-art-case', 'st-exp', 'st-ramp'], areas: ['areas-line'], benches: ['benches'] }[id] || [id];
    const go = () => ids.forEach(l => map.getLayer(l) && map.setLayoutProperty(l, 'visibility', on ? 'visible' : 'none'));
    ready ? go() : map.once('load', go);
  }

  // ---- live vehicles: delayed-live playback of the observed polls along route shapes ----
  let snap = null, prepared = [], loadedMs = 0, routeShapes = null, routeFilter = null, onlyFollowed = false, speed = 1;
  const followed = new Map();                                  // vehicle id -> last computed info
  let onFollow = () => {};
  const shapesP = fetch('data/transit.json').then(r => r.json()).then(T => { routeShapes = Object.fromEntries(T.routes.map(r => [r.id, r.shapes])); }).catch(() => { routeShapes = {}; });
  async function setLive(s) {
    if (!s) return 0;
    await shapesP;
    snap = s; loadedMs = Date.now();
    prepared = (s.vehicles || []).map(v => {
      const track = v.track.map(q => [q[1], q[2]]), shapes = routeShapes[v.route] || [];
      const legs = []; for (let k = 0; k < track.length - 1; k++) legs.push(bestShape(shapes, track[k], track[k + 1]));
      const brg = []; for (let k = 0; k < track.length - 1; k++) { const dx = track[k + 1][0] - track[k][0], dz = track[k + 1][1] - track[k][1]; brg.push(Math.hypot(dx, dz) > 10 ? bearingDeg(dx, dz) : -1); }
      const label = v.mode === 'train' ? (LINE_NAME[v.route] || v.route) : v.route;
      return { v, track, legs, brg, label, times: v.track.map(q => Date.parse(q[0])) };
    });
    tick(Date.now(), true);
    return prepared.length;
  }
  function colorOf(v) { return v.mode === 'train' ? (lineColor[v.route] || '#c60c30') : (v.dly ? '#d6342c' : (t === THEMES.neon ? '#f5ff3b' : '#e8890b')); }
  let lastTick = 0;
  /** Recompute positions (at most ~8 times a second) and push them to the map. */
  function tick(nowMs, force = false) {
    if (!ready || !snap || (!force && nowMs - lastTick < 125)) return null;
    lastTick = nowMs;
    const polls = snap.poll_times_utc.map(x => Date.parse(x)), t0 = polls[0], t1 = polls[polls.length - 1];
    const stale = snapshotAge(snap.generated_utc, nowMs, 30).stale;
    const pb = !stale && t1 > t0 && speed > 0 ? playbackTime(t0, t1, loadedMs, nowMs, speed) : { t: t1, delayMs: nowMs - t1 };
    const feats = [];
    for (const p of prepared) {
      const v = p.v, f = followed.has(v.id);
      if (onlyFollowed && !f) continue;
      if (!f && routeFilter && !routeFilter.has(v.route)) continue;
      const [x, z] = trackPosition(p.times, p.track, p.legs, pb.t);
      const [lon, lat] = toLonLat(x, z);
      const color = colorOf(v);
      let k = 0; while (k < p.times.length - 2 && p.times[k + 1] <= pb.t) k++;
      let brg = p.brg.length ? p.brg[Math.min(k, p.brg.length - 1)] : -1;
      if (brg < 0) { const mv = p.brg.filter(b => b >= 0); brg = mv.length ? mv[mv.length - 1] : (v.hdg ? v.hdg : -1); }
      if (f) followed.set(v.id, { id: v.id, mode: v.mode, route: v.route, dest: v.dest, dly: v.dly, lon, lat, color, t: v.t_utc });
      feats.push({ type: 'Feature', properties: { id: v.id, mode: v.mode, route: v.route, dest: v.dest, t: v.t_utc, dly: v.dly, color, f: f ? 1 : 0, brg,
        glyph: `glyph|${v.mode}|${color}`, badge: `badge|${v.mode}|${p.label}|${color}`, arrow: `arrow|${color}` },
        geometry: { type: 'Point', coordinates: [lon, lat] } });
    }
    map.getSource('live').setData({ type: 'FeatureCollection', features: feats });
    if (followed.size) onFollow([...followed.values()]);
    return { speed, shown: feats.length, total: prepared.length, delayMin: pb.delayMs / 60000, windowMin: (t1 - t0) / 60000, playbackMs: pb.t, stale };
  }
  function follow(id) {
    if (followed.has(id) || followed.size >= 10) return followed.size < 10 || followed.has(id);
    followed.set(id, { id }); tick(Date.now(), true); onFollow([...followed.values()]); return true;
  }
  function unfollow(id) { followed.delete(id); tick(Date.now(), true); onFollow([...followed.values()]); }
  function setRouteFilter(set) { routeFilter = set && set.size ? set : null; tick(Date.now(), true); }
  function setOnlyFollowed(v) { onlyFollowed = v; tick(Date.now(), true); }
  function flyToVehicle(id) { const f = followed.get(id); if (f && f.lon) map.flyTo({ center: [f.lon, f.lat], zoom: Math.max(map.getZoom(), 15), speed: 1.4 }); }

  function setResidents(pos, state, N) {
    if (!ready) return;
    const feats = [];
    for (let i = 0; i < N; i++) {
      const s = state[i]; if (!s || s.kind === 'home') continue;
      const [lon, lat] = toLonLat(pos[i * 2], pos[i * 2 + 1]);
      feats.push({ type: 'Feature', properties: { kind: s.kind === 'trip' ? 'travelling' : s.kind, mode: s.kind === 'trip' ? s.mode : '',
        color: s.kind === 'trip' ? '#1d2735' : (ACT[s.kind] || '#9bb0c6') }, geometry: { type: 'Point', coordinates: [lon, lat] } });
    }
    map.getSource('residents').setData({ type: 'FeatureCollection', features: feats });
  }

  /** "Where's my bus?": draw a route's stops (lon/lat) and the chosen stop; fit the view to them. */
  function showRouteStops(stops, color, fit = true) {
    const go = () => {
      map.getSource('rstops').setData({ type: 'FeatureCollection', features: stops.map(st => ({ type: 'Feature', properties: { id: st.id, name: st.name, color },
        geometry: { type: 'Point', coordinates: [st.lon, st.lat] } })) });
      if (fit && stops.length) {
        const lo = stops.map(x => x.lon), la = stops.map(x => x.lat);
        map.fitBounds([[Math.min(...lo), Math.min(...la)], [Math.max(...lo), Math.max(...la)]], { padding: 60, maxZoom: 15, duration: 800 });
      }
    };
    ready ? go() : map.once('load', go);
  }
  function setMyStop(st) {
    const go = () => map.getSource('mystop').setData({ type: 'FeatureCollection', features: st ? [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [st.lon, st.lat] } }] : [] });
    ready ? go() : map.once('load', go);
  }
  function setSafety(fc, busOnly = false) {
    const go = () => { if (fc) { safetyMeta = fc.meta; map.getSource('safety').setData(fc); }
      map.setFilter('safety', busOnly ? ['==', ['get', 'bus'], true] : null); };
    ready ? go() : map.once('load', go);
  }
  function setBenches(fc) { const go = () => map.getSource('benches').setData(fc); ready ? go() : map.once('load', go); }

  return { map, setSafety, setTheme, setVisible, setLive, tick, showRouteStops, setMyStop, onStopClick: fn => { onStop = fn; }, liveVehicles: () => (snap ? snap.vehicles : []), liveSnapshot: () => snap,
    flyTo: (lon, lat, z = 15) => map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), z), speed: 1.4 }), follow, unfollow, flyToVehicle, setRouteFilter, setOnlyFollowed, setSpeed: v => { const now = Date.now(); if (snap && v > 0 && speed > 0) { const pl = snap.poll_times_utc.map(x => Date.parse(x)); const cur = playbackTime(pl[0], pl[pl.length - 1], loadedMs, now, speed).t; loadedMs = now - (cur - pl[0]) / v; } if (v > 0 && speed === 0) loadedMs = now; speed = v; tick(now, true); }, onFollowChange: fn => { onFollow = fn; },
    routes: () => Object.keys(lineColor), setResidents, setBenches, resize: () => map.resize(), drawLabels, originUtm };
}
