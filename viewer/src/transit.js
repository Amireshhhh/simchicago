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

  const railMats = [];
  for (const r of T.routes.filter(x => x.type === 1)) {
    const g = new LineSegmentsGeometry().setPositions(segmentsOf(r.shapes, 2.5));
    for (const [w, op] of [[9, 0.18], [3.2, 1]]) {
      const m = new LineMaterial({ color: new THREE.Color(r.color), linewidth: w, transparent: true, opacity: op, depthWrite: false,
        blending: w > 5 ? THREE.AdditiveBlending : THREE.NormalBlending, resolution: res });
      railMats.push(m);
      const l = new LineSegments2(g, m); l.renderOrder = w > 5 ? 3 : 4; group.add(l);
    }
  }
  addEventListener('resize', () => { res.set(innerWidth, innerHeight); });

  // stations
  const stGeo = new THREE.CylinderGeometry(1, 1, 1, 20).translate(0, 0.5, 0);
  const stMat = new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.45, roughness: 0.4 });
  const stations = new THREE.InstancedMesh(stGeo, stMat, T.stations.length);
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), S = new THREE.Vector3(), P = new THREE.Vector3();
  T.stations.forEach((s, i) => { M.compose(P.set(s.x, 0, s.z), Q, S.set(30, 5, 30)); stations.setMatrixAt(i, M); });
  group.add(stations);

  // live vehicles (instanced markers, one mesh per mode)
  const busGeoV = new THREE.BoxGeometry(40, 18, 90).translate(0, 9, 0);
  const trainGeoV = new THREE.BoxGeometry(46, 24, 190).translate(0, 12, 0);
  const mkV = (geo, n) => { const m = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({ roughness: 0.35, emissive: 0xffffff, emissiveIntensity: 0.55 }), n);
    m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.frustumCulled = false; m.count = 0; group.add(m); return m; };
  let busMesh = mkV(busGeoV, 1), trainMesh = mkV(trainGeoV, 1);
  let snap = null, prepared = [], status = { state: 'loading' }, ops = null;
  const up = new THREE.Vector3(0, 1, 0), C = new THREE.Color();

  function prepare(s) {
    prepared = s.vehicles.map(v => {
      const shapes = routes[v.route] ? routes[v.route].shapes : [];
      const track = v.track.map(t => [t[1], t[2]]);
      const legs = [];
      for (let k = 0; k < track.length - 1; k++) legs.push(bestShape(shapes, track[k], track[k + 1]));
      return { v, track, legs, color: v.mode === 'train' && routes[v.route] ? routes[v.route].color : (v.dly ? '#ff7a59' : '#e8f0fa') };
    });
    const nb = prepared.filter(p => p.v.mode === 'bus').length, nt = prepared.length - nb;
    group.remove(busMesh, trainMesh);
    busMesh = mkV(busGeoV, Math.max(1, nb)); trainMesh = mkV(trainGeoV, Math.max(1, nt));
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

  /** Place vehicles. Replays the observed window (between the run's polls) in a loop, moving
   *  along route shapes; stale snapshots are drawn at their last position without motion. */
  function update(nowMs) {
    if (!snap) return status;
    const age = snapshotAge(snap.generated_utc, nowMs, STALE_MIN);
    const polls = snap.poll_times_utc.map(t => Date.parse(t));
    const t0 = polls[0], t1 = polls[polls.length - 1];
    const live = !age.stale && t1 > t0;
    const tRep = live ? t0 + ((nowMs / 1000) % REPLAY_SECONDS) / REPLAY_SECONDS * (t1 - t0) : t1;
    let nb = 0, nt = 0;
    for (const p of prepared) {
      const tr = p.v.track, track = p.track;
      let x = track[track.length - 1][0], z = track[track.length - 1][1], hd = p.v.hdg;
      if (live && track.length > 1) {
        const times = tr.map(q => Date.parse(q[0]));
        let k = 0;
        while (k < times.length - 2 && times[k + 1] <= tRep) k++;
        if (tRep < times[0]) { x = track[0][0]; z = track[0][1]; }
        else {
          const f = times[k + 1] > times[k] ? (tRep - times[k]) / (times[k + 1] - times[k]) : 1;
          [x, z] = alongShape(p.legs[k], track[k], track[k + 1], f);
        }
      }
      Q.setFromAxisAngle(up, -hd * Math.PI / 180);
      M.compose(P.set(x, 0, z), Q, S.set(1, 1, 1));
      C.set(p.color).multiplyScalar(age.stale ? 0.35 : 1);
      if (p.v.mode === 'bus') { busMesh.setMatrixAt(nb, M); busMesh.setColorAt(nb, C); nb++; }
      else { trainMesh.setMatrixAt(nt, M); trainMesh.setColorAt(nt, C); nt++; }
    }
    for (const [m, n] of [[busMesh, nb], [trainMesh, nt]]) { m.count = n; m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; }
    return { state: 'ok', ageMin: age.ageMin, stale: age.stale, bus: nb, train: nt, generated: snap.generated_utc, notes: snap.notes || [], empty: !(snap.vehicles || []).length,
             requests: snap.requests, notes: snap.notes, replaying: live };
  }

  refresh();
  setInterval(refresh, REFRESH_MS);
  return { group, update, refresh, setReliability, setBusVisible: v => { busVisible = v; busLines.visible = v && !relLines; if (relLines) relLines.visible = v; }, get status() { return status; }, get ops() { return ops; } };
}
