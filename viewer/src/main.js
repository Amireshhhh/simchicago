import * as THREE from 'three';
import { MapControls } from 'three/examples/jsm/controls/MapControls.js';
import * as BufferGeometryUtils from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { KINDS, MODES, segmentIndex, positionAt, sunPosition, pointInRing, rng, parseFootprint, clockLabel, utcMs, utmForward } from './core.js';

const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = (k, v) => { try { if (v === undefined) return JSON.parse(localStorage.getItem(k)); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; } };
const LAT = 41.8781, LON = -87.6298, UTC_OFFSET_H = -5;   // Chicago, CDT (daylight time runs to 1 Nov 2020)
const ACT_COLOR = { work: '#5b8def', school: '#8fd0ff', aftercare: '#8fd0ff', shop: '#f3b13f', social: '#ff7eb6', leisure: '#7fd8a4', errand: '#d6c27a', wait: '#9bb0c6', home: '#9bb0c6' };
const MODE_COLOR = { walk: '#eaf1f8', car: '#ffcf6b', transit: '#6cc5ee', other: '#b5f0c8' };
const LABOR = ['employed', 'unemployed', 'not in labour force'];
const EDU = ['less than high school', 'high school', 'some college', "associate's", "bachelor's", 'graduate/professional'];
const INC = ['< $25k', '$25–50k', '$50–75k', '$75–100k', '$100–150k', '$150k+'];
const FIRST = ['Ana', 'Ben', 'Cleo', 'Dev', 'Elena', 'Femi', 'Gus', 'Hana', 'Ivo', 'June', 'Kofi', 'Lina', 'Marco', 'Nia', 'Omar', 'Pia', 'Quinn', 'Rosa', 'Sam', 'Tara', 'Uri', 'Vera', 'Wes', 'Xena', 'Yuki', 'Zane'];

const boot = msg => { $('#bootmsg').textContent = msg; };
let D;   // run data
try {
  const res = await fetch('data/run.json');
  if (!res.ok) throw new Error(`HTTP ${res.status} loading data/run.json`);
  D = await res.json();
} catch (e) {
  boot(`Could not load the simulation export (data/run.json): ${e.message}. Run "python -m simchi.cli export" and serve the viewer folder.`);
  throw e;
}

// --------------------------------------------------------------------------------------------
// renderer, scene, camera
const canvas = $('#gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance', logarithmicDepthBuffer: true });
renderer.setClearColor(0x0f2238);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, innerWidth / innerHeight, 2, 300000);
const controls = new MapControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.maxPolarAngle = Math.PI * 0.46;
controls.minDistance = 40; controls.maxDistance = 70000; controls.screenSpacePanning = false;
const QUALITY = { low: { pr: 1, bld: 9000, shadows: false }, medium: { pr: Math.min(devicePixelRatio, 1.5), bld: 26000, shadows: false }, high: { pr: Math.min(devicePixelRatio, 2), bld: 60000, shadows: true } };
let quality = store('simchi-quality') || 'medium';
$('#quality').value = quality;
function applyQuality() {
  const q = QUALITY[quality];
  renderer.setPixelRatio(q.pr); renderer.setSize(innerWidth, innerHeight);
  renderer.shadowMap.enabled = q.shadows; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  sun.castShadow = q.shadows;
}

// sky dome driven by the real solar elevation of the simulated time
const skyU = { sunDir: { value: new THREE.Vector3(0, 1, 0) }, day: { value: 1 }, dusk: { value: 0 } };
const sky = new THREE.Mesh(new THREE.SphereGeometry(1000, 32, 16), new THREE.ShaderMaterial({
  uniforms: skyU, side: THREE.BackSide, depthWrite: false, depthTest: false, fog: false,
  vertexShader: 'varying vec3 vD; void main(){ vD = normalize(position); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }',
  fragmentShader: `uniform vec3 sunDir; uniform float day; uniform float dusk; varying vec3 vD;
    void main(){ float h = clamp(vD.y, -0.1, 1.0);
      vec3 dayTop = vec3(.27,.52,.82), dayHor = vec3(.72,.84,.93), nightTop = vec3(.012,.025,.06), nightHor = vec3(.05,.09,.16);
      vec3 top = mix(nightTop, dayTop, day), hor = mix(nightHor, dayHor, day);
      vec3 c = mix(hor, top, smoothstep(0., .45, h));
      float sd = max(dot(normalize(vD), normalize(sunDir)), 0.);
      c += vec3(1., .55, .25) * dusk * pow(sd, 6.) * (1. - smoothstep(0., .35, h)) * .9;
      c += vec3(1., .95, .85) * pow(sd, 400.) * day * 2.;
      gl_FragColor = vec4(c, 1.); }`,
}));
sky.renderOrder = -1; sky.frustumCulled = false; scene.add(sky);
scene.fog = new THREE.Fog(0x0f2238, 30000, 140000);
const hemi = new THREE.HemisphereLight(0xbcd7ff, 0x2a2a22, 0.6); scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffffff, 2.2);
sun.shadow.mapSize.set(2048, 2048); sun.shadow.camera.near = 10; sun.shadow.camera.far = 20000;
Object.assign(sun.shadow.camera, { left: -2500, right: 2500, top: 2500, bottom: -2500 });
scene.add(sun, sun.target);
const ambient = new THREE.AmbientLight(0x324a6b, 0.25); scene.add(ambient);
applyQuality();

// --------------------------------------------------------------------------------------------
// ground: city land, outside land, Lake Michigan (outline approximated from the city's lakefront)
const toShape = ring => new THREE.Shape(ring.map(([x, z]) => new THREE.Vector2(x, -z)));
const flat = geo => { geo.rotateX(-Math.PI / 2); return geo; };
const outsideLand = new THREE.Mesh(new THREE.PlaneGeometry(400000, 400000), new THREE.MeshStandardMaterial({ color: 0x4d5a4a, roughness: 1 }));
outsideLand.rotation.x = -Math.PI / 2; outsideLand.position.y = -2; outsideLand.receiveShadow = true; scene.add(outsideLand);
const cityMat = new THREE.MeshStandardMaterial({ color: 0x6b7378, roughness: 0.95 });
const cityLand = new THREE.Mesh(flat(new THREE.ShapeGeometry(D.city_rings.map(toShape))), cityMat);
cityLand.position.y = -0.6; cityLand.receiveShadow = true; scene.add(cityLand);

// lake: polygon east of the eastern-most city boundary point in each 250 m band north of the
// Calumet area; beyond the city's north/south ends the shore is extended as straight lines.
// This is a visual approximation, not surveyed shoreline.
(function lake() {
  const pts = D.city_rings.flat();
  const zs = pts.map(p => p[1]); const zMin = Math.min(...zs), zMax = Math.max(...zs);
  const shore = [];
  for (let z = zMin; z <= zMax; z += 250) {
    let mx = -Infinity;
    for (const p of pts) if (Math.abs(p[1] - z) < 200 && p[0] > mx) mx = p[0];
    if (mx > -Infinity) shore.push([mx + 30, z]);
  }
  // keep the shoreline monotone-ish by removing inland notches (river/harbor mouths)
  const sm = shore.map((p, i) => { const w = shore.slice(Math.max(0, i - 3), i + 4).map(q => q[0]); return [Math.max(...w.slice(0)) , p[1]]; });
  const shoreN2S = sm.filter(p => p[1] < zMax - 9000);   // south of ~Calumet the boundary is the Indiana state line
  const north = shoreN2S[0], south = shoreN2S[shoreN2S.length - 1];
  // polygon: far north on the shore line -> down the shore -> east along the cut -> far east -> back north
  const ring = [[north[0], zMin - 60000], ...shoreN2S, [south[0], south[1] + 3000], [60000, south[1] + 3000], [60000, zMin - 60000]];
  const s = toShape(ring.map(([x, z]) => [x, z]));
  const lakeU = { t: { value: 0 }, day: { value: 1 } };
  const m = new THREE.Mesh(flat(new THREE.ShapeGeometry(s)), new THREE.MeshStandardMaterial({ color: 0x2c6e93, roughness: 0.25, metalness: 0.15 }));
  m.position.y = -0.3; m.userData.u = lakeU; scene.add(m); window.__lake = m;
})();

