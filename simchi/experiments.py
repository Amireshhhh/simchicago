"""Experiments: many scenarios x many replicates on one synthetic city.

An experiment file (TOML) has a [build] table, an optional [base] config, a list of
[[scenario]] tables and optional [[sweep]] tables that expand into scenarios:

    name = "remote_work"
    replicates = 10                 # seeds 1..10 (or seeds = [..])
    [build]
    n = 2000
    seed = 1
    [base]
    n_days = 7
    incident_mode = "both"
    [[scenario]]
    name = "baseline"
    [[scenario]]
    name = "double WFH"
    set = { wfh_multiplier = 2.0 }
    [[sweep]]
    param = "safety.gamma_cancel"
    values = [0.0, 0.5, 1.0]

Keys in `set` and `param` are dotted paths into SimConfig (e.g. "safety.a",
"mode_shift.transit", "time_multiplier.transit", "schedule.discretionary_multiplier",
"network.headway_multiplier.bus", "network.ivt_multiplier.rail", "network.headway_multiplier.9"
(a route id), "network.fare_bus").

Every scenario runs with the same replicate seeds, so scenario s and the baseline share all
random numbers on a given seed (common random numbers). Effects are estimated from the
paired differences d_r = metric(s, r) - metric(baseline, r): mean, standard error and a 95%
t-interval over replicates.
"""

from __future__ import annotations

import copy

from simchi import jsonutil
import math
import os
import time
import tomllib
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from simchi.paths import REPORTS
from simchi.pipeline import Built, build
from simchi.sim.engine import SafetyParams, SimConfig, run_sim
from simchi.behavior.schedule import ScheduleParams

METRICS = [
    "incidents_observed", "incidents_simulated", "agents_exposed", "activities_cancelled",
    "activities_cancelled_weighted", "mean_out_of_home_min", "mean_evening_out_min",
    "final_perceived_safety", "trips_car", "trips_transit", "trips_walk", "trips_other",
    "pkm_car", "pkm_transit", "pkm_walk", "pkm_other", "participation_work", "participation_shop",
    "participation_social", "participation_leisure", "participation_errand",
]
METRIC_INFO = {
    "incidents_observed": "recorded incidents replayed (total)",
    "incidents_simulated": "model-drawn incidents (total)",
    "agents_exposed": "agent-days with a direct exposure (total, unweighted)",
    "activities_cancelled": "evening activities cancelled (total, unweighted)",
    "activities_cancelled_weighted": "evening activities cancelled (total, population-weighted)",
    "mean_out_of_home_min": "minutes out of home per resident per day",
    "mean_evening_out_min": "minutes out of home after 18:00 per resident per day",
    "final_perceived_safety": "mean perceived safety at the end of the run",
    "trips_car": "car trips per day (population-weighted)",
    "trips_transit": "transit trips per day (population-weighted)",
    "trips_walk": "walk trips per day (population-weighted)",
    "trips_other": "other-mode trips per day (population-weighted)",
    "pkm_car": "car person-km per day (population-weighted, straight-line x 1.3)",
    "pkm_transit": "transit person-km per day",
    "pkm_walk": "walk person-km per day",
    "pkm_other": "other-mode person-km per day",
    "participation_work": "share of residents working away from home, mean per day",
    "participation_shop": "share of residents shopping, mean per day",
    "participation_social": "share of residents visiting, mean per day",
    "participation_leisure": "share of residents on leisure trips, mean per day",
    "participation_errand": "share of residents on errands, mean per day",
}


@dataclass
class Scenario:
    name: str
    overrides: dict = field(default_factory=dict)


@dataclass
class Experiment:
    name: str
    scenarios: list
    seeds: list
    build_n: int = 2000
    build_seed: int = 1
    base: dict = field(default_factory=dict)
    baseline: str | None = None
    description: str = ""

    @classmethod
    def from_toml(cls, path) -> "Experiment":
        with open(path, "rb") as f:
            spec = tomllib.load(f)
        return cls.from_dict(spec)

    @classmethod
    def from_dict(cls, spec: dict) -> "Experiment":
        scenarios = [Scenario(s["name"], dict(s.get("set", {}))) for s in spec.get("scenario", [])]
        for sw in spec.get("sweep", []):
            for v in sw["values"]:
                label = sw.get("label", sw["param"])
                scenarios.append(Scenario(f"{label} = {v}", {sw["param"]: v, **sw.get("set", {})}))
        if not scenarios:
            raise ValueError("an experiment needs at least one [[scenario]] or [[sweep]]")
        names = [s.name for s in scenarios]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate scenario names: {names}")
        seeds = spec.get("seeds") or list(range(1, int(spec.get("replicates", 5)) + 1))
        b = spec.get("build", {})
        return cls(name=spec["name"], scenarios=scenarios, seeds=[int(s) for s in seeds],
                   build_n=int(b.get("n", 2000)), build_seed=int(b.get("seed", 1)),
                   base=dict(spec.get("base", {})), baseline=spec.get("baseline", names[0]),
                   description=spec.get("description", ""))


def make_config(base: dict, overrides: dict, seed: int) -> SimConfig:
    cfg = SimConfig()
    for key, value in {**base, **overrides}.items():
        set_path(cfg, key, value)
    cfg.seed = seed
    return cfg.validate()


