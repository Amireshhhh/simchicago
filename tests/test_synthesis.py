import numpy as np
import pytest

from simchi.data.cds import load_cds
from simchi.synth.calibrate import rake
from simchi.synth.ipu import ipu
from simchi.synth.population import _systematic_pps, synthesize


def test_rake_exact_on_feasible_problem():
    rng = np.random.default_rng(0)
    A = rng.integers(0, 3, size=(300, 6)).astype(float)
    w_true = rng.uniform(0.5, 2, 300)
    c = A.T @ w_true
    r = rake(A, c)
    assert r.converged
    assert np.abs(r.rel_residual).max() < 1e-6


def test_rake_residual_identity_on_infeasible_problem():
    A = np.array([[1.0, 1.0], [1.0, 1.0]])           # both constraints count the same households
    c = np.array([10.0, 20.0])                      # cannot both hold
    r = rake(A, c, mu=1e-3)
    np.testing.assert_allclose(r.rel_residual, -1e-3 * r.lam, rtol=1e-4, atol=1e-8)


def test_ipu_matches_feasible_controls():
    rng = np.random.default_rng(1)
    A = rng.integers(0, 2, size=(200, 5)).astype(float)
    A[:, 0] = 1
    c = A.T @ rng.uniform(0.5, 2, 200)
    r = ipu(A, c, max_iter=5000, tol=1e-12)
    assert r.max_abs_rel_dev < 1e-3


def test_systematic_pps_selection_counts():
    rng = np.random.default_rng(2)
    w = rng.uniform(0.1, 5, 50)
    n = 37
    for _ in range(50):
        k = np.bincount(_systematic_pps(w, n, rng), minlength=50)
        e = n * w / w.sum()
        assert k.sum() == n
        assert np.all((k == np.floor(e)) | (k == np.ceil(e)))


@pytest.fixture(scope="module")
def pop():
    return synthesize(load_cds(), 2000, seed=3)


def test_all_areas_calibrated(pop):
    assert (pop.fit["calib_max_rel_dev"] < 1e-3).all()


def test_weights_represent_household_population(pop):
    c = load_cds()
    assert abs(pop.persons["weight"].sum() / c.table["POP_HH"].sum() - 1) < 0.03
    assert abs(pop.households["weight"].sum() / c.table["TOT_HH"].sum() - 1) < 1e-5     # equals the calibrated total up to the solver tolerance


def test_structural_constraints(pop):
    P = pop.persons
    assert (P.loc[P["age"] < 16, "labor"] == -1).all()
    assert (P.loc[P["age"] < 25, "edu"] == -1).all()
    adults = P[P["age"] >= 18].groupby("hh_id").size()
    assert set(P["hh_id"]) <= set(adults.index)                       # every household has an adult
    one = pop.households[pop.households["size"] == 1]
    assert (one["hh_type"] == 1).all()                                  # 1-person households are non-family
    kids = P[P["age"] < 18].merge(pop.households[["hh_id", "hh_type"]], on="hh_id", suffixes=("", "_h"))
    assert (kids["hh_type_h"] == 0).all()                               # children live in family households
