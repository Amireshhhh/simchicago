"""W3 seconds per stop on constructed data with known answers: segment cutting, stop and signal
counts, crossing-time interpolation, traversal extraction, the clustered regression and the
pre-registered pass rule."""

import numpy as np
import pandas as pd
import pytest

from simchi.transit import stop_time as W


def test_cut_segments_drops_short_last_and_the_terminal_pieces():
    # 0-400, 400-800, 800-1200, 1200-1600, 1600-1750 (150 m < 200 m: dropped); then first/last dropped
    assert W.cut_segments(1750.0) == [(400.0, 800.0), (800.0, 1200.0)]
    # 1900: last piece 300 m is kept, then first and last dropped
    assert W.cut_segments(1900.0) == [(400.0, 800.0), (800.0, 1200.0), (1200.0, 1600.0)]


def test_segments_count_stops_and_signals():
    shape = np.array([[0.0, 0.0], [2400.0, 0.0]])
    stops = {"a": (100.0, 5.0), "b": (500.0, -5.0), "c": (700.0, 3.0), "d": (1300.0, 0.0)}
    signals = np.array([[600.0, 10.0], [650.0, 30.0], [1500.0, 0.0]])       # the second is 30 m off: not counted
    S = W.segments({("9", 0): (shape, ["a", "b", "c", "d"])}, stops, signals).set_index("seg")
    assert list(S["s0"]) == [400.0, 800.0, 1200.0, 1600.0]
    assert list(S["stops"]) == [2, 0, 1, 0] and list(S["signals"]) == [1, 0, 1, 0]


def test_crossings_interpolate_and_skip_backward_or_long_gaps():
    obs = pd.DataFrame({"t": [0.0, 60.0, 120.0, 300.0, 360.0], "s": [100.0, 500.0, 900.0, 1300.0, 1200.0]})
    cr = W.crossings(obs, np.array([400.0, 800.0, 1250.0]))
    # 400 m crossed at 60 x 300/400 = 45 s; 800 m at 60 + 60 x 300/400 = 105 s; 1250 m lies in a 180 s gap: skipped
    assert cr == [(0, 45.0), (1, 105.0)]


def test_traversals_from_constructed_positions():
    shape = np.array([[0.0, 0.0], [2400.0, 0.0]])
    segs = W.segments({("9", 0): (shape, [])}, {}, np.zeros((0, 2)))
    t0 = pd.Timestamp("2026-11-17T14:00:00Z")
    rows = [{"route": "9", "direction": 0, "run": "1", "id": "v", "poll": t0 + pd.Timedelta(seconds=60 * k),
             "hour": 8, "x": 300.0 + 5.0 * 60 * k, "z": 0.0} for k in range(8)]            # 5 m/s
    T = W.traversals(pd.DataFrame(rows), segs, {("9", 0): (shape, [])})
    assert len(T) >= 2 and np.allclose(T["run_time_s"], 400 / 5.0)


def test_regression_recovers_known_seconds_per_stop():
    rng = np.random.default_rng(0)
    rows = []
    for r in range(40):
        fe = rng.normal(0, 15)
        for _ in range(150):
            L, n, g, h = 400.0, rng.integers(0, 4), rng.integers(0, 3), int(rng.integers(6, 20))
            y = 0.08 * L + 25.0 * n + 10.0 * g + fe + (h - 12) * 0.5 + rng.normal(0, 8)
            rows.append({"route": f"r{r}", "run_time_s": y, "length": L, "stops": n, "signals": g, "hour": h})
    est = W.fit(pd.DataFrame(rows))
    assert est["routes"] == 40 and est["n_traversals"] == 6000
    assert est["seconds_per_stop"] == pytest.approx(25.0, abs=0.6)
    lo, hi = est["ci95"]
    assert lo < 25.0 < hi and hi - lo < 2.0
    assert est["seconds_per_signal"] == pytest.approx(10.0, abs=0.8)
    assert est["t_quantile"] == pytest.approx(2.0227, abs=1e-3)                     # t(39, 0.975)


def test_pass_rule():
    assert W.stop_balancing_rule(-1.0, 500.0)["pass"] is False
    assert W.stop_balancing_rule(5.0, -10.0)["pass"] is False
    assert W.stop_balancing_rule(5.0, None)["pass"] is False
    assert W.stop_balancing_rule(5.0, 10.0)["pass"] is True
