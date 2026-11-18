"""Self-hosted data for the 2D map (viewer/dist/data/map/*.json), all WGS84 lon/lat.

Basemap from City of Chicago open data, no third-party tiles or keys:
  streets   Street Center Lines (portal dataset pr57-gg9e, "transportation"), simplified to ~1 m,
            with street class (CLASS codes from the City's centerline metadata: 1 expressway,
            2 arterials, 3 collectors, 4 other streets, 5 named alleys, 7 tiered, 9 ramps,
            E extent, RIV river, S sidewalk, 99 unclassified) and full street name
  areas     the 77 community areas (CMAP CDS mirror), with names
  land      the land side of the Lake Michigan shoreline (approximation from the city's east
            boundary, as in the 3D view), so the background can be water
  cta       CTA rail lines (colours), bus routes and 'L' stations from the GTFS extract
  labels    one label point per arterial/expressway name per community area
The raw centerline download is not stored in git; data/sources.toml records its sha256 and the
derived file is data/map/streets.json.gz.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, Polygon, mapping, shape

from simchi.paths import DATA, VIEWER

MAPDATA = DATA / "map"
KEEP_CLASSES = {"1", "2", "3", "4", "5", "7", "9", "E", "RIV"}
SIMPLIFY_DEG = 1e-5           # about 1 m
ROUND = 5                     # 5 decimals ~ 1.1 m


def _round(coords):
    return [[round(x, ROUND), round(y, ROUND)] for x, y in coords]


def build_streets(raw_geojson: Path, out: Path = MAPDATA / "streets.json.gz") -> dict:
    """Derived street layer from the raw portal GeoJSON (see module docstring)."""
    d = json.loads(Path(raw_geojson).read_text())
    feats = []
    for f in d["features"]:
        p = f["properties"]
        c = p.get("class")
        if c not in KEEP_CLASSES or not f.get("geometry"):
            continue
        g = shape(f["geometry"]).simplify(SIMPLIFY_DEG, preserve_topology=False)
        lines = list(g.geoms) if isinstance(g, MultiLineString) else [g]
        name = " ".join(x for x in (p.get("pre_dir"), p.get("street_nam"), p.get("street_typ")) if x)
        for ln in lines:
            if ln.is_empty or len(ln.coords) < 2:
                continue
            feats.append({"type": "Feature", "properties": {"c": c, "n": name.title()},
                          "geometry": {"type": "LineString", "coordinates": _round(ln.coords)}})
    fc = {"type": "FeatureCollection", "features": feats}
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt") as fh:
        json.dump(fc, fh, separators=(",", ":"))
    return {"features": len(feats)}


def load_streets() -> dict:
    with gzip.open(MAPDATA / "streets.json.gz", "rt") as fh:
        return json.load(fh)


def areas_fc() -> dict:
    from simchi.data.cds import ROOT, source
    gj = json.loads((ROOT / source("cds_2021")["file"]).read_text())
    feats = []
    for f in gj["features"]:
        p = f["properties"]
        g = shape(f["geometry"])
        if not g.is_valid:
            g = shapely.make_valid(g)
        g = g.simplify(2e-5)
        num = int(p.get("GEOID") or p.get("geoid") or 0) if str(p.get("GEOID", "")).isdigit() else None
        feats.append({"type": "Feature", "properties": {"name": str(p.get("GEOG", "")).title(), "num": num},
                      "geometry": json.loads(json.dumps(mapping(g)), parse_float=lambda s: round(float(s), ROUND))})
    return {"type": "FeatureCollection", "features": feats}


def land_fc(areas: dict) -> dict:
    """Land side of the shoreline: everything west of the city's east edge, by latitude bands."""
    city = shapely.union_all([shape(f["geometry"]) for f in areas["features"]])
    b = city.bounds
    lats = np.arange(b[1], b[3] + 1e-9, 0.0025)
    shore = []
    for la in lats:
        band = city.intersection(shapely.box(b[0] - 1, la - 0.00125, b[2] + 1, la + 0.00125))
        if not band.is_empty:
            shore.append((band.bounds[2], la))
    # smooth piers and harbours out of the shoreline (max over a small window)
    xs = np.array([s[0] for s in shore])
    xs = np.array([xs[max(0, i - 3):i + 4].max() for i in range(len(xs))])
    north = [(xs[-1], b[3] + 0.35)]
    south = [(xs[0], b[1] - 0.35)]
    ring = [(-88.9, b[1] - 0.35), *south, *[(x, la) for x, (_, la) in zip(xs, shore, strict=True)], *north, (-88.9, b[3] + 0.35)]
    poly = Polygon(ring)
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"label": "approximate shoreline"},
                                                        "geometry": mapping(poly)}]}