// community-area outlines and lens fills
const areaFill = new Map();
const outlineMat = new THREE.LineBasicMaterial({ color: 0x6cc5ee, transparent: true, opacity: 0.22 });
for (const a of D.areas) {
  const fill = new THREE.Mesh(flat(new THREE.ShapeGeometry(a.rings.map(toShape))), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false }));
  fill.position.y = -0.2; fill.userData.area = a.num; scene.add(fill); areaFill.set(a.num, fill);
  for (const r of a.rings) {
    const g = new THREE.BufferGeometry().setFromPoints(r.map(([x, z]) => new THREE.Vector3(x, 0.4, z)));
    scene.add(new THREE.Line(g, outlineMat));
  }
  // label anchor: centroid of the largest ring
  const big = a.rings.reduce((m, r) => r.length > m.length ? r : m, a.rings[0]);
  a.c = big.reduce((s, p) => [s[0] + p[0] / big.length, s[1] + p[1] / big.length], [0, 0]);
}
const areaByNum = Object.fromEntries(D.areas.map(a => [a.num, a]));

// --------------------------------------------------------------------------------------------
// buildings. Default: PROCEDURAL massing conditioned on each area's ACS housing-structure mix,
// year-built, CMAP land use and LEHD job density. These are not real buildings.
const winU = { night: { value: 0 } };
function buildingMaterial() {
  const m = new THREE.MeshStandardMaterial({ roughness: 0.82, metalness: 0.05 });
  m.onBeforeCompile = sh => {
    sh.uniforms.uNight = winU.night;
    sh.vertexShader = 'varying vec3 vWP; varying vec3 vWN;\n' + sh.vertexShader.replace('#include <worldpos_vertex>',
      `#include <worldpos_vertex>
       vec4 wp4 = vec4(transformed, 1.0);
       #ifdef USE_INSTANCING
         wp4 = instanceMatrix * wp4;
       #endif
       vWP = (modelMatrix * wp4).xyz; vWN = normalize(mat3(modelMatrix) * objectNormal);`);
    sh.fragmentShader = 'uniform float uNight; varying vec3 vWP; varying vec3 vWN;\nfloat h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }\n' +
      sh.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        if (uNight > 0.01 && vWP.y > 2.5) {
          float u = (vWP.x + vWP.z) / 3.2; float v = vWP.y / 3.4;
          vec2 cell = floor(vec2(u, v)); vec2 f = fract(vec2(u, v));
          float win = step(.25, f.x) * step(f.x, .75) * step(.3, f.y) * step(f.y, .78);
          float on = step(h21(cell + floor(vWP.xz / 40.)), .38);
          vec3 col = mix(vec3(1., .72, .38), vec3(.75, .88, 1.), step(.8, h21(cell * 1.3)));
          totalEmissiveRadiance += col * win * on * 1.4 * uNight * (1. - abs(vWN.y));
        }`);
  };
  return m;
}
const bldGroup = new THREE.Group(); scene.add(bldGroup);
let bldMesh = null, bldInfo = [];
function buildProcedural() {
  bldGroup.clear(); bldInfo = [];
  const target = QUALITY[quality].bld;
  const totalHU = D.areas.reduce((s, a) => s + a.stats.housing_units, 0);
  const totalJobs = D.areas.reduce((s, a) => s + a.stats.jobs, 0);
  const box = new THREE.BoxGeometry(1, 1, 1); box.translate(0, 0.5, 0);
  const mats = [];
  const cBrick = new THREE.Color('#8a5a44'), cStone = new THREE.Color('#b9b2a2'), cGlass = new THREE.Color('#6f8ea8'), cNew = new THREE.Color('#9aa6ae');
  for (const a of D.areas) {
    const r = rng(a.num * 7919 + 13);
    const share = 0.75 * a.stats.housing_units / totalHU + 0.25 * a.stats.jobs / totalJobs;
    const n = Math.max(20, Math.round(target * share));
    const jobDensity = a.stats.jobs / Math.max(a.stats.area_km2, 0.1);      // jobs per km2
    const towers = jobDensity > 20000 ? Math.round(a.stats.jobs / 2500) : 0;
    const mix = a.stats.hu_mix;
    const cum = [mix.single, mix.single + mix.small, mix.single + mix.small + mix.mid, 1];
    const older = Math.max(0, Math.min(1, (1990 - a.stats.med_year_built) / 70));
    const rings = a.rings;
    const xs = rings.flat().map(p => p[0]), zs = rings.flat().map(p => p[1]);
    const [x0, x1, z0, z1] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
    const inside = (x, z) => rings.some(rg => pointInRing(x, z, rg));
    let placed = 0, tries = 0;
    while (placed < n + towers && tries < (n + towers) * 30) {
      tries++;
      // Chicago's street grid: 8 blocks per mile N-S (201 m), 16 per mile E-W (100 m); keep 18 m streets clear
      let x = x0 + r() * (x1 - x0), z = z0 + r() * (z1 - z0);
      const bx = ((x % 201) + 201) % 201, bz = ((z % 100.6) + 100.6) % 100.6;
      if (bx < 18 || bz < 14) continue;
      if (!inside(x, z)) continue;
      if (r() < (a.stats.landuse.OPEN || 0) + (a.stats.landuse.VACANT || 0) * 0.5) continue;   // parks, open space, vacant land
      const tower = placed < towers;
      let w, d, h, col;
      if (tower) { w = 25 + r() * 35; d = 25 + r() * 35; h = 60 + Math.pow(r(), 1.6) * 220; col = (r() < 0.6 ? cGlass : cStone).clone(); }
      else {
        const u = r();
        if (u < cum[0]) { w = 7 + r() * 5; d = 12 + r() * 8; h = 5 + r() * 5; }
        else if (u < cum[1]) { w = 7 + r() * 4; d = 18 + r() * 10; h = 8 + r() * 5; }
        else if (u < cum[2]) { w = 14 + r() * 14; d = 20 + r() * 20; h = 11 + r() * 12; }
        else { w = 22 + r() * 25; d = 22 + r() * 25; h = 25 + Math.pow(r(), 2) * 110; }
        col = (r() < older ? cBrick : cNew).clone().lerp(cStone, r() * 0.35);
      }
      col.offsetHSL(0, 0, (r() - 0.5) * 0.08);
      mats.push({ x, z, w, d, h, col, area: a.num, tower });
      placed++;
    }
  }
  bldMesh = new THREE.InstancedMesh(box, buildingMaterial(), mats.length);
  const M = new THREE.Matrix4();
  mats.forEach((b, i) => { M.compose(new THREE.Vector3(b.x, 0, b.z), new THREE.Quaternion(), new THREE.Vector3(b.w, b.h, b.d)); bldMesh.setMatrixAt(i, M); bldMesh.setColorAt(i, b.col); });
  bldMesh.castShadow = bldMesh.receiveShadow = true;
  bldInfo = mats;
  bldGroup.add(bldMesh);
  // reference landmarks (Wikipedia heights and coordinates; schematic 48 m square footprints)
  const lmMat = buildingMaterial(); lmMat.color.set('#5d6f80'); lmMat.metalness = 0.4; lmMat.roughness = 0.4;
  for (const L of D.landmarks) {
    const m = new THREE.Mesh(box, lmMat); m.scale.set(48, L.h, 48); m.position.set(L.pos[0], 0, L.pos[1]); m.castShadow = true;
    bldGroup.add(m);
  }
}
buildProcedural();

// --------------------------------------------------------------------------------------------
// agents
const agents = D.agents;
const N = agents.length;
const segs = agents.map(a => D.segments[a.pid] || [[0, D.meta.n_days * 1440, 0, ...a.home, ...a.home, 0]]);
const person = BufferGeometryUtils.mergeGeometries([
  new THREE.CylinderGeometry(0.32, 0.38, 1.25, 8).translate(0, 0.62, 0),
  new THREE.SphereGeometry(0.28, 10, 8).translate(0, 1.5, 0)]);
const carG = new THREE.BoxGeometry(1.9, 1.4, 4.4).translate(0, 0.7, 0);
const busG = new THREE.BoxGeometry(2.6, 3.0, 12).translate(0, 1.5, 0);
const mkInst = (g, emissive) => { const m = new THREE.InstancedMesh(g, new THREE.MeshStandardMaterial({ roughness: 0.5, emissive, emissiveIntensity: 0.0 }), N);
  m.instanceMatrix.setUsage(THREE.DynamicDrawUsage); m.frustumCulled = false; scene.add(m); return m; };
const peopleMesh = mkInst(person, 0x3a3a3a), carMesh = mkInst(carG, 0xffe2a0), busMesh = mkInst(busG, 0x9fdcff);
const dotGeo = new THREE.BufferGeometry();
dotGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(N * 3), 3).setUsage(THREE.DynamicDrawUsage));
dotGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(N * 3), 3).setUsage(THREE.DynamicDrawUsage));
const dots = new THREE.Points(dotGeo, new THREE.PointsMaterial({ size: 4, sizeAttenuation: false, vertexColors: true, depthTest: false, transparent: true, opacity: 0.95 }));
dots.frustumCulled = false; dots.renderOrder = 5; scene.add(dots);
const ringSel = new THREE.Mesh(new THREE.RingGeometry(1.1, 1.4, 40), new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, transparent: true, opacity: 0.9, depthTest: false }));
ringSel.rotation.x = -Math.PI / 2; ringSel.visible = false; ringSel.renderOrder = 10; scene.add(ringSel);
const tmpM = new THREE.Matrix4(), tmpQ = new THREE.Quaternion(), tmpS = new THREE.Vector3(), tmpP = new THREE.Vector3(), tmpC = new THREE.Color();
const ZERO = new THREE.Matrix4().makeScale(0, 0, 0);
const agentPos = new Float32Array(N * 2), agentState = new Array(N);
let simT = 8 * 60 + 30, playing = false, speed = 10;   // minutes, sim-minutes per real second

function updateAgents(t) {
  const camDist = camera.position.distanceTo(controls.target);
  const k = Math.min(60, Math.max(1, camDist / 260));                 // keep people visible at city scale
  const out = [0, 0];
  let indoor = 0, moving = 0, outside = 0;
  for (let i = 0; i < N; i++) {
    const s = segs[i], j = segmentIndex(s, t), g = s[j];
    positionAt(s, t, out);
    agentPos[2 * i] = out[0]; agentPos[2 * i + 1] = out[1];
    const kind = KINDS[g[2]], mode = MODES[g[7]];
    agentState[i] = { kind, mode, seg: g };
    peopleMesh.setMatrixAt(i, ZERO); carMesh.setMatrixAt(i, ZERO); busMesh.setMatrixAt(i, ZERO);
    const dp = dotGeo.attributes.position.array, dc = dotGeo.attributes.color.array;
    if (kind === 'home') { indoor++; dp[3 * i + 1] = -1e6; continue; }
    dp[3 * i] = out[0]; dp[3 * i + 1] = 3; dp[3 * i + 2] = out[1];
    tmpC.set(kind === 'trip' ? MODE_COLOR[mode] || '#eaf1f8' : ACT_COLOR[kind] || '#ffffff'); dc[3 * i] = tmpC.r; dc[3 * i + 1] = tmpC.g; dc[3 * i + 2] = tmpC.b;
    const heading = Math.atan2(g[5] - g[3], g[6] - g[4]);
    tmpQ.setFromAxisAngle(THREE.Object3D.DEFAULT_UP, heading);
    if (kind === 'trip' && (mode === 'car' || mode === 'transit')) {
      moving++;
      const kk = Math.min(k, 18);
      tmpS.set(kk, kk, kk); tmpP.set(out[0], 0, out[1]); tmpM.compose(tmpP, tmpQ, tmpS);
      (mode === 'car' ? carMesh : busMesh).setMatrixAt(i, tmpM);
      (mode === 'car' ? carMesh : busMesh).setColorAt(i, tmpC.set(MODE_COLOR[mode]));
    } else {
      if (kind === 'trip') moving++; else outside++;
      const bob = kind === 'trip' ? Math.abs(Math.sin(t * 9 + i)) * 0.12 * k : 0;
      tmpS.set(k * 1.6, k * 1.6, k * 1.6); tmpP.set(out[0], bob, out[1]); tmpM.compose(tmpP, tmpQ, tmpS);
      peopleMesh.setMatrixAt(i, tmpM);
      peopleMesh.setColorAt(i, tmpC.set(kind === 'trip' ? MODE_COLOR[mode] || '#eaf1f8' : ACT_COLOR[kind] || '#ffffff'));
    }
  }
  dotGeo.attributes.position.needsUpdate = true; dotGeo.attributes.color.needsUpdate = true;
  dots.visible = camDist > 1800; dots.material.size = camDist > 12000 ? 3 : 4;
  for (const m of [peopleMesh, carMesh, busMesh]) { m.instanceMatrix.needsUpdate = true; if (m.instanceColor) m.instanceColor.needsUpdate = true; }
  if (selected != null) { ringSel.visible = true; ringSel.position.set(agentPos[2 * selected], 1, agentPos[2 * selected + 1]); ringSel.scale.setScalar(k * 2.2); }
  else ringSel.visible = false;
  return { indoor, moving, outside };
}

// --------------------------------------------------------------------------------------------
// incidents: observed (CPD records) vs simulated, always visibly distinct
const incGroup = new THREE.Group(); scene.add(incGroup);
const incObjs = D.incidents.map(inc => {
  const obs = inc.label === 'observed';
  const col = obs ? 0x6cc5ee : 0xe4002b;
  const g = new THREE.Group(); g.position.set(inc.pos[0], 0, inc.pos[1]);
  const pillar = new THREE.Mesh(new THREE.CylinderGeometry(6, 6, 600, 16, 1, true).translate(0, 300, 0),
    new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
  const ringGeo = new THREE.BufferGeometry().setFromPoints(Array.from({ length: 65 }, (_, k) => new THREE.Vector3(Math.cos(k / 64 * Math.PI * 2), 0, Math.sin(k / 64 * Math.PI * 2))));
  const ring = new THREE.Line(ringGeo, obs ? new THREE.LineBasicMaterial({ color: col, transparent: true }) : new THREE.LineDashedMaterial({ color: col, dashSize: 0.08, gapSize: 0.06, transparent: true }));
  if (!obs) ring.computeLineDistances();
  ring.position.y = 2;
  const radius = new THREE.Line(ringGeo, new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.35 }));
  radius.scale.setScalar(D.meta.config.safety.radius_m); radius.position.y = 1.5;
  g.add(pillar, ring, radius); g.visible = false; incGroup.add(g);
  const el = document.createElement('div'); el.className = `lbl ${inc.label}`;
  el.textContent = obs ? 'Recorded carjacking (CPD)' : 'Simulated carjacking';
  $('#labels').appendChild(el);
  return { inc, g, ring, pillar, radius, el, lines: null };
});
const exposuresByIncident = {};
for (const e of D.events) if (e.kind === 'exposure') (exposuresByIncident[e.incident_id] ||= []).push(e);
const WINDOW = 90; // minutes an incident stays on screen
function updateIncidents(t) {
  for (const o of incObjs) {
    const dt = t - o.inc.t, on = dt > -5 && dt < WINDOW;
    o.g.visible = on; o.el.style.display = 'none';
    if (!on) { if (o.lines) { scene.remove(o.lines); o.lines = null; } continue; }
    const f = dt < 0 ? 0.3 : 1 - dt / WINDOW;
    const pulse = (((t * 4) % 30) / 30);
    o.ring.scale.setScalar(20 + pulse * 220); o.ring.material.opacity = (1 - pulse) * f;
    o.pillar.material.opacity = 0.55 * f; o.radius.material.opacity = 0.35 * f;
    o.el.dataset.pos = `${o.inc.pos[0]},620,${o.inc.pos[1]}`; o.el.style.display = 'block'; o.el.style.opacity = 0.4 + 0.6 * f;
    const ex = exposuresByIncident[o.inc.id];
    if (ex && !o.lines && dt >= 0) {
      const pts = [];
      for (const e of ex) { const p = positionAt(segs[e.pid], o.inc.t); pts.push(new THREE.Vector3(o.inc.pos[0], 4, o.inc.pos[1]), new THREE.Vector3(p[0], 4, p[1])); }
      o.lines = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.7 }));
      scene.add(o.lines);
    }
    if (o.lines) o.lines.material.opacity = 0.7 * f;
  }
}

// --------------------------------------------------------------------------------------------
// labels (areas, landmarks, incidents)
const labelEls = [];
for (const a of D.areas) { const el = document.createElement('div'); el.className = 'lbl area'; el.textContent = a.name; el.dataset.pos = `${a.c[0]},0,${a.c[1]}`; $('#labels').appendChild(el); labelEls.push({ el, kind: 'area' }); }
for (const L of D.landmarks) { const el = document.createElement('div'); el.className = 'lbl landmark'; el.textContent = `${L.name} · ${L.h} m`; el.dataset.pos = `${L.pos[0]},${L.h + 10},${L.pos[1]}`; $('#labels').appendChild(el); labelEls.push({ el, kind: 'landmark' }); }
const _v = new THREE.Vector3();
function placeLabel(el) {
  const [x, y, z] = el.dataset.pos.split(',').map(Number);
  _v.set(x, y, z).project(camera);
  if (_v.z > 1 || Math.abs(_v.x) > 1.1 || Math.abs(_v.y) > 1.1) { el.style.visibility = 'hidden'; return; }
  el.style.visibility = 'visible';
  el.style.left = ((_v.x + 1) / 2 * innerWidth) + 'px'; el.style.top = ((1 - _v.y) / 2 * innerHeight) + 'px';
}
function updateLabels() {
  const dist = camera.position.distanceTo(controls.target);
  const taken = [];
  const free = el => { const r = { x: parseFloat(el.style.left), y: parseFloat(el.style.top), w: el.offsetWidth + 6, h: el.offsetHeight + 4 };
    if (taken.some(q => Math.abs(q.x - r.x) * 2 < q.w + r.w && Math.abs(q.y - r.y) * 2 < q.h + r.h)) return false; taken.push(r); return true; };
  for (const { el, kind } of labelEls.slice().sort((a, b) => (a.kind === 'landmark' ? -1 : 0) - (b.kind === 'landmark' ? -1 : 0))) {
    const show = kind === 'area' ? dist > 1500 && dist < 45000 : dist < 9000;
    if (!show) { el.style.visibility = 'hidden'; continue; }
    placeLabel(el);
    if (el.style.visibility === 'visible' && !free(el)) el.style.visibility = 'hidden';
  }
  for (const o of incObjs) if (o.el.style.display === 'block') placeLabel(o.el);
}

// --------------------------------------------------------------------------------------------
// lighting from the real solar position of the simulated clock
function updateSky(t) {
  const { elevation, azimuth } = sunPosition(utcMs(D.meta.start_date, t, UTC_OFFSET_H), LAT, LON);
  const dir = new THREE.Vector3(Math.sin(azimuth) * Math.cos(elevation), Math.sin(elevation), -Math.cos(azimuth) * Math.cos(elevation));
  const day = THREE.MathUtils.smoothstep(elevation, -0.12, 0.2);
  const dusk = Math.max(0, 1 - Math.abs(elevation - 0.02) / 0.22);
  skyU.sunDir.value.copy(dir); skyU.day.value = day; skyU.dusk.value = dusk;
  const tgt = controls.target;
  sun.position.copy(tgt).addScaledVector(dir.y > 0 ? dir : new THREE.Vector3(0.3, 1, 0.2).normalize(), 8000);
  sun.target.position.copy(tgt);
  sun.intensity = 0.15 + 2.4 * day;
  sun.color.set(day < 0.6 ? 0xffc48a : 0xffffff);
  if (dir.y <= 0) { sun.color.set(0x8fa8d8); sun.intensity = 0.45; }       // moonlight-ish fill
  hemi.intensity = 0.45 + 0.35 * day; ambient.intensity = 0.2 + 0.35 * (1 - day);
  renderer.toneMappingExposure = 0.75 + 0.35 * day;
  winU.night.value = 1 - day;
  scene.fog.color.setRGB(0.05 + 0.55 * day, 0.09 + 0.62 * day, 0.16 + 0.68 * day);
  window.__lake.material.color.setRGB(0.04 + 0.13 * day, 0.08 + 0.32 * day, 0.14 + 0.45 * day);
  peopleMesh.material.emissiveIntensity = 1.0 * (1 - day); carMesh.material.emissiveIntensity = 0.6 * (1 - day); busMesh.material.emissiveIntensity = 0.6 * (1 - day);
}

// --------------------------------------------------------------------------------------------
// hypothetical weather (no weather data is loaded in this build)
let rain = null;
function setRain(on) {
  if (rain) { scene.remove(rain); rain = null; }
  if (!on) return;
  const n = 14000, pos = new Float32Array(n * 3), r = rng(5);
  for (let i = 0; i < n; i++) { pos[3 * i] = (r() - 0.5) * 3000; pos[3 * i + 1] = r() * 900; pos[3 * i + 2] = (r() - 0.5) * 3000; }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  rain = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xaecbe8, size: 2.2, transparent: true, opacity: 0.55, depthWrite: false }));
  scene.add(rain);
}
$('#weatherBtn').onclick = e => { const on = e.currentTarget.getAttribute('aria-pressed') !== 'true'; e.currentTarget.setAttribute('aria-pressed', on); setRain(on); toast(on ? 'Rain on — a hypothetical visual; agents do not react to it' : 'Rain off'); };

// --------------------------------------------------------------------------------------------
// ground lenses
const ramp = (stops, t) => { t = Math.max(0, Math.min(1, t)); const c = stops.map(s => new THREE.Color(s)); const x = t * (c.length - 1), i = Math.min(c.length - 2, Math.floor(x)); return c[i].clone().lerp(c[i + 1], x - i); };
const safetyByArea = () => { const s = {}, w = {}; const d = Math.min(D.meta.n_days, Math.floor(simT / 1440)); for (const a of agents) { s[a.area] = (s[a.area] || 0) + a.weight * D.safety[a.pid][d]; w[a.area] = (w[a.area] || 0) + a.weight; } const o = {}; for (const k in s) o[k] = s[k] / w[k]; return o; };
const LENSES = {
  none: null,
  income: { label: 'Median household income, ACS 2015–19', prov: 'observed', v: a => a.stats.median_income, stops: ['#22324a', '#3f7aa8', '#bfe6ff'], fmt: v => '$' + Math.round(v).toLocaleString() },
  transit: { label: 'Share of commuters using transit, ACS 2015–19', prov: 'observed', v: a => a.stats.transit_share, stops: ['#22324a', '#2f8f9d', '#b6f2e3'], fmt: v => (v * 100).toFixed(0) + '%' },
  safety: { label: 'Mean perceived safety of residents (simulated, hypothesis)', prov: 'simulated', v: a => safetyByArea()[a.num] ?? null, stops: ['#e4002b', '#f3b13f', '#7fd8a4'], fmt: v => v.toFixed(3), fixed: [0.7, 0.8] },
  incidents: { label: 'Recorded carjackings in the simulated week (CPD)', prov: 'observed', v: a => D.incidents.filter(i => i.label === 'observed' && i.area === a.num).length, stops: ['#22324a', '#6cc5ee', '#ffffff'], fmt: v => v + ' records' },
};
let lens = 'none', lensDay = -1;
function applyLens() {
  const L = LENSES[lens];
  const legend = $('#legend');
  if (!L) {
    for (const f of areaFill.values()) f.material.opacity = 0;
    legend.innerHTML = legendBase(); return;
  }
  const vals = D.areas.map(a => L.v(a)).filter(v => v != null);
  const [lo, hi] = L.fixed || [Math.min(...vals), Math.max(...vals)];
  for (const a of D.areas) {
    const v = L.v(a), f = areaFill.get(a.num);
    if (v == null) { f.material.opacity = 0; continue; }
    f.material.color.copy(ramp(L.stops, (v - lo) / Math.max(1e-9, hi - lo))); f.material.opacity = 0.55;
  }
  legend.innerHTML = `<div><span class="chip ${L.prov}">${L.prov}</span> ${esc(L.label)}</div><div class="ramp" style="background:linear-gradient(90deg,${L.stops.join(',')})"></div><div style="display:flex;justify-content:space-between" class="num"><span>${L.fmt(lo)}</span><span>${L.fmt(hi)}</span></div>` + legendBase(true);
}
function legendBase(compact) {
  const acts = [['work', 'At work'], ['shop', 'Shopping'], ['social', 'Visiting friends'], ['leisure', 'Leisure'], ['school', 'School / aftercare']];
  return `${compact ? '<hr style="border:0;border-top:1px solid rgba(255,255,255,.08);margin:8px 0">' : ''}
    ${acts.map(([k, l]) => `<div class="row"><i class="sw" style="background:${ACT_COLOR[k]}"></i>${l}</div>`).join('')}
    <div class="row"><i class="sw" style="background:${MODE_COLOR.car}"></i>Driving · <i class="sw" style="background:${MODE_COLOR.transit}"></i>Transit</div>
    <div class="row"><i class="sw" style="background:#6cc5ee;box-shadow:0 0 6px #6cc5ee"></i>Recorded incident (observed)</div>
    <div class="row"><i class="sw" style="border:1.5px dashed #e4002b"></i>Simulated incident</div>
    <div class="fine">People at home are indoors and not drawn. Buildings are procedural unless you load real footprints.</div>`;
}
$('#lens').onchange = e => { lens = e.target.value; applyLens(); };
applyLens();

// --------------------------------------------------------------------------------------------
// selection & inspector
let selected = null, follow = false, hoverAgent = null;
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
function pickAgent(ev) {
  mouse.set(ev.clientX / innerWidth * 2 - 1, -ev.clientY / innerHeight * 2 + 1);
  ray.setFromCamera(mouse, camera);
  // screen-space nearest visible agent within 14 px (robust for tiny instances)
  let best = null, bd = 14 * 14;
  for (let i = 0; i < N; i++) {
    if (agentState[i]?.kind === 'home') continue;
    _v.set(agentPos[2 * i], 2, agentPos[2 * i + 1]).project(camera);
    if (_v.z > 1) continue;
    const sx = (_v.x + 1) / 2 * innerWidth, sy = (1 - _v.y) / 2 * innerHeight;
    const d = (sx - ev.clientX) ** 2 + (sy - ev.clientY) ** 2;
    if (d < bd) { bd = d; best = i; }
  }
  return best;
}
function pickArea(ev) {
  mouse.set(ev.clientX / innerWidth * 2 - 1, -ev.clientY / innerHeight * 2 + 1);
  ray.setFromCamera(mouse, camera);
  const h = ray.intersectObjects([...areaFill.values()], false)[0];
  return h ? h.object.userData.area : null;
}
let downAt = null;
canvas.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', e => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  const a = pickAgent(e);
  if (a != null) { select(a); return; }
  const ar = pickArea(e);
  if (ar != null) showArea(ar);
});
canvas.addEventListener('pointermove', e => {
  const a = pickAgent(e); hoverAgent = a;
  canvas.classList.toggle('hover', a != null);
  const tip = $('#tip');
  if (a == null) { tip.style.opacity = 0; return; }
  const st = agentState[a];
  tip.innerHTML = `<b>${esc(nameOf(a))}</b>, ${agents[a].age} · ${esc(activityText(st))}<br><span class="chip simulated">simulated person</span>`;
  tip.style.left = (e.clientX + 14) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; tip.style.opacity = 1;
});
const nameOf = i => `${FIRST[(i * 7 + 3) % FIRST.length]} ${String.fromCharCode(65 + (i * 13) % 26)}.`;   // pseudonyms; no real names
function activityText(st) {
  if (!st) return '';
  if (st.kind === 'trip') return `travelling by ${st.mode === 'other' ? 'bike / other' : st.mode}`;
  return { home: 'at home', work: 'at work', school: 'at school', aftercare: 'in after-school care', shop: 'shopping', social: 'visiting a friend', leisure: 'out for leisure', errand: 'running an errand', wait: 'waiting' }[st.kind];
}
const neighbors = Array.from({ length: N }, () => []);
for (const [a, b, k] of D.edges) { neighbors[a].push([b, k]); neighbors[b].push([a, k]); }
const eventsBy = Array.from({ length: N }, () => []);
for (const e of D.events) if (e.pid != null && e.pid !== '' && !isNaN(+e.pid)) eventsBy[+e.pid].push(e);
const incById = Object.fromEntries(D.incidents.map(i => [i.id, i]));

function select(i) {
  selected = i; follow = false;
  $('#inspector').classList.remove('hidden'); $('#timelines').classList.add('hidden');
  renderInspector(); mission('meet');
  if (eventsBy[i].some(e => e.kind === 'exposure' && e.incident_label === 'observed')) mission('witness');
  if (eventsBy[i].some(e => e.kind === 'activity_cancelled')) mission('changed');
}
function gantt(i, day) {
  const s = segs[i].filter(g => g[1] > day * 1440 && g[0] < (day + 1) * 1440);
  const now = simT - day * 1440;
  return `<div class="gantt">${s.map(g => { const a = Math.max(0, g[0] - day * 1440) / 14.4, b = Math.min(1440, g[1] - day * 1440) / 14.4, k = KINDS[g[2]];
    const c = k === 'trip' ? MODE_COLOR[MODES[g[7]]] : k === 'home' ? 'rgba(155,176,198,.25)' : ACT_COLOR[k];
    return `<i style="left:${a}%;width:${Math.max(0.2, b - a)}%;background:${c}" title="${esc(k === 'trip' ? 'trip by ' + MODES[g[7]] : k)}"></i>`; }).join('')}
    ${now >= 0 && now <= 1440 ? `<span class="now" style="left:${now / 14.4}%"></span>` : ''}</div>
    <div class="gantt-axis num"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>`;
}
function spark(values, lo, hi, color) {
  const w = 300, h = 60, n = values.length;
  const pts = values.map((v, k) => `${(k / Math.max(1, n - 1)) * (w - 8) + 4},${h - 4 - (v - lo) / Math.max(1e-9, hi - lo) * (h - 8)}`).join(' ');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="${color}" stroke-width="2" points="${pts}"/>${values.map((v, k) => `<circle cx="${(k / Math.max(1, n - 1)) * (w - 8) + 4}" cy="${h - 4 - (v - lo) / Math.max(1e-9, hi - lo) * (h - 8)}" r="2.5" fill="${color}"/>`).join('')}</svg>`;
}
function renderInspector() {
  const i = selected, a = agents[i], st = agentState[i], day = Math.min(D.meta.n_days - 1, Math.floor(simT / 1440));
  const area = areaByNum[a.area];
  const work = a.work_area === 0 ? 'outside Chicago' : a.work_area > 0 ? areaByNum[a.work_area].name : null;
  const hist = eventsBy[i].slice().sort((x, y) => (x.day - y.day) || ((x.t ?? 0) - (y.t ?? 0)));
  const safety = D.safety[i];
  const nb = neighbors[i].slice(0, 12);
  const hhRole = a.role === 'householder' ? 'householder' : a.age < 18 ? 'child' : 'adult member';
  $('#inspectorBody').innerHTML = `
    <div class="who"><div class="avatar" style="background:${ACT_COLOR[st?.kind] || '#9bb0c6'}">${esc(nameOf(i)[0])}</div>
      <div><h2>${esc(nameOf(i))}</h2><p>${a.age} years old, ${esc(hhRole)} in ${esc(area.name)}</p></div></div>
    <p><span class="chip simulated">simulated person</span><span class="chip estimated">stands for ${Math.round(a.weight).toLocaleString()} residents</span></p>
    <p style="font-size:16px;margin:6px 0">Now ${esc(activityText(st))}.</p>
    <div class="btnrow"><button class="ghost" id="followBtn">${follow ? 'Stop following' : 'Follow'}</button><button class="ghost" id="flyHome">Show home</button></div>
    <h3>Today</h3>${gantt(i, day)}
    <h3>Profile</h3>
    <dl class="facts">
      <dt>Household</dt><dd>${a.hh_size} people, ${a.tenure === 0 ? 'owns' : 'rents'} <span class="chip fitted">fitted</span></dd>
      <dt>Income</dt><dd>${esc(INC[a.income_bin])} household (drawn $${Math.round(a.income).toLocaleString()}) <span class="chip fitted">fitted</span></dd>
      <dt>Vehicles</dt><dd>${a.vehicles === 3 ? '3 or more' : a.vehicles} <span class="chip fitted">fitted</span></dd>
      <dt>Work</dt><dd>${a.labor < 0 ? 'under 16' : esc(LABOR[a.labor])}${a.wfh ? ', works from home' : ''}${work ? `, works in ${esc(work)} and commutes by ${esc(a.mode === 'other' ? 'walking/biking/other' : a.mode)}` : ''} <span class="chip fitted">fitted</span></dd>
      <dt>Education</dt><dd>${a.edu < 0 ? '—' : esc(EDU[a.edu])} <span class="chip fitted">fitted</span></dd>
      <dt>Habit</dt><dd class="num">${a.habit} <span class="chip latent">latent</span></dd>
      <dt>Safety sensitivity</dt><dd class="num">${a.kappa} <span class="chip latent">latent</span></dd>
    </dl>
    <h3>Perceived safety by day <span class="chip hypothesis">hypothesis</span></h3>
    ${spark(safety, Math.min(...safety, 0.7), Math.max(...safety, 0.81), '#f3b13f')}
    <div class="gantt-axis num"><span>start</span><span>${safety[safety.length - 1].toFixed(3)} now (day ${D.meta.n_days})</span></div>
    <h3>Relationships</h3>
    ${nb.length ? `<ul class="history">${nb.map(([j, k]) => `<li><button class="linkish" data-agent="${j}">${esc(nameOf(j))}</button>, ${agents[j].age} — ${k}</li>`).join('')}</ul>` : '<p class="fine">No ties in the synthetic network.</p>'}
    <h3>Life this week</h3>
    ${hist.length ? `<ul class="history">${hist.map(e => historyItem(e)).join('')}</ul>` : '<p class="fine">Nothing unusual happened to this person this week.</p>'}
    <p class="fine">Name is a pseudonym. Every attribute is synthetic; no real resident is represented.</p>`;
  $('#followBtn').onclick = () => { follow = !follow; renderInspector(); };
  $('#flyHome').onclick = () => flyTo(a.home[0], a.home[1], 600);
  document.querySelectorAll('[data-agent]').forEach(b => b.onclick = () => { select(+b.dataset.agent); flyTo(agentPos[2 * selected], agentPos[2 * selected + 1], 700); });
  document.querySelectorAll('[data-inc]').forEach(b => b.onclick = () => { const inc = incById[+b.dataset.inc]; setTime(inc.t); flyTo(inc.pos[0], inc.pos[1], 1200); });
}
function historyItem(e) {
  const when = e.t != null ? clockLabel(D.meta.start_date, e.day * 1440 + e.t) : clockLabel(D.meta.start_date, e.day * 1440).replace(/, 00:00$/, '');
  const inc = e.incident_id != null ? incById[+e.incident_id] : null;
  const incTxt = inc ? `<button class="linkish" data-inc="${inc.id}">${inc.label === 'observed' ? 'a recorded carjacking' : 'a simulated carjacking'}</button> <span class="chip ${inc.label}">${inc.label}</span>` : '';
  switch (e.kind) {
    case 'exposure': return `<li>Was ${Math.round(e.distance_m)} m from ${incTxt}<small>${when}</small></li>`;
    case 'activity_cancelled': return `<li>Cancelled ${esc(e.activity)} after ${incTxt}<small>${when}</small></li>`;
    case 'aftercare': return `<li>Stayed in after-school care until ${String(Math.floor(e.until / 60)).padStart(2, '0')}:${String(Math.round(e.until % 60)).padStart(2, '0')} — no adult home<small>${when}</small></li>`;
    case 'supervision_gap': return `<li>Home without an adult for ${e.minutes} minutes (model gap, logged)<small>${when}</small></li>`;
    case 'skipped_for_childcare': return `<li>Skipped ${esc(e.activity)} to look after children<small>${when}</small></li>`;
    case 'stayed_home_for_childcare': return `<li>Stayed home from work to look after children<small>${when}</small></li>`;
    default: return `<li>${esc(e.kind)}<small>${when}</small></li>`;
  }
}
function showArea(num) {
  const a = areaByNum[num], s = a.stats;
  const res = agents.filter(x => x.area === num);
  const day = Math.min(D.meta.n_days, Math.floor(simT / 1440));
  const sf = res.length ? res.reduce((t, x) => t + x.weight * D.safety[x.pid][day], 0) / res.reduce((t, x) => t + x.weight, 0) : null;
  const rec = D.incidents.filter(i => i.area === num && i.label === 'observed').length, sim = D.incidents.filter(i => i.area === num && i.label === 'simulated').length;
  selected = null;
  $('#inspector').classList.remove('hidden'); $('#timelines').classList.add('hidden');
  $('#inspectorBody').innerHTML = `<h2>${esc(a.name)}</h2><p class="fine">Community area ${num}, ${esc(a.district)}</p>
    <h3>Observed <span class="chip observed">ACS 2015–19 / LEHD via CMAP</span></h3>
    <dl class="facts num"><dt>Population</dt><dd>${s.population.toLocaleString()}</dd><dt>Households</dt><dd>${s.households.toLocaleString()}</dd>
      <dt>Median income</dt><dd>$${Math.round(s.median_income).toLocaleString()}</dd><dt>Median rent</dt><dd>$${Math.round(s.median_rent).toLocaleString()}</dd>
      <dt>Transit commuters</dt><dd>${(s.transit_share * 100).toFixed(1)}%</dd><dt>No vehicle</dt><dd>${(s.no_vehicle_share * 100).toFixed(1)}% of households</dd>
      <dt>Jobs located here</dt><dd>${s.jobs.toLocaleString()}</dd></dl>
    <h3>This week</h3>
    <dl class="facts num"><dt>Recorded carjackings</dt><dd>${rec} <span class="chip observed">observed</span></dd>
      <dt>Simulated carjackings</dt><dd>${sim} <span class="chip simulated">simulated</span></dd>
      <dt>Synthetic residents</dt><dd>${res.length} agents <span class="chip simulated">simulated</span></dd>
      <dt>Mean perceived safety</dt><dd>${sf == null ? '—' : sf.toFixed(3)} <span class="chip hypothesis">hypothesis</span></dd></dl>
    ${res.length ? `<h3>Residents</h3><ul class="history">${res.slice(0, 15).map(x => `<li><button class="linkish" data-agent="${x.pid}">${esc(nameOf(x.pid))}</button>, ${x.age}</li>`).join('')}</ul>` : ''}`;
  document.querySelectorAll('[data-agent]').forEach(b => b.onclick = () => { select(+b.dataset.agent); flyTo(agentPos[2 * selected], agentPos[2 * selected + 1], 700); });
  flyTo(a.c[0], a.c[1], 6000);
}
$('#closeInspector').onclick = () => { $('#inspector').classList.add('hidden'); selected = null; follow = false; };

// --------------------------------------------------------------------------------------------
// alternate timelines: the same population re-run with different settings (engine output)
function renderTimelines() {
  const runs = { 'This run': { daily: D.daily, config: D.meta.config }, ...D.compare };
  const colors = ['#f3b13f', '#6cc5ee', '#ff7eb6', '#7fd8a4', '#b9a3f5'];
  const names = Object.keys(runs);
  const chart = (key, label, fmt) => {
    const series = names.map(n => runs[n].daily.map(d => d[key]));
    const all = series.flat(); const lo = Math.min(...all), hi = Math.max(...all);
    const w = 320, h = 90;
    const days = D.daily.map(d => d.weekday.slice(0, 3));
    const path = (vals, c) => `<polyline fill="none" stroke="${c}" stroke-width="2" points="${vals.map((v, k) => `${10 + k / (vals.length - 1) * (w - 20)},${h - 14 - (v - lo) / Math.max(1e-9, hi - lo) * (h - 24)}`).join(' ')}"/>`;
    return `<div class="chart-title">${esc(label)}</div><svg viewBox="0 0 ${w} ${h}" style="width:100%;height:auto">${series.map((v, k) => path(v, colors[k])).join('')}
      ${days.map((d, k) => `<text x="${10 + k / (days.length - 1) * (w - 20)}" y="${h - 2}" fill="#9bb0c6" font-size="9" text-anchor="middle">${d}</text>`).join('')}</svg>
      <div class="fine num">range ${fmt(lo)} – ${fmt(hi)}</div>`;
  };
  $('#timelinesBody').innerHTML = `<h2>Alternate timelines</h2>
    <p>The same 2,000 synthetic residents, re-run by the engine with one setting changed. Differences come only from that setting and the random seed.</p>
    <div class="legend-inline">${names.map((n, k) => `<span><i style="background:${colors[k]}"></i>${esc(n)}</span>`).join('')}</div>
    ${chart('mean_evening_out_min', 'Evening minutes out of home per resident (18:00–24:00)', v => v.toFixed(1))}
    ${chart('mean_perceived_safety', 'Mean perceived safety (hypothesised mechanism)', v => v.toFixed(3))}
    ${chart('activities_cancelled', 'Plans cancelled after an incident', v => v.toFixed(0))}
    <h3>What differs</h3><ul class="history">${names.map(n => `<li><b>${esc(n)}</b><small>incidents: ${esc(runs[n].config.incident_mode)}; response a=${runs[n].config.safety.a}, b=${runs[n].config.safety.b}, cancel γ=${runs[n].config.safety.gamma_cancel}; seed ${runs[n].config.seed}</small></li>`).join('')}</ul>
    <p class="fine">Run your own scenario with the API: POST /scenarios (see README). Results here are model consequences, not measurements of Chicago.</p>`;
  mission('timelines');
}
$('#timelinesBtn').onclick = () => { $('#timelines').classList.toggle('hidden'); $('#inspector').classList.add('hidden'); renderTimelines(); };
$('#closeTimelines').onclick = () => $('#timelines').classList.add('hidden');

// --------------------------------------------------------------------------------------------
// real building footprints (observed) around the camera target, fetched live
const realGroup = new THREE.Group(); scene.add(realGroup);
$('#footprintsBtn').onclick = async () => {
  // local metres -> lon/lat bounding box via the same UTM 16N frame the engine uses
  const [x0, y0] = D.meta.origin_utm16n, [lon0, lat0] = D.meta.origin_lonlat;
  const tx = controls.target.x, tz = controls.target.z, half = 450;
  const kx = 111320 * Math.cos(lat0 * Math.PI / 180), kz = 110540;              // only for the query box; padded below
  const lon = lon0 + tx / kx, lat = lat0 - tz / kz, pad = 1.15;
  const w = lon - pad * half / kx, e = lon + pad * half / kx, s = lat - pad * half / kz, n = lat + pad * half / kz;
  const url = `https://data.cityofchicago.org/resource/syp8-uezg.json?$select=bldg_id,stories,no_stories,year_built,the_geom&$where=${encodeURIComponent(`within_box(the_geom, ${n}, ${w}, ${s}, ${e})`)}&$limit=8000`;
  toast('Loading real footprints from data.cityofchicago.org…');
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const rows = await res.json();
    const geos = [];
    let unknown = 0;
    for (const r of rows) {
      const fp = parseFootprint(r); if (!fp) continue;
      if (fp.heightSource !== 'stories') unknown++;
      for (const ring of fp.rings) {
        const pts = ring.map(([lo, la]) => { const [E, Nn] = utmForward(lo, la, 16); return new THREE.Vector2(E - x0, Nn - y0); });
        const g = new THREE.ExtrudeGeometry(new THREE.Shape(pts), { depth: fp.heightM, bevelEnabled: false });
        g.rotateX(-Math.PI / 2); geos.push(g);
      }
    }
    if (!geos.length) throw new Error('no footprints returned for this area');
    const merged = BufferGeometryUtils.mergeGeometries(geos.map(g => g.toNonIndexed ? g.toNonIndexed() : g));
    const m = buildingMaterial(); m.color.set('#c9c3b6');
    realGroup.add(new THREE.Mesh(merged, m));
    // hide procedural buildings inside the loaded box
    const M = new THREE.Matrix4();
    bldInfo.forEach((b, i) => { if (Math.abs(b.x - tx) < half && Math.abs(b.z - tz) < half) { bldMesh.setMatrixAt(i, ZERO); } });
    bldMesh.instanceMatrix.needsUpdate = true;
    toast(`${rows.length.toLocaleString()} real footprints loaded (City of Chicago, 2015 data). ${unknown} without story counts drawn 6 m tall.`);
  } catch (err) {
    toast(`Could not load real footprints: ${esc(err.message)}. The procedural city stays in place.`);
  }
};

