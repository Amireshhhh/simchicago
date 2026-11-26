"""W2 archive on constructed data with known answers: the ingestion schema, daily build, exact
daily statistics, archive aggregation, the minimum and coverage rules, and the Frequent Network
check."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from simchi.transit import archive as A
from simchi.transit import reliability as RL
from tests.test_reliability import _route9_history, _write_history


@pytest.fixture(scope="module")
def sched():
    return RL.Schedule()


def test_schema_normalise_fills_defaults_and_drops_bad_rows():
    df = pd.DataFrame({"source": ["x"] * 4, "mode": ["bus", "bus", "bus", "tram"], "route": ["9", "9", "", "9"],
                       "direction": ["N"] * 4, "vehicle_id": ["1", "2", "3", "4"],
                       "timestamp_utc": ["2026-11-17T14:00:31Z", "2026-11-17T14:00:40Z", "2026-11-17T14:00:00Z", "2026-11-17T14:00:00Z"],
                       "poll_utc": [None, "2026-11-17T14:01:00Z", None, None], "lat": [41.88, 0.0, 41.88, 41.88],
                       "lon": [-87.63, 0.0, -87.63, -87.63], "delay_flag": [1, 0, 0, 0], "run": [None] * 4})
    out, n = A.normalise(df)
    assert n == {"rows_in": 4, "rows_kept": 1, "rows_dropped": 3}            # 0,0 position; empty route; mode 'tram'
    r = out.iloc[0]
    assert r["poll_utc"] == "2026-11-17T14:00:00Z" and r["run"] == "x:2026-11-17T14"   # floor of the timestamp; source + hour
    assert list(out.columns) == A.SCHEMA


def test_build_day_and_daily_stats_recover_known_headways(tmp_path, sched):
    start = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)                    # Tuesday 08:00 Chicago
    _write_history(tmp_path / "vehicles-7" / "history.csv.gz", _route9_history(sched, start))
    _write_history(tmp_path / "vehicles-8" / "history.csv.gz", _route9_history(sched, start - timedelta(days=1)))   # other date
    df, counts = A.build_day(sorted(tmp_path.glob("*/history.csv.gz")), "2026-11-17")
    assert counts["rows_on_date"] == 18 and set(df["run"]) == {"7"} and set(df["source"]) == {"cta-bustracker"}
    assert set(df["direction"]) == {"pid:111"} and df["delay_flag"].sum() == 3       # vehicle 0 delayed in 3 polls
    S = A.daily_stats(df, sched)
    sp = S[S["kind"] == "polls"]
    assert int(sp["polls"].sum()) == 3
    c = S[S["kind"] == "cell"].iloc[0]
    assert c["polls_seen"] == 3 and c["veh_sum"] == 18 and c["obs"] == 18 and c["dly"] == 3
    # per poll: three 2000 m gaps, one 1800 m and one 200 m (bunched pair) at 5 m/s
    h = np.array([2000, 2000, 2000, 1800, 200] * 3) / 5 / 60
    assert c["h_n"] == 15
    assert c["h_sum"] == pytest.approx(h.sum(), rel=0.05) and c["h_sumsq"] == pytest.approx((h ** 2).sum(), rel=0.08)


def _stats(dates, route="9", h=(6.0, 8.0, 10.0), polls=60, day_of=None):
    """Constructed daily statistics: one cell (route, dir 0, hour 8) per date with headways h."""
    rows = []
    for dt in dates:
        day = day_of(dt) if day_of else "weekday"
        rows.append({"kind": "polls", "mode": "bus", "day": day, "hour": 8, "date": dt, "polls": polls})
        rows.append({"kind": "cell", "route": route, "mode": "bus", "direction": 0, "day": day, "hour": 8, "date": dt,
                     "polls_seen": polls, "veh_sum": 5 * polls, "obs": 5 * polls, "dly": polls, "h_n": len(h),
                     "h_sum": sum(h), "h_sumsq": sum(x * x for x in h), "n_bunch": 0, "n_gap": 1})
    return pd.DataFrame(rows)


def _daytype(d):
    wd = pd.Timestamp(d).weekday()
    return "weekday" if wd < 5 else ("saturday" if wd == 5 else "sunday")


def test_aggregate_minimum_rule_and_exact_cv(sched):
    short = pd.date_range("2026-01-05", periods=20).strftime("%Y-%m-%d").tolist()
    r = A.aggregate(_stats(short, day_of=_daytype), sched)
    assert r["minimum_reached"] is False and r["span_days"] == 20 and "20 of 56 days" in r["reason"]
    full = pd.date_range("2026-01-05", periods=56).strftime("%Y-%m-%d").tolist()
    r = A.aggregate(_stats(full, day_of=_daytype), sched)
    assert r["minimum_reached"] is True and r["dates_by_day_type"] == {"weekday": 40, "saturday": 8, "sunday": 8}
    g = r["_cells"].set_index("day").loc["weekday"]
    assert g["headway_mean_min"] == pytest.approx(8.0)
    assert g["headway_cv"] == pytest.approx(np.std([6, 8, 10]) / 8)                  # exact across days
    assert g["gap_share_lower_bound"] == pytest.approx(1 / 3) and g["delayed_share"] == pytest.approx(0.2)
    assert g["coverage"] == pytest.approx(1.0) and bool(g["eligible"])               # 60 polls per hour per date
    assert g["vehicles_per_poll"] == pytest.approx(5.0)


def test_cells_under_the_coverage_threshold_are_excluded_not_filled(sched):
    full = pd.date_range("2026-01-05", periods=56).strftime("%Y-%m-%d").tolist()
    r = A.aggregate(_stats(full, polls=20, day_of=_daytype), sched)                 # 20 of 60 expected polls: coverage 1/3
    g = r["_cells"]
    assert (g["coverage"] < 0.5).all() and not g["eligible"].any() and r["cells_eligible"] == 0
    assert g["headway_mean_min"].notna().all()                                       # values kept, not imputed, just ineligible


def test_frequent_network_check_uses_dates_after_joining(sched):
    fn = {"standard": {"headway_max_min": 10, "weekday_window": [6, 21], "weekend_window": [9, 21]},
          "phase": [{"effective_by": "2026-01-20", "routes": ["9"]}]}
    dates = pd.date_range("2026-01-05", periods=56).strftime("%Y-%m-%d").tolist()
    st = _stats(dates, h=(9.0,) * 40, day_of=_daytype)
    before = st["date"] < "2026-01-20"
    st.loc[before & (st["kind"] == "cell"), ["h_sum", "h_sumsq"]] = [40 * 30.0, 40 * 900.0]   # 30 min before joining: ignored
    r = A.aggregate(st, sched, fn=fn)
    f = r["frequent_network"]
    # hour 8 is inside the weekday window (6-21 h) but outside the weekend window (9-21 h): one cell
    assert f["eligible"] == 1 and f["share_meeting"] == 1.0
    assert all(x["headway_mean_min"] == pytest.approx(9.0) for x in f["route_hours"])


def test_write_report_withholds_results_before_the_minimum(tmp_path, sched):
    import json
    short = pd.date_range("2026-01-05", periods=10).strftime("%Y-%m-%d").tolist()
    r = A.aggregate(_stats(short, day_of=_daytype), sched, fn={"standard": {"headway_max_min": 10, "weekday_window": [6, 21], "weekend_window": [9, 21]}, "phase": []})
    A.write_report(r, tmp_path)
    s = json.loads((tmp_path / "archive_summary.json").read_text())
    f = json.loads((tmp_path / "frequent_network.json").read_text())
    assert s["minimum_reached"] is False and "system" not in s and not (tmp_path / "archive_cells.csv.gz").exists()
    assert f["minimum_reached"] is False and "route_hours" not in f and "10 of 56 days" in f["reason"]


def test_daily_traversals_are_derived_and_correct(tmp_path, sched):
    from simchi.transit import stop_time as W
    start = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
    _write_history(tmp_path / "vehicles-7" / "history.csv.gz", _route9_history(sched, start))
    df, _ = A.build_day(sorted(tmp_path.glob("*/history.csv.gz")), "2026-11-17")
    T = A.daily_traversals(df, sched)
    assert list(T.columns) == ["route", "direction", "seg", "hour", "run_time_s", "date"]   # no vehicle id, no position
    assert len(T) >= 3 and np.allclose(T["run_time_s"], 400 / 5.0, rtol=0.03)              # 400 m at 5 m/s
    assert set(T["hour"]) == {8} and set(T["date"]) == {"2026-11-17"}
    segs = W.segments(W.representative_shapes(), {}, np.zeros((0, 2)))
    J = W.estimate_from_traversals(T, segs)
    assert len(J) == len(T) and (J["length"] == 400.0).all()
