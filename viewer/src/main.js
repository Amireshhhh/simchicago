import * as THREE from 'three';
import { KINDS, sunPosition, clockLabel, utcMs, utmForward, parseFootprint, REL_METRICS } from './core.js';
import { createScene, sunVector } from './scene.js';
import { createCity } from './city.js';
import { createAgents, ACT_COLOR, MODE_COLOR } from './agents.js';
import { createIncidents, createFlows } from './overlays.js';
import { renderLab } from './lab.js';
import { createTransit } from './transit.js';

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem(k)); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; } };
const LAT = 41.8781, LON = -87.6298, UTC_OFFSET_H = -5;   // Chicago, CDT (daylight time runs to 1 Nov 2020)
const LABOR = ['employed', 'unemployed', 'not in labour force'];
const EDU = ['less than high school', 'high school', 'some college', "associate's", "bachelor's", 'graduate/professional'];
const INC = ['< $25k', '$25–50k', '$50–75k', '$75–100k', '$100–150k', '$150k+'];
const FIRST = ['Ana', 'Ben', 'Cleo', 'Dev', 'Elena', 'Femi', 'Gus', 'Hana', 'Ivo', 'June', 'Kofi', 'Lina', 'Marco', 'Nia', 'Omar', 'Pia', 'Quinn', 'Rosa', 'Sam', 'Tara', 'Uri', 'Vera', 'Wes', 'Xena', 'Yuki', 'Zane'];
const fmtInt = v => Math.round(v).toLocaleString('en-US');

// ------------------------------------------------------------------------------------------ load
const boot = (msg, frac) => { $('#bootmsg').textContent = msg; if (frac !== undefined) $('#bootbar').style.width = `${Math.round(frac * 100)}%`; };
async function loadData() {
  const res = await fetch('data/run.json');
  if (!res.ok) throw new Error(`HTTP ${res.status} loading data/run.json`);
  const total = Number(res.headers.get('content-length')) || 0;
  if (!res.body || !total) return res.json();
  const reader = res.body.getReader(); const chunks = []; let got = 0;
  for (;;) { const { done, value } = await reader.read(); if (done) break; chunks.push(value); got += value.length; boot(`Loading the city… ${(got / 1e6).toFixed(1)} MB`, 0.1 + 0.6 * got / total); }
  const buf = new Uint8Array(got); let o = 0; for (const c of chunks) { buf.set(c, o); o += c.length; }
  return JSON.parse(new TextDecoder().decode(buf));
}
let D;
try { boot('Loading the city…', 0.05); D = await loadData(); }
catch (e) { boot(`Could not load the simulation export (data/run.json): ${e.message}. Run "python -m simchi.cli demo" and serve viewer/dist.`); throw e; }

// ------------------------------------------------------------------------------------------ world
boot('Raising the skyline…', 0.75);
const S = createScene($('#gl'));
const { scene, camera, controls, renderer, composer } = S;
let quality = store('simchi-quality') || 'medium';
$('#quality').value = quality;
S.applyQuality(quality);
const city = createCity(scene, D);
let nBuildings = city.buildBuildings({ low: 9000, medium: 26000, high: 60000 }[quality]);
boot('Waking up the residents…', 0.88);
const agents = createAgents(scene, D);
const incidents = createIncidents(scene, D);
const flows = createFlows(scene, D);
const areaByNum = Object.fromEntries(D.areas.map(a => [a.num, a]));
const TOTAL = D.meta.n_days * 1440;
const radius = D.meta.config.safety.radius_m;

camera.position.set(9000, 15000, 21000);
controls.target.set(2500, 0, -2500);
controls.update();

// ------------------------------------------------------------------------------------------ state
let simT = Math.min(TOTAL - 1, 17 * 60 + 30), playing = false, speed = 10, selected = -1, selectedArea = null;
const opts = { trails: true, speed, night: 0 };
const scrub = $('#scrub'); scrub.max = TOTAL - 1;
const setTime = t => { simT = Math.max(0, Math.min(TOTAL - 1, t)); scrub.value = simT; };
setTime(simT);

