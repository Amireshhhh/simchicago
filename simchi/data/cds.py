"""Community Data Snapshot (CDS) loader and internal-consistency checks."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd
from shapely.ops import unary_union

from simchi.data.geo import LocalFrame, to_utm
from simchi.paths import DATA, ROOT

__all__ = ["ROOT", "CDS", "load_cds", "sha256", "source", "IDENTITIES"]


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@lru_cache(maxsize=None)
def _sources() -> dict:
    with open(DATA / "sources.toml", "rb") as f:
        return tomllib.load(f)


def source(key: str) -> dict:
    return _sources()[key]


# (name, parts, total): sum(parts) should equal total in every community area.
IDENTITIES = [
    ("age", ["UND5", "A5_19", "A20_34", "A35_49", "A50_64", "A65_74", "A75_84", "OV85"], "TOT_POP"),
    ("race_ethnicity", ["WHITE", "HISP", "BLACK", "ASIAN", "OTHER"], "TOT_POP"),
    ("household_size", ["CT_1PHH", "CT_2PHH", "CT_3PHH", "CT_4MPHH"], "TOT_HH"),
    ("household_type", ["CT_FAM_HH", "CTNONFAMHH"], "TOT_HH"),
    ("income", ["INCLT25K", "INC2550K", "INC5075K", "INC75100K", "INC100150K", "INC_GT_150"], "TOT_HH"),
    ("vehicles", ["NO_VEH", "ONE_VEH", "TWO_VEH", "THREEP_VEH"], "TOT_HH"),
    ("tenure", ["OWN_OCC_HU", "RENTOCCHU"], "TOT_HH"),
    ("education", ["LT_HS", "HS", "SOME_COLL", "ASSOC", "BACH", "GRAD_PROF"], "POP_25OV"),
    ("labour_force", ["EMP", "UNEMP"], "IN_LBFRC"),
    ("population_16_over", ["IN_LBFRC", "N_IN_LBFRC"], "POP_16OV"),
    ("commute_mode", ["DROVE_AL", "CARPOOL", "TRANSIT", "WALK_BIKE", "COMM_OTHER"], "TOT_COMM"),
    ("workers", ["TOT_COMM", "WORK_HOME"], "T_WRKR16OV"),
]


@dataclass
class CDS:
    table: pd.DataFrame          # index: community area number 1..77
    geoms: dict                  # area number -> shapely geometry in local metres
    city: object                 # union of all areas (local metres)
    frame: LocalFrame
    identity_report: dict


def _identity_report(t: pd.DataFrame) -> dict:
    rep = {}
    for name, parts, total in IDENTITIES:
        s = t[parts].sum(axis=1)
        rel = (s - t[total]).abs() / t[total].clip(lower=1)
        rep[name] = {"parts": parts, "total": total, "max_rel_diff": float(rel.max()),
                     "worst_area": int(rel.idxmax())}
    # LEHD orientation. TOTEMPWRK counts jobs located in the area (workplace-based: the Loop
    # has ~441k against ~25k employed residents). WRKCITY1..5 list where those workers live,
    # so their counts cannot exceed TOTEMPWRK; RESCITY1..5 list where the area's residents
    # work, so their counts cannot exceed the employed residents (ACS EMP).
    wrk = t[[f"WRKCITY{i}C" for i in range(1, 6)]].sum(axis=1)
    res = t[[f"RESCITY{i}C" for i in range(1, 6)]].sum(axis=1)
    rep["lehd_orientation"] = {
        "claim": "TOTEMPWRK = jobs in the area; sum(WRKCITY1..5C) <= TOTEMPWRK and sum(RESCITY1..5C) <= EMP",
        "holds": bool((wrk <= t["TOTEMPWRK"]).all() and (res <= t["EMP"]).all()),
        "max_wrk_top5_share_of_jobs": float((wrk / t["TOTEMPWRK"]).max()),
        "max_res_top5_share_of_employed": float((res / t["EMP"]).max()),
    }
    return rep


@lru_cache(maxsize=1)
def load_cds() -> CDS:
    path = ROOT / source("cds_2021")["file"]
    with open(path) as f:
        feats = json.load(f)["features"]
    rows = []
    for ft in feats:
        p = dict(ft["properties"])
        p["num"] = int(p["area_num_1"])
        rows.append(p)
    t = pd.DataFrame(rows).set_index("num").sort_index()
    t["name"] = t["GEOG"]

    # Frame origin: centroid of the city in UTM 16N.
    import shapely
    from shapely.geometry import shape
    city_ll = unary_union([shape(ft["geometry"]) for ft in feats])
    utm_city = shapely.transform(city_ll, lambda ll: np.column_stack(to_utm(ll[:, 0], ll[:, 1])))
    c = utm_city.centroid
    frame = LocalFrame(c.x, c.y)

    geoms = {int(ft["properties"]["area_num_1"]): frame.geometry(ft["geometry"]) for ft in feats}
    city = unary_union(list(geoms.values()))
    return CDS(table=t, geoms=geoms, city=city, frame=frame, identity_report=_identity_report(t))
