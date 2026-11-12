"""Door-to-door travel times.

Transit: the CTA network skim (simchi/transit/network.py): walk + wait + in-vehicle minutes
between community areas (AM peak, weekday), looked up by the areas of the trip's ends.
Car, walk and "other" (bike, taxi, ...):

    T_m(d) = tau_m + 60 * CIRCUITY * d / v_m        (minutes, d = straight-line km)

Assumptions: circuity 1.3; walking 4.8 km/h; "other" 15 km/h; terminal times 5 min by car
(parking), 2 min otherwise. The car speed is fitted by weighted least squares so that each area's
expected commute time

    E_i = sum_j P_ij sum_m share_m(i, j) T_m(i, j)

matches the ACS mean, AGG_TT / TOT_COMM (weights: sqrt of commuters TOT_COMM). The mode shares
depend on T_car, so the car speed and the mode-choice model are fitted alternately until the
speed changes by less than 0.01 km/h (fit_mode_and_travel).

Trips whose ends cannot both be placed in a community area (outside the 250 m area grid) use
the linear approximation T = tau_transit + 60 CIRCUITY d / v_transit fitted by least squares to
the area-to-area skim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from simchi.behavior.mode_choice import (CIRCUITY, TAU_OTHER_MIN, WALK_KMH, ModeModel, area_los,
                                         fit_mode_choice, observed_mode_counts)
from simchi.world import OUTSIDE, World

MODE_CODE = {"walk": 1, "car": 2, "transit": 3, "other": 4}       # viewer MODES index
CHOICE_TO_CODE = np.array([2, 3, 1, 4])                           # car, transit, walk, other
GRID_M = 250.0


@dataclass
class AreaGrid:
    """Community area (1..77, 0 = none) of each GRID_M cell over the city's bounding box."""
    x0: float
    z0: float
    cells: np.ndarray

    def area_at(self, x: float, z: float) -> int:
        i = int((x - self.x0) // GRID_M)
        j = int((z - self.z0) // GRID_M)
        if 0 <= i < self.cells.shape[0] and 0 <= j < self.cells.shape[1]:
            return int(self.cells[i, j])
        return 0


def area_grid(world: World) -> AreaGrid:
    from simchi.world import area_of_points
    minx, minz, maxx, maxz = np.array([g.bounds for g in world.cds.geoms.values()]).T
    x0, z0 = minx.min(), minz.min()
    nx = int(np.ceil((maxx.max() - x0) / GRID_M))
    nz = int(np.ceil((maxz.max() - z0) / GRID_M))
    cx, cz = np.meshgrid(x0 + (np.arange(nx) + 0.5) * GRID_M, z0 + (np.arange(nz) + 0.5) * GRID_M, indexing="ij")
    cells = area_of_points(world, np.column_stack([cx.ravel(), cz.ravel()])).reshape(nx, nz)
    return AreaGrid(float(x0), float(z0), cells.astype(np.int16))


@dataclass
class TravelModel:
    v_car: float = 30.0
    v_other: float = 15.0
    tau_car: float = 5.0
    v_transit: float = 15.0          # linear approximation of the skim (fallback only)
    tau_transit: float = 15.0
    time_multiplier: tuple = (1.0, 1.0, 1.0, 1.0)     # scenario knob per mode code 1..4
    transit_total: np.ndarray | None = field(default=None, repr=False)   # (77, 78) skim minutes
    grid: AreaGrid | None = field(default=None, repr=False)

    def minutes_scalar(self, dist_km: float, mode_code: int) -> float:
        """Same as minutes() for one trip (distance-based; transit uses the linear fallback)."""
        d = dist_km * CIRCUITY
        if mode_code == 1:
            v, tau = WALK_KMH, 0.0
        elif mode_code == 2:
            v, tau = self.v_car, self.tau_car
        elif mode_code == 3:
            v, tau = self.v_transit, self.tau_transit
        else:
            v, tau = self.v_other, TAU_OTHER_MIN
        return (tau + 60.0 * d / v) * self.time_multiplier[min(max(mode_code, 1), 4) - 1]

    def minutes(self, dist_km, mode_code) -> np.ndarray:
        d = np.asarray(dist_km, float) * CIRCUITY
        code = np.asarray(mode_code)
        speed = np.select([code == 1, code == 2, code == 3], [WALK_KMH, self.v_car, self.v_transit], self.v_other)
        tau = np.select([code == 1, code == 2, code == 3], [0.0, self.tau_car, self.tau_transit], TAU_OTHER_MIN)
        mult = np.asarray(self.time_multiplier, float)[np.clip(code, 1, 4) - 1]
        return (tau + 60.0 * d / speed) * mult

    def trip_minutes(self, a, b, dist_km: float, mode_code: int) -> float:
        """Minutes for a trip from point a to point b; transit trips use the network skim."""
        if mode_code == 3 and self.transit_total is not None and self.grid is not None:
            i = self.grid.area_at(*a)
            j = self.grid.area_at(*b)
            if i and j:
                return float(self.transit_total[i - 1, j - 1])
            if i and not j and dist_km > 15.0:      # leaving the city
                return float(self.transit_total[i - 1, OUTSIDE])
            if j and not i and dist_km > 15.0:
                return float(self.transit_total[j - 1, OUTSIDE])
        return self.minutes_scalar(dist_km, mode_code)

    def as_dict(self):
        return {"v_car_kmh": self.v_car, "v_other_kmh": self.v_other, "tau_car_min": self.tau_car,
                "transit_fallback_v_kmh": self.v_transit, "transit_fallback_tau_min": self.tau_transit,
                "walk_kmh": WALK_KMH, "circuity": CIRCUITY}


def observed_commute_minutes(world: World) -> np.ndarray:
    t = world.cds.table
    return (t["AGG_TT"] / t["TOT_COMM"]).to_numpy(float)


def expected_commute_minutes(world: World, P_dest: np.ndarray, mode: ModeModel, travel: TravelModel, skim) -> np.ndarray:
    t = world.cds.table
    p_noveh = (t["NO_VEH"] / t["TOT_HH"]).to_numpy(float)
    los = area_los(world, skim, travel.v_car, travel.tau_car, travel.v_other)
    T = np.stack([los["t_car"], skim.total, los["t_walk"], los["t_other"]], axis=-1)   # (77, 78, 4)
    outside = (np.arange(OUTSIDE + 1) == OUTSIDE).astype(float)[None, :]
    out = np.zeros(len(t))
    for nv, wgt in ((1.0, p_noveh), (0.0, 1 - p_noveh)):
        pm = mode.probs(nv, outside, los)
        out += wgt * (P_dest * (pm * T).sum(-1)).sum(1)
    return out


def fit_car_speed(world: World, P_dest, mode: ModeModel, skim, areas=None, v0=30.0) -> TravelModel:
    obs = observed_commute_minutes(world)
    w = np.sqrt(world.cds.table["TOT_COMM"].to_numpy(float))
    rows = np.arange(len(obs)) if areas is None else np.asarray(areas)

    def resid(x):
        m = TravelModel(v_car=float(x[0]))
        return (w * (expected_commute_minutes(world, P_dest, mode, m, skim) - obs))[rows]

    res = least_squares(resid, x0=[v0], bounds=([8], [80]))
    return TravelModel(v_car=float(res.x[0]))


def transit_fallback(world: World, skim) -> tuple[float, float]:
    """(tau, v) of the least-squares line T = tau + 60 CIRCUITY d / v over area pairs."""
    d = world.dist_km[:, :OUTSIDE].ravel() * CIRCUITY
    T = skim.total[:, :OUTSIDE].ravel()
    A = np.column_stack([np.ones_like(d), 60.0 * d])
    tau, inv_v = np.linalg.lstsq(A, T, rcond=None)[0]
    return float(tau), float(1.0 / inv_v)


def fit_mode_and_travel(world: World, P_dest, skim, areas=None, tol=0.01, max_iter=20):
    """Alternate the mode-choice fit and the car-speed fit until the speed converges.
    Returns (ModeModel, TravelModel, iterations)."""
    v = 30.0
    mode = None
    for it in range(1, max_iter + 1):
        los = area_los(world, skim, v, TravelModel.tau_car, TravelModel.v_other)
        mode = fit_mode_choice(world, P_dest, los, areas=areas, x0=None if mode is None else mode.theta)
        tm = fit_car_speed(world, P_dest, mode, skim, areas=areas, v0=v)
        if abs(tm.v_car - v) < tol:
            v = tm.v_car
            break
        v = tm.v_car
    los = area_los(world, skim, v, TravelModel.tau_car, TravelModel.v_other)
    mode = fit_mode_choice(world, P_dest, los, areas=areas, x0=mode.theta)
    tau, vt = transit_fallback(world, skim)
    return mode, TravelModel(v_car=v, v_transit=vt, tau_transit=tau), it


__all__ = ["TravelModel", "AreaGrid", "area_grid", "observed_commute_minutes", "expected_commute_minutes",
           "fit_car_speed", "fit_mode_and_travel", "observed_mode_counts", "CHOICE_TO_CODE", "MODE_CODE",
           "CIRCUITY", "WALK_KMH"]