// ------------------------------------------------------------------------------------------ labels
const labelsEl = $('#labels');
const areaLabels = D.areas.map(a => { const el = document.createElement('div'); el.className = 'lbl'; el.textContent = a.name; labelsEl.appendChild(el); return { el, x: a.c[0], z: a.c[1], y: 20 }; });
const lmLabels = D.landmarks.map(L => { const el = document.createElement('div'); el.className = 'lbl lm'; el.textContent = L.name; labelsEl.appendChild(el); return { el, x: L.pos[0], z: L.pos[1], y: L.h + 25, near: 9000 }; });
const incLabelPool = [];
const v3 = new THREE.Vector3();
function place(lab, maxDist) {
  v3.set(lab.x, lab.y, lab.z);
  const dist = camera.position.distanceTo(v3);
  v3.project(camera);
  const vis = v3.z < 1 && Math.abs(v3.x) < 1.05 && Math.abs(v3.y) < 1.05 && dist < maxDist;
  lab.el.style.display = vis ? '' : 'none';
  if (vis) lab.el.style.transform = `translate(${(v3.x + 1) / 2 * innerWidth}px, ${(1 - v3.y) / 2 * innerHeight}px) translate(-50%, -50%)`;
  return vis;
}
function updateLabels(live) {
  const show = $('#lyrLabels').checked;
  const camDist = camera.position.distanceTo(controls.target);
  // hide area names that collide on screen (larger areas first)
  const taken = [];
  for (const L of areaLabels) {
    if (!show || camDist > 42000) { L.el.style.display = 'none'; continue; }
    if (!place(L, 60000)) continue;
    const r = L.el.getBoundingClientRect();
    if (taken.some(q => !(r.right < q.left || r.left > q.right || r.bottom < q.top || r.top > q.bottom))) { L.el.style.display = 'none'; continue; }
    taken.push(r);
  }
  for (const L of lmLabels) place(L, L.near);
  while (incLabelPool.length < live.length) { const el = document.createElement('div'); el.className = 'lbl inc'; labelsEl.appendChild(el); incLabelPool.push({ el, x: 0, y: 0, z: 0 }); }
  incLabelPool.forEach((L, i) => {
    const inc = live[i];
    if (!inc || !$('#lyrIncidents').checked) { L.el.style.display = 'none'; return; }
    L.x = inc.pos[0]; L.z = inc.pos[1]; L.y = 60;
    L.el.className = `lbl inc ${inc.label}`;
    L.el.textContent = inc.label === 'observed' ? 'Recorded carjacking (CPD)' : 'Simulated incident';
    place(L, 40000);
  });
}

