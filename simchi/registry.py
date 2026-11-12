"""Registry of every model parameter with its value, provenance class and source.

`python scripts/make_parameters_doc.py` writes docs/PARAMETERS.md from it.
"""

from __future__ import annotations

from dataclasses import asdict

from simchi.behavior.mode_choice import PARAM_NAMES
from simchi.behavior.travel import CIRCUITY, WALK_KMH
from simchi.pipeline import DISC_DECAY_PER_KM, INTENSITY_TRAIN, Built
from simchi.provenance import Prov
from simchi.sim.engine import SafetyParams, SimConfig
from simchi.behavior.schedule import ScheduleParams
from simchi.world import OUTSIDE_EXTRA_KM


def registry(built: Built) -> list[dict]:
    rows = []

    def add(group, name, value, prov: Prov, source):
        rows.append({"group": group, "name": name, "value": value, "provenance": prov.value, "source": source})

    g = built.gravity
    for k, v in g.as_dict().items():
        add("commute destination (gravity)", k, round(v, 5), Prov.FITTED, "max. likelihood, LEHD top-5 destinations (CDS RESCITY1..5) + EMP")
    for k, v in built.mode_model.as_dict().items():
        if k.startswith("b_fare"):
            add("commute mode (MNL)", k, round(v, 4), Prov.HYPOTHESIS, f"60 x b_ivt / value of time ${built.mode_model.vot_per_hour:.0f}/h (assumed; not estimable: fares are flat)")
        else:
            add("commute mode (MNL)", k, round(v, 4), Prov.FITTED, "max. likelihood, ACS commute-mode counts by area (CDS) on CTA network level of service; sign-constrained")
    add("commute mode (MNL)", "value_of_time_per_hour", built.mode_model.vot_per_hour, Prov.HYPOTHESIS, "assumption; only used for fare scenarios")
    tr = built.travel
    add("travel time", "v_car_kmh", round(tr.v_car, 2), Prov.FITTED, "least squares, ACS mean commute time AGG_TT / TOT_COMM (alternating with the mode-choice fit)")
    add("travel time", "v_other_kmh", tr.v_other, Prov.HYPOTHESIS, "assumption")
    add("travel time", "tau_car_min", tr.tau_car, Prov.HYPOTHESIS, "assumption (parking)")
    add("travel time", "walk_kmh", WALK_KMH, Prov.HYPOTHESIS, "assumption")
    add("travel time", "circuity", CIRCUITY, Prov.HYPOTHESIS, "assumption")
    add("travel time", "transit fallback tau / v", f"{tr.tau_transit:.1f} min / {tr.v_transit:.1f} km/h", Prov.FITTED,
        "least-squares line through the area-to-area network skim; used only for trips not placed in an area")
    from simchi.transit import network as N
    for k in ("ACCESS_M", "ACCESS_MIN_STOPS", "TRANSFER_M", "WAIT_CAP_MIN", "PATH_W_WALK", "PATH_W_WAIT",
              "TRANSFER_PENALTY_MIN", "REGIONAL_RADIUS_KM", "REGIONAL_MIN_STOPS", "REGIONAL_TERMINAL_MIN", "REGIONAL_KMH", "ZONE_POINTS", "ASSIGN_POINTS"):
        add("transit network", k, getattr(N, k), Prov.HYPOTHESIS, "assumption (path building; see simchi/transit/network.py)")
    add("transit network", "scheduled headways and in-vehicle times", "GTFS weekday 6-9 am", Prov.OBSERVED, "CTA GTFS feed (data/transit/), scheduled service")
    add("transit network", "fares (bus / 'L')", f"${N.FARE_BUS:.2f} / ${N.FARE_RAIL:.2f}", Prov.OBSERVED, "transitchicago.com/fares, read 2026-11-12")
    add("world", "outside_extra_km", OUTSIDE_EXTRA_KM, Prov.HYPOTHESIS, "assumption: jobs outside Chicago lie this far past the nearest gateway")
    import json

    from simchi.paths import REPORTS
    rv = REPORTS / "ridership_validation.json"
    if rv.exists():
        r = json.loads(rv.read_text())
        for kind, label in (("bus", "bus routes"), ("rail", "'L' stations")):
            C = r[kind]["fold_coefficients"]["M_cal"]
            rng = ", ".join(f"[{min(c[i] for c in C):.3f}, {max(c[i] for c in C):.3f}]" for i in range(3))
            add("ridership calibration", f"{label}: log rides = a + b log(1 + model) + c log(scheduled trips)", f"a, b, c ranges over 5 folds: {rng}",
                Prov.FITTED, "least squares on 2024 weekday means of the training folds (CTA ridership, City of Chicago data portal)")
    add("interventions", "bus priority in-vehicle multiplier", 0.85, Prov.HYPOTHESIS, "assumed effect of bus lanes / signal priority (simchi/interventions.py)")
    add("interventions", "bus headway CV before / after reliability measure", "0.6 / 0.4", Prov.HYPOTHESIS, "assumed; wait multiplier (1 + 0.4^2) / (1 + 0.6^2)")
    add("interventions", "accessibility limits", "45 min (AM peak), 60 min (night)", Prov.SCENARIO, "definition")
    add("interventions", "low-income areas", "lowest median income, 25% of residents", Prov.SCENARIO, "definition (ACS MEDINC, TOT_POP)")
    im = built.intensity
    add("incidents", "level_per_day", round(im.level_per_day, 4), Prov.FITTED, f"CPD records {INTENSITY_TRAIN[0]} to {INTENSITY_TRAIN[1]}")
    add("incidents", "alpha (Dirichlet-multinomial)", round(im.alpha, 2), Prov.FITTED, "max. likelihood, weekly area counts")
    add("incidents", "omega (Mon..Sun)", [round(x, 3) for x in im.omega], Prov.FITTED, "weekday frequencies (add-1/2)")
    add("incidents", "eta peak hour", int(im.eta.argmax()), Prov.FITTED, "hour-of-day frequencies (add-1/2)")
    add("discretionary destinations", "decay_per_km", DISC_DECAY_PER_KM, Prov.HYPOTHESIS, "assumption")
    for k, v in asdict(SafetyParams()).items():
        add("perceived safety (default)", k, v, Prov.HYPOTHESIS, "hypothesised mechanism; no data")
    sp = ScheduleParams()
    for k, v in asdict(sp).items():
        add("schedule (default)", k, v, Prov.SCENARIO, "SimChicago v0.1 exported configuration")
    cfg = SimConfig()
    for k in ("wfh_multiplier", "mode_shift", "time_multiplier", "network", "simulated_incident_multiplier", "local_trip_share"):
        add("scenario knobs (default)", k, getattr(cfg, k), Prov.SCENARIO, "what-if setting")
    add("agents", "household and person attributes", "calibrated weights", Prov.ESTIMATED, "CMAP CDS (ACS 2015-19) marginals by community area")
    add("agents", "home point", "sampled", Prov.LATENT, "tract chosen by 2014 population, uniform within")
    add("agents", "u_wfh, u_mode, work area, kappa", "sampled", Prov.LATENT, "model draws")
    add("agents", "sbar (baseline perceived safety)", "0.9 - 2.5 x tract violent-crime rate, clipped to [0.4, 0.95]", Prov.HYPOTHESIS, "SDOH 2014 VCRIMERT15; mapping assumed")
    add("social network", "household / coworker / neighbour weights", "1.0 / 0.5 / 0.5", Prov.HYPOTHESIS, "assumption; no network data")
    return rows


def as_markdown(rows) -> str:
    out = ["# Parameter registry", "",
           "Generated by `python scripts/make_parameters_doc.py` from the fitted models of the default build "
           "(2,000 requested agents, seed 1). Provenance classes are defined in `simchi/provenance.py`.", ""]
    group = None
    for r in rows:
        if r["group"] != group:
            group = r["group"]
            out += ["", f"## {group}", "", "| Parameter | Value | Provenance | Source |", "|---|---|---|---|"]
        v = r["value"]
        out.append(f"| `{r['name']}` | {v} | {r['provenance']} | {r['source']} |")
    return "\n".join(out) + "\n"


__all__ = ["registry", "as_markdown", "PARAM_NAMES"]
