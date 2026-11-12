"""Crowding forecast: next-week daily ridership per bus route and 'L' station (python -m simchi.ops.crowding).

Crowding index = forecast daily rides / scheduled daily vehicle trips (GTFS) of the route or the
station's trains; the forecast is the hard part, and it is what is validated.

PRE-REGISTERED DESIGN (written before any evaluation of this forecast was run):
  Data      cta_bus_route_daily, cta_l_station_daily (observed daily totals), all day types
  Target    rides on day d, forecast on day d - 7 (one week ahead), using data up to d - 7
  Baseline  B_naive: rides on d - 7 (same weekday last week), or, if d's day type differs from
            d - 7's (holidays), the most recent day with d's day type
  Model     M_med4: median of the last 4 days with d's day type (W weekday / A Saturday /
            U Sunday-holiday) and, for W, the same weekday, all on or before d - 7; day types are
            known in advance (holiday calendar). If fewer than 2 such days exist: B_naive.
  Test      every day 2026-01-01 .. 2026-08-31, every unit with data that day and a forecast
  Metric    mean absolute error of log(1 + rides) (MALE); also MAE in rides
  Criterion M_med4 MALE < B_naive MALE, separately for bus routes and 'L' stations
"""

from __future__ import annotations


import numpy as np
import pandas as pd

from simchi.paths import REPORTS
from simchi.transit.ridership import load_observed

TEST = ("2026-01-01", "2026-08-31")


def forecasts(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """One row per (unit, target day in [start, end]) with observed rides, B_naive and M_med4."""
    df = df[["id", "date", "daytype", "rides"]].sort_values(["id", "date"])
    out = []
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    for uid, g in df.groupby("id", sort=False):
        g = g.set_index("date")
        rides, dtype = g["rides"], g["daytype"]
        for d in g.index[(g.index >= t0) & (g.index <= t1)]:
            cut = d - pd.Timedelta(days=7)
            hist = g.loc[:cut]
            if hist.empty:
                continue
            dt = dtype.at[d]
            same_type = hist[hist["daytype"] == dt]
            if dt == "W":
                same_type = same_type[same_type.index.weekday == d.weekday()]
            if cut in rides.index and dtype.at[cut] == dt:
                naive = rides.at[cut]
            elif len(same_type):
                naive = same_type["rides"].iat[-1]
            else:
                continue
            last4 = same_type["rides"].iloc[-4:]
            med = float(np.median(last4)) if len(last4) >= 2 else naive
            out.append((uid, d, dt, rides.at[d], naive, med))
    return pd.DataFrame(out, columns=["id", "date", "daytype", "rides", "B_naive", "M_med4"])


def evaluate(F: pd.DataFrame) -> dict:
    y = np.log1p(F["rides"].to_numpy(float))
    res = {"forecasts": int(len(F)), "units": int(F["id"].nunique())}
    for k in ("B_naive", "M_med4"):
        p = F[k].to_numpy(float)
        res[k] = {"male": float(np.abs(y - np.log1p(p)).mean()), "mae_rides": float(np.abs(F["rides"] - p).mean())}
    res["pass"] = bool(res["M_med4"]["male"] < res["B_naive"]["male"])
    # by day type, for transparency
    res["by_daytype"] = {dt: {k: float(np.abs(np.log1p(g["rides"]) - np.log1p(g[k])).mean()) for k in ("B_naive", "M_med4")}
                         for dt, g in F.groupby("daytype")}
    return res


DAY = {"W": "weekday", "A": "saturday", "U": "sunday"}


def service_by_daytype(graph, kind: str) -> dict:
    """Scheduled daily vehicle trips per bus route, or train departures per 'L' station (parent),
    for each GTFS reference day type."""
    from simchi.transit.ridership import _parent
    out = {d: {} for d in DAY.values()}
    for i, p in enumerate(graph.pats):
        rail = bool(graph.pat_rail[i])
        if rail != (kind == "rail"):
            continue
        for d in DAY.values():
            n = sum(p.get("trips_band", {}).get(d, {}).values())
            keys = {_parent(graph, s) for s in p["stops"][:-1]} if rail else {p["route"]}
            for k in keys:
                out[d][k] = out[d].get(k, 0) + n
    return out


def next_week(df: pd.DataFrame, service: dict, asof: str | None = None) -> pd.DataFrame:
    """M_med4 forecasts for the 7 days after the last date in the data, with the crowding index
    (forecast rides per scheduled vehicle trip, or per scheduled train departure at a station,
    for that day type; Sunday service stands for holidays)."""
    last = pd.Timestamp(asof) if asof else df["date"].max()
    rows = []
    for d in pd.date_range(last + pd.Timedelta(days=1), periods=7):
        dt = "U" if d.weekday() == 6 else "A" if d.weekday() == 5 else "W"      # holidays not flagged here
        for uid, g in df[df["date"] <= last].groupby("id"):
            h = g[g["daytype"] == dt]
            if dt == "W":
                h = h[h["date"].dt.weekday == d.weekday()]
            if len(h) < 2:
                continue
            f = float(np.median(h["rides"].iloc[-4:]))
            trips = service[DAY[dt]].get(uid, np.nan)
            rows.append({"id": uid, "date": d.date().isoformat(), "daytype": dt, "forecast_rides": f,
                         "scheduled_trips": trips, "rides_per_trip": f / trips if trips and np.isfinite(trips) else None})
    return pd.DataFrame(rows)


def run() -> dict:
    from simchi.transit import network as N
    out = {"design": "see module docstring (pre-registered)", "test_period": TEST}
    g = N._graph()
    for kind in ("bus", "rail"):
        service = service_by_daytype(g, kind)
        df = load_observed(kind)
        F = forecasts(df, *TEST)
        out[kind] = evaluate(F)
        nw = next_week(df, service)
        out[kind]["next_week_asof"] = str(df["date"].max().date())
        out[kind]["next_week"] = nw.to_dict("records")
    return out


def main(argv=None):
    from simchi import jsonutil
    res = run()
    out = REPORTS / "ops"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "crowding.json", "w") as f:
        jsonutil.dump(res, f, indent=1)
    for kind in ("bus", "rail"):
        r = res[kind]
        print(kind, r["forecasts"], "forecasts,", r["units"], "units; MALE naive", round(r["B_naive"]["male"], 4),
              "median-of-4", round(r["M_med4"]["male"], 4), "PASS" if r["pass"] else "FAIL", r["by_daytype"])


if __name__ == "__main__":
    main()
