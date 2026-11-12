"""Projection and geometry helpers.

Local coordinates follow the viewer's convention: metres in UTM zone 16N relative to an
origin, with x = easting - E0 and z = -(northing - N0) (north is negative z).
"""

from __future__ import annotations

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, shape

_FWD = Transformer.from_crs("EPSG:4326", "EPSG:32616", always_xy=True)
_INV = Transformer.from_crs("EPSG:32616", "EPSG:4326", always_xy=True)


def _transform(tr, a, b):
    # pyproj takes a single-point path for one-element arrays that converts them to scalars,
    # which NumPy deprecates; pass plain floats in that case.
    if np.ndim(a) > 0 and np.size(a) == 1:
        x, y = tr.transform(float(np.ravel(a)[0]), float(np.ravel(b)[0]))
        return np.array([x]), np.array([y])
    return tr.transform(a, b)


def to_utm(lon, lat):
    return _transform(_FWD, lon, lat)


def to_lonlat(e, n):
    return _transform(_INV, e, n)


class LocalFrame:
    """UTM 16N metres relative to an origin, with z pointing south."""

    def __init__(self, e0: float, n0: float):
        self.e0, self.n0 = float(e0), float(n0)

    @property
    def origin_lonlat(self):
        return list(to_lonlat(self.e0, self.n0))

    def from_lonlat(self, lon, lat):
        scalar = np.ndim(lon) == 0 and np.ndim(lat) == 0
        e, n = to_utm(np.atleast_1d(np.asarray(lon, float)), np.atleast_1d(np.asarray(lat, float)))
        if scalar:
            return float(e[0]) - self.e0, -(float(n[0]) - self.n0)
        return np.asarray(e) - self.e0, -(np.asarray(n) - self.n0)

    def to_lonlat(self, x, z):
        return to_lonlat(np.asarray(x, float) + self.e0, -np.asarray(z, float) + self.n0)

    def geometry(self, geojson_geom) -> Polygon | MultiPolygon:
        """Project a GeoJSON (Multi)Polygon; invalid rings are repaired with make_valid and
        only the polygonal parts kept."""
        g = shapely.transform(shape(geojson_geom), lambda ll: np.column_stack(self.from_lonlat(ll[:, 0], ll[:, 1])))
        if not g.is_valid:
            g = shapely.make_valid(g)
            if g.geom_type == "GeometryCollection":
                polys = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
                g = shapely.unary_union(polys)
        return g


def rings(geom) -> list[list[list[float]]]:
    """Exterior rings of a (Multi)Polygon as rounded [x, z] lists (for export)."""
    polys = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    return [[[round(x, 1), round(z, 1)] for x, z in p.exterior.coords] for p in polys]
