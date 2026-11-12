"""Identification and sensitivity of the network mode-choice model -> reports/mode_choice_identification.json.

  * constrained fit (as used) and a fit with every coefficient free in [-15, 15]
  * observed information: numerical Hessian of the grouped negative log-likelihood (per commuter)
    at the constrained optimum over the coefficients not at a bound; its eigenvalues, condition
    number and implied correlations (the ACS counts are treated as independent choices, so the
    implied standard errors are lower bounds and are not reported as uncertainty)
  * arc elasticities of the city transit share: in-vehicle time, wait, fare (at several assumed
    values of time)
"""
import json
import sys

import numpy as np

from simchi.behavior.destination import fit_gravity
from simchi.behavior.mode_choice import BOUNDS, PARAM_NAMES, ModeModel, area_los, fit_mode_choice, grouped_negll, observed_mode_counts
from simchi.behavior.travel import fit_mode_and_travel
from simchi.paths import REPORTS
from simchi.transit.network import NetworkScenario, skim
from simchi.world import build_world


def city_transit_share(world, P, m, los):
    N = observed_mode_counts(world)
    s = m.area_shares(world, P, los)
    return float((s[:, 1] * N.sum(1)).sum() / N.sum())


def main():
    w = build_world()
    P = fit_gravity(w).probs(w)
    sk = skim()
    m, tm, iters = fit_mode_and_travel(w, P, sk)
    los = area_los(w, sk, tm.v_car, tm.tau_car, tm.v_other)
    N = observed_mode_counts(w)
    rows = np.arange(77)
    n = N.sum()
    free = [i for i, (v, (lo, hi)) in enumerate(zip(m.theta, BOUNDS, strict=True)) if min(v - lo, hi - v) > 1e-6]
    f = lambda th: grouped_negll(th, w, P, los, N, rows) / n  # noqa: E731
    h = 1e-4
    k = len(free)
    H = np.zeros((k, k))
    for a in range(k):
        for b in range(a, k):
            def at(da, db):
                t = m.theta.copy()
                t[free[a]] += da
                t[free[b]] += db
                return f(t)
            H[a, b] = H[b, a] = (at(h, h) - at(h, -h) - at(-h, h) + at(-h, -h)) / (4 * h * h)
    ev = np.linalg.eigvalsh(H)
    cov = np.linalg.inv(H)
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    names = [PARAM_NAMES[i] for i in free]
    strong = [[names[a], names[b], float(corr[a, b])] for a in range(k) for b in range(a + 1, k) if abs(corr[a, b]) > 0.9]

    unc = fit_mode_choice(w, P, los, bounds=[(-15, 15)] * len(BOUNDS), x0=m.theta)

    base = city_transit_share(w, P, m, los)
    el = {}
    for name, key, f_ in (("in-vehicle time +10%", "ivt", 1.1), ("wait +10%", "wait", 1.1)):
        l2 = dict(los)
        l2[key] = los[key] * f_
        el[name] = (city_transit_share(w, P, m, l2) - base) / base / 0.1
    fares = {}
    sk2 = skim(NetworkScenario(fare_bus=2.25 * 1.1, fare_rail=2.50 * 1.1))
    for vot in (10.0, 15.0, 25.0):
        mv = ModeModel(m.theta, vot_per_hour=vot)
        b0 = city_transit_share(w, P, mv, los)
        b1 = city_transit_share(w, P, mv, area_los(w, sk2, tm.v_car, tm.tau_car, tm.v_other))
        fares[f"VOT ${vot:.0f}/h"] = (b1 - b0) / b0 / 0.1
    out = {
        "constrained": m.as_dict(), "loglik_constrained": m.loglik, "car_speed_kmh": tm.v_car, "fit_iterations": iters,
        "at_bounds": [PARAM_NAMES[i] for i in range(len(BOUNDS)) if i not in free],
        "unconstrained": unc.as_dict(), "loglik_unconstrained": unc.loglik,
        "hessian_free_params": names, "hessian_eigenvalues": ev.tolist(), "hessian_condition_number": float(ev.max() / ev.min()),
        "correlations_above_0.9": strong,
        "city_transit_share_model": base, "city_transit_share_acs": float(N[:, 1].sum() / n),
        "arc_elasticity_transit_share": el, "arc_elasticity_transit_share_fare_+10pct": fares,
    }
    REPORTS.mkdir(exist_ok=True)
    with open(REPORTS / "mode_choice_identification.json", "w") as fh:
        json.dump(out, fh, indent=1)
    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
