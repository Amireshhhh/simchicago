// Incidents (pulsing rings and light pillars) and commute-flow arcs.
import * as THREE from 'three';

export const INCIDENT_WINDOW = 90;   // minutes an incident stays on screen
const COL = { observed: new THREE.Color('#5fd4ff'), simulated: new THREE.Color('#ff7eb6') };

export function createIncidents(scene, D) {
  const group = new THREE.Group(); scene.add(group);
  const ringGeo = new THREE.RingGeometry(0.82, 1.0, 64);
  const pillarGeo = new THREE.CylinderGeometry(1, 1, 1, 24, 1, true).translate(0, 0.5, 0);
  const pillarMat = (c) => new THREE.ShaderMaterial({
    uniforms: { color: { value: c.clone() }, a: { value: 1 } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    vertexShader: 'varying float vY; void main(){ vY = position.y; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }',
    fragmentShader: 'uniform vec3 color; uniform float a; varying float vY; void main(){ gl_FragColor = vec4(color*(1.-vY)*1.4*a, (1.-vY)*a); }',
  });
  const items = D.incidents.map(inc => {
    const c = COL[inc.label] || COL.simulated;
    const rings = [0, 1, 2].map(() => {
      const m = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: c, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide }));
      m.rotation.x = -Math.PI / 2; m.position.set(inc.pos[0], 1.2, inc.pos[1]); m.visible = false; group.add(m); return m;
    });
    const pillar = new THREE.Mesh(pillarGeo, pillarMat(c));
    pillar.position.set(inc.pos[0], 0, inc.pos[1]); pillar.visible = false; group.add(pillar);
    return { inc, rings, pillar };
  });

  function update(t, camDist, radius) {
    const live = [];
    const scale = Math.max(radius, camDist / 40);
    for (const it of items) {
      const age = t - it.inc.t;
      const on = age >= 0 && age < INCIDENT_WINDOW && group.visible;
      it.pillar.visible = on;
      it.rings.forEach(r => { r.visible = on; });
      if (!on) continue;
      const fade = 1 - age / INCIDENT_WINDOW;
      it.pillar.scale.set(scale * 0.05, Math.max(400, camDist * 0.25) * (0.4 + 0.6 * fade), scale * 0.05);
      it.pillar.material.uniforms.a.value = 0.7 * fade;
      it.rings.forEach((r, k) => {
        const ph = ((age / 12 + k / 3) % 1);
        const s = radius * (0.2 + ph);
        r.scale.set(s, s, s);
        r.material.opacity = (1 - ph) * 0.9 * fade;
      });
      live.push(it.inc);
    }
    return live;
  }
  return { group, update };
}

export function createFlows(scene, D) {
  // population-weighted home-area -> work-area commute links of the synthetic residents
  const w = new Map();
  for (const a of D.agents) {
    if (!a.commuter || !a.work_area) continue;
    const key = `${a.area}-${a.work_area}`;
    w.set(key, (w.get(key) || 0) + a.weight);
  }
  const areaC = Object.fromEntries(D.areas.map(a => [a.num, a.c]));
  const ext = Object.values(D.external_targets);
  const top = [...w.entries()].filter(([k]) => { const [o, d] = k.split('-').map(Number); return o !== d; })
    .sort((a, b) => b[1] - a[1]).slice(0, 160);
  const maxW = top.length ? top[0][1] : 1;
  const pos = [], along = [], weight = [];
  for (const [k, v] of top) {
    const [o, d] = k.split('-').map(Number);
    const A = areaC[o];
    const B = d === 78 ? ext.reduce((best, p) => (Math.hypot(p[0] - A[0], p[1] - A[1]) < Math.hypot(best[0] - A[0], best[1] - A[1]) ? p : best), ext[0]) : areaC[d];
    if (!A || !B) continue;
    const len = Math.hypot(B[0] - A[0], B[1] - A[1]);
    const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(A[0], 5, A[1]),
      new THREE.Vector3((A[0] + B[0]) / 2, len * 0.22, (A[1] + B[1]) / 2), new THREE.Vector3(B[0], 5, B[1]));
    const pts = curve.getPoints(48);
    for (let i = 0; i < pts.length - 1; i++) {
      pos.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z);
      along.push(i / 48, (i + 1) / 48);
      weight.push(v / maxW, v / maxW);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('along', new THREE.Float32BufferAttribute(along, 1));
  g.setAttribute('weight', new THREE.Float32BufferAttribute(weight, 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: 'attribute float along; attribute float weight; varying float vA; varying float vW; void main(){ vA = along; vW = weight; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }',
    fragmentShader: `uniform float time; varying float vA; varying float vW;
      void main(){ float dash = smoothstep(0.0, 0.25, fract(vA * 6.0 - time * 0.35)) * (1.0 - smoothstep(0.25, 0.55, fract(vA * 6.0 - time * 0.35)));
        vec3 c = mix(vec3(0.37, 0.83, 1.0), vec3(1.0, 0.75, 0.33), vA);
        gl_FragColor = vec4(c * (0.25 + 1.3 * dash), (0.12 + 0.85 * dash) * (0.25 + 0.75 * vW)); }`,
  });
  const lines = new THREE.LineSegments(g, mat); lines.visible = false; lines.frustumCulled = false; scene.add(lines);
  return { lines, update: (realT) => { mat.uniforms.time.value = realT; }, count: top.length };
}
