import json

import numpy as np
import pandas as pd

from simchi.data.cds import ROOT, load_cds, sha256, source
from simchi.incidents.data import load_carjackings_2020


def test_mirrors_match_pinned_sha256():
    for key in ["cds_2021", "carjackings_2020", "sdoh_tracts_2014", "cds_field_pdf"]:
        s = source(key)
        assert sha256(ROOT / s["file"]) == s["sha256"], key


def test_cds_structure_and_identities():
    c = load_cds()
    assert list(c.table.index) == list(range(1, 78))
    rep = c.identity_report
    for name, v in rep.items():
        if "max_rel_diff" in v:
            assert v["max_rel_diff"] < 0.015, (name, v)     # rounding-level discrepancies only
    assert rep["lehd_orientation"]["holds"]


def test_carjacking_snapshot_matches_portal_counts():
    df = load_carjackings_2020()
    counts = df["iucr"].value_counts().to_dict()
    # official portal on 2026-10-13: 0325 -> 481, 0326 -> 932 (see data/sources.toml)
    assert counts["0325"] == 481
    assert abs(counts["0326"] - 932) <= 1
    assert df["time"].dt.year.eq(2020).all()
    assert (df["label"] == "observed").all()


def test_atus_transcription_sums_to_24h():
    t = pd.read_csv(ROOT / "data" / "reference" / "atus_2025_table1.csv")
    total = t.loc[t["level"] == "top", "avg_hours_per_day_total"].sum()
    assert abs(total - 24.0) <= 12 * 0.005 + 1e-9      # 12 values each rounded to 0.01 h