// --------------------------------------------------------------------------------------------
// missions & achievements
const MISSIONS = [
  { id: 'meet', title: 'Meet a resident', hint: 'Click any person on the street.' },
  { id: 'witness', title: 'Find a witness', hint: 'Find someone who was near a recorded (observed) carjacking. The ribbon’s blue ticks mark when they happened.' },
  { id: 'changed', title: 'Changed plans', hint: 'Find someone who cancelled an outing because of an incident.' },
  { id: 'transit', title: 'Ride along', hint: 'Follow someone while they travel by transit.' },
  { id: 'night', title: 'Night shift', hint: 'Watch the city after 23:00.' },
  { id: 'timelines', title: 'What if?', hint: 'Open Compare timelines and read how the alternate runs differ.' },
];
let done = new Set(store('simchi-missions') || []);
function renderMissions() {
  $('#missionsToggle').textContent = `Missions ${done.size}/${MISSIONS.length}`;
  $('#missionList').innerHTML = MISSIONS.map(m => `<li class="${done.has(m.id) ? 'done' : ''}"><b>${esc(m.title)}</b>${done.has(m.id) ? ' — done' : `<br>${esc(m.hint)}`}</li>`).join('');
}
function mission(id) { if (done.has(id)) return; done.add(id); store('simchi-missions', [...done]); renderMissions(); const m = MISSIONS.find(x => x.id === id); toast(`Mission complete: ${m.title}`); }
$('#missionsToggle').onclick = () => { const m = $('#missions'); const open = m.classList.toggle('hidden') === false; $('#missionsToggle').setAttribute('aria-expanded', open); };
renderMissions();

