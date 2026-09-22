"""Map layout (Doc 07, "the map"): a crossing-free straight-line chart of the location
graph, computed once per topology and cached.

Locations carry a distance-weighted neighbour graph and, optionally, an authored chart
position (`Location.x`/`y`, the generator's grid). The authored grid keeps the author's
geography (river valley north-west, coast east) but is not itself crossing-free — seven
of `tests/scenarios/three_bands.yaml`'s forty edges cross on it, two of them straight through
another node — and a plain spring layout gives no planarity guarantee either. So the
layout is an optimisation: start from the authored grid (or a seeded spring layout when
none is authored), then run a deterministic simulated-annealing pass over node
positions on an energy that charges a crossing far more than any aesthetic term
(edge-length stress, node separation, edge-to-node clearance), polish at zero
temperature, and retry with a fresh seed while any crossing survives. The result is
verified, not assumed: `tests/test_layout.py` checks every shipped scenario for zero
crossings and a minimum edge-to-node clearance.

Everything here is deterministic — seeded from a digest of the topology, never from
`world.rng`, which stays reserved for the simulation — so the map is still between
ticks and identical across runs. No external dependency: `numpy` is the only
numeric package in the environment and a planar-embedding library isn't.
"""

from __future__ import annotations

import hashlib
import math
import random

from stock.core.world import World

Point = tuple[float, float]
Edge = tuple[str, str]

#: Energy charged per edge crossing — dominates every aesthetic term so the annealer
#: only ever trades crossings for ugliness, never the other way round.
CROSSING_PENALTY = 1000.0
#: Annealing schedule (moves per node); the polish phase runs at ~zero temperature.
ANNEAL_MOVES_PER_NODE = 220
POLISH_MOVES_PER_NODE = 90
MAX_ATTEMPTS = 6

_layout_cache: dict[str, dict[str, Point]] = {}


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def _orient(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, c: Point) -> bool:
    return (
        min(a[0], b[0]) - 1e-12 <= c[0] <= max(a[0], b[0]) + 1e-12
        and min(a[1], b[1]) - 1e-12 <= c[1] <= max(a[1], b[1]) + 1e-12
    )


def segments_cross(p1: Point, p2: Point, p3: Point, p4: Point) -> bool:
    """True if closed segments p1p2 and p3p4 share any point (proper crossing, touching,
    or collinear overlap). Callers exclude edge pairs that share an endpoint."""

    o1 = _orient(p1, p2, p3)
    o2 = _orient(p1, p2, p4)
    o3 = _orient(p3, p4, p1)
    o4 = _orient(p3, p4, p2)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if abs(o1) < 1e-12 and _on_segment(p1, p2, p3):
        return True
    if abs(o2) < 1e-12 and _on_segment(p1, p2, p4):
        return True
    if abs(o3) < 1e-12 and _on_segment(p3, p4, p1):
        return True
    return bool(abs(o4) < 1e-12 and _on_segment(p3, p4, p2))


def point_segment_distance(p: Point, a: Point, b: Point) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / length_sq
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def count_crossings(pos: dict[str, Point], edges: list[Edge]) -> int:
    """Pairs of edges (not sharing an endpoint) that cross — the number the test pins
    to zero."""

    n = 0
    for i, (a, b) in enumerate(edges):
        for c, d in edges[i + 1 :]:
            if a in (c, d) or b in (c, d):
                continue
            if segments_cross(pos[a], pos[b], pos[c], pos[d]):
                n += 1
    return n


def min_edge_node_clearance(pos: dict[str, Point], edges: list[Edge]) -> float:
    """Smallest distance from any node to an edge it is not an endpoint of."""

    best = math.inf
    for a, b in edges:
        for node, p in pos.items():
            if node in (a, b):
                continue
            best = min(best, point_segment_distance(p, pos[a], pos[b]))
    return best


# ---------------------------------------------------------------------------
# the graph
# ---------------------------------------------------------------------------


def topology_key(world: World) -> str:
    edges = sorted(
        f"{lid}:{nid}:{d}" for lid, loc in world.locations.items() for nid, d in loc.neighbours.items()
    )
    authored = sorted(f"{lid}:{loc.x}:{loc.y}" for lid, loc in world.locations.items())
    payload = "|".join(sorted(world.locations)) + "#" + "|".join(edges) + "#" + "|".join(authored)
    return hashlib.sha256(payload.encode()).hexdigest()


