// Ground, Lake Michigan, community areas, procedural buildings, landmarks.
import * as THREE from 'three';
import { pointInRing, rng, utmForward } from './core.js';

const toShape = ring => new THREE.Shape(ring.map(([x, z]) => new THREE.Vector2(x, -z)));
const flat = geo => { geo.rotateX(-Math.PI / 2); return geo; };

/** Chicago's street grid in local coordinates: origin at State & Madison (the city's
 *  addressing origin, lon -87.62783, lat 41.88194) and rotated by the UTM grid convergence,
 *  computed here from two points on the same meridian. Returns {ox, oz, c, s}. */
export function streetGrid(D) {
  const [E0, N0] = D.meta.origin_utm16n;
  const loc = (lo, la) => { const [E, N] = utmForward(lo, la, 16); return [E - E0, -(N - N0)]; };
  const [ox, oz] = loc(-87.62783, 41.88194);
  const [ax, az] = loc(-87.62783, 41.80), [bx, bz] = loc(-87.62783, 41.96);
  const ang = Math.atan2(bx - ax, -(bz - az));     // angle of true north from local -z
  return { ox, oz, c: Math.cos(ang), s: Math.sin(ang) };
}

export function createCity(scene, D) {
  const group = new THREE.Group(); scene.add(group);
  const time = { value: 0 }, night = { value: 0 };
  const grid = streetGrid(D);
  const gridU = { uGrid: { value: new THREE.Vector4(grid.ox, grid.oz, grid.c, grid.s) } };
  // grid coordinates (metres east / north of State & Madison along the street grid)
  const toGrid = (x, z) => { const dx = x - grid.ox, dz = z - grid.oz; return [dx * grid.c + dz * grid.s, -(-dx * grid.s + dz * grid.c)]; };

  // outside land and city land
  const outside = new THREE.Mesh(new THREE.PlaneGeometry(600000, 600000), new THREE.MeshStandardMaterial({ color: 0x232a2a, roughness: 1 }));
  outside.rotation.x = -Math.PI / 2; outside.position.y = -3; outside.receiveShadow = true; group.add(outside);
  // City land with the street grid: half-mile arterials (804.67 m; Chicago numbers 800 per
  // mile) and local streets every 1/8 mile E-W (201 m) and 1/16 mile N-S (100.6 m).
  // Arterials glow sodium-orange at night. Streets are drawn, not mapped: no road data.
  const landMat = new THREE.MeshStandardMaterial({ color: 0x3a434c, roughness: 0.95 });
  landMat.onBeforeCompile = sh => {
    sh.uniforms.uNight = night; sh.uniforms.uGrid = gridU.uGrid;
    sh.vertexShader = 'varying vec3 vWP;\n' + sh.vertexShader.replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\n vWP = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = 'uniform float uNight; uniform vec4 uGrid; varying vec3 vWP;\n' + sh.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
      {
        vec2 d = vWP.xz - uGrid.xy;
        vec2 g = vec2(d.x * uGrid.z + d.y * uGrid.w, d.x * uGrid.w - d.y * uGrid.z);   // east, north
        float px = max(length(fwidth(g)), 1e-3);                 // metres per pixel
        // energy-conserving lines: a line narrower than a pixel is drawn one pixel wide but
        // with intensity equal to its coverage, so distant streets fade instead of blooming
        vec2 art = abs(fract(g / 804.67 + 0.5) - 0.5) * 804.67;
        float wa = max(9.0, px * 0.8);
        float a = (1.0 - smoothstep(wa - px * 0.5, wa + px * 0.5, min(art.x, art.y))) * min(1.0, 9.0 / wa);
        vec2 loc = abs(fract(g / vec2(201.17, 100.58) + 0.5) - 0.5) * vec2(201.17, 100.58);
        float wl = max(4.0, px * 0.8);
        float l = (1.0 - smoothstep(wl - px * 0.5, wl + px * 0.5, min(loc.x, loc.y))) * min(1.0, 4.0 / wl);
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.50, 0.53, 0.57), (a * 0.6 + l * 0.35) * (1.0 - uNight));
        totalEmissiveRadiance += vec3(1.0, 0.52, 0.16) * (a * 1.1 + l * 0.35) * uNight;
      }`);
  };
  const land = new THREE.Mesh(flat(new THREE.ShapeGeometry(D.city_rings.map(toShape))), landMat);
  land.position.y = -0.8; land.receiveShadow = true; group.add(land);

  // Lake Michigan: east of the city's lakefront (a visual approximation, not surveyed shoreline)
  const pts = D.city_rings.flat();
  const zs = pts.map(p => p[1]), zMin = Math.min(...zs), zMax = Math.max(...zs);
  const shore = [];
  for (let z = zMin; z <= zMax; z += 250) {
    let mx = -Infinity;
    for (const p of pts) if (Math.abs(p[1] - z) < 200 && p[0] > mx) mx = p[0];
    if (mx > -Infinity) shore.push([mx + 30, z]);
  }
  const sm = shore.map((p, i) => [Math.max(...shore.slice(Math.max(0, i - 3), i + 4).map(q => q[0])), p[1]]).filter(p => p[1] < zMax - 9000);
  const north = sm[0], south = sm[sm.length - 1];
  const lakeRing = [[north[0], zMin - 80000], ...sm, [south[0], south[1] + 3000], [90000, south[1] + 3000], [90000, zMin - 80000]];
  const lakeMat = new THREE.MeshPhysicalMaterial({ color: 0x0f3a55, roughness: 0.08, metalness: 0.0, clearcoat: 0.6, clearcoatRoughness: 0.15, envMapIntensity: 1.1 });
  lakeMat.onBeforeCompile = sh => {
    sh.uniforms.uTime = time;
    sh.vertexShader = 'varying vec3 vWorldP;\n' + sh.vertexShader.replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\n vWorldP = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = 'uniform float uTime; varying vec3 vWorldP;\n' + sh.fragmentShader.replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
      {
        vec2 p = vWorldP.xz;
        float t = uTime;
        vec2 g = vec2(0.0);
        g += vec2(cos(p.x*0.011 + t*0.9), sin(p.y*0.013 - t*0.7)) * 0.35;
        g += vec2(cos(p.x*0.031 - p.y*0.017 + t*1.7), sin(p.y*0.029 + p.x*0.011 + t*1.3)) * 0.18;
        g += vec2(cos(p.x*0.083 + p.y*0.051 + t*2.9), sin(p.y*0.077 - t*2.3)) * 0.07 * (1.0 - smoothstep(1500.0, 6000.0, length(vViewPosition)));
        float fade = 1.0 - smoothstep(4000.0, 26000.0, length(vViewPosition));
        vec3 wn = normalize(vec3(g.x * fade, 1.0, g.y * fade) * vec3(0.14, 1.0, 0.14));
        normal = normalize((viewMatrix * vec4(wn, 0.0)).xyz);
      }`);
  };
  const lake = new THREE.Mesh(flat(new THREE.ShapeGeometry(toShape(lakeRing))), lakeMat);
  lake.position.y = -0.4; group.add(lake);

  // community areas: lens fills and glowing outlines
  const areaFill = new Map();
  const outlineMat = new THREE.LineBasicMaterial({ color: 0x5fd4ff, transparent: true, opacity: 0.28, blending: THREE.AdditiveBlending, depthWrite: false });
  const linePts = [];
  for (const a of D.areas) {
    const fill = new THREE.Mesh(flat(new THREE.ShapeGeometry(a.rings.map(toShape))),
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0, depthWrite: false }));
    fill.position.y = -0.1; fill.userData.area = a.num; group.add(fill); areaFill.set(a.num, fill);
    for (const ring of a.rings) for (let i = 0; i < ring.length - 1; i++) linePts.push(ring[i][0], 0.6, ring[i][1], ring[i + 1][0], 0.6, ring[i + 1][1]);
  }
  const lg = new THREE.BufferGeometry(); lg.setAttribute('position', new THREE.Float32BufferAttribute(linePts, 3));
  const outlines = new THREE.LineSegments(lg, outlineMat); group.add(outlines);

  // procedural buildings (NOT real buildings): counts follow households and jobs; the height
  // mix follows each area's housing-structure shares and job density; parks and open land are
  // left empty in proportion to CMAP open-space land use.
  const box = new THREE.BoxGeometry(1, 1, 1); box.translate(0, 0.5, 0);
  function windowMaterial(params) {
    const m = new THREE.MeshStandardMaterial(params);
    m.onBeforeCompile = sh => {
      sh.uniforms.uNight = night;
      sh.vertexShader = 'varying vec3 vWP; varying vec3 vWN;\n' + sh.vertexShader.replace('#include <worldpos_vertex>', `#include <worldpos_vertex>
        vec4 wp4 = vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
          wp4 = instanceMatrix * wp4;
        #endif
        vWP = (modelMatrix * wp4).xyz; vWN = normalize(mat3(modelMatrix) * objectNormal);`);
      sh.fragmentShader = 'uniform float uNight; varying vec3 vWP; varying vec3 vWN;\nfloat h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }\n' +
        sh.fragmentShader.replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        float side = 1.0 - abs(vWN.y);
        if (vWP.y > 2.0 && side > 0.5) {
          float u0 = (vWP.x + vWP.z) / 3.4, v0 = vWP.y / 3.5;
          // window LOD: when a window would be under ~3.5 px, merge cells in powers of two so
          // lit windows stay visible as separate lights instead of averaging to a flat glow
          float cellPx = 1.0 / max(max(fwidth(u0), fwidth(v0)), 1e-4);
          float k = exp2(ceil(log2(max(1.0, 3.5 / cellPx))));
          float u = u0 / k, v = v0 / k;
          vec2 cell = floor(vec2(u, v)), f = fract(vec2(u, v));
          float win = step(.22, f.x) * step(f.x, .78) * step(.28, f.y) * step(f.y, .8);
          float r = h21(cell + floor(vWP.xz / (37. * k)) + k * 17.0);
          float onFrac = (.10 + .22 * uNight) / sqrt(k);    // merged cells are larger, so fewer are lit
          float on = step(r, onFrac);
          vec3 warm = vec3(1., .70, .36), cool = vec3(.62, .82, 1.);
          vec3 col = mix(warm, cool, step(.78, h21(cell * 1.7 + k)));
          diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * 0.55, win * 0.5);
          diffuseColor.rgb *= mix(1.0, 0.42, uNight);
          totalEmissiveRadiance += col * win * on * (0.04 + 1.2 * uNight) * side;
          // far away (many merged cells) add the averaged glow of the windows too small to draw
          totalEmissiveRadiance += mix(warm, cool, 0.22) * (.10 + .22 * uNight) * 0.27 * 1.2 * uNight * side * smoothstep(4.0, 32.0, k) * 0.8;
        }
`);
    };
    return m;
  }
  const matRes = windowMaterial({ roughness: 0.85, metalness: 0.05 });
  const matGlass = windowMaterial({ roughness: 0.22, metalness: 0.7, envMapIntensity: 0.9 });
  const matLandmark = windowMaterial({ color: 0x2b3440, roughness: 0.25, metalness: 0.85, envMapIntensity: 0.7 });
  const bldGroup = new THREE.Group(); group.add(bldGroup);
  const cBrick = new THREE.Color('#6d4a3c'), cStone = new THREE.Color('#9d978a'), cNew = new THREE.Color('#7b8791'), cGlass = new THREE.Color('#4f6f8c');

  function buildBuildings(target) {
    bldGroup.clear();
    const totHH = D.areas.reduce((s, a) => s + a.stats.households, 0);
    const totJobs = D.areas.reduce((s, a) => s + a.stats.jobs, 0);
    const res = [], glass = [];
    for (const a of D.areas) {
      const r = rng(a.num * 7919 + 13), st = a.stats;
      const n = Math.max(25, Math.round(target * (0.75 * st.households / totHH + 0.25 * st.jobs / totJobs)));
      const jobDensity = st.jobs / Math.max(st.area_km2, 0.1);
      const towers = jobDensity > 15000 ? Math.round(st.jobs / 2200) : 0;
      const pSingle = st.single_family_share, pLarge = st.large_multi_share;
      const empty = Math.min(0.85, (st.open_pct + 0.5 * st.industrial_pct) / 100);
      const xs = a.rings.flat().map(p => p[0]), zs2 = a.rings.flat().map(p => p[1]);
      const [x0, x1, z0, z1] = [Math.min(...xs), Math.max(...xs), Math.min(...zs2), Math.max(...zs2)];
      // towers cluster around the area's job centre (its centroid)
      let placed = 0, tries = 0;
      while (placed < n + towers && tries < (n + towers) * 40) {
        tries++;
        const tower = placed < towers;
        let x, z;
        if (tower) { const ang = r() * 6.283, rad = Math.sqrt(r()) * Math.min(x1 - x0, z1 - z0) * 0.32; x = a.c[0] + Math.cos(ang) * rad; z = a.c[1] + Math.sin(ang) * rad; }
        else { x = x0 + r() * (x1 - x0); z = z0 + r() * (z1 - z0); }
        // keep the drawn streets clear: blocks are 201 m (E-W) by 100.6 m (N-S)
        const [ge, gn] = toGrid(x, z);
        const bx = ((ge % 201.17) + 201.17) % 201.17, bz = ((gn % 100.58) + 100.58) % 100.58;
        if (bx < 14 || bx > 187 || bz < 10 || bz > 90) continue;
        if (!a.rings.some(rg => pointInRing(x, z, rg))) continue;
        if (!tower && r() < empty) continue;
        let w, d, h, col;
        if (tower) { w = 26 + r() * 34; d = 26 + r() * 34; h = 70 + Math.pow(r(), 1.5) * 230; col = (r() < 0.65 ? cGlass : cStone).clone(); }
        else {
          const u = r();
          if (u < pSingle) { w = 7 + r() * 5; d = 12 + r() * 8; h = 5 + r() * 5; }
          else if (u < 1 - pLarge) { w = 9 + r() * 10; d = 18 + r() * 14; h = 9 + r() * 7; }
          else { w = 20 + r() * 25; d = 20 + r() * 25; h = 22 + Math.pow(r(), 2) * 110; }
          col = (r() < 0.55 ? cBrick : cNew).clone().lerp(cStone, r() * 0.35);
        }
        col.offsetHSL(0, 0, (r() - 0.5) * 0.08);
        (tower || h > 60 ? glass : res).push({ x, z, w, d, h, col, area: a.num });
        placed++;
      }
    }
    const M = new THREE.Matrix4(), q = new THREE.Quaternion();
    for (const [list, mat] of [[res, matRes], [glass, matGlass]]) {
      const mesh = new THREE.InstancedMesh(box, mat, Math.max(list.length, 1));
      list.forEach((b, i) => { M.compose(new THREE.Vector3(b.x, 0, b.z), q, new THREE.Vector3(b.w, b.h, b.d)); mesh.setMatrixAt(i, M); mesh.setColorAt(i, b.col); });
      mesh.count = list.length; mesh.castShadow = mesh.receiveShadow = true;
      bldGroup.add(mesh);
    }
    for (const L of D.landmarks) {   // reference towers (heights from the landmark file; schematic footprint)
      const m = new THREE.Mesh(box, matLandmark); m.scale.set(46, L.h, 46); m.position.set(L.pos[0], 0, L.pos[1]); m.castShadow = true;
      bldGroup.add(m);
    }
    return res.length + glass.length;
  }

  // real footprints from the City of Chicago portal (on request)
  const realGroup = new THREE.Group(); group.add(realGroup);
  function addFootprints(list, toLocal) {
    const shapes = [];
    for (const f of list) for (const ring of f.rings) {
      const s = new THREE.Shape(ring.map(([lo, la]) => { const [x, z] = toLocal(lo, la); return new THREE.Vector2(x, -z); }));
      const g = new THREE.ExtrudeGeometry(s, { depth: f.heightM, bevelEnabled: false }); g.rotateX(-Math.PI / 2);
      shapes.push(g);
    }
    for (const g of shapes) realGroup.add(new THREE.Mesh(g, matRes));
    return shapes.length;
  }

  return { group, areaFill, outlines, outlineMat, bldGroup, buildBuildings, addFootprints, lake, land, grid, uniforms: { time, night } };
}
