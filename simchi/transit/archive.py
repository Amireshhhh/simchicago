"""Durable, append-only polling history and reliability over the whole archive
(python -m simchi.transit.archive build|aggregate).

PRE-REGISTERED DESIGN, W2 (committed as "W2 pre-registration" before any archive was built;
the 14-day workflow artifacts had been used before only by simchi.transit.reliability)

STORAGE
  GitHub release assets, outside git history and outside Actions' 14-day artifact retention.
  One release per year, tag "history-<YYYY>" (GitHub allows up to 1000 assets per release, each
  under 2 GiB, no total size or bandwidth limit; docs.github.com "About releases", read
  2026-11-25). Per UTC date D two assets:
    vehicles-<D>.csv.gz   every observation of that date in the ingestion schema
    stats-<D>.csv.gz      the date's sufficient statistics (below)
  Append-only: an asset that exists is never replaced (uploads run without --clobber; an existing
  name is skipped and logged). A vehicles file over 200 MB compressed is not uploaded and the job
  fails loudly (size cap). Built daily by .github/workflows/archive.yml from the live.yml run
  artifacts still within retention (backfilling any missing date of the last 13 days). It makes no
  CTA request. Retention: indefinite (release assets are not subject to artifact retention).

INGESTION SCHEMA (one row per vehicle observation; any polling source can be dropped in)
  source         who observed it, e.g. "cta-bustracker", "cta-traintracker", or another name
  mode           bus | train
  route          route id as in the CTA GTFS extract (bus "9", train "Red", "Brn", ...)
  direction      the source's own direction code, text: Bus Tracker pattern "pid:<n>", Train
                 Tracker "trDr:<n>", or any code consistent within the source (the analysis infers
                 GTFS direction from movement and uses this code only as a fallback)
  vehicle_id     text, unique within source
  timestamp_utc  when the vehicle reported this position (ISO 8601, UTC)
  poll_utc       when the observation was taken (ISO 8601, UTC); may be empty, then the
                 timestamp rounded down to the minute is used
  lat, lon       WGS84 degrees
  delay_flag     1 / 0, or empty when the source has none (CTA: Bus Tracker dly, Train Tracker isDly)
  run            groups consecutive observations of one polling session (live.yml run id); may be
                 empty, then source + UTC hour is used
  Rows failing the schema (missing route, vehicle_id, timestamp or position; position outside the
  CTA service box of simchi.transit.live) are dropped and counted.

METRICS (per route x direction x day type x hour, over the whole archive; definitions of
simchi.transit.reliability: headway from positions and median speed, scheduled headway from GTFS)
  delivered/scheduled vehicles  mean vehicles observed per poll / scheduled vehicles in service
  headway CV                    std / mean of all headways of the cell (population std)
  bunching, gaps                shares below 0.25x / above 2x the scheduled headway. Reported as
                                LOWER BOUNDS for gaps (the measured polling bias: polling misses
                                gaps; simchi.transit.reliability.polling_bias)
  coverage                      system polls observed in the cell's day type and hour / polls the
                                polling plan expects (60 per hour per date of that day type: 12 runs
                                x 5 polls), and distinct dates contributing headways
  Sufficient statistics per day make the archive totals exact: polls, sum of vehicles per poll,
  observations, delay-flagged observations, headway count, sum, sum of squares, bunching count,
  gap count, and distinct dates.

MINIMUM AND COVERAGE (fixed now; nothing is reported as a result before the minimum)
  Minimum archive: first to last archived date spans >= 56 days (8 weeks) and each day type has
  >= 8 distinct dates. Until then the report states "insufficient data" with the coverage so far.
  Per-cell coverage threshold: a route-direction-day type-hour cell is eligible only if its
  system poll coverage is >= 0.5, it has headways from >= 4 distinct dates, and >= 30 headways.
  Cells under the threshold are excluded and listed; they are never filled in or imputed.

FREQUENT NETWORK DELIVERED CHECK
  Routes and windows from data/frequent_network.toml (weekdays 6-20 h start hours, weekends
  9-20 h); only dates on or after the route's effective_by. A cell meets the standard if its mean
  observed headway is <= 10 min. Reported: share of eligible cells meeting it, per route and
  overall, and the excluded cells. Because polling undercounts gaps, the share meeting is an
  upper bound on compliance.

AMENDMENT 1, 2026-11-26: DAY TYPE FROM SCHEDULED SERVICE (committed as "W2 amendment: day type
from scheduled service" before any W2 result existed; no aggregate had reached the minimum)
  Why: day types were assigned from the calendar weekday, so holidays (Thanksgiving 2026-11-26,
  the day after, 2026-12-25/26 in CTA's feed) would be scored against a regular schedule. The feed
  also shows that one reference week cannot stand for every date: CTA's service ids differ by
  weekday (45 services on Mondays, 51 on Tuesdays in the pinned feed) and change with schedule
  periods (services starting 2026-11-15/16), and the pinned feed ends on 2026-12-31.
  Day type of a Chicago service date D, from the GTFS feed in effect (one covering D):
    regular(D) = calendar.txt services with D's weekday flag and start_date <= D <= end_date
    actual(D)  = regular(D) with calendar_dates applied (added: exception_type 1, removed: 2)
    actual(D) empty                                   -> "unknown" (the feed does not cover D)
    actual(D) == regular(D)                           -> D's weekday class (Mon-Fri "weekday",
                                                         Saturday "saturday", Sunday "sunday")
    else, actual(D) == regular(S) for a Sunday S within D +- 7 days -> "sunday"; for a Saturday ->
      "saturday"; for a Monday-Friday -> "weekday"; otherwise -> "holiday"
  "holiday" and "unknown" dates are excluded from cell eligibility, from the minimum-archive
  counts (span and dates per day type count only weekday/saturday/sunday dates) and from the
  Frequent Network check.
  Scheduled values per date: each archived date's scheduled trips per route, direction and hour
  (first departure, as in the GTFS extract; one-direction-coded routes halved as before) and
  scheduled vehicles in service (trips x median trip duration that hour / 60) come from the trips
  active on that date in the feed in effect, and are stored in that date's statistics with the
  feed's sha256. Bunching and gap counts compare each headway with that date's scheduled headway.
  Archive-wide: scheduled headway = 60 / mean scheduled trips per date; delivered = mean vehicles
  per poll / mean scheduled vehicles in service.
  Files: the amended statistics are written as stats2-<D>.csv.gz (the append-only rule forbids
  replacing stats-<D>, which are kept and superseded); aggregation reads stats2 only. Dates whose
  run artifacts have left retention cannot be re-derived and are reported as missing.

TRAIN STATION HEADWAYS (derived data product for W10; not a test)
  train_station_headways-<D>.csv.gz, from Train Tracker rows of the live.yml artifacts (before
  conversion to the ingestion schema, which drops the next-station field): when a train's next
  station changes from S to another between two consecutive observations of that train at most
  150 s apart, it is taken to have arrived at S at the midpoint of the two observation times
  (error at most half the gap). Per station, line and Train Tracker direction, consecutive arrivals
  give headways. Columns: station_id, line, direction, arrival_utc, headway_min, continuous;
  continuous = no gap over 150 s between system polls from the previous arrival to this one (else
  an arrival may have been missed and the headway is an upper bound). No vehicle ids.

RIDER FEEDBACK (schema and comparison; no pass criterion, nothing is tuned to it)
  Schema: route, stop_id (CTA GTFS stop id), timestamp_utc, observed_wait_min, source.
  Each record is matched to its stop's route-direction (the GTFS patterns serving the stop on that
  route; if two directions serve it, both are averaged) and the cell of its Chicago day type and
  hour; predicted mean wait = E[H] (1 + CV^2) / 2 from that cell's archive statistics (random
  arrivals). Reported: records matched, Spearman correlation of observed vs predicted wait,
  median ratio observed / predicted, mean absolute difference in minutes, share within +-50%.
"""

