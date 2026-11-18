"""A typed, paged, cached client for the City of Chicago data portal (Socrata SODA API).

    from simchi.portal.client import Portal
    p = Portal()                                   # optional app token: env SODA_APP_TOKEN
    p.info("ijzp-q8t2")                            # name, columns, last update, declared frequency, status
    df = p.query("ijzp-q8t2", select="date, primary_type, community_area",
                 where="date >= '2026-01-01'", limit=200_000)
    p.count("ijzp-q8t2", where="date >= '2026-01-01'")

What it does that a plain request does not:
  * pages through any number of rows ($limit/$offset, PAGE rows per request) with a stable
    $order (":id" unless you order), so pages neither overlap nor skip rows;
  * converts each column to its portal datatype (number -> float, calendar_date -> datetime,
    checkbox -> bool, text -> string), using the dataset's own column metadata;
  * retries timeouts, 429 and 5xx with exponential backoff (2, 4, 8 s), never in a tight loop;
  * caches each query on disk (Parquet when pyarrow is installed, else CSV) keyed by the query
    and the dataset's data_updated_at, so a re-run is instant until the City changes the data;
  * reports freshness from the catalog (simchi.portal.catalog) next to every result.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://data.cityofchicago.org"
PAGE = 50_000
BACKOFF = (2.0, 4.0, 8.0)


class PortalError(RuntimeError):
    pass


def _cast(df: pd.DataFrame, columns: list) -> pd.DataFrame:
    types = {c["field"]: c["type"] for c in columns}
    for col in df.columns:
        t = (types.get(col) or "").lower().replace(" ", "_")       # catalog labels: "Number", "Calendar date", ...
        if t == "number":
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif t in ("calendar_date", "floating_timestamp", "date"):
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif t == "checkbox":
            df[col] = df[col].map({True: True, False: False, "true": True, "false": False}).astype("boolean")
        elif t in ("text", "url"):
            df[col] = df[col].astype("string")
    return df


class Portal:
    def __init__(self, app_token: str | None = None, cache_dir: str | Path | None = None, opener=None, catalog: dict | None = None):
        self.app_token = app_token if app_token is not None else os.environ.get("SODA_APP_TOKEN")
        self.cache_dir = Path(cache_dir or os.environ.get("SIMCHI_PORTAL_CACHE", Path.home() / ".cache" / "simchi-portal"))
        self._open = opener or urllib.request.urlopen
        self._catalog = catalog
        self.requests = 0

    # ------------------------------------------------------------------ metadata
    @property
    def catalog(self) -> dict:
        if self._catalog is None:
            from simchi.portal.catalog import load
            self._catalog = {d["id"]: d for d in load()["datasets"]}
        return self._catalog

    def info(self, dataset_id: str) -> dict:
        d = self.catalog.get(dataset_id)
        if d is None:
            raise PortalError(f"{dataset_id} is not a dataset in the catalog snapshot (refresh: python -m simchi.portal.catalog --save)")
        return d

    def search(self, text: str, limit: int = 20) -> list:
        t = text.lower()
        hits = [d for d in self.catalog.values() if t in d["name"].lower() or t in (d.get("description") or "").lower()
                or any(t in c["name"].lower() for c in d["columns"])]
        return sorted(hits, key=lambda d: -(d.get("views_month") or 0))[:limit]

    # ------------------------------------------------------------------ requests
    def _get(self, url: str) -> bytes:
        headers = {"Accept": "text/csv"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token
        for attempt in range(len(BACKOFF) + 1):
            self.requests += 1
            try:
                with self._open(urllib.request.Request(url, headers=headers), timeout=120) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == len(BACKOFF):
                    raise PortalError(f"HTTP {e.code} for {url}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == len(BACKOFF):
                    raise PortalError(f"{e} for {url}") from e
            time.sleep(BACKOFF[attempt])
        raise PortalError("unreachable")

    def _url(self, dataset_id: str, params: dict) -> str:
        return f"{BASE}/resource/{dataset_id}.csv?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"

    def count(self, dataset_id: str, where: str | None = None) -> int:
        raw = self._get(self._url(dataset_id, {"$select": "count(*) as n", "$where": where}))
        return int(pd.read_csv(io.BytesIO(raw))["n"].iloc[0])

    def query(self, dataset_id: str, select: str | None = None, where: str | None = None, order: str | None = None,
              group: str | None = None, limit: int | None = None, cache: bool = True) -> pd.DataFrame:
        """All rows matching the query (up to `limit`), typed. Aggregations ($group) are not paged
        by :id because grouped results have no row ids."""
        meta = self.catalog.get(dataset_id)
        key = hashlib.sha256(json.dumps([dataset_id, select, where, order, group, limit, meta and meta.get("updated")]).encode()).hexdigest()[:20]
        path = self.cache_dir / dataset_id / key
        if cache:
            for ext in (".parquet", ".csv.gz"):
                if path.with_suffix(ext).exists():
                    return pd.read_parquet(path.with_suffix(ext)) if ext == ".parquet" else pd.read_csv(path.with_suffix(ext))
        order = order or (None if group else ":id")
        frames, off = [], 0
        while True:
            n = PAGE if limit is None else min(PAGE, limit - off)
            if n <= 0:
                break
            raw = self._get(self._url(dataset_id, {"$select": select, "$where": where, "$order": order, "$group": group,
                                                   "$limit": n, "$offset": off}))
            page = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, na_values=[""])
            frames.append(page)
            off += len(page)
            if len(page) < n:
                break
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if meta:
            df = _cast(df, meta["columns"])
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                df.to_parquet(path.with_suffix(".parquet"), index=False)
            except (ImportError, ValueError):
                df.to_csv(path.with_suffix(".csv.gz"), index=False)
        return df


__all__ = ["Portal", "PortalError"]
