"""Where to sit in Chicago: a benches and seating layer from several sources, with a measured
estimate of how complete it is (python -m simchi.benches --out viewer/dist/data/map).

No public dataset of Chicago benches exists: the City data portal has none (catalog search, 18 Nov
2026). Sources combined here:
  osm        OpenStreetMap: amenity=bench, leisure=picnic_table, bus stops tagged bench=yes or
             shelter=yes, transit platforms tagged bench=yes (Overpass API, one query per build).
             Data (c) OpenStreetMap contributors, ODbL 1.0: the published layer is therefore
             under the ODbL and must carry that attribution.
  cta        CTA bus stops "in shelters and at CTA rail stations" with digital signs (City data
             portal 5cq6-qygt, 2016 list): sheltered stops; whether each shelter has a bench is not
             recorded, so they are labelled "shelter (seating not recorded)".
Points from different sources within MATCH_M of each other at a bus stop are treated as one place.

Completeness (capture-recapture). Sheltered bus stops are seen by two sources, OpenStreetMap
(shelter=yes) and the CTA list. If the sources record stops independently, the Chapman estimator
of the number of sheltered stops is N = (a+1)(b+1)/(m+1) - 1 with a, b the stops each source has
and m the stops both have; Var(N) = (a+1)(b+1)(a-m)(b-m) / ((m+1)^2 (m+2)) (Seber 1970), 95%
interval N +- 1.96 sd. OpenStreetMap's share of shelters is then a / N. Independence is an
assumption: both sources favour busy downtown stops, which biases N downward, so OpenStreetMap's
completeness is an upper bound. The CTA list only covers stops chosen for digital signs, so it
says nothing about benches outside bus stops; their completeness is not estimated.
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

OVERPASS = "https://overpass-api.de/api/interpreter"
QUERY = """[out:json][timeout:180];
area["name"="Chicago"]["boundary"="administrative"]["admin_level"="8"]->.c;
(
  nwr["amenity"="bench"](area.c);
  nwr["leisure"="picnic_table"](area.c);
  nwr["highway"="bus_stop"]["bench"="yes"](area.c);
  nwr["highway"="bus_stop"]["shelter"="yes"](area.c);
  nwr["public_transport"="platform"]["bench"="yes"](area.c);
);
out center tags;"""
MATCH_M = 40.0
COLORS = {"bench": "#2f8f5b", "picnic_table": "#7a9a2f", "bus_stop_bench": "#1f6fd1", "shelter": "#7b57c9", "platform_bench": "#c2410c"}
LABEL = {"bench": "Bench", "picnic_table": "Picnic table", "bus_stop_bench": "Bus stop with bench", "shelter": "Bus shelter (seating not recorded)",
         "platform_bench": "Transit platform with bench"}


def fetch_osm(timeout: int = 240) -> dict:
    data = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(OVERPASS, data=data, headers={"User-Agent": "SimChicago-benches/0.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(10 * 2 ** attempt)
    raise RuntimeError("unreachable")


def osm_points(osm: dict) -> list:
    out = []
    for e in osm.get("elements", []):
        t = e.get("tags", {})
        lat, lon = (e.get("lat"), e.get("lon")) if e["type"] == "node" else (e.get("center", {}).get("lat"), e.get("center", {}).get("lon"))
        if lat is None:
            continue
        if t.get("amenity") == "bench":
            kind = "bench"
        elif t.get("leisure") == "picnic_table":
            kind = "picnic_table"
        elif t.get("highway") == "bus_stop":
            kind = "bus_stop_bench" if t.get("bench") == "yes" else "shelter"
        else:
            kind = "platform_bench"
        out.append({"lon": float(lon), "lat": float(lat), "kind": kind, "source": "osm", "osm": f"{e['type']}/{e['id']}",
                    "shelter": t.get("shelter") == "yes" and t.get("highway") == "bus_stop", "name": t.get("name", "")})
    return out


def cta_shelters(rows) -> list:
    out = []
    for r in rows:
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except (TypeError, ValueError, KeyError):
            continue
        out.append({"lon": lon, "lat": lat, "kind": "shelter", "source": "cta", "name": r.get("cta_stop_name", ""), "shelter": True})
    return out


def _xy(points) -> np.ndarray:
    lat0 = 41.85
    return np.array([[(p["lon"] + 87.65) * 111320.0 * math.cos(math.radians(lat0)), (p["lat"] - lat0) * 110574.0] for p in points]).reshape(-1, 2)


def match(a: list, b: list, radius: float = MATCH_M) -> list:
    """Greedy one-to-one matching of points in a to points in b within radius (closest first)."""
    if not a or not b:
        return []
    A, B = _xy(a), _xy(b)
    d = np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1])
    pairs = sorted(((d[i, j], i, j) for i, j in zip(*np.nonzero(d <= radius), strict=True)))
    used_a, used_b, out = set(), set(), []
    for _, i, j in pairs:
        if i not in used_a and j not in used_b:
            used_a.add(i)
            used_b.add(j)
            out.append((i, j))
    return out


def chapman(a: int, b: int, m: int) -> dict:
    N = (a + 1) * (b + 1) / (m + 1) - 1
    var = (a + 1) * (b + 1) * (a - m) * (b - m) / ((m + 1) ** 2 * (m + 2))
    sd = math.sqrt(var)
    return {"a": a, "b": b, "m": m, "N": N, "ci95": [N - 1.96 * sd, N + 1.96 * sd]}


def build(osm: dict, cta_rows) -> tuple[dict, dict]:
    o = osm_points(osm)
    c = cta_shelters(cta_rows)
    osm_shelters = [p for p in o if p["shelter"]]
    m = match(osm_shelters, c)
    est = chapman(len(osm_shelters), len(c), len(m))
    est["osm_share_of_shelters"] = len(osm_shelters) / est["N"] if est["N"] > 0 else None
    matched_c = {j for _, j in m}
    feats = []
    for p in o:
        feats.append(p)
    for j, p in enumerate(c):
        if j not in matched_c:
            feats.append(p)
    fc = {"type": "FeatureCollection", "license": "Contains OpenStreetMap data (c) OpenStreetMap contributors, ODbL 1.0; CTA shelter list: City of Chicago data portal 5cq6-qygt",
          "features": [{"type": "Feature", "properties": {"kind": LABEL[p["kind"]], "source": "OpenStreetMap" if p["source"] == "osm" else "CTA (2016 list)",
                                                          "color": COLORS[p["kind"]], "note": p.get("name", "")},
                        "geometry": {"type": "Point", "coordinates": [round(p["lon"], 6), round(p["lat"], 6)]}} for p in feats]}
    counts = {}
    for p in feats:
        counts[p["kind"]] = counts.get(p["kind"], 0) + 1
    summary = {"osm_base": osm.get("osm3s", {}).get("timestamp_osm_base"), "features": len(feats), "by_kind": counts,
               "osm_elements": len(o), "cta_shelters": len(c), "shelter_capture_recapture": est,
               "method": __doc__.split("Completeness")[1].strip()}
    return fc, summary


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="viewer/dist/data/map")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    from simchi.portal.client import Portal
    osm = fetch_osm()
    import tempfile
    rows = Portal(cache_dir=tempfile.mkdtemp()).query("5cq6-qygt", cache=False).to_dict("records")
    fc, summary = build(osm, rows)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "benches.json").write_text(json.dumps(fc, separators=(",", ":")))
    (out / "benches_summary.json").write_text(json.dumps(summary, indent=1))
    print("BENCHES", json.dumps({k: summary[k] for k in ("osm_base", "features", "by_kind", "osm_elements", "cta_shelters")}),
          "CAPTURE-RECAPTURE", json.dumps(summary["shelter_capture_recapture"]))


if __name__ == "__main__":
    main()