from __future__ import annotations  # noqa: E402  (after the pre-registration docstring)

import gzip
import json
import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

from simchi.paths import DATA, REPORTS

SCHEMA = ["source", "mode", "route", "direction", "vehicle_id", "timestamp_utc", "poll_utc", "lat", "lon", "delay_flag", "run"]
SIZE_CAP_BYTES = 200 * 1024 * 1024
EXPECTED_POLLS_PER_HOUR = 60            # 12 runs x 5 polls (live.yml plan)
MIN_SPAN_DAYS, MIN_DATES_PER_DAYTYPE = 56, 8
CELL_MIN_COVERAGE, CELL_MIN_DATES, CELL_MIN_HEADWAYS = 0.5, 4, 30
CELL = ["route", "mode", "direction", "day", "hour"]


# ----------------------------------------------------------------------------- schema
def from_live(history: pd.DataFrame, run: str) -> pd.DataFrame:
    """live.yml history.csv.gz rows -> ingestion schema."""
    h = history
    bus = h["mode"].astype(str) == "bus"
    direction = np.where(bus, "pid:" + h.get("pid", pd.Series("", index=h.index)).astype(str),
                         "trDr:" + h.get("train_dir", pd.Series("", index=h.index)).astype(str))
    vid = h["id"].astype(str).str.split(":").str[-1]
    return pd.DataFrame({
        "source": np.where(bus, "cta-bustracker", "cta-traintracker"), "mode": h["mode"].astype(str),
        "route": h["route"].astype(str), "direction": direction,
        "vehicle_id": np.where(bus, vid, h["id"].astype(str).str.replace("train:", "", regex=False)),
        "timestamp_utc": h["t_utc"].astype(str), "poll_utc": h["poll_utc"].astype(str),
        "lat": pd.to_numeric(h["lat"], errors="coerce").round(5), "lon": pd.to_numeric(h["lon"], errors="coerce").round(5),
        "delay_flag": h["dly"].astype(str).str.lower().isin(["true", "1"]).astype(int), "run": str(run)})


