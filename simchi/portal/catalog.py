"""The City of Chicago data portal catalog, with freshness measured against each dataset's own
declared update frequency (python -m simchi.portal.catalog).

Source: the portal's catalog API (https://data.cityofchicago.org/api/catalog/v1), all assets of
type "dataset". For each dataset:
  age_days        days since data_updated_at (the portal's own timestamp of the last data change)
  declared        the "Metadata_Frequency" text the City publishes with the dataset
  period_days     that text parsed to a period: daily 1, weekly 7, bi-weekly 14, monthly 31,
                  quarterly 92, semi-annually 183, annually 366; None for "as needed", historical
                  or blank (no promise to check against)
  status          fresh (age <= period + 7 days, or <= 30 days when no period is declared),
                  late (up to max(2 x period, 30 days)), overdue (older than that),
                  static (no declared period and older than 30 days). The grace exists because
                  data_updated_at only changes when the data change.
Nothing here judges why a dataset is stale; many are historical by design.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from simchi.paths import DATA, VIEWER

CATALOG_URL = "https://data.cityofchicago.org/api/catalog/v1"
OUT = DATA / "portal" / "catalog.json.gz"
_PERIODS = [(r"bi-?weekly|every (two|2) weeks", 14), (r"semi-?annual|twice a year|every (six|6) months", 183),
            (r"daily|every day|nightly|real[- ]time|hourly|every hour|per hour|every \\d+ minutes|times (a|per) day", 1), (r"weekly|every week", 7),
            (r"monthly|every month", 31), (r"quarterly|every (three|3) months", 92), (r"annual|yearly|every year", 366)]



def parse_period(text: str | None) -> int | None:
    """Declared frequency text -> period in days (first schedule keyword wins), None if no promise."""
    t = (text or "").lower()
    if not t.strip():
        return None
    hits = [(m.start(), p) for pat, p in _PERIODS for m in [re.search(pat, t)] if m]
    if hits:
        return min(hits)[1]
    return None                     # "as needed", historical, discontinued, or no schedule word


GRACE_DAYS = 30


def status(age_days: float | None, period: int | None) -> str:
    """The portal's data_updated_at changes only when the data change, so a daily load that found
    nothing new looks a few days old: lateness gets a grace of max(2 x period, 30 days)."""
    if age_days is None:
        return "unknown"
    if period is None:
        return "fresh" if age_days <= GRACE_DAYS else "static"
    if age_days <= period + 7:
        return "fresh"
    return "late" if age_days <= max(2 * period, GRACE_DAYS) else "overdue"


def fetch_raw(timeout: int = 120) -> list:
    out, off = [], 0
    while True:
        q = urllib.parse.urlencode({"domains": "data.cityofchicago.org", "search_context": "data.cityofchicago.org",
                                    "only": "dataset", "limit": 1000, "offset": off})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(f"{CATALOG_URL}?{q}", timeout=timeout) as r:
                    page = json.load(r)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * 2 ** attempt)
        out += page["results"]
        if len(page["results"]) < 1000:
            return out
        off += 1000


def normalise(raw: list, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    rows = []
    for r in raw:
        x = r["resource"]
        if x.get("type") != "dataset":
            continue
        md = {m["key"]: m["value"] for m in r["classification"].get("domain_metadata", [])}
        upd = x.get("data_updated_at")
        age = None
        if upd:
            t = dt.datetime.fromisoformat(upd.replace("Z", "+00:00"))
            age = round((now - t).total_seconds() / 86400.0, 1)
        declared = md.get("Metadata_Frequency", "")
        per = parse_period(declared)
        pv = x.get("page_views") or {}
        rows.append({
            "id": x["id"], "name": x["name"], "category": r["classification"].get("domain_category"),
            "description": (x.get("description") or "")[:600], "owner": md.get("Metadata_Data-Owner") or x.get("attribution"),
            "updated": upd, "age_days": age, "declared": declared, "period_days": per, "status": status(age, per),
            "time_period": md.get("Metadata_Time-Period"),
            "columns": [{"name": n, "field": f, "type": ty} for n, f, ty in zip(x.get("columns_name", []), x.get("columns_field_name", []),
                                                                                x.get("columns_datatype", []), strict=False)],
            "views_month": pv.get("page_views_last_month"), "views_total": pv.get("page_views_total"),
            "downloads": x.get("download_count"), "link": r.get("permalink") or r.get("link"),
        })
    rows.sort(key=lambda d: -(d["views_month"] or 0))
    return {"source": CATALOG_URL, "fetched_utc": now.replace(microsecond=0).isoformat(), "datasets": rows, "summary": summary(rows)}


def summary(rows: list) -> dict:
    import statistics
    ages = [r["age_days"] for r in rows if r["age_days"] is not None]
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
    declared_daily = [r for r in rows if r["period_days"] == 1]
    return {"datasets": len(rows), "median_age_days": statistics.median(ages) if ages else None,
            "updated_within_7d": sum(a <= 7 for a in ages), "older_than_1y": sum(a > 365 for a in ages),
            "older_than_5y": sum(a > 1825 for a in ages), "status": by,
            "with_declared_period": sum(r["period_days"] is not None for r in rows),
            "declared_daily": len(declared_daily), "declared_daily_overdue": sum(r["status"] == "overdue" for r in declared_daily)}


def save(cat: dict, path: Path = OUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as f:
        json.dump(cat, f, separators=(",", ":"))


def load(path: Path = OUT) -> dict:
    with gzip.open(path, "rt") as f:
        return json.load(f)


def export_viewer(cat: dict | None = None, out: Path | None = None) -> Path:
    cat = cat or load()
    out = Path(out) if out else VIEWER / "dist" / "data" / "portal" / "catalog.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    slim = {**cat, "datasets": [{k: v for k, v in d.items() if k != "description"} | {"description": d["description"][:240]} for d in cat["datasets"]]}
    out.write_text(json.dumps(slim, separators=(",", ":")))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cat = normalise(fetch_raw())
    if "--save" in argv:
        save(cat)
    if "--viewer" in argv:
        export_viewer(cat)
    print(json.dumps(cat["summary"], indent=1))


if __name__ == "__main__":
    main()
