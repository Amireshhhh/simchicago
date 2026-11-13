// Renderer, camera, sky, lighting, post-processing and environment.
import * as THREE from 'three';
import { MapControls } from 'three/examples/jsm/controls/MapControls.js';
import { Sky } from 'three/examples/jsm/objects/Sky.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { FXAAShader } from 'three/examples/jsm/shaders/FXAAShader.js';
import { rng } from './core.js';

export const QUALITY = {
  low: { pr: 1, bloom: false, fxaa: true, bld: 9000, shadows: false },
  medium: { pr: Math.min(devicePixelRatio, 1.5), bloom: true, fxaa: true, bld: 26000, shadows: false },
  high: { pr: Math.min(devicePixelRatio, 2), bloom: true, fxaa: false, bld: 60000, shadows: true },
};

/** Sun direction in scene coordinates (x east, y up, z south) from elevation/azimuth. */
export function sunVector(el, az, out = new THREE.Vector3()) {
  return out.set(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
}

export function createScene(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance', logarithmicDepthBuffer: true });
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.9;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, innerWidth / innerHeight, 2, 400000);
  const controls = new MapControls(camera, canvas);
  Object.assign(controls, { enableDamping: true, dampingFactor: 0.07, maxPolarAngle: Math.PI * 0.47, minDistance: 30, maxDistance: 90000, screenSpacePanning: false, zoomSpeed: 1.2 });

  // physical sky (Preetham) + a star dome that fades in after dusk
  const sky = new Sky();
  sky.scale.setScalar(350000);
  const su = sky.material.uniforms;
  su.turbidity.value = 6; su.rayleigh.value = 1.6; su.mieCoefficient.value = 0.004; su.mieDirectionalG.value = 0.86;
  scene.add(sky);
  const starGeo = new THREE.BufferGeometry();
  const r = rng(42), nStars = 2600, sp = new Float32Array(nStars * 3), ss = new Float32Array(nStars);
  for (let i = 0; i < nStars; i++) {
    const u = r() * 2 - 1, th = r() * Math.PI * 2, h = Math.abs(u) * 0.98 + 0.02, rr = Math.sqrt(1 - h * h);
    sp.set([Math.cos(th) * rr * 300000, h * 300000, Math.sin(th) * rr * 300000], i * 3); ss[i] = 0.6 + r() * r() * 2.4;
  }
  starGeo.setAttribute('position', new THREE.BufferAttribute(sp, 3));
  starGeo.setAttribute('size', new THREE.BufferAttribute(ss, 1));
  const starMat = new THREE.ShaderMaterial({
    uniforms: { night: { value: 0 }, pr: { value: 1 } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false,
    vertexShader: 'attribute float size; uniform float pr; varying float vS; void main(){ vS = size; vec4 mv = modelViewMatrix*vec4(position,1.); gl_Position = projectionMatrix*mv; gl_PointSize = size*pr; }',
    fragmentShader: 'uniform float night; varying float vS; void main(){ float d = length(gl_PointCoord-.5); if(d>.5) discard; gl_FragColor = vec4(vec3(.85,.9,1.)*(1.-d*2.)*night*min(vS,1.4), 1.); }',
  });
  const stars = new THREE.Points(starGeo, starMat); stars.frustumCulled = false; scene.add(stars);

  scene.fog = new THREE.FogExp2(0x0b1626, 0.0000105);
  const hemi = new THREE.HemisphereLight(0xbcd7ff, 0x1b2230, 0.55);
  const sun = new THREE.DirectionalLight(0xfff2e0, 2.4);
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { near: 10, far: 30000, left: -3000, right: 3000, top: 3000, bottom: -3000 });
  const moon = new THREE.DirectionalLight(0x8fb4ff, 0.0);
  const ambient = new THREE.AmbientLight(0x3a5a8f, 0.2);
  scene.add(hemi, sun, sun.target, moon, moon.target, ambient);

  // environment map rendered from the sky only (reflections on glass towers and the lake)
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envScene = new THREE.Scene();
  const envSky = new Sky(); envSky.scale.setScalar(1000); envScene.add(envSky);
  let envRT = null, lastEnvSun = new THREE.Vector3(9, 9, 9);
  function updateEnv(sunDir) {
    if (sunDir.distanceTo(lastEnvSun) < 0.04) return;
    lastEnvSun.copy(sunDir);
    const eu = envSky.material.uniforms;
    for (const k of ['turbidity', 'rayleigh', 'mieCoefficient', 'mieDirectionalG']) eu[k].value = su[k].value;
    eu.sunPosition.value.copy(sunDir);
    if (envRT) envRT.dispose();
    envRT = pmrem.fromScene(envScene, 0.02);
    scene.environment = envRT.texture;
    scene.environmentIntensity = THREE.MathUtils.clamp(sunDir.y * 3 + 0.25, 0.08, 1.0);
  }

  // post-processing: render -> bloom (stronger at night) -> FXAA -> output (tone map, sRGB)
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), 0.55, 0.55, 0.82);
  composer.addPass(bloom);
  const fxaa = new ShaderPass(FXAAShader);
  composer.addPass(fxaa);
  composer.addPass(new OutputPass());

  // rain (what-if overlay; no weather data are loaded)
  const rainN = 9000, rainGeo = new THREE.BufferGeometry(), rp = new Float32Array(rainN * 6);
  rainGeo.setAttribute('position', new THREE.BufferAttribute(rp, 3).setUsage(THREE.DynamicDrawUsage));
  const rain = new THREE.LineSegments(rainGeo, new THREE.LineBasicMaterial({ color: 0x9fc4ff, transparent: true, opacity: 0.35, fog: false }));
  rain.frustumCulled = false; rain.visible = false; scene.add(rain);
  const rainSeed = new Float32Array(rainN * 3);
  for (let i = 0; i < rainN; i++) rainSeed.set([r() - 0.5, r(), r() - 0.5], i * 3);
  function updateRain(dt) {
    if (!rain.visible) return;
    const span = THREE.MathUtils.clamp(camera.position.distanceTo(controls.target) * 1.2, 300, 12000);
    const c = controls.target;
    for (let i = 0; i < rainN; i++) {
      rainSeed[i * 3 + 1] = (rainSeed[i * 3 + 1] - dt * 0.9 + 1) % 1;
      const x = c.x + rainSeed[i * 3] * span, z = c.z + rainSeed[i * 3 + 2] * span, y = rainSeed[i * 3 + 1] * span * 0.6;
      rp.set([x, y, z, x + span * 0.002, y - span * 0.012, z], i * 6);
    }
    rainGeo.attributes.position.needsUpdate = true;
  }

  let quality = 'medium';
  function applyQuality(q) {
    quality = q;
    const Q = QUALITY[q];
    renderer.setPixelRatio(Q.pr);
    renderer.setSize(innerWidth, innerHeight);
    composer.setPixelRatio(Q.pr);
    composer.setSize(innerWidth, innerHeight);
    bloom.enabled = Q.bloom;
    fxaa.enabled = Q.fxaa;
    fxaa.material.uniforms.resolution.value.set(1 / (innerWidth * Q.pr), 1 / (innerHeight * Q.pr));
    renderer.shadowMap.enabled = Q.shadows;
    sun.castShadow = Q.shadows;
    starMat.uniforms.pr.value = Q.pr;
  }
  addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); applyQuality(quality); });

  /** Light the scene for a sun direction; returns {day, dusk, night} in [0, 1]. */
  const tmp = new THREE.Vector3();
  let neon = 0;
  const setNeon = v => { neon = v; };
  function setSun(sunDir, rainy) {
    const el = Math.asin(THREE.MathUtils.clamp(sunDir.y, -1, 1));
    const day = THREE.MathUtils.smoothstep(el, -0.1, 0.18);
    const dusk = Math.exp(-((el - 0.02) ** 2) / 0.012);
    const night = 1 - THREE.MathUtils.smoothstep(el, -0.2, -0.02);
    su.sunPosition.value.copy(sunDir);
    su.rayleigh.value = rainy ? 3.2 : 1.6;
    su.turbidity.value = rainy ? 14 : 6;
    sun.position.copy(tmp.copy(sunDir).multiplyScalar(20000).add(controls.target));
    sun.target.position.copy(controls.target);
    sun.intensity = 2.6 * day * (rainy ? 0.35 : 1);
    sun.color.setHSL(0.09, 0.55 * dusk + 0.12, 0.82);
    moon.position.set(controls.target.x - 8000, 9000, controls.target.z + 6000);
    moon.target.position.copy(controls.target);
    moon.intensity = 0.45 * night;
    hemi.intensity = 0.14 + 0.6 * day;
    ambient.intensity = 0.16 + 0.2 * night;
    starMat.uniforms.night.value = night * (rainy ? 0.15 : 1);
    const fogDay = new THREE.Color(rainy ? 0x6f7f92 : 0xa9c3dd), fogNight = new THREE.Color(0x07101e);
    scene.fog.color.copy(fogNight).lerp(fogDay, day).lerp(new THREE.Color(0xe39a6c), dusk * 0.25 * (1 - night));
    scene.fog.density = rainy ? 0.000034 : 0.0000055 + 0.000006 * night;
    bloom.strength = 0.3 + 0.45 * night + 0.12 * neon;
    bloom.threshold = 0.88 - 0.16 * night + 0.06 * neon;
    if (neon) { scene.fog.color.lerp(new THREE.Color(0x12051f), neon); scene.fog.density = 0.000012; }
    renderer.toneMappingExposure = 0.95 + 0.05 * day;
    updateEnv(sunDir);
    return { day, dusk, night };
  }

  return { renderer, scene, camera, controls, composer, bloom, sun, applyQuality, setSun, setNeon, rain, updateRain };
}
