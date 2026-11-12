"""Command-line interface: python -m simchi.cli <command>  (or `simchi <command>`)."""

from __future__ import annotations

import argparse
import json
import sys
import time

from simchi import jsonutil
from simchi.paths import REPORTS, RUNS, ROOT


def _build(args):
    from simchi.pipeline import build
    t0 = time.time()
    b = build(args.agents, args.build_seed, cache=not args.no_cache)
    print(f"city built: {len(b.persons)} synthetic residents in {len(b.population.households)} households "
          f"({time.time() - t0:.1f} s)")
    return b


def cmd_run(args):
    from simchi.experiments import make_config
    from simchi.pipeline import run
    from simchi.export.viewer import export_viewer
    b = _build(args)
    overrides = dict(kv.split("=", 1) for kv in args.set)
    overrides = {k: json.loads(v) if v[:1] in "0123456789-[{tf\"" else v for k, v in overrides.items()}
    cfg = make_config({"incident_mode": args.incidents, "n_days": args.days, "start_date": args.start}, overrides, args.seed)
    t0 = time.time()
    sim = run(b, cfg, RUNS / args.name)
    print(f"run {args.name!r}: {args.days} days in {time.time() - t0:.1f} s -> {RUNS / args.name}")
    for d in sim.daily:
        print(f"  {d['date']} {d['weekday'][:3]}  incidents {d['incidents_observed']} recorded + "
              f"{d['incidents_simulated']} simulated  exposed {d['agents_exposed']}  cancelled {d['activities_cancelled']}  "
              f"safety {d['mean_perceived_safety']:.4f}")
    if args.export:
        print("viewer data:", export_viewer(b, sim))


def cmd_experiment(args):
    from simchi.experiments import Experiment, run_experiment
    exp = Experiment.from_toml(args.file)
    if args.replicates:
        exp.seeds = list(range(1, args.replicates + 1))
    print(f"experiment {exp.name!r}: {len(exp.scenarios)} scenarios x {len(exp.seeds)} replicates")
    res = run_experiment(exp, workers=args.workers)
    print(f"done in {res['wall_seconds']:.1f} s on {res['workers']} workers -> {res['outdir']}")
    shown = set(args.metrics.split(",")) if args.metrics else {"activities_cancelled", "mean_evening_out_min",
                                                                "final_perceived_safety", "pkm_car", "pkm_transit"}
    print(f"\neffects vs {res['baseline']!r} (paired over seeds; * = 95% CI excludes 0)")
    for e in res["effects"]:
        if e["metric"] in shown:
            star = "*" if e["significant"] else " "
            print(f"  {e['scenario'][:38]:38s} {e['metric'][:28]:28s} {e['diff']:+12.4f} "
                  f"[{e['ci_low']:+.4f}, {e['ci_high']:+.4f}] {star}")


def cmd_demo(args):
    """Build the city, run the default week plus three comparison runs, export the viewer."""
    from simchi.experiments import Experiment, make_config, run_experiment
    from simchi.export.viewer import export_viewer
    from simchi.pipeline import run
    b = _build(args)
    base = {"n_days": 7, "start_date": "2020-10-05"}
    main = run(b, make_config(base, {"incident_mode": "both"}, 1), RUNS / "demo")
    compare = {}
    for label, over in [("No incidents", {"incident_mode": "none"}),
                        ("Recorded incidents only", {"incident_mode": "replay"}),
                        ("Incidents, no behavioural response", {"incident_mode": "both", "safety.a": 0.0, "safety.b": 0.0, "safety.gamma_cancel": 0.0})]:
        sim = run(b, make_config(base, over, 1))
        compare[label] = {"daily": sim.daily, "config": sim.cfg.to_dict()}
    experiments = []
    if not args.skip_experiments:
        for name in ("incident_response", "remote_work", "transit_disruption", "safety_sensitivity"):
            exp = Experiment.from_toml(ROOT / "configs" / "experiments" / f"{name}.toml")
            exp.seeds = exp.seeds[: args.replicates]
            print(f"experiment {name}: {len(exp.scenarios)} scenarios x {len(exp.seeds)} replicates")
            res = run_experiment(exp, built=b, progress=lambda m: None)
            experiments.append({k: res[k] for k in ("name", "description", "baseline", "scenarios", "metrics", "summary", "effects", "seeds")})
    out = export_viewer(b, main, compare=compare, experiments=experiments)
    print("viewer data:", out)
    from simchi.export.transit_layer import export_layer
    print("transit layer:", export_layer())


def cmd_serve(args):
    import uvicorn
    uvicorn.run("simchi.api.app:app", host=args.host, port=args.port)


def cmd_validate(args):
    from simchi.eval.run_all import run_all
    rep = run_all(n=args.agents, seed=args.build_seed)
    out = REPORTS / "validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        jsonutil.dump(rep, f, indent=1)
    print("validation report:", out)
    for k, v in rep["checks"].items():
        print(f"  {'PASS' if v['pass'] else 'FAIL'}  {k}: {v['summary']}")
    if not all(v["pass"] for v in rep["checks"].values()):
        sys.exit(1)


def cmd_export(args):
    from simchi.experiments import make_config
    from simchi.export.viewer import export_viewer
    from simchi.pipeline import run
    b = _build(args)
    sim = run(b, make_config({"incident_mode": args.incidents, "n_days": args.days}, {}, args.seed))
    print("viewer data:", export_viewer(b, sim))
    from simchi.export.transit_layer import export_layer
    print("transit layer:", export_layer())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="simchi", description=__doc__)
    ap.add_argument("--agents", type=int, default=2000, help="synthetic residents to build (default 2000)")
    ap.add_argument("--build-seed", type=int, default=1)
    ap.add_argument("--no-cache", action="store_true", help="rebuild the city instead of using runs/.cache")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="one simulation")
    r.add_argument("--name", default="myrun")
    r.add_argument("--incidents", default="both", choices=["none", "replay", "simulated", "both"])
    r.add_argument("--days", type=int, default=7)
    r.add_argument("--start", default="2020-10-05")
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="dotted SimConfig setting, e.g. --set wfh_multiplier=2 --set safety.a=0.3")
    r.add_argument("--export", action="store_true", help="also write the viewer data")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("experiment", help="scenarios x replicates from a TOML file")
    e.add_argument("file")
    e.add_argument("--workers", type=int, default=None)
    e.add_argument("--replicates", type=int, default=None, help="override the file's replicate count")
    e.add_argument("--metrics", default="", help="comma-separated metrics to print")
    e.set_defaults(func=cmd_experiment)

    d = sub.add_parser("demo", help="default week, comparison runs, experiments and viewer export")
    d.add_argument("--replicates", type=int, default=5)
    d.add_argument("--skip-experiments", action="store_true")
    d.set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="HTTP API and viewer")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)

    v = sub.add_parser("validate", help="all validation checks -> reports/validation.json")
    v.set_defaults(func=cmd_validate)

    x = sub.add_parser("export", help="viewer data for one run")
    x.add_argument("--incidents", default="both", choices=["none", "replay", "simulated", "both"])
    x.add_argument("--days", type=int, default=7)
    x.add_argument("--seed", type=int, default=1)
    x.set_defaults(func=cmd_export)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
