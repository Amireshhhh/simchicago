"""Service design: re-allocate bus frequencies and balance bus stops, then test the result in the
simulation (python -m simchi.service_design).

1. Frequency re-allocation (square-root rule). For bus route r with daily boardings Q_r (observed,
   CTA, last 12 months of weekdays), round-trip time C_r (scheduled, GTFS) and frequency f_r
   (round trips a day), riders arriving at random wait half a headway, so total daily waiting is
   proportional to sum_r Q_r / f_r, and the scheduled vehicle-hours are sum_r C_r f_r. Minimising
   sum_r Q_r / (2 f_r) subject to sum_r C_r f_r = B (a fixed budget) gives, with a Lagrange
   multiplier l: Q_r / (2 f_r^2) = l C_r, i.e.

        f_r* = sqrt(Q_r / (2 l C_r))  ∝  sqrt(Q_r / C_r)                       (square-root rule)

   (the objective is convex in f > 0 and the constraint linear, so this stationary point is the
   minimum). Practical bounds keep every route between 0.6x and 1.6x its current frequency
   (water-filling: clipped routes are fixed and the rest re-scaled until the budget holds).
   Tested with budgets of 100% (cost-neutral), 95% and 90% of today's bus vehicle-hours.
   Rail is not re-allocated: CTA publishes 'L' ridership by station, not by line.

2. Bus stop balancing on the ten busiest routes. Walking each pattern, a stop is kept if it is a
   terminal, a transfer point (served by another route, or within 150 m of an 'L' station), or at
   least STOP_SPACING_M (400 m, straight line) beyond the last kept stop; the others are no longer
   served. Each skipped stop saves STOP_SAVING_S (20 s: deceleration, dwell and re-entry; an
   assumption, not measured) of in-vehicle time; riders walk to the nearest served stop (the
   network model routes them). Vehicle-hours fall by the skipped stops x trips x 20 s.

Each design is simulated on 10 synthetic populations against today's schedule (as in
simchi/interventions.py) for transit trips, time savings, equity and job access.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from simchi import jsonutil
from simchi.paths import REPORTS
from simchi.transit.gtfs import load_extract

BOUNDS = (0.6, 1.6)
STOP_SPACING_M = 400.0
STOP_SAVING_S = 20.0
TRANSFER_M = 150.0


def route_table() -> pd.DataFrame:
    """Per bus route: weekday trips (both directions, GTFS service table), scheduled vehicle-hours and
    round trips (the kept patterns, as the cost proxy counts them), mean round-trip time (h),
    observed weekday boardings (last 12 months), mean scheduled headway (min, per direction, hours
    with service)."""
    from simchi.transit.ridership import load_observed
    routes = {r["id"]: r for r in load_extract("routes")}
    pats = [p for p in load_extract("patterns") if routes[p["route"]]["type"] == 3]
    # vehicle-hours and round trips as the cost proxy counts them (simchi.interventions.vehicle_hours):
    # trips x scheduled run time per pattern and time band, weekday
    vh, trips_p = {}, {}
    for p in pats:
        for band, n in p.get("trips_band", {}).get("weekday", {}).items():
            off = p["offsets_min"].get(band)
            if n and off is not None:
                vh[p["route"]] = vh.get(p["route"], 0.0) + n * off[-1] / 60.0
                trips_p[p["route"]] = trips_p.get(p["route"], 0.0) + n
    svc = pd.DataFrame(load_extract("service"))
    wk = svc[svc["day"] == "weekday"]
    trips = wk.groupby("route")["trips"].sum()
    headway = wk.assign(h=60.0 / wk["trips"]).groupby(["route", "direction"])["h"].mean().groupby("route").mean()
    df = load_observed("bus")
    last = df["date"].max()
    q = df[(df["date"] > last - pd.Timedelta(days=365)) & (df["daytype"] == "W")].groupby("id")["rides"].mean()
    rows = []
    for r in sorted(vh):
        if r not in q.index or r not in trips.index or trips_p.get(r, 0) <= 0:
            continue
        rows.append({"route": r, "name": routes[r]["long"], "weekday_trips": float(trips[r]), "boardings": float(q[r]),
                     "headway_min": float(headway[r]), "vehicle_hours": vh[r], "round_trips": trips_p[r] / 2.0})
    t = pd.DataFrame(rows).set_index("route")
    t["cycle_h"] = t["vehicle_hours"] / t["round_trips"]               # mean round-trip time, h
    t["boardings_per_trip"] = t["boardings"] / t["weekday_trips"]
    return t


def square_root_allocation(t: pd.DataFrame, budget_share: float = 1.0, bounds=BOUNDS) -> pd.Series:
    """Multipliers m_r = f_r*/f_r under the square-root rule with bounds, spending budget_share of
    today's vehicle-hours (water-filling over the clipped routes)."""
    f0, C, Q = t["round_trips"], t["cycle_h"], t["boardings"]
    B = budget_share * float((C * f0).sum())
    base = np.sqrt(Q / C)
    lo, hi = bounds
    fixed = pd.Series(np.nan, index=t.index)
    for _ in range(100):
        free = fixed.isna()
        spent = float((C * fixed.fillna(0)).sum())
        k = (B - spent) / float((C[free] * base[free]).sum())
        f = fixed.fillna(k * base)
        m = f / f0
        newly = free & ((m < lo) | (m > hi))
        if not newly.any():
            return m
        fixed[newly] = (m[newly].clip(lo, hi) * f0[newly])
    return fixed.fillna(k * base) / f0


