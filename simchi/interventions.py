"""Transit intervention experiments and their ranking (python -m simchi.interventions).

Each intervention changes the CTA network (headways, in-vehicle times, waits, fares) and is run
on R synthetic populations (build seeds 1..R, 2,000 requested agents each) against the scheduled
network; effects are paired differences over the R populations with 95% t-intervals. Riders
respond only through the network-based mode choice (no manual mode shift).

Metrics
  transit_trips, car_trips      population-weighted trips on a simulated weekday (simulated)
  car_pkm                       car person-km per weekday (simulated; a vehicle-km proxy)
  time_saved_min                person-minutes per weekday saved by residents who commute by
                                transit in the baseline (2 trips x change in the AM-peak skim's
                                walk + wait + in-vehicle minutes between home and work areas)
  low_income_share_of_savings   share of time_saved_min going to residents of the
                                lowest-income areas (areas with the lowest ACS median household
                                income holding 25% of the population); compare with 0.25
  access_jobs_45                population-weighted mean of jobs reachable within 45 min by
                                transit (AM peak; night band and 60 min for late-night service),
                                share of zone-point pairs within the limit x destination jobs
  access_gain_low / _other      the same change for the low-income areas / the other areas
Cost proxy (scheduled, deterministic)
  vehicle_hours                 change in scheduled weekday vehicle-hours: for every pattern and
                                time band, trips x run time, with trips / headway multiplier and run
                                time x in-vehicle multiplier, in the bands the intervention touches
  revenue                       change in weekday fare revenue (fare interventions): mean fare x
                                transit trips (passes, transfers and reduced fares ignored; rough)
Ranking
  service changes that add vehicle-hours: transit trips gained per 1,000 added weekday
  vehicle-hours (with the interval of the trips effect; the cost is deterministic)
  changes that save vehicle-hours (bus priority) are listed as such: their capital cost is not
  modelled; fare changes: transit trips gained per $1,000 of weekday revenue forgone.
Effect sizes that are assumptions are labelled hypothesis in INTERVENTIONS.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
from scipy import stats

from simchi import jsonutil
from simchi.paths import REPORTS
from simchi.transit import network as N
from simchi.transit.gtfs import BANDS, load_extract

ALL_BANDS = tuple(BANDS)
ACCESS_MIN = {"am_peak": 45.0, "night": 60.0}


def top_bus_routes(k: int = 10) -> list:
    from simchi.transit.ridership import load_observed, weekday_means
    m = weekday_means(load_observed("bus"), "2024-01-01", "2024-12-31")
    gtfs = {r["id"] for r in load_extract("routes") if r["type"] == 3}
    return [r for r in m.sort_values(ascending=False).index if r in gtfs][:k]


def interventions(top: list) -> list:
    t = {r: 0.75 for r in top}
    return [
        {"name": "Frequent network: top-10 bus routes, headways x0.75", "network": {"headway_multiplier": t},
         "bands": ALL_BANDS, "kind": "service", "provenance": "scenario (routes chosen by 2024 ridership)"},
        {"name": "All buses: headways x0.8", "network": {"headway_multiplier": {"bus": 0.8}}, "bands": ALL_BANDS,
         "kind": "service", "provenance": "scenario"},
        {"name": "All 'L' lines: headways x0.8", "network": {"headway_multiplier": {"rail": 0.8}}, "bands": ALL_BANDS,
         "kind": "service", "provenance": "scenario"},
        {"name": "Bus priority on the top-10 routes: in-vehicle time x0.85", "network": {"ivt_multiplier": {r: 0.85 for r in top}},
         "bands": ALL_BANDS, "kind": "priority", "provenance": "hypothesis (15% faster from lanes / signal priority; not estimated)"},
        {"name": "Bus reliability: waits x0.853 (headway CV 0.6 -> 0.4)", "network": {"wait_multiplier": {"bus": (1 + 0.4 ** 2) / (1 + 0.6 ** 2)}},
         "bands": (), "kind": "reliability", "provenance": "hypothesis (random arrivals: mean wait = H (1 + CV^2) / 2; CVs assumed, not observed yet)"},
        {"name": "Late-night service: night headways x0.5 (11 pm - 4 am)", "network": {"headway_multiplier": {"bus": 0.5, "rail": 0.5}},
         "bands": ("night",), "kind": "service", "access_band": "night", "behaviour": False,
         "provenance": "scenario; the mode-choice model is an AM-peak commute model, so only night accessibility and cost are computed"},
        {"name": "Fares -$0.50", "network": {"fare_bus": N.FARE_BUS - 0.5, "fare_rail": N.FARE_RAIL - 0.5}, "bands": (),
         "kind": "fare", "provenance": "scenario; response from an assumed value of time ($15/h)"},
        {"name": "Fare-free CTA", "network": {"fare_bus": 0.0, "fare_rail": 0.0}, "bands": (), "kind": "fare",
         "provenance": "scenario; response from an assumed value of time ($15/h), linear in fare"},
    ]


def network_scenario(net: dict, band="am_peak") -> N.NetworkScenario:
    return N.NetworkScenario(headway_multiplier=dict(net.get("headway_multiplier", {})),
                             ivt_multiplier=dict(net.get("ivt_multiplier", {})),
                             wait_multiplier=dict(net.get("wait_multiplier", {})),
                             fare_bus=float(net.get("fare_bus", N.FARE_BUS)), fare_rail=float(net.get("fare_rail", N.FARE_RAIL)),
                             removed_stops={r: tuple(v) for r, v in net.get("removed_stops", {}).items()},
                             stop_saving_s=float(net.get("stop_saving_s", 0.0)), band=band)


def vehicle_hours(sc: N.NetworkScenario, bands) -> float:
    """Scheduled weekday vehicle-hours over `bands` (multipliers applied) - same without them."""
    routes = {r["id"]: r["type"] == 1 for r in load_extract("routes")}
    base = new = 0.0
    for p in load_extract("patterns"):
        rail = routes[p["route"]]
        hm = sc.factor(sc.headway_multiplier, p["route"], rail)
        im = sc.factor(sc.ivt_multiplier, p["route"], rail)
        gone = set(sc.removed_stops.get(p["route"], ()))
        skipped = sum(1 for s_ in p["stops"][1:-1] if s_ in gone)
        for band in bands:
            n = p.get("trips_band", {}).get("weekday", {}).get(band, 0)
            off = p["offsets_min"].get(band)
            if not n or off is None:
                continue
            rt = off[-1] / 60.0
            base += n * rt
            new += n / hm * max(rt * im - skipped * sc.stop_saving_s / 3600.0, 0.0)
    return new - base


def reach_fraction(sc: N.NetworkScenario, limit: float) -> np.ndarray:
    """(77, 77) share of zone-point pairs (i, j) connected by transit within `limit` minutes."""
    g = N._graph()
    G, wn, iv = g.matrix(sc)
    nz = len(g.zone_xy)
    K = g.K
    nA = g.world.n_areas
    out = np.zeros((nA, nA))
    for s0 in range(0, nz, 48):
        src = np.arange(s0, min(nz, s0 + 48))
        comp, _ = g.point_components(sc, src, G, wn, iv)
        T = comp[0] + comp[1] + comp[2]                     # walk + wait + ivt (inf if unreachable)
        ok = (np.isfinite(comp[-1]) & (T <= limit))[:, :nA * K].reshape(len(src), nA, K).mean(2)
        np.add.at(out, src // K, ok)
    return out / K


def low_income_areas(world) -> np.ndarray:
    t = world.cds.table
    order = np.argsort(t["MEDINC"].to_numpy(float))
    pop = t["TOT_POP"].to_numpy(float)[order]
    cum = np.cumsum(pop) / pop.sum()
    low = np.zeros(len(t), bool)
    low[order[cum <= 0.25 + 1e-12]] = True
    return low


def accessibility(world, frac: np.ndarray) -> np.ndarray:
    return frac @ world.areas["jobs"].to_numpy(float)


def _ci(x):
    x = np.asarray(x, float)
    n = len(x)
    m = float(x.mean())
    if n < 2:
        return {"mean": m, "ci_low": float("nan"), "ci_high": float("nan")}
    h = float(stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n))
    return {"mean": m, "ci_low": m - h, "ci_high": m + h}


def run(R: int = 10, n: int = 2000, ivs: list | None = None) -> dict:
    from simchi.experiments import make_config
    from simchi.pipeline import build
    from simchi.sim.engine import _choose_modes, run_sim, scenario_skim
    from simchi.world import build_world

    world = build_world()
    top = top_bus_routes()
    ivs = ivs if ivs is not None else interventions(top)
    low = low_income_areas(world)
    pop = world.cds.table["TOT_POP"].to_numpy(float)

    # deterministic parts: cost, accessibility
    det = []
    base_acc = {}
    for band in ("am_peak", "night"):
        base_acc[band] = accessibility(world, reach_fraction(N.NetworkScenario(band=band), ACCESS_MIN[band]))
    for iv in ivs:
        band = iv.get("access_band", "am_peak")
        sc = network_scenario(iv["network"], band)
        acc = accessibility(world, reach_fraction(sc, ACCESS_MIN[band]))
        d = acc - base_acc[band]
        det.append({"vehicle_hours": vehicle_hours(sc, iv["bands"]),
                    "access_band": band, "access_limit_min": ACCESS_MIN[band],
                    "access_jobs": float((pop * d).sum() / pop.sum()),
                    "access_gain_low": float((pop[low] * d[low]).sum() / pop[low].sum()),
                    "access_gain_other": float((pop[~low] * d[~low]).sum() / pop[~low].sum()),
                    "access_base": float((pop * base_acc[band]).sum() / pop.sum())})

    rows = []
    base_cfg = {"n_days": 1, "incident_mode": "none", "start_date": "2020-10-06"}      # a Tuesday
    for seed in range(1, R + 1):
        b = build(n, seed)
        P = b.persons
        cfg0 = make_config(base_cfg, {}, seed)
        sk0 = scenario_skim(b, cfg0)
        m0 = _choose_modes(b, cfg0, sk0)
        s0 = run_sim(b, cfg0).daily[0]
        employed = (P["labor"] == 0).to_numpy()
        wfh = employed & (P["u_wfh"].to_numpy() < np.clip(P["p_wfh"].to_numpy(), 0, 1))
        rider = employed & ~wfh & np.isfinite(P["work_x"].to_numpy()) & (m0 == 3)
        hi_ = P["area"].to_numpy() - 1
        wj = np.clip(P["work_area"].to_numpy() - 1, 0, None)
        w = P["weight"].to_numpy()
        lowp = low[hi_]
        tr_trips0 = s0["trips_weighted"]["transit"]
        for k, iv in enumerate(ivs):
            row = {"seed": seed, "intervention": k}
            if iv.get("behaviour", True):
                over = {}
                for a, v in iv["network"].items():
                    if a in ("removed_stops", "stop_saving_s"):
                        continue                                    # set on the config directly below
                    if isinstance(v, dict):
                        for kk, vv in v.items():
                            over[f"network.{a}.{kk}"] = vv
                    else:
                        over[f"network.{a}"] = v
                cfg = make_config(base_cfg, over, seed)
                for a in ("removed_stops", "stop_saving_s"):
                    if a in iv["network"]:
                        cfg.network[a] = iv["network"][a]
                sk = scenario_skim(b, cfg)
                s1 = run_sim(b, cfg).daily[0]
                saved = 2.0 * (sk0.total[hi_, wj] - sk.total[hi_, wj]) * rider * w
                row.update({"transit_trips": s1["trips_weighted"]["transit"] - tr_trips0,
                            "car_trips": s1["trips_weighted"]["car"] - s0["trips_weighted"]["car"],
                            "car_pkm": s1["pkm_weighted"]["car"] - s0["pkm_weighted"]["car"],
                            "time_saved_min": float(saved.sum()),
                            "low_income_share_of_savings": float(saved[lowp].sum() / saved.sum()) if abs(saved.sum()) > 1e-9 else float("nan")})
                if iv["kind"] == "fare":
                    fare0 = float((sk0.fare[hi_, wj] * rider * w).sum() / (rider * w).sum())
                    fare1 = float((sk.fare[hi_, wj] * rider * w).sum() / (rider * w).sum())
                    row["revenue"] = fare1 * s1["trips_weighted"]["transit"] - fare0 * tr_trips0
            rows.append(row)
    df = pd.DataFrame(rows)
    out = []
    for k, iv in enumerate(ivs):
        d = df[df["intervention"] == k]
        r = {"name": iv["name"], "kind": iv["kind"], "provenance": iv["provenance"], **det[k], "replicates": int(len(d))}
        for m in ("transit_trips", "car_trips", "car_pkm", "time_saved_min", "low_income_share_of_savings", "revenue"):
            if m in d and d[m].notna().any():
                r[m] = _ci(d[m].dropna())
        vh = det[k]["vehicle_hours"]
        if "transit_trips" in r:
            if iv["kind"] == "fare" and "revenue" in r and r["revenue"]["mean"] < 0:
                per = 1000.0 / -r["revenue"]["mean"]
                r["trips_per_1000_dollars"] = {kk: v * per for kk, v in r["transit_trips"].items()}
            elif vh > 1e-9:
                r["trips_per_1000_vehicle_hours"] = {kk: v * 1000.0 / vh for kk, v in r["transit_trips"].items()}
        out.append(r)
    return {"label": "simulated (behaviour) and scheduled (cost)", "replicates": R, "agents_requested": n,
            "top_bus_routes": top, "low_income_population_share": float(pop[low].sum() / pop.sum()),
            "low_income_areas": [int(i) for i in world.areas.index[low]], "interventions": out, "per_replicate": rows,
            "definitions": __doc__.split("Metrics")[1].strip()}


def ranking(res: dict) -> pd.DataFrame:
    rows = []
    for r in res["interventions"]:
        base = {"intervention": r["name"], "kind": r["kind"], "vehicle_hours_per_weekday": r["vehicle_hours"],
                "transit_trips": r.get("transit_trips", {}).get("mean"), "transit_trips_ci": [r.get("transit_trips", {}).get("ci_low"), r.get("transit_trips", {}).get("ci_high")],
                "access_jobs": r["access_jobs"], "access_gain_low": r["access_gain_low"], "access_gain_other": r["access_gain_other"],
                "low_income_share_of_savings": r.get("low_income_share_of_savings", {}).get("mean")}
        if "trips_per_1000_vehicle_hours" in r:
            x = r["trips_per_1000_vehicle_hours"]
            base.update(ranked_by="transit trips per 1,000 added vehicle-hours", value=x["mean"], ci_low=x["ci_low"], ci_high=x["ci_high"])
        elif "trips_per_1000_dollars" in r:
            x = r["trips_per_1000_dollars"]
            base.update(ranked_by="transit trips per $1,000 weekday revenue forgone", value=x["mean"], ci_low=x["ci_low"], ci_high=x["ci_high"])
        elif r["vehicle_hours"] < 0:
            base.update(ranked_by="saves vehicle-hours (capital cost not modelled)", value=None, ci_low=None, ci_high=None)
        else:
            base.update(ranked_by="no ridership response modelled" if "transit_trips" not in r else "no operating cost", value=None, ci_low=None, ci_high=None)
        rows.append(base)
    df = pd.DataFrame(rows)
    df["_order"] = df["ranked_by"].map({"transit trips per 1,000 added vehicle-hours": 0, "saves vehicle-hours (capital cost not modelled)": 1,
                                        "no operating cost": 2, "transit trips per $1,000 weekday revenue forgone": 3}).fillna(4)
    df = df.sort_values(["_order", "value"], ascending=[True, False]).drop(columns="_order").reset_index(drop=True)
    return df


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    R = int(argv[argv.index("--replicates") + 1]) if "--replicates" in argv else 10
    res = run(R)
    out = REPORTS / "interventions"
    out.mkdir(parents=True, exist_ok=True)
    rk = ranking(res)
    res["ranking"] = rk.to_dict("records")
    with open(out / "interventions.json", "w") as f:
        jsonutil.dump(res, f, indent=1)
    rk.to_csv(out / "ranking.csv", index=False)
    pd.set_option("display.width", 220)
    print(rk[["intervention", "vehicle_hours_per_weekday", "transit_trips", "ranked_by", "value", "ci_low", "ci_high", "access_jobs", "access_gain_low", "access_gain_other", "low_income_share_of_savings"]].to_string())


if __name__ == "__main__":
    main()
