"""Rider feedback vs polled headways on constructed data with known answers."""

import numpy as np
import pandas as pd
import pytest

from simchi.transit import feedback as F


def test_predicted_wait_formula_and_matching():
    cells = pd.DataFrame({"route": ["9", "9", "9"], "direction": [0, 1, 0], "day": ["weekday"] * 3, "hour": [8, 8, 9],
                          "headway_mean_min": [10.0, 6.0, 20.0], "headway_cv": [0.0, 1.0, 0.5]})
    # E[W] = H (1 + CV^2) / 2: 5, 6, 12.5
    assert F.predicted_wait(cells).tolist() == pytest.approx([5.0, 6.0, 12.5])
    dirs = F.stop_directions([{"route": "9", "direction": 0, "stops": ["a", "b"]}, {"route": "9", "direction": 1, "stops": ["b"]}])
    assert dirs == {("9", "a"): [0], ("9", "b"): [0, 1]}
    fb = pd.DataFrame({"route": ["9", "9", "9", "9", "9"], "stop_id": ["a", "b", "a", "a", "zz"],
                       # 14:10 UTC = 08:10 Chicago (Tuesday); 15:30 UTC = 09:30
                       "timestamp_utc": ["2026-11-17T14:10:00Z", "2026-11-17T14:20:00Z", "2026-11-17T15:30:00Z", "2026-11-17T14:50:00Z", "2026-11-17T14:10:00Z"],
                       "observed_wait_min": [4.0, 5.5, 15.0, 7.0, 3.0], "source": ["s"] * 5})
    r = F.compare(fb, cells, dirs)
    # stop zz is not on route 9: unmatched; predictions 5, (5+6)/2 = 5.5, 12.5, 5
    assert r["records"] == 5 and r["matched"] == 4
    obs, pred = np.array([4.0, 5.5, 15.0, 7.0]), np.array([5.0, 5.5, 12.5, 5.0])
    assert r["mean_abs_diff_min"] == pytest.approx(np.mean(np.abs(obs - pred)))
    assert r["median_ratio_observed_to_predicted"] == pytest.approx(np.median(obs / pred))
    assert r["share_within_50pct"] == pytest.approx(1.0)
    assert "nothing is tuned" in r["label"]


def test_feedback_schema_is_enforced():
    with pytest.raises(ValueError, match="missing"):
        F.compare(pd.DataFrame({"route": ["9"]}), pd.DataFrame(columns=["route", "direction", "day", "hour", "headway_mean_min", "headway_cv"]), {})
