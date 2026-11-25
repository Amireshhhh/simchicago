"""Crash sites from the street extract, and snapping points to them (rules: the W4 design in
simchi/safety/crashes.py, SITES).

Sites
  segment       one feature of data/map/streets.json.gz of a street class (not river, not extent);
                id "s<feature index>"
  intersection  a segment end point (lon/lat to 5 decimals) shared by >= 3 segment ends;
                id "i<rank in sorted coordinates>"
CPD streets are classes 2, 3, 4, 5, 7; expressway classes are 1 and 9. A segment of class 1/9 and
an intersection all of whose legs are 1/9 are flagged `expressway` (not CPD jurisdiction).
Snap: within 30 m of an intersection -> it; else nearest segment within 50 m; else None.
Distances in the simulation frame (metres, UTM 16N based).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree
from shapely import STRtree, points
from shapely.geometry import LineString

STREET_CLASSES = {"1", "2", "3", "4", "5", "7", "9"}
EXPRESSWAY = {"1", "9"}
CLASS_ORDER = {"1": 0, "9": 1, "2": 2, "3": 3, "4": 4, "7": 5, "5": 6}   # lower = higher order
INTERSECTION_M = 30.0
SEGMENT_M = 50.0


@dataclass
class Sites:
    table: "pd.DataFrame"        # one row per site
    seg_geoms: list              # metric LineStrings of segments (index = segment number)
    seg_ids: np.ndarray
    node_xy: np.ndarray
    node_ids: np.ndarray
    _tree: STRtree = None
    _ktree: cKDTree = None

    def snap(self, x, z) -> np.ndarray:
        """Site id (str) or None for each point (metric coordinates)."""
        x, z = np.asarray(x, float), np.asarray(z, float)
        out = np.full(len(x), None, dtype=object)
        ok = np.isfinite(x) & np.isfinite(z)
        if not ok.any():
            return out
        idx = np.nonzero(ok)[0]
        P = np.column_stack([x[idx], z[idx]])
        if len(self.node_xy):
            d, j = self._ktree.query(P, distance_upper_bound=INTERSECTION_M)
            hit = np.isfinite(d)
            out[idx[hit]] = self.node_ids[j[hit]]
            rest = idx[~hit]
        else:
            rest = idx
        if len(rest):
            pts = points(np.column_stack([x[rest], z[rest]]))
            pi, si = self._tree.query_nearest(pts, max_distance=SEGMENT_M, all_matches=False)
            out[rest[pi]] = self.seg_ids[si]
        return out


def build_sites(streets_fc: dict, to_xy) -> Sites:
    """streets_fc: GeoJSON FeatureCollection (lon/lat) with properties c (class) and n (name);
    to_xy(lon_array, lat_array) -> (x, z) metric arrays."""
    import pandas as pd
    segs, ends = [], {}
    for k, f in enumerate(streets_fc["features"]):
        c = str(f["properties"].get("c"))
        if c not in STREET_CLASSES:
            continue
        co = np.asarray(f["geometry"]["coordinates"], float)
        x, z = to_xy(co[:, 0], co[:, 1])
        g = LineString(np.column_stack([x, z]))
        sid = f"s{k}"
        segs.append({"site": sid, "type": "segment", "cls": c, "name": f["properties"].get("n", ""),
                     "length_m": float(g.length), "expressway": c in EXPRESSWAY, "geom": g,
                     "lon": float(co[len(co) // 2, 0]), "lat": float(co[len(co) // 2, 1])})
        for end in (co[0], co[-1]):
            key = (round(float(end[0]), 5), round(float(end[1]), 5))
            ends.setdefault(key, []).append((sid, c, f["properties"].get("n", "")))
    nodes = sorted(k for k, v in ends.items() if len(v) >= 3)
    rows = []
    nlon = np.array([k[0] for k in nodes]); nlat = np.array([k[1] for k in nodes])
    nx, nz = to_xy(nlon, nlat) if len(nodes) else (np.array([]), np.array([]))
    for r, key in enumerate(nodes):
        legs = ends[key]
        classes = [c for _, c, _ in legs]
        top = min(classes, key=lambda c: CLASS_ORDER.get(c, 9))
        cpd = [c for c in classes if c not in EXPRESSWAY]
        rows.append({"site": f"i{r}", "type": "intersection", "cls": min(cpd, key=lambda c: CLASS_ORDER.get(c, 9)) if cpd else top,
                     "name": " & ".join(sorted({n for _, _, n in legs if n})[:3]), "legs": len(legs),
                     "leg_segments": [s for s, _, _ in legs], "length_m": 0.0,
                     "expressway": all(c in EXPRESSWAY for c in classes), "lon": key[0], "lat": key[1]})
    seg_table = pd.DataFrame([{k: v for k, v in s.items() if k != "geom"} for s in segs])
    seg_table["legs"] = 0
    seg_table["leg_segments"] = [[] for _ in range(len(seg_table))]
    table = pd.concat([seg_table, pd.DataFrame(rows)], ignore_index=True)
    geoms = [s["geom"] for s in segs]
    S = Sites(table=table.set_index("site", drop=False), seg_geoms=geoms, seg_ids=np.array([s["site"] for s in segs]),
              node_xy=np.column_stack([nx, nz]) if len(nodes) else np.zeros((0, 2)), node_ids=np.array([f"i{r}" for r in range(len(nodes))]))
    S._tree = STRtree(geoms)
    S._ktree = cKDTree(S.node_xy) if len(nodes) else None
    return S
