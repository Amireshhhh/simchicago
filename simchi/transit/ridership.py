"""CTA ridership (observed) and the model's predicted ridership by bus route and 'L' station.

Observed: City of Chicago data portal mirrors pinned in data/sources.toml
  cta_bus_route_daily   boardings per bus route and day
  cta_l_station_daily   turnstile entries per 'L' station and day
Only weekdays (daytype "W") are used, as means over a period.

Model: weekday commute trips by transit between areas,

    T_ij = 2 * C_i * P(j | i) * Ptransit(i, j)

(C_i: ACS commuters TOT_COMM of area i; P(j | i): gravity model; Ptransit: the network mode-choice
model averaged over the area's vehicle-ownership mix; 2: there and back), spread over zone-point
pairs and loaded onto the AM-peak shortest paths of the CTA network (all-or-nothing). The result
is a predicted *pattern* of boardings by route and entries by station, up to scale: the model has
no non-commute transit demand, so the scale is calibrated (one factor for buses, one for the 'L').
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from simchi.data.cds import ROOT, source


def load_observed(kind: str) -> pd.DataFrame:
    key = {"bus": "cta_bus_route_daily", "rail": "cta_l_station_daily"}[kind]
    df = pd.read_csv(ROOT / source(key)["file"], dtype={"route": str, "station_id": str})
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.rename(columns={"route": "id", "station_id": "id"})


def weekday_means(df: pd.DataFrame, start: str, end: str) -> pd.Series:
    """Mean weekday rides per id over [start, end] (inclusive), ids with at least 20 weekdays."""
    d = df[(df["daytype"] == "W") & (df["date"] >= start) & (df["date"] <= end)]
    g = d.groupby("id")["rides"]
    n = g.size()
    return g.mean()[n >= 20]


def commute_transit_od(world, P_dest, mode_model, travel, skim) -> np.ndarray:
    """(77, 78) expected weekday commute trips by transit (both directions)."""
    from simchi.behavior.mode_choice import area_los
    from simchi.world import OUTSIDE
    t = world.cds.table
    C = t["TOT_COMM"].to_numpy(float)
    p_noveh = (t["NO_VEH"] / t["TOT_HH"]).to_numpy(float)
    los = area_los(world, skim, travel.v_car, travel.tau_car, travel.v_other)
    outside = (np.arange(OUTSIDE + 1) == OUTSIDE).astype(float)[None, :]
    pt = np.zeros_like(P_dest)
    for nv, w in ((1.0, p_noveh), (0.0, 1 - p_noveh)):
        pt += w[:, None] * mode_model.probs(nv, outside, los)[..., 1]
    return 2.0 * C[:, None] * P_dest * pt


def predict(graph, sc, T: np.ndarray) -> tuple[pd.Series, pd.Series]:
    """Unscaled predicted weekday boardings per bus route and entries per 'L' station (parent id)."""
    res = graph.assign(sc, graph.area_demand_to_points(T))
    bus = defaultdict(float)
    for p, b, rail in zip(graph.pats, res["pattern_boardings"], graph.pat_rail, strict=True):
        if not rail:
            bus[p["route"]] += b
    st = defaultdict(float)
    for i, e in enumerate(res["stop_entries"]):
        if e > 0:
            st[graph.stop_parent[i]] += e
    rail_stations = {graph.stop_parent[graph.pnode_stop[k]] for k in np.flatnonzero(graph.pat_rail[graph.pnode_pat])}
    stations = pd.Series({s: st.get(s, 0.0) for s in rail_stations})
    return pd.Series(bus), stations


def scheduled_service(graph) -> tuple[pd.Series, pd.Series]:
    """Baseline covariates: weekday scheduled trips per bus route; weekday scheduled train
    departures per 'L' station (summed over the patterns that stop there)."""
    bus = defaultdict(float)
    st = defaultdict(float)
    for i, p in enumerate(graph.pats):
        trips = p["trips_weekday"]
        if graph.pat_rail[i]:
            for s in set(p["stops"][:-1]):
                st[_parent(graph, s)] += trips
        else:
            bus[p["route"]] += trips
    return pd.Series(bus), pd.Series(st)


def _parent(graph, stop_id):
    if not hasattr(graph, "_sidx"):
        graph._sidx = {s: i for i, s in enumerate(graph.stop_ids)}
    return graph.stop_parent[graph._sidx[stop_id]]
