"""Benches layer: source merging and the capture-recapture estimate (offline fixtures)."""

import pytest

from simchi import benches as B


def osm(elements):
    return {"osm3s": {"timestamp_osm_base": "2026-11-18T00:00:00Z"}, "elements": elements}


def test_kinds_and_way_centres():
    o = B.osm_points(osm([
        {"type": "node", "id": 1, "lat": 41.88, "lon": -87.63, "tags": {"amenity": "bench"}},
        {"type": "way", "id": 2, "center": {"lat": 41.89, "lon": -87.62}, "tags": {"leisure": "picnic_table"}},
        {"type": "node", "id": 3, "lat": 41.90, "lon": -87.64, "tags": {"highway": "bus_stop", "shelter": "yes"}},
        {"type": "node", "id": 4, "lat": 41.91, "lon": -87.64, "tags": {"highway": "bus_stop", "bench": "yes", "shelter": "yes"}},
    ]))
    assert [p["kind"] for p in o] == ["bench", "picnic_table", "shelter", "bus_stop_bench"]
    assert o[1]["lat"] == 41.89 and [p["shelter"] for p in o] == [False, False, True, True]


def test_matching_is_one_to_one_within_radius():
    a = [{"lon": -87.63, "lat": 41.88}, {"lon": -87.6301, "lat": 41.88}]        # ~8 m apart
    b = [{"lon": -87.63005, "lat": 41.88}, {"lon": -87.60, "lat": 41.88}]       # second is ~2.5 km away
    m = B.match(a, b, radius=40)
    assert len(m) == 1 and m[0][1] == 0


def test_chapman_estimator_matches_the_formula():
    e = B.chapman(100, 80, 40)
    assert e["N"] == pytest.approx(101 * 81 / 41 - 1)
    var = 101 * 81 * 60 * 40 / (41 ** 2 * 42)
    assert e["ci95"][1] - e["N"] == pytest.approx(1.96 * var ** 0.5)
    assert B.chapman(50, 50, 50)["N"] == pytest.approx(50)                         # identical lists: N = a


def test_build_merges_matched_shelters_and_labels_sources():
    o = osm([{"type": "node", "id": 3, "lat": 41.90, "lon": -87.64, "tags": {"highway": "bus_stop", "shelter": "yes"}},
             {"type": "node", "id": 5, "lat": 41.80, "lon": -87.60, "tags": {"amenity": "bench"}}])
    cta = [{"latitude": "41.90001", "longitude": "-87.64001", "cta_stop_name": "A & B"},       # same shelter as OSM node 3
           {"latitude": "41.95", "longitude": "-87.70", "cta_stop_name": "C & D"}]
    fc, s = B.build(o, cta)
    assert s["features"] == 3 and s["shelter_capture_recapture"]["m"] == 1
    assert "ODbL" in fc["license"]
    assert {f["properties"]["source"] for f in fc["features"]} == {"OpenStreetMap", "CTA (2016 list)"}