// ------------------------------------------------------------------------------------------ lenses
const ramp = (stops, f) => { const n = stops.length - 1, i = Math.min(n - 1, Math.floor(f * n)); return new THREE.Color(stops[i]).lerp(new THREE.Color(stops[i + 1]), f * n - i); };
function safetyByArea() {
  const day = Math.floor(simT / 1440), byArea = {}, w = {};
  D.agents.forEach((a, i) => { const s = D.safety[i][Math.min(day + 1, D.safety[i].length - 1)]; byArea[a.area] = (byArea[a.area] || 0) + s * a.weight; w[a.area] = (w[a.area] || 0) + a.weight; });
  for (const k in byArea) byArea[k] /= w[k];
  return byArea;
}
const LENSES = {
  none: null,
  income: { label: 'Median household income, ACS 2015–19', prov: 'observed', v: a => a.stats.median_income, stops: ['#1a2b45', '#3f7aa8', '#bfe6ff'], fmt: v => '$' + fmtInt(v) },
  transit: { label: 'Commuters using transit, ACS 2015–19', prov: 'observed', v: a => a.stats.transit_share, stops: ['#1a2b45', '#2f8f9d', '#b6f2e3'], fmt: v => (v * 100).toFixed(0) + '%' },
  commute: { label: 'Mean commute time, ACS 2015–19', prov: 'observed', v: a => a.stats.mean_commute_min, stops: ['#1a2b45', '#8a5bd6', '#ffb6f0'], fmt: v => v.toFixed(0) + ' min' },
  jobs: { label: 'Jobs per km², LEHD', prov: 'observed', v: a => Math.log10(1 + a.stats.jobs / a.stats.area_km2), stops: ['#1a2b45', '#d08a2e', '#fff0b0'], fmt: v => fmtInt(10 ** v - 1) },
  safety: { label: 'Mean perceived safety of residents (simulated, hypothesis)', prov: 'simulated', v: a => safetyByArea()[a.num] ?? null, stops: ['#ff4d6d', '#ffbe55', '#7fe0a8'], fmt: v => v.toFixed(3) },
  incidents: { label: 'Recorded carjackings in the simulated week (CPD)', prov: 'observed', v: a => D.incidents.filter(i => i.label === 'observed' && i.area === a.num).length, stops: ['#1a2b45', '#5fd4ff', '#ffffff'], fmt: v => v + ' records' },
};
let lens = 'none', lensDay = -1;
function applyLens() {
  const L = LENSES[lens];
  if (!L) { city.areaFill.forEach(f => { f.material.opacity = 0; }); legend(); return; }
  const vals = D.areas.map(a => L.v(a)).filter(v => v !== null && Number.isFinite(v));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  for (const a of D.areas) {
    const v = L.v(a), f = city.areaFill.get(a.num);
    if (v === null || !Number.isFinite(v)) { f.material.opacity = 0; continue; }
    f.material.color.copy(ramp(L.stops, (v - lo) / (hi - lo || 1)));
    f.material.opacity = 0.62;
  }
  legend(lo, hi);
}
function legend(lo, hi) {
  const L = LENSES[lens];
  let h = '';
  for (const [k, c] of [['work', ACT_COLOR.work], ['school', ACT_COLOR.school], ['shop', ACT_COLOR.shop], ['social', ACT_COLOR.social], ['leisure', ACT_COLOR.leisure], ['errand', ACT_COLOR.errand]]) h += `<div class="row"><span class="sw" style="background:${c};color:${c}"></span>${k === 'social' ? 'Visiting friends' : k[0].toUpperCase() + k.slice(1)}</div>`;
  h += `<div class="row"><span class="sw" style="background:${MODE_COLOR.car};color:${MODE_COLOR.car}"></span>Driving <span class="sw" style="background:${MODE_COLOR.transit};color:${MODE_COLOR.transit};margin-left:8px"></span>Transit <span class="sw" style="background:${MODE_COLOR.walk};color:${MODE_COLOR.walk};margin-left:8px"></span>Walking</div>`;
  h += `<div class="row"><span class="sw ring" style="color:#5fd4ff"></span>Recorded incident (observed)</div><div class="row"><span class="sw ring" style="color:#ff7eb6"></span>Simulated incident</div>`;
  if (L) h += `<div style="margin-top:8px">${esc(L.label)} <span class="tag ${L.prov}">${L.prov}</span></div><div class="ramp" style="background:linear-gradient(90deg,${L.stops.join(',')})"></div><div class="ramp-labels"><span>${L.fmt(lo)}</span><span>${L.fmt(hi)}</span></div>`;
  h += `<div class="note">${fmtInt(D.meta.n_persons)} synthetic residents stand for ${fmtInt(D.meta.represented_population)} people. People at home are indoors and not drawn. Buildings are procedural unless you load real footprints.</div>`;
  $('#legend').innerHTML = `<button class="ghost small" id="legendToggle" aria-expanded="${!legendCollapsed}">Legend</button>${legendCollapsed ? '' : `<div style="margin-top:8px">${h}</div>`}`;
  $('#legendToggle').onclick = () => { legendCollapsed = !legendCollapsed; store('simchi-legend-collapsed', legendCollapsed); legend(lastLo, lastHi); };
  lastLo = lo; lastHi = hi;
}
let legendCollapsed = store('simchi-legend-collapsed') ?? false, lastLo, lastHi;
$('#lens').onchange = e => { lens = e.target.value; lensDay = -1; applyLens(); };

// ------------------------------------------------------------------------------------------ ribbon
const daysEl = $('#ribbonDays'), ticksEl = $('#ribbonTicks');
for (let d = 0; d < D.meta.n_days; d++) { const el = document.createElement('div'); el.style.left = `${d / D.meta.n_days * 100}%`; el.textContent = clockLabel(D.meta.start_date, d * 1440).split(',')[0]; daysEl.appendChild(el); }
for (const inc of D.incidents) { const el = document.createElement('i'); el.className = inc.label; el.style.left = `${inc.t / TOTAL * 100}%`; el.title = inc.label === 'observed' ? 'Recorded carjacking (CPD)' : 'Simulated incident'; ticksEl.appendChild(el); }
function drawRibbon() {
  const cv = $('#ribbonSky'), w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w * devicePixelRatio; cv.height = h * devicePixelRatio;
  const ctx = cv.getContext('2d');
  for (let x = 0; x < cv.width; x++) {
    const t = x / cv.width * TOTAL;
    const el = sunPosition(utcMs(D.meta.start_date, t, UTC_OFFSET_H), LAT, LON).elevation;
    const day = THREE.MathUtils.smoothstep(el, -0.12, 0.2), dusk = Math.exp(-((el - 0.02) ** 2) / 0.01);
    const c = new THREE.Color('#0a1530').lerp(new THREE.Color('#3f74b8'), day).lerp(new THREE.Color('#e08a5a'), dusk * 0.55);
    ctx.fillStyle = `#${c.getHexString()}`; ctx.fillRect(x, 0, 1, cv.height);
  }
}
drawRibbon(); addEventListener('resize', drawRibbon);
scrub.oninput = () => { simT = +scrub.value; };

