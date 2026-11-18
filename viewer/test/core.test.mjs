import test from 'node:test';
import assert from 'node:assert/strict';
import { segmentIndex, positionAt, sunPosition, pointInRing, parseFootprint, clockLabel, utcMs, utmForward, STORY_M, alongShape, bestShape, snapshotAge } from '../src/core.js';
import { readFileSync } from 'node:fs';

const segs = [[0, 100, 0, 0, 0, 0, 0, 0], [100, 110, 8, 0, 0, 100, 0, 2], [110, 500, 1, 100, 0, 100, 0, 0]];

test('segment lookup matches engine rule', () => {
  assert.equal(segmentIndex(segs, -5), 0);
  assert.equal(segmentIndex(segs, 0), 0);
  assert.equal(segmentIndex(segs, 99.9), 0);
  assert.equal(segmentIndex(segs, 100), 1);
  assert.equal(segmentIndex(segs, 110), 2);
  assert.equal(segmentIndex(segs, 9999), 2);
});

test('interpolation mid-trip', () => {
  assert.deepEqual(positionAt(segs, 105), [50, 0]);
  assert.deepEqual(positionAt(segs, 300), [100, 0]);
});

test('positions equal the Python engine on exported fixtures', () => {
  const fx = JSON.parse(readFileSync(new URL('./fixtures/positions.json', import.meta.url)));
  for (const c of fx.cases) {
    const p = positionAt(c.segs, c.t);
    assert.ok(Math.abs(p[0] - c.xy[0]) < 1e-6 && Math.abs(p[1] - c.xy[1]) < 1e-6, JSON.stringify(c));
  }
});

test('UTM forward agrees with pyproj', () => {
  const fx = JSON.parse(readFileSync(new URL('./fixtures/utm.json', import.meta.url)));
  for (const [lon, lat, E, N] of fx) {
    const [e, n] = utmForward(lon, lat, 16);
    assert.ok(Math.abs(e - E) < 0.01 && Math.abs(n - N) < 0.01, `${lon},${lat}: ${e},${n} vs ${E},${N}`);
  }
});

test('sun: noon high, midnight below horizon in Chicago on 2020-10-05 (CDT)', () => {
  const noon = sunPosition(utcMs('2020-10-05', 12 * 60 + 45, -5), 41.88, -87.63).elevation * 180 / Math.PI;
  const mid = sunPosition(utcMs('2020-10-05', 0, -5), 41.88, -87.63).elevation * 180 / Math.PI;
  // solar declination on 5 Oct is about -4.8 deg, so solar-noon elevation ~ 90 - 41.88 - 4.8 = 43.3 deg
  assert.ok(Math.abs(noon - 43.3) < 1.5, `noon elevation ${noon}`);
  assert.ok(mid < -30, `midnight elevation ${mid}`);
});

test('point in ring', () => {
  const sq = [[0, 0], [10, 0], [10, 10], [0, 10]];
  assert.equal(pointInRing(5, 5, sq), true);
  assert.equal(pointInRing(15, 5, sq), false);
});

test('footprint parser on the verified portal record (bldg_id 729719)', () => {
  const row = { bldg_id: '729719', stories: '2', no_stories: '0', year_built: '1899',
    the_geom: { type: 'MultiPolygon', coordinates: [[[[-87.6667306636366, 41.707976033242225], [-87.66686799082457, 41.70797682976896], [-87.66686709803044, 41.70806327088082], [-87.6667306636366, 41.707976033242225]]]] } };
  const f = parseFootprint(row);
  assert.equal(f.heightM, 2 * STORY_M);
  assert.equal(f.yearBuilt, 1899);
  assert.equal(f.rings.length, 1);
  assert.equal(parseFootprint({ the_geom: null }), null);
  assert.equal(parseFootprint({ stories: '0', no_stories: '0', the_geom: row.the_geom }).heightSource, 'unknown (drawn 6 m)');
});

test('clock label', () => {
  assert.equal(clockLabel('2020-10-05', 0), 'Mon 5 Oct 2020, 00:00');
  assert.equal(clockLabel('2020-10-05', 1440 * 6 + 23 * 60 + 59), 'Sun 11 Oct 2020, 23:59');
});

test('alongShape and bestShape equal the Python implementation on GTFS shapes', () => {
  const fx = JSON.parse(readFileSync(new URL('./fixtures/along.json', import.meta.url)));
  for (const c of fx.cases) {
    const p = alongShape(c.shape, c.p0, c.p1, c.f);
    assert.ok(Math.abs(p[0] - c.xy[0]) < 1e-6 && Math.abs(p[1] - c.xy[1]) < 1e-6, JSON.stringify([p, c.xy]));
  }
  for (const c of fx.best.cases) {
    const b = bestShape(fx.best.shapes, c.p0, c.p1);
    assert.equal(fx.best.shapes.indexOf(b), c.index);
  }
});

test('snapshot age and staleness', () => {
  const t = Date.parse('2026-11-17T14:00:00Z');
  assert.deepEqual(snapshotAge('2026-11-17T13:50:00+00:00', t), { ageMin: 10, stale: false });
  assert.equal(snapshotAge('2026-11-17T13:20:00+00:00', t).stale, true);
  assert.equal(snapshotAge('not a date', t).stale, true);
});

