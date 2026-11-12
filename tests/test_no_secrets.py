"""Fails if anything resembling a CTA API key is in published or generated output.

Scanned: viewer/dist (the Pages artifact), data/transit, reports/, and the live snapshot
directory given by SIMCHI_LIVE_DIR (set in live.yml before deploying). Checks:
  1. the actual key values, when CTA_BUS_KEY / CTA_TRAIN_KEY are set (as in the workflow);
  2. any URL query parameter named key with a value;
  3. tokens shaped like CTA keys: 25 letters and digits mixing both (Bus Tracker keys are
     "25-digit" alphanumeric), or 32 hexadecimal characters (Train Tracker keys).
"""

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = [ROOT / "viewer" / "dist", ROOT / "data" / "transit", ROOT / "reports"]
if os.environ.get("SIMCHI_LIVE_DIR"):
    SCAN.append(Path(os.environ["SIMCHI_LIVE_DIR"]))
TEXT = {".json", ".js", ".html", ".css", ".csv", ".txt", ".md", ".map"}
KEY_PARAM = re.compile(r"[?&]key=([A-Za-z0-9]{8,})")
BUS_LIKE = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*[A-Za-z])(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{25}(?![A-Za-z0-9])")
TRAIN_LIKE = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{32}(?![0-9a-fA-F])")


def files():
    for root in SCAN:
        if root.exists():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in TEXT:
                    yield p


def findings(text):
    out = []
    for name in ("CTA_BUS_KEY", "CTA_TRAIN_KEY"):
        v = os.environ.get(name)
        if v and v in text:
            out.append(f"value of {name}")
    out += [f"key= parameter ({m[:4]}...)" for m in KEY_PARAM.findall(text)]
    out += [f"bus-key-like token {m[:4]}..." for m in BUS_LIKE.findall(text)]
    out += [f"train-key-like token {m[:4]}..." for m in TRAIN_LIKE.findall(text)]
    return out


def test_detector_catches_key_shapes():
    assert findings("https://x/getvehicles?key=AbCdEfGhIjKlMnOpQrStUvW12&rt=9")
    assert findings('"id":"x","k":"0123456789abcdef0123456789abcdef"')
    assert not findings("route 9 Ashland, sha 3e7426439fcb069c6537ea75ee911e43c7ecfccb")


def test_no_key_like_strings_in_outputs():
    bad = []
    for p in files():
        hits = findings(p.read_text(errors="ignore"))
        if hits:
            bad.append(f"{p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}: {sorted(set(hits))[:3]}")
    assert not bad, "possible API keys in output:\n" + "\n".join(bad)