def cta_fc() -> dict:
    from simchi.data.cds import load_cds
    from simchi.transit.gtfs import load_extract
    frame = load_cds().frame
    routes = {r["id"]: r for r in load_extract("routes")}
    shapes = load_extract("shapes")
    feats = []
    seen = set()
    for p in load_extract("patterns"):
        key = (p["route"], p["shape"])
        if key in seen:
            continue
        seen.add(key)
        xz = np.asarray(shapes[p["shape"]], float)
        lon, lat = frame.to_lonlat(xz[:, 0], xz[:, 1])
        r = routes[p["route"]]
        ln = LineString(np.column_stack([lon, lat])).simplify(1e-5)
        feats.append({"type": "Feature", "properties": {"route": r["id"], "name": r["long"], "kind": "rail" if r["type"] == 1 else "bus",
                                                        "color": r["color"]},
                      "geometry": {"type": "LineString", "coordinates": _round(ln.coords)}})
    for s in load_extract("stations"):
        lon, lat = frame.to_lonlat(s["x"], s["z"])
        feats.append({"type": "Feature", "properties": {"kind": "station", "name": s["name"], "lines": s["lines"]},
                      "geometry": {"type": "Point", "coordinates": [round(float(lon), ROUND), round(float(lat), ROUND)]}})
    return {"type": "FeatureCollection", "features": feats}


def labels_fc(streets: dict, areas: dict) -> dict:
    """One label point per (major street name, community area): the midpoint of its longest piece."""
    polys = [(f["properties"]["name"], shape(f["geometry"])) for f in areas["features"]]
    tree = shapely.STRtree([p for _, p in polys])
    best = {}
    for f in streets["features"]:
        c, n = f["properties"]["c"], f["properties"]["n"]
        if c not in ("1", "2") or not n:
            continue
        ln = LineString(f["geometry"]["coordinates"])
        mid = ln.interpolate(0.5, normalized=True)
        hit = tree.query(mid, predicate="within")
        area = polys[int(hit[0])][0] if len(hit) else "outside"
        k = (n, area)
        if k not in best or ln.length > best[k][0]:
            a, b_ = ln.coords[0], ln.coords[-1]
            ang = float(np.degrees(np.arctan2(b_[1] - a[1], (b_[0] - a[0]) * np.cos(np.radians(mid.y)))))
            best[k] = (ln.length, mid.x, mid.y, c, ang)
    feats = [{"type": "Feature", "properties": {"n": n, "c": c, "a": round(ang, 1)},
              "geometry": {"type": "Point", "coordinates": [round(x, ROUND), round(y, ROUND)]}}
             for (n, _), (_, x, y, c, ang) in best.items()]
    for f in areas["features"]:
        pt = shape(f["geometry"]).representative_point()
        feats.append({"type": "Feature", "properties": {"n": f["properties"]["name"], "c": "area", "a": 0},
                      "geometry": {"type": "Point", "coordinates": [round(pt.x, ROUND), round(pt.y, ROUND)]}})
    return {"type": "FeatureCollection", "features": feats}


def export_map(out_dir: Path | None = None) -> Path:
    out_dir = Path(out_dir) if out_dir else VIEWER / "dist" / "data" / "map"
    out_dir.mkdir(parents=True, exist_ok=True)
    streets = load_streets()
    areas = areas_fc()
    files = {"streets": streets, "areas": areas, "land": land_fc(areas), "cta": cta_fc(), "labels": labels_fc(streets, areas)}
    for k, v in files.items():
        with open(out_dir / f"{k}.json", "w") as fh:
            json.dump(v, fh, separators=(",", ":"))
    return out_dir


__all__ = ["build_streets", "export_map", "load_streets"]
