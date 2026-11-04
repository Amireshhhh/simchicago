"""Census tracts (2010) with 2014 indicators, used to place homes inside community areas."""

from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from simchi.data.cds import load_cds, source
from simchi.paths import ROOT


@lru_cache(maxsize=1)
def load_tracts() -> tuple[pd.DataFrame, dict]:
    frame = load_cds().frame
    with open(ROOT / source("sdoh_tracts_2014")["file"]) as f:
        feats = json.load(f)["features"]
    rows, geoms = [], {}
    for ft in feats:
        p = ft["properties"]
        gid = int(p["geoid10"])
        rows.append({"geoid": gid, "area": int(p["commarea"]), "pop2014": float(p["Pop2014"] or 0),
                     "novehicle_pct": p["EP_NOVEH"], "cta_commute_pct": p["CTA14P"],
                     "commute_min": p["CmTm14"], "violent_crime_rate_2015": p["VCRIMERT15"]})
        geoms[gid] = frame.geometry(ft["geometry"])
    return pd.DataFrame(rows).set_index("geoid"), geoms