def graph_edges(world: World) -> list[Edge]:
    ids = sorted(world.locations)
    return [
        (a, b) for a in ids for b in sorted(world.locations[a].neighbours) if b in world.locations and a < b
    ]


def _seed_xy(loc_id: str) -> Point:
    digest = hashlib.sha256(loc_id.encode()).digest()
    return int.from_bytes(digest[0:4], "big") / 0xFFFFFFFF, int.from_bytes(digest[4:8], "big") / 0xFFFFFFFF


def _spring_layout(ids: list[str], edges: list[Edge]) -> dict[str, Point]:
    """The seeded Fruchterman-Reingold pass the layout used before the annealer
    existed; now only the starting point when a scenario authors no grid."""

    pos = {lid: _seed_xy(lid) for lid in ids}
    k = 1.0 / max(1.0, math.sqrt(len(ids)))
    for _ in range(300):
        disp: dict[str, list[float]] = {lid: [0.0, 0.0] for lid in ids}
        for i, a in enumerate(ids):
            ax, ay = pos[a]
            for b in ids[i + 1 :]:
                bx, by = pos[b]
                dx, dy = ax - bx, ay - by
                dist = max(math.hypot(dx, dy), 1e-4)
                force = (k * k) / dist * 0.02
                disp[a][0] += dx / dist * force
                disp[a][1] += dy / dist * force
                disp[b][0] -= dx / dist * force
                disp[b][1] -= dy / dist * force
        for a, b in edges:
            ax, ay = pos[a]
            bx, by = pos[b]
            dx, dy = ax - bx, ay - by
            dist = max(math.hypot(dx, dy), 1e-4)
            force = (dist * dist) / k * 0.02
            disp[a][0] -= dx / dist * force
            disp[a][1] -= dy / dist * force
            disp[b][0] += dx / dist * force
            disp[b][1] += dy / dist * force
        for lid in ids:
            dx, dy = disp[lid]
            mag = max(math.hypot(dx, dy), 1e-9)
            step = min(mag, 0.02)
            x, y = pos[lid]
            pos[lid] = (x + dx / mag * step, y + dy / mag * step)
    return pos


def _authored_positions(world: World, ids: list[str]) -> dict[str, Point] | None:
    if not all(world.locations[lid].x is not None and world.locations[lid].y is not None for lid in ids):
        return None
    # Authored `y` grows northward (the generator's convention); the canvas grows
    # downward, so flip it here once.
    return {lid: (float(world.locations[lid].x or 0.0), -float(world.locations[lid].y or 0.0)) for lid in ids}


def _scatter(ids: list[str], seed: int, span: float) -> dict[str, Point]:
    rng = random.Random(seed)
    return {lid: (rng.uniform(0.0, span), rng.uniform(0.0, span)) for lid in ids}


# ---------------------------------------------------------------------------
# the annealer
# ---------------------------------------------------------------------------


