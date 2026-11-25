"""Promised vs delivered: public commitments and their computed status
(python -m simchi.commitments -> reports/commitments/status.json).

PRE-REGISTERED STATUS RULES, W5 (committed as "W5 pre-registration" before any status was computed)

Commitments live in data/commitments.toml: id, agency, the commitment as published (quote),
source URL, metric, how it is measured, and the dataset or report it is measured from. A status
is never typed into that file; this module computes it with the rule named by the commitment's
`rule`, and writes the inputs it used next to the result.

Statuses: "met", "not met", "missed", "on track", "insufficient data", "not measurable".

Rules
  frequent_scheduled   CTA's scheduled service (GTFS extract data/transit/service.json, its
      reference weekday, Saturday and Sunday) for the Frequent Network routes in the network by the
      feed's reference date (data/frequent_network.toml, effective_by). Unit: route x direction x
      day type x hour inside the window (weekdays 6-20 h start hours, weekends 9-20 h). A unit
      meets the standard if its scheduled trips that hour are >= 60 / headway_max (6 trips for 10
      min). Status "met" if every unit meets it, else "not met"; the share of units meeting it is
      reported either way. Trips are counted by the hour of first departure of each trip.
  frequent_delivered   Delivered service from the polling archive (W2 report
      reports/reliability/frequent_network.json). "insufficient data" until that report says its
      pre-registered minimum (8 weeks, per-route coverage threshold) is reached; then "met" if
      every eligible route-hour's observed headway meets the standard, else "not met", with the
      share reported.
  zero_by_year         A goal of zero (deaths or serious injuries) in a target year. Count in the
      target year so far from the named dataset. Count > 0: "missed" (a later month cannot undo it;
      the year-to-date count and the last date in the data are reported). Count = 0 and the year is
      complete in the data: "met"; count = 0 and the year is not complete: "on track".
  reduction_vs_baseline  A percentage reduction by a year. Needs a baseline year stated in the
      source; if the source states none, "not measurable" (no baseline is chosen here). With a
      baseline: "met" if the target-year count <= (1 - reduction) x baseline count, else "not met".
  needs_unmirrored_data  The commitment's metric needs data not in this repository (named in
      `missing`): "not measurable" until it is mirrored.

Every status carries the date it was computed (last checked). Corrections to commitments (a
quote, a source, a rule) are appended to the [[correction]] log in data/commitments.toml with a
date and reason, and shown in the viewer; past entries are never edited.
"""

from __future__ import annotations  # noqa: E402  (after the pre-registration docstring)

import json
import sys
import tomllib
from datetime import datetime, timezone

from simchi.paths import DATA, REPORTS

COMMITMENTS = DATA / "commitments.toml"
FREQUENT = DATA / "frequent_network.toml"
OUT = REPORTS / "commitments" / "status.json"


def load(path=COMMITMENTS) -> dict:
    return tomllib.loads(path.read_text())


def frequent_routes(fn: dict, on: str) -> list:
    """Frequent Network routes in the network by date `on` (YYYY-MM-DD), by effective_by."""
    return sorted(r for p in fn["phase"] if p["effective_by"] <= on for r in p["routes"])


def frequent_scheduled(service: list, fn: dict, reference_dates: dict) -> dict:
    """Rule frequent_scheduled: service rows {route, direction, day, hour, trips}."""
    std = fn["standard"]
    need = 60.0 / std["headway_max_min"]
    windows = {"weekday": std["weekday_window"], "saturday": std["weekend_window"], "sunday": std["weekend_window"]}
    trips = {(r["route"], r["direction"], r["day"], r["hour"]): r["trips"] for r in service}
    units, per_route = [], {}
    for day, (h0, h1) in windows.items():
        routes = frequent_routes(fn, reference_dates[day])
        for route in routes:
            dirs = sorted({d for (r, d, dd, _h) in trips if r == route and dd == day})
            for d in dirs or [None]:
                for h in range(h0, h1):
                    n = trips.get((route, d, day, h), 0)
                    ok = n >= need - 1e-9
                    units.append(ok)
                    pr = per_route.setdefault(route, [0, 0])
                    pr[0] += ok
                    pr[1] += 1
    share = sum(units) / len(units) if units else None
    return {"status": ("met" if units and all(units) else "not met") if units else "insufficient data",
            "share_meeting": share, "units": len(units), "units_meeting": int(sum(units)),
            "routes_short": {r: {"meeting": m, "units": n} for r, (m, n) in sorted(per_route.items()) if m < n},
            "routes_checked": sorted(per_route), "reference_dates": reference_dates, "trips_needed_per_hour": need}


