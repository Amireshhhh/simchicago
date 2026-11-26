"""Seconds saved per skipped bus stop, measured from the polling archive
(python -m simchi.transit.stop_time). Replaces the assumed 20 s in simchi/service_design.py.

PRE-REGISTERED DESIGN, W3 (committed as "W3 pre-registration" before any archive data were used
for it)

Positions are about 60 s apart, too coarse to time individual stops, so the cost of a stop is
estimated cross-sectionally from segment run times.

SEGMENTS
  Each bus route-direction's representative GTFS shape (simchi.transit.reliability.Schedule) is cut
  into consecutive 400 m segments from its start; a final piece under 200 m is dropped, and so are
  the first and last segment of every shape (terminals, layovers).
  stops     the representative pattern's stops whose projection on the shape falls in the segment
  signals   OpenStreetMap highway=traffic_signals nodes within 20 m of the shape, projected on it,
            falling in the segment (fetched by the W3 job through Overpass; the file's sha256 and
            OSM base timestamp are recorded in the report, the file kept as a release asset)
  length    the segment's length along the shape (m)

RUN TIMES
  For each vehicle in each run, positions along its direction's shape (the archive's direction
  inference) are ordered by time; the time it crosses a point is interpolated linearly between the
  two consecutive observations that bracket it (at most 120 s apart, moving forward). A segment
  traversal is kept when both its start and end crossings are interpolated within the same run;
  run time = end - start, kept if 20 s <= run time <= 1200 s. Hour = Chicago hour of the start.

MODEL
  run_time = b_len x length + b_stop x stops + b_sig x signals + hour fixed effects
             + route fixed effects + error,
  ordinary least squares over all kept traversals; standard errors clustered by route (CR1: the
  G/(G-1) x (n-1)/(n-k) small-sample factor); the 95% interval for b_stop is
  b_stop +- t(G-1, 0.975) x SE, G = number of routes. Reported: b_stop with its interval, b_len,
  b_sig, n traversals, G.
  Minimum data: archive (W2) spanning >= 28 days and >= 30 routes with kept traversals; otherwise
  the report states "insufficient data" and nothing is estimated.

STOP BALANCING RERUN (pass rule fixed now)
  simchi/service_design.py's stop balancing is rerun with stop_saving_s equal to the lower end,
  the estimate and the upper end of the b_stop interval (same 10 synthetic populations, same
  spacing rule). Pass only if the lower end is > 0 and the simulated change in weekday transit trips
  at the lower end has a 95% interval entirely above 0. Otherwise the finding is reported as failed.
"""

from __future__ import annotations  # noqa: E402  (after the pre-registration docstring)

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from simchi.paths import REPORTS
from simchi.transit.interp import cumulative, project

SEG_M, MIN_LAST_M, SIGNAL_M = 400.0, 200.0, 20.0
MAX_GAP_S = 120.0
RUN_RANGE_S = (20.0, 1200.0)
MIN_DAYS, MIN_ROUTES = 28, 30


def representative_shapes() -> dict:
    """(route, direction) -> (shape, stop ids) of each bus route-direction's pattern with most weekday trips."""
    from simchi.transit.gtfs import load_extract
    routes = {r["id"]: r for r in load_extract("routes")}
    shapes_all = load_extract("shapes")
    rep = {}
    for p in load_extract("patterns"):
        if routes[p["route"]]["type"] != 3:
            continue
        k = (p["route"], p["direction"])
        if k not in rep or p["trips_weekday"] > rep[k]["trips_weekday"]:
            rep[k] = p
    return {k: (shapes_all[p["shape"]], p["stops"]) for k, p in rep.items()}


# ----------------------------------------------------------------------------- segments
def cut_segments(cum_len: float) -> list:
    """[(start, end)] 400 m pieces; a last piece under 200 m dropped; first and last dropped."""
    edges = list(np.arange(0.0, cum_len, SEG_M)) + [cum_len]
    segs = [(a, b) for a, b in zip(edges[:-1], edges[1:], strict=True)]
    if segs and segs[-1][1] - segs[-1][0] < MIN_LAST_M:
        segs = segs[:-1]
    return segs[1:-1]


