import gzip
import io
import json
import urllib.error
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from simchi.data.cds import load_cds
from simchi.transit import live

BUS_KEY = "BUSKEYabcdefghijklmnopqrs"            # 25 characters, like a real Bus Tracker key
TRAIN_KEY = "0123456789abcdef0123456789abcdef"   # 32 hex characters, like a Train Tracker key
NOW = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)   # 08:00 in Chicago, a Tuesday


def service_for(routes, hour=8, day="weekday"):
    return [{"route": r, "direction": 0, "day": day, "hour": hour, "trips": 6, "headway_min": 10.0} for r in routes]


class FakeAPI:
    """Records every URL and answers like CTA; can be told to fail."""

    def __init__(self, bus_fail=None, train_mode="ok"):
        self.urls = []
        self.bus_fail = list(bus_fail or [])
        self.train_mode = train_mode

    def __call__(self, url):
        self.urls.append(url)
        q = parse_qs(urlparse(url).query)
        if "bustime" in url:
            if self.bus_fail:
                code = self.bus_fail.pop(0)
                raise urllib.error.HTTPError(url, code, "fail", {}, io.BytesIO())
            vehicles = [{"vid": f"{r}01", "tmstmp": "20261117 08:00:05", "lat": "41.88", "lon": "-87.63", "hdg": "90",
                         "pid": "1", "rt": r, "des": "Somewhere", "pdist": "100", "tatripid": "t", "psgld": "HALF_EMPTY"}
                        for r in q["rt"][0].split(",")]
            return {"bustime-response": {"vehicle": vehicles}}
        if self.train_mode == "reject_multi" and "," in q["rt"][0]:
            return {"ctatt": {"tmst": "2026-11-17T08:00:07", "errCd": "106", "errNm": "Invalid route identifier"}}
        if self.train_mode == "limit":
            return {"ctatt": {"tmst": "2026-11-17T08:00:07", "errCd": "102", "errNm": "Maximum daily usage exceeded"}}
        routes = [{"@name": rt, "train": [{"rn": "8" + rt, "destNm": "Loop", "lat": "41.9", "lon": "-87.64", "heading": "180",
                                           "isDly": "0", "isApp": "1", "nextStaNm": "Clark/Lake"}]} for rt in q["rt"][0].split(",")]
        return {"ctatt": {"tmst": "2026-11-17T08:00:07", "errCd": "0", "route": routes}}


def run(tmp_path, api, routes, polls=3, bus_key=BUS_KEY, train_key=TRAIN_KEY, service=None, sleeps=None):
    sleeps = [] if sleeps is None else sleeps
    return live.run(polls, 60, tmp_path, bus_key, train_key, service or service_for(routes), routes,
                    load_cds().frame, fetch=api, sleep=sleeps.append, now=lambda: NOW)


def test_bus_requests_are_batched_by_ten(tmp_path):
    routes = [str(i) for i in range(1, 26)]                  # 25 routes -> 3 requests per poll
    api = FakeAPI()
    snap = run(tmp_path, api, routes, polls=1)
    bus_urls = [u for u in api.urls if "bustime" in u]
    assert len(bus_urls) == 3
    assert all(len(parse_qs(urlparse(u).query)["rt"][0].split(",")) <= 10 for u in bus_urls)
    assert snap["requests"]["bus"] == 3 and snap["counts"]["bus"] == 25


def test_train_uses_one_request_and_falls_back_per_line(tmp_path):
    api = FakeAPI()
    run(tmp_path, api, ["9"], polls=1)
    assert len([u for u in api.urls if "ttpositions" in u]) == 1
    api = FakeAPI(train_mode="reject_multi")
    snap = run(tmp_path, api, ["9"], polls=1)
    assert len([u for u in api.urls if "ttpositions" in u]) == 1 + 8
    assert snap["counts"]["train"] == 8


