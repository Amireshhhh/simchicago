import numpy as np
import pandas as pd

from simchi.pipeline import run
from simchi.sim.engine import SafetyParams, SimConfig


def _run(built, **kw):
    return run(built, SimConfig(n_days=kw.pop("n_days", 3), **kw))


def test_deterministic_given_seed(built):
    a = pd.DataFrame(_run(built, seed=5).segments)
    b = pd.DataFrame(_run(built, seed=5).segments)
    pd.testing.assert_frame_equal(a, b)


def test_seeds_change_outcomes(built):
    a = pd.DataFrame(_run(built, seed=5).segments)
    b = pd.DataFrame(_run(built, seed=6).segments)
    assert len(a) != len(b) or not np.allclose(a["t0"], b["t0"])


def test_every_day_plan_is_a_partition_of_the_day(built):
    S = pd.DataFrame(_run(built, seed=1, n_days=2).segments).sort_values(["day", "pid", "t0"])
    for (_, _), g in S.groupby(["day", "pid"]):
        assert g["t0"].iloc[0] == 0 and abs(g["t1"].iloc[-1] - 1440) < 1e-6
        assert np.allclose(g["t0"].to_numpy()[1:], g["t1"].to_numpy()[:-1])
        assert (g["t1"] >= g["t0"] - 1e-9).all()


def test_labels_and_exposure_radius(built):
    sim = _run(built, seed=1, incident_mode="both")
    inc = pd.concat(sim.incidents)
    assert set(inc["label"]) <= {"observed", "simulated"}
    assert (inc.loc[inc["record_id"] > 0, "label"] == "observed").all()
    assert (inc.loc[inc["record_id"] < 0, "label"] == "simulated").all()
    ex = [e for e in sim.events if e["kind"] == "exposure"]
    assert ex and all(e["distance_m"] <= sim.cfg.safety.radius_m + 1e-9 for e in ex)


def test_no_response_equals_no_incidents_common_random_numbers(built):
    off = _run(built, seed=2, incident_mode="replay", safety=SafetyParams(a=0, b=0, gamma_cancel=0))
    none = _run(built, seed=2, incident_mode="none")
    pd.testing.assert_frame_equal(pd.DataFrame(off.segments), pd.DataFrame(none.segments))


def test_safety_theorem_invariance_and_contraction():
    """Theorem 1 (docs/DESIGN.md): s stays in [0,1]; without exposure the map contracts at rate 1-eta."""
    rng = np.random.default_rng(0)
    n = 60
    W = rng.uniform(size=(n, n)) * (rng.uniform(size=(n, n)) < 0.1); np.fill_diagonal(W, 0)
    deg = W.sum(1); W[deg == 0, 0] = 1; W = W / W.sum(1, keepdims=True)
    eta, c, a, b = 0.1, 0.2, 0.15, 0.02
    sbar = rng.uniform(size=n)
    def step(s, Ed, Ea):
        return ((1 - eta - c) * s + eta * sbar + c * W @ s) * (1 - a) ** Ed * (1 - b) ** Ea
    s = rng.uniform(size=n)
    for _ in range(200):
        s = step(s, rng.poisson(0.5, n), rng.poisson(2, n))
        assert (s >= 0).all() and (s <= 1).all()
    x, y = rng.uniform(size=n), rng.uniform(size=n)
    for _ in range(30):
        x2, y2 = step(x, 0, 0), step(y, 0, 0)
        assert np.abs(x2 - y2).max() <= (1 - eta) * np.abs(x - y).max() + 1e-12
        x, y = x2, y2
