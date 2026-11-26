"""Service day types and per-date schedules from a GTFS feed (rules: W2 amendment 1 in the
docstring of simchi/transit/archive.py).

    python -m simchi.transit.calendar <google_transit.zip>   # writes data/transit/calendar.json

data/transit/calendar.json holds the day type of every date the pinned feed covers, with the
feed's sha256; simchi.transit.reliability and the archive use it when no feed is given.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

from simchi.transit.gtfs import TRANSIT, _trip_table, active_services, sha256_file

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
REGULAR = ("weekday", "saturday", "sunday")


def weekday_class(d: date) -> str:
    return "weekday" if d.weekday() < 5 else ("saturday" if d.weekday() == 5 else "sunday")


def regular_services(feed, d: date) -> frozenset:
    cal = feed["calendar"]
    ymd = d.strftime("%Y%m%d")
    return frozenset(cal[(cal[WEEKDAYS[d.weekday()]] == "1") & (cal["start_date"] <= ymd) & (cal["end_date"] >= ymd)]["service_id"])


def day_type(feed, d: date) -> str:
    actual = frozenset(active_services(feed, d))
    if not actual:
        return "unknown"
    if actual == regular_services(feed, d):
        return weekday_class(d)
    for want in ("sunday", "saturday", "weekday"):
        for k in range(-7, 8):
            s = d + timedelta(days=k)
            if k != 0 and weekday_class(s) == want and actual == regular_services(feed, s):
                return want
    return "holiday"


def day_types(feed, first: date, last: date) -> dict:
    out, d = {}, first
    while d <= last:
        out[d.isoformat()] = day_type(feed, d)
        d += timedelta(days=1)
    return out


def date_schedule(feed, d: date) -> pd.DataFrame:
    """Scheduled trips and vehicles in service per route, direction and hour of first departure for
    the trips active on date d (hours >= 24 belong to the service day, as in the GTFS extract)."""
    t = _trip_table(feed, d)
    if t.empty:
        return pd.DataFrame(columns=["route", "direction", "hour", "trips", "in_service"])
    t = t.assign(hour=(t["t0"] // 3600).astype(int), dur=t["offsets"].map(lambda o: o[-1] / 60.0 if len(o) else np.nan),
                 direction=t["direction_id"].astype(int))
    g = t.groupby(["route_id", "direction", "hour"]).agg(trips=("t0", "size"), dur=("dur", "median")).reset_index()
    g["in_service"] = g["trips"] * g["dur"] / 60.0
    return g.rename(columns={"route_id": "route"})[["route", "direction", "hour", "trips", "in_service"]]


def feed_range(feed) -> tuple[date, date]:
    cal = feed["calendar"]
    days = list(cal["start_date"]) + list(cal["end_date"])
    if "calendar_dates" in feed.tables and len(feed["calendar_dates"]):
        days += list(feed["calendar_dates"]["date"])
    p = lambda s: date(int(s[:4]), int(s[4:6]), int(s[6:]))  # noqa: E731
    return p(min(days)), p(max(days))


def load_table() -> dict:
    p = TRANSIT / "calendar.json"
    return json.loads(p.read_text()) if p.exists() else {"dates": {}}


def main(argv=None):
    from simchi.transit.gtfs import read_feed
    path = (sys.argv[1:] if argv is None else argv)[0]
    feed = read_feed(path)
    a, b = feed_range(feed)
    tab = {"feed_sha256": sha256_file(path), "rule": "W2 amendment 1 (simchi/transit/archive.py)", "first": a.isoformat(), "last": b.isoformat(),
           "dates": day_types(feed, a, b)}
    (TRANSIT / "calendar.json").write_text(json.dumps(tab, indent=0))
    print({k: v for k, v in tab.items() if k != "dates"}, {t: sum(1 for x in tab["dates"].values() if x == t) for t in set(tab["dates"].values())})


if __name__ == "__main__":
    main()
