"""Crash safety layer: where serious crashes concentrate, ranked with empirical Bayes, and a
camera before/after slice (python -m simchi.safety.crashes).

PRE-REGISTERED DESIGN, W4 (fixed in this docstring and committed as "W4 pre-registration"
before any crash, fatality, camera or traffic-count values were downloaded or examined; only the
portal's column metadata had been read).

DATA (City of Chicago data portal, mirrored through simchi.portal.client, pinned by sha256 in
data/sources.toml; only aggregates are stored, never person-level records)
  crashes      85ca-t3if Traffic Crashes - Crashes, crash_date 2018-01-01 .. 2025-12-31
               (citywide reporting starts September 2017, so 2018 is the first full year)
  people       u6pd-qa9d Traffic Crashes - People, aggregated on the portal to counts per crash and
               person type of fatal and incapacitating injuries; context only
  deaths       gzaz-isa6 Vision Zero Chicago Traffic Fatalities: the official death count
  cameras      4i42-qv3h Speed Camera Locations, thvf-6diy Red Light Camera Locations (go-live dates)
  violations   hhkd-xvj4, spqx-js37, aggregated per camera and month; context only, never a layer
  volume       gc7y-n4xa Average Daily Traffic Counts (camera-derived, from 2020-10), mean daily
               count per counted segment over days before 2025-01-01 (training years only)
  streets      data/map/streets.json.gz (Street Center Lines pr57-gg9e, derived extract)
  Lanes: neither the street extract nor the centerline dataset has a lane count, and the crash
  records' lane_cnt exists only where crashes happened (using it would leak the outcome into the
  covariates). Lanes are therefore not in the model; this is reported, not filled in.

SITES
  Street classes 2 (arterial), 3 (collector), 4 (other street), 5 (named alley), 7 (tiered) are
  CPD streets. Classes 1 (expressway) and 9 (ramp) are not CPD's jurisdiction: excluded from the
  ranking and the test, drawn grey on the map, and their crashes reported separately.
  Intersection: a segment end point (coordinates to 5 decimals) shared by >= 3 segment ends; it is
  excluded only if every leg is class 1 or 9. Segment: one feature of the street extract.
  Snapping: a crash (or Vision Zero death) within 30 m of an intersection belongs to it; otherwise
  to the nearest non-river segment within 50 m; otherwise it is unsnapped (counted, reported).
  Distances in a local metric projection (the simulation frame, UTM 16N).

OUTCOME (serious crashes, "KA")
  K events: Vision Zero fatalities grouped into crashes (same crash_date to the minute and the same
            snapped site count as one fatal crash). Vision Zero, not the crash table, is the death
            count.
  A events: crash-table crashes with injuries_incapacitating >= 1 and injuries_fatal = 0.
  KA count of a site in a period = K events + A events snapped to it.

PERIODS
  Ranking (training)  2018-01-01 .. 2024-12-31
  Test                2025-01-01 .. 2025-12-31

MODEL
  Negative binomial (NB2: variance mu + alpha mu^2), fitted by maximum likelihood on every
  ranked site's 2018-2024 KA count (zeros included), with covariates:
    site type (intersection / segment);
    road class: segments by their class (2, 3, 4, other); intersections by the highest-order
      class among their legs, plus the number of legs (3, 4, >= 5);
    log segment length (segments; intersections 0);
    log average daily traffic where a count is snapped (within 30 m of the segment, or the
      largest count on any leg of an intersection), with a "volume missing" indicator.
  Empirical Bayes estimate per site: w = 1 / (1 + alpha mu), EB = w mu + (1 - w) y, with mu the
  model's expected 2018-2024 KA count and y the observed one.

TEST (primary)
  Three rankings of the ranked sites, top 100 each:
    EB      by the EB estimate (ties: site id)
    raw     by the 2018-2024 KA count (ties: 2018-2024 crashes of any severity, then site id)
    y2024   by the 2024 KA count (ties: 2024 crashes of any severity, then site id)
  Metric: share of 2025 KA events at ranked sites that occur at the ranking's top 100 sites.
  Pass: share(EB) > share(raw) and share(EB) > share(y2024).
  Reported, not criteria: the same shares for the top 50 and top 200; unsnapped and expressway
  2025 KA events; the fitted coefficients and alpha.

CAMERA SLICE (descriptive, no pass criterion)
  Cameras (speed and red-light separately) whose go-live date is in 2019-01-01 .. 2024-12-31, so
  12 full months before and after fall inside 2018-2025. Pre = the 12 calendar months before the
  go-live month; post = the 12 months after it (the go-live month itself is excluded).
  Counted: crashes (any severity) and KA crashes from the crash table within 660 ft (201.2 m) of
  the camera.
  Comparison pool: intersections with at least one class-2 leg and no speed or red-light camera
  (of any date) within 805 m (1/2 mile). Each camera is matched, with replacement, to the 3 pool
  intersections whose crash count within 201.2 m in the camera's pre window is closest (ties: site
  id), and those are counted over the camera's own pre and post windows.
  Estimate: ratio of ratios (sum post / sum pre at cameras) / (sum post / sum pre at comparisons),
  for all crashes and for KA, with a 95% interval from 2,000 bootstrap resamples of cameras
  (seed 0). Matching on the pre-period count limits, but does not remove, regression to the mean
  (cameras are sited where crashes were high). Violation counts are shown next to each camera as
  context, never as a separate layer or outcome.
"""