class _Annealer:
    """Local-energy simulated annealing over node positions (see module docstring).
    Only the terms a moved node participates in are recomputed per move."""

    def __init__(
        self,
        ids: list[str],
        edges: list[Edge],
        ideal: dict[Edge, float],
        pos: dict[str, Point],
        rng: random.Random,
    ) -> None:
        self.ids = ids
        self.edges = edges
        self.ideal = ideal
        self.pos = dict(pos)
        self.rng = rng
        self.incident: dict[str, list[Edge]] = {lid: [] for lid in ids}
        for e in edges:
            self.incident[e[0]].append(e)
            self.incident[e[1]].append(e)
        base = sum(ideal.values()) / max(1, len(ideal)) if ideal else 1.0
        self.base = base
        self.min_sep = 0.62 * base
        self.clearance = 0.40 * base

    # -- energy ------------------------------------------------------------

    def node_energy(self, n: str) -> float:
        pos = self.pos
        p = pos[n]
        e_total = 0.0
        incident = self.incident[n]
        incident_set = set(incident)

        # crossings between an incident edge and any edge not touching n
        for a, b in incident:
            pa, pb = pos[a], pos[b]
            other = b if a == n else a
            for c, d in self.edges:
                if (c, d) in incident_set or c == other or d == other:
                    continue
                if segments_cross(pa, pb, pos[c], pos[d]):
                    e_total += CROSSING_PENALTY

        # edge-length stress on incident edges
        for a, b in incident:
            length = math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
            r = length / self.ideal[(a, b)] - 1.0
            e_total += r * r

        # node separation, and clearance of n from non-incident edges
        for m in self.ids:
            if m == n:
                continue
            q = pos[m]
            sep = math.hypot(p[0] - q[0], p[1] - q[1])
            if sep < self.min_sep:
                t = 1.0 - sep / self.min_sep
                e_total += 2.0 * t * t
        for c, d in self.edges:
            if (c, d) in incident_set:
                continue
            dist = point_segment_distance(p, pos[c], pos[d])
            if dist < self.clearance:
                t = 1.0 - dist / self.clearance
                e_total += 4.0 * t * t

        # clearance of other nodes from n's incident edges
        for a, b in incident:
            pa, pb = pos[a], pos[b]
            for m in self.ids:
                if m == a or m == b:
                    continue
                dist = point_segment_distance(pos[m], pa, pb)
                if dist < self.clearance:
                    t = 1.0 - dist / self.clearance
                    e_total += 4.0 * t * t
        return e_total

    def crossings(self) -> int:
        return count_crossings(self.pos, self.edges)

    # -- moves -------------------------------------------------------------

    def run(self, moves: int, t_start: float, t_end: float, amp_start: float, amp_end: float) -> None:
        rng = self.rng
        ids = self.ids
        n_ids = len(ids)
        if n_ids < 2 or moves <= 0:
            return
        tangled: list[str] = []
        for i in range(moves):
            frac = i / max(1, moves - 1)
            temp = t_start * (t_end / t_start) ** frac if t_start > 0 else 0.0
            amp = amp_start * (amp_end / amp_start) ** frac
            if temp > 0.0 and i % 40 == 0:
                tangled = self.tangled_nodes()
            roll = rng.random()
            if tangled and roll < 0.25:
                # A long jump for a node on a crossing edge: the only move that can
                # carry a vertex across a cluster, which local jitter never does.
                self._jump_move(rng.choice(tangled), temp)
            elif roll < 0.35 and temp > 0.05:
                self._swap_move(temp)
            else:
                self._jitter_move(temp, amp)

    def tangled_nodes(self) -> list[str]:
        pos = self.pos
        out: set[str] = set()
        for i, (a, b) in enumerate(self.edges):
            for c, d in self.edges[i + 1 :]:
                if a in (c, d) or b in (c, d):
                    continue
                if segments_cross(pos[a], pos[b], pos[c], pos[d]):
                    out.update((a, b, c, d))
        return sorted(out)

    def _jump_move(self, n: str, temp: float) -> None:
        xs = [p[0] for p in self.pos.values()]
        ys = [p[1] for p in self.pos.values()]
        pad = self.base
        old = self.pos[n]
        before = self.node_energy(n)
        self.pos[n] = (
            self.rng.uniform(min(xs) - pad, max(xs) + pad),
            self.rng.uniform(min(ys) - pad, max(ys) + pad),
        )
        after = self.node_energy(n)
        if not self._accept(after - before, temp):
            self.pos[n] = old

    def _accept(self, delta: float, temp: float) -> bool:
        if delta <= 0.0:
            return True
        if temp <= 0.0:
            return False
        return self.rng.random() < math.exp(-delta / temp)

    def _jitter_move(self, temp: float, amp: float) -> None:
        n = self.rng.choice(self.ids)
        old = self.pos[n]
        before = self.node_energy(n)
        self.pos[n] = (old[0] + self.rng.gauss(0.0, amp), old[1] + self.rng.gauss(0.0, amp))
        after = self.node_energy(n)
        if not self._accept(after - before, temp):
            self.pos[n] = old

    def _swap_move(self, temp: float) -> None:
        a, b = self.rng.sample(self.ids, 2)
        before = self.node_energy(a) + self.node_energy(b)
        self.pos[a], self.pos[b] = self.pos[b], self.pos[a]
        after = self.node_energy(a) + self.node_energy(b)
        if not self._accept(after - before, temp):
            self.pos[a], self.pos[b] = self.pos[b], self.pos[a]


