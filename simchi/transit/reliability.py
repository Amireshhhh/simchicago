"""Scheduled vs observed service from polled CTA vehicle positions (python -m simchi.transit.reliability).

Input: the `history.csv.gz` files of `live.yml` runs (one row per vehicle per poll, label
observed), e.g. downloaded workflow artifacts `vehicles-<run id>/`.

Definitions (fixed before any polled data existed; all times in Chicago local time):
  position    distance along the route-direction's representative GTFS shape (the pattern with
              most weekday trips), by projecting the vehicle's point; direction of a vehicle =
              sign of its movement along that shape between polls of the same run (vehicles seen
              once take the majority direction of their Bus Tracker pattern id / train direction)
  speed       median over (route, hour) of |movement| / time between consecutive polls of the
              same vehicle in a run (only 0.5-25 m/s kept)
  headway     at one poll, consecutive vehicles of a route-direction ordered by position:
              distance between them / speed, minutes
  scheduled headway   60 / scheduled trips of that route, direction, day type and hour (GTFS;
              routes coded with one GTFS direction for both ways, e.g. Yellow: trips / 2)
  bunching    share of headways below 0.25 x scheduled headway
  gap         share of headways above 2 x scheduled headway
  regularity  coefficient of variation of headways (route-direction-hour)
  service delivered   mean vehicles observed per poll / scheduled vehicles in service, the latter
              by Little's law: scheduled trips per hour x median scheduled run time / 60
              (missing trips show as a ratio below 1; extra or early pull-outs above 1)
  delayed     share of vehicle observations with CTA's delay flag (Bus Tracker `dly`, Train
              Tracker `isDly`); CTA does not publish an on-time definition in these feeds, so
              this is reported as "flagged delayed", not on-time performance
Everything here is observed (positions, flags) or scheduled (GTFS); nothing is simulated except
in polling_bias(), which is labelled simulated.
"""

from __future__ import annotations

import gzip
import json
import sys
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from simchi.transit.gtfs import BANDS, load_extract
from simchi.transit.interp import cumulative, project

CHICAGO = ZoneInfo("America/Chicago")
BUNCH = 0.25
GAP = 2.0
SPEED_RANGE = (0.5, 25.0)


def load_history(paths) -> pd.DataFrame:
    frames = []
    for p in paths:
        p = Path(p)
        run = p.parent.name
        with gzip.open(p, "rt") as f:
            df = pd.read_csv(f, dtype={"route": str, "id": str, "pid": str, "train_dir": str, "trip": str})
        frames.append(df.assign(run=run))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["poll"] = pd.to_datetime(df["poll_utc"], utc=True)
    loc = df["poll"].dt.tz_convert(CHICAGO)
    df["hour"] = loc.dt.hour
    wd = loc.dt.weekday
    df["day"] = np.where(wd < 5, "weekday", np.where(wd == 5, "saturday", "sunday"))
    df["date"] = loc.dt.date.astype(str)
    df["dly"] = df["dly"].astype(str).str.lower().isin(["true", "1"])
    return df


class Schedule:
    """Representative shapes, scheduled trips and run times per route and direction (GTFS extract)."""

    def __init__(self):
        pats = load_extract("patterns")
        shapes = load_extract("shapes")
        xy = {st["id"]: (st["x"], st["z"]) for st in load_extract("stops")}
        self.service = {(s["route"], s["direction"], s["day"], s["hour"]): s["trips"] for s in load_extract("service")}
        self.rep, self.runtime, self.dirs, self.both_ways = {}, {}, {}, set()
        by_rd = {}
        for p in pats:
            by_rd.setdefault((p["route"], p["direction"]), []).append(p)
        for (r, d), ps in by_rd.items():
            self.dirs.setdefault(r, []).append(d)
            main = max(ps, key=lambda p: p["trips_weekday"])
            sh = np.asarray(shapes[main["shape"]], float)
            self.rep[(r, d)] = (sh, cumulative(sh))
            rt = {}
            for band in BANDS:
                v = [p["offsets_min"][band][-1] for p in ps if band in p["offsets_min"]]
                if v:
                    rt[band] = float(np.median(v))
            self.runtime[(r, d)] = rt
            # opposite runs coded with one direction id: some pattern starts within 400 m of where
            # another ends and ends within 400 m of where that one starts
            ends = [(xy[p["stops"][0]], xy[p["stops"][-1]]) for p in ps]
            near = lambda a, b: np.hypot(a[0] - b[0], a[1] - b[1]) < 400.0  # noqa: E731
            if any(near(a0, b1) and near(a1, b0) for i, (a0, a1) in enumerate(ends) for (b0, b1) in ends[i + 1:]):
                self.both_ways.add((r, d))

    def trips(self, route, d, day, hour) -> float:
        n = float(self.service.get((route, d, day, hour), 0))
        return n / 2 if (route, d) in self.both_ways else n

    def headway(self, route, d, day, hour) -> float:
        n = self.trips(route, d, day, hour)
        return 60.0 / n if n > 0 else np.nan

    def in_service(self, route, d, day, hour) -> float:
        band = next((b for b, (h0, h1) in BANDS.items() if h0 <= hour < h1 or h0 <= hour + 24 < h1), None)
        rt = self.runtime.get((route, d), {}).get(band)
        if rt is None:
            return np.nan
        return self.trips(route, d, day, hour) * rt / 60.0


