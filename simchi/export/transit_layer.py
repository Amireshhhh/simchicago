"""Transit layer for the viewer: routes with their shapes, and rail stations (from the GTFS extract)."""

from __future__ import annotations

import json
from pathlib import Path

from simchi import jsonutil
from simchi.paths import VIEWER
from simchi.transit.gtfs import load_extract

ATTRIBUTION = "Routes, stations and schedules: data provided by Chicago Transit Authority (GTFS)."


def build_layer() -> dict:
    routes = load_extract("routes")
    patterns = load_extract("patterns")
    shapes = load_extract("shapes")
    meta = load_extract("meta")
    by_route: dict = {}
    for p in patterns:
        by_route.setdefault(p["route"], []).append(p["shape"])
    out_routes = []
    for r in routes:
        ids = by_route.get(r["id"], [])
        out_routes.append({**r, "shapes": [shapes[s] for s in ids if s in shapes]})
    return {"schema": "simchi.transit/1", "label": "observed", "attribution": ATTRIBUTION,
            "source_sha256": meta["source_sha256"], "reference_dates": meta["reference_dates"],
            "routes": out_routes, "stations": load_extract("stations")}


def export_layer(out: Path | None = None) -> Path:
    out = Path(out) if out else VIEWER / "dist" / "data" / "transit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        jsonutil.dump(build_layer(), f, separators=(",", ":"))
    return out


__all__ = ["build_layer", "export_layer", "json"]
