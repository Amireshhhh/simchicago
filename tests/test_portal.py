"""Portal catalog freshness rules and the client's paging, typing, retries and cache (offline)."""

import io
import urllib.error
import urllib.parse

import pandas as pd
import pytest

from simchi.portal import client as C
from simchi.portal.catalog import parse_period, status


def test_declared_frequency_parsing():
    assert parse_period("Data are updated daily") == 1
    assert parse_period("Every hour between 7:30 am and 7:30pm") == 1
    assert parse_period("Data is updated weekly") == 7
    assert parse_period("Monthly or Data are updated as needed") == 31
    assert parse_period("Data are updated twice a year") == 183
    assert parse_period("Annually") == 366
    assert parse_period("Data is updated as needed") is None
    assert parse_period("No longer updated") is None
    assert parse_period("") is None


def test_status_rules():
    assert status(5, 1) == "fresh"            # no new records for a few days is not lateness
    assert status(20, 1) == "late" and status(31, 1) == "overdue"
    assert status(400, 366) == "late" and status(800, 366) == "overdue"
    assert status(10, None) == "fresh" and status(100, None) == "static"


class FakePortal:
    """Serves a 120-row dataset in CSV pages, failing the first request with a 503."""

    def __init__(self):
        self.calls = []
        self.rows = pd.DataFrame({"id": range(120), "amount": [i * 1.5 for i in range(120)],
                                  "when": pd.date_range("2026-01-01", periods=120, freq="D").strftime("%Y-%m-%dT00:00:00.000"),
                                  "flag": ["true", "false"] * 60, "name": [f"n{i}" for i in range(120)]})

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        if len(self.calls) == 1:
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        if q.get("$select") == "count(*) as n":
            return io.BytesIO(b"n\n120\n")
        off, lim = int(q["$offset"]), int(q["$limit"])
        assert q["$order"] == ":id"
        return io.BytesIO(self.rows.iloc[off:off + lim].to_csv(index=False).encode())


def test_client_pages_types_retries_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "PAGE", 50)
    monkeypatch.setattr(C, "BACKOFF", (0.0, 0.0, 0.0))
    cat = {"x-1": {"id": "x-1", "updated": "2026-11-01T00:00:00Z", "columns": [
        {"name": "Id", "field": "id", "type": "Number"}, {"name": "Amount", "field": "amount", "type": "Number"},
        {"name": "When", "field": "when", "type": "Calendar date"}, {"name": "Flag", "field": "flag", "type": "Checkbox"},
        {"name": "Name", "field": "name", "type": "Text"}]}}              # the catalog's own type labels
    fake = FakePortal()
    p = C.Portal(app_token="", cache_dir=tmp_path, opener=fake, catalog=cat)
    df = p.query("x-1")
    assert len(df) == 120 and df["id"].tolist() == list(range(120))            # 3 pages, no overlap or gap
    assert df["amount"].dtype.kind == "f" and str(df["when"].dtype).startswith("datetime64") and bool(df["flag"].iloc[0]) is True and str(df["flag"].dtype) == "boolean"
    assert len(fake.calls) == 1 + 3                                              # one 503 retried, then 50 + 50 + 20
    n = len(fake.calls)
    again = p.query("x-1")                                                       # second call served from the cache
    assert len(again) == 120 and again["id"].tolist() == df["id"].tolist()
    assert len(fake.calls) == n
    assert p.count("x-1") == 120


def test_client_gives_up_on_client_errors(tmp_path):
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "bad query", {}, None)
    p = C.Portal(app_token="", cache_dir=tmp_path, opener=opener, catalog={})
    with pytest.raises(C.PortalError):
        p.query("x-1", cache=False)


def test_client_retries_dropped_connections(tmp_path, monkeypatch):
    import http.client
    monkeypatch.setattr(C, "BACKOFF", (0.0, 0.0, 0.0))
    calls = []

    def opener(req, timeout=None):
        calls.append(1)
        if len(calls) <= 2:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return io.BytesIO(b"n\n7\n")
    p = C.Portal(app_token="", cache_dir=tmp_path, opener=opener, catalog={})
    assert p.count("x-1") == 7 and len(calls) == 3
