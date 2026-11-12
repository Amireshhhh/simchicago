import numpy as np
from scipy.special import gammaln

from simchi.behavior.destination import grouped_counts
from simchi.incidents.data import load_carjackings_2020
from simchi.incidents.intensity import dm_loglik, fit_intensity


def test_gravity_rows_are_distributions(built):
    P = built.gravity.probs(built.world)
    assert P.shape == (77, 78)
    np.testing.assert_allclose(P.sum(1), 1)
    cols, cnt, rest = grouped_counts(built.world)
    assert (rest >= 0).all()


def test_mode_shares_are_distributions(built):
    from simchi.behavior.mode_choice import area_los
    tr = built.travel
    los = area_los(built.world, built.skim, tr.v_car, tr.tau_car, tr.v_other)
    m = built.mode_model.probs(np.array([0.0, 1.0])[:, None, None], 0.0, los)
    np.testing.assert_allclose(m.sum(-1), 1)
    sh = built.mode_model.area_shares(built.world, built.gravity.probs(built.world), los)
    np.testing.assert_allclose(sh.sum(1), 1)


def test_dirichlet_multinomial_loglik_against_direct_formula():
    counts = np.array([[3, 0, 2], [1, 1, 1]], float)
    m = np.array([0.2, 0.3, 0.5]); alpha = 4.0
    direct = 0.0
    for row in counts:
        N = row.sum(); a = alpha * m
        direct += gammaln(alpha) - gammaln(N + alpha) + (gammaln(row + a) - gammaln(a)).sum()
    assert abs(dm_loglik(alpha, counts, m) - direct) < 1e-12


def test_intensity_model_is_normalised():
    m = fit_intensity(load_carjackings_2020(), "2020-01-01", "2020-10-01")
    assert abs(m.pi.sum() - 1) < 1e-12 and abs(m.eta.sum() - 1) < 1e-12 and abs(m.omega.mean() - 1) < 1e-12
