"""Day-by-day simulation of the synthetic population.

Per simulated day:
  1. incidents: recorded CPD incidents of that date ("replay"), draws from the fitted
     intensity model ("simulated"), both, or none;
  2. a plan for every person (behavior/schedule.py), with a probability of cancelling evening
     discretionary activities that grows as perceived safety falls below its baseline;
  3. exposure: a person who is out of home (at an activity or travelling) within
     `radius_m` of an incident at the minute it happens is directly exposed;
  4. awareness: E_aware[i] = number of i's network contacts directly exposed that day;
  5. perceived safety (hypothesised mechanism, Theorem 1 in docs/DESIGN.md), starting from
     the no-exposure equilibrium s* (see safety_equilibrium):
         s <- ((1 - eta - c) s + eta sbar + c W s) * (1 - a)^E_direct * (1 - b)^E_aware
     With eta, c >= 0, eta + c <= 1, W row-stochastic and s, sbar in [0, 1], s stays in
     [0, 1]; without exposure the map is a contraction with modulus 1 - eta.

Random numbers: day d uses one stream seeded (seed, d) for the person uniforms and a
separate stream for simulated incidents, so scenarios with the same seed share them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd

from simchi.behavior.schedule import DISCRETIONARY, KINDS, N_UNIFORMS, PersonDay, ScheduleParams, plan_day
from simchi.behavior.mode_choice import level_of_service
from simchi.behavior.travel import CHOICE_TO_CODE, CIRCUITY, TravelModel
from simchi.transit.network import FARE_BUS, FARE_RAIL, NetworkScenario

INCIDENT_MODES = ("none", "replay", "simulated", "both")
MODE_NAMES = ["", "walk", "car", "transit", "other"]


@dataclass
class SafetyParams:
    eta: float = 0.10           # pull towards the baseline per day
    c: float = 0.20             # weight of contacts' perceived safety
    a: float = 0.15             # proportional drop per direct exposure
    b: float = 0.02             # proportional drop per exposed contact
    radius_m: float = 400.0     # exposure radius
    gamma_cancel: float = 0.5   # scale of the evening-cancellation response

    def validate(self):
        if not (0 <= self.eta and 0 <= self.c and self.eta + self.c <= 1):
            raise ValueError("need eta, c >= 0 and eta + c <= 1")
        if not (0 <= self.a <= 1 and 0 <= self.b <= 1 and self.gamma_cancel >= 0 and self.radius_m >= 0):
            raise ValueError("need 0 <= a, b <= 1, gamma_cancel >= 0, radius_m >= 0")


@dataclass
class SimConfig:
    n_days: int = 7
    seed: int = 1
    start_date: str = "2020-10-05"
    incident_mode: str = "both"
    safety: SafetyParams = field(default_factory=SafetyParams)
    schedule: ScheduleParams = field(default_factory=ScheduleParams)
    wfh_multiplier: float = 1.0                       # scales each area's work-from-home share
    mode_shift: dict = field(default_factory=lambda: {"transit": 0.0, "walk": 0.0, "other": 0.0})
    time_multiplier: dict = field(default_factory=lambda: {"walk": 1.0, "car": 1.0, "transit": 1.0, "other": 1.0})
    # scheduled CTA service (acts on the network skim, hence on mode choice and transit trip times):
    # multipliers keyed by "bus", "rail" or a route id; fares in dollars
    network: dict = field(default_factory=lambda: {"headway_multiplier": {"bus": 1.0, "rail": 1.0},
                                                   "ivt_multiplier": {"bus": 1.0, "rail": 1.0},
                                                   "wait_multiplier": {"bus": 1.0, "rail": 1.0},
                                                   "fare_bus": FARE_BUS, "fare_rail": FARE_RAIL})
    simulated_incident_multiplier: float = 1.0        # scales the fitted daily incident level
    local_trip_share: float = 0.45                    # discretionary trips within 1 km of home

    def validate(self):
        if self.incident_mode not in INCIDENT_MODES:
            raise ValueError(f"incident_mode must be one of {INCIDENT_MODES}")
        if not 1 <= self.n_days <= 366:
            raise ValueError("n_days must be in 1..366")
        self.safety.validate()
        return self

    def to_dict(self):
        return asdict(self)


@dataclass
class SimResult:
    cfg: SimConfig
    segments: dict          # column arrays: day, pid, t0, t1, kind, x0, z0, x1, z1, mode
    incidents: list         # one DataFrame per day
    events: list            # dicts with day, t, pid, kind, ...
    safety: np.ndarray      # (n_persons, n_days + 1)
    daily: list             # one dict of weighted indicators per day
    commute_mode: np.ndarray
    wfh: np.ndarray


def safety_step(s, sbar, W, Ed, Ea, p: SafetyParams):
    return ((1 - p.eta - p.c) * s + p.eta * sbar + p.c * (W @ s)) * (1 - p.a) ** Ed * (1 - p.b) ** Ea


def safety_equilibrium(sbar, W, p: SafetyParams, tol: float = 1e-14, max_iter: int = 100_000) -> np.ndarray:
    """Fixed point of the update without exposure: (eta I + c (I - W)) s* = eta sbar.

    Solved by the Jacobi iteration s <- (eta sbar + c W s) / (eta + c), which is a contraction
    in the max-norm with factor c / (eta + c) < 1 when eta > 0 (W is row-stochastic), so it
    converges geometrically to the unique fixed point using only sparse products. s* lies in
    [min sbar, max sbar]. With eta = 0, s* = sbar is used."""
    if p.eta <= 0:
        return sbar.copy()
    s = sbar.copy()
    k = p.eta + p.c
    for _ in range(max_iter):
        s_new = (p.eta * sbar + p.c * (W @ s)) / k
        if np.abs(s_new - s).max() < tol:
            return s_new
        s = s_new
    return s


def network_scenario(cfg: SimConfig) -> NetworkScenario:
    n = cfg.network
    return NetworkScenario(headway_multiplier=dict(n.get("headway_multiplier", {})),
                           ivt_multiplier=dict(n.get("ivt_multiplier", {})),
                           wait_multiplier=dict(n.get("wait_multiplier", {})),
                           fare_bus=float(n.get("fare_bus", FARE_BUS)), fare_rail=float(n.get("fare_rail", FARE_RAIL)))


def scenario_skim(built, cfg: SimConfig):
    """The AM-peak transit skim under the scenario's network settings."""
    sc = network_scenario(cfg)
    if sc.key() == built.skim.scenario.key():
        return built.skim
    from simchi.transit.network import skim
    return skim(sc)


