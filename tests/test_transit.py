import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from simchi.transit.gtfs import active_services, build_extract, gtfs_seconds, read_feed
from simchi.transit.interp import along_shape, best_shape

FIX = Path(__file__).parent / "fixtures" / "gtfs_small"


@pytest.fixture(scope="module")
def extract(tmp_path_factory):
    out = tmp_path_factory.mktemp("transit")
    build_extract(FIX, out, source_sha256="test")
    return {n: json.loads((out / f"{n}.json").read_text()) for n in
            ("routes", "stations", "stops", "patterns", "service", "shapes", "meta")}


def test_gtfs_times_past_midnight():
    import pandas as pd
    assert list(gtfs_seconds(pd.Series(["08:00:00", "24:30:15"]))) == [28800, 88215]


def test_calendar_and_exceptions():
    feed = read_feed(FIX)
    assert active_services(feed, date(2026, 11, 17)) == {"WK"}          # Tuesday
    assert active_services(feed, date(2026, 11, 21)) == {"SA"}          # Saturday
    assert active_services(feed, date(2026, 11, 26)) == {"SA"}          # Thanksgiving: WK removed, SA added


def test_routes_and_colours(extract):
    r = {x["id"]: x for x in extract["routes"]}
    assert r["9"]["type"] == 3 and r["Y"]["type"] == 1 and r["Y"]["color"] == "#F9E300"


def test_service_headways(extract):
    s = {(x["route"], x["direction"], x["day"], x["hour"]): x for x in extract["service"]}
    assert s[("9", 0, "weekday", 8)]["trips"] == 3 and s[("9", 0, "weekday", 8)]["headway_min"] == 20.0
    assert s[("9", 0, "weekday", 24)]["trips"] == 1                      # after-midnight trip kept on its service day
    assert s[("9", 0, "saturday", 9)]["trips"] == 1


def test_patterns_grouped_by_terminals(extract):
    y = [p for p in extract["patterns"] if p["route"] == "Y"]
    # both Yellow trips share direction_id 1 but run opposite ways: two patterns
    assert sorted((p["stops"][0], p["stops"][-1]) for p in y) == [("30027", "30176"), ("30175", "30026")]
    p9 = [p for p in extract["patterns"] if p["route"] == "9" and p["direction"] == 0][0]
    assert p9["stops"] == ["100", "101", "102"] and p9["trips_weekday"] == 4
    # median offsets in the AM peak band: trips at 08:00, 08:10, 08:20 take 12, 13, 12 min
    assert p9["offsets_min"]["am_peak"] == [0.0, 6.0, 12.0]


def test_stations_and_shapes_in_local_frame(extract):
    st = {s["id"]: s for s in extract["stations"]}
    assert set(st) == {"40900", "41680"} and st["40900"]["lines"] == ["Y"]
    sh = extract["shapes"]["S9N"]
    assert len(sh) >= 2 and sh[0][1] > sh[-1][1]           # northbound: z decreases (north is -z)


def test_along_shape_follows_the_polyline():
    shape = np.array([[0, 0], [100, 0], [100, 100]], float)
    # halfway in time between (50, 0) and (100, 50): 100 m of shape, so 50 m along -> corner
    x, z = along_shape(shape, (50, 0), (100, 50), 0.5)
    assert abs(x - 100) < 1e-9 and abs(z - 0) < 1e-9
    # straight-line fallback when the second point is behind the first
    x, z = along_shape(shape, (100, 50), (50, 0), 0.5)
    assert abs(x - 75) < 1e-9 and abs(z - 25) < 1e-9


def test_best_shape_picks_forward_direction():
    north = [[0, 0], [0, -1000]]
    south = [[0, -1000], [0, 0]]
    assert best_shape([south, north], (0, -100), (0, -300)) == pytest.approx(np.array(north, float))
    assert best_shape([north], (500, 0), (500, -10)) is None


def test_committed_extract_matches_the_pinned_feed():
    from simchi.data.cds import source
    from simchi.transit.gtfs import load_extract
    meta = load_extract("meta")
    assert meta["source_sha256"] == source("gtfs_cta")["sha256"]
    assert meta["counts"]["routes"] == 132 and meta["counts"]["rail_routes"] == 8