def normalise(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Fill the optional fields, drop rows failing the schema; returns (rows, counts)."""
    from simchi.transit.live import SERVICE_BOX
    df = df.copy()
    for c in SCHEMA:
        if c not in df:
            df[c] = np.nan
    ts = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    poll = pd.to_datetime(df["poll_utc"], utc=True, errors="coerce")
    poll = poll.fillna(ts.dt.floor("min"))
    lat, lon = pd.to_numeric(df["lat"], errors="coerce"), pd.to_numeric(df["lon"], errors="coerce")
    ok = (df["route"].notna() & (df["route"].astype(str) != "") & df["vehicle_id"].notna() & ts.notna() & poll.notna()
          & lat.between(*SERVICE_BOX["lat"]) & lon.between(*SERVICE_BOX["lon"]) & df["mode"].isin(["bus", "train"]))
    out = df[ok].copy()
    out["timestamp_utc"] = ts[ok].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out["poll_utc"] = poll[ok].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_missing = out["run"].isna() | (out["run"].astype(str).isin(["", "nan"]))
    out.loc[run_missing, "run"] = out.loc[run_missing, "source"].astype(str) + ":" + poll[ok][run_missing].dt.strftime("%Y-%m-%dT%H")
    out = out.drop_duplicates(["source", "vehicle_id", "poll_utc"])
    return out[SCHEMA].reset_index(drop=True), {"rows_in": int(len(df)), "rows_kept": int(len(out)), "rows_dropped": int((~ok).sum())}


def to_reliability_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Ingestion schema -> the frame simchi.transit.reliability.positions expects."""
    from simchi.transit.reliability import CHICAGO
    d = df.copy()
    d["id"] = d["source"].astype(str) + ":" + d["vehicle_id"].astype(str)
    dirc = d["direction"].astype(str)
    d["pid"] = np.where(dirc.str.startswith("pid:"), dirc.str[4:], dirc)
    d["train_dir"] = np.where(dirc.str.startswith("trDr:"), dirc.str[5:], dirc)
    d["dly"] = d["delay_flag"].astype(str).isin(["1", "True", "true", "1.0"])
    d["lat"], d["lon"] = d["lat"].astype(float), d["lon"].astype(float)
    d["poll"] = pd.to_datetime(d["poll_utc"], utc=True)
    loc = d["poll"].dt.tz_convert(CHICAGO)
    d["hour"] = loc.dt.hour
    wd = loc.dt.weekday
    d["day"] = np.where(wd < 5, "weekday", np.where(wd == 5, "saturday", "sunday"))
    d["date"] = loc.dt.date.astype(str)
    return d


# ----------------------------------------------------------------------------- daily build
def build_day(history_paths, date: str) -> tuple[pd.DataFrame, dict]:
    """All live.yml history files -> the date's rows (UTC date of poll) in the schema."""
    frames = []
    for p in history_paths:
        p = Path(p)
        with gzip.open(p, "rt") as f:
            h = pd.read_csv(f, dtype={"route": str, "id": str, "pid": str, "train_dir": str})
        if len(h):
            frames.append(from_live(h, p.parent.name.replace("vehicles-", "")))
    if not frames:
        return pd.DataFrame(columns=SCHEMA), {"rows_in": 0, "rows_kept": 0, "rows_dropped": 0}
    df, counts = normalise(pd.concat(frames, ignore_index=True))
    df = df[df["poll_utc"].str[:10] == date].reset_index(drop=True)
    counts["rows_on_date"] = int(len(df))
    return df, counts


def daily_stats(df: pd.DataFrame, sched=None, frame=None) -> pd.DataFrame:
    """Sufficient statistics of one day's rows (schema) per cell and date, plus system polls."""
    from simchi.transit import reliability as RL
    if df.empty:
        return pd.DataFrame()
    if sched is None:
        sched = RL.Schedule()
    if frame is None:
        from simchi.data.cds import load_cds
        frame = load_cds().frame
    R = to_reliability_frame(df)
    sys_polls = R.groupby(["mode", "day", "hour", "date"])["poll"].nunique().rename("polls").reset_index()
    sys_polls.insert(0, "kind", "polls")
    P = RL.positions(R, sched, frame)
    if P.empty:
        return sys_polls
    H = RL.headways(P, sched)
    per_poll = P.groupby(CELL + ["date", "poll"]).size().rename("n").reset_index()
    cell = per_poll.groupby(CELL + ["date"]).agg(polls_seen=("poll", "nunique"), veh_sum=("n", "sum")).reset_index()
    ob = P.groupby(CELL + ["date"]).agg(obs=("dly", "size"), dly=("dly", "sum")).reset_index()
    cell = cell.merge(ob, on=CELL + ["date"], how="left")
    if len(H):
        H = H.assign(date=pd.to_datetime(H["poll"], utc=True).dt.tz_convert(RL.CHICAGO).dt.date.astype(str),
                     bunch=H["headway_min"] < RL.BUNCH * H["scheduled_headway_min"],
                     gap=H["headway_min"] > RL.GAP * H["scheduled_headway_min"], sq=H["headway_min"] ** 2)
        hs = H.groupby(CELL + ["date"]).agg(h_n=("headway_min", "size"), h_sum=("headway_min", "sum"), h_sumsq=("sq", "sum"),
                                            n_bunch=("bunch", "sum"), n_gap=("gap", "sum")).reset_index()
        cell = cell.merge(hs, on=CELL + ["date"], how="left")
    for c in ("h_n", "h_sum", "h_sumsq", "n_bunch", "n_gap"):
        if c not in cell:
            cell[c] = 0
        cell[c] = cell[c].fillna(0)
    cell.insert(0, "kind", "cell")
    return pd.concat([cell, sys_polls], ignore_index=True)


def daily_traversals(df: pd.DataFrame, sched=None, frame=None) -> pd.DataFrame:
    """Derived W3 input: bus segment run times of the day (route, direction, segment, hour, run time;
    no vehicle id or position). Stops, signals and lengths are joined by segment at estimation."""
    from simchi.transit import reliability as RL
    from simchi.transit import stop_time as W
    cols = ["route", "direction", "seg", "hour", "run_time_s", "date"]
    b = df[df["mode"] == "bus"]
    if b.empty:
        return pd.DataFrame(columns=cols)
    if sched is None:
        sched = RL.Schedule()
    if frame is None:
        from simchi.data.cds import load_cds
        frame = load_cds().frame
    shapes = W.representative_shapes()
    segs = W.segments(shapes, {}, np.zeros((0, 2)))
    P = RL.positions(to_reliability_frame(b), sched, frame)
    T = W.traversals(P, segs, shapes)
    if T.empty:
        return pd.DataFrame(columns=cols)
    T["date"] = str(pd.to_datetime(b["poll_utc"].iloc[0], utc=True).date())
    T["run_time_s"] = T["run_time_s"].round(1)
    return T[cols]


# ----------------------------------------------------------------------------- aggregate
def aggregate(stats: pd.DataFrame, sched=None, fn: dict | None = None) -> dict:
    """Archive-wide metrics, eligibility and the Frequent Network check from daily statistics."""
    from simchi.transit import reliability as RL
    if stats is None or stats.empty:
        return {"minimum_reached": False, "reason": "no archived days yet", "weeks_observed": 0}
    sched = sched or RL.Schedule()
    polls = stats[stats["kind"] == "polls"]
    cells = stats[stats["kind"] == "cell"].copy()
    dates = sorted(polls["date"].unique())
    span = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days + 1 if dates else 0
    per_day = polls.drop_duplicates(["date"])[["date", "day"]].groupby("day")["date"].nunique().to_dict()
    minimum = span >= MIN_SPAN_DAYS and all(per_day.get(d, 0) >= MIN_DATES_PER_DAYTYPE for d in ("weekday", "saturday", "sunday"))
    out = {"archive_dates": [dates[0], dates[-1]] if dates else [], "span_days": int(span), "dates_by_day_type": per_day,
           "weeks_observed": round(span / 7, 1), "minimum_reached": bool(minimum),
           "minimum_rule": f">= {MIN_SPAN_DAYS} days and >= {MIN_DATES_PER_DAYTYPE} dates of each day type"}
    if not minimum:
        out["reason"] = (f"{span} of {MIN_SPAN_DAYS} days; dates per day type "
                         f"{ {d: per_day.get(d, 0) for d in ('weekday', 'saturday', 'sunday')} } (need {MIN_DATES_PER_DAYTYPE})")
    # system polls and expected polls per (mode, day, hour)
    sp = polls.groupby(["mode", "day", "hour"]).agg(polls=("polls", "sum"), poll_dates=("date", "nunique")).reset_index()
    sp["expected"] = [EXPECTED_POLLS_PER_HOUR * per_day.get(d, 0) for d in sp["day"]]
    sp["coverage"] = sp["polls"] / sp["expected"].where(sp["expected"] > 0)
    g = cells.groupby(CELL).agg(veh_sum=("veh_sum", "sum"), obs=("obs", "sum"), dly=("dly", "sum"), h_n=("h_n", "sum"),
                                h_sum=("h_sum", "sum"), h_sumsq=("h_sumsq", "sum"), n_bunch=("n_bunch", "sum"),
                                n_gap=("n_gap", "sum")).reset_index()
    hd = cells[cells["h_n"] > 0].groupby(CELL)["date"].nunique().rename("headway_dates")
    g = g.merge(hd, on=CELL, how="left").merge(sp[["mode", "day", "hour", "polls", "coverage"]], on=["mode", "day", "hour"], how="left")
    g["headway_dates"] = g["headway_dates"].fillna(0).astype(int)
    g["vehicles_per_poll"] = g["veh_sum"] / g["polls"]
    g["scheduled_in_service"] = [sched.in_service(r, d, day, h) for r, d, day, h in zip(g["route"], g["direction"], g["day"], g["hour"], strict=True)]
    g["scheduled_headway_min"] = [sched.headway(r, d, day, h) for r, d, day, h in zip(g["route"], g["direction"], g["day"], g["hour"], strict=True)]
    g["service_delivered"] = g["vehicles_per_poll"] / g["scheduled_in_service"]
    mean = g["h_sum"] / g["h_n"].where(g["h_n"] > 0)
    var = (g["h_sumsq"] / g["h_n"].where(g["h_n"] > 0) - mean ** 2).clip(lower=0)
    g["headway_mean_min"] = mean
    g["headway_cv"] = np.sqrt(var) / mean
    g["bunching_share"] = g["n_bunch"] / g["h_n"].where(g["h_n"] > 0)
    g["gap_share_lower_bound"] = g["n_gap"] / g["h_n"].where(g["h_n"] > 0)
    g["delayed_share"] = g["dly"] / g["obs"].where(g["obs"] > 0)
    g["eligible"] = (g["coverage"] >= CELL_MIN_COVERAGE) & (g["headway_dates"] >= CELL_MIN_DATES) & (g["h_n"] >= CELL_MIN_HEADWAYS)
    out["cells"] = int(len(g))
    out["cells_eligible"] = int(g["eligible"].sum())
    out["coverage_by_hour"] = sp.to_dict("records")
    out["_cells"] = g
    if minimum:
        E = g[g["eligible"]]
        out["system"] = {m: {k: float(np.nanmedian(x[k])) for k in ("service_delivered", "headway_cv", "bunching_share", "gap_share_lower_bound", "delayed_share")}
                         for m, x in E.groupby("mode")}
    out["frequent_network"] = frequent_network_check(g, cells, fn) if fn else None
    return out


def frequent_network_check(g: pd.DataFrame, cells: pd.DataFrame, fn: dict) -> dict:
    """Eligible Frequent Network cells in the windows, using only dates on or after effective_by."""
    std = fn["standard"]
    eff = {r: p["effective_by"] for p in fn["phase"] for r in p["routes"]}
    win = {"weekday": std["weekday_window"], "saturday": std["weekend_window"], "sunday": std["weekend_window"]}
    c = cells[cells["route"].isin(eff)].copy()
    c = c.loc[np.array([d >= eff[r] for r, d in zip(c["route"], c["date"], strict=True)], dtype=bool)]
    c = c.loc[np.array([win[day][0] <= h < win[day][1] for day, h in zip(c["day"], c["hour"], strict=True)], dtype=bool)]
    if c.empty:
        return {"route_hours": [], "eligible": 0, "note": "no archived observations of Frequent Network routes in the windows"}
    a = c.groupby(CELL).agg(h_n=("h_n", "sum"), h_sum=("h_sum", "sum")).reset_index()
    hd = c[c["h_n"] > 0].groupby(CELL)["date"].nunique().rename("headway_dates")
    a = a.merge(hd, on=CELL, how="left").merge(g[CELL + ["coverage"]], on=CELL, how="left")
    a["headway_dates"] = a["headway_dates"].fillna(0)
    a["headway_mean_min"] = a["h_sum"] / a["h_n"].where(a["h_n"] > 0)
    a["eligible"] = (a["coverage"] >= CELL_MIN_COVERAGE) & (a["headway_dates"] >= CELL_MIN_DATES) & (a["h_n"] >= CELL_MIN_HEADWAYS)
    a["meets"] = a["headway_mean_min"] <= std["headway_max_min"]
    E = a[a["eligible"]]
    per_route = {r: {"cells": int(len(x)), "meeting": int(x["meets"].sum())} for r, x in E.groupby("route")}
    return {"eligible": int(len(E)), "excluded": int((~a["eligible"]).sum()),
            "share_meeting": float(E["meets"].mean()) if len(E) else None, "per_route": per_route,
            "route_hours": [{"route": r.route, "direction": int(r.direction), "day": r.day, "hour": int(r.hour),
                             "headway_mean_min": float(r.headway_mean_min), "meets": bool(r.meets)} for r in E.itertuples()],
            "note": "polling undercounts gaps, so the share meeting the standard is an upper bound on compliance"}


def load_stats(paths) -> pd.DataFrame:
    frames = [pd.read_csv(p, dtype={"route": str, "date": str}) for p in paths]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_report(res: dict, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    g = res.pop("_cells", None)
    if g is not None and res.get("minimum_reached"):
        g.to_csv(out_dir / "archive_cells.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    fnr = res.get("frequent_network") or {}
    fn_out = {"minimum_reached": res.get("minimum_reached", False), "reason": res.get("reason"),
              "weeks_observed": res.get("weeks_observed"), **({"route_hours": fnr.get("route_hours", []), "share_meeting": fnr.get("share_meeting"),
                                                                "eligible": fnr.get("eligible"), "excluded": fnr.get("excluded"),
                                                                "per_route": fnr.get("per_route"), "note": fnr.get("note")} if res.get("minimum_reached") else {})}
    (out_dir / "frequent_network.json").write_text(json.dumps(fn_out, indent=1, default=str))
    keep = {k: v for k, v in res.items() if k != "frequent_network"}
    if not res.get("minimum_reached"):
        keep.pop("system", None)
    (out_dir / "archive_summary.json").write_text(json.dumps(keep, indent=1, default=str))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="one UTC date's vehicles and stats files from live.yml artifacts")
    b.add_argument("--date", required=True)
    b.add_argument("--artifacts", required=True, help="directory with vehicles-<run id>/history.csv.gz")
    b.add_argument("--out", required=True)
    a = sub.add_parser("aggregate", help="archive-wide metrics from stats-*.csv.gz")
    a.add_argument("--stats", required=True)
    a.add_argument("--out", default=str(REPORTS / "reliability"))
    x = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if x.cmd == "build":
        paths = sorted(Path(x.artifacts).glob("*/history.csv.gz"))
        df, counts = build_day(paths, x.date)
        out = Path(x.out)
        out.mkdir(parents=True, exist_ok=True)
        vf = out / f"vehicles-{x.date}.csv.gz"
        df.to_csv(vf, index=False, compression={"method": "gzip", "mtime": 0})
        if vf.stat().st_size > SIZE_CAP_BYTES:          # cap applies whether or not the raw file is published
            vf.unlink()
            sys.exit(f"vehicles-{x.date}.csv.gz exceeds the {SIZE_CAP_BYTES // 2**20} MB cap; not written")
        daily_stats(df).to_csv(out / f"stats-{x.date}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
        daily_traversals(df).to_csv(out / f"traversals-{x.date}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
        print("ARCHIVE", x.date, json.dumps(counts))
    else:
        fn = tomllib.loads((DATA / "frequent_network.toml").read_text())
        res = aggregate(load_stats(sorted(Path(x.stats).glob("stats-*.csv.gz"))), fn=fn)
        write_report(res, Path(x.out))
        print(json.dumps({k: res.get(k) for k in ("archive_dates", "span_days", "dates_by_day_type", "minimum_reached", "reason", "cells", "cells_eligible")}, default=str))


if __name__ == "__main__":
    main()