function toast(html) { const t = document.createElement('div'); t.className = 'toast'; t.innerHTML = html; $('#toasts').appendChild(t); setTimeout(() => t.remove(), 4200); }

// --------------------------------------------------------------------------------------------
// time ribbon: each day's real sky colours, observed vs simulated incident ticks
const TOTAL = D.meta.n_days * 1440;
const scrub = $('#scrub'); scrub.max = TOTAL - 1;
function drawRibbon() {
  const c = $('#ribbonSky'), w = c.clientWidth, h = c.clientHeight; c.width = w * devicePixelRatio; c.height = h * devicePixelRatio;
  const g = c.getContext('2d'); g.scale(devicePixelRatio, devicePixelRatio);
  for (let x = 0; x < w; x++) {
    const t = x / w * TOTAL;
    const { elevation } = sunPosition(utcMs(D.meta.start_date, t, UTC_OFFSET_H), LAT, LON);
    const day = THREE.MathUtils.smoothstep(elevation, -0.12, 0.2), dusk = Math.max(0, 1 - Math.abs(elevation - 0.02) / 0.22);
    const col = new THREE.Color().setRGB(0.03 + 0.25 * day + 0.45 * dusk * (1 - day), 0.06 + 0.45 * day + 0.18 * dusk * (1 - day), 0.13 + 0.7 * day);
    g.fillStyle = '#' + col.getHexString(); g.fillRect(x, 0, 1, h);
  }
  $('#ribbonTicks').innerHTML = D.incidents.map(i => `<i class="${i.label}" style="left:${i.t / TOTAL * 100}%" title="${i.label === 'observed' ? 'Recorded' : 'Simulated'} carjacking ${esc(i.time)}"></i>`).join('');
  $('#ribbonDays').innerHTML = D.daily.map((d, k) => `<span style="left:${k / D.meta.n_days * 100}%">${esc(clockLabel(D.meta.start_date, k * 1440).replace(/, 00:00$/, ''))}</span>`).join('');
}
function setTime(t) { simT = Math.max(0, Math.min(TOTAL - 1, t)); scrub.value = simT; }
scrub.oninput = () => { simT = +scrub.value; };
$('#play').onclick = () => { playing = !playing; $('#play').textContent = playing ? 'Pause' : 'Play'; $('#play').setAttribute('aria-label', playing ? 'Pause' : 'Play'); };
document.querySelectorAll('[data-speed]').forEach(b => b.onclick = () => { speed = +b.dataset.speed; document.querySelectorAll('[data-speed]').forEach(x => x.classList.toggle('on', x === b)); });
$('#quality').onchange = e => { quality = e.target.value; store('simchi-quality', quality); applyQuality(); buildProcedural(); };
addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' && e.target.type !== 'range') return;
  if (e.code === 'Space') { e.preventDefault(); $('#play').click(); }
  if (e.code === 'Escape') $('#closeInspector').click();
  if (e.code === 'KeyF' && selected != null) { follow = !follow; renderInspector(); }
  if (e.code === 'BracketRight') setTime(simT + 60);
  if (e.code === 'BracketLeft') setTime(simT - 60);
});

