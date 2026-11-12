"""The CTA network skim and the network-based mode choice."""

import numpy as np
import pytest

from simchi.experiments import make_config
from simchi.sim.engine import _choose_modes, scenario_skim
from simchi.transit import network as N


@pytest.fixture(scope="module")
def base(built):
    return scenario_skim(built, make_config({}, {}, 1))


def test_skim_shapes_and_ranges(base):
    for a in (base.walk, base.wait, base.ivt, base.boardings, base.fare):
        assert a.shape == (77, 78) and np.isfinite(a).all()
    assert (base.boardings >= 1).all()                         # every path boards a vehicle
    assert ((base.fare >= N.FARE_BUS - 1e-9) & (base.fare <= N.FARE_RAIL + 1e-9)).all()
    assert (base.wait > 0).all() and (base.wait <= N.WAIT_CAP_MIN * base.boardings + 1e-9).all()


def test_pointer_doubling_matches_explicit_path_tracing():
    g = N._graph()
    sc = N.NetworkScenario()
    G, wait_node, ivt_node = g.matrix(sc)
    src = np.array([0, 100, 300])
    out, (dist, pred) = g.point_components(sc, src, G, wait_node, ivt_node)
    dests = g.dest_nodes()
    kind = g.node_kind
    for a in range(len(src)):
        for b in (0, 57, 250, len(dests) - 1):
            node = dests[b]
            walk = wait = ivt = board = 0.0
            while pred[a, node] >= 0:
                p = pred[a, node]
                w = dist[a, node] - dist[a, p]
                if kind[node] == 2 and kind[p] == 0:
                    wait += wait_node[node - g.P0]
                    board += 1
                elif kind[node] == 2 and kind[p] == 2:
                    ivt += ivt_node[node - g.P0]
                elif kind[node] == 5:
                    ivt += w
                elif kind[node] in (0, 4):
                    walk += w / N.PATH_W_WALK
                node = p
            assert node == g.O0 + src[a]
            np.testing.assert_allclose(out[:4, a, b], [walk, wait, ivt, board], rtol=1e-9, atol=1e-6)


def test_service_knobs_act_on_the_skim(built, base):
    slow = scenario_skim(built, make_config({}, {"network.ivt_multiplier.bus": 1.5, "network.ivt_multiplier.rail": 1.5}, 1))
    sparse = scenario_skim(built, make_config({}, {"network.headway_multiplier.bus": 2.0, "network.headway_multiplier.rail": 2.0}, 1))
    # generalised cost can only rise when every edge cost rises or stays equal
    gen = lambda s: s.ivt + N.PATH_W_WAIT * s.wait + N.PATH_W_WALK * s.walk + N.TRANSFER_PENALTY_MIN * s.boardings  # noqa: E731
    assert (gen(slow) >= gen(base) - 1e-6).all() and gen(slow).mean() > gen(base).mean()
    assert (gen(sparse) >= gen(base) - 1e-6).all() and sparse.wait.mean() > base.wait.mean()


def test_slower_transit_reduces_ridership_without_mode_shift(built, base):
    """Proof sketch: with common draws u, a person chooses transit iff P_car < u <= P_car + P_transit.
    Lowering V_transit raises P_car and lowers P_car + P_transit = 1 - P_walk - P_other, so the set
    of transit choosers can only shrink; mode_shift stays 0."""
    cfg0 = make_config({}, {}, 1)
    cfg1 = make_config({}, {"network.ivt_multiplier.bus": 1.5, "network.ivt_multiplier.rail": 1.5}, 1)
    assert cfg1.mode_shift == cfg0.mode_shift == {"transit": 0.0, "walk": 0.0, "other": 0.0}
    m0 = _choose_modes(built, cfg0, base) == 3
    m1 = _choose_modes(built, cfg1, scenario_skim(built, cfg1)) == 3
    assert not (m1 & ~m0).any()
    assert m1.sum() < m0.sum()


def test_fare_increase_reduces_area_transit_shares(built, base):
    from simchi.behavior.mode_choice import area_los
    tr = built.travel
    P = built.gravity.probs(built.world)
    pricey = scenario_skim(built, make_config({}, {"network.fare_bus": 3.25, "network.fare_rail": 3.50}, 1))
    s0 = built.mode_model.area_shares(built.world, P, area_los(built.world, base, tr.v_car, tr.tau_car, tr.v_other))
    s1 = built.mode_model.area_shares(built.world, P, area_los(built.world, pricey, tr.v_car, tr.tau_car, tr.v_other))
    assert (s1[:, 1] < s0[:, 1]).all()


def test_assignment_conserves_trips_and_boardings():
    """sum over patterns of assigned boardings = sum over OD pairs of trips x path boardings."""
    g = N._graph()
    sc = N.NetworkScenario()
    rng = np.random.default_rng(3)
    nz, nd = len(g.zone_xy), len(g.dest_nodes())
    D = np.zeros((nz, nd))
    src = np.array([5, 77, 200, 401])
    D[src] = rng.uniform(0, 3, (len(src), nd)) * (rng.uniform(size=(len(src), nd)) < 0.2)
    res = g.assign(sc, D)
    comp, _ = g.point_components(sc, src)
    boardings = (D[src] * comp[3]).sum()
    rail_boardings = (D[src] * comp[4]).sum()
    assert res["pattern_boardings"].sum() == pytest.approx(boardings, rel=1e-9)
    assert res["pattern_boardings"][g.pat_rail].sum() == pytest.approx(rail_boardings, rel=1e-9)
    assert 0 < res["stop_entries"].sum() <= rail_boardings + 1e-9


def test_area_demand_spreads_without_loss(built):
    g = N._graph()
    T = np.random.default_rng(1).uniform(0, 10, (77, 78))
    D = g.area_demand_to_points(T)
    assert D.sum() == pytest.approx(T.sum(), rel=1e-12)