def person_los(built, cfg: SimConfig, sk) -> dict:
    """Level of service of each person's commute (home area -> work area or outside)."""
    P = built.persons
    i = P["area"].to_numpy() - 1
    j = np.clip(P["work_area"].to_numpy() - 1, 0, None)
    sk_ij = {"ivt": sk.ivt[i, j], "wait": sk.wait[i, j], "walk": sk.walk[i, j],
             "boardings": sk.boardings[i, j], "fare": sk.fare[i, j]}
    tr = built.travel
    return level_of_service(P["dist_km"].to_numpy(), sk_ij, tr.v_car, tr.tau_car, tr.v_other, cfg.time_multiplier)


def _choose_modes(built, cfg: SimConfig, sk) -> np.ndarray:
    P = built.persons
    V = built.mode_model._V(P["noveh"].to_numpy(), P["outside"].to_numpy(), person_los(built, cfg, sk))
    for k, name in ((1, "transit"), (2, "walk"), (3, "other")):
        V[:, k] += cfg.mode_shift.get(name, 0.0)
    pr = np.exp(V - V.max(1, keepdims=True))
    pr /= pr.sum(1, keepdims=True)
    choice = (P["u_mode"].to_numpy()[:, None] > np.cumsum(pr, 1)).sum(1).clip(max=3)
    return CHOICE_TO_CODE[choice]


def _incidents_for_day(built, cfg: SimConfig, date, d: int) -> pd.DataFrame:
    parts = []
    if cfg.incident_mode in ("replay", "both"):
        obs = built.observed_incidents
        day = obs[obs["time"].dt.normalize() == date]
        if len(day):
            parts.append(pd.DataFrame({
                "record_id": day["record_id"].to_numpy(), "time": day["time"].to_numpy(),
                "t_min": (day["time"] - date).dt.total_seconds().to_numpy() / 60.0,
                "area": day["area"].to_numpy(), "x": day["x"].to_numpy(), "z": day["z"].to_numpy(),
                "label": "observed", "desc": day["desc"].to_numpy()}))
    if cfg.incident_mode in ("simulated", "both"):
        rng = np.random.default_rng([cfg.seed, d, 1_000_003])
        model = replace(built.intensity, level_per_day=built.intensity.level_per_day * cfg.simulated_incident_multiplier)
        sim = model.sample_day(date, rng, built.world, next_id=-(d * 10_000 + 1))
        if len(sim):
            parts.append(sim)
    if not parts:
        return pd.DataFrame(columns=["record_id", "time", "t_min", "area", "x", "z", "label", "desc"])
    return pd.concat(parts, ignore_index=True).sort_values("t_min").reset_index(drop=True)