// ------------------------------------------------------------------------------------------ inspector
const nameOf = i => `${FIRST[i % FIRST.length]} ${String.fromCharCode(65 + (i * 7) % 26)}.`;
const evByPid = new Map();
for (const e of D.events) { if (!evByPid.has(e.pid)) evByPid.set(e.pid, []); evByPid.get(e.pid).push(e); }
function gantt(i, day) {
  const segs = agents.segs[i].filter(s => s[1] > day * 1440 && s[0] < (day + 1) * 1440);
  return `<div class="gantt">${segs.map(s => { const k = KINDS[s[2]]; const a = Math.max(s[0], day * 1440) - day * 1440, b = Math.min(s[1], (day + 1) * 1440) - day * 1440;
    const c = k === 'trip' ? MODE_COLOR[['', 'walk', 'car', 'transit', 'other'][s[7]]] : ACT_COLOR[k];
    return `<i style="left:${a / 14.4}%;width:${(b - a) / 14.4}%;background:${c};opacity:${k === 'home' ? 0.25 : 0.9}" title="${k}"></i>`; }).join('')}</div>
    <div class="gantt-axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>`;
}
function spark(values, color) {
  const W = 380, H = 60, lo = Math.min(...values) - 1e-4, hi = Math.max(...values) + 1e-4;
  const pts = values.map((v, k) => `${k / (values.length - 1) * W},${H - (v - lo) / (hi - lo) * (H - 8) - 4}`).join(' ');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2"/></svg><div class="gantt-axis"><span>${lo.toFixed(4)}</span><span>${hi.toFixed(4)}</span></div>`;
}
function renderAgent(i) {
  const a = D.agents[i], st = agents.state[i], day = Math.floor(simT / 1440);
  const ev = (evByPid.get(a.pid) || []).slice(-12).reverse();
  $('#inspectorBody').innerHTML = `<h2>${nameOf(i)} <span class="tag simulated">synthetic</span></h2>
    <p>${a.age}-year-old ${esc(a.role)} in ${esc(areaByNum[a.area].name)}; ${a.labor >= 0 ? LABOR[a.labor] : 'under 16'}${a.wfh ? ', works from home' : ''}${a.student ? ', in school' : ''}.</p>
    <p class="fine">Now: <b>${esc(st.kind === 'trip' ? `travelling by ${st.mode}` : st.kind)}</b></p>
    <h3>Today</h3>${gantt(i, day)}
    <h3>Profile</h3><dl class="kv">
      <dt>Household</dt><dd>${a.hh_size} people, income ${INC[a.income_bin]}</dd>
      <dt>Vehicles</dt><dd>${a.vehicles}</dd><dt>Tenure</dt><dd>${a.tenure === 0 ? 'owner' : 'renter'}</dd>
      <dt>Education</dt><dd>${a.edu >= 0 ? EDU[a.edu] : '–'}</dd>
      <dt>Commute</dt><dd>${a.commuter ? `${a.mode} to ${a.work_area === 78 ? 'outside Chicago' : esc(areaByNum[a.work_area]?.name)}` : '–'}</dd>
      <dt>Represents</dt><dd>${fmtInt(a.weight)} residents</dd></dl>
    <h3>Perceived safety <span class="tag hypothesis">hypothesis</span></h3>${spark(D.safety[i], '#ffbe55')}
    <h3>History</h3><ul class="history">${ev.length ? ev.map(e => `<li>Day ${e.day + 1}: ${esc(e.kind === 'exposure' ? `within ${Math.round(e.distance_m)} m of a ${e.incident_label === 'observed' ? 'recorded' : 'simulated'} incident` : e.kind === 'cancelled' ? `cancelled ${e.activity}` : e.kind === 'aftercare' ? 'aftercare after school' : e.kind)}</li>`).join('') : '<li>No notable events.</li>'}</ul>`;
}
function renderArea(num) {
  const a = areaByNum[num], s = a.stats;
  const residents = D.agents.filter(x => x.area === num);
  $('#inspectorBody').innerHTML = `<h2>${esc(a.name)}</h2><p class="fine">${esc(a.district)} · community area ${num} · <span class="tag observed">ACS / LEHD</span></p>
    <dl class="kv"><dt>Population</dt><dd>${fmtInt(s.population)}</dd><dt>Households</dt><dd>${fmtInt(s.households)}</dd><dt>Jobs located here</dt><dd>${fmtInt(s.jobs)}</dd>
    <dt>Median income</dt><dd>$${fmtInt(s.median_income)}</dd><dt>Commute by car / transit / walk</dt><dd>${(s.car_share * 100).toFixed(0)}% / ${(s.transit_share * 100).toFixed(0)}% / ${(s.walk_share * 100).toFixed(0)}%</dd>
    <dt>Mean commute</dt><dd>${s.mean_commute_min.toFixed(1)} min</dd><dt>Households without a car</dt><dd>${(s.no_vehicle_share * 100).toFixed(0)}%</dd><dt>Work from home</dt><dd>${(s.wfh_share * 100).toFixed(1)}%</dd></dl>
    <h3>Synthetic residents</h3><p>${residents.length} agents live here, standing for ${fmtInt(residents.reduce((t, x) => t + x.weight, 0))} people.</p>`;
}
function openInspector() { $('#inspector').classList.remove('hidden'); $('#timelines').classList.add('hidden'); $('#timelinesBtn').setAttribute('aria-expanded', 'false'); }
$('#closeInspector').onclick = () => { $('#inspector').classList.add('hidden'); selected = -1; selectedArea = null; agents.select(-1); };

