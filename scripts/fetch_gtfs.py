"""Download CTA's GTFS feed, check it against the pinned sha256, and (re)build data/transit/.

  python scripts/fetch_gtfs.py              # download, verify against data/sources.toml, rebuild the extract
  python scripts/fetch_gtfs.py --refresh    # accept a new feed: rebuild and update sha256 in data/sources.toml
  python scripts/fetch_gtfs.py --zip FILE   # use a local zip instead of downloading

CTA posts one package at a time and replaces it every week or two, so a plain run fails once
the pinned feed is gone; that is deliberate (the extract stays reproducible until refreshed).
The zip is kept outside the repository (default: ~/.cache/simchi/).
"""

import argparse
import re
import sys
import urllib.request
from pathlib import Path

from simchi.data.cds import source
from simchi.paths import DATA
from simchi.transit.gtfs import build_extract, sha256_file

URL = "https://www.transitchicago.com/downloads/sch_data/google_transit.zip"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--zip", type=Path)
    a = ap.parse_args()
    z = a.zip
    if z is None:
        z = Path.home() / ".cache" / "simchi" / "google_transit.zip"
        z.parent.mkdir(parents=True, exist_ok=True)
        print("downloading", URL)
        urllib.request.urlretrieve(URL, z)
    digest = sha256_file(z)
    pinned = source("gtfs_cta")["sha256"]
    if digest != pinned and not a.refresh:
        print(f"sha256 {digest} does not match the pinned {pinned}.\n"
              "CTA has published a new feed. Re-run with --refresh to adopt it (then re-run the validation).")
        return 1
    meta = build_extract(z, source_sha256=digest)
    print("extract rebuilt:", meta["counts"])
    if digest != pinned:
        p = DATA / "sources.toml"
        p.write_text(re.sub(r'(\[gtfs_cta\][^\[]*?sha256 = ")[0-9a-f]{64}(")', rf"\g<1>{digest}\g<2>", p.read_text(), flags=re.S))
        print("data/sources.toml updated to", digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
