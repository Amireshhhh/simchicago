"""CTA static GTFS: read the feed and build the compact derived extract in data/transit/.

The raw feed (a ~51 MB zip that CTA replaces every week or two) is not stored in git. The
extract keeps what SimChicago uses, in the local coordinate frame:

  routes.json    every route: id, names, type (1 rail, 3 bus), colour
  stations.json  rail stations (GTFS parent stations) with the lines that serve them
  stops.json     every stop used by a representative pattern
  patterns.json  per route, direction and pair of terminals carrying >= 10% of the
                 route-direction's weekday trips, the most frequent stop sequence, with its share
                 of trips, shape and scheduled stop offsets (minutes from the first stop) by band
  service.json   scheduled trips per route, direction, day type and hour, and the implied
                 headway
  shapes.json    the representative pattern's shape, simplified to 5 m, as [x, z] metres
  meta.json      source sha256, download time, reference dates, counts

Times in GTFS may exceed 24:00:00 (service after midnight belongs to the previous day).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import LineString

from simchi.data.cds import load_cds
from simchi.paths import DATA

TRANSIT = DATA / "transit"
DAY_TYPES = {"weekday": date(2026, 11, 17), "saturday": date(2026, 11, 21), "sunday": date(2026, 11, 22)}
# Time bands for scheduled run times (start hour inclusive, end hour exclusive)
BANDS = {"early": (4, 6), "am_peak": (6, 9), "midday": (9, 15), "pm_peak": (15, 19), "evening": (19, 23), "night": (23, 28)}
SIMPLIFY_M = 5.0
MIN_PATTERN_SHARE = 0.10
RAIL_NAMES = {"Red": "Red Line", "Blue": "Blue Line", "Brn": "Brown Line", "G": "Green Line",
              "Org": "Orange Line", "P": "Purple Line", "Pink": "Pink Line", "Y": "Yellow Line"}


def gtfs_seconds(s: pd.Series) -> np.ndarray:
    """'HH:MM:SS' (HH may exceed 23) -> seconds after midnight of the service day."""
    if len(s) == 0:
        return np.zeros(0, dtype=int)
    parts = s.str.split(":", expand=True).astype(int)
    return (parts[0] * 3600 + parts[1] * 60 + parts[2]).to_numpy()


@dataclass
class Feed:
    tables: dict

    def __getitem__(self, name) -> pd.DataFrame:
        return self.tables[name]


def read_feed(path) -> Feed:
    """Read a GTFS zip or directory. All columns are read as strings."""
    path = Path(path)
    names = ["agency", "routes", "stops", "trips", "stop_times", "calendar", "calendar_dates", "shapes", "transfers"]
    tables = {}
    if path.is_dir():
        for n in names:
            f = path / f"{n}.txt"
            if f.exists():
                tables[n] = pd.read_csv(f, dtype=str, keep_default_na=False)
    else:
        with zipfile.ZipFile(path) as z:
            for n in names:
                if f"{n}.txt" in z.namelist():
                    tables[n] = pd.read_csv(io.BytesIO(z.read(f"{n}.txt")), dtype=str, keep_default_na=False)
    return Feed(tables)


def active_services(feed: Feed, day: date) -> set:
    cal = feed["calendar"]
    wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][day.weekday()]
    ymd = day.strftime("%Y%m%d")
    on = set(cal[(cal[wd] == "1") & (cal["start_date"] <= ymd) & (cal["end_date"] >= ymd)]["service_id"])
    if "calendar_dates" in feed.tables:
        cd = feed["calendar_dates"]
        cd = cd[cd["date"] == ymd]
        on |= set(cd[cd["exception_type"] == "1"]["service_id"])
        on -= set(cd[cd["exception_type"] == "2"]["service_id"])
    return on


def _trip_table(feed: Feed, day: date) -> pd.DataFrame:
    """One row per trip running on `day`: route, direction, shape, first departure (s), stop tuple."""
    trips = feed["trips"]
    trips = trips[trips["service_id"].isin(active_services(feed, day))]
    st = feed["stop_times"]
    st = st[st["trip_id"].isin(set(trips["trip_id"]))].copy()
    st["seq"] = st["stop_sequence"].astype(int)
    st["t"] = gtfs_seconds(st["departure_time"].where(st["departure_time"] != "", st["arrival_time"]))
    st = st.sort_values(["trip_id", "seq"])
    g = st.groupby("trip_id", sort=False)
    t0 = g["t"].first()
    stops = g["stop_id"].agg(tuple)
    offs = g["t"].agg(lambda x: tuple((x - x.iloc[0]).tolist()))
    out = trips.set_index("trip_id")[["route_id", "direction_id", "shape_id"]].join(
        pd.DataFrame({"t0": t0, "stops": stops, "offsets": offs}), how="inner")
    return out.reset_index()


def build_extract(feed_path, out_dir: Path = TRANSIT, source_sha256: str | None = None) -> dict:
    feed = read_feed(feed_path)
    frame = load_cds().frame
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    routes = feed["routes"]
    route_rows = [{"id": r.route_id, "short": r.route_short_name, "long": r.route_long_name,
                   "type": int(r.route_type), "color": "#" + (r.route_color or "888888").upper()}
                  for r in routes.itertuples()]

    # trips on each reference day
    by_day = {k: _trip_table(feed, d) for k, d in DAY_TYPES.items()}
    wk = by_day["weekday"]

    # representative patterns: per route and direction, group trips by (first stop, last stop) and
    # keep each group with at least MIN_PATTERN_SHARE of the route-direction's weekday trips; its
    # representative is its most frequent stop sequence. (Grouping by terminals as well as by
    # direction_id matters: e.g. every Yellow Line trip is coded direction_id 1.)
    patterns, used_stops, used_shapes = [], set(), set()
    wk = wk.assign(first=wk["stops"].str[0], last=wk["stops"].str[-1])
    for (rid, did), g_rd in wk.groupby(["route_id", "direction_id"]):
        for (first, last), g in g_rd.groupby(["first", "last"]):
            share = len(g) / len(g_rd)
            if share < MIN_PATTERN_SHARE:
                continue
            seq = g["stops"].value_counts().index[0]
            same = g[g["stops"] == seq]
            shape_id = same["shape_id"].mode().iloc[0]
            off = np.array(same["offsets"].tolist(), float)          # trips x stops (seconds)
            hours = same["t0"].to_numpy() / 3600.0
            band_offsets = {}
            for band, (h0, h1) in BANDS.items():
                m = (hours >= h0) & (hours < h1)
                if m.any():
                    band_offsets[band] = np.round(np.median(off[m], axis=0) / 60.0, 2).tolist()
            patterns.append({"route": rid, "direction": int(did), "stops": list(seq), "shape": shape_id,
                             "share_of_trips": round(share, 4), "trips_weekday": int(len(g)),
                             "offsets_min": band_offsets})
            used_stops.update(seq)
            used_shapes.add(shape_id)

    # scheduled service: trips and headway per route, direction, day type and hour of first departure
    service = []
    for day_type, t in by_day.items():
        t = t.assign(hour=(t["t0"] // 3600).astype(int))
        for (rid, did, hour), g in t.groupby(["route_id", "direction_id", "hour"]):
            service.append({"route": rid, "direction": int(did), "day": day_type, "hour": int(hour),
                            "trips": int(len(g)), "headway_min": round(60.0 / len(g), 2)})

    # stops and rail stations
    stops = feed["stops"]
    st_xy = frame.from_lonlat(stops["stop_lon"].astype(float).to_numpy(), stops["stop_lat"].astype(float).to_numpy())
    stops = stops.assign(x=np.round(st_xy[0], 1), z=np.round(st_xy[1], 1))
    stop_rows = [{"id": s.stop_id, "name": s.stop_name, "x": s.x, "z": s.z, "parent": s.parent_station}
                 for s in stops[stops["stop_id"].isin(used_stops)].itertuples()]
    rail_routes = {r["id"] for r in route_rows if r["type"] == 1}
    parent_of = dict(zip(stops["stop_id"], stops["parent_station"], strict=True))
    lines_at = {}
    for p in patterns:
        if p["route"] in rail_routes:
            for s in p["stops"]:
                par = parent_of.get(s) or s
                lines_at.setdefault(par, set()).add(p["route"])
    parents = stops[stops["location_type"] == "1"]
    station_rows = [{"id": s.stop_id, "name": s.stop_name, "x": s.x, "z": s.z, "lines": sorted(lines_at.get(s.stop_id, []))}
                    for s in parents.itertuples() if s.stop_id in lines_at]

    # shapes, simplified
    sh = feed["shapes"]
    sh = sh[sh["shape_id"].isin(used_shapes)].copy()
    sh["seq"] = sh["shape_pt_sequence"].astype(int)
    shape_rows = {}
    for sid, g in sh.sort_values(["shape_id", "seq"]).groupby("shape_id"):
        x, z = frame.from_lonlat(g["shape_pt_lon"].astype(float).to_numpy(), g["shape_pt_lat"].astype(float).to_numpy())
        line = LineString(np.column_stack([x, z])).simplify(SIMPLIFY_M)
        shape_rows[sid] = [[round(a, 1), round(b, 1)] for a, b in line.coords]

    meta = {
        "source": "CTA GTFS google_transit.zip", "source_url": "https://www.transitchicago.com/downloads/sch_data/google_transit.zip",
        "source_sha256": source_sha256, "built_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "reference_dates": {k: d.isoformat() for k, d in DAY_TYPES.items()}, "bands": BANDS,
        "counts": {"routes": len(route_rows), "rail_routes": len(rail_routes), "patterns": len(patterns),
                   "stops": len(stop_rows), "stations": len(station_rows), "shapes": len(shape_rows),
                   "weekday_trips": int(len(wk))},
        "license": "CTA Developer License Agreement and Terms of Use (see docs/CTA_TERMS.md)",
        "label": "observed (scheduled service as published by CTA)",
    }
    files = {"routes.json": route_rows, "stations.json": station_rows, "stops.json": stop_rows,
             "patterns.json": patterns, "service.json": service, "shapes.json": shape_rows, "meta.json": meta}
    for name, obj in files.items():
        with open(out_dir / name, "w") as f:
            json.dump(obj, f, separators=(",", ":"))
    return meta


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_extract(name: str, root: Path = TRANSIT):
    with open(Path(root) / f"{name}.json") as f:
        return json.load(f)