def positions(df: pd.DataFrame, sched: Schedule, frame) -> pd.DataFrame:
    """Adds x, z, s (m along the route's first-direction representative shape) and direction."""
    x, z = frame.from_lonlat(df["lon"].to_numpy(float), df["lat"].to_numpy(float))
    df = df.assign(x=x, z=z)
    s = np.full(len(df), np.nan)
    for r, idx in df.groupby("route").indices.items():
        d0 = min(sched.dirs.get(r, [None]) or [None]) if r in sched.dirs else None
        if d0 is None:
            continue
        shape, cum = sched.rep[(r, d0)]
        for i in idx:
            s[i] = project(shape, cum, (df["x"].iat[i], df["z"].iat[i]))[0]
    df = df.assign(s=s).dropna(subset=["s"])
    df = df.sort_values(["run", "id", "poll"])
    g = df.groupby(["run", "id"])
    ds = g["s"].diff()
    dt = g["poll"].diff().dt.total_seconds()
    df["v"] = (ds.abs() / dt).where(dt > 0)
    df["move"] = np.sign(ds)
    # vehicle direction: its own movement, else the majority of its pattern id / train direction
    veh = df.groupby(["run", "id"])["move"].sum()
    df["vsign"] = df.set_index(["run", "id"]).index.map(veh).to_numpy()
    key = np.where(df["mode"] == "bus", "pid:" + df["pid"].astype(str), "dir:" + df["train_dir"].astype(str))
    df["gkey"] = df["route"] + "|" + key
    maj = df[df["vsign"] != 0].groupby("gkey")["vsign"].apply(lambda v: np.sign(np.sign(v).sum()))
    sign = np.where(df["vsign"] != 0, np.sign(df["vsign"]), df["gkey"].map(maj).fillna(0).to_numpy())
    dirs = df["route"].map(lambda r: sorted(sched.dirs.get(r, [0])))
    df["direction"] = [d[0] if sg >= 0 or len(d) == 1 else d[1] for d, sg in zip(dirs, sign, strict=True)]
    df["dsign"] = sign
    return df[df["dsign"] != 0]


def headways(df: pd.DataFrame, sched: Schedule) -> pd.DataFrame:
    """One row per pair of consecutive vehicles of a route-direction at one poll."""
    lo, hi = SPEED_RANGE
    v = df[(df["v"] >= lo) & (df["v"] <= hi)].groupby(["route", "hour"])["v"].median()
    rows = []
    for (route, d, sg, poll), g in df.groupby(["route", "direction", "dsign", "poll"]):
        if len(g) < 2:
            continue
        sp = v.get((route, int(g["hour"].iat[0])), np.nan)
        if not np.isfinite(sp):
            continue
        s = np.sort(g["s"].to_numpy())
        h = np.diff(s) / sp / 60.0
        hour, day = int(g["hour"].iat[0]), g["day"].iat[0]
        sh = sched.headway(route, d, day, hour)
        for x in h:
            rows.append({"route": route, "mode": g["mode"].iat[0], "direction": d, "poll": poll, "day": day,
                         "hour": hour, "headway_min": x, "scheduled_headway_min": sh})
    return pd.DataFrame(rows)


