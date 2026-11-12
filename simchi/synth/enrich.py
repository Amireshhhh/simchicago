"""Person attributes the simulation needs, added to a synthetic population.

Random choices are stored as uniforms (u_*), not as outcomes, so a scenario that shifts a
probability (work from home, mode preferences) re-decides with the same draws.

  home_x, home_z, home_tract  household home point: tract by 2014 population, uniform within
  work_area                   work destination drawn from the gravity model (0 if not employed)
  work_x, work_z              uniform point in the work area, or 5 km past the city gateway
  u_wfh, p_wfh                work-from-home draw and the area's ACS share WORK_HOME / T_WRKR16OV
  u_mode, noveh, dist_km      inputs of the commute-mode choice
  school_x, school_z          a point in the home area for ages 5-17 (no school data: assumption)
  sbar                        baseline perceived safety in [0.4, 0.95], decreasing in the home
                              tract's 2015 violent-crime rate (hypothesis)
  kappa                       individual sensitivity of the safety response (latent, lognormal)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from simchi.world import OUTSIDE, World


def enrich(pop, world: World, P_dest: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    H = pop.households.copy()
    P = pop.persons.copy()
    t = world.cds.table

    home = np.zeros((len(H), 2))
    tract = np.zeros(len(H), np.int64)
    for area, idx in H.groupby("area").indices.items():
        pts, gids = world.sample_points(int(area), len(idx), rng, return_tract=True)
        home[idx], tract[idx] = pts, gids
    H["home_x"], H["home_z"], H["home_tract"] = home[:, 0], home[:, 1], tract
    P = P.merge(H[["hh_id", "home_x", "home_z", "home_tract"]], on="hh_id", how="left")

    n = len(P)
    employed = (P["labor"] == 0).to_numpy()
    area_idx = P["area"].to_numpy() - 1
    P["p_wfh"] = (t["WORK_HOME"] / t["T_WRKR16OV"]).to_numpy()[area_idx]
    P["u_wfh"] = rng.uniform(size=n)

    work_area = np.zeros(n, int)
    cum = np.cumsum(P_dest, axis=1)
    u = rng.uniform(size=n)
    dest = (u[:, None] > cum[area_idx]).sum(1).clip(max=OUTSIDE)        # 0..77
    work_area[employed] = dest[employed] + 1                             # 1..77, 78 = outside
    P["work_area"] = work_area

    work = np.full((n, 2), np.nan)
    for a, idx in pd.Series(np.flatnonzero(employed)).groupby(work_area[employed]).indices.items():
        rows = np.flatnonzero(employed)[idx]
        if a == OUTSIDE + 1:
            g = world.gateway_xy[world.nearest_gateway[area_idx[rows]]]
            out = g - world.cds.city.centroid.coords[0]
            out /= np.linalg.norm(out, axis=1, keepdims=True)
            work[rows] = g + out * 5000.0 + rng.normal(0, 800, (len(rows), 2))
        else:
            work[rows] = world.sample_points(int(a), len(rows), rng, by_population=False)
    P["work_x"], P["work_z"] = work[:, 0], work[:, 1]

    P["noveh"] = (P["vehicles"] == 0).astype(float)
    d = np.hypot(P["work_x"] - P["home_x"], P["work_z"] - P["home_z"]) / 1000.0
    P["dist_km"] = np.where(employed, d, 0.0)
    P["outside"] = (work_area == OUTSIDE + 1).astype(float)
    P["u_mode"] = rng.uniform(size=n)

    school = np.full((n, 2), np.nan)
    kids = (P["age"] >= 5) & (P["age"] <= 17)
    for area, idx in P[kids].groupby("area").indices.items():
        rows = P[kids].index.to_numpy()[idx]
        school[rows] = world.sample_points(int(area), len(rows), rng)
    P["school_x"], P["school_z"] = school[:, 0], school[:, 1]

    crime = world.tracts["violent_crime_rate_2015"].reindex(P["home_tract"]).fillna(
        world.tracts["violent_crime_rate_2015"].median()).to_numpy()
    P["sbar"] = np.clip(0.9 - 2.5 * crime, 0.4, 0.95)
    P["kappa"] = np.exp(rng.normal(0.0, 0.25, n))
    P["has_car"] = P["vehicles"] > 0
    return P