// ------------------------------------------------------------------------------------------ timelines
function renderTimelines() {
  const runs = { 'This run': D.daily, ...Object.fromEntries(Object.entries(D.compare || {}).map(([k, v]) => [k, v.daily])) };
  const cols = ['#ffffff', '#5fd4ff', '#ffbe55', '#ff7eb6', '#7fe0a8'];
  const metrics = [['mean_evening_out_min', 'Minutes out after 18:00 per resident'], ['mean_out_of_home_min', 'Minutes out of home per resident'], ['mean_perceived_safety', 'Mean perceived safety (hypothesis)'], ['activities_cancelled', 'Evening activities cancelled (agents)'], ['agents_exposed', 'Agents within the exposure radius']];
  let h = `<h2>Alternate timelines</h2><p class="fine">Same residents and random numbers, different incident and response settings.</p><div>${Object.keys(runs).map((k, i) => `<span class="tag" style="color:${cols[i]};border-color:${cols[i]}">${esc(k)}</span>`).join('')}</div>`;
  for (const [m, label] of metrics) {
    const all = Object.values(runs).flat().map(d => d[m]);
    const lo = Math.min(...all), hi = Math.max(...all) + 1e-9, W = 380, H = 80;
    h += `<h3>${esc(label)}</h3><svg class="chart" viewBox="0 0 ${W} ${H}">`;
    Object.values(runs).forEach((d, i) => { h += `<polyline fill="none" stroke="${cols[i]}" stroke-width="${i ? 1.6 : 2.4}" opacity="${i ? 0.85 : 1}" points="${d.map((x, k) => `${k / Math.max(d.length - 1, 1) * W},${H - 6 - (x[m] - lo) / (hi - lo || 1) * (H - 12)}`).join(' ')}"/>`; });
    h += `</svg><div class="gantt-axis"><span>${(+lo).toFixed(m.includes('safety') ? 4 : 1)}</span><span>${(+hi).toFixed(m.includes('safety') ? 4 : 1)}</span></div>`;
  }
  $('#timelinesBody').innerHTML = h;
}
const toggleDrawer = (id, btn, render) => { const el = $(id), open = el.classList.toggle('hidden') === false; $(btn).setAttribute('aria-expanded', String(open)); if (open && render) render(); return open; };
$('#timelinesBtn').onclick = () => { if (toggleDrawer('#timelines', '#timelinesBtn', renderTimelines)) $('#inspector').classList.add('hidden'); };
$('#closeTimelines').onclick = () => { $('#timelines').classList.add('hidden'); $('#timelinesBtn').setAttribute('aria-expanded', 'false'); };
$('#labBtn').onclick = () => toggleDrawer('#lab', '#labBtn', () => renderLab($('#labBody'), D));
$('#closeLab').onclick = () => { $('#lab').classList.add('hidden'); $('#labBtn').setAttribute('aria-expanded', 'false'); };