from __future__ import annotations  # noqa: E402  (after the pre-registration docstring)

import json
import math
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import gammaln

from simchi.paths import MIRROR, REPORTS

SAFETY = MIRROR / "safety"
TRAIN_YEARS = tuple(range(2018, 2025))
TEST_YEAR = 2025
TOP = 100
CAMERA_WINDOW = ("2019-01-01", "2024-12-31")
N_BOOT = 2000


# ----------------------------------------------------------------------------- outcome
def ka_table(site_year: pd.DataFrame, vz_site_year: pd.DataFrame) -> pd.DataFrame:
    """Per site: KA (Vision Zero fatal crashes + crash-table A crashes) and all crashes, for the
    training years, 2024 and 2025."""
    a = site_year.set_index(["site", "year"])
    k = vz_site_year.set_index(["site", "year"])["fatal_crashes"]
    idx = a.index.union(k.index)
    A = a["a_crashes"].reindex(idx).fillna(0)
    K = k.reindex(idx).fillna(0)
    C = a["crashes"].reindex(idx).fillna(0)
    df = pd.DataFrame({"ka": A + K, "k": K, "a": A, "crashes": C}).reset_index()
    tr = df[df["year"].isin(TRAIN_YEARS)].groupby("site")[["ka", "k", "a", "crashes"]].sum().add_suffix("_train")
    y24 = df[df["year"] == 2024].groupby("site")[["ka", "crashes"]].sum().add_suffix("_2024")
    y25 = df[df["year"] == TEST_YEAR].groupby("site")[["ka", "crashes"]].sum().add_suffix("_2025")
    return tr.join(y24, how="outer").join(y25, how="outer").fillna(0)


# ----------------------------------------------------------------------------- covariates
def design(sites: pd.DataFrame, site_adt: pd.DataFrame) -> pd.DataFrame:
    """Covariates of the NB model for the given (non-expressway) sites, by the W4 design."""
    adt = site_adt.set_index("site")["adt"] if len(site_adt) else pd.Series(dtype=float)
    seg = sites["type"] == "segment"
    vol = pd.Series(np.nan, index=sites.index)
    vol[seg] = adt.reindex(sites.index[seg]).to_numpy()
    legs = sites.loc[~seg, "leg_segments"]
    vol[~seg] = [max([adt.get(s, np.nan) for s in L if s in adt.index] or [np.nan]) for L in legs]
    cls = sites["cls"].astype(str)
    X = pd.DataFrame(index=sites.index)
    X["const"] = 1.0
    X["intersection"] = (~seg).astype(float)
    X["seg_class2"] = (seg & (cls == "2")).astype(float)
    X["seg_class3"] = (seg & (cls == "3")).astype(float)
    X["seg_class_other"] = (seg & ~cls.isin(["2", "3", "4"])).astype(float)
    X["int_class2"] = (~seg & (cls == "2")).astype(float)
    X["int_class3"] = (~seg & (cls == "3")).astype(float)
    X["int_legs4"] = (~seg & (sites["legs"] == 4)).astype(float)
    X["int_legs5p"] = (~seg & (sites["legs"] >= 5)).astype(float)
    X["log_length"] = np.where(seg, np.log(np.maximum(sites["length_m"].astype(float), 1.0)), 0.0)
    have = vol.notna() & (vol > 0)
    X["log_adt"] = np.where(have, np.log(vol.where(have, 1.0).astype(float)), 0.0)
    X["adt_missing"] = (~have).astype(float)
    X = X.loc[:, (X != 0).any(axis=0)]          # drop covariates absent in this sample (e.g. no 5-leg nodes)
    X.attrs["adt"] = vol
    return X


