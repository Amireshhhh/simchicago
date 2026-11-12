"""Near-live CTA vehicle positions, polled server-side within a fixed request budget.

Run in GitHub Actions (live.yml):  python -m simchi.transit.live --polls 3 --interval 60 --out live/

Keys are read only from the environment variables CTA_BUS_KEY and CTA_TRAIN_KEY. They are
placed in request URLs and nowhere else: never logged, never written, and redacted from any
error text. See docs/CTA_TERMS.md for the terms and the budget arithmetic.

Outputs (in --out):
  latest.json      the snapshot the viewer reads (schema "simchi.live/1"): one entry per
                   vehicle with its latest position and the positions from this run's polls
  history.csv.gz   one row per vehicle per poll (kept as a workflow artifact, not in git)
  requests.json    request counts for this run (used to measure daily use from the logs)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")
BUS_URL = "https://www.ctabustracker.com/bustime/api/v3/getvehicles"
TRAIN_URL = "https://lapi.transitchicago.com/api/1.0/ttpositions.aspx"
TRAIN_LINES = ["red", "blue", "brn", "g", "org", "p", "pink", "y"]   # Train Tracker route ids
TRAIN_LINE_TO_GTFS = {"red": "Red", "blue": "Blue", "brn": "Brn", "g": "G", "org": "Org", "p": "P", "pink": "Pink", "y": "Y"}
BUS_ROUTES_PER_REQUEST = 10            # getvehicles: "A maximum of 10 identifiers can be specified"
REQUEST_CAP = {"bus": 60, "train": 36}  # hard cap per run, retries included (docs/CTA_TERMS.md)
MAX_RETRIES = 2
BACKOFF_S = (2.0, 4.0)
TIMEOUT_S = 20
SCHEMA = "simchi.live/1"
ATTRIBUTION = ("Data provided by Chicago Transit Authority (CTA Bus Tracker, CTA Train Tracker). "
               "SimChicago is not affiliated with or endorsed by CTA. Positions may be missing, delayed or wrong.")
BUS_FATAL = ("invalid api access key", "transaction limit for current day has been exceeded")
TRAIN_FATAL = {"101", "102"}           # invalid key; maximum daily usage exceeded


class BudgetExhausted(Exception):
    """The per-run request cap was reached; stop polling politely."""


class FatalAPIError(Exception):
    """CTA reported a key or daily-limit problem; stop polling for this run."""


@dataclass
class Budget:
    cap: int
    used: int = 0
    retries: int = 0

    def take(self, retry: bool = False):
        if self.used >= self.cap:
            raise BudgetExhausted(f"request cap {self.cap} reached")
        self.used += 1
        self.retries += int(retry)


def redact(text: str, secrets) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text


def http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SimChicago/0.3 (research simulation; GitHub Actions)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


@dataclass
class Client:
    """One API (bus or train): builds URLs with the key, counts requests, retries with backoff."""
    name: str
    base: str
    key: str
    budget: Budget
    fetch: object = http_get_json
    sleep: object = time.sleep
    log: list = field(default_factory=list)

    def get(self, params: dict) -> dict:
        query = urllib.parse.urlencode({"key": self.key, **params}, safe=",")
        url = f"{self.base}?{query}"
        for attempt in range(MAX_RETRIES + 1):
            self.budget.take(retry=attempt > 0)
            try:
                return self.fetch(url)
            except urllib.error.HTTPError as e:
                status = e.code
                if status not in (429,) and status < 500:
                    raise FatalAPIError(f"{self.name}: HTTP {status}") from None
                err = f"HTTP {status}"
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                err = redact(type(e).__name__ + ": " + str(e), [self.key])
            self.log.append(f"{self.name} attempt {attempt + 1} failed: {err}")
            if attempt < MAX_RETRIES:
                self.sleep(BACKOFF_S[attempt] + random.uniform(0, 1))
        raise TimeoutError(f"{self.name}: gave up after {MAX_RETRIES + 1} attempts")


def chicago_hour_and_day(now_utc: datetime):
    local = now_utc.astimezone(CHICAGO)
    day = "saturday" if local.weekday() == 5 else "sunday" if local.weekday() == 6 else "weekday"
    prev = local - timedelta(days=1)
    prev_day = "saturday" if prev.weekday() == 5 else "sunday" if prev.weekday() == 6 else "weekday"
    return local.hour, day, prev_day


def routes_in_service(service: list, bus_routes: list, now_utc: datetime) -> list:
    """Bus routes with a scheduled trip starting this hour or the previous hour (GTFS),
    including after-midnight trips (hour >= 24) of the previous service day."""
    hour, day, prev_day = chicago_hour_and_day(now_utc)
    want = {(day, hour), (day, hour - 1), (prev_day, hour + 24), (prev_day, hour + 23)}
    active = {s["route"] for s in service if (s["day"], s["hour"]) in want}
    return [r for r in bus_routes if r in active]


def _bus_time_utc(tmstmp: str) -> str:
    fmt = "%Y%m%d %H:%M:%S" if len(tmstmp) > 14 else "%Y%m%d %H:%M"
    return datetime.strptime(tmstmp, fmt).replace(tzinfo=CHICAGO).astimezone(timezone.utc).isoformat()


def poll_bus(client: Client, routes: list) -> list:
    out = []
    for i in range(0, len(routes), BUS_ROUTES_PER_REQUEST):
        batch = routes[i:i + BUS_ROUTES_PER_REQUEST]
        data = client.get({"rt": ",".join(batch), "tmres": "s", "format": "json"}).get("bustime-response", {})
        for e in data.get("error", []) or []:
            msg = str(e.get("msg", "")).lower()
            if any(f in msg for f in BUS_FATAL):
                raise FatalAPIError(f"bus: {e.get('msg')}")
        for v in data.get("vehicle", []) or []:
            out.append({"mode": "bus", "id": f"bus:{v['vid']}", "route": str(v.get("rt", "")),
                        "lat": float(v["lat"]), "lon": float(v["lon"]), "hdg": float(v.get("hdg") or 0),
                        "t_utc": _bus_time_utc(v["tmstmp"]), "dly": bool(v.get("dly", False)),
                        "dest": v.get("des", ""), "pid": v.get("pid"), "pdist": v.get("pdist"),
                        "trip": v.get("tatripid"), "stst": v.get("stst"), "stsd": v.get("stsd"),
                        "load": v.get("psgld")})
    return out


def _train_rows(data: dict, now_utc: datetime) -> list:
    ctatt = data.get("ctatt", {})
    t_local = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y%m%d %H:%M:%S"):        # JSON example / field table
        try:
            t_local = datetime.strptime(str(ctatt.get("tmst", "")), fmt)
            break
        except ValueError:
            pass
    t_utc = (t_local.replace(tzinfo=CHICAGO).astimezone(timezone.utc).isoformat() if t_local else now_utc.isoformat())
    out = []
    routes = ctatt.get("route", []) or []
    routes = routes if isinstance(routes, list) else [routes]
    for r in routes:
        line = TRAIN_LINE_TO_GTFS.get(str(r.get("@name", "")).lower(), str(r.get("@name", "")))
        trains = r.get("train", []) or []
        trains = trains if isinstance(trains, list) else [trains]
        for tr in trains:
            if not tr.get("lat") or not tr.get("lon"):
                continue                                     # schedule-based entries have no position
            out.append({"mode": "train", "id": f"train:{line}:{tr.get('rn')}", "route": line,
                        "lat": float(tr["lat"]), "lon": float(tr["lon"]), "hdg": float(tr.get("heading") or 0),
                        "t_utc": t_utc, "dly": str(tr.get("isDly", "0")) == "1", "dest": tr.get("destNm", ""),
                        "next_station": tr.get("nextStaNm", ""), "next_station_id": tr.get("nextStaId"),
                        "train_dir": tr.get("trDr"), "approaching": str(tr.get("isApp", "0")) == "1"})
    return out


def poll_train(client: Client, now_utc: datetime) -> list:
    data = client.get({"rt": ",".join(TRAIN_LINES), "outputType": "JSON"})
    code = str(data.get("ctatt", {}).get("errCd", "0"))
    if code in TRAIN_FATAL:
        raise FatalAPIError(f"train: error {code}")
    if code in ("106", "500"):                               # multi-route syntax not accepted: one per line
        client.log.append(f"train: combined request rejected (error {code}); falling back to one request per line")
        rows = []
        for line in TRAIN_LINES:
            d = client.get({"rt": line, "outputType": "JSON"})
            c = str(d.get("ctatt", {}).get("errCd", "0"))
            if c in TRAIN_FATAL:
                raise FatalAPIError(f"train: error {c}")
            rows += _train_rows(d, now_utc)
        return rows
    return _train_rows(data, now_utc)


def build_snapshot(polls: list, frame, requests: dict, notes: list) -> dict:
    """polls: [(poll_time_utc, rows)]. Latest position per vehicle plus its track over the run."""
    tracks: dict = {}
    for t_poll, rows in polls:
        for r in rows:
            tracks.setdefault(r["id"], []).append((t_poll, r))
    vehicles = []
    for vid, items in tracks.items():
        last = items[-1][1]
        xs, zs = frame.from_lonlat([i[1]["lon"] for i in items], [i[1]["lat"] for i in items])
        vehicles.append({
            "id": vid, "mode": last["mode"], "route": last["route"], "label": "observed",
            "x": round(float(xs[-1]), 1), "z": round(float(zs[-1]), 1), "hdg": last["hdg"],
            "t_utc": last["t_utc"], "dly": last["dly"], "dest": last.get("dest", ""),
            "track": [[i[0], round(float(x), 1), round(float(z), 1)] for i, x, z in zip(items, xs, zs, strict=True)],
        })
    return {
        "schema": SCHEMA, "label": "observed",
        "generated_utc": polls[-1][0] if polls else datetime.now(timezone.utc).isoformat(),
        "poll_times_utc": [p[0] for p in polls], "attribution": ATTRIBUTION,
        "requests": requests, "notes": notes,
        "counts": {"bus": sum(v["mode"] == "bus" for v in vehicles), "train": sum(v["mode"] == "train" for v in vehicles)},
        "vehicles": vehicles,
    }


HISTORY_FIELDS = ["poll_utc", "mode", "id", "route", "lat", "lon", "hdg", "t_utc", "dly", "dest", "pid", "pdist",
                  "trip", "stst", "stsd", "load", "next_station", "next_station_id", "train_dir", "approaching"]


def write_outputs(out: Path, snapshot: dict, polls: list):
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "latest.json", "w") as f:
        json.dump(snapshot, f, separators=(",", ":"))
    with gzip.open(out / "history.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        w.writeheader()
        for t_poll, rows in polls:
            for r in rows:
                w.writerow({"poll_utc": t_poll, **r})
    with open(out / "requests.json", "w") as f:
        json.dump(snapshot["requests"], f)


def run(polls: int, interval: float, out: Path, bus_key: str | None, train_key: str | None,
        service: list, bus_routes: list, frame, fetch=http_get_json, sleep=time.sleep, now=None) -> dict:
    now = now or (lambda: datetime.now(timezone.utc))
    bus = Client("bus", BUS_URL, bus_key or "", Budget(REQUEST_CAP["bus"]), fetch, sleep)
    train = Client("train", TRAIN_URL, train_key or "", Budget(REQUEST_CAP["train"]), fetch, sleep)
    active = {"bus": bool(bus_key), "train": bool(train_key)}
    notes = [f"{m}: no key in the environment, not polled" for m, ok in active.items() if not ok]
    results = []
    for k in range(polls):
        t = now()
        rows = []
        for mode, client in (("bus", bus), ("train", train)):
            if not active[mode]:
                continue
            try:
                rows += poll_bus(client, routes_in_service(service, bus_routes, t)) if mode == "bus" else poll_train(client, t)
            except BudgetExhausted as e:
                notes.append(f"{mode}: {e}; stopped polling {mode} for this run")
                active[mode] = False
            except FatalAPIError as e:
                notes.append(redact(str(e), [bus_key, train_key]) + f"; stopped polling {mode} for this run")
                active[mode] = False
            except TimeoutError as e:
                notes.append(redact(str(e), [bus_key, train_key]))
        results.append((t.replace(microsecond=0).isoformat(), rows))
        if k < polls - 1 and any(active.values()):
            sleep(interval)
    notes += [redact(x, [bus_key, train_key]) for x in bus.log + train.log]
    requests = {"bus": bus.budget.used, "bus_retries": bus.budget.retries, "train": train.budget.used,
                "train_retries": train.budget.retries, "cap": REQUEST_CAP, "polls": polls}
    snap = build_snapshot(results, frame, requests, notes)
    write_outputs(out, snap, results)
    return snap


def main(argv=None):
    from simchi.data.cds import load_cds
    from simchi.transit.gtfs import load_extract
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--polls", type=int, default=3)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--out", type=Path, default=Path("live"))
    a = ap.parse_args(argv)
    if a.polls < 1 or a.polls > 3 or a.interval < 30:
        ap.error("the request budget assumes at most 3 polls per run, at least 30 s apart")
    routes = [r["id"] for r in load_extract("routes") if r["type"] == 3]
    snap = run(a.polls, a.interval, a.out, os.environ.get("CTA_BUS_KEY"), os.environ.get("CTA_TRAIN_KEY"),
               load_extract("service"), routes, load_cds().frame)
    r = snap["requests"]
    print(f"REQUESTS bus={r['bus']} bus_retries={r['bus_retries']} train={r['train']} train_retries={r['train_retries']} "
          f"vehicles bus={snap['counts']['bus']} train={snap['counts']['train']}")
    for n in snap["notes"]:
        print("NOTE", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
