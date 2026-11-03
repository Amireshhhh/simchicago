// Pure functions shared by the viewer and its tests (no DOM, no three.js).

export const KINDS = ['home', 'work', 'school', 'aftercare', 'shop', 'social', 'leisure', 'errand', 'trip', 'wait'];
export const MODES = ['', 'walk', 'car', 'transit', 'other'];

// Segment layout: [t0, t1, kind, x0, z0, x1, z1, mode], times in minutes since the run start.

/** Index of the segment active at time t (t0 <= t < t1); clamps to the first/last segment.
 *  Mirrors simchi.sim.engine.Simulation.positions: k = (#segments with t0 <= t) - 1. */
export function segmentIndex(segs, t) {
  let lo = 0, hi = segs.length - 1;
  if (t < segs[0][0]) return 0;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (segs[mid][0] <= t) lo = mid; else hi = mid - 1;
  }
  return lo;
}

/** Linear interpolation of position inside a segment, identical to the engine's rule. */
export function positionAt(segs, t, out = [0, 0]) {
  const s = segs[segmentIndex(segs, t)];
  const f = Math.min(1, Math.max(0, (t - s[0]) / Math.max(s[1] - s[0], 1e-9)));
  out[0] = s[3] + f * (s[5] - s[3]);
  out[1] = s[4] + f * (s[6] - s[4]);
  return out;
}

/** Solar elevation and azimuth (radians) — NOAA low-precision algorithm, ~1 degree accuracy.
 *  Used only for lighting. utcMs: UNIX time in ms. */
export function sunPosition(utcMs, latDeg, lonDeg) {
  const rad = Math.PI / 180;
  const d = utcMs / 86400000 + 2440587.5 - 2451545.0;          // days since J2000
  const g = (357.529 + 0.98560028 * d) * rad;                    // mean anomaly
  const q = 280.459 + 0.98564736 * d;                            // mean longitude (deg)
  const L = (q + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
  const e = (23.439 - 0.00000036 * d) * rad;
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const gmst = (18.697374558 + 24.06570982441908 * d) % 24;
  const lst = (gmst * 15 + lonDeg) * rad;
  const H = lst - ra;
  const lat = latDeg * rad;
  const el = Math.asin(Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(H));
  const az = Math.atan2(-Math.sin(H), Math.tan(dec) * Math.cos(lat) - Math.sin(lat) * Math.cos(H)); // from north, clockwise
  return { elevation: el, azimuth: az };
}

/** Even-odd point-in-polygon for one ring of [x, z] points. */
export function pointInRing(x, z, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, zi] = ring[i], [xj, zj] = ring[j];
    if ((zi > z) !== (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

/** Deterministic PRNG (mulberry32). */
export function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Parse one City of Chicago Building Footprints row (dataset syp8-uezg) into
 *  {rings: [[lon, lat], ...][], heightM, heightSource}. 12 ft per story is a stated assumption. */
export const STORY_M = 3.6576;
export function parseFootprint(row) {
  const g = row.the_geom;
  if (!g || !g.coordinates) return null;
  const polys = g.type === 'MultiPolygon' ? g.coordinates : g.type === 'Polygon' ? [g.coordinates] : [];
  if (!polys.length) return null;
  const st = [Number(row.stories), Number(row.no_stories)].find(v => Number.isFinite(v) && v > 0);
  return {
    rings: polys.map(p => p[0]),
    heightM: st ? st * STORY_M : 6,
    heightSource: st ? 'stories' : 'unknown (drawn 6 m)',
    yearBuilt: Number(row.year_built) > 1800 ? Number(row.year_built) : null,
  };
}

/** Time label 'Mon 5 Oct 2020, 08:30' for minutes since the run start (local clock of the run). */
export function clockLabel(startDate, t) {
  const [Y, M, D] = startDate.split('-').map(Number);
  const day = Math.floor(t / 1440), m = ((t % 1440) + 1440) % 1440;
  const date = new Date(Date.UTC(Y, M - 1, D + day));
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][date.getUTCDay()];
  const mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][date.getUTCMonth()];
  const hh = String(Math.floor(m / 60)).padStart(2, '0'), mm = String(Math.floor(m % 60)).padStart(2, '0');
  return `${wd} ${date.getUTCDate()} ${mo} ${date.getUTCFullYear()}, ${hh}:${mm}`;
}

/** UTC milliseconds of local run time t, for a fixed UTC offset in hours (CDT = -5). */
export function utcMs(startDate, t, utcOffsetH) {
  const [Y, M, D] = startDate.split('-').map(Number);
  return Date.UTC(Y, M - 1, D) + (t - utcOffsetH * 60) * 60000;
}

/** WGS84 -> UTM (Krüger series, n^4 terms; sub-millimetre within the zone). Returns [E, N] metres. */
export function utmForward(lonDeg, latDeg, zone = 16) {
  const a = 6378137, f = 1 / 298.257223563, k0 = 0.9996;
  const n = f / (2 - f), A = a / (1 + n) * (1 + n * n / 4 + n ** 4 / 64);
  const al = [0, n / 2 - 2 * n * n / 3 + 5 * n ** 3 / 16 + 41 * n ** 4 / 180, 13 * n * n / 48 - 3 * n ** 3 / 5 + 557 * n ** 4 / 1440,
    61 * n ** 3 / 240 - 103 * n ** 4 / 140, 49561 * n ** 4 / 161280];
  const lat = latDeg * Math.PI / 180, lon0 = ((zone - 1) * 6 - 180 + 3) * Math.PI / 180, dl = lonDeg * Math.PI / 180 - lon0;
  const e = Math.sqrt(f * (2 - f));
  const t = Math.sinh(Math.atanh(Math.sin(lat)) - e * Math.atanh(e * Math.sin(lat)));
  const xi = Math.atan2(t, Math.cos(dl)), eta = Math.atanh(Math.sin(dl) / Math.sqrt(1 + t * t));
  let x = eta, y = xi;
  for (let j = 1; j <= 4; j++) { x += al[j] * Math.cos(2 * j * xi) * Math.sinh(2 * j * eta); y += al[j] * Math.sin(2 * j * xi) * Math.cosh(2 * j * eta); }
  return [500000 + k0 * A * x, k0 * A * y];
}