def segments(shapes: dict, stop_xy: dict, signals_xy: np.ndarray) -> pd.DataFrame:
    """shapes: (route, direction) -> (shape array, its representative pattern's stop ids)."""
    rows = []
    for (route, d), (sh, stop_ids) in shapes.items():
        sh = np.asarray(sh, float)
        cum = cumulative(sh)
        st = np.array([project(sh, cum, stop_xy[s])[0] for s in stop_ids if s in stop_xy])
        sig = []
        for p in signals_xy:
            s_, off = project(sh, cum, p)
            if off <= SIGNAL_M:
                sig.append(s_)
        sig = np.array(sig)
        for j, (a, b) in enumerate(cut_segments(float(cum[-1]))):
            rows.append({"route": route, "direction": d, "seg": j, "s0": a, "s1": b, "length": b - a,
                         "stops": int(((st > a) & (st <= b)).sum()) if len(st) else 0,
                         "signals": int(((sig > a) & (sig <= b)).sum()) if len(sig) else 0})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- traversals
def crossings(obs: pd.DataFrame, bounds: np.ndarray) -> list:
    """obs: one vehicle-run's rows with t (s) and s (m), ordered by t. Returns [(boundary index,
    crossing time)] interpolated between consecutive forward observations <= 120 s apart."""
    out = []
    t, s = obs["t"].to_numpy(float), obs["s"].to_numpy(float)
    for k in range(len(t) - 1):
        dt, ds = t[k + 1] - t[k], s[k + 1] - s[k]
        if not (0 < dt <= MAX_GAP_S) or ds <= 0:
            continue
        for i in np.nonzero((bounds > s[k]) & (bounds <= s[k + 1]))[0]:
            out.append((int(i), t[k] + (bounds[i] - s[k]) / ds * dt))
    return out


def traversals(P: pd.DataFrame, segs: pd.DataFrame, shapes: dict) -> pd.DataFrame:
    """P: rows with route, direction, run, id, poll (UTC), hour, x, z (bus only). Projects each row
    on its own direction's shape and returns segment run times."""
    rows = []
    for (route, d), g in P.groupby(["route", "direction"]):
        if (route, d) not in shapes:
            continue
        sg = segs[(segs["route"] == route) & (segs["direction"] == d)].sort_values("seg")
        if sg.empty:
            continue
        sh = np.asarray(shapes[(route, d)][0], float)
        cum = cumulative(sh)
        g = g.assign(s=[project(sh, cum, (x, z))[0] for x, z in zip(g["x"], g["z"], strict=True)],
                     t=(pd.to_datetime(g["poll"], utc=True) - pd.Timestamp("2020-01-01", tz="UTC")).dt.total_seconds())
        starts, ends = sg["s0"].to_numpy(), sg["s1"].to_numpy()
        bounds = np.concatenate([starts, ends[-1:]])        # segments are contiguous
        for (_run, _vid), v in g.sort_values("t").groupby(["run", "id"]):
            cr = dict(crossings(v, bounds))
            for j, srow in enumerate(sg.itertuples()):
                if j in cr and (j + 1) in cr:
                    rt = cr[j + 1] - cr[j]
                    if RUN_RANGE_S[0] <= rt <= RUN_RANGE_S[1]:
                        h = int(v["hour"].iloc[np.searchsorted(v["t"].to_numpy(), cr[j]).clip(0, len(v) - 1)])
                        rows.append({"route": route, "direction": d, "seg": srow.seg, "run_time_s": rt, "length": srow.length,
                                     "stops": srow.stops, "signals": srow.signals, "hour": h})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- model
def fit(T: pd.DataFrame) -> dict:
    """OLS with route and hour fixed effects, CR1 standard errors clustered by route."""
    routes = sorted(T["route"].unique())
    hours = sorted(T["hour"].unique())
    X = [T["length"].to_numpy(float), T["stops"].to_numpy(float), T["signals"].to_numpy(float)]
    names = ["length_m", "stops", "signals"]
    for r in routes:
        X.append((T["route"] == r).to_numpy(float))
        names.append(f"route:{r}")
    for h in hours[1:]:
        X.append((T["hour"] == h).to_numpy(float))
        names.append(f"hour:{h}")
    X = np.column_stack(X)
    keep = X.any(axis=0)
    X, names = X[:, keep], [n for n, k in zip(names, keep, strict=True) if k]
    y = T["run_time_s"].to_numpy(float)
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    n, k = X.shape
    G = len(routes)
    meat = np.zeros((k, k))
    for r in routes:
        m = (T["route"] == r).to_numpy()
        u = X[m].T @ e[m]
        meat += np.outer(u, u)
    c = G / (G - 1) * (n - 1) / (n - k) if G > 1 and n > k else np.nan
    V = c * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.clip(np.diag(V), 0, None))
    q = student_t.ppf(0.975, G - 1) if G > 1 else np.nan
    i = names.index("stops")
    return {"seconds_per_stop": float(beta[i]), "se": float(se[i]), "ci95": [float(beta[i] - q * se[i]), float(beta[i] + q * se[i])],
            "seconds_per_m": float(beta[names.index("length_m")]), "seconds_per_signal": float(beta[names.index("signals")]) if "signals" in names else None,
            "n_traversals": int(n), "routes": int(G), "t_quantile": float(q)}


