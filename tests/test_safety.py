"""W4 crash safety layer on constructed data with known answers: site building and snapping,
aggregation (Vision Zero as the death count, KA definition, no person-level output), the NB2
fit, empirical Bayes, ranking tie-breaks, the captured-share test and the camera slice."""

import math

import numpy as np
import pandas as pd
import pytest

from simchi.safety import crashes as C
from simchi.safety import sites as ST

# a local metric "projection" around (-87.6, 41.8): 1 degree = 100 km, so 0.0003 deg = 30 m.
# Constructed coordinates are written as offsets from that origin (O + dx).
LON0, LAT0 = -87.6, 41.8
to_xy = lambda lon, lat: ((np.asarray(lon, float) - LON0) * 1e5, (np.asarray(lat, float) - LAT0) * 1e5)
def L(lon_off):
    return [LON0 + v for v in lon_off] if isinstance(lon_off, list) else LON0 + lon_off
def B(lat_off):
    return [LAT0 + v for v in lat_off] if isinstance(lat_off, list) else LAT0 + lat_off


def _grid():
    """A plus-shaped arterial crossing (4 legs at the origin) plus a dead-end local street and an
    expressway segment."""
    f = lambda c, n, co: {"type": "Feature", "properties": {"c": c, "n": n},
                          "geometry": {"type": "LineString", "coordinates": [[LON0 + a, LAT0 + b] for a, b in co]}}
    return {"type": "FeatureCollection", "features": [
        f("2", "A St", [[0, 0], [0.01, 0]]), f("2", "A St", [[-0.01, 0], [0, 0]]),
        f("4", "B Av", [[0, 0], [0, 0.01]]), f("4", "B Av", [[0, -0.01], [0, 0]]),
        f("4", "C Ct", [[0.01, 0], [0.01, 0.005]]),                   # meets A St's east end: only 2 ends there
        f("1", "I-90", [[0.05, 0], [0.05, 0.02]]),
        f("RIV", "River", [[0.02, 0], [0.03, 0]])]}


def test_sites_intersections_and_snapping():
    S = ST.build_sites(_grid(), to_xy)
    T = S.table
    assert (T["type"] == "intersection").sum() == 1 and T.loc["i0", "legs"] == 4 and T.loc["i0", "cls"] == "2"
    assert (T["type"] == "segment").sum() == 6                     # river excluded
    assert bool(T.loc["s5", "expressway"]) and not bool(T.loc["i0", "expressway"])
    x, z = to_xy(L([0.0002, 0.0005, 0.005, 0.005, 0.2]), B([0.0001, 0.0, 0.0004, 0.0006, 0.2]))
    # 22 m from the node -> node; 50 m along A St but 0 m off it -> segment s0; 40 m off s0 -> s0; 60 m off -> none? (B Av is 500 m away)
    assert list(S.snap(x, z)) == ["i0", "s0", "s0", None, None]


def test_aggregate_vision_zero_ka_and_no_person_rows():
    from simchi.safety.mirror import aggregate
    S = ST.build_sites(_grid(), to_xy)

    class F:
        from_lonlat = staticmethod(to_xy)
    t = "2025-03-01T10:15:00"
    raw = {
        "crashes": pd.DataFrame({"crash_record_id": ["c1", "c2", "c3", "c4"], "crash_date": [t, t, "2024-05-01T00:00:00", t],
                                 "latitude": B([0.0001, 0.0, 0.0, 0.0]), "longitude": L([0.0001, 0.005, 0.005, 0.0]),
                                 "injuries_fatal": [1, 0, 0, 0], "injuries_incapacitating": [0, 2, 1, 0], "injuries_total": [1, 2, 1, 0]}),
        "people": pd.DataFrame({"crash_record_id": ["c2", "c2"], "person_type": ["PEDESTRIAN", "DRIVER"],
                                "injury_classification": ["INCAPACITATING INJURY"] * 2, "n": [1, 1]}),
        # two deaths in the same crash (same minute, same site) and one elsewhere
        "vision_zero": pd.DataFrame({"crash_date": [t, t, "2025-06-01T08:00:00"], "latitude": B([0.0001, 0.0001, 0.0]), "longitude": L([0.0, 0.0, 0.005]),
                                     "victim": ["PEDESTRIAN", "DRIVER", "BICYCLE"]}),
        "speed_cameras": pd.DataFrame({"id": ["1"], "address": ["x"], "go_live_date": ["2020-01-15"], "latitude": B([0.0]), "longitude": L([0.004])}),
        "red_light_cameras": pd.DataFrame({"intersection": ["A-B"], "go_live_date": ["2019-02-01"], "latitude": B([0.0]), "longitude": L([0.0])}),
        "speed_violations": pd.DataFrame({"camera_id": ["1"], "month": ["2020-02-01T00:00:00"], "violations": ["7"]}),
        "red_light_violations": pd.DataFrame({"camera_id": ["9"], "intersection": ["A-B"], "month": ["2020-02-01T00:00:00"], "violations": ["3"]}),
        "adt": pd.DataFrame({"segmentid": ["1", "1"], "direction": ["E", "W"], "midpointlat": B([0.0, 0.0]), "midpointlon": L([0.005, 0.005]),
                             "mean_count": ["1000", "1500"], "days": ["300", "290"]}),
    }
    tables, summ = aggregate(raw, S, F)
    sy = tables["site_year"].set_index(["site", "year"])
    assert sy.loc[("s0", 2025), "a_crashes"] == 1 and sy.loc[("s0", 2025), "ped_bike_ka"] == 1
    assert sy.loc[("i0", 2025), "k_crashes_cpd"] == 1 and sy.loc[("i0", 2025), "crashes"] == 2      # c1 and c4
    vz = tables["vz_site_year"].set_index(["site", "year"])
    assert vz.loc[("i0", 2025), "deaths"] == 2 and vz.loc[("i0", 2025), "fatal_crashes"] == 1
    assert vz.loc[("s0", 2025), "fatal_crashes"] == 1
    assert tables["site_adt"].set_index("site").loc["s0", "adt"] == 2500                       # directions summed
    for name, df in tables.items():                                                             # no person-level fields
        assert not {"person_id", "age", "sex", "victim", "crash_record_id"} & set(df.columns), name
    assert summ["vision_zero_deaths"] == 3


