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
