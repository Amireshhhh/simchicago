"""Corridor-level crash concentration test, W4b (python -m simchi.safety.corridors).

PRE-REGISTERED DESIGN, W4b (committed as "W4b pre-registration" before any code read
location-level crash data dated 2026; W4 in simchi/safety/crashes.py is not modified)

CORRIDORS
  Built from the W4 sites (simchi/safety/sites.py; streets of classes 2, 3, 4, 5, 7; expressways
  1 and 9 excluded as not CPD jurisdiction).
  A corridor is a maximal chain of segments with the same street name joined end to end through
  intersections, split at every intersection where the street crosses or meets an arterial (class
  2) segment of a different name (the arterial grid). Each segment belongs to exactly one corridor.
  Intersections: each belongs to the corridor of its highest-order leg (class order 2, 3, 4, 7, 5;
  ties by street name, then corridor id), so no crash is counted twice. Corridor id: the street name
  and the rank of its first segment (by site id) among that street's corridors.
  Bus-corridor subset: corridors of which at least 50% of the length lies within 20 m of a CTA bus
  route shape (GTFS extract), reported separately (not part of the criterion).

OUTCOME
  KA events as in W4: Vision Zero fatal crashes (deaths in the same minute at the same site are one
  crash) plus crash-table crashes with an incapacitating injury and no fatality, snapped to sites by
  the W4 rule, summed over the corridor's sites.
  Vision Zero is updated monthly; test-period K events come from Vision Zero up to its last
  available crash date at mirror time, and from crash-table crashes with injuries_fatal >= 1 for
  dates after it (both recorded in the report).

PERIODS
  Ranking 2018-01-01 .. 2025-12-31 (Vision Zero begins 2019-01-03, as reported for W4)
  Test    2026-01-01 .. 2026-10-31

RANKINGS (top k = 25, 50, 100 corridors)
  EB      negative binomial (NB2, maximum likelihood) of 2018-2025 corridor KA on: highest street
          class (2, 3, other), log length, log(1 + number of intersections), log of the largest
          traffic count on the corridor (W4 site_adt) with a volume-missing indicator; empirical
          Bayes estimate w mu + (1 - w) y, w = 1 / (1 + alpha mu). Ties: corridor id.
  raw     2018-2025 KA (ties: 2018-2025 crashes of any severity, then corridor id)
  y2025   2025 KA (ties: 2025 crashes of any severity, then corridor id)
  Metric: share of test-period KA events at ranked corridors that fall in a ranking's top k.
  PASS: share(EB) > share(raw) and share(EB) > share(y2025) at top 50.
  Reported, not criteria: the shares at 25 and 100, the same for the bus-corridor subset, the
  number of corridors and their length distribution, the model's coefficients and alpha.

LIMITS stated in advance
  Crash reports for recent months are still being added when mirrored, so the test period's last
  weeks may be undercounted (equally for all rankings). Corridor boundaries follow names in the
  City street centerline file.
"""

from __future__ import annotations  # noqa: E402  (after the pre-registration docstring)

import gzip
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from simchi.paths import DATA, MIRROR, REPORTS
from simchi.safety import crashes as C
from simchi.safety.sites import CLASS_ORDER, EXPRESSWAY, STREET_CLASSES

TEST = ("2026-01-01", "2026-10-31")
TOPS = (25, 50, 100)
TEST_FILE = MIRROR / "safety" / "w4b_test_sites.csv.gz"
TEST_SUMMARY = MIRROR / "safety" / "w4b_test_summary.json"


# ----------------------------------------------------------------------------- corridors
def build_corridors(streets_fc: dict, sites_table: pd.DataFrame) -> pd.Series:
    """site id -> corridor id, by the W4b rule (segments chained by name, split at the arterial grid;
    intersections to their highest-order leg)."""
    seg_name, seg_cls, nodes = {}, {}, {}
    for k, f in enumerate(streets_fc["features"]):
        c = str(f["properties"].get("c"))
        if c not in STREET_CLASSES or c in EXPRESSWAY:
            continue
        sid = f"s{k}"
        seg_name[sid], seg_cls[sid] = f["properties"].get("n", ""), c
        co = f["geometry"]["coordinates"]
        for end in (co[0], co[-1]):
            nodes.setdefault((round(float(end[0]), 5), round(float(end[1]), 5)), []).append(sid)
    parent = {s: s for s in seg_name}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for segs in nodes.values():
        for i, a in enumerate(segs):
            for b in segs[i + 1:]:
                if seg_name[a] != seg_name[b] or not seg_name[a]:
                    continue
                split = any(seg_cls[o] == "2" and seg_name[o] != seg_name[a] for o in segs)
                if not split:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[max(ra, rb, key=_sid_num)] = min(ra, rb, key=_sid_num)
    groups = {}
    for s in seg_name:
        groups.setdefault(find(s), []).append(s)
    corr, rank = {}, {}
    for root, members in sorted(groups.items(), key=lambda kv: _sid_num(min(kv[1], key=_sid_num))):
        name = seg_name[root]
        rank[name] = rank.get(name, 0) + 1
        cid = f"{name or '(unnamed)'} #{rank[name]}"
        for s in members:
            corr[s] = cid
    T = sites_table
    inter = T[(T["type"] == "intersection") & ~T["expressway"].astype(bool)]
    for sid, legs in zip(inter.index, inter["leg_segments"], strict=True):
        cand = [(CLASS_ORDER.get(seg_cls[l], 9), seg_name[l], corr[l]) for l in legs if l in corr]
        if cand:
            corr[sid] = min(cand)[2]
    return pd.Series(corr, name="corridor")


