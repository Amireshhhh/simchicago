"""W2 amendment 1 on constructed data with known answers: day types from the GTFS calendar and
calendar_dates (a constructed holiday), per-date schedules, aggregation without holidays, and
train station headways."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from simchi.transit import archive as A
from simchi.transit import calendar as CAL
from simchi.transit.gtfs import Feed


def _feed():
    flags = lambda wd, sat, sun: {**{d: wd for d in CAL.WEEKDAYS[:5]}, "saturday": sat, "sunday": sun}  # noqa: E731
    cal = pd.DataFrame([{"service_id": "WK", **flags("1", "0", "0"), "start_date": "20261101", "end_date": "20261231"},
                        {"service_id": "SAT", **flags("0", "1", "0"), "start_date": "20261101", "end_date": "20261231"},
                        {"service_id": "SUN", **flags("0", "0", "1"), "start_date": "20261101", "end_date": "20261231"}])
    cd = pd.DataFrame([  # Thursday 2026-11-26 runs exactly the Sunday service; Friday 11-27 a holiday-only service
        {"service_id": "WK", "date": "20261126", "exception_type": "2"}, {"service_id": "SUN", "date": "20261126", "exception_type": "1"},
        {"service_id": "WK", "date": "20261127", "exception_type": "2"}, {"service_id": "HOL", "date": "20261127", "exception_type": "1"}])
    trips = pd.DataFrame({"route_id": ["9", "9", "9", "9"], "service_id": ["WK", "WK", "SUN", "HOL"], "trip_id": ["t1", "t2", "t3", "t4"],
                          "direction_id": ["0", "0", "0", "1"], "shape_id": ["s"] * 4})
    st = pd.DataFrame({"trip_id": ["t1", "t1", "t2", "t2", "t3", "t3", "t4", "t4"], "stop_sequence": ["1", "2"] * 4,
                       "stop_id": ["a", "b"] * 4,
                       "arrival_time": ["08:00:00", "08:30:00", "08:20:00", "09:00:00", "10:00:00", "10:20:00", "08:00:00", "08:10:00"],
                       "departure_time": ["08:00:00", "08:30:00", "08:20:00", "09:00:00", "10:00:00", "10:20:00", "08:00:00", "08:10:00"]})
    return Feed({"calendar": cal, "calendar_dates": cd, "trips": trips, "stop_times": st})


def test_day_types_from_scheduled_service():
    F = _feed()
    assert CAL.day_type(F, date(2026, 11, 24)) == "weekday"           # regular Tuesday
    assert CAL.day_type(F, date(2026, 11, 28)) == "saturday"
    assert CAL.day_type(F, date(2026, 11, 26)) == "sunday"            # Thanksgiving running exactly the Sunday service
    assert CAL.day_type(F, date(2026, 11, 27)) == "holiday"           # a service that matches no regular day type
    assert CAL.day_type(F, date(2027, 1, 5)) == "unknown"             # the feed does not cover it
    assert CAL.day_types(F, date(2026, 11, 26), date(2026, 11, 28)) == {"2026-11-26": "sunday", "2026-11-27": "holiday", "2026-11-28": "saturday"}


def test_date_schedule_counts_trips_and_vehicles():
    F = _feed()
    s = CAL.date_schedule(F, date(2026, 11, 24)).set_index(["route", "direction", "hour"])
    # two weekday trips first departing in hour 8, lasting 30 and 40 min: in service = 2 x 35 / 60
    assert s.loc[("9", 0, 8), "trips"] == 2 and s.loc[("9", 0, 8), "in_service"] == pytest.approx(2 * 35 / 60)
    h = CAL.date_schedule(F, date(2026, 11, 27))
    assert list(h["direction"]) == [1] and list(h["trips"]) == [1]     # only the holiday trip runs


def test_aggregate_excludes_holidays_from_cells_and_minimum():
    from tests.test_archive import _daytype, _stats
    days = pd.date_range("2026-01-05", periods=56).strftime("%Y-%m-%d").tolist()
    st = _stats(days, day_of=_daytype)
    hol = st["date"] == "2026-01-19"                                    # a Monday labelled holiday
    st.loc[hol, "day"] = "holiday"
    st.loc[hol & (st["kind"] == "cell"), ["h_sum", "h_sumsq"]] = [3 * 50.0, 3 * 2500.0]   # its headways would change the mean
    r = A.aggregate(st)
    assert r["dates_by_day_type"]["weekday"] == 39 and "holiday" not in r["dates_by_day_type"]
    g = r["_cells"]
    assert set(g["day"]) == {"weekday", "saturday", "sunday"}
    assert g.set_index("day").loc["weekday", "headway_mean_min"] == pytest.approx(8.0)


def test_service_day_uses_the_table_and_marks_unknown():
    out = A.service_day(["2026-11-26", "2026-11-24", "2030-01-01"], {"2026-11-26": "holiday", "2026-11-24": "weekday"})
    assert list(out) == ["holiday", "weekday", "unknown"]


def test_station_headways_midpoints_and_continuity():
    t0 = pd.Timestamp("2026-11-17T14:00:00Z")
    rows = []
    # train A passes station 40380 between polls 0 and 1 (next station changes), train B between polls 6 and 7
    for k in range(10):
        ts = (t0 + pd.Timedelta(minutes=k)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append({"id": "train:Red:1", "mode": "train", "route": "Red", "train_dir": "1", "next_station_id": "40380" if k == 0 else "40370", "poll_utc": ts})
        rows.append({"id": "train:Red:2", "mode": "train", "route": "Red", "train_dir": "1", "next_station_id": "40380" if k <= 6 else "40370", "poll_utc": ts})
    raw = pd.DataFrame(rows)
    polls = sorted({r["poll_utc"] for r in rows})
    H = A.station_headways(raw, polls)
    h = H[H["station_id"] == "40380"]
    assert len(h) == 1 and h.iloc[0]["headway_min"] == pytest.approx(6.0)     # arrivals at 0.5 and 6.5 min
    assert h.iloc[0]["arrival_utc"] == "2026-11-17T14:06:30Z" and bool(h.iloc[0]["continuous"])
    assert "id" not in H.columns
    gap_polls = [p for p in polls if p not in ("2026-11-17T14:03:00Z", "2026-11-17T14:04:00Z", "2026-11-17T14:05:00Z")]
    assert not bool(A.station_headways(raw, gap_polls).iloc[0]["continuous"])      # 4-minute hole in the polling
