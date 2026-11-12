"""Transit network times from the CTA GTFS extract (data/transit/).

A trip by transit is a path in a time-expanded-free ("frequency-based") graph:

    origin point --walk--> stop (depart) --board: wait--> pattern stop k --ride--> pattern stop k+1
    ... --alight--> stop (arrive) --walk transfer--> stop (depart) --board--> ... --walk--> destination

Nodes: zone points (origins and destinations), each used stop twice (departure side and arrival
side, so that every path boards at least one vehicle), and each (pattern, position) pair.

Edge costs (minutes, for choosing the path; the path's components are reported separately):
  walk      CIRCUITY * straight-line distance / WALK_KMH, weighted by PATH_W_WALK; access and
            egress to stops within ACCESS_M of the point (the ACCESS_MIN_STOPS nearest if none),
            transfers between stops within TRANSFER_M
  wait      half the scheduled headway of all trips of the same route and direction that serve
            this stop and the pattern's next stop, in the time band (weekday, 6-9 am for commutes),
            capped at WAIT_CAP_MIN, weighted by PATH_W_WAIT, plus TRANSFER_PENALTY_MIN per boarding
  ride      median scheduled in-vehicle time between consecutive stops of the pattern in the band
Patterns with no trip in the band are not available.

Jobs outside Chicago (column OUTSIDE of the distance matrix) are reached through a "regional
leg" from any stop within REGIONAL_RADIUS_KM of the area's nearest gateway (the
REGIONAL_MIN_STOPS nearest stops if fewer): REGIONAL_TERMINAL_MIN
+ CIRCUITY * (distance + OUTSIDE_EXTRA_KM) / REGIONAL_KMH. Pace and Metra are not modelled; this
leg is an assumption and is reported as in-vehicle time.

The shortest-path tree from every origin point is computed with Dijkstra (scipy); path components
(walk, wait, in-vehicle minutes, boardings, rail boardings) are summed along the tree by pointer
doubling. Area-to-area values are means over all pairs of the areas' zone points (ZONE_POINTS per
area, sampled by tract population with a fixed seed; pairs of a point with itself are excluded).

Scenario knobs act on the graph: a headway multiplier and an in-vehicle time multiplier per mode
(bus, rail) or per route, and fares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from simchi.transit.gtfs import BANDS, load_extract

CIRCUITY = 1.3
WALK_KMH = 4.8
ACCESS_M = 800.0
ACCESS_MIN_STOPS = 3
TRANSFER_M = 250.0
WAIT_CAP_MIN = 20.0
PATH_W_WALK = 2.0
PATH_W_WAIT = 2.0
TRANSFER_PENALTY_MIN = 5.0
REGIONAL_RADIUS_KM = 8.0
REGIONAL_TERMINAL_MIN = 10.0
REGIONAL_MIN_STOPS = 20
REGIONAL_KMH = 25.0
ZONE_POINTS = 6
ASSIGN_POINTS = 20           # zone points per area for loading trips onto paths (ridership)
ZONE_SEED = 2026
# CTA fares read 2026-11-12 (transitchicago.com/fares): 'L' $2.50, bus $2.25, up to two further
# rides within 2 hours free. A path that uses the 'L' is charged $2.50, otherwise $2.25.
FARE_RAIL = 2.50
FARE_BUS = 2.25

COMPONENTS = ("walk", "wait", "ivt", "boardings", "rail_boardings")


def _walk_min(d_m):
    return CIRCUITY * np.asarray(d_m, float) / 1000.0 / WALK_KMH * 60.0


@dataclass
class NetworkScenario:
    """Changes to scheduled service. Keys of the dicts are "bus", "rail" or a route id (a route id
    takes precedence over its mode)."""
    headway_multiplier: dict = field(default_factory=dict)
    ivt_multiplier: dict = field(default_factory=dict)
    wait_multiplier: dict = field(default_factory=dict)      # e.g. more regular service (hypothesis)
    fare_bus: float = FARE_BUS
    fare_rail: float = FARE_RAIL
    day: str = "weekday"
    band: str = "am_peak"

    def factor(self, which: dict, route: str, rail: bool) -> float:
        if route in which:
            return float(which[route])
        return float(which.get("rail" if rail else "bus", 1.0))

    def key(self):
        nz = lambda d: tuple(sorted((k, float(v)) for k, v in d.items() if float(v) != 1.0))  # noqa: E731
        key = (nz(self.headway_multiplier), nz(self.ivt_multiplier), self.fare_bus, self.fare_rail, self.day, self.band)
        w = nz(self.wait_multiplier)
        return key + (w,) if w else key


@dataclass
class Skim:
    """Area-to-area transit skim (77 x 78, last column: outside Chicago), minutes and counts."""
    walk: np.ndarray
    wait: np.ndarray
    ivt: np.ndarray
    boardings: np.ndarray
    fare: np.ndarray
    scenario: NetworkScenario

    @property
    def transfers(self) -> np.ndarray:
        return np.maximum(self.boardings - 1.0, 0.0)

    @property
    def total(self) -> np.ndarray:
        """Unweighted door-to-door minutes (walk + wait + in-vehicle)."""
        return self.walk + self.wait + self.ivt


def zone_points(world, k: int = ZONE_POINTS) -> np.ndarray:
    """(77, k, 2) points per community area, by tract population, fixed seed."""
    rng = np.random.default_rng(ZONE_SEED)
    return np.stack([world.sample_points(a, k, rng) for a in world.areas.index])


class Graph:
    """The static part of the network graph (everything except scenario-dependent weights)."""

    def __init__(self, world, k: int = ZONE_POINTS):
        self.K = k
        self.world = world
        stops = load_extract("stops")
        pats = load_extract("patterns")
        routes = {r["id"]: r for r in load_extract("routes")}
        self.stop_ids = [s["id"] for s in stops]
        self.stop_parent = [s.get("parent") or s["id"] for s in stops]
        sidx = {s: i for i, s in enumerate(self.stop_ids)}
        self.stop_xy = np.array([[s["x"], s["z"]] for s in stops], float)
        ns = len(stops)
        self.pats = pats
        self.pat_rail = np.array([routes[p["route"]]["type"] == 1 for p in pats])

        # node layout: [dep stops | arr stops | pattern positions | origin points | dest points | gateways]
        self.n_stop = ns
        self.pat_off = np.cumsum([0] + [len(p["stops"]) for p in pats])
        n_pat_nodes = int(self.pat_off[-1])
        self.P0 = 2 * ns
        Z = zone_points(world, k)
        self.zone_xy = Z.reshape(-1, 2)
        nz = len(self.zone_xy)
        self.O0 = self.P0 + n_pat_nodes
        self.D0 = self.O0 + nz
        self.G0 = self.D0 + nz
        self.n_nodes = self.G0 + len(world.gateway_xy)
        self.node_kind = np.zeros(self.n_nodes, np.int8)        # 0 dep, 1 arr, 2 pattern, 3 origin, 4 dest, 5 gateway
        self.node_kind[ns:2 * ns] = 1
        self.node_kind[self.P0:self.O0] = 2
        self.node_kind[self.O0:self.D0] = 3
        self.node_kind[self.D0:self.G0] = 4
        self.node_kind[self.G0:] = 5

        # pattern node attributes
        self.pnode_pat = np.repeat(np.arange(len(pats)), np.diff(self.pat_off))
        self.pnode_stop = np.array([sidx[s] for p in pats for s in p["stops"]])
        self.pnode_pos = np.concatenate([np.arange(len(p["stops"])) for p in pats])

        tree = cKDTree(self.stop_xy)
        # walking edges that do not depend on the scenario: access, egress, transfers
        rows, cols, w = [], [], []
        for q, xy in enumerate(self.zone_xy):
            near = tree.query_ball_point(xy, ACCESS_M)
            if len(near) < ACCESS_MIN_STOPS:
                near = list(tree.query(xy, ACCESS_MIN_STOPS)[1])
            d = np.hypot(*(self.stop_xy[near] - xy).T)
            rows += [self.O0 + q] * len(near) + list(ns + np.asarray(near))
            cols += list(near) + [self.D0 + q] * len(near)
            w += list(_walk_min(d)) * 2
        pairs = tree.query_pairs(TRANSFER_M, output_type="ndarray")
        d = np.hypot(*(self.stop_xy[pairs[:, 0]] - self.stop_xy[pairs[:, 1]]).T)
        for a, b in ((0, 1), (1, 0)):
            rows += list(ns + pairs[:, a])
            cols += list(pairs[:, b])
            w += list(_walk_min(d))
        rows += list(ns + np.arange(ns))            # same-stop transfer
        cols += list(np.arange(ns))
        w += [0.0] * ns
        self.walk_edges = (np.asarray(rows), np.asarray(cols), PATH_W_WALK * np.asarray(w))
        # regional legs to the gateways
        from simchi.world import OUTSIDE_EXTRA_KM
        rr, rc, rw = [], [], []
        for g, gxy in enumerate(world.gateway_xy):
            near = tree.query_ball_point(gxy, REGIONAL_RADIUS_KM * 1000.0)
            if len(near) < REGIONAL_MIN_STOPS:
                near = list(tree.query(gxy, REGIONAL_MIN_STOPS)[1])
            d = np.hypot(*(self.stop_xy[near] - gxy).T) / 1000.0
            rr += list(ns + np.asarray(near))
            rc += [self.G0 + g] * len(near)
            rw += list(REGIONAL_TERMINAL_MIN + CIRCUITY * (d + OUTSIDE_EXTRA_KM) / REGIONAL_KMH * 60.0)
        self.regional_edges = (np.asarray(rr), np.asarray(rc), np.asarray(rw))

    def transit_edges(self, sc: NetworkScenario):
        """Boarding, riding and alighting edges and the per-node wait and in-vehicle minutes."""
        h0, h1 = BANDS[sc.band]
        band_min = (h1 - h0) * 60.0
        ns = self.n_stop
        # trips per band of each route-direction serving each consecutive stop pair
        seg_trips = {}
        for p in self.pats:
            n = p.get("trips_band", {}).get(sc.day, {}).get(sc.band, 0)
            for a, b in zip(p["stops"][:-1], p["stops"][1:], strict=True):
                k = (p["route"], p["direction"], a, b)
                seg_trips[k] = seg_trips.get(k, 0) + n
        wait = np.full(self.O0 - self.P0, np.nan)
        ivt_in = np.zeros(self.O0 - self.P0)
        rows, cols, w = [], [], []
        for i, p in enumerate(self.pats):
            off = p["offsets_min"].get(sc.band)
            mine = p.get("trips_band", {}).get(sc.day, {}).get(sc.band, 0)
            if off is None or mine == 0:
                continue
            rail = bool(self.pat_rail[i])
            hm = sc.factor(sc.headway_multiplier, p["route"], rail)
            im = sc.factor(sc.ivt_multiplier, p["route"], rail)
            wm = sc.factor(sc.wait_multiplier, p["route"], rail)
            base = int(self.pat_off[i])
            st = p["stops"]
            for k in range(len(st)):
                node = base + k
                if k < len(st) - 1:
                    trips = seg_trips[(p["route"], p["direction"], st[k], st[k + 1])]
                    wt = min(0.5 * band_min / trips * hm, WAIT_CAP_MIN) * wm
                    wait[node] = wt
                    rows.append(self.pnode_stop[node])                       # board
                    cols.append(self.P0 + node)
                    w.append(PATH_W_WAIT * wt + TRANSFER_PENALTY_MIN)
                    seg = max(off[k + 1] - off[k], 0.0) * im
                    ivt_in[node + 1] = seg
                    rows.append(self.P0 + node)                              # ride
                    cols.append(self.P0 + node + 1)
                    w.append(seg)
                if k > 0:
                    rows.append(self.P0 + node)                              # alight
                    cols.append(ns + self.pnode_stop[node])
                    w.append(0.0)
        return (np.asarray(rows), np.asarray(cols), np.asarray(w, float)), wait, ivt_in

    def matrix(self, sc: NetworkScenario):
        """Sparse graph for a scenario, with the per-node wait and in-vehicle minutes."""
        (tr, tc, tw), wait_node, ivt_node = self.transit_edges(sc)
        wr, wc, ww = self.walk_edges
        gr, gc, gw = self.regional_edges
        r = np.concatenate([tr, wr, gr])
        c = np.concatenate([tc, wc, gc])
        w = np.concatenate([tw, ww, gw]) + 1e-9          # explicit zeros would be dropped
        G = csr_matrix((w, (r, c)), shape=(self.n_nodes, self.n_nodes))
        G.sum_duplicates()
        return G, wait_node, ivt_node

    def dest_nodes(self):
        return np.arange(self.D0, self.n_nodes)          # destination points, then gateways

    def point_components(self, sc: NetworkScenario, src: np.ndarray, G=None, wait_node=None, ivt_node=None):
        """(len(COMPONENTS) + 1, len(src), n_dest) path components (and generalised cost, last)
        from zone points `src` (indices into zone_xy) to every destination point and gateway."""
        if G is None:
            G, wait_node, ivt_node = self.matrix(sc)
        kind = self.node_kind
        is_p = kind == 2
        dests = self.dest_nodes()
        rail_node = np.zeros(self.n_nodes, bool)
        rail_node[self.P0:self.O0] = self.pat_rail[self.pnode_pat]
        dist, pred = dijkstra(G, indices=self.O0 + np.asarray(src), return_predecessors=True)
        m = len(src)
        vals = np.zeros((len(COMPONENTS), m, self.n_nodes))
        valid = pred >= 0
        pr = np.where(valid, pred, 0)
        pkind = kind[pr]
        ddiff = np.where(valid, dist - np.take_along_axis(dist, pr, 1), 0.0)
        # walk edges end at departure stops (from an origin or an arrival stop) and at destinations
        walk_edge = valid & ((pkind == 3) | ((pkind == 1) & (kind[None, :] == 0)) | (kind[None, :] == 4))
        vals[0] = np.where(walk_edge, ddiff / PATH_W_WALK, 0.0)
        board = valid & is_p[None, :] & (pkind == 0)
        ride = valid & is_p[None, :] & (pkind == 2)
        wn = np.zeros(self.n_nodes)
        wn[self.P0:self.O0] = np.nan_to_num(wait_node)
        iv = np.zeros(self.n_nodes)
        iv[self.P0:self.O0] = ivt_node
        vals[1] = np.where(board, wn[None, :], 0.0)
        vals[2] = np.where(ride, iv[None, :], 0.0) + np.where(valid & (kind[None, :] == 5), ddiff, 0.0)
        vals[3] = board
        vals[4] = board & rail_node[None, :]
        # pointer doubling: after round r, S[n] sums the edge values of the last 2^r edges of the
        # tree path into n and P[n] is the 2^r-th ancestor (-1 once past the source)
        P = np.where(valid, pred, -1)
        S = vals
        rows_ = np.arange(m)[:, None]
        while (P >= 0).any():
            ok = P >= 0
            Pc = np.where(ok, P, 0)
            S = S + np.where(ok[None], S[:, rows_, Pc], 0.0)
            P = np.where(ok, P[rows_, Pc], -1)
        out = np.empty((len(COMPONENTS) + 1, m, len(dests)))
        out[:len(COMPONENTS)] = S[:, :, dests]
        out[-1] = dist[:, dests]
        return out, (dist, pred)

    def skim(self, sc: NetworkScenario | None = None, chunk: int = 48) -> Skim:
        sc = sc or NetworkScenario()
        G, wait_node, ivt_node = self.matrix(sc)
        nz = len(self.zone_xy)
        out = np.zeros((len(COMPONENTS) + 1, nz, len(self.dest_nodes())))
        for s0 in range(0, nz, chunk):
            src = np.arange(s0, min(nz, s0 + chunk))
            out[:, src], _ = self.point_components(sc, src, G, wait_node, ivt_node)
        if not np.isfinite(out[-1]).all():
            raise RuntimeError("some zone points cannot reach some destinations by transit")
        return self._aggregate(out, sc)

    def assign(self, sc: NetworkScenario, demand: np.ndarray, chunk: int = 48) -> dict:
        """Load trips onto the shortest paths (all-or-nothing assignment).

        demand: (n_zone_points, n_dest) trips from each zone point to each destination point
        and gateway (columns as dest_nodes()). Returns boardings per pattern and 'L' entries
        per rail stop. Flows are summed over each shortest-path tree by doubling: with M the
        child-to-parent map, total flow through every node is sum_j M^j q = prod_k (I + M^(2^k)) q,
        and M^(2^k) is the 2^k-th-ancestor map. An 'L' entry is a boarding of a rail pattern
        whose path reached the platform on foot from the origin or from a bus (not from
        another 'L' line: transfers between lines are assumed to stay inside the paid area)."""
        G, wait_node, ivt_node = self.matrix(sc)
        kind = self.node_kind
        dests = self.dest_nodes()
        nz = len(self.zone_xy)
        n = self.n_nodes
        rail_p = np.zeros(n, bool)
        rail_p[self.P0:self.O0] = self.pat_rail[self.pnode_pat]
        board_total = np.zeros(n)
        entry_total = np.zeros(n)
        for s0 in range(0, nz, chunk):
            src = np.arange(s0, min(nz, s0 + chunk))
            m = len(src)
            dist, pred = dijkstra(G, indices=self.O0 + src, return_predecessors=True)
            f = np.zeros((m, n))
            f[:, dests] = demand[src]
            P = np.where(pred >= 0, pred, -1)
            offs = (np.arange(m) * n)[:, None]
            while (P >= 0).any():
                ok = P >= 0
                add = np.bincount((P + offs)[ok], weights=f[ok], minlength=m * n).reshape(m, n)
                f = f + add
                Pc = np.where(ok, P, 0)
                P = np.where(ok, np.take_along_axis(P, Pc, 1), -1)
            pr = np.where(pred >= 0, pred, 0)
            board = (pred >= 0) & (kind[None, :] == 2) & (kind[pr] == 0)
            # how the departure stop was reached: on foot from the origin, or via an arrival stop
            pp = np.take_along_axis(pr, pr, 1)                         # pred of the departure stop
            ppp = np.take_along_axis(pr, pp, 1)                        # pred of that arrival stop
            from_origin = kind[pp] == 3
            from_bus = (kind[pp] == 1) & (kind[ppp] == 2) & ~rail_p[ppp]
            entry = board & rail_p[None, :] & (from_origin | from_bus)
            board_total += np.where(board, f, 0.0).sum(0)
            entry_total += np.where(entry, f, 0.0).sum(0)
        pat_board = np.bincount(self.pnode_pat, weights=board_total[self.P0:self.O0], minlength=len(self.pats))
        stop_entry = np.bincount(self.pnode_stop, weights=entry_total[self.P0:self.O0], minlength=self.n_stop)
        return {"pattern_boardings": pat_board, "stop_entries": stop_entry}

    def area_demand_to_points(self, T: np.ndarray) -> np.ndarray:
        """Spread an area-level trip matrix (77, 78; last column outside Chicago) evenly over the
        zone-point pairs (a point is not paired with itself) and the nearest gateway."""
        nA = self.world.n_areas
        K = self.K
        D = np.zeros((nA * K, len(self.dest_nodes())))
        inner = np.repeat(np.repeat(T[:, :nA], K, 0), K, 1)
        cnt = np.full((nA, nA), K * K, float)
        cnt[np.diag_indices(nA)] = K * (K - 1)
        inner = inner / np.repeat(np.repeat(cnt, K, 0), K, 1)
        np.fill_diagonal(inner, 0.0)
        D[:, :nA * K] = inner
        for i in range(nA):
            D[i * K:(i + 1) * K, nA * K + self.world.nearest_gateway[i]] = T[i, nA] / K
        return D

    def _aggregate(self, out, sc):
        nA = self.world.n_areas
        K = self.K
        nz = nA * K
        comp = {k: out[i] for i, k in enumerate(COMPONENTS)}
        fare = np.where(comp["rail_boardings"] > 0, sc.fare_rail, sc.fare_bus)
        res = {}
        for name, M in (*comp.items(), ("fare", fare)):
            inner = M[:, :nz].reshape(nA, K, nA, K)
            A = inner.sum((1, 3))
            # exclude each point paired with itself on the diagonal
            selfpairs = np.einsum("akak->a", inner)
            A[np.diag_indices(nA)] -= selfpairs
            cnt = np.full((nA, nA), K * K, float)
            cnt[np.diag_indices(nA)] = K * (K - 1)
            A /= cnt
            gate = M[:, nz:].reshape(nA, K, -1).mean(1)        # (77, n_gateways)
            outside = gate[np.arange(nA), self.world.nearest_gateway]
            res[name] = np.column_stack([A, outside])
        return Skim(walk=res["walk"], wait=res["wait"], ivt=res["ivt"], boardings=res["boardings"],
                    fare=res["fare"], scenario=sc)


@lru_cache(maxsize=2)
def _graph(k: int = ZONE_POINTS):
    from simchi.world import build_world
    return Graph(build_world(), k)


_SKIMS: dict = {}


def _cache_path(sc: NetworkScenario):
    import hashlib
    from pathlib import Path

    from simchi.paths import RUNS
    from simchi.transit.gtfs import TRANSIT
    h = hashlib.sha256(repr(sc.key()).encode())
    h.update(Path(__file__).read_bytes())
    h.update((TRANSIT / "meta.json").read_bytes())
    h.update((TRANSIT / "patterns.json").read_bytes())
    return RUNS / ".cache" / f"skim_{h.hexdigest()[:20]}.npz"


def skim(sc: NetworkScenario | None = None, cache: bool = True) -> Skim:
    """Area-to-area transit skim for a scenario, cached in this process and on disk
    (runs/.cache, keyed by the scenario, this module's code and the GTFS extract)."""
    sc = sc or NetworkScenario()
    k = sc.key()
    if k in _SKIMS:
        return _SKIMS[k]
    path = _cache_path(sc)
    if cache and path.exists():
        z = np.load(path)
        out = Skim(walk=z["walk"], wait=z["wait"], ivt=z["ivt"], boardings=z["boardings"], fare=z["fare"], scenario=sc)
    else:
        out = _graph().skim(sc)
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp.npz")
            np.savez_compressed(tmp, walk=out.walk, wait=out.wait, ivt=out.ivt, boardings=out.boardings, fare=out.fare)
            tmp.replace(path)
    _SKIMS[k] = out
    return out
