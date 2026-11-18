// 2D map mode: a light, Google-Maps-like view built with MapLibre GL from self-hosted City of
// Chicago data (no third-party tiles, no keys). Layers: streets by class, community areas, CTA
// network, near-live vehicles (observed), simulated residents (simulated), benches (observed,
// mixed sources). Labels are an HTML overlay (no glyph server needed).
import * as maplibregl from 'maplibre-gl';

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
      { id: 'benches', type: 'circle', source: 'benches', minzoom: 12, paint: { 'circle-radius': w(12, 1.8, 18, 6), 'circle-color': ['get', 'color'], 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 0.8 } },
      { id: 'residents', type: 'circle', source: 'residents', paint: { 'circle-radius': w(10, 2, 17, 6), 'circle-color': ['get', 'color'], 'circle-opacity': t.resident,
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 0.6 } },
      { id: 'live-halo', type: 'circle', source: 'live', paint: { 'circle-radius': w(10, 6, 17, 16), 'circle-color': ['get', 'color'], 'circle-opacity': 0.22 } },
      { id: 'live', type: 'circle', source: 'live', paint: { 'circle-radius': ['interpolate', ['exponential', 1.6], ['zoom'], 10, ['case', ['==', ['get', 'mode'], 'train'], 4.5, 3], 17, ['case', ['==', ['get', 'mode'], 'train'], 9, 7]],
        'circle-color': ['get', 'color'], 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.4 } },
    ],
  };
}

export function createMap(el, { theme = 'real', originUtm, toLonLat, onReady } = {}) {
  maplibregl.setWorkerUrl(new URL('./maplibre-gl-worker.mjs', import.meta.url).href);
  let t = THEMES[theme] || THEMES.real;
  const map = new maplibregl.Map({ container: el, style: style(t), center: [-87.66, 41.86], zoom: 10.6, minZoom: 9, maxZoom: 18.5,
    attributionControl: false, dragRotate: false, pitchWithRotate: false });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-left');
  map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: 'Streets, areas: City of Chicago · CTA GTFS & Bus/Train Tracker · not affiliated with CTA' }), 'bottom-right');

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

  // popups
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: true, maxWidth: '280px', className: 'mpop' });
  const tip = (layer, html) => {
    map.on('click', layer, e => { const f = e.features[0]; popup.setLngLat(e.lngLat).setHTML(html(f.properties)).addTo(map); });
    map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
  };
  tip('live', p => `<b>${p.mode === 'train' ? 'Train' : 'Bus'} · route ${esc(p.route)}</b><br>${esc(p.dest ? 'to ' + p.dest : '')}<br><span class="fine">Observed ${esc(p.t)}${p.dly === 'true' || p.dly === true ? ' · flagged delayed by CTA' : ''}</span>`);
  tip('stations', p => `<b>${esc(p.name)}</b><br><span class="fine">'L' station · scheduled (GTFS)</span>`);
  tip('residents', p => `<b>Synthetic resident</b><br>${esc(p.kind)}${p.mode ? ' · ' + esc(p.mode) : ''}<br><span class="fine">Simulated, not a real person</span>`);
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
    const ids = { bus: ['cta-bus'], rail: ['cta-rail', 'cta-rail-case', 'stations'], live: ['live', 'live-halo'], residents: ['residents'],
      streets: ['st-minor', 'st-minor-case', 'st-coll', 'st-art', 'st-art-case', 'st-exp', 'st-ramp'], areas: ['areas-line'], benches: ['benches'] }[id] || [id];
    const go = () => ids.forEach(l => map.getLayer(l) && map.setLayoutProperty(l, 'visibility', on ? 'visible' : 'none'));
    ready ? go() : map.once('load', go);
  }

  function setLive(snap) {
    if (!snap) return 0;
    const feats = (snap.vehicles || []).map(v => {
      const [lon, lat] = v.lon !== undefined ? [v.lon, v.lat] : toLonLat(v.x, v.z);
      const color = v.mode === 'train' ? (lineColor[v.route] || '#c60c30') : (v.dly ? '#d6342c' : (t === THEMES.neon ? '#f5ff3b' : '#e8890b'));
      return { type: 'Feature', properties: { mode: v.mode, route: v.route, dest: v.dest, t: v.t_utc, dly: v.dly, color },
        geometry: { type: 'Point', coordinates: [lon, lat] } };
    });
    const go = () => map.getSource('live').setData({ type: 'FeatureCollection', features: feats });
    ready ? go() : map.once('load', go);
    return feats.length;
  }

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

  function setBenches(fc) { const go = () => map.getSource('benches').setData(fc); ready ? go() : map.once('load', go); }

  return { map, setTheme, setVisible, setLive, setResidents, setBenches, resize: () => map.resize(), drawLabels, originUtm };
}
