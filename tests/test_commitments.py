"""W5 status rules on constructed data with known answers."""

from simchi import commitments as CM

FN = {"standard": {"headway_max_min": 10, "weekday_window": [6, 8], "weekend_window": [9, 10]},
      "phase": [{"effective_by": "2025-03-23", "routes": ["A"]}, {"effective_by": "2026-12-31", "routes": ["B"]}]}
REF = {"weekday": "2026-11-17", "saturday": "2026-11-21", "sunday": "2026-11-22"}


def svc(route, d, day, hour, trips):
    return {"route": route, "direction": d, "day": day, "hour": hour, "trips": trips}


def test_frequent_routes_by_effective_date():
    assert CM.frequent_routes(FN, "2026-11-17") == ["A"] and CM.frequent_routes(FN, "2027-01-01") == ["A", "B"]


def test_frequent_scheduled_counts_units_and_shortfalls():
    rows = [svc("A", 0, "weekday", 6, 6), svc("A", 0, "weekday", 7, 5),        # 7 h: 5 trips = 12 min, short
            svc("A", 1, "weekday", 6, 8), svc("A", 1, "weekday", 7, 6),
            svc("A", 0, "saturday", 9, 6), svc("A", 1, "saturday", 9, 6),
            svc("A", 0, "sunday", 9, 6),                                          # direction 1 missing on Sunday: 0 trips
            svc("B", 0, "weekday", 6, 1)]                                         # B not yet in the network
    r = CM.frequent_scheduled(rows, FN, REF)
    # weekday 2 dirs x 2 h + saturday 2 x 1 + sunday: only direction 0 has rows -> 1 unit; total 7
    assert r["units"] == 7 and r["units_meeting"] == 6 and r["status"] == "not met"
    assert abs(r["share_meeting"] - 6 / 7) < 1e-12 and r["routes_short"] == {"A": {"meeting": 6, "units": 7}}
    assert r["routes_checked"] == ["A"]
    rows[1]["trips"] = 6
    assert CM.frequent_scheduled(rows, FN, REF)["status"] == "met"


def test_zero_by_year_rules():
    assert CM.zero_by_year(3, "2026-11-20", 2026)["status"] == "missed"
    assert CM.zero_by_year(0, "2026-11-20", 2026)["status"] == "on track"
    assert CM.zero_by_year(0, "2026-12-31", 2026)["status"] == "met"


def test_reduction_needs_a_stated_baseline():
    assert CM.reduction_vs_baseline({"baseline_year": ""})["status"] == "not measurable"
    c = {"baseline_year": "2016", "target_year": 2020, "reduction": 0.2}
    assert CM.reduction_vs_baseline(c, {2016: 100, 2020: 80})["status"] == "met"
    assert CM.reduction_vs_baseline(c, {2016: 100, 2020: 81})["status"] == "not met"


def test_delivered_waits_for_the_minimum():
    assert CM.frequent_delivered(None)["status"] == "insufficient data"
    assert CM.frequent_delivered({"minimum_reached": False, "reason": "3 of 8 weeks"})["reason"] == "3 of 8 weeks"
    r = CM.frequent_delivered({"minimum_reached": True, "route_hours": [{"meets": True}, {"meets": False}]})
    assert r["status"] == "not met" and r["share_meeting"] == 0.5


def test_commitments_file_has_no_typed_status_and_every_entry_is_sourced():
    C = CM.load()
    for c in C["commitment"]:
        assert "status" not in c
        for k in ("id", "agency", "quote", "source", "metric", "measured", "measured_from", "rule"):
            assert c.get(k), (c["id"], k)
        assert c["source"].startswith("https://")
    assert C["correction"]
