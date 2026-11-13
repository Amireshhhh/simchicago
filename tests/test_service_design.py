"""Service design: square-root frequency allocation and bus stop balancing."""

import numpy as np
import pandas as pd
import pytest

from simchi import service_design as SD
from simchi.interventions import ALL_BANDS, network_scenario, vehicle_hours
from simchi.transit import network as N


def test_square_root_rule_on_a_toy_network():
    t = pd.DataFrame({"round_trips": [10.0, 10.0, 10.0], "cycle_h": [1.0, 1.0, 4.0], "boardings": [400.0, 100.0, 400.0]},
                     index=["a", "b", "c"])
    m = SD.square_root_allocation(t, 1.0, bounds=(0.01, 100))
    f = m * t["round_trips"]
    # f proportional to sqrt(Q / C): a : b : c = 20 : 10 : 10
    assert f["a"] / f["b"] == pytest.approx(2.0) and f["b"] / f["c"] == pytest.approx(1.0)
    assert (t["cycle_h"] * f).sum() == pytest.approx((t["cycle_h"] * t["round_trips"]).sum())
    # it lowers total waiting (sum Q / f) at the same cost
    assert (t["boardings"] / f).sum() < (t["boardings"] / t["round_trips"]).sum()


def test_bounds_and_budget_hold_on_the_real_routes():
    t = SD.route_table()
    for share in (1.0, 0.9):
        m = SD.square_root_allocation(t, share)
        assert m.min() >= SD.BOUNDS[0] - 1e-9 and m.max() <= SD.BOUNDS[1] + 1e-9
        assert (t["vehicle_hours"] * m).sum() == pytest.approx(share * t["vehicle_hours"].sum(), rel=1e-9)
        hm = {r: 1.0 / v for r, v in m.items()}
        assert vehicle_hours(network_scenario({"headway_multiplier": hm}), ALL_BANDS) == pytest.approx((share - 1) * t["vehicle_hours"].sum(), rel=1e-6, abs=1e-6)


def test_stop_balancing_keeps_terminals_and_saves_time():
    rm = SD.balanced_stops(["9"])
    from simchi.transit.gtfs import load_extract
    pats = [p for p in load_extract("patterns") if p["route"] == "9"]
    ends = {s for p in pats for s in (p["stops"][0], p["stops"][-1])}
    assert rm["9"] and not ends & set(rm["9"])
    sc = network_scenario({"removed_stops": rm, "stop_saving_s": 20.0})
    assert vehicle_hours(sc, ALL_BANDS) < 0
    g = N._graph()
    _, w0, iv0 = g.matrix(N.NetworkScenario())
    _, w1, iv1 = g.matrix(sc)
    route9 = np.array([g.pats[i]["route"] == "9" for i in g.pnode_pat])
    assert iv1[route9].sum() < iv0[route9].sum() and np.allclose(iv1[~route9], iv0[~route9])
    assert np.isnan(w1[route9]).sum() > np.isnan(w0[route9]).sum()      # skipped stops have no boarding
