"""Operations view of a published live snapshot (run in live.yml after polling):

    python -m simchi.ops.live_ops --snapshot live/latest.json --out live/ops.json

Writes holding advice (simchi.ops.holding.live_recommendations) and anomaly flags
(simchi.ops.anomalies.detect) for the snapshot's observed positions. Advisory and labelled:
the holding rule failed its simulated evaluation (docs/EVALUATION.md), the anomaly detectors were
evaluated on constructed labels only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def live_anomalies(snapshot: dict) -> dict:
    from simchi.data.cds import load_cds
    from simchi.ops.anomalies import detect, route_shapes
    from simchi.transit.reliability import CHICAGO, Schedule, positions
    rows = []
    for v in snapshot.get("vehicles", []):
        for t_poll, x, z in v.get("track", []):
            rows.append({"poll_utc": t_poll, "mode": v["mode"], "id": v["id"], "route": v["route"], "x": x, "z": z,
                         "dly": v.get("dly", False), "pid": "", "train_dir": ""})
    if not rows:
        return {"jump": [], "stuck": [], "off_route": [], "outage": []}
    frame = load_cds().frame
    df = pd.DataFrame(rows)
    df["lon"], df["lat"] = frame.to_lonlat(df["x"].to_numpy(), df["z"].to_numpy())
    df["run"] = "snapshot"
    df["poll"] = pd.to_datetime(df["poll_utc"], utc=True)
    loc = df["poll"].dt.tz_convert(CHICAGO)
    df["hour"] = loc.dt.hour
    df["day"] = np.where(loc.dt.weekday < 5, "weekday", np.where(loc.dt.weekday == 5, "saturday", "sunday"))
    sched = Schedule()
    P = positions(df, sched, frame)
    feed = P.assign(poll=(P["poll"] - P["poll"].min()).dt.total_seconds())[["poll", "id", "route", "direction", "x", "z"]]
    hour, day = int(df["hour"].iloc[-1]), df["day"].iloc[-1]
    routes_seen = set(df["route"])
    scheduled = {}
    for (r, d) in sched.rep:
        if r in routes_seen:
            n = sched.in_service(r, d, day, hour)
            if np.isfinite(n):
                scheduled[(r, d)] = n
    flags = detect(feed, route_shapes(), scheduled)
    return {k: sorted([list(x) if isinstance(x, tuple) else x for x in v], key=str) for k, v in flags.items()}


def build(snapshot: dict) -> dict:
    from simchi.ops.holding import live_recommendations
    return {"schema": "simchi.ops/1", "generated_from": snapshot.get("generated_utc"),
            "holding": {"label": "advisory; the rule failed its simulated evaluation", "advice": live_recommendations(snapshot)},
            "anomalies": {"label": "rule-based flags; evaluated on constructed labels only", **live_anomalies(snapshot)}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    snap = json.loads(Path(a.snapshot).read_text())
    from simchi import jsonutil
    out = build(snap)
    with open(a.out, "w") as f:
        jsonutil.dump(out, f, separators=(",", ":"))
    print("holding advice:", len(out["holding"]["advice"]), "anomalies:", {k: len(v) for k, v in out["anomalies"].items() if isinstance(v, list)})


if __name__ == "__main__":
    main()
