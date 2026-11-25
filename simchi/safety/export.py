"""Map layer for the crash safety results (viewer/dist/data/map/safety.json), read only from
reports/safety/ (python -m simchi.safety.crashes writes them).

Each site with any serious (KA) crash in 2018-2025 or in a top-100 ranking becomes a point with:
  eb        empirical-Bayes estimate of 2018-2024 KA crashes (the severity score)
  k, a      Vision Zero fatal crashes and incapacitating-injury crashes, 2018-2024
  crashes   crashes of any severity, 2018-2024
  volume    true if a traffic count is snapped to the site; without it the layer shows "crash
            concentration" (counts, not a rate per vehicle)
  bus       within 20 m of a CTA bus route shape (GTFS), for the bus-corridor filter
Expressways are not in the layer (not CPD jurisdiction); the map draws them grey with that label.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import STRtree, points
from shapely.geometry import LineString

from simchi.paths import REPORTS, VIEWER

BUS_M = 20.0


def bus_flags(lon, lat, frame) -> np.ndarray:
    from simchi.transit.gtfs import load_extract
    routes = {r["id"]: r for r in load_extract("routes")}
    shapes = load_extract("shapes")
    lines = [LineString(xy) for p in load_extract("patterns") if routes[p["route"]]["type"] == 3
             for xy in [shapes[p["shape"]]] if len(xy) >= 2]
    tree = STRtree(lines)
    x, z = frame.from_lonlat(np.asarray(lon, float), np.asarray(lat, float))
    pi, _ = tree.query_nearest(points(np.column_stack([x, z])), max_distance=BUS_M, all_matches=False)
    out = np.zeros(len(x), bool)
    out[pi] = True
    return out


def build_layer() -> dict:
    from simchi.data.cds import load_cds
    rep = json.loads((REPORTS / "safety" / "crash_ranking.json").read_text())
    s = pd.read_csv(REPORTS / "safety" / "sites.csv.gz", dtype={"site": str})
    top = set(rep["top100"]["EB"])
    s["bus"] = bus_flags(s["lon"], s["lat"], load_cds().frame)
    feats = []
    for r in s.itertuples():
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r.lon, 5), round(r.lat, 5)]},
                      "properties": {"site": r.site, "name": r.name if isinstance(r.name, str) else "", "type": r.type,
                                     "eb": round(float(r.eb), 3), "k": int(r.k_train), "a": int(r.a_train), "crashes": int(r.crashes_train),
                                     "volume": bool(np.isfinite(r.adt)) if isinstance(r.adt, float) else True,
                                     "bus": bool(r.bus), "top100": r.site in top}})
    m = rep["mirror"]
    return {"type": "FeatureCollection", "features": feats,
            "meta": {"source": "City of Chicago data portal: Traffic Crashes (85ca-t3if, u6pd-qa9d), Vision Zero fatalities (gzaz-isa6), Average Daily Traffic Counts (gc7y-n4xa)",
                     "data_through": m["crash_date_range"][1][:10], "downloaded": m["downloaded"],
                     "method": "Serious (KA) crashes 2018-2024 per site; negative binomial expected count by road class, legs, length and traffic volume where counted; empirical Bayes estimate (W4, simchi/safety/crashes.py)",
                     "test": {"pass": rep["test"]["pass"], "share": rep["test"]["captured_share"]["100"]},
                     "vision_zero_starts": m["vision_zero_date_range"][0][:10]}}


def export_layer(out: Path | None = None) -> Path | None:
    if not (REPORTS / "safety" / "crash_ranking.json").exists():
        return None
    out = Path(out) if out else VIEWER / "dist" / "data" / "map" / "safety.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_layer(), separators=(",", ":")))
    return out


if __name__ == "__main__":
    print(export_layer())