def wait_change(t: pd.DataFrame, m: pd.Series) -> float:
    """Analytic change in boarding-weighted waiting, rider-hours per weekday (wait = headway / 2)."""
    return float((t["boardings"] * t["headway_min"] * (1.0 / m - 1.0) / 2.0).sum() / 60.0)


def balanced_stops(route_ids: list) -> dict:
    """route -> stop ids no longer served, by the rule in the module docstring."""
    stops = {s["id"]: (s["x"], s["z"], s.get("parent", "")) for s in load_extract("stops")}
    stations = np.array([[s["x"], s["z"]] for s in load_extract("stations")])
    serving = {}
    for p in load_extract("patterns"):
        for s in p["stops"]:
            serving.setdefault(s, set()).add(p["route"])
    out = {}
    for r in route_ids:
        removed_in, kept_in = set(), set()
        for p in load_extract("patterns"):
            if p["route"] != r:
                continue
            st = p["stops"]
            last = None
            for k, s in enumerate(st):
                x, z, _ = stops[s]
                transfer = len(serving.get(s, ())) > 1 or (len(stations) and np.hypot(*(stations - [x, z]).T).min() < TRANSFER_M)
                if k in (0, len(st) - 1) or transfer or last is None or np.hypot(x - last[0], z - last[1]) >= STOP_SPACING_M:
                    kept_in.add(s)
                    last = (x, z)
                else:
                    removed_in.add(s)
        out[r] = sorted(removed_in - kept_in)
    return out


def designs(t: pd.DataFrame, top: list) -> tuple[list, dict]:
    ivs, info = [], {}
    for share in (1.0, 0.95, 0.90):
        m = square_root_allocation(t, share)
        hm = {r: float(1.0 / v) for r, v in m.items() if abs(v - 1.0) > 1e-6}
        name = f"Re-allocate bus frequency (square-root rule), {int(round(share * 100))}% of today's bus vehicle-hours"
        ivs.append({"name": name, "network": {"headway_multiplier": hm}, "bands": ("early", "am_peak", "midday", "pm_peak", "evening", "night"),
                    "kind": "service", "provenance": "scheduled + observed demand; behaviour simulated"})
        info[name] = {"multipliers": m, "wait_change_rider_hours": wait_change(t, m), "budget_share": share}
    rm = balanced_stops(top)
    name = f"Bus stop balancing on the top-10 routes (>= {int(STOP_SPACING_M)} m spacing, {int(STOP_SAVING_S)} s per skipped stop)"
    ivs.append({"name": name, "network": {"removed_stops": rm, "stop_saving_s": STOP_SAVING_S}, "bands": ("early", "am_peak", "midday", "pm_peak", "evening", "night"),
                "kind": "priority", "provenance": "hypothesis (20 s per skipped stop; spacing rule)"})
    info[name] = {"removed_stops": {r: len(v) for r, v in rm.items()}}
    return ivs, info


def main(argv=None):
    from simchi.interventions import run, top_bus_routes
    argv = sys.argv[1:] if argv is None else argv
    R = int(argv[argv.index("--replicates") + 1]) if "--replicates" in argv else 10
    t = route_table()
    top = top_bus_routes()
    ivs, info = designs(t, top)
    res = run(R, ivs=ivs)
    m100 = info[ivs[0]["name"]]["multipliers"]
    rec = t.assign(multiplier=m100, proposed_trips=t["weekday_trips"] * m100).sort_values("multiplier")
    out = {"label": "simulated (behaviour), scheduled (cost), observed (demand)", "replicates": R,
           "method": __doc__.strip(), "results": res["interventions"],
           "analytic": {k: {kk: (vv.to_dict() if isinstance(vv, pd.Series) else vv) for kk, vv in v.items()} for k, v in info.items()},
           "route_recommendations": rec.reset_index()[["route", "name", "boardings", "weekday_trips", "proposed_trips", "multiplier",
                                                        "boardings_per_trip", "cycle_h", "headway_min"]].to_dict("records"),
           "low_income_population_share": res["low_income_population_share"]}
    d = REPORTS / "service_design"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "service_design.json", "w") as f:
        jsonutil.dump(out, f, indent=1)
    rec.to_csv(d / "route_recommendations.csv")
    for r in res["interventions"]:
        tt = r.get("transit_trips", {})
        print(f"{r['name'][:95]:95s} veh-h {r['vehicle_hours']:+9.1f}  trips {tt.get('mean', float('nan')):+10.0f} [{tt.get('ci_low', float('nan')):+.0f}, {tt.get('ci_high', float('nan')):+.0f}]  saved min {r.get('time_saved_min', {}).get('mean', float('nan')):+.0f}")


if __name__ == "__main__":
    main()
