"""Intervention cost proxy, equity grouping and the wait knob."""

import numpy as np
import pytest

from simchi import interventions as IV
from simchi.transit import network as N


def test_vehicle_hours_cost_proxy():
    sc0 = N.NetworkScenario()
    assert IV.vehicle_hours(sc0, IV.ALL_BANDS) == 0.0
    base_bus = IV.vehicle_hours(N.NetworkScenario(headway_multiplier={"bus": 0.5}), IV.ALL_BANDS)
    # halving headways doubles trips: the added vehicle-hours equal the scheduled bus vehicle-hours
    slower = IV.vehicle_hours(N.NetworkScenario(ivt_multiplier={"bus": 2.0}), IV.ALL_BANDS)
    assert base_bus > 0 and slower == pytest.approx(base_bus)
    assert IV.vehicle_hours(N.NetworkScenario(headway_multiplier={"bus": 0.5}), ("night",)) < base_bus
    assert IV.vehicle_hours(N.NetworkScenario(ivt_multiplier={"bus": 0.85}), IV.ALL_BANDS) == pytest.approx(-0.15 * base_bus)


def test_low_income_group_holds_a_quarter_of_residents():
    from simchi.world import build_world
    w = build_world()
    low = IV.low_income_areas(w)
    pop = w.cds.table["TOT_POP"].to_numpy(float)
    inc = w.cds.table["MEDINC"].to_numpy(float)
    assert 0.2 < pop[low].sum() / pop.sum() <= 0.25
    assert inc[low].max() <= inc[~low].min()


def test_wait_multiplier_scales_waits():
    g = N._graph()
    _, w0, _ = g.matrix(N.NetworkScenario())
    _, w1, _ = g.matrix(N.NetworkScenario(wait_multiplier={"bus": 0.5}))
    rail = g.pat_rail[g.pnode_pat]
    ok = np.isfinite(w0)
    np.testing.assert_allclose(w1[ok & ~rail], 0.5 * w0[ok & ~rail])
    np.testing.assert_allclose(w1[ok & rail], w0[ok & rail])
