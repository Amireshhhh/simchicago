"""W8 explore/confirm lanes: refusal of post-2023 data, logging, and the pre-registration check."""

import json
from pathlib import Path

import pandas as pd
import pytest

from simchi import lanes as L


def _fetch(dates):
    return lambda start, end: pd.DataFrame({"d": dates})


def test_explore_refuses_windows_and_records_from_2024(tmp_path):
    lane = L.Lane("explore", "m", log=tmp_path / "r.jsonl")
    with pytest.raises(L.LaneError, match="window"):
        lane.read("x", "d", "2023-06-01", "2024-01-01", _fetch([]))
    with pytest.raises(L.LaneError, match="records dated"):
        lane.read("x", "d", "2023-01-01", "2023-12-31", _fetch(["2023-05-01", "2024-02-01"]))   # the source returned a later record
    df = lane.read("x", "d", "2018-01-01", "2023-12-31", _fetch(["2019-01-01"]))
    assert len(df) == 1
    log = L.read_log(tmp_path / "r.jsonl")
    assert [r["refused"] for r in log] == [True, False] and log[-1]["rows"] == 1 and log[-1]["lane"] == "explore"


def test_confirm_lane_reads_any_window_and_logs(tmp_path):
    lane = L.Lane("confirm", "m", log=tmp_path / "r.jsonl")
    assert len(lane.read("x", "d", "2024-01-01", "2026-10-31", _fetch(["2025-01-01"]))) == 1
    assert L.read_log(tmp_path / "r.jsonl")[0]["lane"] == "confirm"
    with pytest.raises(L.LaneError):
        lane.output("x.json", {})


def test_violation_check():
    conf = {"mod": {"window": ("2024-01-01", "2026-10-31"), "datasets": ["ds"], "prereg": "P"}}
    early = {"utc": "2026-11-01T00:00:00+00:00", "lane": "explore", "dataset": "ds", "start": "2023-01-01", "end": "2024-03-01"}
    late = {**early, "utc": "2026-12-01T00:00:00+00:00"}
    other = {**early, "dataset": "other"}
    before = {**early, "end": "2023-12-31"}
    assert L.violations([early, late, other, before], {"mod": "2026-11-15T00:00:00+00:00"}, conf) == [("mod", early)]
    assert len(L.violations([late], {"mod": None}, conf)) == 1             # not yet pre-registered: any overlap fails


def test_no_explore_read_touched_a_test_window_before_its_preregistration():
    assert L.violations(L.read_log(), L.prereg_times()) == []


def test_exploratory_outputs_are_labelled_and_never_exported(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "EXPLORE_DIR", tmp_path / "explore")
    p = L.Lane("explore", "m", log=tmp_path / "r.jsonl").output("note.json", {"x": 1})
    assert json.loads(p.read_text())["label"] == "exploratory"
    root = Path(__file__).resolve().parent.parent
    for f in list((root / "simchi" / "export").glob("*.py")) + [root / "simchi" / "safety" / "export.py"]:
        assert "explore" not in f.read_text(), f