// --------------------------------------------------------------------------------------------
// camera flights
let flight = null;
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
function flyTo(x, z, dist) {
  const tgt = new THREE.Vector3(x, 0, z), dir = camera.position.clone().sub(controls.target).normalize();
  if (dir.y < 0.35) dir.y = 0.6; dir.normalize();
  const pos = tgt.clone().addScaledVector(dir, dist);
  if (reduceMotion) { controls.target.copy(tgt); camera.position.copy(pos); return; }
  flight = { p0: camera.position.clone(), t0: controls.target.clone(), p1: pos, t1: tgt, start: performance.now(), ms: 1400 };
}
function flightTick(now) {
  if (!flight) return;
  const k = Math.min(1, (now - flight.start) / flight.ms), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
  camera.position.lerpVectors(flight.p0, flight.p1, e); controls.target.lerpVectors(flight.t0, flight.t1, e);
  if (k >= 1) flight = null;
}

// --------------------------------------------------------------------------------------------
// HUD counters
function counters(c) {
  const d = Math.min(D.meta.n_days - 1, Math.floor(simT / 1440)), dm = D.daily[d];
  $('#counters').innerHTML = `
    <div class="counter"><b>${c.outside.toLocaleString()}</b><span>out and about</span></div>
    <div class="counter"><b>${c.moving.toLocaleString()}</b><span>travelling</span></div>
    <div class="counter"><b>${c.indoor.toLocaleString()}</b><span>at home</span></div>
    <div class="counter"><b>${dm.incidents_observed}</b><span>recorded incidents today</span></div>
    <div class="counter"><b>${dm.agents_exposed}</b><span>people nearby one</span></div>`;
}

