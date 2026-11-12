"""Live-feed anomaly detection with constructed labels (python -m simchi.ops.anomalies).

Detectors (thresholds fixed from physical reasoning before any evaluation; no tuning):
  jump      implied speed between consecutive polls of a vehicle > 35 m/s (126 km/h)
  stuck     moved < 10 m over 3 polls (120 s) while more than 300 m from either end of its
            route shape (layovers at terminals are normal)
  off_route farther than 300 m from every shape of its route
  outage    a route-direction with no vehicle at a poll while >= 3 are scheduled in service
            (Little's law, as in the reliability report)

PRE-REGISTERED EVALUATION (constructed labels): a base feed is made of clean polls (3 polls
60 s apart): vehicles placed along each route-direction's representative shape at the scheduled
number in service, moving at the scheduled speed (shape length / run time) with GPS noise
(sd 15 m), plus 5% of vehicles in a layover at a terminal (stationary, a hard negative).
Anomalies are then injected into a random 2% of vehicles each (jump: one poll moved 2-5 km;
stuck: frozen in place mid-route; off_route: all polls moved 500-1500 m sideways) and into 3% of
route-directions (outage: all vehicles removed). Precision and recall per type over 20 seeds
(weekday 8 am service). When polled history exists, the same injection is run on real polls;
anything the detectors flag in the real base that was not injected counts as a false positive.
The base feed here is SIMULATED; the labels are constructed, not observed incidents.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from simchi.transit.interp import cumulative, point_at, project

JUMP_MS = 35.0
STUCK_M = 10.0
END_M = 300.0
OFF_M = 300.0
OUTAGE_MIN_SCHED = 3.0
POLLS_S = (0.0, 60.0, 120.0)


def route_shapes():
    from simchi.transit.gtfs import load_extract
    shapes = load_extract("shapes")
    by = {}
    for p in load_extract("patterns"):
        by.setdefault(p["route"], set()).add(p["shape"])
    return {r: [np.asarray(shapes[s], float) for s in ss] for r, ss in by.items()}


def _dist_to_shapes(xy, shapes):
    best = np.inf
    for sh in shapes:
        a, b = sh[:-1], sh[1:]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(1), 1e-9)
        t = np.clip(((xy - a) * ab).sum(1) / L2, 0, 1)
        d = np.hypot(*(a + t[:, None] * ab - xy).T).min()
        best = min(best, d)
    return best


def detect(feed: pd.DataFrame, shapes: dict, scheduled: dict) -> dict:
    """feed: rows (poll, id, route, direction, x, z). Returns flagged vehicle ids per type and
    flagged (route, direction) outages."""
    out = {"jump": set(), "stuck": set(), "off_route": set(), "outage": set()}
    for vid, g in feed.sort_values("poll").groupby("id"):
        xy = g[["x", "z"]].to_numpy(float)
        t = g["poll"].to_numpy(float)
        route = g["route"].iat[0]
        if len(g) > 1:
            v = np.hypot(*np.diff(xy, axis=0).T) / np.maximum(np.diff(t), 1e-9)
            if (v > JUMP_MS).any():
                out["jump"].add(vid)
            if len(g) >= 3 and np.hypot(*(xy - xy[0]).T).max() < STUCK_M:
                ends = []
                for sh in shapes.get(route, []):
                    cum = cumulative(sh)
                    s_, _ = project(sh, cum, tuple(xy[0]))
                    ends.append(min(s_, cum[-1] - s_))
                if ends and min(ends) > END_M:
                    out["stuck"].add(vid)
        med = np.median(xy, axis=0)
        if _dist_to_shapes(med[None, :], shapes.get(route, [])) > OFF_M:
            out["off_route"].add(vid)
    seen = feed.groupby(["route", "direction", "poll"]).size()
    for (route, d), n_sched in scheduled.items():
        if n_sched >= OUTAGE_MIN_SCHED:
            for p in feed["poll"].unique():
                if (route, d, p) not in seen.index:
                    out["outage"].add((route, d))
                    break
    return out


def synthetic_feed(seed: int, day="weekday", hour=8):
    """Clean simulated polls of all routes at the scheduled level, with layovers (labelled simulated)."""
    from simchi.transit.reliability import Schedule
    rng = np.random.default_rng(seed)
    sched = Schedule()
    rows, scheduled, layover = [], {}, set()
    for (route, d), (shape, cum) in sched.rep.items():
        L = sched.in_service(route, d, day, hour)
        if not np.isfinite(L) or L <= 0:
            continue
        scheduled[(route, d)] = L
        n = rng.poisson(L)
        rt = None
        for band in ("am_peak", "midday", "pm_peak"):
            rt = sched.runtime[(route, d)].get(band) or rt
        if not rt or n == 0:
            continue
        v = cum[-1] / (rt * 60.0)
        for i in range(n):
            vid = f"{route}:{d}:{i}"
            lay = rng.uniform() < 0.05
            s0 = (0.0 if rng.uniform() < 0.5 else cum[-1]) if lay else rng.uniform(0, cum[-1] - v * 130)
            if lay:
                layover.add(vid)
            for t in POLLS_S:
                s = s0 if lay else s0 + v * t
                x, z = point_at(shape, cum, s)
                rows.append({"poll": t, "id": vid, "route": route, "direction": d,
                             "x": x + rng.normal(0, 15), "z": z + rng.normal(0, 15)})
    return pd.DataFrame(rows), scheduled, layover


def inject(feed: pd.DataFrame, scheduled: dict, seed: int, rate=0.02, outage_rate=0.03):
    rng = np.random.default_rng(10_000 + seed)
    feed = feed.copy()
    ids = feed["id"].unique()
    labels = {"jump": set(), "stuck": set(), "off_route": set(), "outage": set()}
    pick = rng.permutation(ids)
    k = int(round(rate * len(ids)))
    for name, chosen in zip(("jump", "stuck", "off_route"), (pick[:k], pick[k:2 * k], pick[2 * k:3 * k]), strict=True):
        for vid in chosen:
            m = feed["id"] == vid
            idx = np.flatnonzero(m)
            if name == "jump":
                j = idx[rng.integers(len(idx))]
                ang, dist = rng.uniform(0, 2 * np.pi), rng.uniform(2000, 5000)
                feed.loc[feed.index[j], ["x", "z"]] += [dist * np.cos(ang), dist * np.sin(ang)]
            elif name == "stuck":
                feed.loc[m, ["x", "z"]] = feed.loc[feed.index[idx[0]], ["x", "z"]].to_numpy(float)
            else:
                ang, dist = rng.uniform(0, 2 * np.pi), rng.uniform(500, 1500)
                feed.loc[m, ["x", "z"]] += [dist * np.cos(ang), dist * np.sin(ang)]
            labels[name].add(vid)
    rds = [rd for rd, n in scheduled.items() if n >= OUTAGE_MIN_SCHED]
    for j in rng.permutation(len(rds))[:int(round(outage_rate * len(rds)))]:
        r, d = rds[j]
        feed = feed[~((feed["route"] == r) & (feed["direction"] == d))]
        labels["outage"].add((r, d))
    present = set(feed["id"])
    for k in ("jump", "stuck", "off_route"):                 # vehicles removed by an outage cannot be detected
        labels[k] &= present
    return feed, labels


def score(flags: dict, labels: dict) -> dict:
    out = {}
    for k in labels:
        tp = len(flags[k] & labels[k])
        fp = len(flags[k] - labels[k])
        fn = len(labels[k] - flags[k])
        out[k] = {"tp": tp, "fp": fp, "fn": fn}
    return out


def evaluate(seeds=range(1, 21)) -> dict:
    shapes = route_shapes()
    tot = {}
    per_seed = []
    for sd in seeds:
        base, scheduled, layover = synthetic_feed(sd)
        feed, labels = inject(base, scheduled, sd)
        # stuck-injected vehicles that were already in a layover are not anomalies
        labels["stuck"] -= layover
        sc = score(detect(feed, shapes, scheduled), labels)
        per_seed.append(sc)
        for k, v in sc.items():
            for m in v:
                tot.setdefault(k, {"tp": 0, "fp": 0, "fn": 0})[m] += v[m]
    res = {"label": "simulated base feed, constructed labels", "seeds": len(per_seed), "detectors": {}}
    for k, v in tot.items():
        p = v["tp"] / (v["tp"] + v["fp"]) if v["tp"] + v["fp"] else float("nan")
        r = v["tp"] / (v["tp"] + v["fn"]) if v["tp"] + v["fn"] else float("nan")
        res["detectors"][k] = {**v, "precision": p, "recall": r}
    return res


def main():
    from simchi import jsonutil
    from simchi.paths import REPORTS
    r = evaluate()
    (REPORTS / "ops").mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "ops" / "anomalies.json", "w") as f:
        jsonutil.dump(r, f, indent=1)
    for k, v in r["detectors"].items():
        print(k, v)


if __name__ == "__main__":
    main()