def metrics(df: pd.DataFrame, H: pd.DataFrame, sched: Schedule) -> pd.DataFrame:
    """Per route, direction, day type and hour."""
    obs = (df.groupby(["route", "mode", "direction", "day", "hour", "poll"]).size()
             .groupby(["route", "mode", "direction", "day", "hour"]).agg(["mean", "size"])
             .rename(columns={"mean": "vehicles_per_poll", "size": "polls"}))
    dl = df.groupby(["route", "mode", "direction", "day", "hour"])["dly"].mean().rename("delayed_share")
    out = obs.join(dl).reset_index()
    out["scheduled_in_service"] = [sched.in_service(r, d, day, h) for r, d, day, h in
                                   zip(out["route"], out["direction"], out["day"], out["hour"], strict=True)]
    out["scheduled_headway_min"] = [sched.headway(r, d, day, h) for r, d, day, h in
                                    zip(out["route"], out["direction"], out["day"], out["hour"], strict=True)]
    out["service_delivered"] = out["vehicles_per_poll"] / out["scheduled_in_service"]
    if len(H):
        H = H.assign(bunch=H["headway_min"] < BUNCH * H["scheduled_headway_min"],
                     gap=H["headway_min"] > GAP * H["scheduled_headway_min"])
        hg = H.groupby(["route", "direction", "day", "hour"]).agg(
            headways=("headway_min", "size"), headway_mean_min=("headway_min", "mean"),
            headway_cv=("headway_min", lambda x: float(np.std(x) / np.mean(x)) if len(x) > 1 else np.nan),
            bunching_share=("bunch", "mean"), gap_share=("gap", "mean")).reset_index()
        out = out.merge(hg, on=["route", "direction", "day", "hour"], how="left")
    return out


def route_summary(M: pd.DataFrame) -> pd.DataFrame:
    w = M["polls"]
    agg = []
    for (route, mode), g in M.groupby(["route", "mode"]):
        ww = g["polls"].to_numpy(float)
        hw = g["headways"].fillna(0).to_numpy(float) if "headways" in g else np.zeros(len(g))

        def wmean(col, weights):
            x = g[col].to_numpy(float) if col in g else np.full(len(g), np.nan)
            ok = np.isfinite(x) & (weights > 0)
            return float((x[ok] * weights[ok]).sum() / weights[ok].sum()) if ok.any() else np.nan
        agg.append({"route": route, "mode": mode, "polls": int(ww.sum()), "headways": int(hw.sum()),
                    "service_delivered": wmean("service_delivered", ww), "delayed_share": wmean("delayed_share", ww),
                    "bunching_share": wmean("bunching_share", hw), "gap_share": wmean("gap_share", hw),
                    "headway_cv": wmean("headway_cv", hw)})
    del w
    return pd.DataFrame(agg)


def coverage(df: pd.DataFrame) -> dict:
    """What the polling actually observed: runs, polls, hours covered (GitHub schedules can be
    delayed or skipped, so coverage is measured, not assumed)."""
    if df.empty:
        return {"runs": 0, "polls": 0}
    polls = df.drop_duplicates("poll_utc")
    loc = pd.to_datetime(polls["poll_utc"], utc=True).dt.tz_convert(CHICAGO)
    span_h = (loc.max() - loc.min()).total_seconds() / 3600.0
    expected = span_h * 12 * 3                       # 12 runs per hour x 3 polls
    by_hour = loc.dt.hour.value_counts().sort_index()
    return {"runs": int(df["run"].nunique()), "polls": int(len(polls)), "first_poll_local": str(loc.min()),
            "last_poll_local": str(loc.max()), "span_hours": round(span_h, 2),
            "polls_expected_if_every_run_fired": int(round(expected)),
            "poll_coverage": float(len(polls) / expected) if expected > 0 else None,
            "polls_by_local_hour": {int(k): int(v) for k, v in by_hour.items()},
            "dates": sorted(df["date"].unique().tolist())}