def frequent_delivered(report: dict | None) -> dict:
    """Rule frequent_delivered, from the W2 report (or None if it does not exist yet)."""
    if not report or not report.get("minimum_reached"):
        return {"status": "insufficient data", "reason": (report or {}).get("reason", "no polling-archive report yet (W2)"),
                "weeks_observed": (report or {}).get("weeks_observed")}
    units = report["route_hours"]
    ok = [u["meets"] for u in units]
    return {"status": "met" if all(ok) else "not met", "share_meeting": sum(ok) / len(ok), "units": len(ok)}


def zero_by_year(count: float, last_date: str, target_year: int) -> dict:
    complete = last_date >= f"{target_year}-12-31"
    if count > 0:
        st = "missed"
    else:
        st = "met" if complete else "on track"
    return {"status": st, "count": count, "year_complete_in_data": complete, "data_through": last_date}


def reduction_vs_baseline(c: dict, counts: dict | None = None) -> dict:
    if not str(c.get("baseline_year", "")).strip():
        return {"status": "not measurable", "reason": "the source states no baseline year; none is chosen here"}
    b, t = counts[int(c["baseline_year"])], counts[int(c["target_year"])]
    return {"status": "met" if t <= (1 - c["reduction"]) * b else "not met", "baseline": b, "target_year_count": t}


def needs_unmirrored_data(c: dict) -> dict:
    return {"status": "not measurable", "reason": f"needs data not in this repository: {c['missing']}"}


def _portal_count(portal, c) -> tuple[float, str]:
    y = int(c["target_year"])
    f = c["date_field"]
    where = f"{f} >= '{y}-01-01T00:00:00' AND {f} <= '{y}-12-31T23:59:59'"
    import io

    import pandas as pd
    raw = portal._get(portal._url(c["dataset"], {"$select": f"{c['count']} AS n, max({f}) AS last", "$where": where}))   # one aggregate row
    df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    n = float(df["n"].iloc[0]) if len(df) and str(df["n"].iloc[0]) not in ("", "nan") else 0.0
    last = str(df["last"].iloc[0])[:10] if len(df) else ""
    return n, last


def compute(portal=None, today: str | None = None) -> dict:
    from simchi.transit.gtfs import load_extract
    C = load()
    fn = load(FREQUENT)
    today = today or datetime.now(timezone.utc).date().isoformat()
    w2 = REPORTS / "reliability" / "frequent_network.json"
    rows = []
    for c in C["commitment"]:
        r = c["rule"]
        if r == "frequent_scheduled":
            res = frequent_scheduled(load_extract("service"), fn, load_extract("meta")["reference_dates"])
        elif r == "frequent_delivered":
            res = frequent_delivered(json.loads(w2.read_text()) if w2.exists() else None)
        elif r == "zero_by_year":
            if portal is None:
                from simchi.portal.client import Portal
                portal = Portal()
            n, last = _portal_count(portal, c)
            res = zero_by_year(n, last, int(c["target_year"]))
            res["query"] = {"dataset": c["dataset"], "count": c["count"], "year": c["target_year"]}
        elif r == "reduction_vs_baseline":
            res = reduction_vs_baseline(c)
        elif r == "needs_unmirrored_data":
            res = needs_unmirrored_data(c)
        else:
            raise ValueError(f"unknown rule {r}")
        rows.append({**{k: c[k] for k in ("id", "agency", "quote", "source", "metric", "measured", "measured_from", "rule")},
                     "source_title": c.get("source_title", ""), **res, "last_checked": today})
    return {"generated": today, "rules": "docstring of simchi/commitments.py (W5 pre-registration)",
            "commitments": rows, "corrections": C.get("correction", [])}


def main(argv=None):
    out = compute()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    for r in out["commitments"]:
        extra = f" share {r['share_meeting']:.3f}" if isinstance(r.get("share_meeting"), float) else (f" count {r['count']:.0f} (data through {r['data_through']})" if "count" in r else "")
        print(f"{r['status']:>17}  {r['id']}{extra}")


if __name__ == "__main__":
    main(sys.argv[1:])
