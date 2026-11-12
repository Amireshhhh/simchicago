"""Operations tools: holding rule, crowding forecast, anomaly detectors."""

import numpy as np
import pandas as pd

from simchi.ops import anomalies as AN
from simchi.ops import crowding as CR
from simchi.ops import holding as HO


def test_holding_rule():
    # bunched (front 1 min < 0.5 x 8) with a long back headway: hold half the difference, capped at 2
    assert list(HO.recommend([1.0, 1.0, 6.0, np.nan], [3.0, 13.0, 1.0, 9.0], 8.0)) == [1.0, 2.0, 0.0, 0.0]


def test_holding_simulation_is_paired_and_labelled():
    a, b = HO.simulate(False, 3, hours=2.0), HO.simulate(True, 3, hours=2.0)
    assert a["hold_min_per_hour"] == 0 and b["hold_min_per_hour"] > 0
    again = HO.simulate(False, 3, hours=2.0)                        # deterministic per seed
    assert all(again[k] == v or (v != v and again[k] != again[k]) for k, v in a.items())


def test_crowding_forecasts_use_only_data_a_week_old():
    days = pd.date_range("2026-01-05", periods=63, freq="D")         # starts on a Monday
    dt = np.where(days.weekday == 6, "U", np.where(days.weekday == 5, "A", "W"))
    rides = np.arange(len(days), dtype=float) * 10 + 100              # rising: any leak of the target would show
    df = pd.DataFrame({"id": "x", "date": days, "daytype": dt, "rides": rides})
    F = CR.forecasts(df, "2026-02-23", "2026-03-08")
    r = F.set_index("date")
    d = pd.Timestamp("2026-03-02")                                    # a Monday
    assert r.at[d, "B_naive"] == df.set_index("date").at[d - pd.Timedelta(days=7), "rides"]
    prev_mondays = df[(df["date"] <= d - pd.Timedelta(days=7)) & (df["date"].dt.weekday == 0)]["rides"].iloc[-4:]
    assert r.at[d, "M_med4"] == np.median(prev_mondays)
    assert (r["M_med4"] < r["rides"]).all() and (r["B_naive"] < r["rides"]).all()


def test_anomaly_detectors_on_a_constructed_feed():
    shapes = {"R": [np.array([[0.0, 0.0], [10000.0, 0.0]])]}
    rows = []
    for t in (0.0, 60.0, 120.0):
        rows += [{"poll": t, "id": "ok", "route": "R", "direction": 0, "x": 2000 + 5 * t, "z": 0.0},
                 {"poll": t, "id": "jump", "route": "R", "direction": 0, "x": 3000 + 5 * t + (4000 if t == 60 else 0), "z": 0.0},
                 {"poll": t, "id": "stuck", "route": "R", "direction": 0, "x": 5000.0, "z": 2.0},
                 {"poll": t, "id": "layover", "route": "R", "direction": 0, "x": 50.0, "z": 0.0},
                 {"poll": t, "id": "off", "route": "R", "direction": 0, "x": 6000 + 5 * t, "z": 900.0}]
    feed = pd.DataFrame(rows)
    flags = AN.detect(feed, shapes, {("R", 0): 5.0, ("R", 1): 4.0})
    assert flags["jump"] == {"jump"} and flags["stuck"] == {"stuck"} and flags["off_route"] == {"off"}
    assert flags["outage"] == {("R", 1)}
    s = AN.score(flags, {"jump": {"jump"}, "stuck": {"stuck", "missed"}, "off_route": set(), "outage": {("R", 1)}})
    assert s["stuck"] == {"tp": 1, "fp": 0, "fn": 1} and s["off_route"] == {"tp": 0, "fp": 1, "fn": 0}