def run_sim(built, cfg: SimConfig) -> SimResult:
    cfg.validate()
    P = built.persons
    n = len(P)
    sp = cfg.safety
    params = cfg.schedule
    sk = scenario_skim(built, cfg)
    mt = cfg.time_multiplier.get("transit", 1.0)
    travel = TravelModel(v_car=built.travel.v_car, v_transit=built.travel.v_transit,
                         v_other=built.travel.v_other, tau_car=built.travel.tau_car,
                         tau_transit=built.travel.tau_transit,
                         time_multiplier=tuple(cfg.time_multiplier[m] for m in ("walk", "car", "transit", "other")),
                         transit_total=sk.walk + sk.wait + mt * sk.ivt, grid=built.area_grid)

    employed = (P["labor"] == 0).to_numpy()
    wfh = employed & (P["u_wfh"].to_numpy() < np.clip(P["p_wfh"].to_numpy() * cfg.wfh_multiplier, 0, 1))
    commuter = employed & ~wfh & np.isfinite(P["work_x"].to_numpy())
    modes = _choose_modes(built, cfg, sk)
    modes[~commuter] = np.where(P["has_car"].to_numpy()[~commuter], 2, 3)

    # Aftercare: a child aged 5..young_child_age whose household adults all commute that day.
    age = P["age"].to_numpy()
    adult = age >= 18
    hh = P["hh_id"].to_numpy()
    all_adults_commute = pd.Series(~adult | commuter).groupby(hh).transform("all").to_numpy()
    aftercare = (age >= 5) & (age <= params.young_child_age) & all_adults_commute

    home = P[["home_x", "home_z"]].to_numpy()
    work = P[["work_x", "work_z"]].to_numpy()
    school = P[["school_x", "school_z"]].to_numpy()
    has_car = P["has_car"].to_numpy()
    sbar = P["sbar"].to_numpy()
    kappa = P["kappa"].to_numpy()
    weight = P["weight"].to_numpy()
    area_idx = P["area"].to_numpy() - 1
    disc_cum = built.disc_cum            # (77, 77) cumulative destination distribution
    pools = built.disc_points            # area index -> (m, 2) candidate points

    def make_dest(i):
        h = home[i]
        cum = disc_cum[area_idx[i]]

        def dest(u3, _name):
            if u3[0] < cfg.local_trip_share:
                r = 1000.0 * np.sqrt(u3[1])
                ang = 2 * np.pi * u3[2]
                return (h[0] + r * np.cos(ang), h[1] + r * np.sin(ang))
            j = min(int((u3[1] > cum).sum()), len(cum) - 1)
            pool = pools[j]
            x, z = pool[int(u3[2] * len(pool)) % len(pool)]
            return (float(x), float(z))
        return dest

    dests = [make_dest(i) for i in range(n)]
    W, A = built.network.W, built.network.A

    # Everyone starts at the no-exposure equilibrium, so without incidents perceived safety
    # stays there and the cancellation response (driven by the deficit below it) is zero.
    s_eq = safety_equilibrium(sbar, built.network.W, sp)
    s = s_eq.copy()
    safety = np.empty((n, cfg.n_days + 1))
    safety[:, 0] = s
    cols = {k: [] for k in ("day", "pid", "t0", "t1", "kind", "x0", "z0", "x1", "z1", "mode")}
    incidents, events, daily = [], [], []
    start = pd.Timestamp(cfg.start_date).normalize()

    for d in range(cfg.n_days):
        date = start + pd.Timedelta(days=d)
        weekend = date.weekday() >= 5
        inc = _incidents_for_day(built, cfg, date, d)
        incidents.append(inc.assign(day=d))
        U = np.random.default_rng([cfg.seed, d]).random((n, N_UNIFORMS))
        deficit = (s_eq - s) / s_eq
        deficit[deficit < 1e-9] = 0.0           # round-off of the fixed point is not a response
        p_cancel = np.clip(sp.gamma_cancel * kappa * deficit, 0.0, 1.0)
        p_work = params.p_work_weekend if weekend else params.p_work_weekday

        day_rows = []
        for i in range(n):
            pd_ = PersonDay(
                pid=i, age=int(age[i]), home=(home[i, 0], home[i, 1]),
                work=(work[i, 0], work[i, 1]) if commuter[i] else None,
                school=(school[i, 0], school[i, 1]) if np.isfinite(school[i, 0]) else None,
                commute_mode=int(modes[i]), has_car=bool(has_car[i]), weekend=weekend,
                works_today_prob=p_work, child_needs_aftercare=bool(aftercare[i]),
                p_cancel_evening=float(p_cancel[i]), disc_dest=dests[i])
            segs, evs = plan_day(pd_, params, travel, U[i])
            day_rows.append(segs)
            for e in evs:
                events.append({"day": d, "pid": i, **e})

        seg = np.array([r for segs in day_rows for r in segs], float)
        pid = np.repeat(np.arange(n), [len(segs) for segs in day_rows])
        for k, col in enumerate(("t0", "t1", "kind", "x0", "z0", "x1", "z1", "mode")):
            cols[col].append(seg[:, k])
        cols["day"].append(np.full(len(seg), d))
        cols["pid"].append(pid)

        # Exposure
        Ed = np.zeros(n)
        out_mask = seg[:, 2] != KINDS.index("home")
        for _, row in inc.iterrows():
            t = row["t_min"]
            live = out_mask & (seg[:, 0] <= t) & (t < seg[:, 1])
            if not live.any():
                continue
            S = seg[live]
            f = np.where(S[:, 1] > S[:, 0], (t - S[:, 0]) / np.maximum(S[:, 1] - S[:, 0], 1e-9), 0.0)
            x = S[:, 3] + f * (S[:, 5] - S[:, 3])
            z = S[:, 4] + f * (S[:, 6] - S[:, 4])
            dist = np.hypot(x - row["x"], z - row["z"])
            hit = dist <= sp.radius_m
            for who, dm in zip(pid[live][hit], dist[hit], strict=True):
                Ed[who] += 1
                events.append({"day": d, "pid": int(who), "kind": "exposure", "t": float(t),
                               "incident_id": int(row["record_id"]), "incident_label": row["label"],
                               "distance_m": float(dm)})
        Ea = A @ (Ed > 0).astype(float)
        s = safety_step(s, sbar, W, Ed, Ea, sp)
        safety[:, d + 1] = s
        daily.append(_daily_summary(d, date, seg, pid, weight, inc, Ed, events, s))

    segments = {k: np.concatenate(v) for k, v in cols.items()}
    for k in ("day", "pid", "kind", "mode"):
        segments[k] = segments[k].astype(int)
    return SimResult(cfg=cfg, segments=segments, incidents=incidents, events=events, safety=safety,
                     daily=daily, commute_mode=modes, wfh=wfh)


