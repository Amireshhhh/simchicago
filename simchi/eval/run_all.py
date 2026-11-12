"""All validation checks -> reports/validation.json (python -m simchi.cli validate).

Every model check is out of sample and compares against a simple baseline, with the pass
criterion fixed in advance ("beats the baseline on held-out data"):

  gravity      leave-one-district-out: refit without a district's origins, score its
               residents' grouped LEHD likelihood; baseline: destinations proportional to jobs
  mode choice  leave-one-district-out grouped ACS likelihood of the network-based model (CTA
               GTFS skim); baseline: city-wide shares
  commute time leave-one-district-out area mean commute (ACS), network transit times and a
               fitted car speed; baseline: city mean
  incidents    train Jan-Sep 2020, score Oct-Dec weekly area counts (see incident_forecast)
  ridership    bus routes and 'L' stations, held-out units and period; baselines: constant and
               scheduled service (see simchi/eval/ridership.py, criteria pre-registered)

plus data integrity, calibration and engine invariants.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from simchi.behavior.destination import _negll, fit_gravity, grouped_counts
from simchi.behavior.mode_choice import BOUNDS, PARAM_NAMES, area_los, observed_mode_counts
from simchi.behavior.travel import expected_commute_minutes, fit_mode_and_travel, observed_commute_minutes
from simchi.data.cds import ROOT, load_cds, sha256, source
from simchi.eval import incident_forecast
from simchi.pipeline import build, run
from simchi.sim.engine import SafetyParams, SimConfig
from simchi.world import OUTSIDE, build_world


def _check(passed, summary, **details):
    return {"pass": bool(passed), "summary": summary, **details}


def data_integrity():
    out = {}
    for key in ("cds_2021", "carjackings_2020", "sdoh_tracts_2014", "cta_l_station_daily", "cta_bus_route_daily", "crimes_cta_by_area", "crimes_all_by_area"):
        s = source(key)
        out[key] = sha256(ROOT / s["file"]) == s["sha256"]
    return _check(all(out.values()), f"{sum(out.values())}/{len(out)} mirrors match their pinned sha256", files=out)


def cds_identities():
    rep = load_cds().identity_report
    worst = max(v["max_rel_diff"] for v in rep.values() if "max_rel_diff" in v)
    ok = worst < 0.015 and rep["lehd_orientation"]["holds"]
    return _check(ok, f"12 count identities hold within {worst:.4f} (max relative difference); LEHD orientation holds: {rep['lehd_orientation']['holds']}",
                  report=rep)


def calibration(built):
    f = built.population.fit
    P, H, t = built.persons, built.population.households, load_cds().table
    pw = P["weight"].sum() / t["POP_HH"].sum()
    hw = H["weight"].sum() / t["TOT_HH"].sum()
    ok = f["calib_max_rel_dev"].max() < 1e-6 and abs(hw - 1) < 1e-9 and abs(pw - 1) < 0.03
    return _check(ok, f"77/77 areas calibrated (max relative deviation {f['calib_max_rel_dev'].max():.1e}); "
                      f"household weights / TOT_HH = {hw:.6f}; person weights / POP_HH = {pw:.4f}",
                  max_calib_dev=float(f["calib_max_rel_dev"].max()), person_weight_ratio=float(pw), household_weight_ratio=float(hw))


def _districts(world):
    return world.areas["district"].to_numpy()


def gravity_holdout(world):
    cols, cnt, rest = grouped_counts(world)
    dist = _districts(world)
    jobs = world.areas["jobs"].to_numpy(float)
    rows = []
    for d in np.unique(dist):
        test = np.flatnonzero(dist == d)
        train = np.flatnonzero(dist != d)
        m = fit_gravity(world, origins=train)
        ll_model = -_negll([m.alpha, m.beta, m.delta, m.gamma0, m.gamma1], world, cols, cnt, rest, test)
        # baseline: probabilities proportional to jobs, with the outside share fitted on the training origins
        P = np.zeros((len(cols), OUTSIDE + 1))
        emp = world.cds.table["EMP"].to_numpy(float)
        out_share = float(np.clip(_outside_share(cols, cnt, emp, train), 1e-3, 0.9))
        P[:, :OUTSIDE] = (1 - out_share) * jobs / jobs.sum()
        P[:, OUTSIDE] = out_share
        lp = np.log(np.take_along_axis(P[test], cols[test], 1))
        ll_base = float((cnt[test] * lp).sum() + (rest[test] * np.log(np.clip(1 - np.exp(lp).sum(1), 1e-300, None))).sum())
        rows.append({"district": d, "origins": len(test), "loglik_model": ll_model, "loglik_baseline": ll_base})
    df = pd.DataFrame(rows)
    full = fit_gravity(world)
    Pf = full.probs(world)
    emp = world.cds.table["EMP"].to_numpy(float)
    obs = (cnt / emp[:, None]).ravel()
    pred = np.take_along_axis(Pf, cols, 1).ravel()
    ok = bool((df["loglik_model"] > df["loglik_baseline"]).all())
    return _check(ok, f"held-out log-likelihood better than the jobs-proportional baseline in {int((df.loglik_model > df.loglik_baseline).sum())}/{len(df)} districts; "
                      f"in-sample correlation of listed top-5 shares {np.corrcoef(obs, pred)[0, 1]:.3f}",
                  per_district=df.to_dict("records"), fitted=full.as_dict(),
                  in_sample_corr=float(np.corrcoef(obs, pred)[0, 1]), in_sample_mae_share=float(np.abs(obs - pred).mean()))


def _outside_share(cols, cnt, emp, rows):
    out = (cnt[rows] * (cols[rows] == OUTSIDE)).sum()
    return out / emp[rows].sum()


def network_holdouts(world, P_dest, skim):
    """Leave-one-district-out for the network mode-choice model and the commute-time model.

    For each district the mode-choice model and the car speed are refitted (alternately, see
    fit_mode_and_travel) on the other districts' areas; the held-out areas are then scored:
      mode choice  grouped ACS log-likelihood; baseline: city-wide shares of the training areas
      commute time absolute error of the area mean commute (ACS); baseline: commuter-weighted
                   city mean of the training areas
    Pass criteria (fixed before running): the model's held-out log-likelihood beats the baseline
    in every district; the model's held-out mean absolute error is below the baseline's."""
    N = observed_mode_counts(world)
    obs = observed_commute_minutes(world)
    w = world.cds.table["TOT_COMM"].to_numpy(float)
    dist = _districts(world)
    rows, coefs = [], []
    err_model, err_base = np.zeros(len(obs)), np.zeros(len(obs))
    for d in np.unique(dist):
        test = np.flatnonzero(dist == d)
        train = np.flatnonzero(dist != d)
        m, tm, _ = fit_mode_and_travel(world, P_dest, skim, areas=train)
        los = area_los(world, skim, tm.v_car, tm.tau_car, tm.v_other)
        s = m.area_shares(world, P_dest, los)[test]
        city = N[train].sum(0) / N[train].sum()
        e = expected_commute_minutes(world, P_dest, m, tm, skim)
        cm = float((obs[train] * w[train]).sum() / w[train].sum())
        err_model[test] = np.abs(e[test] - obs[test])
        err_base[test] = np.abs(cm - obs[test])
        rows.append({"district": d, "areas": len(test),
                     "loglik_model": float((N[test] * np.log(s)).sum()),
                     "loglik_baseline": float((N[test] * np.log(city)[None, :]).sum()),
                     "commute_mae_model": float(err_model[test].mean()), "commute_mae_baseline": float(err_base[test].mean()),
                     "v_car_kmh": tm.v_car})
        coefs.append(m.theta)
    df = pd.DataFrame(rows)
    full, ftm, iters = fit_mode_and_travel(world, P_dest, skim)
    los = area_los(world, skim, ftm.v_car, ftm.tau_car, ftm.v_other)
    pred = full.area_shares(world, P_dest, los)
    obs_sh = N / N.sum(1, keepdims=True)
    corr = {k: float(np.corrcoef(obs_sh[:, i], pred[:, i])[0, 1]) for i, k in enumerate(["car", "transit", "walk", "other"])}
    C = np.array(coefs)
    spread = {k: [float(C[:, i].min()), float(C[:, i].max())] for i, k in enumerate(PARAM_NAMES)}
    n_win = int((df.loglik_model > df.loglik_baseline).sum())
    mode = _check(n_win == len(df),
                  f"held-out log-likelihood better than city-wide shares in {n_win}/{len(df)} districts; "
                  f"in-sample area correlations car {corr['car']:.2f}, transit {corr['transit']:.2f}, walk {corr['walk']:.2f}",
                  per_district=df[["district", "areas", "loglik_model", "loglik_baseline"]].to_dict("records"),
                  fitted=full.as_dict(), loglik=full.loglik, in_sample_corr=corr, leave_one_out_coefficient_range=spread,
                  at_bounds=[k for k, v, (lo, hi) in zip(PARAM_NAMES, full.theta, BOUNDS, strict=True) if min(v - lo, hi - v) < 1e-6])
    e = expected_commute_minutes(world, P_dest, full, ftm, skim)
    n_tw = int((df.commute_mae_model < df.commute_mae_baseline).sum())
    ct = _check(err_model.mean() < err_base.mean(),
                f"held-out mean absolute error {err_model.mean():.2f} min vs {err_base.mean():.2f} min for the city mean "
                f"(better in {n_tw}/{len(df)} districts); in-sample correlation {np.corrcoef(obs, e)[0, 1]:.2f}",
                holdout_mae_model=float(err_model.mean()), holdout_mae_baseline=float(err_base.mean()),
                per_district=df[["district", "areas", "commute_mae_model", "commute_mae_baseline", "v_car_kmh"]].to_dict("records"),
                in_sample_corr=float(np.corrcoef(obs, e)[0, 1]), fitted=ftm.as_dict(), fit_iterations=iters)
    return mode, ct


def incidents():
    r = incident_forecast.run()
    s = r["log_scores"]
    return _check(r["model_beats_baselines"],
                  f"Oct-Dec 2020 weekly area counts: log score {s['model_dirichlet_multinomial']:.1f} (model) vs "
                  f"{s['baseline_population_areas']:.1f} (population) and {s['baseline_uniform_areas']:.1f} (uniform); "
                  f"daily mean {r['daily_mean_predicted']:.2f} predicted vs {r['daily_mean_observed_test']:.2f} observed", **r)


def gtfs_extract():
    from simchi.transit.gtfs import load_extract
    meta = load_extract("meta")
    pinned = source("gtfs_cta")["sha256"]
    pats = load_extract("patterns")
    from collections import defaultdict
    share = defaultdict(float)
    for p in pats:
        share[(p["route"], p["direction"])] += p["share_of_trips"]
    cover = float(np.mean(list(share.values())))
    ok = meta["source_sha256"] == pinned and meta["counts"]["routes"] > 0
    return _check(ok, f"extract built from the pinned feed: {meta['source_sha256'] == pinned}; {meta['counts']['routes']} routes "
                      f"({meta['counts']['rail_routes']} rail), {meta['counts']['stations']} stations, {meta['counts']['patterns']} patterns "
                      f"covering on average {cover:.1%} of each route-direction's weekday trips",
                  counts=meta["counts"], mean_pattern_coverage=cover)


def ridership(built):
    """Pre-registered held-out ridership validation (see simchi/eval/ridership.py)."""
    from simchi.eval import ridership as RV
    r = RV.run(built)
    out = {}
    for kind, label in (("bus", "bus routes"), ("rail", "'L' stations")):
        x = r[kind]
        m = x["male_heldout_units_and_period"]
        out[f"ridership_{kind}"] = _check(
            x["pass"], f"{x['units']} {label}, held-out units and period (train 2024, test 2025-01..2026-08): mean absolute log error "
                       f"{m['M_cal']:.3f} (simulation + scheduled service) vs {m['B_service']:.3f} (scheduled service) and "
                       f"{m['B_mean']:.3f} (constant); simulation alone {m['M_sim']:.3f}", **x)
    return out


def engine_invariants(built):
    sim = run(built, SimConfig(n_days=3, seed=11, incident_mode="both"))
    S = pd.DataFrame(sim.segments).sort_values(["day", "pid", "t0"], kind="stable")
    g = S.groupby(["day", "pid"])
    starts_ok = bool((g["t0"].first() == 0).all())
    ends_ok = bool((np.abs(g["t1"].last() - 1440) < 1e-6).all())
    contiguous = bool(np.allclose(S["t0"].to_numpy()[1:][S["pid"].to_numpy()[1:] == S["pid"].to_numpy()[:-1]],
                                  S["t1"].to_numpy()[:-1][S["pid"].to_numpy()[1:] == S["pid"].to_numpy()[:-1]]))
    safety_ok = bool((sim.safety >= 0).all() and (sim.safety <= 1).all())
    a = run(built, SimConfig(n_days=2, seed=5, incident_mode="replay", safety=SafetyParams(a=0, b=0, gamma_cancel=0)))
    b = run(built, SimConfig(n_days=2, seed=5, incident_mode="none"))
    crn = all(np.array_equal(a.segments[k], b.segments[k]) for k in a.segments)
    c = run(built, SimConfig(n_days=2, seed=5, incident_mode="both"))
    d = run(built, SimConfig(n_days=2, seed=5, incident_mode="both"))
    det = all(np.array_equal(c.segments[k], d.segments[k]) for k in c.segments)
    ok = starts_ok and ends_ok and contiguous and safety_ok and crn and det
    return _check(ok, f"day plans partition [0, 1440]: {starts_ok and ends_ok and contiguous}; safety in [0, 1]: {safety_ok}; "
                      f"no response == no incidents: {crn}; deterministic: {det}",
                  agent_days=int(g.ngroups))


def run_all(n: int = 2000, seed: int = 1) -> dict:
    t0 = time.time()
    world = build_world()
    built = build(n, seed)
    P_dest = built.gravity.probs(world)
    mode_ct = network_holdouts(world, P_dest, built.skim)
    checks = {
        "data_integrity": data_integrity(),
        "cds_identities": cds_identities(),
        "calibration": calibration(built),
        "gravity_holdout": gravity_holdout(world),
        "mode_choice_holdout": mode_ct[0],
        "commute_time_holdout": mode_ct[1],
        "incident_forecast": incidents(),
        "engine_invariants": engine_invariants(built),
        "gtfs_extract": gtfs_extract(),
        **ridership(built),
    }
    return {"n_agents": len(built.persons), "build_seed": seed, "seconds": time.time() - t0, "checks": checks}