def _ideal_lengths(world: World, edges: list[Edge], pos: dict[str, Point]) -> dict[Edge, float]:
    """Ideal length per edge ∝ the scenario's own neighbour distance, scaled so the
    mean matches the starting layout's mean edge length (the annealer then never
    fights the authored scale)."""

    dists = {(a, b): float(world.locations[a].neighbours.get(b, 1.0)) or 1.0 for a, b in edges}
    if not edges:
        return {}
    mean_len = sum(math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]) for a, b in edges) / len(edges)
    mean_dist = sum(dists.values()) / len(dists)
    scale = (mean_len / mean_dist) if mean_len > 1e-9 and mean_dist > 1e-9 else 1.0
    return {e: max(1e-6, d * scale) for e, d in dists.items()}


def _fit(pos: dict[str, Point], width: float, height: float, margin: float) -> dict[str, Point]:
    """Uniform scale (aspect preserved) and centre into the canvas."""

    if not pos:
        return {}
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    span_x = max(max(xs) - min(xs), 1e-9)
    span_y = max(max(ys) - min(ys), 1e-9)
    scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)
    off_x = (width - span_x * scale) / 2 - min(xs) * scale
    off_y = (height - span_y * scale) / 2 - min(ys) * scale
    return {lid: (x * scale + off_x, y * scale + off_y) for lid, (x, y) in pos.items()}


def untangle(
    ids: list[str],
    edges: list[Edge],
    ideal: dict[Edge, float],
    start: dict[str, Point],
    seed: int,
    *,
    polish_only: bool = False,
) -> tuple[dict[str, Point], int]:
    """One attempt from `start`; returns (positions, crossings left). `polish_only`
    skips the hot phase: at zero temperature a move that adds a crossing costs
    `CROSSING_PENALTY` and is always rejected, so a crossing-free start stays one."""

    rng = random.Random(seed)
    ann = _Annealer(ids, edges, ideal, start, rng)
    base = ann.base
    n = len(ids)
    if not polish_only:
        ann.run(
            ANNEAL_MOVES_PER_NODE * n, t_start=0.6, t_end=0.003, amp_start=0.55 * base, amp_end=0.04 * base
        )
    ann.run(POLISH_MOVES_PER_NODE * n, t_start=0.0, t_end=0.0, amp_start=0.08 * base, amp_end=0.01 * base)
    return ann.pos, ann.crossings()


def compute_layout(world: World, *, width: float = 1000.0, height: float = 600.0) -> dict[str, Point]:
    """Canvas positions for every location, crossing-free where the graph allows it,
    cached per topology (see module docstring)."""

    key = topology_key(world)
    cached = _layout_cache.get(key)
    if cached is not None:
        return cached

    ids = sorted(world.locations)
    if not ids:
        _layout_cache[key] = {}
        return {}
    edges = graph_edges(world)
    authored = _authored_positions(world, ids)
    start = authored if authored is not None else _spring_layout(ids, edges)
    ideal = _ideal_lengths(world, edges, start)
    span = math.sqrt(len(ids)) * (sum(ideal.values()) / len(ideal) if ideal else 1.0)

    best_pos = start
    best_crossings = count_crossings(start, edges)
    if edges:
        seed_base = int(key[:8], 16)
        if best_crossings == 0:
            # A planar authored chart: only spread it out (separation, clearance,
            # even edge lengths) without ever admitting a crossing.
            best_pos, best_crossings = untangle(ids, edges, ideal, start, seed_base, polish_only=True)
        else:
            # Attempt 0 keeps the author's geography; later attempts scatter, which
            # costs the geography but reaches embeddings the authored start can't be
            # jittered into.
            for attempt in range(MAX_ATTEMPTS):
                seed = seed_base + attempt
                origin = start if attempt == 0 else _scatter(ids, seed, span)
                pos, crossings = untangle(ids, edges, ideal, origin, seed)
                if crossings <= best_crossings:
                    best_pos, best_crossings = pos, crossings
                if crossings == 0:
                    break

    fitted = _fit(best_pos, width, height, margin=64.0)
    _layout_cache[key] = fitted
    return fitted