def polling_bias(n_days: int = 20, headway_min: float = 8.0, cv: float = 0.6, speed_cv: float = 0.1,
                 skip: float = 0.0, delay_mean_s: float = 0.0, seed: int = 0) -> dict:
    """SIMULATED check of what the polling design recovers. Vehicles leave a terminal at gamma
    headways (mean `headway_min`, coefficient of variation `cv`) and run a 15 km line at their
    own constant speed (mean 5 m/s, coefficient of variation `speed_cv`). Truth: headways at the
    line's midpoint (passage times). Estimate: as in headways(), spatial gaps between consecutive
    vehicles at each poll divided by the median speed, at the polling times (runs every 5 min,
    3 polls 60 s apart; each run skipped with probability `skip` and delayed by an exponential
    delay with mean `delay_mean_s`). Overtaking is allowed (positions are re-sorted)."""
    rng = np.random.default_rng(seed)
    k = 1.0 / cv ** 2
    T = n_days * 18 * 3600.0                             # 18 service hours a day, concatenated
    L, v0 = 15000.0, 5.0
    n = int(T / (headway_min * 60.0) * 1.5) + 100
    dep = np.cumsum(rng.gamma(k, headway_min * 60.0 / k, size=n))
    dep = dep[dep < T]
    v = v0 * np.clip(1 + speed_cv * rng.standard_normal(len(dep)), 0.3, None)
    true_h = np.diff(np.sort(dep + 0.5 * L / v)) / 60.0
    truth = {"bunching_share": float((true_h < BUNCH * headway_min).mean()), "gap_share": float((true_h > GAP * headway_min).mean()),
             "headway_cv": float(true_h.std() / true_h.mean())}
    run_t = np.arange(120.0, T, 300.0)
    run_t = run_t[rng.uniform(size=len(run_t)) >= skip]
    if delay_mean_s > 0:
        run_t = run_t + rng.exponential(delay_mean_s, size=len(run_t))
    polls = (run_t[:, None] + np.array([0.0, 60.0, 120.0])[None, :]).ravel()
    vmed = float(np.median(v))
    est = []
    for t in polls:
        pos = (t - dep) * v
        on = pos[(pos >= 0) & (pos <= L)]
        if len(on) > 1:
            est.append(np.diff(np.sort(on)) / vmed / 60.0)
    e = np.concatenate(est) if est else np.array([])
    estimate = {"bunching_share": float((e < BUNCH * headway_min).mean()), "gap_share": float((e > GAP * headway_min).mean()),
                "headway_cv": float(e.std() / e.mean())}
    return {"label": "simulated", "inputs": {"n_days": n_days, "headway_min": headway_min, "cv": cv, "speed_cv": speed_cv,
                                             "skip": skip, "delay_mean_s": delay_mean_s, "seed": seed},
            "truth": truth, "estimate": estimate, "bias": {k_: estimate[k_] - truth[k_] for k_ in truth},
            "headways_true": int(len(true_h)), "headways_sampled": int(len(e)), "polls": int(len(polls))}


BIAS_CASES = [  # (cv, speed_cv, skip, delay_mean_s)
    (0.6, 0.0, 0.0, 0.0), (0.6, 0.1, 0.0, 0.0), (0.6, 0.1, 0.2, 60.0), (0.6, 0.1, 0.5, 120.0),
    (0.3, 0.1, 0.2, 60.0), (1.0, 0.1, 0.2, 60.0), (0.6, 0.25, 0.2, 60.0)]


VIOLENT = ("HOMICIDE", "CRIMINAL SEXUAL ASSAULT", "ROBBERY", "ASSAULT", "BATTERY")


def route_area_shares(world) -> dict:
    """Share of each bus route's representative shapes (both directions) in each community area."""
    import shapely
    from shapely.geometry import LineString
    sched = Schedule()
    out = {}
    for (r, d), (shape, _) in sched.rep.items():
        line = LineString(shape)
        acc = out.setdefault(r, {})
        for num, g in world.cds.geoms.items():
            ln = line.intersection(g).length
            if ln > 0:
                acc[num] = acc.get(num, 0.0) + ln
    for r, acc in out.items():
        tot = sum(acc.values())
        out[r] = {a: v / tot for a, v in acc.items()} if tot > 0 else {}
    del shapely
    return out


