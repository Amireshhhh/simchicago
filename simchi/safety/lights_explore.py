"""W9 exploratory lane (2018-2023 only; simchi.lanes explore): which 311 request types are street
and alley light outages, how crime location descriptions split indoor/outdoor, and a first look
at outage windows. Outputs go to reports/explore/ (labelled exploratory; never public or briefed).
"""

from __future__ import annotations

import io
import json
import sys
import urllib.parse

import pandas as pd

from simchi.lanes import Lane

MOD = "simchi.safety.lights_explore"


def _soda(portal, dataset, params):
    raw = portal._get(f"https://data.cityofchicago.org/resource/{dataset}.csv?{urllib.parse.urlencode(params)}")
    return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)


def light_types(portal, lane):
    def fetch(start, end):
        df = _soda(portal, "v6vf-nfxy", {"$select": "sr_type, count(*) AS n, max(created_date) AS last_date",
                                         "$where": f"created_date >= '{start}T00:00:00' AND created_date <= '{end}T23:59:59' AND upper(sr_type) like '%LIGHT%'",
                                         "$group": "sr_type", "$order": "n DESC", "$limit": 1000})
        return df
    return lane.read("v6vf-nfxy", "last_date", "2018-01-01", "2023-12-31", fetch)


def location_descriptions(portal, lane):
    def fetch(start, end):
        return _soda(portal, "ijzp-q8t2", {"$select": "location_description, count(*) AS n, max(date) AS last_date",
                                           "$where": f"date >= '{start}T00:00:00' AND date <= '{end}T23:59:59'",
                                           "$group": "location_description", "$order": "n DESC", "$limit": 5000})
    return lane.read("ijzp-q8t2", "last_date", "2018-01-01", "2023-12-31", fetch)


def fetch_period(portal, lane, start="2018-01-01", end="2023-12-31"):
    """311 outage requests and crimes of the explore period, through the explore lane."""
    from simchi.safety.lights import OUTAGE_TYPES
    types = ", ".join(f"'{t}'" for t in OUTAGE_TYPES)
    req = lane.read("v6vf-nfxy", "created_date", start, end, lambda a, b: monthly(portal, "v6vf-nfxy", "created_date", a, b,
        "sr_type, status, created_date, closed_date, latitude, longitude", f"sr_type in ({types})"))
    cr = lane.read("ijzp-q8t2", "date", start, end, lambda a, b: monthly(portal, "ijzp-q8t2", "date", a, b,
        "date, latitude, longitude, primary_type, location_description", None))
    return req, cr


def monthly(portal, dataset, col, start, end, select, extra):
    """One query per calendar month (large datasets time out when paged deep with offsets)."""
    parts = []
    for m0 in pd.date_range(pd.Timestamp(start).replace(day=1), end, freq="MS"):
        a = max(m0, pd.Timestamp(start))
        b = min(m0 + pd.offsets.MonthEnd(0), pd.Timestamp(end))
        w = f"{col} >= '{a:%Y-%m-%d}T00:00:00' AND {col} <= '{b:%Y-%m-%d}T23:59:59'" + (f" AND {extra}" if extra else "")
        parts.append(portal.query(dataset, select=select, where=w))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def build_mirror(req, cr, tag: str):
    """Per-block aggregates (no individual records): outage windows and crime counts on blocks that
    had an outage. Written to data/raw/mirror/w9/<tag>_*.csv.gz."""
    import hashlib

    from simchi.safety import lights as LG
    from simchi.safety.mirror import load_sites
    sites, _ = load_sites()
    req = req[req["status"].astype(str).str.lower() == "completed"].copy()
    req["block"] = LG.snap_segments(sites, req["longitude"], req["latitude"])
    W = LG.outage_windows(req)
    cr = cr.copy()
    cr["block"] = LG.snap_segments(sites, cr["longitude"], cr["latitude"])
    blocks = set(W["block"])
    A = LG.crime_aggregate(cr[cr["block"].isin(blocks)], LG.location_map())
    LG.W9.mkdir(parents=True, exist_ok=True)
    W.assign(start=W["start"].dt.strftime("%Y-%m-%d"), end=W["end"].dt.strftime("%Y-%m-%d")).to_csv(
        LG.W9 / f"{tag}_outage_windows.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    A.to_csv(LG.W9 / f"{tag}_crime_blocks.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    summ = {"requests": int(len(req)), "requests_unsnapped": int(req["block"].isna().sum()), "windows": int(len(W)),
            "outage_blocks": int(len(blocks)), "crimes": int(len(cr)), "crimes_unsnapped": int(cr["block"].isna().sum()),
            "crimes_on_outage_blocks": int(cr["block"].isin(blocks).sum())}
    return W, A, summ


def main(argv=None):
    from simchi.portal.client import Portal
    portal, lane = Portal(), Lane("explore", MOD)
    if "--analyse" in (argv or []):
        from simchi.safety import lights as LG
        req, cr = fetch_period(portal, lane)
        W, A, summ = build_mirror(req, cr, "explore")
        W["start"], W["end"] = pd.to_datetime(W["start"]), pd.to_datetime(W["end"])
        dur = (W["end"] - W["start"]).dt.days
        Q = LG.panel(W, A)
        res = LG.did(Q) if len(Q) else {}
        lane.output("w9_explore.json", {"period": ["2018-01-01", "2023-12-31"], "mirror": summ,
                                        "window_days": {q: float(dur.quantile(q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
                                        "did": res})
        print(json.dumps({"mirror": summ, "window_days_median": float(dur.median()), "did": res}, indent=1, default=float))
        return
    lt = light_types(portal, lane)
    ld = location_descriptions(portal, lane)
    lane.output("w9_light_types.json", {"period": ["2018-01-01", "2023-12-31"], "sr_types": lt.to_dict("records")})
    lane.output("w9_location_descriptions.json", {"period": ["2018-01-01", "2023-12-31"], "values": ld.to_dict("records")})
    print(lt.to_string()); print(len(ld), "location descriptions"); print(ld.head(80).to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
