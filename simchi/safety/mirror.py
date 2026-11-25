"""Mirror the W4 safety data as aggregates (python -m simchi.safety.mirror).

Downloads through simchi.portal.client (raw rows are cached outside the repository, in the
portal client's cache directory), snaps points to the sites of simchi.safety.sites and writes only
aggregates to data/raw/mirror/safety/:

  site_year.csv.gz          site, year, crashes, injury_crashes, a_crashes (incapacitating, no
                            fatal), k_crashes_cpd (crash table, injuries_fatal >= 1),
                            ped_bike_ka (people: pedestrian/cyclist killed or incapacitated)
  vz_site_year.csv.gz       site, year, deaths, fatal_crashes (Vision Zero, the official count;
                            deaths with the same minute and site are one crash)
  radial_month.csv.gz       point, month, crashes, ka_crashes: crash-table crashes within 201.2 m
                            (660 ft) of each camera and each comparison-pool intersection
                            (rows with no crash are omitted)
  comparison_pool.csv.gz    site: the comparison-pool intersections (W4 design, CAMERA SLICE)
  cameras.csv.gz            kind, camera, address, lon, lat, go_live
  violations_month.csv.gz   kind, camera, month, violations (context only)
  site_adt.csv.gz           site, adt (mean daily vehicles over counted days before 2025-01-01,
                            directions summed), counted_days
  summary.json              row counts, unsnapped and expressway tallies, query strings, dates

No person-level record is stored: people and Vision Zero rows are reduced to counts per site.
"""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from simchi.paths import DATA, MIRROR
from simchi.safety.sites import build_sites

OUT = MIRROR / "safety"
START, END = "2018-01-01", "2025-12-31"
RADIUS_M = 201.168          # 660 ft
POOL_EXCLUSION_M = 804.672  # 1/2 mile

Q = {
    "crashes": dict(id="85ca-t3if", select="crash_record_id, crash_date, latitude, longitude, injuries_fatal, injuries_incapacitating, injuries_total",
                    where=f"crash_date >= '{START}T00:00:00' AND crash_date <= '{END}T23:59:59'"),
    "people": dict(id="u6pd-qa9d", select="crash_record_id, person_type, injury_classification, count(*) AS n",
                   where=f"crash_date >= '{START}T00:00:00' AND crash_date <= '{END}T23:59:59' AND injury_classification in ('FATAL', 'INCAPACITATING INJURY')",
                   group="crash_record_id, person_type, injury_classification", order="crash_record_id, person_type, injury_classification"),
    "vision_zero": dict(id="gzaz-isa6", select="crash_date, latitude, longitude, victim",
                        where=f"crash_date >= '{START}T00:00:00' AND crash_date <= '{END}T23:59:59'"),
    "speed_cameras": dict(id="4i42-qv3h", select="id, address, go_live_date, latitude, longitude", where=None),
    "red_light_cameras": dict(id="thvf-6diy", select="intersection, go_live_date, latitude, longitude", where=None),
    "speed_violations": dict(id="hhkd-xvj4", select="camera_id, date_trunc_ym(violation_date) AS month, sum(violations) AS violations",
                             where=f"violation_date >= '{START}T00:00:00' AND violation_date <= '{END}T23:59:59'",
                             group="camera_id, month", order="camera_id, month"),
    "red_light_violations": dict(id="spqx-js37", select="camera_id, intersection, date_trunc_ym(violation_date) AS month, sum(violations) AS violations",
                                 where=f"violation_date >= '{START}T00:00:00' AND violation_date <= '{END}T23:59:59'",
                                 group="camera_id, intersection, month", order="camera_id, intersection, month"),
    "adt": dict(id="gc7y-n4xa", select="segmentid, direction, midpointlat, midpointlon, avg(vehiclecount) AS mean_count, count(*) AS days",
                where="timestamp < '2025-01-01T00:00:00'", group="segmentid, direction, midpointlat, midpointlon",
                order="segmentid, direction, midpointlat, midpointlon"),
}


BY_YEAR = {"crashes", "people"}          # large: one cached query per year, so an interrupted run resumes


def fetch(portal, key):
    q = Q[key]
    if key not in BY_YEAR:
        return portal.query(q["id"], select=q["select"], where=q.get("where"), group=q.get("group"), order=q.get("order"))
    parts = []
    for y in range(int(START[:4]), int(END[:4]) + 1):
        w = f"crash_date >= '{y}-01-01T00:00:00' AND crash_date <= '{y}-12-31T23:59:59'"
        extra = q["where"].split("AND", 2)[2] if key == "people" else None          # keep the injury filter
        where = w + (f" AND{extra}" if extra else "")
        parts.append(portal.query(q["id"], select=q["select"], where=where, group=q.get("group"), order=q.get("order")))
        print(f"  {key} {y}: {len(parts[-1]):,} rows", flush=True)
    return pd.concat(parts, ignore_index=True)


def load_sites():
    from simchi.data.cds import load_cds
    frame = load_cds().frame
    with gzip.open(DATA / "map" / "streets.json.gz", "rt") as fh:
        streets = json.load(fh)
    return build_sites(streets, frame.from_lonlat), frame


