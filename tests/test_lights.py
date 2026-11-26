"""W9 on constructed data with known answers: outage-window merging, the outage/after panel, and
the two-way fixed-effects difference in differences."""

import numpy as np
import pandas as pd
import pytest

from simchi.safety import lights as LG


def test_outage_windows_merge_overlaps():
    req = pd.DataFrame({"block": ["s1", "s1", "s1", "s2"], "created_date": ["2020-01-01", "2020-01-05", "2020-02-01", "2020-03-01"],
                        "closed_date": ["2020-01-10", "2020-01-12", "2020-02-03", None]})
    w = LG.outage_windows(req)
    assert len(w) == 2 and list(w["requests"]) == [2, 1]                 # s2 has no closed date: dropped
    assert str(w.iloc[0]["end"].date()) == "2020-01-12"


def test_panel_days_and_bands():
    w = pd.DataFrame({"block": ["s1"], "start": [pd.Timestamp("2020-01-01")], "end": [pd.Timestamp("2020-01-05")], "requests": [1]})
    agg = pd.DataFrame({"block": ["s1", "s1", "s1"], "day": ["2020-01-02", "2020-01-02", "2020-01-07"], "hour": [22, 12, 23],
                        "primary_type": ["THEFT"] * 3, "place": ["outdoor", "outdoor", "outdoor"], "n": [2, 1, 1]})
    Q = LG.panel(w, agg)
    # during: Jan 2-4 (3 days, strictly inside); after: Jan 6-8; x 2 bands
    assert len(Q) == 12 and Q["outage"].sum() == 6
    r = Q.set_index(["day", "night"])["y"]
    assert r[("2020-01-02", 1)] == 2 and r[("2020-01-02", 0)] == 1 and r[("2020-01-07", 1)] == 1


def test_did_recovers_a_known_interaction():
    rng = np.random.default_rng(0)
    rows = []
    for b in range(300):
        fe = rng.normal(0, 1)
        for d in range(40):
            wk = d // 7
            out = int(d < 20)
            for night in (0, 1):
                y = 1.0 + fe + 0.1 * wk + 0.5 * night + 0.2 * out + 0.7 * night * out + rng.normal(0, 0.5)
                rows.append((f"b{b}", f"w{wk}", out, night, y))
    Q = pd.DataFrame(rows, columns=["block", "week", "outage", "night", "y"])
    r = LG.did(Q)
    assert r["coef"]["night_x_outage"] == pytest.approx(0.7, abs=0.03)
    assert r["coef"]["night"] == pytest.approx(0.5, abs=0.03)
    lo, hi = r["ci95_night_x_outage"]
    assert lo < 0.7 < hi and lo > 0 and r["blocks"] == 300


def test_location_map_is_complete_and_classified():
    m = LG.location_map()
    assert len(m) == 193 and set(m.values()) == {"indoor", "outdoor", "other"}
    assert m["STREET"] == "outdoor" and m["APARTMENT"] == "indoor" and m["BOWLING ALLEY"] == "indoor" and m["CTA TRAIN"] == "other"