def test_nb2_fit_recovers_known_parameters():
    rng = np.random.default_rng(1)
    n = 40000
    x = rng.normal(size=n)
    X = np.column_stack([np.ones(n), x])
    beta, alpha = np.array([-0.5, 0.8]), 0.6
    mu = np.exp(X @ beta)
    y = rng.poisson(rng.gamma(1 / alpha, alpha * mu))                    # NB2 as a gamma-Poisson mixture
    fit = C.nb2_fit(X, y)
    assert fit["beta"] == pytest.approx(beta, abs=0.03)
    assert fit["alpha"] == pytest.approx(alpha, abs=0.05)


def test_empirical_bayes_formula():
    eb, w = C.empirical_bayes(np.array([2.0, 10.0]), np.array([10.0, 0.0]), 0.5)
    assert w == pytest.approx([1 / 2, 1 / 6])
    assert eb == pytest.approx([0.5 * 2 + 0.5 * 10, 10 / 6])


def test_top_k_tie_breaks_and_captured_share():
    ids = np.array(["b", "a", "c", "d"])
    t = C.top_k(ids, [np.array([5, 5, 5, 1]), np.array([1, 1, 2, 9])], 3)
    assert list(t) == ["c", "a", "b"]                                    # key 1, then key 2, then id
    out = pd.Series({"a": 2, "b": 0, "c": 1, "d": 1})
    assert C.captured(["a", "c"], out) == pytest.approx(3 / 4)


def test_ka_table_uses_vision_zero_for_deaths():
    sy = pd.DataFrame({"site": ["s1", "s1"], "year": [2024, 2025], "crashes": [5, 3], "a_crashes": [1, 2], "k_crashes_cpd": [3, 3]})
    vz = pd.DataFrame({"site": ["s1"], "year": [2025], "deaths": [2], "fatal_crashes": [1]})
    K = C.ka_table(sy, vz)
    assert K.loc["s1", "ka_2025"] == 3 and K.loc["s1", "ka_2024"] == 1 and K.loc["s1", "ka_train"] == 1   # CPD's k ignored


def test_camera_slice_ratio_of_ratios():
    cams = pd.DataFrame({"kind": ["speed"], "camera": ["1"], "address": ["x"], "lon": [0.0], "lat": [0.0], "go_live": ["2021-06-10"]})
    pre, post = C._months("2021-06-10")
    assert pre[0] == "2020-06" and pre[-1] == "2021-05" and post[0] == "2021-07" and post[-1] == "2022-06"
    rows = [("cam:speed:1", pre[0], 10, 2), ("cam:speed:1", post[0], 5, 1)]
    # pool: p1 pre 10 (best match), p2 pre 9, p3 pre 12, p4 pre 30 (not matched); all post 10
    for p, n in (("site:p1", 10), ("site:p2", 9), ("site:p3", 12), ("site:p4", 30)):
        rows += [(p, pre[3], n, 0), (p, post[3], 10, 0)]
    radial = pd.DataFrame(rows, columns=["point", "month", "crashes", "ka_crashes"])
    res = C.camera_slice(cams, radial, ["p1", "p2", "p3", "p4"], n_boot=50)["speed"]
    assert res["cameras"] == 1
    r = res["all_crashes"]
    assert r["comparison_pre"] == 31 and r["comparison_post"] == 30       # p1, p2, p3
    assert r["ratio_of_ratios"] == pytest.approx((5 / 10) / (30 / 31))