def _xy(frame, lon, lat):
    lon = pd.to_numeric(pd.Series(lon), errors="coerce").to_numpy(float)
    lat = pd.to_numeric(pd.Series(lat), errors="coerce").to_numpy(float)
    bad = ~np.isfinite(lon) | ~np.isfinite(lat) | (np.abs(lat) < 1) | (np.abs(lon) < 1)
    lon, lat = np.where(bad, np.nan, lon), np.where(bad, np.nan, lat)
    x, z = frame.from_lonlat(np.nan_to_num(lon, nan=-87.6), np.nan_to_num(lat, nan=41.8))
    x, z = np.asarray(x, float), np.asarray(z, float)
    x[bad] = np.nan
    z[bad] = np.nan
    return x, z


def aggregate(raw: dict, sites, frame) -> tuple[dict, dict]:
    """raw: dict of DataFrames as returned by fetch(). Returns (tables, summary)."""
    T = sites.table
    expressway = T["expressway"].to_dict()
    # ---- crashes
    c = raw["crashes"].copy()
    c["crash_date"] = pd.to_datetime(c["crash_date"])
    for k in ("injuries_fatal", "injuries_incapacitating", "injuries_total"):
        c[k] = pd.to_numeric(c[k], errors="coerce").fillna(0)
    cx, cz = _xy(frame, c["longitude"], c["latitude"])
    c["site"] = sites.snap(cx, cz)
    c["year"] = c["crash_date"].dt.year
    c["ka"] = (c["injuries_fatal"] >= 1) | (c["injuries_incapacitating"] >= 1)
    c["a"] = (c["injuries_incapacitating"] >= 1) & (c["injuries_fatal"] == 0)
    p = raw["people"].copy()
    p["n"] = pd.to_numeric(p["n"], errors="coerce").fillna(0)
    pb = p[p["person_type"].astype(str).str.upper().isin(["PEDESTRIAN", "BICYCLE"])].groupby("crash_record_id")["n"].sum()
    c["ped_bike_ka"] = c["crash_record_id"].map(pb).fillna(0)
    snapped = c[c["site"].notna()]
    site_year = snapped.groupby(["site", "year"]).agg(
        crashes=("crash_record_id", "size"), injury_crashes=("injuries_total", lambda s: int((s > 0).sum())),
        a_crashes=("a", "sum"), k_crashes_cpd=("injuries_fatal", lambda s: int((s >= 1).sum())),
        ped_bike_ka=("ped_bike_ka", "sum")).reset_index()
    # ---- Vision Zero deaths: one fatal crash per (minute, site)
    v = raw["vision_zero"].copy()
    v["crash_date"] = pd.to_datetime(v["crash_date"])
    vx, vz = _xy(frame, v["longitude"], v["latitude"])
    v["site"] = sites.snap(vx, vz)
    v["year"] = v["crash_date"].dt.year
    v["minute"] = v["crash_date"].dt.floor("min")
    vs = v[v["site"].notna()]
    vz_site_year = vs.groupby(["site", "year"]).agg(deaths=("minute", "size"), fatal_crashes=("minute", "nunique")).reset_index()
    # ---- cameras
    sc = raw["speed_cameras"].rename(columns={"id": "camera", "address": "address"})
    sc["kind"] = "speed"
    rl = raw["red_light_cameras"].rename(columns={"intersection": "address"})
    rl["kind"] = "red_light"
    rl["camera"] = rl["address"]
    cams = pd.concat([sc[["kind", "camera", "address", "go_live_date", "latitude", "longitude"]],
                      rl[["kind", "camera", "address", "go_live_date", "latitude", "longitude"]]], ignore_index=True)
    cams = cams.rename(columns={"go_live_date": "go_live", "latitude": "lat", "longitude": "lon"})
    cams["go_live"] = pd.to_datetime(cams["go_live"]).dt.date.astype(str)
    cams["camera"] = cams["camera"].astype(str)
    cams = cams.drop_duplicates(["kind", "camera"]).sort_values(["kind", "camera"]).reset_index(drop=True)
    kx, kz = _xy(frame, cams["lon"], cams["lat"])
    cam_ok = np.isfinite(kx)
    # ---- comparison pool: intersections with a class-2 leg, no camera within 1/2 mile, CPD
    inter = T[(T["type"] == "intersection") & ~T["expressway"]]
    seg_cls = T["cls"].to_dict()
    has_arterial = inter["leg_segments"].map(lambda L: any(seg_cls.get(s) == "2" for s in L))
    cand = inter[has_arterial]
    node_xy = dict(zip(sites.node_ids, map(tuple, sites.node_xy)))
    cxy = np.array([node_xy[s] for s in cand.index]) if len(cand) else np.zeros((0, 2))
    if cam_ok.any() and len(cxy):
        dmin, _ = cKDTree(np.column_stack([kx[cam_ok], kz[cam_ok]])).query(cxy)
        pool = cand.index[dmin > POOL_EXCLUSION_M]
    else:
        pool = cand.index
    pool_xy = np.array([node_xy[s] for s in pool]) if len(pool) else np.zeros((0, 2))
    # ---- radial monthly counts around cameras and pool intersections
    pts_id = [f"cam:{k}:{c_}" for k, c_ in zip(cams["kind"][cam_ok], cams["camera"][cam_ok])] + [f"site:{s}" for s in pool]
    pts_xy = np.vstack([np.column_stack([kx[cam_ok], kz[cam_ok]]), pool_xy]) if len(pool_xy) else np.column_stack([kx[cam_ok], kz[cam_ok]])
    ok = np.isfinite(cx)
    ctree = cKDTree(np.column_stack([cx[ok], cz[ok]]))
    month = c["crash_date"].dt.to_period("M").astype(str).to_numpy()[ok]
    ka = c["ka"].to_numpy()[ok]
    rows = []
    for pid, hits in zip(pts_id, ctree.query_ball_point(pts_xy, RADIUS_M)):
        if not hits:
            continue
        h = np.asarray(hits)
        df = pd.DataFrame({"month": month[h], "ka": ka[h]})
        g = df.groupby("month").agg(crashes=("ka", "size"), ka_crashes=("ka", "sum")).reset_index()
        g.insert(0, "point", pid)
        rows.append(g)
    radial = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["point", "month", "crashes", "ka_crashes"])
    # ---- violations (context)
    sv = raw["speed_violations"].assign(kind="speed").rename(columns={"camera_id": "camera"})
    rv = raw["red_light_violations"].assign(kind="red_light").rename(columns={"camera_id": "camera_id_rl"})
    rv["camera"] = rv["intersection"].astype(str)
    viol = pd.concat([sv[["kind", "camera", "month", "violations"]], rv[["kind", "camera", "month", "violations"]]], ignore_index=True)
    viol["month"] = pd.to_datetime(viol["month"]).dt.to_period("M").astype(str)
    viol["violations"] = pd.to_numeric(viol["violations"], errors="coerce").fillna(0).astype(int)
    viol = viol.groupby(["kind", "camera", "month"], as_index=False)["violations"].sum()
    # ---- traffic volume: sum directions per counted segment, snap the midpoint to a segment
    a = raw["adt"].copy()
    for k in ("mean_count", "days", "midpointlat", "midpointlon"):
        a[k] = pd.to_numeric(a[k], errors="coerce")
    seg = a.groupby(["segmentid"]).agg(adt=("mean_count", "sum"), days=("days", "min"), lat=("midpointlat", "first"), lon=("midpointlon", "first")).reset_index()
    ax, az = _xy(frame, seg["lon"], seg["lat"])
    seg["site"] = sites.snap(ax, az)
    seg = seg[seg["site"].astype(str).str.startswith("s")]          # counts belong to segments (30 m rule may hit a node: skip)
    site_adt = seg.groupby("site").agg(adt=("adt", "max"), counted_days=("days", "max")).reset_index()

    unsnapped = c[c["site"].isna()]
    expr = snapped[snapped["site"].map(expressway).fillna(False).astype(bool)]
    tables = {"site_year": site_year, "vz_site_year": vz_site_year, "radial_month": radial,
              "comparison_pool": pd.DataFrame({"site": list(pool)}),
              "cameras": cams[["kind", "camera", "address", "lon", "lat", "go_live"]], "violations_month": viol, "site_adt": site_adt}
    summary = {
        "crashes": int(len(c)), "crashes_unsnapped": int(len(unsnapped)), "crashes_no_location": int((~ok).sum()),
        "crashes_on_expressway_sites": int(len(expr)),
        "ka_crashes": int(c["ka"].sum()), "ka_unsnapped": int(unsnapped["ka"].sum()),
        "vision_zero_deaths": int(len(v)), "vision_zero_unsnapped": int(v["site"].isna().sum()),
        "cameras": {k: int(n) for k, n in cams["kind"].value_counts().items()}, "comparison_pool": int(len(pool)),
        "adt_segments_counted": int(len(seg)), "sites_with_adt": int(len(site_adt)),
        "crash_date_range": [str(c["crash_date"].min()), str(c["crash_date"].max())],
        "vision_zero_date_range": [str(v["crash_date"].min()), str(v["crash_date"].max())],
    }
    return tables, summary


def main(argv=None):
    from simchi.portal.client import Portal
    cache = Path(tempfile.gettempdir()) / "simchi-portal-cache"
    portal = Portal(cache_dir=cache)
    raw = {}
    for k in Q:
        print(f"fetching {k} ...", flush=True)
        raw[k] = fetch(portal, k)
        print(f"{k}: {len(raw[k]):,} rows", flush=True)
    sites, frame = load_sites()
    tables, summary = aggregate(raw, sites, frame)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(OUT / f"{name}.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
    summary.update({"downloaded": datetime.now(timezone.utc).date().isoformat(), "portal_requests": portal.requests,
                    "queries": {k: {kk: vv for kk, vv in v.items() if vv} for k, v in Q.items()}, "sites": int(len(sites.table))})
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "queries"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