def stop_balancing_rule(ci_low: float, trips_ci_low_at_ci_low: float | None) -> dict:
    """The pre-registered pass rule for the rerun."""
    if not (ci_low > 0):
        return {"pass": False, "reason": "the interval's lower end is not above 0 s: no time saving is supported"}
    if trips_ci_low_at_ci_low is None or not (trips_ci_low_at_ci_low > 0):
        return {"pass": False, "reason": "at the interval's lower end the simulated trip change's 95% interval is not above 0"}
    return {"pass": True, "reason": "lower end > 0 and its simulated trip gain's 95% interval is above 0"}


def estimate_from_traversals(T: pd.DataFrame, segs: pd.DataFrame) -> pd.DataFrame:
    """Join daily traversal rows (route, direction, seg, hour, run_time_s) with segment attributes."""
    keys = ["route", "direction", "seg"]
    return T.merge(segs[keys + ["length", "stops", "signals"]], on=keys, how="inner")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--traversals", required=True, help="directory with traversals-<date>.csv.gz archive files (W2)")
    ap.add_argument("--signals", required=True, help="Overpass JSON of highway=traffic_signals nodes")
    ap.add_argument("--replicates", type=int, default=10)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    import hashlib

    from simchi.data.cds import load_cds
    from simchi.transit.gtfs import load_extract
    files = sorted(Path(a.traversals).glob("traversals-*.csv.gz"))
    days = [f.name[11:21] for f in files]
    span = (pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days + 1 if days else 0
    raw_sig = Path(a.signals).read_bytes()
    sig_json = json.loads(raw_sig)
    out = {"design": "W3 pre-registration, docstring of simchi/transit/stop_time.py", "archive_days": len(days), "span_days": span,
           "signals": {"file_sha256": hashlib.sha256(raw_sig).hexdigest(), "osm_base": sig_json.get("osm3s", {}).get("timestamp_osm_base"),
                       "nodes": len(sig_json.get("elements", [])), "license": "OpenStreetMap contributors, ODbL 1.0"}}
    if span < MIN_DAYS:
        out.update({"status": "insufficient data", "reason": f"archive spans {span} of {MIN_DAYS} days"})
    else:
        frame = load_cds().frame
        shapes = representative_shapes()
        stop_xy = {s["id"]: (s["x"], s["z"]) for s in load_extract("stops")}
        el = sig_json.get("elements", [])
        if el:
            sx, sz = frame.from_lonlat(np.array([e["lon"] for e in el], float), np.array([e["lat"] for e in el], float))
            sig_xy = np.column_stack([sx, sz])
        else:
            sig_xy = np.zeros((0, 2))
        segs = segments(shapes, stop_xy, sig_xy)
        T = pd.concat([pd.read_csv(f, dtype={"route": str}) for f in files], ignore_index=True)
        T = estimate_from_traversals(T, segs)
        out["segments"] = {"n": int(len(segs)), "stops": int(segs["stops"].sum()), "signals": int(segs["signals"].sum())}
        if T.empty or T["route"].nunique() < MIN_ROUTES:
            out.update({"status": "insufficient data", "reason": f"{0 if T.empty else T['route'].nunique()} of {MIN_ROUTES} routes with traversals"})
        else:
            est = fit(T)
            out["estimate"] = est
            from simchi.service_design import stop_balancing_rerun
            runs = stop_balancing_rerun([est["ci95"][0], est["seconds_per_stop"], est["ci95"][1]], a.replicates)
            out["stop_balancing"] = runs
            lo = runs[0]["transit_trips"]["ci_low"] if runs and runs[0].get("transit_trips") else None
            out["rule"] = stop_balancing_rule(est["ci95"][0], lo)
            out["status"] = "pass" if out["rule"]["pass"] else "fail"
    (REPORTS / "service_design").mkdir(parents=True, exist_ok=True)
    (REPORTS / "service_design" / "stop_time.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: out.get(k) for k in ("status", "reason", "estimate", "rule")}, indent=1, default=float))


if __name__ == "__main__":
    main()
