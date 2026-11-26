"""Explore / confirm lanes for data access (W8).

    from simchi.lanes import Lane
    explore = Lane("explore", module="simchi.safety.lights_explore")
    df = explore.read("v6vf-nfxy", "created_date", "2018-01-01", "2023-12-31", fetch)

Rules
  explore  refuses any read whose window reaches 2024-01-01 or later, and any returned record dated
           on or after it (the record's date column is checked after the fetch). Every read is
           logged. Outputs go to reports/explore/, are labelled "exploratory", and never appear in
           public modes or briefs (simchi.briefs refuses reports/explore/; no export reads it).
  confirm  for pre-registered tests; every read is logged as well.
Log: reports/lanes/reads.jsonl, one JSON object per read: utc time, lane, module, dataset, date
column, window start and end, rows returned.
CONFIRM lists each confirm-lane module's test window and the commit-message prefix of its
pre-registration; tests/test_lanes.py fails if an explore read overlapping a test window (same
dataset) was logged before that module's pre-registration commit.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from simchi.paths import REPORTS

EXPLORE_CUTOFF = "2024-01-01"
LOG = REPORTS / "lanes" / "reads.jsonl"
EXPLORE_DIR = REPORTS / "explore"

# confirm-lane modules: test window, datasets, pre-registration commit-message prefix
CONFIRM = {
    "simchi.safety.lights": {"window": ("2024-01-01", "2026-10-31"), "datasets": ["v6vf-nfxy", "ijzp-q8t2"],
                             "prereg": "W9 pre-registration"},
    "simchi.transit.train_gaps": {"window": ("2026-11-13", "2099-12-31"), "datasets": ["ijzp-q8t2", "train_station_headways"],
                                  "prereg": "W10 pre-registration"},
}


class LaneError(RuntimeError):
    pass


class Lane:
    def __init__(self, lane: str, module: str, log: Path = LOG):
        if lane not in ("explore", "confirm"):
            raise LaneError(f"unknown lane {lane!r}")
        self.lane, self.module, self.log = lane, module, Path(log)

    def _check_window(self, start: str, end: str):
        if self.lane == "explore" and (end >= EXPLORE_CUTOFF or start >= EXPLORE_CUTOFF):
            raise LaneError(f"explore lane: window {start}..{end} reaches {EXPLORE_CUTOFF} or later")

    def read(self, dataset: str, date_column: str, start: str, end: str, fetch) -> pd.DataFrame:
        """fetch(start, end) -> DataFrame with `date_column`. Window bounds are YYYY-MM-DD, inclusive."""
        self._check_window(start, end)
        df = fetch(start, end)
        if self.lane == "explore" and len(df):
            d = pd.to_datetime(df[date_column], errors="coerce")
            if (d >= pd.Timestamp(EXPLORE_CUTOFF)).any():
                self._write(dataset, date_column, start, end, len(df), refused=True)
                raise LaneError(f"explore lane: {int((d >= pd.Timestamp(EXPLORE_CUTOFF)).sum())} records dated {EXPLORE_CUTOFF} or later returned; refused")
        self._write(dataset, date_column, start, end, len(df))
        return df

    def _write(self, dataset, date_column, start, end, rows, refused=False):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        rec = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "lane": self.lane, "module": self.module,
               "dataset": dataset, "date_column": date_column, "start": start, "end": end, "rows": int(rows), "refused": refused}
        with open(self.log, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def output(self, name: str, obj: dict) -> Path:
        """Write an exploratory output (explore lane only), labelled."""
        if self.lane != "explore":
            raise LaneError("output() is for exploratory results; confirm results go to their report")
        EXPLORE_DIR.mkdir(parents=True, exist_ok=True)
        p = EXPLORE_DIR / name
        p.write_text(json.dumps({"label": "exploratory", "module": self.module, **obj}, indent=1, default=str))
        return p


def read_log(log: Path = LOG) -> list:
    if not Path(log).exists():
        return []
    return [json.loads(line) for line in Path(log).read_text().splitlines() if line.strip()]


def violations(log_records: list, prereg_times: dict, confirm: dict = CONFIRM) -> list:
    """Explore reads overlapping a confirm module's test window (same dataset) logged before that
    module's pre-registration time (None: not yet pre-registered, so any such read is a violation)."""
    out = []
    for r in log_records:
        if r["lane"] != "explore":
            continue
        for mod, c in confirm.items():
            if r["dataset"] not in c["datasets"]:
                continue
            lo, hi = c["window"]
            if r["start"] <= hi and r["end"] >= lo:
                t = prereg_times.get(mod)
                if t is None or r["utc"] < t:
                    out.append((mod, r))
    return out


def prereg_times(repo: Path | None = None) -> dict:
    """Commit time (UTC ISO) of each confirm module's pre-registration commit, or None."""
    import subprocess
    repo = repo or Path(__file__).resolve().parent.parent
    out = {}
    for mod, c in CONFIRM.items():
        r = subprocess.run(["git", "log", "--format=%cI", "--grep", f"^{c['prereg']}", "--reverse"], cwd=repo, capture_output=True, text=True)
        lines = [x for x in r.stdout.splitlines() if x.strip()]
        out[mod] = pd.Timestamp(lines[0]).tz_convert("UTC").isoformat() if lines else None
    return out
