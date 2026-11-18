"""2D map exports are WGS84 and inside Chicago."""
import json

from simchi.export.mapdata import export_map, load_streets


def test_map_exports(tmp_path):
    s = load_streets()
    assert len(s["features"]) > 50_000
    assert {f["properties"]["c"] for f in s["features"]} <= {"1", "2", "3", "4", "5", "7", "9", "E", "RIV"}
    out = export_map(tmp_path)
    cta = json.loads((out / "cta.json").read_text())
    st = [f for f in cta["features"] if f["properties"]["kind"] == "station"]
    assert len(st) == 143
    for f in st:
        lon, lat = f["geometry"]["coordinates"]
        assert -87.95 < lon < -87.5 and 41.6 < lat < 42.1          # Chicago (O'Hare to the lake)
    labels = json.loads((out / "labels.json").read_text())["features"]
    assert sum(f["properties"]["c"] == "area" for f in labels) == 77
