"""Reliability metrics from polled positions, on a constructed history with known answers."""

import csv
import gzip
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from simchi.data.cds import load_cds
from simchi.transit import reliability as RL
from simchi.transit.interp import point_at
from simchi.transit.live import HISTORY_FIELDS


@pytest.fixture(scope="module")
def sched():
    return RL.Schedule()


def _write_history(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _route9_history(sched, start_utc, spacing_m=2000.0, n=5, bunch_gap_m=200.0, speed=5.0, delayed=1):
    """Route 9, first direction: n vehicles spaced spacing_m apart plus one vehicle bunched
    bunch_gap_m behind the last, all moving at `speed`; 3 polls 60 s apart."""
    frame = load_cds().frame
    d0 = min(sched.dirs["9"])
    shape, cum = sched.rep[("9", d0)]
    s0 = np.array([1000.0 + i * spacing_m for i in range(n)] + [1000.0 + (n - 1) * spacing_m - bunch_gap_m])
    rows = []
    for k in range(3):
        t = start_utc + timedelta(seconds=60 * k)
        for i, s in enumerate(s0 + speed * 60 * k):
            x, z = point_at(shape, cum, s)
            lon, lat = frame.to_lonlat(x, z)
            rows.append({"poll_utc": t.isoformat(), "mode": "bus", "id": f"bus:{i}", "route": "9",
                         "lat": float(lat), "lon": float(lon), "hdg": 0, "t_utc": t.isoformat(),
                         "dly": i < delayed, "pid": "111", "pdist": int(s / 0.3048)})
    return rows


def test_headways_bunching_and_delay_flags_are_recovered(tmp_path, sched):
    start = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)          # Tuesday 08:00 in Chicago
    _write_history(tmp_path / "vehicles-1" / "history.csv.gz", _route9_history(sched, start))
    df = RL.load_history([tmp_path / "vehicles-1" / "history.csv.gz"])
    assert set(df["day"]) == {"weekday"} and set(df["hour"]) == {8}
    P = RL.positions(df, sched, load_cds().frame)
    assert len(P) == 18 and P["direction"].nunique() == 1                 # all moving the same way
    assert np.allclose(P["v"].dropna(), 5.0, rtol=0.03)                   # speed recovered from movement
    H = RL.headways(P, sched)
    h = np.sort(H["headway_min"].to_numpy())
    # per poll: 4 gaps of 2000 m (6.67 min at 5 m/s) and the bunched pair split one gap into 200 m + 1800 m
    assert len(H) == 3 * 5
    assert np.allclose(h[:3], 200 / 5 / 60, rtol=0.05)
    assert np.allclose(h[-9:], 2000 / 5 / 60, rtol=0.05)
    M = RL.metrics(P, H, sched)
    row = M.iloc[0]
    sh = sched.headway("9", min(sched.dirs["9"]), "weekday", 8)
    assert row["scheduled_headway_min"] == pytest.approx(sh)
    assert row["bunching_share"] == pytest.approx(np.mean(h < 0.25 * sh))
    assert row["delayed_share"] == pytest.approx(1 / 6)
    assert row["vehicles_per_poll"] == 6
    assert row["service_delivered"] == pytest.approx(6 / sched.in_service("9", min(sched.dirs["9"]), "weekday", 8))


def test_report_and_viewer_layer(tmp_path, sched):
    start = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
    hist = tmp_path / "h"
    _write_history(hist / "vehicles-1" / "history.csv.gz", _route9_history(sched, start))
    _write_history(hist / "vehicles-2" / "history.csv.gz", _route9_history(sched, start + timedelta(minutes=5)))
    res = RL.report(sorted(hist.glob("*/history.csv.gz")), tmp_path / "rep")
    assert res["coverage"]["runs"] == 2 and res["coverage"]["polls"] == 6
    assert (tmp_path / "rep" / "routes.csv").exists()
    RL.viewer_layer(tmp_path / "rep" / "routes.csv", tmp_path / "rel.json")
    v = json.loads((tmp_path / "rel.json").read_text())
    assert v["label"] == "observed" and "9" in v["routes"]


def test_polling_bias_simulation_is_labelled_and_consistent():
    r = RL.polling_bias(n_days=5, speed_cv=0.0)
    assert r["label"] == "simulated"
    # with identical speeds, snapshot spacing is the true headway: CV is recovered closely
    assert abs(r["bias"]["headway_cv"]) < 0.05


def test_schedule_handles_one_direction_code_for_both_ways(sched):
    # every Yellow Line trip is coded direction 1; scheduled trips per way are half the total
    assert ("Y", 1) in sched.both_ways
    assert sched.trips("Y", 1, "weekday", 8) == sched.service[("Y", 1, "weekday", 8)] / 2


def test_crime_join_is_descriptive_and_runs():
    import pandas as pd
    from simchi.world import build_world
    routes = pd.DataFrame({"route": ["9", "8", "66", "79", "4", "3"], "mode": "bus",
                           "bunching_share": [0.1, 0.2, 0.05, 0.3, 0.15, 0.12], "gap_share": [0.1] * 6,
                           "service_delivered": [0.9, 0.8, 1.0, 0.7, 0.95, 0.85], "delayed_share": [0.05] * 6})
    out = RL.crime_join(routes, build_world())
    assert out["label"] == "descriptive association, not causal"
    assert "crimes_all_by_area vs bunching_share" in out["correlations"]
    assert len(out["routes"]) == 6 and all(r["crimes_all_by_area_per_1000"] > 0 for r in out["routes"])
