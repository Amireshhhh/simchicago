"""Daily activity plans.

Every person starts and ends the day at home. Mandatory activities (work, school, aftercare)
are placed first; discretionary activities (shop, social, leisure, errand) are then drawn
with day-type probabilities and time windows and inserted where they fit, travel included.
The output for one person-day is a list of segments that partitions [0, 1440] minutes:

    (t0, t1, kind, x0, z0, x1, z1, mode)

kind indexes KINDS (activities, "trip" for travel); mode indexes MODES (0 when not moving).

Common random numbers: each person-day draws all its uniforms up front, in a fixed order,
from a stream seeded by (seed, day, pid). Whether a draw is *used* may depend on the state
(e.g. perceived safety), but the draws themselves never do, so two runs that differ only in
a scenario setting differ only through the decisions that setting changes.

Default values are those recorded in SimChicago v0.1's exported configuration; they are
scenario assumptions (provenance "scenario"), not estimates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

KINDS = ["home", "work", "school", "aftercare", "shop", "social", "leisure", "errand", "trip", "wait"]
K = {k: i for i, k in enumerate(KINDS)}
DISCRETIONARY = ["shop", "social", "leisure", "errand"]
N_UNIFORMS = 48


@dataclass
class ScheduleParams:
    p_work_weekday: float = 0.92
    p_work_weekend: float = 0.20
    work_start_mean: float = 510.0          # minutes after midnight (08:30)
    work_start_sd: float = 50.0
    work_dur_mean_min: float = 510.0
    work_dur_sd_min: float = 45.0
    school_start: float = 480.0
    school_end: float = 900.0
    young_child_age: int = 12
    aftercare_until: float = 1140.0
    p_base: dict = field(default_factory=lambda: {
        "weekday": {"shop": 0.30, "social": 0.15, "leisure": 0.20, "errand": 0.10},
        "weekend": {"shop": 0.40, "social": 0.30, "leisure": 0.30, "errand": 0.05}})
    # (earliest start, latest start, mean duration) in minutes
    windows: dict = field(default_factory=lambda: {
        "shop": (600, 1200, 45), "social": (1080, 1290, 120), "leisure": (420, 1140, 75), "errand": (540, 1020, 40)})
    weekend_social_window: tuple = (780, 1260, 150)
    evening_start: float = 1080.0
    walk_max_m: float = 1500.0
    discretionary_multiplier: float = 1.0     # scenario knob: scales every p_base
    max_discretionary: int = 3


@dataclass
class PersonDay:
    """Inputs for one person-day (plain values so plans are cheap to build)."""
    pid: int
    age: int
    home: tuple
    work: tuple | None            # None if the person does not work away from home today
    school: tuple | None
    commute_mode: int             # MODES index
    has_car: bool
    weekend: bool
    works_today_prob: float
    child_needs_aftercare: bool
    p_cancel_evening: float       # probability of cancelling an evening discretionary activity
    disc_dest: object             # callable(rng_uniforms, activity) -> (x, z)


def _travel(params, travel, a, b, mode_default, has_car):
    d_km = float(np.hypot(b[0] - a[0], b[1] - a[1])) / 1000.0
    if d_km * 1000.0 <= params.walk_max_m:
        mode = 1
    elif mode_default == 2 and not has_car:
        mode = 3
    else:
        mode = mode_default
    return travel.trip_minutes(a, b, d_km, mode), mode


def plan_day(p: PersonDay, params: ScheduleParams, travel, u: np.ndarray):
    """Returns (segments, events). `u` holds N_UNIFORMS uniforms for this person-day."""
    ui = iter(u)
    nxt = lambda: next(ui)  # noqa: E731
    normal = lambda: float(np.sqrt(-2 * np.log(max(nxt(), 1e-12))) * np.cos(2 * np.pi * nxt()))  # noqa: E731
    events = []
    acts = []   # (start, end, kind, xy)

    # Mandatory activities (draws are taken whether or not they are used)
    work_u, ws, wd = nxt(), normal(), normal()
    if p.work is not None and work_u < p.works_today_prob:
        start = float(np.clip(params.work_start_mean + params.work_start_sd * ws, 300, 900))
        dur = float(np.clip(params.work_dur_mean_min + params.work_dur_sd_min * wd, 180, 720))
        acts.append((start, min(start + dur, 1380), K["work"], p.work))
    if p.school is not None and not p.weekend:
        acts.append((params.school_start, params.school_end, K["school"], p.school))
        if p.child_needs_aftercare:
            acts.append((params.school_end, params.aftercare_until, K["aftercare"], p.school))
            events.append({"kind": "aftercare", "until": params.aftercare_until})

    # Discretionary activities
    day = "weekend" if p.weekend else "weekday"
    for name in DISCRETIONARY:
        u_take, u_start, u_dur, u_cancel = nxt(), nxt(), nxt(), nxt()
        dest_u = (nxt(), nxt(), nxt())
        prob = min(1.0, params.p_base[day][name] * params.discretionary_multiplier)
        if p.age < 5 or u_take >= prob:
            continue
        lo, hi, mean = params.weekend_social_window if (p.weekend and name == "social") else params.windows[name]
        start = lo + (hi - lo) * u_start
        dur = float(np.clip(-mean * np.log(max(u_dur, 1e-9)), 15, 4 * mean))
        if start >= params.evening_start and u_cancel < p.p_cancel_evening:
            events.append({"kind": "cancelled", "activity": name, "t": start})
            continue
        acts.append((start, start + dur, K[name], p.disc_dest(dest_u, name)))

    # Sequence: keep activities in start order, dropping any that cannot fit with travel.
    acts.sort(key=lambda a: a[0])
    segs = []
    t, loc = 0.0, p.home
    kept = 0
    for start, end, kind, xy in acts:
        is_disc = kind >= K["shop"]
        if is_disc and kept >= params.max_discretionary:
            continue
        tt, mode = _travel(params, travel, loc, xy, p.commute_mode, p.has_car)
        back, _ = _travel(params, travel, xy, p.home, p.commute_mode, p.has_car)
        depart = max(t, start - tt)
        arrive = depart + tt
        end = max(end, arrive + 10)
        if end + back > 1440:
            end = 1440 - back
        if end - arrive < 10:          # no room for this activity
            if not is_disc:
                events.append({"kind": "skipped", "activity": KINDS[kind]})
            continue
        if depart > t:
            segs.append((t, depart, K["home"] if loc == p.home else K["wait"], *loc, *loc, 0))
        segs.append((depart, arrive, K["trip"], *loc, *xy, mode))
        segs.append((arrive, end, kind, *xy, *xy, 0))
        t, loc = end, xy
        kept += is_disc
    if loc != p.home:
        tt, mode = _travel(params, travel, loc, p.home, p.commute_mode, p.has_car)
        segs.append((t, t + tt, K["trip"], *loc, *p.home, mode))
        t += tt
    segs.append((t, 1440.0, K["home"], *p.home, *p.home, 0))
    return segs, events