def _sid_num(s: str) -> int:
    return int(s[1:])


def corridor_table(corr: pd.Series, sites_table: pd.DataFrame, site_adt: pd.DataFrame, bus_flag: pd.Series) -> pd.DataFrame:
    T = sites_table.loc[corr.index]
    adt = site_adt.set_index("site")["adt"] if len(site_adt) else pd.Series(dtype=float)
    df = pd.DataFrame({"corridor": corr.values, "type": T["type"].values, "cls": T["cls"].astype(str).values,
                       "length_m": T["length_m"].astype(float).values, "adt": adt.reindex(corr.index).values,
                       "bus": bus_flag.reindex(corr.index).fillna(False).astype(bool).values}, index=corr.index)
    seg = df[df["type"] == "segment"]
    g = seg.groupby("corridor").agg(length_m=("length_m", "sum"), adt=("adt", "max"),
                                    top_cls=("cls", lambda c: min(c, key=lambda x: CLASS_ORDER.get(x, 9))))
    g["bus_share"] = seg.assign(bl=seg["length_m"] * seg["bus"]).groupby("corridor")["bl"].sum() / g["length_m"].where(g["length_m"] > 0)
    g["intersections"] = df[df["type"] == "intersection"].groupby("corridor").size().reindex(g.index).fillna(0).astype(int)
    return g


def design(g: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=g.index)
    X["const"] = 1.0
    X["cls2"] = (g["top_cls"] == "2").astype(float)
    X["cls3"] = (g["top_cls"] == "3").astype(float)
    X["log_length"] = np.log(np.maximum(g["length_m"].to_numpy(float), 1.0))
    X["log_intersections"] = np.log1p(g["intersections"].to_numpy(float))
    have = g["adt"].notna() & (g["adt"] > 0)
    X["log_adt"] = np.where(have, np.log(g["adt"].where(have, 1.0).astype(float)), 0.0)
    X["adt_missing"] = (~have).astype(float)
    return X.loc[:, (X != 0).any(axis=0)]


def rank_and_score(g: pd.DataFrame, y_train, crashes_train, y2025, crashes2025, y_test, tops=TOPS) -> dict:
    """Rankings of corridors g (index = corridor id) and their top-k shares of test-period KA."""
    ids = g.index.to_numpy()
    X = design(g)
    y = np.asarray(y_train, float)
    fit = C.nb2_fit(X.to_numpy(float), y)
    eb, _ = C.empirical_bayes(fit["mu"], y, fit["alpha"])
    yt = pd.Series(np.asarray(y_test, float), index=ids)
    keys = {"EB": [eb], "raw": [y, np.asarray(crashes_train, float)], "y2025": [np.asarray(y2025, float), np.asarray(crashes2025, float)]}
    shares = {str(k): {n: C.captured(C.top_k(ids, kk, k), yt) for n, kk in keys.items()} for k in tops}
    return {"corridors": int(len(ids)), "ka_test": float(yt.sum()), "ka_train": float(y.sum()), "alpha": fit["alpha"],
            "coefficients": dict(zip(X.columns, map(float, fit["beta"]))), "captured_share": shares,
            "top50": {n: list(map(str, C.top_k(ids, kk, 50))) for n, kk in keys.items()}}


