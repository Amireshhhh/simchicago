"""Regenerate viewer/test/fixtures from the Python engine (positions) and pyproj (UTM).

The viewer's positionAt() must reproduce the engine's interpolation rule exactly; the
fixtures are produced by the Python side so the JS test checks the two agree.
"""

import json

import numpy as np

from simchi.data.geo import to_utm
from simchi.paths import VIEWER
from simchi.pipeline import build, run
from simchi.sim.engine import SimConfig


def position(segs, t):
    """Engine rule: segment k = (#segments with t0 <= t) - 1 (clamped), linear in time."""
    k = int(np.clip(np.searchsorted([s[0] for s in segs], t, side="right") - 1, 0, len(segs) - 1))
    s = segs[k]
    f = min(1.0, max(0.0, (t - s[0]) / max(s[1] - s[0], 1e-9)))
    return [s[3] + f * (s[5] - s[3]), s[4] + f * (s[6] - s[4])]


def main():
    sim = run(build(2000, 1), SimConfig(n_days=2, seed=7, incident_mode="none"))
    S = sim.segments
    rng = np.random.default_rng(0)
    cases = []
    for pid in rng.choice(int(S["pid"].max()) + 1, 12, replace=False):
        m = S["pid"] == pid
        t0 = S["day"][m] * 1440 + S["t0"][m]
        order = np.argsort(t0, kind="stable")
        segs = np.column_stack([t0, S["day"][m] * 1440 + S["t1"][m], S["kind"][m], S["x0"][m], S["z0"][m],
                                S["x1"][m], S["z1"][m], S["mode"][m]])[order].tolist()
        trips = [s for s in segs if s[2] == 8]
        times = list(rng.uniform(0, 2880, 3)) + [(s[0] + s[1]) / 2 for s in trips[:3]] + [-5.0, 4000.0]
        for t in times:
            cases.append({"segs": segs, "t": float(t), "xy": position(segs, t)})
    with open(VIEWER / "test" / "fixtures" / "positions.json", "w") as f:
        json.dump({"source": "simchi engine segments (n=2000, seed 1 build; run seed 7, 2 days)", "cases": cases}, f)
    # shape interpolation: JS alongShape/bestShape must match simchi.transit.interp
    from simchi.transit.gtfs import load_extract
    from simchi.transit.interp import along_shape, best_shape
    shapes = load_extract("shapes")
    pats = [p for p in load_extract("patterns") if p["route"] in ("Red", "9", "Y")]
    along = []
    for p in pats:
        sh = shapes[p["shape"]]
        n = len(sh)
        for i, j, f in ((0, n // 3, 0.25), (n // 3, 2 * n // 3, 0.7), (2 * n // 3, n // 3, 0.5)):
            p0 = [sh[i][0] + 20, sh[i][1] - 15]
            p1 = [sh[j][0] - 10, sh[j][1] + 30]
            along.append({"shape": sh, "p0": p0, "p1": p1, "f": f, "xy": list(along_shape(sh, p0, p1, f))})
    cands = [shapes[p["shape"]] for p in pats if p["route"] == "9"]
    pick = []
    for k in (0, 1):
        sh = cands[k]
        p0, p1 = sh[len(sh) // 4], sh[len(sh) // 2]
        b = best_shape(cands, p0, p1)
        pick.append({"p0": p0, "p1": p1, "index": next(i for i, c in enumerate(cands) if b is not None and c == b.tolist())})
    with open(VIEWER / "test" / "fixtures" / "along.json", "w") as f:
        json.dump({"source": "simchi.transit.interp on the GTFS extract", "cases": along,
                   "best": {"shapes": cands, "cases": pick}}, f)
    print(len(along), "along-shape cases,", len(pick), "best-shape cases")
    pts = [(-87.6298, 41.8781), (-87.9073, 41.9742), (-87.524, 41.645), (-87.6359, 41.8789), (-87.94, 42.023)]
    with open(VIEWER / "test" / "fixtures" / "utm.json", "w") as f:
        json.dump([[lo, la, *to_utm(lo, la)] for lo, la in pts], f)
    print(len(cases), "position cases,", len(pts), "UTM points")


if __name__ == "__main__":
    main()
