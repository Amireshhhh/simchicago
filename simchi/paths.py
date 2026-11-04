"""Repository paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MIRROR = DATA / "raw" / "mirror"
RUNS = ROOT / "runs"
REPORTS = ROOT / "reports"
VIEWER = ROOT / "viewer"
