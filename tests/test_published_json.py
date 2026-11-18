"""Every JSON file the live deploy publishes must parse in a browser: strict JSON, no NaN or
Infinity (JSON.parse rejects them, and then the whole file is unusable). Run by live.yml before
deploying, with SIMCHI_LIVE_DIR pointing at the run's output; skipped when nothing is there."""

import json
import os
from pathlib import Path

import pytest

LIVE = Path(os.environ.get("SIMCHI_LIVE_DIR", "live"))
FILES = sorted(LIVE.glob("*.json")) if LIVE.is_dir() else []


def _strict(c):
    raise ValueError(f"non-JSON constant {c}")


@pytest.mark.skipif(not FILES, reason="no live output in this checkout")
@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_strict_json(path):
    json.loads(path.read_text(), parse_constant=_strict)
