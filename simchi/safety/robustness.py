"""Robustness of the crash concentration finding, D (python -m simchi.safety.robustness).

PRE-REGISTERED DESCRIPTIVE CHECKS (committed as "D pre-registration" before they were computed;
no pass or fail: these describe how concentrated serious crashes are, they test nothing)

The W4 finding: the top 100 of 76,522 ranked sites held under 5% of 2025's serious (KA) crashes.
These checks ask whether that holds in other years and for other units. Data, sites, outcome and
the NB2/empirical Bayes model are W4's (simchi/safety/crashes.py); 2019-2024 were W4's training
years, so nothing here is out of sample in the sense of an unseen period.

For each test year Y in 2019 .. 2024, rank on all years 2018 .. Y-1 and report, for k = 100:
  all sites          share of year-Y KA events at ranked sites captured by the top k, ranked by
                     (a) empirical Bayes (NB2 refitted on 2018 .. Y-1) and (b) raw count
                     (ties as in W4); this is W4's design moved back in time
  segments per mile  segments only, ranked by KA per mile, (a) EB / length and (b) raw count /
                     length, segments shorter than 100 m excluded (a few metres would make any single
                     crash a huge rate); share of year-Y segment KA events in the top k
  intersections      intersections only, (a) EB and (b) raw count; share of year-Y intersection
                     KA events in the top k
Also reported: the share of ranked units holding any KA event in year Y, and the top-k share an
oracle would reach (the k units with most year-Y KA), as the ceiling.
Output: reports/safety/robustness.json and a table in docs/EVALUATION.md.
"""

from __future__ import annotations  # noqa: E402  (after the pre-registration docstring)

import json
import sys

import numpy as np
import pandas as pd

from simchi.paths import REPORTS
from simchi.safety import crashes as C

YEARS = tuple(range(2019, 2025))
K = 100
MIN_SEG_M = 100.0


def site_year_ka(site_year: pd.DataFrame, vz_site_year: pd.DataFrame) -> pd.DataFrame:
    a = site_year.set_index(["site", "year"])
    k = vz_site_year.set_index(["site", "year"])["fatal_crashes"]
    idx = a.index.union(k.index)
    return pd.DataFrame({"ka": a["a_crashes"].reindex(idx).fillna(0) + k.reindex(idx).fillna(0),
                         "crashes": a["crashes"].reindex(idx).fillna(0)}).reset_index()


def shares_for(ids, keys: dict, outcome: pd.Series, k: int = K) -> dict:
    out = {n: C.captured(C.top_k(ids, kk, k), outcome) for n, kk in keys.items()}
    out["oracle"] = C.captured(C.top_k(ids, [outcome.reindex(ids).fillna(0).to_numpy()], k), outcome)
    out["share_of_units_with_any"] = float((outcome.reindex(ids).fillna(0) > 0).mean())
    out["units"] = int(len(ids))
    out["events"] = float(outcome.reindex(ids).fillna(0).sum())
    return out


def year_checks(sites: pd.DataFrame, sy: pd.DataFrame, site_adt: pd.DataFrame, Y: int, k: int = K) -> dict:
    ranked = sites[~sites["expressway"]]
    ids = ranked.index.to_numpy()
    tr = sy[(sy["year"] >= 2018) & (sy["year"] < Y)].groupby("site")[["ka", "crashes"]].sum().reindex(ids).fillna(0)
    yt = sy[sy["year"] == Y].groupby("site")["ka"].sum().reindex(ids).fillna(0)
    X = C.design(ranked, site_adt)
    y = tr["ka"].to_numpy(float)
    fit = C.nb2_fit(X.to_numpy(float), y)
    eb, _ = C.empirical_bayes(fit["mu"], y, fit["alpha"])
    eb = pd.Series(eb, index=ids)
    out = {"train_years": [2018, Y - 1], "test_year": Y, "alpha": fit["alpha"]}
    out["all_sites"] = shares_for(ids, {"EB": [eb.to_numpy()], "raw": [y, tr["crashes"].to_numpy(float)]}, yt, k)
    seg = ranked[(ranked["type"] == "segment") & (ranked["length_m"].astype(float) >= MIN_SEG_M)]
    sid = seg.index.to_numpy()
    miles = seg["length_m"].astype(float).to_numpy() / 1609.344
    out["segments_per_mile"] = shares_for(sid, {"EB": [eb[sid].to_numpy() / miles, tr.loc[sid, "ka"].to_numpy()],
                                                "raw": [tr.loc[sid, "ka"].to_numpy() / miles, tr.loc[sid, "ka"].to_numpy()]}, yt[sid], k)
    it = ranked[ranked["type"] == "intersection"].index.to_numpy()
    out["intersections"] = shares_for(it, {"EB": [eb[it].to_numpy()], "raw": [tr.loc[it, "ka"].to_numpy(), tr.loc[it, "crashes"].to_numpy()]}, yt[it], k)
    return out


def main(argv=None):
    from simchi.safety.mirror import load_sites
    D = C.load_mirror()
    S, _ = load_sites()
    sy = site_year_ka(D["site_year"], D["vz_site_year"])
    res = {"design": "D pre-registration, docstring of simchi/safety/robustness.py (commit 8d9650a)", "k": K,
           "label": "descriptive, not causal; no pass or fail", "years": [year_checks(S.table, sy, D["site_adt"], Y) for Y in YEARS]}
    (REPORTS / "safety").mkdir(parents=True, exist_ok=True)
    (REPORTS / "safety" / "robustness.json").write_text(json.dumps(res, indent=1, default=float))
    for r in res["years"]:
        print(r["test_year"], {u: {n: round(r[u][n], 4) for n in ("EB", "raw", "oracle")} for u in ("all_sites", "segments_per_mile", "intersections")})


if __name__ == "__main__":
    main(sys.argv[1:])