// ------------------------------------------------------------------------------------------ picking
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
let downXY = null;
$('#gl').addEventListener('pointerdown', e => { downXY = [e.clientX, e.clientY]; });
$('#gl').addEventListener('pointerup', e => {
  if (!downXY || Math.hypot(e.clientX - downXY[0], e.clientY - downXY[1]) > 5) return;
  ndc.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  const i = agents.pick(ray, camera, ndc);
  if (i >= 0) { selected = i; selectedArea = null; openInspector(); renderAgent(i); return; }
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects([...city.areaFill.values()])[0];
  if (hit) { selectedArea = hit.object.userData.area; selected = -1; agents.select(-1); openInspector(); renderArea(selectedArea); }
});
$('#gl').addEventListener('pointermove', e => {
  const tip = $('#tip');
  ndc.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObjects([...city.areaFill.values()])[0];
  if (hit) { const a = areaByNum[hit.object.userData.area]; const L = LENSES[lens]; tip.innerHTML = `<b>${esc(a.name)}</b>${L ? `<br>${esc(L.fmt(L.v(a)))}` : ''}`; tip.style.left = `${e.clientX + 14}px`; tip.style.top = `${e.clientY + 14}px`; tip.style.opacity = 1; }
  else tip.style.opacity = 0;
});

// ------------------------------------------------------------------------------------------ controls
$('#play').onclick = () => { playing = !playing; $('#play').textContent = playing ? 'Pause' : 'Play'; };
document.querySelectorAll('.speeds button').forEach(b => b.onclick = () => { document.querySelectorAll('.speeds button').forEach(x => x.classList.remove('on')); b.classList.add('on'); speed = +b.dataset.speed; });
$('#quality').onchange = e => { quality = e.target.value; store('simchi-quality', quality); S.applyQuality(quality); nBuildings = city.buildBuildings({ low: 9000, medium: 26000, high: 60000 }[quality]); };
$('#lyrBuildings').onchange = e => { city.bldGroup.visible = e.target.checked; };
$('#lyrTrails').onchange = e => { opts.trails = e.target.checked; };
$('#lyrFlows').onchange = e => { flows.lines.visible = e.target.checked; };
$('#lyrIncidents').onchange = e => { incidents.group.visible = e.target.checked; };
$('#lyrRain').onchange = e => { S.rain.visible = e.target.checked; };
addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.code === 'Space') { e.preventDefault(); $('#play').click(); }
  if (e.code === 'ArrowRight') setTime(simT + (e.shiftKey ? 60 : 10));
  if (e.code === 'ArrowLeft') setTime(simT - (e.shiftKey ? 60 : 10));
  if (e.key === 'l') $('#labBtn').click();
});

// camera flights and the fly-through tour
let flight = null;
function flyTo(x, z, dist, tilt = 0.9, dur = 2600) {
  const from = { p: camera.position.clone(), t: controls.target.clone() };
  const to = { t: new THREE.Vector3(x, 0, z), p: new THREE.Vector3(x + dist * 0.45, dist * Math.sin(tilt), z + dist * Math.cos(tilt)) };
  flight = { from, to, t0: performance.now(), dur };
}
const TOUR = [['The Loop', 32, 2600, 0.6], ['Near North Side', 8, 3800, 0.75], ['Hyde Park', 41, 5200, 0.9], ['O\'Hare', 76, 9000, 1.0], ['The whole city', null, 42000, 1.05]];
let tourStep = -1, tourTimer = 0;
$('#tourBtn').onclick = () => { tourStep = 0; tourTimer = 0; toast('Fly-through: Esc or drag to stop'); };
addEventListener('keydown', e => { if (e.key === 'Escape') tourStep = -1; });
$('#gl').addEventListener('pointerdown', () => { tourStep = -1; flight = null; });