def crime_join(routes: pd.DataFrame, world) -> dict:
    """DESCRIPTIVE ONLY. Route-level exposure to reported crime (CPD, 12 months to Oct 2026,
    aggregated by community area) next to the route's observed reliability. Exposure = the
    route's length share in each area x the area's rate per 1,000 residents (ACS population).
    Reports Spearman rank correlations; these are associations between places, not effects:
    crime does not 'cause' bunching or vice versa in this analysis, and both co-vary with
    density, ridership, traffic and service levels, none of which are controlled for."""
    from scipy.stats import spearmanr

    from simchi.data.cds import ROOT, source
    pop = world.cds.table["TOT_POP"].astype(float)
    tabs = {}
    for key in ("crimes_all_by_area", "crimes_cta_by_area"):
        c = pd.read_csv(ROOT / source(key)["file"])
        c = c[c["primary_type"].isin(VIOLENT) & c["community_area"].between(1, 77)]
        tabs[key] = (c.groupby("community_area")["n"].sum().reindex(pop.index).fillna(0) / pop * 1000.0)
    shares = route_area_shares(world)
    rows = []
    for r in routes.itertuples():
        sh = shares.get(str(r.route))
        if not sh:
            continue
        rows.append({"route": r.route, **{f"{k}_per_1000": sum(w * tabs[k][a] for a, w in sh.items()) for k in tabs},
                     **{m: getattr(r, m) for m in ("bunching_share", "gap_share", "service_delivered", "delayed_share")}})
    J = pd.DataFrame(rows)
    corr = {}
    for k in tabs:
        for m in ("bunching_share", "gap_share", "service_delivered", "delayed_share"):
            ok = J[[f"{k}_per_1000", m]].dropna() if len(J) else J
            if len(ok) >= 5:
                rho, p = spearmanr(ok.iloc[:, 0], ok.iloc[:, 1])
                corr[f"{k} vs {m}"] = {"spearman_rho": float(rho), "p_value": float(p), "routes": int(len(ok))}
    return {"label": "descriptive association, not causal", "violent_types": list(VIOLENT),
            "period": "2025-11-01 to 2026-10-31", "correlations": corr, "routes": J.to_dict("records")}


def report(paths, out_dir: Path, frame=None) -> dict:
    from simchi.data.cds import load_cds
    frame = frame or load_cds().frame
    df = load_history(paths)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cov = coverage(df)
    res = {"label": "observed (polled CTA positions) vs scheduled (GTFS)", "definitions": __doc__.split("Definitions")[1].split("Everything here")[0].strip(),
           "coverage": cov}
    bias = [polling_bias(cv=c, speed_cv=sc, skip=sk, delay_mean_s=d) for c, sc, sk, d in BIAS_CASES]
    res["polling_bias_simulated"] = bias
    if df.empty:
        res["note"] = "no polled history available"
    else:
        sched = Schedule()
        P = positions(df, sched, frame)
        H = headways(P, sched)
        M = metrics(P, H, sched)
        R = route_summary(M)
        M.to_csv(out_dir / "route_hour.csv", index=False)
        R.to_csv(out_dir / "routes.csv", index=False)
        res["routes"] = int(len(R))
        res["system"] = {mode: {k: float(np.nanmedian(g[k])) for k in ("service_delivered", "delayed_share", "bunching_share", "gap_share", "headway_cv")}
                         for mode, g in R.groupby("mode")}
        res["system_note"] = "medians over routes of each route's poll-weighted (or headway-weighted) mean"
        from simchi.world import build_world
        cj = crime_join(R[R["mode"] == "bus"], build_world())
        res["crime_join"] = {k: cj[k] for k in ("label", "violent_types", "period", "correlations")}
        pd.DataFrame(cj["routes"]).to_csv(out_dir / "crime_join_routes.csv", index=False)
    with open(out_dir / "summary.json", "w") as f:
        json.dump(res, f, indent=1, default=str)
    return res


def viewer_layer(routes_csv: Path, out: Path):
    """Compact per-route metrics for the viewer's reliability lens (observed, aggregated)."""
    R = pd.read_csv(routes_csv, dtype={"route": str})
    keep = ["service_delivered", "delayed_share", "bunching_share", "gap_share", "headway_cv", "polls"]
    data = {r.route: {k: (None if pd.isna(getattr(r, k)) else round(float(getattr(r, k)), 4)) for k in keep} for r in R.itertuples()}
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump({"schema": "simchi.reliability/1", "label": "observed", "generated_utc": pd.Timestamp.now(tz=timezone.utc).isoformat(),
                   "routes": data}, f, separators=(",", ":"))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("history_dir", help="directory with vehicles-<run id>/history.csv.gz subdirectories")
    ap.add_argument("--out", default="reports/reliability")
    ap.add_argument("--viewer", default=None, help="also write the viewer layer JSON here")
    a = ap.parse_args(argv)
    paths = sorted(Path(a.history_dir).glob("*/history.csv.gz"))
    res = report(paths, Path(a.out))
    if a.viewer and (Path(a.out) / "routes.csv").exists():
        viewer_layer(Path(a.out) / "routes.csv", Path(a.viewer))
    print(json.dumps({k: res[k] for k in res if k in ("coverage", "routes", "system", "note")}, indent=1, default=str))


if __name__ == "__main__":
    main()
