"""The viewer's insights export reads the pinned data and committed reports."""

from simchi.export.insights import build_insights


def test_insights_export_blocks():
    I = build_insights()
    assert I["schema"] == "simchi.insights/1"
    w = I["ridership"]["weekly"]
    assert len(w["week_start"]) == len(w["bus"]) == len(w["rail"]) > 100
    assert len(I["ridership"]["top_bus"]) == 15 and I["ridership"]["top_bus"][0]["weekday_rides"] > 10_000
    assert I["network"]["counts"]["routes"] == 132
    assert {c["key"] for c in I["validation"]} >= {"ridership_bus", "mode_choice_holdout"}
    assert I["ops"]["crowding"]["top_bus"] and I["interventions"]["ranking"]


def test_ridership_block_never_compares_across_the_method_break():
    from simchi.export.insights import ridership_block
    R = ridership_block()
    assert R["method_break"]["date"] == "2025-01-01"
    # the mirror ends 2026-08-31, so the year before the last 12 months starts 2024-09: no comparison
    assert R["period"][1] == "2026-08-31"
    assert R["bus_yoy"] is None and R["rail_yoy"] is None


def test_camera_slice_is_not_in_the_public_export():
    from simchi.export.insights import _public_safety
    s = _public_safety()
    assert s is None or ("camera_slice" not in s and "test" in s)
