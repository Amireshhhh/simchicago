"""Aggregated statistics for the viewer's Overview and Insights pages (viewer/dist/data/insights.json).

Everything here is read from the pinned data mirrors and the committed reports; each block
carries its provenance label (observed, scheduled, simulated, hypothesis).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from simchi import jsonutil
from simchi.paths import REPORTS, VIEWER


def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def ridership_block() -> dict:
    from simchi.transit.gtfs import load_extract
    from simchi.transit.ridership import load_observed
    routes = {r["id"]: r for r in load_extract("routes")}
    out = {"label": "observed", "source": "CTA ridership, City of Chicago data portal (daily totals)"}
    weekly = {}
    for kind in ("bus", "rail"):
        df = load_observed(kind)
        daily = df.groupby("date")["rides"].sum()
        wk = daily.groupby(daily.index.to_period("W-SUN"))
        full = wk.size() == 7
        w = wk.mean()[full]
        weekly[kind] = w
        last12 = df[df["date"] > df["date"].max() - pd.Timedelta(days=365)]
        wd = last12[last12["daytype"] == "W"].groupby(["id"])["rides"].mean().sort_values(ascending=False)
        names = df.drop_duplicates("id").set_index("id").get("stationname")
        top = []
        for uid, v in wd.head(15).items():
            name = (routes[uid]["long"] if uid in routes else uid) if kind == "bus" else (names.get(uid, uid) if names is not None else uid)
            top.append({"id": uid, "name": name, "weekday_rides": float(v)})
        out[f"top_{kind}"] = top
        last = df["date"].max()
        yr = df[df["date"] > last - pd.Timedelta(days=365)]["rides"].sum()
        prev = df[(df["date"] <= last - pd.Timedelta(days=365)) & (df["date"] > last - pd.Timedelta(days=730))]["rides"].sum()
        out[f"{kind}_last12_total"] = float(yr)
        out[f"{kind}_yoy"] = float(yr / prev - 1) if prev > 0 else None
    idx = weekly["bus"].index.intersection(weekly["rail"].index)
    out["weekly"] = {"week_start": [str(p.start_time.date()) for p in idx],
                     "bus": [round(float(weekly["bus"][p])) for p in idx],
                     "rail": [round(float(weekly["rail"][p])) for p in idx]}
    out["period"] = [out["weekly"]["week_start"][0], str(last.date())]
    return out


def network_block() -> dict:
    from simchi.transit.gtfs import load_extract
    m = load_extract("meta")
    return {"label": "scheduled", "counts": m["counts"], "source_sha256": m["source_sha256"][:12],
            "reference_dates": m["reference_dates"]}


def validation_block() -> list:
    v = _load(REPORTS / "validation.json")
    if not v:
        return []
    names = {
        "data_integrity": ("Data integrity", "data"), "cds_identities": ("Census count identities", "data"),
        "calibration": ("Population calibration", "model"), "gravity_holdout": ("Commute destinations", "model"),
        "mode_choice_holdout": ("Mode choice (CTA network)", "model"), "commute_time_holdout": ("Commute time", "model"),
        "incident_forecast": ("Incident forecast", "model"), "engine_invariants": ("Engine invariants", "engine"),
        "gtfs_extract": ("CTA GTFS extract", "data"), "ridership_bus": ("Bus-route ridership", "transit"),
        "ridership_rail": ("'L' station ridership", "transit"), "crowding_forecast_bus": ("Crowding forecast, bus", "ops"),
        "crowding_forecast_rail": ("Crowding forecast, 'L'", "ops"), "holding_simulated": ("Holding rule (simulated)", "ops"),
        "anomaly_detectors": ("Anomaly detectors", "ops")}
    out = []
    for k, c in v["checks"].items():
        label, group = names.get(k, (k, "other"))
        out.append({"key": k, "label": label, "group": group, "pass": c["pass"], "summary": c["summary"]})
    return out


def interventions_block():
    r = _load(REPORTS / "interventions" / "interventions.json")
    if not r:
        return None
    return {k: r[k] for k in ("label", "replicates", "top_bus_routes", "low_income_population_share", "ranking")}


def ops_block() -> dict:
    out = {}
    c = _load(REPORTS / "ops" / "crowding.json")
    if c:
        from simchi.transit.gtfs import load_extract
        routes = {r["id"]: r["long"] for r in load_extract("routes")}
        nw = [x for x in c["bus"]["next_week"] if x["daytype"] == "W" and x.get("rides_per_trip")]
        first = min(x["date"] for x in nw) if nw else None
        day = sorted([x for x in nw if x["date"] == first], key=lambda x: -x["rides_per_trip"])[:12]
        out["crowding"] = {"label": "observed history, forecast", "asof": c["bus"]["next_week_asof"], "date": first,
                           "male": {k: {m: c[k][m]["male"] for m in ("B_naive", "M_med4")} for k in ("bus", "rail")},
                           "top_bus": [{"id": x["id"], "name": routes.get(x["id"], x["id"]), "rides": x["forecast_rides"],
                                        "trips": x["scheduled_trips"], "per_trip": x["rides_per_trip"]} for x in day]}
    h = _load(REPORTS / "ops" / "holding.json")
    if h:
        out["holding"] = {"label": "simulated", "preregistered": h["preregistered_run_terminal_start"]["mean_wait_min"],
                          "corrected": h["corrected_start"]["mean_wait_min"]}
    a = _load(REPORTS / "ops" / "anomalies.json")
    if a:
        out["anomalies"] = {"label": "simulated feed, constructed labels", "detectors": a["detectors"]}
    rel = _load(REPORTS / "reliability" / "summary.json")
    if rel:
        out["reliability"] = {"coverage": rel["coverage"], "system": rel.get("system"),
                              "polling_bias": [{"inputs": b["inputs"], "truth": b["truth"], "estimate": b["estimate"]} for b in rel["polling_bias_simulated"]]}
    return out


def models_block() -> dict:
    out = {}
    mi = _load(REPORTS / "mode_choice_identification.json")
    if mi:
        out["elasticity"] = {"label": "simulated (fitted model)", **mi["arc_elasticity_transit_share"],
                             "fare_by_vot": mi["arc_elasticity_transit_share_fare_+10pct"],
                             "transit_share_model": mi["city_transit_share_model"], "transit_share_acs": mi["city_transit_share_acs"]}
    rv = _load(REPORTS / "ridership_validation.json")
    if rv:
        out["ridership_validation"] = {k: {"units": rv[k]["units"], "male": rv[k]["male_heldout_units_and_period"],
                                           "persistence": rv[k]["male_period_only"]["persistence (own 2024 mean)"]} for k in ("bus", "rail")}
    td = _load(REPORTS / "experiments" / "transit_disruption" / "experiment.json")
    if td:
        out["transit_disruption"] = [{"scenario": e["scenario"], "rel": e["rel_diff"], "ci_low": e["ci_low"] / e["baseline_mean"],
                                      "ci_high": e["ci_high"] / e["baseline_mean"]} for e in td["effects"] if e["metric"] == "trips_transit"]
    return out


def service_design_block():
    r = _load(REPORTS / "service_design" / "service_design.json")
    if not r:
        return None
    recs = r["route_recommendations"]
    up = sorted(recs, key=lambda x: -x["multiplier"])[:12]
    down = sorted(recs, key=lambda x: x["multiplier"])[:12]
    keep = ("name", "vehicle_hours", "transit_trips", "car_trips", "time_saved_min", "low_income_share_of_savings", "access_jobs",
            "access_gain_low", "access_gain_other")
    return {"label": r["label"], "replicates": r["replicates"], "low_income_population_share": r["low_income_population_share"],
            "results": [{k: x.get(k) for k in keep} for x in r["results"]], "analytic": r["analytic"],
            "more_service": up, "less_service": down, "routes": len(recs)}


def build_insights() -> dict:
    return {"schema": "simchi.insights/1", "network": network_block(), "ridership": ridership_block(),
            "validation": validation_block(), "models": models_block(), "interventions": interventions_block(),
            "ops": ops_block(), "service_design": service_design_block()}


def export_insights(out: Path | None = None) -> Path:
    out = Path(out) if out else VIEWER / "dist" / "data" / "insights.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        jsonutil.dump(build_insights(), f, separators=(",", ":"))
    return out


__all__ = ["build_insights", "export_insights", "np"]
