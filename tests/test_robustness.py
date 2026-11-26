"""D robustness checks on constructed data with known answers."""

import numpy as np
import pandas as pd
import pytest

from simchi.safety import robustness as R


def test_site_year_ka_and_shares():
    sy = pd.DataFrame({"site": ["a", "a", "b"], "year": [2019, 2020, 2020], "crashes": [3, 2, 1], "a_crashes": [1, 0, 1]})
    vz = pd.DataFrame({"site": ["b"], "year": [2020], "deaths": [2], "fatal_crashes": [1]})
    t = R.site_year_ka(sy, vz).set_index(["site", "year"])
    assert t.loc[("a", 2019), "ka"] == 1 and t.loc[("b", 2020), "ka"] == 2 and t.loc[("a", 2020), "ka"] == 0
    ids = np.array(["a", "b", "c", "d"])
    out = pd.Series({"a": 1.0, "b": 3.0, "c": 0.0, "d": 0.0})
    s = R.shares_for(ids, {"score": [np.array([4.0, 1.0, 0.0, 0.0])]}, out, k=1)
    assert s["score"] == pytest.approx(0.25) and s["oracle"] == pytest.approx(0.75)      # ranking picks a; oracle picks b
    assert s["share_of_units_with_any"] == pytest.approx(0.5) and s["units"] == 4 and s["events"] == 4.0