// Live CTA: real routes and stations (GTFS) and near-live vehicles from the published snapshot
let transit = null, transitLoading = false, lastPanel = 0;
async function toggleLive() {
  const btn = $('#liveBtn'), on = btn.getAttribute('aria-pressed') !== 'true';
  btn.setAttribute('aria-pressed', String(on));
  $('#livePanel').classList.toggle('hidden', !on);
  if (on && !transit && !transitLoading) {
    transitLoading = true;
    $('#livePanel').innerHTML = '<h3>Live CTA</h3>Loading the CTA network…';
    try {
      const r = await fetch('data/transit.json');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      transit = createTransit(scene, await r.json());
      transit.setBusVisible($('#lyrBusRoutes').checked);
    } catch (e) { $('#livePanel').innerHTML = `<h3>Live CTA</h3>Could not load the CTA network: ${esc(e.message)}`; }
    transitLoading = false;
  }
  if (transit) transit.group.visible = on;
}
$('#liveBtn').onclick = toggleLive;
$('#lyrBusRoutes').onchange = e => { if (transit) transit.setBusVisible(e.target.checked); };
let reliability, relNote = '';
async function applyReliability() {
  const metric = $('#relMetric').value;
  if (metric && $('#liveBtn').getAttribute('aria-pressed') !== 'true') await toggleLive();
  if (!transit) return;
  if (metric && reliability === undefined) {
    try { const r = await fetch('data/reliability.json', { cache: 'no-store' }); reliability = r.ok ? await r.json() : null; } catch { reliability = null; }
  }
  const n = transit.setReliability(metric ? reliability : null, metric);
  relNote = !metric ? '' : reliability ? `Reliability lens: ${REL_METRICS[metric].label}; ${n} routes with observed data (teal good, red poor). Observed from polled positions vs GTFS schedule; see reports/reliability.`
    : 'Reliability lens: no observed reliability data published yet (it is built from the polled history).';
  toast(relNote);
}
$('#relMetric').onchange = applyReliability;
function opsHtml(o) {
  if (!o) return '';
  const adv = o.holding.advice || [], A = o.anomalies || {};
  const n = k => (A[k] || []).length;
  return `<div class="ops"><b>Operations view</b> <span class="tag simulated">advisory</span>
    <div>${adv.length ? `Holding advice for ${adv.length} bunched vehicle${adv.length > 1 ? 's' : ''}: ` + adv.slice(0, 4).map(a => `${esc(a.vehicle.replace(/^bus:/, 'bus '))} (route ${esc(a.route)}) hold ${a.hold_min} min`).join('; ') : 'No bunched vehicles flagged for holding.'}</div>
    <div>Feed flags: ${n('jump')} position jumps, ${n('stuck')} stuck mid-route, ${n('off_route')} off route, ${n('outage')} route-directions with no vehicle while ≥3 scheduled.</div>
    <div class="fine">Holding rule failed its simulated test; flags were tested on constructed labels only (docs/EVALUATION.md).</div></div>`;
}
function renderLivePanel(st) {
  const el = $('#livePanel');
  if (!st || st.state === 'loading') { el.innerHTML = '<h3>Live CTA</h3>Loading the latest snapshot…'; return; }
  if (st.state === 'none') {
    el.innerHTML = '<h3>Live CTA</h3>No live snapshot is published yet. Routes and stations are from CTA GTFS.<div class="fine">Snapshots are taken server-side by a scheduled workflow; the browser never calls CTA.</div>';
    return;
  }
  const age = st.ageMin < 1 ? 'under a minute' : `${Math.round(st.ageMin)} min`;
  if (st.empty) {
    el.innerHTML = `<h3>Live CTA</h3>The latest snapshot (${age} old) has no vehicle positions. Routes and stations are from CTA GTFS.
      ${(st.notes || []).length ? `<div class="fine">Workflow notes: ${st.notes.map(esc).join('; ')}</div>` : ''}
      <div class="fine">Snapshots are taken server-side by a scheduled workflow; the browser never calls CTA.</div>`;
    return;
  }
  el.innerHTML = `<h3>Live CTA <span class="tag observed">observed</span></h3>
    ${fmtInt(st.bus)} buses and ${fmtInt(st.train)} trains, snapshot
    <span class="age ${st.stale ? 'stale' : ''}">${age} old${st.stale ? ' (stale: not animated)' : ''}</span>.
    ${st.replaying ? '<div>Replaying the last ~2 minutes of observed positions along route shapes (×10).</div>' : ''}
    ${opsHtml(transit && transit.ops)}
    <div class="fine">"Live" means near-live: GitHub runs the snapshot workflow at most every 5 minutes, and runs can be delayed or skipped. Positions may be missing, delayed or wrong. Data provided by Chicago Transit Authority; SimChicago is not affiliated with or endorsed by CTA.</div>`;
}

// real building footprints around the camera target (City of Chicago Building Footprints, syp8-uezg)
$('#footprintsBtn').onclick = async () => {
  const [x0, y0] = D.meta.origin_utm16n;
  const toLocal = (lo, la) => { const [E, N] = utmForward(lo, la, 16); return [E - x0, -(N - y0)]; };
  const c = controls.target, [lon0, lat0] = D.meta.origin_lonlat;
  const dLat = -c.z / 111320, dLon = c.x / (111320 * Math.cos(lat0 * Math.PI / 180));
  const lat = lat0 + dLat, lon = lon0 + dLon, h = 0.004;
  const url = `https://data.cityofchicago.org/resource/syp8-uezg.json?$limit=3000&$where=within_box(the_geom,${lat + h},${lon - h * 1.35},${lat - h},${lon + h * 1.35})`;
  toast('Fetching real building footprints from data.cityofchicago.org…');
  try {
    const res = await fetch(url); if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    const n = city.addFootprints(rows.map(parseFootprint).filter(Boolean), toLocal);
    toast(`Loaded ${n} real footprints (heights from stories × 3.66 m).`);
  } catch (err) { toast(`Could not load footprints: ${esc(err.message)}`); }
};
function toast(html) { const t = document.createElement('div'); t.className = 'toast'; t.innerHTML = html; $('#toasts').appendChild(t); setTimeout(() => t.remove(), 4200); }