# ----------------------------------------------------------------------------- NB2 + EB
def _irls(X, y, alpha, beta0=None, iters=100, tol=1e-10):
    beta = np.zeros(X.shape[1]) if beta0 is None else beta0.copy()
    if beta0 is None:
        beta[0] = math.log(max(y.mean(), 1e-6))
    for _ in range(iters):
        eta = np.clip(X @ beta, -30, 30)
        mu = np.exp(eta)
        w = mu / (1 + alpha * mu)
        z = eta + (y - mu) / mu
        WX = X * w[:, None]
        new = np.linalg.solve(X.T @ WX + 1e-9 * np.eye(X.shape[1]), WX.T @ z)
        if np.max(np.abs(new - beta)) < tol:
            beta = new
            break
        beta = new
    return beta


def nb2_loglik(y, mu, alpha):
    r = 1.0 / alpha
    return float(np.sum(gammaln(y + r) - gammaln(r) - gammaln(y + 1) + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu))))


def nb2_fit(X: np.ndarray, y: np.ndarray) -> dict:
    """Maximum likelihood NB2: beta by IRLS for each alpha, alpha by a bounded 1-D search."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    cache = {}

    def negll(log_a):
        a = math.exp(log_a)
        b = _irls(X, y, a, cache.get("b"))
        cache["b"] = b
        return -nb2_loglik(y, np.exp(np.clip(X @ b, -30, 30)), a)

    res = minimize_scalar(negll, bounds=(-10, 5), method="bounded", options={"xatol": 1e-6})
    alpha = math.exp(res.x)
    beta = _irls(X, y, alpha, cache.get("b"))
    mu = np.exp(np.clip(X @ beta, -30, 30))
    return {"beta": beta, "alpha": alpha, "mu": mu, "loglik": nb2_loglik(y, mu, alpha)}


def empirical_bayes(mu, y, alpha):
    w = 1.0 / (1.0 + alpha * np.asarray(mu, float))
    return w * mu + (1 - w) * np.asarray(y, float), w


# ----------------------------------------------------------------------------- rankings and test
def top_k(ids, keys, k):
    """ids sorted by keys (list of arrays, each descending) then id ascending; first k."""
    ids = np.asarray(ids)
    order = np.lexsort([ids] + [-np.asarray(a, float) for a in reversed(keys)])
    return ids[order[:k]]


def captured(top, outcome: pd.Series) -> float:
    tot = float(outcome.sum())
    return float(outcome.reindex(top).fillna(0).sum()) / tot if tot > 0 else float("nan")


def rank_and_test(sites: pd.DataFrame, ka: pd.DataFrame, site_adt: pd.DataFrame) -> dict:
    ranked = sites[~sites["expressway"]]
    K = ka.reindex(ranked.index).fillna(0)
    X = design(ranked, site_adt)
    y = K["ka_train"].to_numpy(float)
    fit = nb2_fit(X.to_numpy(float), y)
    eb, w = empirical_bayes(fit["mu"], y, fit["alpha"])
    ids = ranked.index.to_numpy()
    ranks = {"EB": [eb], "raw": [y, K["crashes_train"].to_numpy(float)],
             "y2024": [K["ka_2024"].to_numpy(float), K["crashes_2024"].to_numpy(float)]}
    out = {"sites_ranked": int(len(ranked)), "ka_2025_at_ranked_sites": float(K["ka_2025"].sum()),
           "ka_train_at_ranked_sites": float(y.sum()), "alpha": fit["alpha"], "loglik": fit["loglik"],
           "coefficients": dict(zip(X.columns, map(float, fit["beta"]))),
           "sites_with_volume": int((X.get("adt_missing", pd.Series(0, index=X.index)) == 0).sum())}
    shares = {}
    tops = {}
    for k in (50, 100, 200):
        shares[k] = {}
        for name, keys in ranks.items():
            t = top_k(ids, keys, k)
            shares[k][name] = captured(t, K["ka_2025"])
            if k == TOP:
                tops[name] = list(map(str, t))
    s = shares[TOP]
    out["captured_share"] = {str(k): v for k, v in shares.items()}
    out["pass"] = bool(s["EB"] > s["raw"] and s["EB"] > s["y2024"])
    out["top100_overlap"] = {"EB_raw": len(set(tops["EB"]) & set(tops["raw"])), "EB_y2024": len(set(tops["EB"]) & set(tops["y2024"]))}
    site_out = pd.DataFrame({"eb": eb, "mu": fit["mu"], "w": w, "ka_train": y, "k_train": K["k_train"].to_numpy(),
                             "a_train": K["a_train"].to_numpy(), "crashes_train": K["crashes_train"].to_numpy(),
                             "ka_2025": K["ka_2025"].to_numpy(), "adt": X.attrs["adt"].to_numpy()}, index=ids)
    return out, site_out, tops


# ----------------------------------------------------------------------------- camera slice
def _months(go_live: str):
    g = pd.Period(go_live, "M")
    return [str(g - i) for i in range(12, 0, -1)], [str(g + i) for i in range(1, 13)]


def camera_slice(cameras: pd.DataFrame, radial: pd.DataFrame, pool: list, seed: int = 0, n_boot: int = N_BOOT) -> dict:
    R = radial.set_index(["point", "month"])[["crashes", "ka_crashes"]]

    def window(point, months, col):
        return float(R[col].reindex(pd.MultiIndex.from_product([[point], months])).fillna(0).sum())

    pool_pts = [f"site:{s}" for s in sorted(pool)]
    pool_month = {p: R.xs(p, level=0) if p in R.index.get_level_values(0) else None for p in pool_pts}
    out = {}
    for kind in ("speed", "red_light"):
        cams = cameras[(cameras["kind"] == kind) & (cameras["go_live"] >= CAMERA_WINDOW[0]) & (cameras["go_live"] <= CAMERA_WINDOW[1])
                       & cameras["lon"].notna()]
        rows = []
        for _, c in cams.iterrows():
            pre, post = _months(c["go_live"])
            pid = f"cam:{kind}:{c['camera']}"
            cp = {col: window(pid, pre, col) for col in ("crashes", "ka_crashes")}
            cq = {col: window(pid, post, col) for col in ("crashes", "ka_crashes")}
            # matched comparisons: 3 pool intersections closest in pre-window crash count (ties: site id)
            pc = np.array([float(pool_month[p]["crashes"].reindex(pre).fillna(0).sum()) if pool_month[p] is not None else 0.0 for p in pool_pts])
            order = np.lexsort([np.array(pool_pts), np.abs(pc - cp["crashes"])])[:3]
            m = [pool_pts[i] for i in order]
            mp = {col: sum(window(p, pre, col) for p in m) for col in ("crashes", "ka_crashes")}
            mq = {col: sum(window(p, post, col) for p in m) for col in ("crashes", "ka_crashes")}
            rows.append({"camera": c["camera"], "go_live": c["go_live"], "pre": cp["crashes"], "post": cq["crashes"],
                         "pre_ka": cp["ka_crashes"], "post_ka": cq["ka_crashes"], "cmp_pre": mp["crashes"], "cmp_post": mq["crashes"],
                         "cmp_pre_ka": mp["ka_crashes"], "cmp_post_ka": mq["ka_crashes"], "matched": m})
        df = pd.DataFrame(rows)
        res = {"cameras": int(len(df))}
        if len(df):
            rng = np.random.default_rng(seed)
            for lab, a, b, ca, cb in (("all_crashes", "pre", "post", "cmp_pre", "cmp_post"), ("ka", "pre_ka", "post_ka", "cmp_pre_ka", "cmp_post_ka")):
                def ror(d):
                    num = d[b].sum() / d[a].sum() if d[a].sum() > 0 else np.nan
                    den = d[cb].sum() / d[ca].sum() if d[ca].sum() > 0 else np.nan
                    return num / den if den and np.isfinite(den) and den > 0 else np.nan
                est = ror(df)
                boot = [ror(df.iloc[rng.integers(0, len(df), len(df))]) for _ in range(n_boot)]
                boot = np.array([x for x in boot if np.isfinite(x)])
                res[lab] = {"ratio_of_ratios": float(est), "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))] if len(boot) else None,
                            "camera_pre": float(df[a].sum()), "camera_post": float(df[b].sum()),
                            "comparison_pre": float(df[ca].sum()), "comparison_post": float(df[cb].sum()), "bootstrap_draws": int(len(boot))}
        out[kind] = res
        out[f"{kind}_cameras_table"] = df.drop(columns=["matched"]).to_dict("records") if len(df) else []
    return out


# ----------------------------------------------------------------------------- run
def load_mirror() -> dict:
    files = ("site_year", "vz_site_year", "radial_month", "cameras", "violations_month", "site_adt", "comparison_pool")
    D = {k: pd.read_csv(SAFETY / f"{k}.csv.gz", dtype={"site": str, "camera": str, "point": str}) for k in files}
    D["summary"] = json.loads((SAFETY / "summary.json").read_text())
    return D


def run() -> dict:
    from simchi.safety.mirror import load_sites
    D = load_mirror()
    S, _ = load_sites()
    ka = ka_table(D["site_year"], D["vz_site_year"])
    T = S.table
    test, site_out, tops = rank_and_test(T, ka, D["site_adt"])
    expr = T.index[T["expressway"]]
    ka_expr = ka.reindex(expr).fillna(0)
    cams = camera_slice(D["cameras"], D["radial_month"], D["comparison_pool"]["site"].astype(str).tolist())
    out = {"design": "W4 pre-registration, docstring of simchi/safety/crashes.py (commit cb367e0)",
           "train_years": [TRAIN_YEARS[0], TRAIN_YEARS[-1]], "test_year": TEST_YEAR, "top": TOP,
           "test": test, "top100": tops,
           "excluded_expressway": {"sites": int(len(expr)), "ka_train": float(ka_expr["ka_train"].sum()), "ka_2025": float(ka_expr["ka_2025"].sum())},
           "mirror": {k: v for k, v in D["summary"].items() if k != "queries"},
           "camera_slice": cams}
    return out, site_out, T


def main(argv=None):
    out, site_out, T = run()
    (REPORTS / "safety").mkdir(parents=True, exist_ok=True)
    with open(REPORTS / "safety" / "crash_ranking.json", "w") as f:
        json.dump(out, f, indent=1, default=float)
    keep = site_out[(site_out["ka_train"] > 0) | (site_out["ka_2025"] > 0) | site_out.index.isin(sum(out["top100"].values(), []))]
    keep = keep.join(T[["type", "cls", "name", "lon", "lat", "length_m"]])
    keep.to_csv(REPORTS / "safety" / "sites.csv.gz", index_label="site", compression={"method": "gzip", "mtime": 0}, float_format="%.5g")
    s = out["test"]["captured_share"][str(TOP)]
    print(f"top-{TOP} share of 2025 KA: EB {s['EB']:.4f}, raw {s['raw']:.4f}, 2024-only {s['y2024']:.4f} ->",
          "PASS" if out["test"]["pass"] else "FAIL")
    for kind in ("speed", "red_light"):
        print(kind, {k: v for k, v in out["camera_slice"][kind].items()})


if __name__ == "__main__":
    main(sys.argv[1:])