test('reliability colours run from good to bad and clamp', async () => {
  const { relColor } = await import('../src/core.js');
  assert.deepEqual(relColor('bunching_share', 0), [0.2, 0.85, 0.75]);
  assert.deepEqual(relColor('bunching_share', 0.3), [1.0, 0.25, 0.2]);
  assert.deepEqual(relColor('bunching_share', 5), relColor('bunching_share', 0.3));
  assert.deepEqual(relColor('service_delivered', 1), [0.2, 0.85, 0.75]);
  assert.deepEqual(relColor('service_delivered', 0.6), [1.0, 0.25, 0.2]);
  assert.equal(relColor('service_delivered', null), null);
  assert.equal(relColor('nope', 0.1), null);
});

test('local frame -> lon/lat matches pyproj to centimetres', async () => {
  const { localToLonLat, utmForward, utmInverse } = await import('../src/core.js');
  const fx = JSON.parse((await import('node:fs')).readFileSync(new URL('./fixtures_lonlat.json', import.meta.url), 'utf8'));
  for (const p of fx.pts) {
    const [lon, lat] = localToLonLat(p.x, p.z, fx.origin);
    // 1e-7 degrees is about 1 cm
    assert.ok(Math.abs(lon - p.lon) < 1e-7 && Math.abs(lat - p.lat) < 1e-7, `${lon},${lat} vs ${p.lon},${p.lat}`);
    const [E, N] = utmForward(p.lon, p.lat);
    const [lo2, la2] = utmInverse(E, N);
    assert.ok(Math.abs(lo2 - p.lon) < 1e-9 && Math.abs(la2 - p.lat) < 1e-9);
  }
});

test('delayed-live playback loops the observed window at real speed', async () => {
  const { playbackTime, trackPosition } = await import('../src/core.js');
  const t0 = 1_000_000, t1 = t0 + 240_000;                       // 5 polls over 4 minutes
  assert.equal(playbackTime(t0, t1, 5_000_000, 5_000_000).t, t0);
  assert.equal(playbackTime(t0, t1, 5_000_000, 5_060_000).t, t0 + 60_000);   // 60 s later: 60 s into the window
  assert.equal(playbackTime(t0, t1, 5_000_000, 5_250_000).t, t0 + 10_000);   // loops after 240 s
  assert.equal(playbackTime(t0, t1, 5_000_000, 5_060_000).delayMs, 5_060_000 - t0 - 60_000);
  assert.equal(playbackTime(t0, t1, 5_000_000, 5_015_000, 4).t, t0 + 60_000);   // 4x: 15 s of wall time = 60 s observed
  // a straight east-west route: half-way between polls is half-way along the shape
  const shape = [[0, 0], [1000, 0]];
  const track = [[0, 0], [600, 0]], times = [0, 60_000];
  const [x, z] = trackPosition(times, track, [shape], 30_000);
  assert.ok(Math.abs(x - 300) < 1e-6 && Math.abs(z) < 1e-6);
  assert.deepEqual(trackPosition(times, track, [shape], -5), [0, 0]);
  assert.deepEqual(trackPosition(times, track, [shape], 99_000), [600, 0]);
});

import { bearingDeg, bandForHour, patternPosition, stopDistances, offsetAt } from '../src/core.js';
test('wheres my bus geometry', () => {
  assert.equal(bearingDeg(0, -1), 0); assert.equal(bearingDeg(1, 0), 90); assert.equal(bearingDeg(0, 1), 180); assert.equal(bearingDeg(-1, 0), 270);
  assert.deepEqual([3, 4, 7, 12, 16, 20, 23, 0].map(bandForHour), ['night', 'early', 'am_peak', 'midday', 'pm_peak', 'evening', 'night', 'night']);
  const shape = [[0, 0], [0, -1000], [1000, -1000]];                       // north 1 km, then east 1 km
  assert.deepEqual(patternPosition(shape, [[5, -100], [5, -400]], 0), { s: 400, how: 'moved' });
  assert.equal(patternPosition(shape, [[5, -400], [5, -100]], 0), null);   // travelling against the pattern
  assert.equal(patternPosition(shape, [[500, -500]], 0), null);            // 500 m off the shape
  assert.deepEqual(patternPosition(shape, [[3, -300]], 2), { s: 300, how: 'heading' });   // stationary, heading ~north
  assert.equal(patternPosition(shape, [[3, -300]], 180), null);            // stationary, heading south
  assert.deepEqual(patternPosition(shape, [[3, -300]], 0), { s: 300, how: 'unconfirmed' });
  assert.deepEqual(patternPosition(shape, [[500, -1004], [800, -1004]], 0), { s: 1800, how: 'moved' });
  const stops = [['a', 'A', 0, 0], ['b', 'B', 0, -1000], ['c', 'C', 1000, -1000]];
  const S = stopDistances(shape, stops);
  assert.deepEqual(S, [0, 1000, 2000]);
  assert.equal(offsetAt(S, [0, 4, 10], 500), 2);
  assert.equal(offsetAt(S, [0, 4, 10], 1500), 7);
  assert.equal(offsetAt(S, [0, 4, 10], 2600), 10);
});