// ------------------------------------------------------------------------------------------ frame loop
const sunDir = new THREE.Vector3();
let last = performance.now(), lastInspect = -1, lastDay = -1;
function counters(c, live) {
  const day = Math.floor(simT / 1440), d = D.daily[Math.min(day, D.daily.length - 1)];
  const todayObs = D.incidents.filter(i => i.label === 'observed' && Math.floor(i.t / 1440) === day).length;
  $('#counters').innerHTML = [
    [fmtInt(c.out), 'out and about'], [fmtInt(c.travelling), 'travelling'], [fmtInt(c.home), 'at home'],
    [todayObs, 'recorded incidents today', live.some(i => i.label === 'observed')], [d.agents_exposed, 'agents exposed today'],
  ].map(([v, l, alert]) => `<div class="counter ${alert ? 'alert' : ''}"><b>${v}</b><span>${l}</span></div>`).join('');
  if (day !== lastDay) {
    lastDay = day;
    $('#dayStats').innerHTML = `<span>Evening out <b>${d.mean_evening_out_min.toFixed(1)} min</b></span><span>Cancelled <b>${d.activities_cancelled}</b></span><span>Safety <b>${d.mean_perceived_safety.toFixed(4)}</b></span>`;
  }
}
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  if (playing) { simT += speed * dt; if (simT >= TOTAL - 1) { simT = TOTAL - 1; playing = false; $('#play').textContent = 'Play'; } scrub.value = simT; }
  if (flight) {
    const f = Math.min(1, (now - flight.t0) / flight.dur), e = f < 0.5 ? 4 * f * f * f : 1 - (-2 * f + 2) ** 3 / 2;
    camera.position.lerpVectors(flight.from.p, flight.to.p, e); controls.target.lerpVectors(flight.from.t, flight.to.t, e);
    if (f >= 1) flight = null;
  } else if (tourStep >= 0) {
    tourTimer -= dt;
    if (tourTimer <= 0) {
      const [name, num, dist, tilt] = TOUR[tourStep];
      const p = num ? areaByNum[num].c : [2500, -2500];
      flyTo(p[0], p[1], dist, tilt, 3400); toast(name); tourTimer = 6.5;
      tourStep = (tourStep + 1) % TOUR.length;
    }
  }
  controls.update();
  const camDist = camera.position.distanceTo(controls.target);

  const sp = sunPosition(utcMs(D.meta.start_date, simT, UTC_OFFSET_H), LAT, LON);
  sunVector(sp.elevation, sp.azimuth, sunDir);
  const light = S.setSun(sunDir, S.rain.visible);
  city.uniforms.night.value = light.night;
  city.outlineMat.opacity = 0.22 + 0.25 * light.night;
  city.uniforms.time.value = now / 1000;
  opts.night = light.night; opts.speed = speed;
  const c = agents.update(simT, camDist, opts);
  const live = incidents.update(simT, camDist, radius);
  flows.update(now / 1000);
  S.updateRain(dt);
  if (transit && transit.group.visible) {
    const st = transit.update(Date.now());
    if (now - lastPanel > 1000) { lastPanel = now; renderLivePanel(st); }
  }
  if (selected >= 0) { agents.select(selected, camDist); if (Math.abs(simT - lastInspect) > 5) { lastInspect = simT; renderAgent(selected); } }
  if (lens === 'safety' && Math.floor(simT / 1440) !== lensDay) { lensDay = Math.floor(simT / 1440); applyLens(); }
  $('#clock').textContent = clockLabel(D.meta.start_date, simT);
  $('#playhead').style.left = `${simT / TOTAL * 100}%`;
  counters(c, live);
  updateLabels(live);
  composer.render();
  requestAnimationFrame(frame);
}
legend();
boot('Ready', 1);
$('#boot').classList.add('gone');
window.__simchi = { D, agents, city, S, setTime: t => setTime(t), flyTo, nBuildings: () => nBuildings, get simT() { return simT; } };
requestAnimationFrame(frame);