def set_path(cfg: SimConfig, dotted: str, value):
    parts = dotted.split(".")
    obj = cfg
    for p in parts[:-1]:
        obj = obj[p] if isinstance(obj, dict) else getattr(obj, p)
    last = parts[-1]
    if isinstance(obj, dict):
        if last not in obj and parts[:-1] not in (["network", "headway_multiplier"], ["network", "ivt_multiplier"], ["network", "wait_multiplier"]):
            raise KeyError(f"unknown setting {dotted!r}")
        obj[last] = value
    else:
        if not hasattr(obj, last):
            raise KeyError(f"unknown setting {dotted!r}")
        current = getattr(obj, last)
        if isinstance(current, (SafetyParams, ScheduleParams)) and isinstance(value, dict):
            for k, v in value.items():
                set_path(cfg, f"{dotted}.{k}", v)
        else:
            setattr(obj, last, type(current)(value) if isinstance(current, (int, float)) and not isinstance(current, bool) else value)


def summarize_run(sim) -> dict:
    d = sim.daily
    n_days = len(d)
    out = {
        "incidents_observed": sum(x["incidents_observed"] for x in d),
        "incidents_simulated": sum(x["incidents_simulated"] for x in d),
        "agents_exposed": sum(x["agents_exposed"] for x in d),
        "activities_cancelled": sum(x["activities_cancelled"] for x in d),
        "activities_cancelled_weighted": sum(x["activities_cancelled_weighted"] for x in d),
        "mean_out_of_home_min": float(np.mean([x["mean_out_of_home_min"] for x in d])),
        "mean_evening_out_min": float(np.mean([x["mean_evening_out_min"] for x in d])),
        "final_perceived_safety": d[-1]["mean_perceived_safety"],
    }
    for m in ("car", "transit", "walk", "other"):
        out[f"trips_{m}"] = sum(x["trips_weighted"][m] for x in d) / n_days
        out[f"pkm_{m}"] = sum(x["pkm_weighted"][m] for x in d) / n_days
    for a in ("work", "shop", "social", "leisure", "errand"):
        out[f"participation_{a}"] = float(np.mean([x["participation"][a] for x in d]))
    return out


_BUILT: Built | None = None


def _worker(args):
    base, overrides, seed, scenario = args
    t0 = time.time()
    sim = run_sim(_BUILT, make_config(base, overrides, seed))
    return {"scenario": scenario, "seed": seed, "seconds": time.time() - t0, **summarize_run(sim)}


def run_experiment(exp: Experiment, workers: int | None = None, outdir: Path | None = None,
                   built: Built | None = None, progress=print) -> dict:
    global _BUILT
    _BUILT = built or build(exp.build_n, exp.build_seed)
    from simchi.sim.engine import scenario_skim
    for s in exp.scenarios:                    # fail fast on bad settings; build network skims once
        scenario_skim(_BUILT, make_config(exp.base, s.overrides, exp.seeds[0]))
    jobs = [(exp.base, s.overrides, seed, s.name) for s in exp.scenarios for seed in exp.seeds]
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 2)))
    t0 = time.time()
    rows = []
    if workers == 1:
        for k, j in enumerate(jobs, 1):
            rows.append(_worker(j))
            progress(f"  run {k}/{len(jobs)}: {j[3]} seed {j[2]}")
    else:
        import multiprocessing as mp
        ctx = mp.get_context("fork")           # workers inherit the built city (copy-on-write)
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
            for k, r in enumerate(pool.map(_worker, jobs), 1):
                rows.append(r)
                if k % max(1, len(jobs) // 10) == 0 or k == len(jobs):
                    progress(f"  {k}/{len(jobs)} runs done")
    runs = pd.DataFrame(rows)
    result = analyse(exp, runs)
    result["wall_seconds"] = time.time() - t0
    result["workers"] = workers
    out = Path(outdir) if outdir else REPORTS / "experiments" / exp.name
    out.mkdir(parents=True, exist_ok=True)
    runs.to_csv(out / "runs.csv", index=False)
    pd.DataFrame(result["summary"]).to_csv(out / "summary.csv", index=False)
    pd.DataFrame(result["effects"]).to_csv(out / "effects.csv", index=False)
    with open(out / "experiment.json", "w") as f:
        jsonutil.dump(result, f, indent=1)
    result["outdir"] = str(out)
    return result


def _ci(x: np.ndarray):
    n = len(x)
    mean = float(np.mean(x))
    if n < 2:
        return mean, float("nan"), float("nan"), float("nan")
    se = float(np.std(x, ddof=1) / math.sqrt(n))
    h = float(stats.t.ppf(0.975, n - 1) * se)
    return mean, se, mean - h, mean + h


def analyse(exp: Experiment, runs: pd.DataFrame) -> dict:
    summary, effects = [], []
    base = runs[runs["scenario"] == exp.baseline].set_index("seed")
    for s in exp.scenarios:
        r = runs[runs["scenario"] == s.name].set_index("seed")
        for m in METRICS:
            mean, se, lo, hi = _ci(r[m].to_numpy(float))
            summary.append({"scenario": s.name, "metric": m, "mean": mean, "se": se, "ci_low": lo, "ci_high": hi, "n": len(r)})
            if s.name != exp.baseline:
                d = (r[m] - base[m]).dropna().to_numpy(float)
                dm, dse, dlo, dhi = _ci(d)
                bmean = float(base[m].mean())
                effects.append({"scenario": s.name, "metric": m, "baseline_mean": bmean, "diff": dm, "se": dse,
                                "ci_low": dlo, "ci_high": dhi,
                                "rel_diff": dm / bmean if bmean else float("nan"),
                                "significant": bool(np.isfinite(dlo) and (dlo > 0 or dhi < 0))})
    return {"name": exp.name, "description": exp.description, "baseline": exp.baseline,
            "build": {"n": exp.build_n, "seed": exp.build_seed}, "base": exp.base, "seeds": exp.seeds,
            "scenarios": [{"name": s.name, "set": s.overrides} for s in exp.scenarios],
            "metrics": METRIC_INFO, "summary": summary, "effects": effects}


def copy_config(cfg: SimConfig) -> SimConfig:
    return copy.deepcopy(cfg)
