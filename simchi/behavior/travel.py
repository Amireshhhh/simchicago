"""Door-to-door travel times, fitted to ACS mean commute times by community area.

    T_m(d) = tau_m + 60 * CIRCUITY * d / v_m        (minutes, d = straight-line km)

Assumptions: circuity 1.3; walking 4.8 km/h; "other" (bike, taxi, ...) 15 km/h; terminal
times 5 min by car (parking), 10 min by transit (access and waiting), 2 min otherwise.
The car and transit speeds are fitted by weighted least squares so that each area's
expected commute time

    E_i = sum_j P_ij sum_m share_m(i, j) T_m(d_ij)

matches the ACS mean, AGG_TT / TOT_COMM (weights: sqrt of commuters TOT_COMM). Fitting the
terminal times as well is not identified from 77 area means: car speed runs to its bound
and the car terminal time to ~25 min.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from simchi.behavior.mode_choice import ModeModel, transit_access
from simchi.world import OUTSIDE, World

CIRCUITY = 1.3
WALK_KMH = 4.8
MODE_CODE = {"walk": 1, "car": 2, "transit": 3, "other": 4}       # viewer MODES index
CHOICE_TO_CODE = np.array([2, 3, 1, 4])                           # car, transit, walk, other


@dataclass
class TravelModel:
    v_car: float = 30.0
    v_transit: float = 18.0
    v_other: float = 15.0
    tau_car: float = 5.0
    tau_transit: float = 10.0
    time_multiplier: tuple = (1.0, 1.0, 1.0, 1.0)     # scenario knob per mode code 1..4

    def minutes_scalar(self, dist_km: float, mode_code: int) -> float:
        """Same as minutes() for one trip (fast path for the scheduler)."""
        d = dist_km * CIRCUITY
        if mode_code == 1:
            v, tau = WALK_KMH, 2.0
        elif mode_code == 2:
            v, tau = self.v_car, self.tau_car
        elif mode_code == 3:
            v, tau = self.v_transit, self.tau_transit
        else:
            v, tau = self.v_other, 2.0
        return (tau + 60.0 * d / v) * self.time_multiplier[min(max(mode_code, 1), 4) - 1]

    def minutes(self, dist_km, mode_code) -> np.ndarray:
        d = np.asarray(dist_km, float) * CIRCUITY
        code = np.asarray(mode_code)
        speed = np.select([code == 1, code == 2, code == 3], [WALK_KMH, self.v_car, self.v_transit], self.v_other)
        tau = np.select([code == 2, code == 3], [self.tau_car, self.tau_transit], 2.0)
        mult = np.asarray(self.time_multiplier, float)[np.clip(code, 1, 4) - 1]
        return (tau + 60.0 * d / speed) * mult

    def as_dict(self):
        return {"v_car_kmh": self.v_car, "v_transit_kmh": self.v_transit, "v_other_kmh": self.v_other,
                "tau_car_min": self.tau_car, "tau_transit_min": self.tau_transit,
                "walk_kmh": WALK_KMH, "circuity": CIRCUITY}


def observed_commute_minutes(world: World) -> np.ndarray:
    t = world.cds.table
    return (t["AGG_TT"] / t["TOT_COMM"]).to_numpy(float)


def expected_commute_minutes(world: World, P_dest: np.ndarray, mode: ModeModel, travel: TravelModel) -> np.ndarray:
    t = world.cds.table
    p_noveh = (t["NO_VEH"] / t["TOT_HH"]).to_numpy(float)
    ta = transit_access(world)
    outside = (np.arange(OUTSIDE + 1) == OUTSIDE).astype(float)
    T = np.stack([travel.minutes(world.dist_km, c) for c in CHOICE_TO_CODE], axis=-1)   # (77, 78, 4)
    out = np.zeros(len(t))
    for nv, wgt in ((1.0, p_noveh), (0.0, 1 - p_noveh)):
        pm = mode.probs(nv, ta[:, None], world.dist_km, outside[None, :])
        out += wgt * (P_dest * (pm * T).sum(-1)).sum(1)
    return out


def fit_travel(world: World, P_dest, mode: ModeModel, areas=None) -> TravelModel:
    obs = observed_commute_minutes(world)
    w = np.sqrt(world.cds.table["TOT_COMM"].to_numpy(float))
    rows = np.arange(len(obs)) if areas is None else np.asarray(areas)

    def resid(x):
        m = TravelModel(v_car=x[0], v_transit=x[1])
        return (w * (expected_commute_minutes(world, P_dest, mode, m) - obs))[rows]

    res = least_squares(resid, x0=[30.0, 18.0], bounds=([8, 5], [80, 60]))
    return TravelModel(v_car=float(res.x[0]), v_transit=float(res.x[1]))