def _daily_summary(d, date, seg, pid, weight, inc, Ed, events, s):
    kind = seg[:, 2].astype(int)
    dur = seg[:, 1] - seg[:, 0]
    w = weight[pid]
    trips = kind == KINDS.index("trip")
    out = kind != KINDS.index("home")
    tw = {MODE_NAMES[m]: float(w[trips & (seg[:, 7] == m)].sum()) for m in (1, 2, 3, 4)}
    km = np.hypot(seg[:, 5] - seg[:, 3], seg[:, 6] - seg[:, 4]) / 1000.0 * CIRCUITY
    pkm = {MODE_NAMES[m]: float((w * km)[trips & (seg[:, 7] == m)].sum()) for m in (1, 2, 3, 4)}
    disc = {a: float(w[kind == KINDS.index(a)].sum()) for a in DISCRETIONARY}
    total_w = float(weight.sum())
    part = {}
    for a in ("work", "school", *DISCRETIONARY):
        who = np.unique(pid[kind == KINDS.index(a)])
        part[a] = float(weight[who].sum() / total_w)
    out_min = np.bincount(pid[out], weights=dur[out], minlength=len(weight))
    ev_start = np.maximum(seg[:, 0], 1080.0)
    ev_min = np.bincount(pid[out], weights=np.clip(seg[out, 1] - ev_start[out], 0, None), minlength=len(weight))
    cancelled = [e for e in events if e["day"] == d and e["kind"] == "cancelled"]
    return {
        "day": d, "date": str(date.date()), "weekday": date.day_name(),
        "incidents_observed": int((inc["label"] == "observed").sum()) if len(inc) else 0,
        "incidents_simulated": int((inc["label"] == "simulated").sum()) if len(inc) else 0,
        "agents_exposed": int((Ed > 0).sum()),
        "activities_cancelled": len(cancelled),
        "activities_cancelled_weighted": float(sum(weight[e["pid"]] for e in cancelled)),
        "trips_weighted": tw, "pkm_weighted": pkm, "discretionary_weighted": disc, "participation": part,
        "mean_out_of_home_min": float((weight * out_min).sum() / total_w),
        "mean_evening_out_min": float((weight * ev_min).sum() / total_w),
        "mean_perceived_safety": float((weight * s).sum() / total_w),
    }