// --------------------------------------------------------------------------------------------
camera.position.set(9000, 21000, 26000); controls.target.set(2500, 0, -1500);
const clock = new THREE.Clock();
let lastHud = 0, lastLensDay = -1;
function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(0.1, clock.getDelta());
  if (playing) { simT += dt * speed; if (simT >= TOTAL - 1) { simT = TOTAL - 1; playing = false; $('#play').textContent = 'Play'; } scrub.value = simT; }
  flightTick(performance.now());
  if (follow && selected != null && !flight) { const dx = agentPos[2 * selected] - controls.target.x, dz = agentPos[2 * selected + 1] - controls.target.z; controls.target.x += dx; controls.target.z += dz; camera.position.x += dx; camera.position.z += dz;
    const st = agentState[selected]; if (st && st.kind === 'trip' && st.mode === 'transit') mission('transit'); }
  controls.update();
  const c = updateAgents(simT);
  updateIncidents(simT);
  updateSky(simT);
  sky.position.copy(camera.position);
  if (rain) { const p = rain.geometry.attributes.position; for (let i = 0; i < p.count; i++) { let y = p.getY(i) - dt * 220; if (y < 0) y += 900; p.setY(i, y); } p.needsUpdate = true; rain.position.set(controls.target.x, 0, controls.target.z); }
  if ((simT % 1440) >= 23 * 60) mission('night');
  updateLabels();
  $('#playhead').style.left = (simT / TOTAL * 100) + '%';
  const now = performance.now();
  if (now - lastHud > 250) {
    lastHud = now; $('#clock').textContent = clockLabel(D.meta.start_date, simT); counters(c);
    if (selected != null && !$('#inspector').classList.contains('hidden')) renderInspectorLive();
    const d = Math.floor(simT / 1440); if (lens === 'safety' && d !== lastLensDay) { lastLensDay = d; applyLens(); }
  }
  renderer.render(scene, camera);
}
let lastInspectT = -1;
function renderInspectorLive() { if (Math.abs(simT - lastInspectT) > 5) { lastInspectT = simT; const sc = $('#inspector').scrollTop; renderInspector(); $('#inspector').scrollTop = sc; } }
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); drawRibbon(); });
drawRibbon(); setTime(simT);
$('#boot').remove();
frame();
window.__sim = { D, setTime, select, flyTo, get simT() { return simT; }, camera, controls, agentState };
toast('Press Play, or drag the time ribbon. Click a person to see their life.');
