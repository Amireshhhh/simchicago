"""Export a simulation (and optional comparison runs and experiments) for the 3D viewer."""

from __future__ import annotations

import json

from simchi import jsonutil
from pathlib import Path

import numpy as np
import pandas as pd

from simchi import __version__
from simchi.behavior.schedule import KINDS
from simchi.data.geo import rings, to_utm
from simchi.paths import DATA, VIEWER
from simchi.sim.engine import MODE_NAMES

PROVENANCE = {
    "areas": "City of Chicago community-area boundaries; statistics CMAP Community Data Snapshots (ACS 2015-2019, LEHD)",
    "agents": "synthetic (simulated) individuals calibrated to the area statistics; no real person is represented",
    "observed_incidents": "CPD reported incidents, IUCR 0325/0326 (vehicular hijacking), 2020; block-level, privacy-shifted",
    "simulated_incidents": "draws from the intensity model fitted to January-September 2020",
    "safety": "perceived safety follows a hypothesised mechanism with no data behind it",
    "buildings_default": "procedural massing conditioned on ACS housing-structure mix, CMAP land use and LEHD job density; not real buildings",
}

LENS_FIELDS = {
    "median_income": "MEDINC", "population": "TOT_POP", "households": "TOT_HH", "jobs": "TOTEMPWRK",
}


def _area_stats(world) -> list:
    t = world.cds.table
    out = []
    for num, a in world.areas.iterrows():
        r = t.loc[num]
        comm = r["TOT_COMM"]
        hu = max(r["HU_TOT"], 1)
        out.append({
            "num": int(num), "name": a["name"], "district": a["district"],
            "c": [round(a["x"], 1), round(a["z"], 1)], "rings": rings(world.cds.geoms[num].simplify(3.0)),
            "stats": {
                "median_income": float(r["MEDINC"]), "population": int(r["TOT_POP"]),
                "households": int(r["TOT_HH"]), "jobs": int(r["TOTEMPWRK"]),
                "area_km2": round(float(a["area_km2"]), 3),
                "transit_share": float(r["TRANSIT"] / comm), "car_share": float((r["DROVE_AL"] + r["CARPOOL"]) / comm),
                "walk_share": float(r["WALK_BIKE"] / comm),
                "no_vehicle_share": float(r["NO_VEH"] / r["TOT_HH"]),
                "wfh_share": float(r["WORK_HOME"] / r["T_WRKR16OV"]),
                "mean_commute_min": float(r["AGG_TT"] / comm),
                "single_family_share": float((r["HU_SNG_DET"] + r["HU_SNG_ATT"]) / hu),
                "large_multi_share": float((r["HU_10_19UN"] + r["HU_GT_19UN"]) / hu),
                "commercial_pct": float(r["COMMperc"]), "industrial_pct": float(r["INDperc"]),
                "open_pct": float(r["OPENperc"]), "residential_pct": float(r["Sfperc"] + r["Mfperc"]),
            },
        })
    return out


def _agents(built, sim) -> list:
    P = built.persons
    out = []
    for i, r in P.iterrows():
        work = None if not np.isfinite(r["work_x"]) else [round(r["work_x"], 1), round(r["work_z"], 1)]
        out.append({
            "pid": int(r["pid"]), "hh": r["hh_id"], "area": int(r["area"]), "age": int(r["age"]),
            "role": r["role"], "labor": int(r["labor"]), "edu": int(r["edu"]), "income": float(r["income"]),
            "income_bin": int(r["income_bin"]), "vehicles": int(r["vehicles"]), "tenure": int(r["tenure"]),
            "hh_size": int(r["hh_size"]), "weight": round(float(r["weight"]), 1),
            "commuter": bool(r["labor"] == 0 and not sim.wfh[i] and work is not None), "wfh": bool(sim.wfh[i]),
            "student": bool(5 <= r["age"] <= 17), "mode": MODE_NAMES[int(sim.commute_mode[i])],
            "work_area": int(r["work_area"]), "home": [round(r["home_x"], 1), round(r["home_z"], 1)],
            "work": work, "sbar": round(float(r["sbar"]), 4), "kappa": round(float(r["kappa"]), 3),
            "label": "simulated",
        })
    return out


