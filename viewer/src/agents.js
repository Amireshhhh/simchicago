// Agents: glowing points (coloured by activity), motion trails, close-up meshes.
import * as THREE from 'three';
import * as BufferGeometryUtils from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { KINDS, MODES, segmentIndex } from './core.js';

export const ACT_COLOR = { home: '#9bb0c6', work: '#6c9dff', school: '#8fd0ff', aftercare: '#8fd0ff', shop: '#ffbe55', social: '#ff7eb6', leisure: '#7fe0a8', errand: '#e3cf7a', wait: '#9bb0c6' };
export const MODE_COLOR = { walk: '#f2f6fb', car: '#ffcf6b', transit: '#5fd4ff', other: '#b5f0c8' };
const TRAIL_MIN = 5;   // trail length in simulated minutes

export function createAgents(scene, D) {
  const N = D.agents.length;
  const segs = D.agents.map(a => D.segments[a.pid] || [[0, D.meta.n_days * 1440, 0, ...a.home, ...a.home, 0]]);
  const lastIdx = new Int32Array(N);
  const pos = new Float32Array(N * 2), state = new Array(N);
  const tmpColor = new THREE.Color();

  // glow points: additive soft discs; size in metres, clamped to a pixel range
  const g = new THREE.BufferGeometry();
  const pAttr = new THREE.BufferAttribute(new Float32Array(N * 3), 3).setUsage(THREE.DynamicDrawUsage);
  const cAttr = new THREE.BufferAttribute(new Float32Array(N * 3), 3).setUsage(THREE.DynamicDrawUsage);
  const sAttr = new THREE.BufferAttribute(new Float32Array(N), 1).setUsage(THREE.DynamicDrawUsage);
  g.setAttribute('position', pAttr); g.setAttribute('color', cAttr); g.setAttribute('size', sAttr);
  const pointMat = new THREE.ShaderMaterial({
    uniforms: { scale: { value: 1 }, glow: { value: 1 } },
    transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending, vertexColors: true,   // glows show through buildings (residents at work are indoors)
    vertexShader: `attribute float size; uniform float scale; varying vec3 vC; varying float vA;
      void main(){ vC = color; vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv;
        float px = size * scale / max(-mv.z, 1.0); gl_PointSize = clamp(px, 4.2, 26.0) * (size > 0.0 ? 1.0 : 0.0); vA = clamp(px / 5.0, 0.75, 1.0); }`,
    fragmentShader: `uniform float glow; varying vec3 vC; varying float vA;
      void main(){ float d = length(gl_PointCoord - 0.5) * 2.0; if (d > 1.0) discard;
        float core = smoothstep(0.45, 0.0, d), halo = pow(1.0 - d, 2.2);
        vec3 c = vC * (core * 1.6 + halo * 0.8 * glow);
        gl_FragColor = vec4(mix(c, vC * 1.15, step(glow, 0.68)), (core + halo * 0.6) * vA); }`,
  });
  const points = new THREE.Points(g, pointMat); points.frustumCulled = false; points.renderOrder = 6; scene.add(points);

  // trails: one fading segment per travelling agent, from its position TRAIL_MIN earlier
  const tg = new THREE.BufferGeometry();
  const tp = new THREE.BufferAttribute(new Float32Array(N * 6), 3).setUsage(THREE.DynamicDrawUsage);
  const tc = new THREE.BufferAttribute(new Float32Array(N * 8), 4).setUsage(THREE.DynamicDrawUsage);
  tg.setAttribute('position', tp); tg.setAttribute('color', tc);
  const trailMat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
  const trails = new THREE.LineSegments(tg, trailMat); trails.frustumCulled = false; trails.renderOrder = 5; scene.add(trails);

  // close-up meshes (people, cars, buses), shown when the camera is near the ground
  const person = BufferGeometryUtils.mergeGeometries([
    new THREE.CylinderGeometry(0.32, 0.38, 1.25, 8).translate(0, 0.62, 0), new THREE.SphereGeometry(0.28, 10, 8).translate(0, 1.5, 0)]);
  const carG = new THREE.BoxGeometry(1.9, 1.4, 4.4).translate(0, 0.7, 0);
  const busG = new THREE.BoxGeometry(2.6, 3.0, 12).translate(0, 1.5, 0);
  const mk = (geo, emissive) => { const m = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({ roughness: 0.5, emissive, emissiveIntensity: 0.6 }), N);
    m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.frustumCulled = false; m.count = 0; scene.add(m); return m; };
  const people = mk(person, 0x222222), cars = mk(carG, 0x664411), buses = mk(busG, 0x114466);
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), S = new THREE.Vector3(1, 1, 1), P = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);

  const sel = new THREE.Mesh(new THREE.RingGeometry(1, 1.25, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95, depthTest: false, side: THREE.DoubleSide }));
  sel.rotation.x = -Math.PI / 2; sel.visible = false; sel.renderOrder = 10; scene.add(sel);

  function locate(i, t, out) {
    const s = segs[i];
    let k = lastIdx[i];
    if (k >= s.length || s[k][0] > t || (k + 1 < s.length && s[k + 1][0] <= t)) k = segmentIndex(s, t);
    lastIdx[i] = k;
    const sg = s[k];
    const f = Math.min(1, Math.max(0, (t - sg[0]) / Math.max(sg[1] - sg[0], 1e-9)));
    out[0] = sg[3] + f * (sg[5] - sg[3]); out[1] = sg[4] + f * (sg[6] - sg[4]);
    return sg;
  }

  const tmp = [0, 0], tmp2 = [0, 0];
  let counts = { out: 0, travelling: 0, home: 0 };
  /** Update every agent for time t. camDist: camera distance to its target (m). */
  function update(t, camDist, options) {
    const close = camDist < 700;
    let nOut = 0, nTrav = 0, nHome = 0, nP = 0, nC = 0, nB = 0;
    const pa = pAttr.array, ca = cAttr.array, sa = sAttr.array, ta = tp.array, tca = tc.array;
    const base = THREE.MathUtils.clamp(camDist / 100, 8, 220);
    const ms = THREE.MathUtils.clamp(camDist / 140, 1, 5);   // close-up meshes: stylised scale-up
    S.set(ms, ms, ms);
    for (let i = 0; i < N; i++) {
      const sg = locate(i, t, tmp);
      pos[i * 2] = tmp[0]; pos[i * 2 + 1] = tmp[1];
      const kind = KINDS[sg[2]], mode = MODES[sg[7]];
      state[i] = { kind, mode, seg: sg };
      const atHome = kind === 'home';
      const trav = kind === 'trip';
      if (atHome) nHome++; else nOut++;
      if (trav) nTrav++;
      const y = trav ? (mode === 'transit' ? 3 : mode === 'car' ? 1.6 : 1.2) : 1.5;
      pa[i * 3] = tmp[0]; pa[i * 3 + 1] = y; pa[i * 3 + 2] = tmp[1];
      tmpColor.set(trav ? MODE_COLOR[mode] || '#ffffff' : ACT_COLOR[kind] || '#ffffff');
      ca[i * 3] = tmpColor.r; ca[i * 3 + 1] = tmpColor.g; ca[i * 3 + 2] = tmpColor.b;
      sa[i] = atHome ? 0 : (trav ? base * 1.15 : base);
      // trail
      if (trav && options.trails) {
        const s0 = Math.max(sg[0], t - Math.max(TRAIL_MIN, options.speed * 0.25));
        const f0 = Math.min(1, Math.max(0, (s0 - sg[0]) / Math.max(sg[1] - sg[0], 1e-9)));
        tmp2[0] = sg[3] + f0 * (sg[5] - sg[3]); tmp2[1] = sg[4] + f0 * (sg[6] - sg[4]);
        ta.set([tmp2[0], y, tmp2[1], tmp[0], y, tmp[1]], i * 6);
        tca.set([tmpColor.r, tmpColor.g, tmpColor.b, 0.0, tmpColor.r, tmpColor.g, tmpColor.b, 0.9], i * 8);
      } else {
        ta.fill(0, i * 6, i * 6 + 6);
      }
      if (close && !atHome) {
        const dx = sg[5] - sg[3], dz = sg[6] - sg[4];
        Q.setFromAxisAngle(up, Math.atan2(dx, dz));
        P.set(tmp[0], 0, tmp[1]);
        M.compose(P, Q, S);
        if (trav && mode === 'car') { cars.setMatrixAt(nC, M); cars.setColorAt(nC, tmpColor); nC++; }
        else if (trav && mode === 'transit') { buses.setMatrixAt(nB, M); buses.setColorAt(nB, tmpColor); nB++; }
        else { people.setMatrixAt(nP, M); people.setColorAt(nP, tmpColor); nP++; }
      }
    }
    pAttr.needsUpdate = cAttr.needsUpdate = sAttr.needsUpdate = true;
    tp.needsUpdate = tc.needsUpdate = true;
    trails.visible = options.trails;
    for (const [m, n] of [[people, nP], [cars, nC], [buses, nB]]) {
      m.count = n; m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true;
    }
    pointMat.uniforms.scale.value = innerHeight * 0.9;
    pointMat.uniforms.glow.value = options.night * 0.8 + 0.4;
    // additive glow reads well at night; by day (bright background) blend normally
    const blend = options.night > 0.35 ? THREE.AdditiveBlending : THREE.NormalBlending;
    if (pointMat.blending !== blend) { pointMat.blending = blend; trailMat.blending = blend; pointMat.needsUpdate = trailMat.needsUpdate = true; }
    counts = { out: nOut, travelling: nTrav, home: nHome };
    return counts;
  }

  function pick(raycaster, camera, ndc) {
    // nearest visible agent to the cursor in screen space (within 14 px)
    let best = -1, bestD = 14 * 14;
    const v = new THREE.Vector3();
    for (let i = 0; i < N; i++) {
      if (state[i] && state[i].kind === 'home') continue;
      v.set(pos[i * 2], 1.5, pos[i * 2 + 1]).project(camera);
      if (v.z > 1) continue;
      const dx = (v.x - ndc.x) * innerWidth / 2, dy = (v.y - ndc.y) * innerHeight / 2;
      const d = dx * dx + dy * dy;
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  }

  function select(i, camDist) {
    if (i < 0) { sel.visible = false; return; }
    sel.visible = true;
    const s = THREE.MathUtils.clamp(camDist / 60, 3, 160);
    sel.scale.set(s, s, s);
    sel.position.set(pos[i * 2], 2, pos[i * 2 + 1]);
  }

  return { N, segs, pos, state, update, pick, select, points, trails, get counts() { return counts; } };
}
