"""Rider feedback vs polled headways (schema and comparison pre-registered in the W2 docstring of
simchi/transit/archive.py, RIDER FEEDBACK). No pass criterion; nothing is fitted to the feedback.

    python -m simchi.transit.feedback <feedback.csv> [--cells reports/reliability/archive_cells.csv.gz]

Feedback schema: route, stop_id, timestamp_utc, observed_wait_min, source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from simchi.paths import REPORTS

FEEDBACK_SCHEMA = ["route", "stop_id", "timestamp_utc", "observed_wait_min", "source"]


def stop_directions(patterns: list) -> dict:
    """(route, stop_id) -> sorted GTFS directions of the patterns serving the stop on that route."""
    out = {}
    for p in patterns:
        for s in p["stops"]:
            out.setdefault((str(p["route"]), str(s)), set()).add(int(p["direction"]))
    return {k: sorted(v) for k, v in out.items()}


def predicted_wait(cells: pd.DataFrame) -> pd.Series:
    """E[W] = E[H] (1 + CV^2) / 2 per cell (random arrivals)."""
    return cells["headway_mean_min"] * (1 + cells["headway_cv"] ** 2) / 2


def compare(feedback: pd.DataFrame, cells: pd.DataFrame, stop_dirs: dict) -> dict:
    from simchi.transit.reliability import CHICAGO
    fb = feedback.copy()
    missing = [c for c in FEEDBACK_SCHEMA if c not in fb]
    if missing:
        raise ValueError(f"feedback is missing columns {missing}")
    loc = pd.to_datetime(fb["timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(CHICAGO)
    fb["hour"] = loc.dt.hour
    wd = loc.dt.weekday
    fb["day"] = np.where(wd < 5, "weekday", np.where(wd == 5, "saturday", "sunday"))
    c = cells.assign(pred=predicted_wait(cells)).set_index(["route", "direction", "day", "hour"])["pred"]
    preds = []
    for r in fb.itertuples():
        dirs = stop_dirs.get((str(r.route), str(r.stop_id)), [])
        v = [c.get((str(r.route), d, r.day, int(r.hour)), np.nan) if pd.notna(r.hour) else np.nan for d in dirs]
        v = [x for x in v if np.isfinite(x)]
        preds.append(float(np.mean(v)) if v else np.nan)
    fb["predicted_wait_min"] = preds
    m = fb[np.isfinite(fb["predicted_wait_min"]) & pd.to_numeric(fb["observed_wait_min"], errors="coerce").notna()]
    obs, pred = m["observed_wait_min"].astype(float).to_numpy(), m["predicted_wait_min"].to_numpy()
    out = {"records": int(len(fb)), "matched": int(len(m)), "label": "comparison only; nothing is tuned to the feedback"}
    if len(m) >= 3:
        out.update({"spearman": float(spearmanr(obs, pred).statistic), "median_ratio_observed_to_predicted": float(np.median(obs / pred)),
                    "mean_abs_diff_min": float(np.mean(np.abs(obs - pred))),
                    "share_within_50pct": float(np.mean(np.abs(obs - pred) <= 0.5 * pred))})
    return out


def main(argv=None):
    import argparse

    from simchi.transit.gtfs import load_extract
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("feedback")
    ap.add_argument("--cells", default=str(REPORTS / "reliability" / "archive_cells.csv.gz"))
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if not Path(a.cells).exists():
        sys.exit("no archive cells yet (the W2 archive has not reached its minimum)")
    cells = pd.read_csv(a.cells, dtype={"route": str})
    cells = cells[cells["eligible"]]
    res = compare(pd.read_csv(a.feedback, dtype={"route": str, "stop_id": str}), cells, stop_directions(load_extract("patterns")))
    (REPORTS / "reliability").mkdir(parents=True, exist_ok=True)
    (REPORTS / "reliability" / "feedback_comparison.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
