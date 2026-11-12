"""Bunching control: a holding recommender and its simulated evaluation (python -m simchi.ops.holding).

Recommender (applied to a live snapshot or a simulation): for each vehicle i of a route-direction
with a leader and a follower, with time headways h_front (to the leader) and h_back (to the
follower), recommend holding at its next stop for

    hold_i = min(MAX_HOLD_MIN, max(0, (h_back - h_front) / 2))      only if h_front < 0.5 x H_sched

i.e. move it halfway towards the midpoint between its neighbours ("two-way headway" holding), and
only when it is running bunched behind its leader. Advisory output only; CTA's own operations
rules are not known to SimChicago.

PRE-REGISTERED EVALUATION (SIMULATED; written before the evaluation was run): a 40-stop loop with
10 buses, scheduled headway 8 min, passengers arriving at each stop at a constant rate (2 per min),
dwell = 6 s + 3 s per boarding, stop-to-stop travel times lognormal (mean 90 s, CV 0.25). Control
points every 10th stop apply the recommender. 30 seeds x 6 simulated hours (first hour discarded),
same random numbers with and without control. Metrics: mean passenger wait (E[H^2] / (2 E[H]) over
stop headways), bunching share (stop headways < 0.25 x 8 min), mean round-trip time.
Criterion: holding lowers the mean passenger wait, with the paired 95% interval below zero.
Not validated on CTA operations: no observed data on holding exists in SimChicago.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

MAX_HOLD_MIN = 2.0
BUNCHED = 0.5


def recommend(headways_front: np.ndarray, headways_back: np.ndarray, scheduled: float) -> np.ndarray:
    hf = np.asarray(headways_front, float)
    hb = np.asarray(headways_back, float)
    hold = np.clip((hb - hf) / 2.0, 0.0, MAX_HOLD_MIN)
    return np.where(np.isfinite(hf) & np.isfinite(hb) & (hf < BUNCHED * scheduled), hold, 0.0)


def simulate(control: bool, seed: int, n_bus=10, n_stops=40, H=8.0, rate=2.0, hours=6.0, warm=1.0,
             tt_mean=90.0, tt_cv=0.25, dwell0=6.0, dwell1=3.0, control_every=10, start="spread") -> dict:
    """Event-by-event loop simulation. Each bus visits stops in order; arrival times are tracked per
    stop so that headways at each stop are exact. Random travel times come from one stream per
    (bus, visit), shared between the controlled and uncontrolled runs.

    start="spread" (default): buses start evenly spaced around the loop and every stop was last
    served one even spacing ago, i.e. the line starts in regular operation. start="terminal" is the
    initial condition of the first, pre-registered run: all buses leave stop 0 one headway apart
    while passengers at every stop have been waiting since time -H, so the first bus meets very
    long dwells (a start-up artifact; see docs/EVALUATION.md)."""
    rng = np.random.default_rng(seed)
    sig = np.sqrt(np.log(1 + tt_cv ** 2))
    mu = np.log(tt_mean) - sig ** 2 / 2
    T = hours * 3600.0
    max_visits = int(T / (tt_mean * 0.5)) + n_stops
    tt = rng.lognormal(mu, sig, size=(n_bus, max_visits))
    if start == "terminal":
        t = np.array([i * H * 60.0 for i in range(n_bus)])[::-1].copy()     # bus 0 starts last
        stop = np.zeros(n_bus, int)
        last_dep = np.full(n_stops, -H * 60.0)                           # passengers accumulate since the last departure
    else:
        per_stop = tt_mean + dwell0 + dwell1 * rate * H                  # mean time per stop at the scheduled headway
        stop = (np.arange(n_bus) * n_stops // n_bus).astype(int)         # bus b ahead of bus b - 1
        t = np.zeros(n_bus)
        last_dep = np.empty(n_stops)
        for s_ in range(n_stops):
            ahead = (stop - s_) % n_stops
            ahead[ahead == 0] = n_stops
            last_dep[s_] = -ahead.min() * per_stop                       # the nearest bus ahead passed this long ago
    visit = np.zeros(n_bus, int)
    arrivals = [[] for _ in range(n_stops)]
    holds = 0.0
    laps = []
    lap_start = t.copy()
    while True:
        b = int(np.argmin(t))
        now = t[b]
        if now > T:
            break
        s = stop[b]
        arrivals[s].append(now)
        board = rate / 60.0 * max(now - last_dep[s], 0.0)
        dep = now + dwell0 + dwell1 * board
        if control and s % control_every == 0:
            # headways from the last arrivals at this stop (front) and the follower's expected arrival (back)
            prev = arrivals[s][-2] if len(arrivals[s]) > 1 else now - H * 60.0
            hf = (now - prev) / 60.0
            fol = (b - 1) % n_bus                                         # the bus behind started one headway later
            gap_stops = (s - stop[fol]) % n_stops                         # stops between its next stop and this one
            mean_dwell = dwell0 + dwell1 * rate * H                      # boardings over one scheduled headway
            hb = ((t[fol] - now) + gap_stops * (tt_mean + mean_dwell)) / 60.0
            h = float(recommend(np.array([hf]), np.array([hb]), H)[0]) * 60.0
            dep += h
            holds += h
        last_dep[s] = dep
        if s == n_stops - 1:
            laps.append(dep - lap_start[b])
            lap_start[b] = dep
        stop[b] = (s + 1) % n_stops
        t[b] = dep + tt[b, visit[b] % max_visits]
        visit[b] += 1
    hw = []
    for s in range(n_stops):
        a = np.array(arrivals[s])
        a = a[a > warm * 3600.0]
        if len(a) > 1:
            hw.append(np.diff(a) / 60.0)
    h = np.concatenate(hw)
    return {"mean_wait_min": float((h ** 2).mean() / (2 * h.mean())), "bunching_share": float((h < 0.25 * H).mean()),
            "headway_cv": float(h.std() / h.mean()), "round_trip_min": float(np.mean(laps) / 60.0) if laps else float("nan"),
            "hold_min_per_hour": holds / 60.0 / hours}


def evaluate(seeds=range(1, 31), start="spread") -> dict:
    rows = [(simulate(False, s, start=start), simulate(True, s, start=start)) for s in seeds]
    out = {"label": "simulated", "seeds": len(rows), "start": start,
           "criterion": "mean passenger wait lower with holding (paired 95% interval below 0)"}
    for k in ("mean_wait_min", "bunching_share", "headway_cv", "round_trip_min", "hold_min_per_hour"):
        a = np.array([r[0][k] for r in rows])
        b = np.array([r[1][k] for r in rows])
        d = b - a
        h = stats.t.ppf(0.975, len(d) - 1) * d.std(ddof=1) / np.sqrt(len(d))
        out[k] = {"no_control": float(a.mean()), "holding": float(b.mean()), "diff": float(d.mean()),
                  "ci_low": float(d.mean() - h), "ci_high": float(d.mean() + h)}
    out["pass"] = bool(out["mean_wait_min"]["ci_high"] < 0)
    return out


def live_recommendations(snapshot: dict, max_items: int = 30) -> list:
    """Holding advice for the vehicles in a published snapshot (observed positions)."""
    import pandas as pd

    from simchi.data.cds import load_cds
    from simchi.transit.reliability import Schedule, headways, positions
    rows = []
    for v in snapshot.get("vehicles", []):
        for t_poll, x, z in v.get("track", []):
            rows.append({"poll_utc": t_poll, "mode": v["mode"], "id": v["id"], "route": v["route"], "x": x, "z": z,
                         "dly": v.get("dly", False), "pid": "", "train_dir": ""})
    if not rows:
        return []
    frame = load_cds().frame
    df = pd.DataFrame(rows)
    lon, lat = frame.to_lonlat(df["x"].to_numpy(), df["z"].to_numpy())
    df["lon"], df["lat"] = lon, lat
    df["run"] = "snapshot"
    df["poll"] = pd.to_datetime(df["poll_utc"], utc=True)
    from simchi.transit.reliability import CHICAGO
    loc = df["poll"].dt.tz_convert(CHICAGO)
    df["hour"] = loc.dt.hour
    df["day"] = np.where(loc.dt.weekday < 5, "weekday", np.where(loc.dt.weekday == 5, "saturday", "sunday"))
    sched = Schedule()
    P = positions(df, sched, frame)
    last = P[P["poll"] == P["poll"].max()]
    out = []
    for (route, d, sg), g in last.groupby(["route", "direction", "dsign"]):
        if len(g) < 3:
            continue
        H = headways(g, sched)
        if H.empty:
            continue
        H_s = float(H["scheduled_headway_min"].iat[0])
        if not np.isfinite(H_s):
            continue
        g = g.sort_values("s")                                           # headways() orders by s too
        hw = H["headway_min"].to_numpy()
        if sg > 0:      # moving towards larger s: the leader of vehicle k is k + 1
            hf, hb = np.concatenate([hw, [np.nan]]), np.concatenate([[np.nan], hw])
        else:
            hf, hb = np.concatenate([[np.nan], hw]), np.concatenate([hw, [np.nan]])
        hold = recommend(hf, hb, H_s)
        for vid, hd, a, b_ in zip(g["id"], hold, hf, hb, strict=True):
            if hd > 0:
                out.append({"vehicle": vid, "route": route, "hold_min": round(float(hd), 1), "headway_front_min": round(float(a), 1),
                            "headway_back_min": round(float(b_), 1), "scheduled_headway_min": round(H_s, 1)})
    return sorted(out, key=lambda r: -r["hold_min"])[:max_items]


def main():
    from simchi import jsonutil
    from simchi.paths import REPORTS
    res = {"corrected_start": evaluate(start="spread"), "preregistered_run_terminal_start": evaluate(start="terminal")}
    (REPORTS / "ops").mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "ops" / "holding.json", "w") as f:
        jsonutil.dump(res, f, indent=1)
    for name, r in res.items():
        print(name)
        for k in ("mean_wait_min", "bunching_share", "headway_cv", "round_trip_min", "hold_min_per_hour"):
            print("  ", k, {a: round(b, 4) for a, b in r[k].items()})
        print("  ", "PASS" if r["pass"] else "FAIL")


if __name__ == "__main__":
    main()
