"""Street-light outages and nighttime outdoor crime, W9 (python -m simchi.safety.lights).

Shared code for the explore lane (simchi/safety/lights_explore.py, 2018-2023) and the
pre-registered confirm test (below, once committed).

Units: a "block" is a W4 street segment (simchi/safety/sites.py; non-expressway street classes);
311 requests and crimes are snapped to the nearest segment within 50 m (intersection sites are not
used: both datasets are block-level). Outage request types (311 v6vf-nfxy sr_type values found in
2018-2023 by the explore lane): "Street Light Out Complaint", "Alley Light Out Complaint".
Indoor/outdoor: data/w9_location_map.csv (all 193 location_description values of 2018-2023;
values not in the file are "other" and unused). Night = 21:00-04:59, day = 10:00-15:59 Chicago
time (dark, respectively light, in every season).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from simchi.paths import DATA, MIRROR, REPORTS

OUTAGE_TYPES = ("Street Light Out Complaint", "Alley Light Out Complaint")
NIGHT_HOURS = tuple(list(range(21, 24)) + list(range(0, 5)))
DAY_HOURS = tuple(range(10, 16))
MAX_POST_DAYS = 30
W9 = MIRROR / "w9"
CHICAGO = "America/Chicago"


def location_map(path: Path = DATA / "w9_location_map.csv") -> dict:
    with open(path) as f:
        return {r["location_description"]: r["class"] for r in csv.DictReader(f)}


def snap_segments(sites, lon, lat) -> np.ndarray:
    """Nearest W4 segment (non-expressway) within 50 m, else None."""
    from shapely import points

    from simchi.safety.sites import SEGMENT_M
    from simchi.safety.mirror import _xy
    from simchi.data.cds import load_cds
    x, z = _xy(load_cds().frame, lon, lat)
    out = np.full(len(x), None, dtype=object)
    ok = np.isfinite(x)
    if ok.any():
        idx = np.nonzero(ok)[0]
        pi, si = sites._tree.query_nearest(points(np.column_stack([x[idx], z[idx]])), max_distance=SEGMENT_M, all_matches=False)
        out[idx[pi]] = sites.seg_ids[si]
    expr = set(sites.table.index[sites.table["expressway"].astype(bool)])
    return np.array([None if s in expr else s for s in out], dtype=object)


def outage_windows(req: pd.DataFrame) -> pd.DataFrame:
    """req: block, created_date, closed_date (completed requests). Overlapping or touching requests on
    a block merge into one window. Returns block, start, end (Chicago dates), requests."""
    r = req.dropna(subset=["block", "created_date", "closed_date"]).copy()
    r["start"] = pd.to_datetime(r["created_date"]).dt.normalize()
    r["end"] = pd.to_datetime(r["closed_date"]).dt.normalize()
    r = r[r["end"] >= r["start"]].sort_values(["block", "start"])
    rows = []
    for b, g in r.groupby("block"):
        cs, ce, n = None, None, 0
        for s, e in zip(g["start"], g["end"], strict=True):
            if cs is None or s > ce + pd.Timedelta(days=1):
                if cs is not None:
                    rows.append((b, cs, ce, n))
                cs, ce, n = s, e, 1
            else:
                ce, n = max(ce, e), n + 1
        rows.append((b, cs, ce, n))
    return pd.DataFrame(rows, columns=["block", "start", "end", "requests"])


def crime_aggregate(cr: pd.DataFrame, locmap: dict) -> pd.DataFrame:
    """cr: block, date (Chicago local), primary_type, location_description. Counts per block, date,
    hour, primary type and indoor/outdoor/other."""
    d = cr.dropna(subset=["block"]).copy()
    t = pd.to_datetime(d["date"])
    d["day"] = t.dt.strftime("%Y-%m-%d")
    d["hour"] = t.dt.hour
    d["place"] = d["location_description"].fillna("").map(lambda v: locmap.get(v, "other"))
    return d.groupby(["block", "day", "hour", "primary_type", "place"]).size().rename("n").reset_index()


def panel(windows: pd.DataFrame, agg: pd.DataFrame, max_post: int = MAX_POST_DAYS) -> pd.DataFrame:
    """Block x date x band rows: outdoor crimes at night (21-04 h) and in the day (10-15 h), for the
    days strictly inside each outage window (outage = 1) and the same number of days right after the
    repair, at most max_post (outage = 0). Days inside another window of the block are dropped."""
    rows = []
    by_block = {b: g for b, g in windows.groupby("block")}
    for b, g in by_block.items():
        inside = set()
        for s, e in zip(g["start"], g["end"], strict=True):
            inside.update(pd.date_range(s + pd.Timedelta(days=1), e - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        for s, e in zip(g["start"], g["end"], strict=True):
            during = pd.date_range(s + pd.Timedelta(days=1), e - pd.Timedelta(days=1))
            if len(during) == 0:
                continue
            after = pd.date_range(e + pd.Timedelta(days=1), periods=min(len(during), max_post))
            for days, o in ((during, 1), (after, 0)):
                for d in days.strftime("%Y-%m-%d"):
                    if o == 0 and d in inside:
                        continue
                    rows.append((b, d, o))
    P = pd.DataFrame(rows, columns=["block", "day", "outage"]).drop_duplicates(["block", "day"])
    out = agg[agg["place"] == "outdoor"]
    night = out[out["hour"].isin(NIGHT_HOURS)].groupby(["block", "day"])["n"].sum()
    dayc = out[out["hour"].isin(DAY_HOURS)].groupby(["block", "day"])["n"].sum()
    k = list(zip(P["block"], P["day"], strict=True))
    n1 = pd.DataFrame({"block": P["block"], "day": P["day"], "outage": P["outage"], "night": 1, "y": [night.get(x, 0) for x in k]})
    n0 = pd.DataFrame({"block": P["block"], "day": P["day"], "outage": P["outage"], "night": 0, "y": [dayc.get(x, 0) for x in k]})
    Q = pd.concat([n1, n0], ignore_index=True)
    Q["week"] = pd.to_datetime(Q["day"]).dt.strftime("%G-%V")
    return Q


def twoway_demean(M: np.ndarray, a: np.ndarray, b: np.ndarray, tol: float = 1e-10, iters: int = 500) -> np.ndarray:
    """Remove block (a) and week (b) fixed effects from each column of M by alternating projections."""
    M = M.astype(float).copy()
    for _ in range(iters):
        prev = M.copy()
        for g in (a, b):
            sums = np.zeros((g.max() + 1, M.shape[1]))
            np.add.at(sums, g, M)
            cnt = np.bincount(g, minlength=g.max() + 1)[:, None]
            M -= (sums / np.maximum(cnt, 1))[g]
        if np.max(np.abs(M - prev)) < tol:
            break
    return M


def did(Q: pd.DataFrame) -> dict:
    """y = b1 night x outage + b2 outage + b3 night + block FE + week FE; errors clustered by block."""
    a = pd.factorize(Q["block"])[0]
    b = pd.factorize(Q["week"])[0]
    X = np.column_stack([Q["night"] * Q["outage"], Q["outage"], Q["night"]]).astype(float)
    Z = twoway_demean(np.column_stack([Q["y"].to_numpy(float), X]), a, b)
    y, Xd = Z[:, 0], Z[:, 1:]
    XtX_inv = np.linalg.pinv(Xd.T @ Xd)
    beta = XtX_inv @ Xd.T @ y
    e = y - Xd @ beta
    G = a.max() + 1
    S = np.zeros((G, Xd.shape[1]))
    np.add.at(S, a, Xd * e[:, None])
    n, k = len(y), Xd.shape[1] + G + (b.max() + 1) - 1
    c = G / (G - 1) * (n - 1) / max(n - k, 1)
    V = c * XtX_inv @ (S.T @ S) @ XtX_inv
    se = np.sqrt(np.clip(np.diag(V), 0, None))
    q = student_t.ppf(0.975, G - 1)
    names = ["night_x_outage", "outage", "night"]
    return {"coef": dict(zip(names, map(float, beta))), "se": dict(zip(names, map(float, se))),
            "ci95_night_x_outage": [float(beta[0] - q * se[0]), float(beta[0] + q * se[0])],
            "blocks": int(G), "weeks": int(b.max() + 1), "rows": int(n),
            "mean_y": {"night_outage": float(Q[(Q.night == 1) & (Q.outage == 1)]["y"].mean()), "night_after": float(Q[(Q.night == 1) & (Q.outage == 0)]["y"].mean()),
                       "day_outage": float(Q[(Q.night == 0) & (Q.outage == 1)]["y"].mean()), "day_after": float(Q[(Q.night == 0) & (Q.outage == 0)]["y"].mean())}}


# ----------------------------------------------------------------------------- confirm lane
CONFIRM_WINDOW = ("2024-01-01", "2026-10-31")


def run_confirm() -> dict:
    """Pre-registered W9 test: reads only through the confirm lane (simchi.lanes)."""
    import hashlib

    from simchi.lanes import Lane
    from simchi.portal.client import Portal
    from simchi.safety.lights_explore import build_mirror, monthly
    portal, lane = Portal(), Lane("confirm", "simchi.safety.lights")
    a, b = CONFIRM_WINDOW
    types = ", ".join(f"'{t}'" for t in OUTAGE_TYPES)
    req = lane.read("v6vf-nfxy", "created_date", a, b, lambda s, e: monthly(portal, "v6vf-nfxy", "created_date", s, e,
                    "sr_type, status, created_date, closed_date, latitude, longitude", f"sr_type in ({types})"))
    cr = lane.read("ijzp-q8t2", "date", a, b, lambda s, e: monthly(portal, "ijzp-q8t2", "date", s, e,
                   "date, latitude, longitude, primary_type, location_description", None))
    late = pd.to_datetime(req["closed_date"], errors="coerce") > pd.Timestamp(b) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    req = req[~late]                                      # closed after the window: information from beyond it
    W, A, summ = build_mirror(req, cr, "confirm")
    summ["requests_closed_after_window_dropped"] = int(late.sum())
    # outage windows must end by the window's end so the after-repair days are inside it
    W = W[pd.to_datetime(W["end"]) <= pd.Timestamp(b) - pd.Timedelta(days=1)]
    W = W.assign(start=pd.to_datetime(W["start"]), end=pd.to_datetime(W["end"]))
    Q = panel(W, A)
    Q = Q[Q["day"] <= b]
    res = did(Q)
    res["pass"] = bool(res["coef"]["night_x_outage"] > 0 and res["ci95_night_x_outage"][0] > 0)
    files = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(W9.glob("confirm_*.csv.gz"))}
    out = {"design": "W9 pre-registration, docstring of simchi/safety/lights.py", "window": CONFIRM_WINDOW, "mirror": summ,
           "mirror_sha256": files, "windows_used": int(len(W)), **res}
    (REPORTS / "safety").mkdir(parents=True, exist_ok=True)
    (REPORTS / "safety" / "lights.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def main(argv=None):
    out = run_confirm()
    print(json.dumps({k: out[k] for k in ("coef", "ci95_night_x_outage", "blocks", "rows", "pass", "mean_y")}, indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1:])
