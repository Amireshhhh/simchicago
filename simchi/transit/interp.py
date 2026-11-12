"""Interpolating vehicle positions along a route shape between two observed positions.

Both positions are projected onto the shape polyline (nearest point, as distance along the
shape). For a fraction f in [0, 1] of the time between the two observations, the vehicle is
placed at distance s0 + f (s1 - s0) along the shape. If the second projection lies behind the
first (s1 < s0: GPS noise, or the vehicle turned at a terminal) or either point is farther than
`max_offset_m` from the shape, the interpolation falls back to a straight line between the
observed points. The viewer implements the same rule (viewer/src/core.js: alongShape).
"""

from __future__ import annotations

import numpy as np


def cumulative(shape: np.ndarray) -> np.ndarray:
    d = np.hypot(np.diff(shape[:, 0]), np.diff(shape[:, 1]))
    return np.concatenate([[0.0], np.cumsum(d)])


def project(shape: np.ndarray, cum: np.ndarray, p) -> tuple[float, float]:
    """(distance along the shape of the nearest point, distance from p to the shape)."""
    a, b = shape[:-1], shape[1:]
    ab = b - a
    L2 = (ab ** 2).sum(1)
    t = np.clip(((np.asarray(p) - a) * ab).sum(1) / np.where(L2 > 0, L2, 1), 0, 1)
    q = a + ab * t[:, None]
    d = np.hypot(q[:, 0] - p[0], q[:, 1] - p[1])
    k = int(d.argmin())
    return float(cum[k] + t[k] * np.sqrt(L2[k])), float(d[k])


def point_at(shape: np.ndarray, cum: np.ndarray, s: float) -> tuple[float, float]:
    s = float(np.clip(s, 0, cum[-1]))
    k = int(np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(cum) - 2))
    seg = cum[k + 1] - cum[k]
    f = 0.0 if seg <= 0 else (s - cum[k]) / seg
    return (float(shape[k, 0] + f * (shape[k + 1, 0] - shape[k, 0])), float(shape[k, 1] + f * (shape[k + 1, 1] - shape[k, 1])))


def along_shape(shape, p0, p1, f: float, max_offset_m: float = 150.0) -> tuple[float, float]:
    shape = np.asarray(shape, float)
    f = float(np.clip(f, 0, 1))
    line = (p0[0] + f * (p1[0] - p0[0]), p0[1] + f * (p1[1] - p0[1]))
    if len(shape) < 2:
        return line
    cum = cumulative(shape)
    s0, d0 = project(shape, cum, p0)
    s1, d1 = project(shape, cum, p1)
    if d0 > max_offset_m or d1 > max_offset_m or s1 < s0:
        return line
    return point_at(shape, cum, s0 + f * (s1 - s0))


def best_shape(shapes, p0, p1, max_offset_m: float = 150.0):
    """Among a route's shapes, the one both points lie within max_offset_m of, running forward
    from p0 to p1, with the smallest larger offset; None if no shape qualifies.
    (Bus Tracker pattern ids do not map onto GTFS shape ids, so the shape is chosen this way.)"""
    best, best_d = None, float("inf")
    for sh in shapes:
        sh = np.asarray(sh, float)
        if len(sh) < 2:
            continue
        cum = cumulative(sh)
        s0, d0 = project(sh, cum, p0)
        s1, d1 = project(sh, cum, p1)
        d = max(d0, d1)
        if d <= max_offset_m and s1 >= s0 and d < best_d:
            best, best_d = sh, d
    return best