def _segments(sim) -> dict:
    s = sim.segments
    t0 = s["day"] * 1440 + s["t0"]
    t1 = s["day"] * 1440 + s["t1"]
    rows = np.column_stack([np.round(t0, 2), np.round(t1, 2), s["kind"], np.round(s["x0"], 1), np.round(s["z0"], 1),
                            np.round(s["x1"], 1), np.round(s["z1"], 1), s["mode"]])
    order = np.lexsort((t0, s["pid"]))
    rows, pid = rows[order], s["pid"][order]
    out = {}
    for p, idx in pd.Series(np.arange(len(pid))).groupby(pid).indices.items():
        out[str(int(p))] = [[float(v) if k < 2 or 2 < k < 7 else int(v) for k, v in enumerate(r)] for r in rows[idx]]
    return out


def _incidents(sim) -> list:
    out = []
    for inc in sim.incidents:
        for _, r in inc.iterrows():
            out.append({"id": int(r["record_id"]), "t": round(float(r["day"] * 1440 + r["t_min"]), 2),
                        "pos": [round(float(r["x"]), 1), round(float(r["z"]), 1)], "area": int(r["area"]),
                        "label": r["label"], "desc": str(r["desc"]), "time": str(r["time"])})
    return out


def _interventions():
    """The committed intervention ranking (reports/interventions/interventions.json), if any."""
    from simchi.paths import REPORTS
    p = REPORTS / "interventions" / "interventions.json"
    if not p.exists():
        return None
    r = json.loads(p.read_text())
    return {k: r[k] for k in ("label", "replicates", "agents_requested", "top_bus_routes", "low_income_population_share", "ranking", "interventions")}


def build_payload(built, sim, compare: dict | None = None, experiments: list | None = None) -> dict:
    world = built.world
    frame = world.cds.frame
    with open(DATA / "reference" / "landmarks.json") as f:
        lm = json.load(f)
    landmarks = []
    for L in lm["landmarks"]:
        x, z = frame.from_lonlat(L["ll"][0], L["ll"][1])
        landmarks.append({**L, "pos": [round(float(x), 1), round(float(z), 1)]})
    events = [{k: (None if (isinstance(v, float) and not np.isfinite(v)) else v) for k, v in e.items()} for e in sim.events]
    return {
        "meta": {
            "version": __version__, "origin_lonlat": frame.origin_lonlat, "origin_utm16n": [frame.e0, frame.n0],
            "start_date": sim.cfg.start_date, "n_days": sim.cfg.n_days, "seed": sim.cfg.seed,
            "incident_mode": sim.cfg.incident_mode, "config": sim.cfg.to_dict(), "fitted": built.fitted(),
            "n_persons": len(built.persons), "represented_population": float(built.persons["weight"].sum()),
            "kinds": KINDS, "modes": MODE_NAMES,
            "provenance": {**PROVENANCE, "landmarks": lm["provenance"]},
        },
        "city_rings": rings(world.cds.city.simplify(3.0)),
        "areas": _area_stats(world),
        "agents": _agents(built, sim),
        "segments": _segments(sim),
        "incidents": _incidents(sim),
        "events": events,
        "edges": [[int(i), int(j), k] for i, j, k in built.network.edges],
        "safety": np.round(sim.safety, 4).tolist(),
        "daily": sim.daily,
        "compare": compare or {},
        "experiments": experiments or [],
        "interventions": _interventions(),
        "external_targets": {n: [round(float(x), 1), round(float(z), 1)] for n, (x, z) in zip(world.gateway_names, world.gateway_xy, strict=True)},
        "landmarks": landmarks,
    }


def export_viewer(built, sim, out: Path | None = None, compare=None, experiments=None) -> Path:
    out = Path(out) if out else VIEWER / "dist" / "data" / "run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(built, sim, compare, experiments)
    with open(out, "w") as f:
        jsonutil.dump(payload, f, separators=(",", ":"))
    return out


__all__ = ["export_viewer", "build_payload", "to_utm"]
