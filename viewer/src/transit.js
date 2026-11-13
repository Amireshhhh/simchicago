// Real CTA network (GTFS) and near-live vehicles (published snapshots; the browser never calls CTA).
import * as THREE from 'three';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { alongShape, bestShape, snapshotAge, relColor } from './core.js';

export const STALE_MIN = 30;           // snapshots older than this are shown as stale and not animated
const REPLAY_SECONDS = 12;             // the observed window (about 2 min) is replayed in this many seconds
const REFRESH_MS = 60000;

function segmentsOf(shapes, y) {
  const pos = [];
  for (const sh of shapes) for (let i = 0; i < sh.length - 1; i++) pos.push(sh[i][0], y, sh[i][1], sh[i + 1][0], y, sh[i + 1][1]);
  return pos;
}

export function createTransit(scene, T) {
  const group = new THREE.Group(); scene.add(group);
  const routes = Object.fromEntries(T.routes.map(r => [r.id, r]));
  const res = new THREE.Vector2(innerWidth, innerHeight);

  // bus routes: thin and subtle; rail lines: thick, in CTA line colours, with a glow underlay
  const busPos = segmentsOf(T.routes.filter(r => r.type === 3).flatMap(r => r.shapes), 1.2);
  const busGeo = new LineSegmentsGeometry().setPositions(busPos);
  const busMat = new LineMaterial({ color: 0x9fb4cc, linewidth: 1.1, transparent: true, opacity: 0.32, depthWrite: false, resolution: res });
  const busLines = new LineSegments2(busGeo, busMat); busLines.renderOrder = 3; group.add(busLines);

  // reliability lens: bus routes coloured by an observed metric (data/reliability.json)
  let relLines = null;
  function setReliability(rel, metric) {
    if (relLines) { group.remove(relLines); relLines.geometry.dispose(); relLines.material.dispose(); relLines = null; }
    busLines.visible = busVisible && !(rel && metric);
    if (!rel || !metric) return 0;
    const pos = [], col = [];
    let n = 0;
    for (const r of T.routes.filter(x => x.type === 3)) {
      const m = rel.routes[r.id], c = m ? relColor(metric, m[metric]) : null;
      if (!c) continue;
      n++;
      const p = segmentsOf(r.shapes, 1.6);
      pos.push(...p);
      for (let i = 0; i < p.length / 3; i++) col.push(...c);
    }
    if (!n) return 0;
    const g = new LineSegmentsGeometry().setPositions(pos);
    g.setColors(col);
    const mat = new LineMaterial({ vertexColors: true, linewidth: 2.4, transparent: true, opacity: 0.9, depthWrite: false, resolution: res });
    relLines = new LineSegments2(g, mat); relLines.renderOrder = 4; group.add(relLines);
    return n;
  }
  let busVisible = true;

  const railMats = [], flowMats = [], flowObjs = [];
  for (const r of T.routes.filter(x => x.type === 1)) {
    const g = new LineSegmentsGeometry().setPositions(segmentsOf(r.shapes, 2.5));
    for (const [w, op] of [[9, 0.18], [3.2, 1]]) {
      const m = new LineMaterial({ color: new THREE.Color(r.color), linewidth: w, transparent: true, opacity: op, depthWrite: false,
        blending: w > 5 ? THREE.AdditiveBlending : THREE.NormalBlending, resolution: res });
      railMats.push(m);
      const l = new LineSegments2(g, m); l.renderOrder = w > 5 ? 3 : 4; group.add(l);
    }
    // travelling light pulses along each line (decorative motion; not vehicle positions)
    const fm = new LineMaterial({ color: new THREE.Color(r.color).lerp(new THREE.Color('#ffffff'), 0.55), linewidth: 4.2, transparent: true,
      opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending, dashed: true, dashSize: 260, gapSize: 2200, resolution: res });
    const fl = new LineSegments2(g, fm); fl.computeLineDistances(); fl.renderOrder = 5; group.add(fl);
    flowMats.push(fm); flowObjs.push(fl);
  }
  addEventListener('resize', () => { res.set(innerWidth, innerHeight); });
  /** Advance the decorative pulses (seconds since start). */
  function animate(t) { for (const m of flowMats) m.dashOffset = -t * 900; }
  /** Vehicles per route in the current snapshot. */
  function stats() {
    const by = {};
    for (const v of (snap?.vehicles || [])) by[v.route] = (by[v.route] || 0) + 1;
    return { by, routes, notes: snap?.notes || [], generated: snap?.generated_utc, n: (snap?.vehicles || []).length };
  }

  // stations
  const stGeo = new THREE.CylinderGeometry(1, 1, 1, 20).translate(0, 0.5, 0);
  const stMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.45, roughness: 0.4 });
  const stations = new THREE.InstancedMesh(stGeo, stMat, T.stations.length);
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), S = new THREE.Vector3(), P = new THREE.Vector3();
  T.stations.forEach((s, i) => { M.compose(P.set(s.x, 0, s.z), Q, S.set(30, 5, 30)); stations.setMatrixAt(i, M); });
  group.add(stations);

  // live vehicles: screen-space glowing markers at the last observed position (sized in pixels so
  // they stay visible at city scale); trains in their line colour, buses amber (red when CTA flags
  // them delayed). Nothing moves unless the optional replay of the run's ~2 observed minutes is on.
  const vMat = new THREE.ShaderMaterial({
    uniforms: { t: { value: 0 }, pr: { value: Math.min(devicePixelRatio, 2) }, dim: { value: 1 } },
    vertexShader: `attribute float size; attribute vec3 color; varying vec3 vC; uniform float pr;
      void main(){ vC = color; vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv; gl_PointSize = size * pr; }`,
    fragmentShader: `varying vec3 vC; uniform float t; uniform float dim;
      void main(){ vec2 q = gl_PointCoord * 2.0 - 1.0; float r = length(q); if (r > 1.0) discard;
        float core = smoothstep(0.42, 0.30, r); float ring = smoothstep(0.62, 0.55, r) * smoothstep(0.48, 0.55, r);
        float halo = (1.0 - r) * 0.38 * (0.75 + 0.25 * sin(t * 2.4));
        vec3 c = mix(vC, vec3(1.0), core * 0.55) * dim; float a = max(core, max(ring, halo));
        gl_FragColor = vec4(c * (core + ring + halo * 1.2), a); }`,
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending });
  const vGeo = new THREE.BufferGeometry();
  const vPts = new THREE.Points(vGeo, vMat); vPts.frustumCulled = false; vPts.renderOrder = 9; group.add(vPts);
  let snap = null, prepared = [], status = { state: 'loading' }, ops = null, replay = false, showBuses = true;
  const BUS = new THREE.Color('#ffb547'), BUS_DLY = new THREE.Color('#ff4d6d');
  function setBusColor(hex) { BUS.set(hex); if (snap) prepare(snap); }

  function prepare(s) {
    prepared = s.vehicles.map(v => {
      const shapes = routes[v.route] ? routes[v.route].shapes : [];
      const track = v.track.map(t => [t[1], t[2]]);
      const legs = [];
      for (let k = 0; k < track.length - 1; k++) legs.push(bestShape(shapes, track[k], track[k + 1]));
      const color = v.mode === 'train' && routes[v.route] ? new THREE.Color(routes[v.route].color) : (v.dly ? BUS_DLY : BUS);
      return { v, track, legs, color };
    });
    const n = prepared.length;
    vGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    vGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    vGeo.setAttribute('size', new THREE.BufferAttribute(new Float32Array(n), 1));
    prepared.forEach((p, i) => { p.color.toArray(vGeo.attributes.color.array, i * 3); });
    vGeo.attributes.color.needsUpdate = true;
  }

  async function refresh() {
    try {
      const r = await fetch(`live/latest.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!r.ok) { status = { state: 'none' }; return; }
      const s = await r.json();
      if (s.schema !== 'simchi.live/1') { status = { state: 'none' }; return; }
      if (!snap || s.generated_utc !== snap.generated_utc) {
        snap = s; prepare(s); ops = null;
        try { const o = await fetch(`live/ops.json?t=${Date.now()}`, { cache: 'no-store' }); if (o.ok) { const j = await o.json(); if (j.generated_from === s.generated_utc) ops = j; } } catch { ops = null; }
      }
    } catch (e) { status = { state: 'none' }; return; }
    status = { state: 'ok' };
  }

  /** Place vehicles at their last observed position (or, with replay on, replay the run's observed
   *  window along route shapes). Stale snapshots are dimmed. */
  function update(nowMs) {
    if (!snap) return status;
    vMat.uniforms.t.value = nowMs / 1000;
    const age = snapshotAge(snap.generated_utc, nowMs, STALE_MIN);
    vMat.uniforms.dim.value = age.stale ? 0.45 : 1;
    const polls = snap.poll_times_utc.map(t => Date.parse(t));
    const t0 = polls[0], t1 = polls[polls.length - 1];
    const moving = replay && !age.stale && t1 > t0;
    const tRep = moving ? t0 + ((nowMs / 1000) % REPLAY_SECONDS) / REPLAY_SECONDS * (t1 - t0) : t1;
    const pos = vGeo.attributes.position?.array, size = vGeo.attributes.size?.array;
    let nb = 0, nt = 0;
    prepared.forEach((p, i) => {
      const tr = p.v.track, track = p.track;
      let x = track[track.length - 1][0], z = track[track.length - 1][1];
      if (moving && track.length > 1) {
        const times = tr.map(q => Date.parse(q[0]));
        let k = 0;
        while (k < times.length - 2 && times[k + 1] <= tRep) k++;
        if (tRep < times[0]) { x = track[0][0]; z = track[0][1]; }
        else { const f = times[k + 1] > times[k] ? (tRep - times[k]) / (times[k + 1] - times[k]) : 1; [x, z] = alongShape(p.legs[k], track[k], track[k + 1], f); }
      }
      const bus = p.v.mode === 'bus';
      pos[i * 3] = x; pos[i * 3 + 1] = bus ? 8 : 14; pos[i * 3 + 2] = z;
      size[i] = bus ? (showBuses ? 9 : 0) : 17;
      if (bus) nb++; else nt++;
    });
    if (pos) { vGeo.attributes.position.needsUpdate = true; vGeo.attributes.size.needsUpdate = true; }
    return { state: 'ok', ageMin: age.ageMin, stale: age.stale, bus: nb, train: nt, generated: snap.generated_utc,
             empty: !(snap.vehicles || []).length, requests: snap.requests, notes: snap.notes || [], replaying: moving };
  }

  refresh();
  setInterval(refresh, REFRESH_MS);
  return { group, update, refresh, animate, stats, setReliability, setReplay: v => { replay = v; }, setBusColor, setPulses: v => { flowObjs.forEach(o => { o.visible = v; }); }, setBusMarkers: v => { showBuses = v; }, setBusVisible: v => { busVisible = v; busLines.visible = v && !relLines; if (relLines) relLines.visible = v; }, get status() { return status; }, get ops() { return ops; } };
}
