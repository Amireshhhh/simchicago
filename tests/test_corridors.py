"""W4b corridors on constructed data with known answers: chaining by name, splitting at the
arterial grid, intersection assignment, and the top-k shares."""

import numpy as np
import pandas as pd
import pytest

from simchi.safety import corridors as CO
from simchi.safety import sites as ST

LON0, LAT0 = -87.6, 41.8
to_xy = lambda lon, lat: ((np.asarray(lon, float) - LON0) * 1e5, (np.asarray(lat, float) - LAT0) * 1e5)  # noqa: E731


def _streets():
    f = lambda c, n, co: {"type": "Feature", "properties": {"c": c, "n": n},  # noqa: E731
                          "geometry": {"type": "LineString", "coordinates": [[LON0 + a, LAT0 + b] for a, b in co]}}
    return {"type": "FeatureCollection", "features": [
        f("3", "A St", [[0.000, 0], [0.004, 0]]),      # s0
        f("3", "A St", [[0.004, 0], [0.008, 0]]),      # s1   joins s0 at x=0.004, where local C Ct crosses: no split
        f("3", "A St", [[0.008, 0], [0.012, 0]]),      # s2   joins s1 at x=0.008, where arterial B Ave crosses: split
        f("4", "C Ct", [[0.004, 0], [0.004, 0.004]]),  # s3
        f("4", "C Ct", [[0.004, -0.004], [0.004, 0]]),  # s4
        f("2", "B Ave", [[0.008, 0], [0.008, 0.004]]),  # s5
        f("2", "B Ave", [[0.008, -0.004], [0.008, 0]]),  # s6
        f("1", "I-90", [[0.02, 0], [0.03, 0]])]}       # s7 expressway: no corridor


def test_corridors_split_at_arterials_and_assign_intersections():
    S = ST.build_sites(_streets(), to_xy)
    corr = CO.build_corridors(_streets(), S.table)
    assert corr["s0"] == corr["s1"] == "A St #1" and corr["s2"] == "A St #2"
    assert corr["s3"] == corr["s4"] == "C Ct #1" and corr["s5"] == corr["s6"] == "B Ave #1"
    assert "s7" not in corr.index
    nodes = S.table[S.table["type"] == "intersection"]
    at = {round(float(r.lon) - LON0, 3): corr[sid] for sid, r in nodes.iterrows()}
    assert at == {0.004: "A St #1", 0.008: "B Ave #1"}        # highest-order leg: collector over local, arterial over collector


def test_corridor_table_and_shares():
    S = ST.build_sites(_streets(), to_xy)
    corr = CO.build_corridors(_streets(), S.table)
    bus = pd.Series(False, index=corr.index)
    bus[["s0", "s1"]] = True
    g = CO.corridor_table(corr, S.table, pd.DataFrame({"site": ["s1"], "adt": [9000.0]}), bus)
    assert g.loc["A St #1", "length_m"] == pytest.approx(800.0) and g.loc["A St #2", "length_m"] == pytest.approx(400.0)
    assert g.loc["A St #1", "bus_share"] == pytest.approx(1.0) and g.loc["A St #2", "bus_share"] == pytest.approx(0.0)
    assert g.loc["A St #1", "intersections"] == 1 and g.loc["B Ave #1", "intersections"] == 1 and g.loc["A St #1", "adt"] == 9000.0
    assert g.loc["B Ave #1", "top_cls"] == "2"
    from simchi.safety import crashes as C
    ids = g.index.to_numpy()
    test = pd.Series({"A St #1": 3.0, "A St #2": 1.0, "B Ave #1": 0.0, "C Ct #1": 0.0})
    top = C.top_k(ids, [g.loc[ids, "length_m"].to_numpy()], 1)          # longest corridor first
    assert C.captured(top, test) == pytest.approx(0.75)
