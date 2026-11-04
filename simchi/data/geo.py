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


def to_utm(lon, lat):
    return _FWD.transform(lon, lat)


def to_lonlat(e, n):
    return _INV.transform(e, n)


class LocalFrame:
    """UTM 16N metres relative to an origin, with z pointing south."""

    def __init__(self, e0: float, n0: float):
        self.e0, self.n0 = float(e0), float(n0)

    @property
    def origin_lonlat(self):
        return list(to_lonlat(self.e0, self.n0))

    def from_lonlat(self, lon, lat):
        e, n = to_utm(np.asarray(lon, float), np.asarray(lat, float))
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