# ----------------------------------------------------------------------------- test-period mirror
def mirror_test(portal=None) -> dict:
    """Mirror the test period (2026-01-01 .. 2026-10-31) as per-site aggregates (no person-level data)."""
    from simchi.portal.client import Portal
    from simchi.safety.mirror import _xy, load_sites
    portal = portal or Portal(cache_dir=Path(tempfile.gettempdir()) / "simchi-portal-cache")
    w = f"crash_date >= '{TEST[0]}T00:00:00' AND crash_date <= '{TEST[1]}T23:59:59'"
    cr = portal.query("85ca-t3if", select="crash_record_id, crash_date, latitude, longitude, injuries_fatal, injuries_incapacitating", where=w)
    vz = portal.query("gzaz-isa6", select="crash_date, latitude, longitude", where=w)
    sites, frame = load_sites()
    for d in (cr, vz):
        d["crash_date"] = pd.to_datetime(d["crash_date"])
        x, z = _xy(frame, d["longitude"], d["latitude"])
        d["site"] = sites.snap(x, z)
    for k in ("injuries_fatal", "injuries_incapacitating"):
        cr[k] = pd.to_numeric(cr[k], errors="coerce").fillna(0)
    vz_last = vz["crash_date"].max() if len(vz) else pd.Timestamp(TEST[0]) - pd.Timedelta(days=1)
    cr["a"] = (cr["injuries_incapacitating"] >= 1) & (cr["injuries_fatal"] == 0)
    cr["k_after_vz"] = (cr["injuries_fatal"] >= 1) & (cr["crash_date"].dt.normalize() > vz_last.normalize())
    vz["minute"] = vz["crash_date"].dt.floor("min")
    k = vz[vz["site"].notna()].groupby("site")["minute"].nunique().rename("k_vz")
    c = cr[cr["site"].notna()].groupby("site").agg(crashes=("crash_record_id", "size"), a=("a", "sum"), k_after_vz=("k_after_vz", "sum"))
    out = c.join(k, how="outer").fillna(0).astype(int).reset_index().rename(columns={"index": "site"})
    TEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(TEST_FILE, index=False, compression={"method": "gzip", "mtime": 0})
    summ = {"test_period": TEST, "crashes": int(len(cr)), "crashes_unsnapped": int(cr["site"].isna().sum()),
            "crash_date_max": str(cr["crash_date"].max()), "vision_zero_deaths": int(len(vz)), "vision_zero_last": str(vz_last),
            "ka_a": int(cr["a"].sum()), "k_after_vz_crash_table": int(cr["k_after_vz"].sum()),
            "downloaded": datetime.now(timezone.utc).date().isoformat(), "queries": {"crashes": w, "vision_zero": w}}
    TEST_SUMMARY.write_text(json.dumps(summ, indent=1))
    return summ


# ----------------------------------------------------------------------------- run
def run() -> dict:
    from simchi.safety.export import bus_flags
    from simchi.safety.mirror import load_sites
    D = C.load_mirror()
    S, frame = load_sites()
    with gzip.open(DATA / "map" / "streets.json.gz", "rt") as fh:
        streets = json.load(fh)
    corr = build_corridors(streets, S.table)
    T = S.table
    bus = pd.Series(bus_flags(T.loc[corr.index, "lon"], T.loc[corr.index, "lat"], frame), index=corr.index)
    g = corridor_table(corr, T, D["site_adt"], bus)
    # training KA per site: W4's table with 2025 counted in the ranking period
    sy, vz = D["site_year"], D["vz_site_year"]
    a = sy.set_index(["site", "year"])
    kk = vz.set_index(["site", "year"])["fatal_crashes"]
    idx = a.index.union(kk.index)
    site_year = pd.DataFrame({"ka": a["a_crashes"].reindex(idx).fillna(0) + kk.reindex(idx).fillna(0),
                              "crashes": a["crashes"].reindex(idx).fillna(0)}).reset_index()
    site_year["corridor"] = site_year["site"].map(corr)
    site_year = site_year[site_year["corridor"].notna()]
    tr = site_year[site_year["year"].between(2018, 2025)].groupby("corridor")[["ka", "crashes"]].sum()
    y25 = site_year[site_year["year"] == 2025].groupby("corridor")[["ka", "crashes"]].sum()
    t = pd.read_csv(TEST_FILE, dtype={"site": str})
    t["corridor"] = t["site"].map(corr)
    t["ka"] = t["a"] + t["k_vz"] + t["k_after_vz"]
    yt = t[t["corridor"].notna()].groupby("corridor")["ka"].sum()
    out = {"design": "W4b pre-registration, docstring of simchi/safety/corridors.py (commit 961b085)", "test_period": TEST,
           "mirror": json.loads(TEST_SUMMARY.read_text()),
           "corridor_length_m": {q: float(g["length_m"].quantile(q)) for q in (0.1, 0.5, 0.9)}}
    for name, sub in (("all", g), ("bus", g[g["bus_share"] >= 0.5])):
        r = rank_and_score(sub, tr["ka"].reindex(sub.index).fillna(0), tr["crashes"].reindex(sub.index).fillna(0),
                           y25["ka"].reindex(sub.index).fillna(0), y25["crashes"].reindex(sub.index).fillna(0),
                           yt.reindex(sub.index).fillna(0))
        out[name] = r
    s50 = out["all"]["captured_share"]["50"]
    out["pass"] = bool(s50["EB"] > s50["raw"] and s50["EB"] > s50["y2025"])
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--mirror" in argv:
        print(json.dumps(mirror_test(), indent=1))
        return
    out = run()
    (REPORTS / "safety").mkdir(parents=True, exist_ok=True)
    (REPORTS / "safety" / "corridors.json").write_text(json.dumps(out, indent=1, default=float))
    for k in ("25", "50", "100"):
        print(k, {n: round(v, 4) for n, v in out["all"]["captured_share"][k].items()}, "bus:", {n: round(v, 4) for n, v in out["bus"]["captured_share"][k].items()})
    print("PASS" if out["pass"] else "FAIL", out["all"]["corridors"], "corridors;", out["bus"]["corridors"], "bus corridors")


if __name__ == "__main__":
    main()
