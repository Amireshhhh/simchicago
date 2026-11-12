"""Ridership calibration and held-out validation (python -m simchi.eval.ridership).

PRE-REGISTERED DESIGN (fixed in this docstring before any 2025-2026 ridership was examined;
the 2024 data of all routes and stations had been looked at during development, so 2024
results are not out of sample in time):

Units
  bus   CTA bus routes present in the GTFS extract and with positive mean weekday rides in
        both periods
  rail  'L' stations inside the City of Chicago (station point in a community area) with
        positive mean weekday entries in both periods
Periods
  training  2024-01-01 .. 2024-12-31 (mean weekday rides per unit)
  test      2025-01-01 .. 2026-08-31 (mean weekday rides per unit)
Features
  m = log(1 + model weekday commute boardings/entries), from the simulation's network assignment
      (simchi.transit.ridership.predict)
  s = log(scheduled weekday vehicle trips of the route / train departures at the station)
Predictors of log(rides), each fitted by least squares on the training units' training period
  B_mean     a
  B_service  a + c s
  M_sim      a + m                 (simulation only; one calibrated scale factor)
  M_cal      a + b m + c s         (simulation calibrated together with scheduled service)
Held-out evaluation (primary): 5 folds of units (fixed shuffle, seed 0); for each fold, fit on
  the other folds' training-period means, predict the fold's test-period means.
  Metric: mean absolute log error (MALE) over all units.
Pass criteria (per mode, bus and rail):
  ridership_<mode>: MALE(M_cal) < MALE(B_service) and MALE(M_cal) < MALE(B_mean)
Also reported, not criteria: MALE(M_sim); a period-only holdout (fit on all units' 2024 means,
  test on all units' 2025-26 means) with the persistence reference (each unit's own 2024 mean).
Replicate variance (replicates()): the simulation's agent-based commute OD for several build
  seeds (different synthetic populations) instead of the expected OD; coefficient of variation
  of the predictions per unit, and MALE of M_cal per seed.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from simchi.paths import REPORTS
from simchi.transit import network as N
from simchi.transit import ridership as R

TRAIN = ("2024-01-01", "2024-12-31")
TEST = ("2025-01-01", "2026-08-31")
FOLDS = 5


def _units(graph, model_bus, model_rail):
    from simchi.world import area_of_points
    obs = {}
    for kind in ("bus", "rail"):
        df = R.load_observed(kind)
        tr, te = R.weekday_means(df, *TRAIN), R.weekday_means(df, *TEST)
        ids = tr.index.intersection(te.index)
        ids = ids[(tr[ids] > 0) & (te[ids] > 0)]
        model = model_bus if kind == "bus" else model_rail
        ids = ids.intersection(model.index)
        if kind == "rail":
            st = pd.DataFrame(json_load("stations")).set_index("id")
            st = st.loc[st.index.intersection(ids)]
            inside = area_of_points(graph.world, st[["x", "z"]].to_numpy(float)) > 0
            ids = st.index[inside]
        obs[kind] = (tr[ids].sort_index(), te[ids].sort_index())
    return obs


def json_load(name):
    from simchi.transit.gtfs import load_extract
    return load_extract(name)


def _design(m, s):
    return {"B_mean": np.ones((len(m), 1)),
            "B_service": np.column_stack([np.ones(len(m)), s]),
            "M_sim": np.ones((len(m), 1)),
            "M_cal": np.column_stack([np.ones(len(m)), m, s])}


def _fit_predict(name, Xtr, ytr, mtr, Xte, mte):
    off_tr = mtr if name == "M_sim" else 0.0
    off_te = mte if name == "M_sim" else 0.0
    beta = np.linalg.lstsq(Xtr, ytr - off_tr, rcond=None)[0]
    return Xte @ beta + off_te, beta


def evaluate(obs_train: pd.Series, obs_test: pd.Series, model: pd.Series, service: pd.Series, seed: int = 0) -> dict:
    ids = obs_train.index
    m = np.log1p(model.reindex(ids).fillna(0.0).to_numpy())
    s = np.log(service.reindex(ids).to_numpy(float))
    ytr = np.log(obs_train.to_numpy(float))
    yte = np.log(obs_test.reindex(ids).to_numpy(float))
    rng = np.random.default_rng(seed)
    fold = np.empty(len(ids), int)
    fold[rng.permutation(len(ids))] = np.arange(len(ids)) % FOLDS
    D = _design(m, s)
    err = {k: np.zeros(len(ids)) for k in D}
    coefs = {k: [] for k in D}
    for f in range(FOLDS):
        te, tr = fold == f, fold != f
        for k, X in D.items():
            pred, beta = _fit_predict(k, X[tr], ytr[tr], m[tr], X[te], m[te])
            err[k][te] = np.abs(yte[te] - pred)
            coefs[k].append(beta.tolist())
    period = {}
    for k, X in D.items():
        pred, beta = _fit_predict(k, X, ytr, m, X, m)
        period[k] = float(np.abs(yte - pred).mean())
    period["persistence (own 2024 mean)"] = float(np.abs(yte - ytr).mean())
    male = {k: float(v.mean()) for k, v in err.items()}
    return {"units": len(ids), "male_heldout_units_and_period": male,
            "pass": bool(male["M_cal"] < male["B_service"] and male["M_cal"] < male["B_mean"]),
            "male_period_only": period, "fold_coefficients": coefs,
            "corr_log_model_vs_log_obs_train": float(np.corrcoef(m, ytr)[0, 1]),
            "corr_log_service_vs_log_obs_train": float(np.corrcoef(s, ytr)[0, 1]),
            "units_with_zero_model_prediction": int((m == 0).sum()),
            "observed_train_total": float(np.exp(ytr).sum()), "observed_test_total": float(np.exp(yte).sum())}


def model_predictions(built, T=None):
    graph = N._graph(N.ASSIGN_POINTS)
    if T is None:
        T = R.commute_transit_od(built.world, built.gravity.probs(built.world), built.mode_model, built.travel, built.skim)
    bus, rail = R.predict(graph, N.NetworkScenario(), T)
    return graph, bus, rail, T


def run(built=None) -> dict:
    from simchi.pipeline import build
    built = built or build(2000, 1)
    graph, bus, rail, T = model_predictions(built)
    sb, ss = R.scheduled_service(graph)
    obs = _units(graph, bus, rail)
    out = {"design": __doc__.split("PRE-REGISTERED DESIGN")[1].strip().split("\n")[0],
           "train_period": TRAIN, "test_period": TEST,
           "model_commute_transit_trips_per_weekday": float(T.sum())}
    for kind, model, service in (("bus", bus, sb), ("rail", rail, ss)):
        tr, te = obs[kind]
        out[kind] = evaluate(tr, te, model, service)
        out[kind]["model_total_unscaled"] = float(model.reindex(tr.index).fillna(0).sum())
    return out


def agent_od(built, sim_cfg=None) -> np.ndarray:
    """(77, 78) weekday commute transit trips from the agents (weights x 2), using the engine's
    mode choice and work-from-home draws."""
    from simchi.sim.engine import SimConfig, _choose_modes, scenario_skim
    cfg = sim_cfg or SimConfig()
    P = built.persons
    modes = _choose_modes(built, cfg, scenario_skim(built, cfg))
    employed = (P["labor"] == 0).to_numpy()
    wfh = employed & (P["u_wfh"].to_numpy() < np.clip(P["p_wfh"].to_numpy() * cfg.wfh_multiplier, 0, 1))
    commuter = employed & ~wfh & np.isfinite(P["work_x"].to_numpy()) & (modes == 3)
    i = P["area"].to_numpy()[commuter] - 1
    j = P["work_area"].to_numpy()[commuter] - 1
    T = np.zeros((77, 78))
    np.add.at(T, (i, j), 2.0 * P["weight"].to_numpy()[commuter])
    return T


def replicates(seeds=(1, 2, 3, 4, 5), n=2000) -> dict:
    from simchi.pipeline import build
    preds, males = {"bus": [], "rail": []}, {"bus": [], "rail": []}
    for sd in seeds:
        b = build(n, sd)
        graph, bus, rail, T = model_predictions(b, agent_od(b))
        sb, ss = R.scheduled_service(graph)
        obs = _units(graph, bus, rail)
        for kind, model, service in (("bus", bus, sb), ("rail", rail, ss)):
            tr, te = obs[kind]
            preds[kind].append(model.reindex(tr.index).fillna(0.0))
            males[kind].append(evaluate(tr, te, model, service)["male_heldout_units_and_period"])
    out = {"seeds": list(seeds), "n_agents_requested": n}
    for kind in ("bus", "rail"):
        M = pd.concat(preds[kind], axis=1)
        mean = M.mean(1)
        cv = (M.std(1, ddof=1) / mean.replace(0, np.nan)).dropna()
        out[kind] = {"median_cv_of_unit_prediction": float(cv.median()), "p90_cv": float(cv.quantile(0.9)),
                     "male_by_seed": males[kind],
                     "male_M_cal_range": [min(x["M_cal"] for x in males[kind]), max(x["M_cal"] for x in males[kind])],
                     "male_B_service_range": [min(x["B_service"] for x in males[kind]), max(x["B_service"] for x in males[kind])]}
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out = run()
    if "--replicates" in argv:
        out["replicates"] = replicates()
    REPORTS.mkdir(exist_ok=True)
    with open(REPORTS / "ridership_validation.json", "w") as f:
        json.dump(out, f, indent=1)
    for kind in ("bus", "rail"):
        r = out[kind]
        print(kind, r["units"], "units; held-out MALE", {k: round(v, 3) for k, v in r["male_heldout_units_and_period"].items()},
              "PASS" if r["pass"] else "FAIL")
        print("   period-only MALE", {k: round(v, 3) for k, v in r["male_period_only"].items()})
    if "replicates" in out:
        print(json.dumps(out["replicates"], indent=1))


if __name__ == "__main__":
    main()
