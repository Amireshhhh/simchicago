"""Commute mode choice: multinomial logit on network level-of-service, fitted to ACS shares.

Alternatives: car (drove alone + carpool), transit, walk/bike, other. For a trip from area i to
destination j (77 areas + outside Chicago):

    V_car     = b_ivt * T_car
    V_transit = a_t + b_t * noveh + e_t * outside
                + b_ivt * IVT + b_wait * WAIT + b_walk * WALK + b_xfer * XFERS + b_fare * FARE
    V_walk    = a_w + b_w * noveh + b_walk * T_walk
    V_other   = a_o + b_o * noveh + b_ivt * T_other

T_car = tau_car + 60 c d / v_car and T_other = 2 + 60 c d / v_other (minutes; d straight-line km,
c = circuity), T_walk = 60 c d / walk speed. IVT, WAIT, WALK (minutes), XFERS (boardings - 1)
and FARE (dollars) are the AM-peak transit skim of the CTA network (simchi/transit/network.py).
noveh: household has no vehicle; outside: job outside Chicago.

The fare coefficient is not estimable from these data: the fare is $2.25 or $2.50 everywhere,
so its effect is absorbed by a_t. It is fixed by an assumed value of time,
b_fare = 60 * b_ivt / VOT_PER_HOUR (hypothesis), and only matters for fare scenarios.

Fit: for each area i the model share of mode m is the average of P_m over the area's
vehicle-ownership mix (NO_VEH / TOT_HH) and over work destinations j with the gravity
probabilities P_ij; the grouped log-likelihood sum_i sum_m N_im log share_im uses the ACS commuter
counts N_im. Sign constraints (justification): time, waiting, walking and transfers cannot make
an alternative more attractive (b_ivt, b_wait, b_walk, b_xfer <= 0); having no vehicle cannot make
the non-car alternatives less attractive (b_t, b_w, b_o in [0, 8]).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

from simchi.world import OUTSIDE, World

MODES = ["car", "transit", "walk", "other"]
PARAM_NAMES = ["a_t", "b_t(no veh)", "e_t(outside)", "a_w", "b_w(no veh)", "a_o", "b_o(no veh)",
               "b_ivt(per min)", "b_wait(per min)", "b_walk(per min)", "b_xfer(per transfer)"]
BOUNDS = [(-15, 15), (0, 8), (-15, 15), (-15, 15), (0, 8), (-15, 15), (0, 8),
          (-1, 0), (-1, 0), (-1, 0), (-5, 0)]
VOT_PER_HOUR = 15.0          # dollars per hour of in-vehicle time (hypothesis; sensitivity in EVALUATION)
CIRCUITY = 1.3
WALK_KMH = 4.8
TAU_OTHER_MIN = 2.0
LOS_KEYS = ("t_car", "t_walk", "t_other", "ivt", "wait", "walk", "xfer", "fare")


def observed_mode_counts(world: World) -> np.ndarray:
    t = world.cds.table
    return np.column_stack([t["DROVE_AL"] + t["CARPOOL"], t["TRANSIT"], t["WALK_BIKE"], t["COMM_OTHER"]]).astype(float)


def level_of_service(dist_km, skim_ij: dict, v_car: float, tau_car: float, v_other: float,
                     time_multiplier: dict | None = None) -> dict:
    """Level-of-service arrays for the four alternatives. `skim_ij` holds ivt, wait, walk,
    boardings and fare arrays of the same shape as dist_km."""
    tm = {"car": 1.0, "walk": 1.0, "transit": 1.0, "other": 1.0, **(time_multiplier or {})}
    d = np.asarray(dist_km, float) * CIRCUITY
    return {
        "t_car": (tau_car + 60.0 * d / v_car) * tm["car"],
        "t_walk": 60.0 * d / WALK_KMH * tm["walk"],
        "t_other": (TAU_OTHER_MIN + 60.0 * d / v_other) * tm["other"],
        "ivt": np.asarray(skim_ij["ivt"], float) * tm["transit"],
        "wait": np.asarray(skim_ij["wait"], float),
        "walk": np.asarray(skim_ij["walk"], float),
        "xfer": np.maximum(np.asarray(skim_ij["boardings"], float) - 1.0, 0.0),
        "fare": np.asarray(skim_ij["fare"], float),
    }


def area_los(world: World, skim, v_car: float, tau_car: float, v_other: float, time_multiplier=None) -> dict:
    """(77, 78) level of service between community areas (and to outside Chicago)."""
    sk = {"ivt": skim.ivt, "wait": skim.wait, "walk": skim.walk, "boardings": skim.boardings, "fare": skim.fare}
    return level_of_service(world.dist_km, sk, v_car, tau_car, v_other, time_multiplier)


@dataclass
class ModeModel:
    theta: np.ndarray = field(default_factory=lambda: np.zeros(len(PARAM_NAMES)))
    loglik: float = float("nan")
    vot_per_hour: float = VOT_PER_HOUR

    @property
    def b_fare(self) -> float:
        return 60.0 * self.theta[7] / self.vot_per_hour

    def _V(self, noveh, outside, los: dict) -> np.ndarray:
        a_t, b_t, e_t, a_w, b_w, a_o, b_o, b_ivt, b_wait, b_walk, b_xfer = self.theta
        noveh = np.asarray(noveh, float)
        outside = np.asarray(outside, float)
        shape = np.broadcast(noveh, outside, *(np.asarray(los[k]) for k in LOS_KEYS)).shape
        V = np.zeros(shape + (4,))
        V[..., 0] = b_ivt * los["t_car"]
        V[..., 1] = (a_t + b_t * noveh + e_t * outside + b_ivt * los["ivt"] + b_wait * los["wait"]
                     + b_walk * los["walk"] + b_xfer * los["xfer"] + self.b_fare * los["fare"])
        V[..., 2] = a_w + b_w * noveh + b_walk * los["t_walk"]
        V[..., 3] = a_o + b_o * noveh + b_ivt * los["t_other"]
        return V

    def probs(self, noveh, outside, los: dict) -> np.ndarray:
        """Choice probabilities (..., 4) over car, transit, walk/bike, other."""
        V = self._V(noveh, outside, los)
        return np.exp(V - logsumexp(V, axis=-1, keepdims=True))

    def area_shares(self, world: World, P_dest: np.ndarray, los: dict) -> np.ndarray:
        t = world.cds.table
        p_noveh = (t["NO_VEH"] / t["TOT_HH"]).to_numpy(float)
        outside = (np.arange(OUTSIDE + 1) == OUTSIDE).astype(float)[None, :]
        out = np.zeros((len(t), 4))
        for nv, wgt in ((1.0, p_noveh), (0.0, 1 - p_noveh)):
            pm = self.probs(nv, outside, los)                                   # (77, 78, 4)
            out += wgt[:, None] * (P_dest[:, :, None] * pm).sum(1)
        return out

    def as_dict(self):
        return {**dict(zip(PARAM_NAMES, map(float, self.theta), strict=True)),
                "b_fare(per dollar, from VOT)": float(self.b_fare)}


def grouped_negll(theta, world, P_dest, los, N, rows, vot=VOT_PER_HOUR):
    s = ModeModel(np.asarray(theta), vot_per_hour=vot).area_shares(world, P_dest, los)[rows]
    return -(N[rows] * np.log(np.clip(s, 1e-300, None))).sum()


X0 = np.array([0.0, 2.0, -1.0, 0.0, 1.5, -3.0, 0.5, -0.03, -0.05, -0.05, -0.3])


def fit_mode_choice(world: World, P_dest: np.ndarray, los: dict, areas=None, bounds=BOUNDS,
                    x0=None, vot=VOT_PER_HOUR) -> ModeModel:
    N = observed_mode_counts(world)
    rows = np.arange(len(N)) if areas is None else np.asarray(areas)
    # scale the objective to per-commuter units so L-BFGS-B's tolerances are meaningful
    scale = N[rows].sum()
    res = minimize(lambda th: grouped_negll(th, world, P_dest, los, N, rows, vot) / scale,
                   X0 if x0 is None else x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 2000, "ftol": 1e-13, "gtol": 1e-9})
    return ModeModel(res.x, loglik=-float(res.fun) * scale, vot_per_hour=vot)