def test_only_routes_in_service_are_polled(tmp_path):
    api = FakeAPI()
    service = service_for(["9"], hour=8) + service_for(["N9"], hour=2)     # an owl route, not running at 08:00
    snap = run(tmp_path, api, ["9", "N9"], polls=1, service=service)
    rts = [parse_qs(urlparse(u).query)["rt"][0] for u in api.urls if "bustime" in u]
    assert rts == ["9"] and snap["counts"]["bus"] == 1


def test_budget_cap_stops_polling_politely(tmp_path, monkeypatch):
    monkeypatch.setitem(live.REQUEST_CAP, "bus", 4)
    routes = [str(i) for i in range(1, 31)]                  # 3 requests per poll, 3 polls -> 9 wanted
    api = FakeAPI()
    snap = run(tmp_path, api, routes)
    assert snap["requests"]["bus"] == 4
    assert any("request cap 4 reached" in n for n in snap["notes"])
    assert (tmp_path / "latest.json").exists()               # still writes what it has


def test_retries_back_off_and_count_against_the_cap(tmp_path):
    sleeps = []
    api = FakeAPI(bus_fail=[503, 503])
    snap = run(tmp_path, api, ["9"], polls=1, sleeps=sleeps)
    assert snap["requests"]["bus"] == 3 and snap["requests"]["bus_retries"] == 2
    assert 2 <= sleeps[0] <= 3 and 4 <= sleeps[1] <= 5          # exponential backoff with jitter
    assert snap["counts"]["bus"] == 1


def test_auth_error_is_not_retried(tmp_path):
    api = FakeAPI(bus_fail=[403])
    snap = run(tmp_path, api, ["9"])
    assert snap["requests"]["bus"] == 1                        # no retry, and no further polls
    assert any("HTTP 403" in n for n in snap["notes"])


def test_train_daily_limit_stops_train_polling(tmp_path):
    api = FakeAPI(train_mode="limit")
    snap = run(tmp_path, api, ["9"])
    assert snap["requests"]["train"] == 1 and any("error 102" in n for n in snap["notes"])


def test_missing_keys_mean_no_requests(tmp_path):
    api = FakeAPI()
    snap = run(tmp_path, api, ["9"], bus_key=None, train_key=None, polls=2)
    assert api.urls == [] and snap["vehicles"] == []


def test_snapshot_schema_and_labels(tmp_path):
    snap = run(tmp_path, FakeAPI(), ["9", "X9"])
    on_disk = json.loads((tmp_path / "latest.json").read_text())
    assert on_disk == snap
    assert snap["schema"] == "simchi.live/1" and snap["label"] == "observed"
    assert len(snap["poll_times_utc"]) == 3 and "not affiliated" in snap["attribution"]
    v = snap["vehicles"][0]
    assert set(v) >= {"id", "mode", "route", "label", "x", "z", "hdg", "t_utc", "dly", "track"}
    assert v["label"] == "observed" and len(v["track"]) == 3
    assert v["t_utc"] == "2026-11-17T14:00:05+00:00"           # Chicago 08:00:05 -> UTC
    with gzip.open(tmp_path / "history.csv.gz", "rt") as f:
        rows = f.read().splitlines()
    assert rows[0].startswith("poll_utc,mode,id,route") and len(rows) == 1 + 3 * (2 + 8)


def test_keys_never_appear_in_outputs(tmp_path, capsys):
    api = FakeAPI(bus_fail=[503, 403])
    run(tmp_path, api, ["9"])
    assert any(BUS_KEY in u for u in api.urls)                 # the key is sent to CTA ...
    blob = "".join(p.read_bytes().decode("latin-1") for p in tmp_path.iterdir() if p.suffix != ".gz")
    blob += gzip.open(tmp_path / "history.csv.gz", "rt").read() + capsys.readouterr().out
    assert BUS_KEY not in blob and TRAIN_KEY not in blob       # ... and written nowhere


def test_redact():
    assert live.redact(f"https://x?key={BUS_KEY}&rt=9", [BUS_KEY, None]) == "https://x?key=***&rt=9"


def test_cli_refuses_settings_outside_the_budget():
    with pytest.raises(SystemExit):
        live.main(["--polls", "5"])
    with pytest.raises(SystemExit):
        live.main(["--interval", "5"])
