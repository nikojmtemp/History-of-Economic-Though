"""Procedural worlds (design doc §5): a seed is a world.

Steps: best-candidate points on a 5:3 canvas; their Gabriel graph (planar and
connected by construction, so the map never needs untangling); relief with an ocean
along one side; rivers walked downhill to the sea; terrain from elevation, moisture
and rivers; features (wild herds, rare goods, ore, coal); sea lanes between nearby
coasts; and starting bands spread apart by farthest-point sampling, each on game
near wild herds or arable ground.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from stock.game import rules
from stock.game.names import assign_names
from stock.game.state import Edge, Nation, Node, Unit, World


@dataclass(frozen=True)
class WorldGenConfig:
    seed: int = 0
    nodes: int = 45
    nations: int = 5
    rivers: int = 2

    def __post_init__(self) -> None:
        if not rules.MAP_NODES[0] <= self.nodes <= rules.MAP_NODES[1]:
            raise ValueError(f"a world has {rules.MAP_NODES[0]} to {rules.MAP_NODES[1]} nodes")
        if not 2 <= self.nations <= len(rules.NATION_COLOURS):
            raise ValueError(f"2 to {len(rules.NATION_COLOURS)} peoples")
        if self.nations * 5 > self.nodes:
            raise ValueError("at least 5 nodes per nation")


#: Canvas aspect (the map pane is 1000x600, `api.layout`).
CANVAS_W, CANVAS_H = 5.0, 3.0
#: Best-candidate sampling: candidates tried per placed point.
CANDIDATES_PER_POINT = 24
# --- geometry ------------------------------------------------------------------------


def _sample_points(rng: random.Random, n: int) -> list[tuple[float, float]]:
    """Best-candidate sampling: each new point is the one of `CANDIDATES_PER_POINT`
    random candidates farthest from every point placed so far."""

    points: list[tuple[float, float]] = [(rng.uniform(0.5, CANVAS_W - 0.5), rng.uniform(0.5, CANVAS_H - 0.5))]
    while len(points) < n:
        best: tuple[float, float] | None = None
        best_d = -1.0
        for _ in range(CANDIDATES_PER_POINT):
            c = (rng.uniform(0.0, CANVAS_W), rng.uniform(0.0, CANVAS_H))
            d = min(math.dist(c, p) for p in points)
            if d > best_d:
                best_d, best = d, c
        assert best is not None
        points.append(best)
    return points


def _gabriel_edges(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Edges `(i, j)` of the Gabriel graph: no third point inside the circle with
    `ij` as diameter. O(n^3) — fine for the few dozen locations a map holds."""

    n = len(points)
    edges: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            (ax, ay), (bx, by) = points[i], points[j]
            cx, cy = (ax + bx) / 2.0, (ay + by) / 2.0
            r2 = ((ax - bx) ** 2 + (ay - by) ** 2) / 4.0
            blocked = False
            for k in range(n):
                if k == i or k == j:
                    continue
                px, py = points[k]
                if (px - cx) ** 2 + (py - cy) ** 2 < r2 - 1e-12:
                    blocked = True
                    break
            if not blocked:
                edges.append((i, j))
    return edges


def _neighbours(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    nb: list[list[int]] = [[] for _ in range(n)]
    for i, j in edges:
        nb[i].append(j)
        nb[j].append(i)
    return nb


# --- relief ----------------------------------------------------------------------------


def _relief(
    rng: random.Random, points: list[tuple[float, float]]
) -> tuple[list[float], list[float], list[float], int]:
    """Returns `(elevation, moisture, distance_to_ocean, ocean_side)` per point, each
    field in [0, 1]. The ocean lies along one side of the canvas (0 W, 1 E, 2 S, 3 N)."""

    side = rng.randrange(4)

    def ocean_distance(p: tuple[float, float]) -> float:
        x, y = p
        return {0: x, 1: CANVAS_W - x, 2: y, 3: CANVAS_H - y}[side]

    far = CANVAS_W if side in (0, 1) else CANVAS_H
    hills = [
        (rng.uniform(0.0, CANVAS_W), rng.uniform(0.0, CANVAS_H), rng.uniform(0.5, 1.1), rng.uniform(0.3, 1.0))
        for _ in range(4)
    ]
    wet = [
        (
            rng.uniform(0.0, CANVAS_W),
            rng.uniform(0.0, CANVAS_H),
            rng.uniform(0.6, 1.4),
            rng.choice((-1.0, 1.0)),
        )
        for _ in range(5)
    ]

    elevation: list[float] = []
    moisture: list[float] = []
    distance: list[float] = []
    for p in points:
        d = ocean_distance(p)
        e = 0.15 + 0.6 * (d / far)  # climbs inland
        for hx, hy, hr, hh in hills:
            e += hh * math.exp(-((p[0] - hx) ** 2 + (p[1] - hy) ** 2) / (2.0 * hr * hr))
        e += rng.uniform(-0.08, 0.08)
        m = 0.5 - 0.25 * (d / far)  # sea air
        for wx, wy, wr, ws in wet:
            m += 0.35 * ws * math.exp(-((p[0] - wx) ** 2 + (p[1] - wy) ** 2) / (2.0 * wr * wr))
        m += rng.uniform(-0.1, 0.1)
        elevation.append(e)
        moisture.append(m)
        distance.append(d / far)

    def norm(v: list[float]) -> list[float]:
        lo, hi = min(v), max(v)
        return [(x - lo) / (hi - lo) if hi > lo else 0.5 for x in v]

    return norm(elevation), norm(moisture), distance, side


def _carve_rivers(
    rng: random.Random,
    elevation: list[float],
    distance: list[float],
    nb: list[list[int]],
    count: int,
) -> list[list[int]]:
    """Each river starts at a high, inland location and walks strictly downhill
    along edges until it can go no lower, preferring the neighbour closest to the
    ocean. Rivers don't share a source or cross a previous river's path."""

    n = len(elevation)
    taken: set[int] = set()
    rivers: list[list[int]] = []
    sources = sorted(range(n), key=lambda i: elevation[i] * 0.7 + distance[i] * 0.3, reverse=True)
    for src in sources:
        if len(rivers) >= count:
            break
        if src in taken:
            continue
        path = [src]
        cur = src
        while True:
            lower = [j for j in nb[cur] if elevation[j] < elevation[cur] and j not in taken]
            if not lower:
                break
            cur = min(lower, key=lambda j: (distance[j], elevation[j]))
            path.append(cur)
        if len(path) >= 3:
            rivers.append(path)
            taken.update(path)
    return rivers


# --- terrain and features ------------------------------------------------------------------


def _classify(
    elevation: list[float], moisture: list[float], distance: list[float], on_river: list[bool]
) -> list[str]:
    n = len(elevation)
    order = sorted(range(n), key=lambda i: elevation[i], reverse=True)
    mountain = set(order[: max(1, n // 12)])
    hills = set(order[max(1, n // 12) : max(2, n // 12 + n // 6)])
    terrain: list[str] = []
    for i in range(n):
        if distance[i] <= 0.15 and i not in mountain:
            terrain.append("COAST")
        elif i in mountain:
            terrain.append("MOUNTAIN")
        elif i in hills and not on_river[i]:
            terrain.append("HILLS")
        elif on_river[i]:
            terrain.append("VALLEY")
        elif moisture[i] > 0.78 and elevation[i] < 0.35:
            terrain.append("MARSH")
        elif moisture[i] > 0.52:
            terrain.append("FOREST")
        else:
            terrain.append("GRASSLAND")
    return terrain


def _features(rng: random.Random, terrain: list[str]) -> list[list[str]]:
    feats: list[list[str]] = [[] for _ in terrain]
    for i, t in enumerate(terrain):
        if (t == "GRASSLAND" and rng.random() < 0.6) or (t == "HILLS" and rng.random() < 0.3):
            feats[i].append("wild_herds")
        if (t == "HILLS" and rng.random() < 0.45) or (t == "MOUNTAIN" and rng.random() < 0.8):
            feats[i].append("ore")
        if (t == "MOUNTAIN" and rng.random() < 0.5) or (t == "FOREST" and rng.random() < 0.15):
            feats[i].append("coal")
    n = len(terrain)
    # rare goods: about one node in eight, coasts, forests and valleys first
    pool = [i for i in range(n) if terrain[i] in ("COAST", "FOREST", "VALLEY")] or list(range(n))
    rng.shuffle(pool)
    for i in pool[: max(2, n // 8)]:
        feats[i].append("rare")
    if not any("ore" in f for f in feats):
        cands = [i for i in range(n) if terrain[i] in ("HILLS", "MOUNTAIN")] or list(range(n))
        feats[rng.choice(cands)].append("ore")
    if not any("coal" in f for f in feats):
        feats[rng.randrange(n)].append("coal")
    return feats


# --- the generator ---------------------------------------------------------------------


def generate(config: WorldGenConfig | None = None, **overrides: int) -> World:
    cfg = config if config is not None else WorldGenConfig(**overrides)
    rng = random.Random(cfg.seed)
    n = cfg.nodes

    points = _sample_points(rng, n)
    pairs = _gabriel_edges(points)
    nb = _neighbours(n, pairs)
    elevation, moisture, distance, _side = _relief(rng, points)
    rivers = _carve_rivers(rng, elevation, distance, nb, cfg.rivers)
    on_river = [False] * n
    river_steps: set[tuple[int, int]] = set()
    for path in rivers:
        for a, b in zip(path, path[1:], strict=False):
            river_steps.add((min(a, b), max(a, b)))
        for i in path[1:]:
            on_river[i] = True
    terrain = _classify(elevation, moisture, distance, on_river)
    feats = _features(rng, terrain)
    herd_nodes = [i for i in range(n) if "wild_herds" in feats[i]]
    while len(herd_nodes) < max(3, cfg.nations + 1):
        cands = [
            i for i in range(n) if terrain[i] in ("GRASSLAND", "HILLS", "VALLEY") and i not in herd_nodes
        ]
        i = rng.choice(cands or [k for k in range(n) if k not in herd_nodes])
        feats[i].append("wild_herds")
        herd_nodes.append(i)

    ids = [f"n{i}" for i in range(n)]
    names = assign_names(cfg.seed, [(ids[i], terrain[i], on_river[i]) for i in range(n)], cfg.nations)
    nodes = {
        ids[i]: Node(
            id=ids[i],
            name=names.nodes[ids[i]],
            x=round(1000 * points[i][0] / CANVAS_W, 1),
            y=round(600 * points[i][1] / CANVAS_H, 1),
            terrain=terrain[i],
            river=on_river[i],
            coast=terrain[i] == "COAST",
            features=feats[i],
        )
        for i in range(n)
    }

    edges: list[Edge] = []
    for i, j in pairs:
        rough = rules.TERRAIN[terrain[i]].rough or rules.TERRAIN[terrain[j]].rough
        kind = "river" if (i, j) in river_steps else "rough" if rough else "path"
        edges.append(Edge(ids[i], ids[j], kind))
    # sea lanes: each coast to its two nearest coasts not already joined by land
    coasts = [i for i in range(n) if terrain[i] == "COAST"]
    joined = {(min(i, j), max(i, j)) for i, j in pairs}
    for i in coasts:
        near = sorted((c for c in coasts if c != i), key=lambda c: math.dist(points[i], points[c]))[:2]
        for c in near:
            key = (min(i, c), max(i, c))
            if key not in joined and math.dist(points[i], points[c]) < 1.6:
                joined.add(key)
                edges.append(Edge(ids[key[0]], ids[key[1]], "sea"))

    # starts: habitable game nodes near wild herds or arable ground, spread apart
    def score(i: int) -> float:
        near = [i, *nb[i]]
        herds = any("wild_herds" in feats[k] for k in near)
        arable = any(rules.TERRAIN[terrain[k]].arable >= 1.0 for k in near)
        return rules.TERRAIN[terrain[i]].game + 0.4 * herds + 0.3 * arable

    habitable = [
        i for i in range(n) if not rules.TERRAIN[terrain[i]].rough and rules.TERRAIN[terrain[i]].game >= 0.6
    ]
    habitable.sort(key=score, reverse=True)
    good = habitable[: max(cfg.nations * 3, len(habitable) // 2)] or list(range(n))
    starts = [good[0]]
    while len(starts) < cfg.nations:
        pool = [i for i in good if i not in starts] or [i for i in range(n) if i not in starts]
        starts.append(max(pool, key=lambda i: min(math.dist(points[i], points[s]) for s in starts)))

    # every people can find wild herds within two steps of home (§5.4)
    for s in starts:
        ring1 = set(nb[s])
        ring2 = {k for j in ring1 for k in nb[j]} - {s}
        if any("wild_herds" in feats[k] for k in {s} | ring1 | ring2):
            continue
        grazing = [
            k
            for k in sorted(ring1) + sorted(ring2 - ring1)
            if not rules.TERRAIN[terrain[k]].rough and rules.TERRAIN[terrain[k]].grazing >= 0.6
        ]
        pick = grazing[0] if grazing else sorted(ring1)[0]
        feats[pick].append("wild_herds")

    world = World(seed=cfg.seed, spec=spec_for(cfg), nodes=nodes, edges=edges, nations={})
    world.rng = random.Random(cfg.seed * 7919 + 1)
    for k, i in enumerate(starts):
        nid = f"p{k}"
        world.nations[nid] = Nation(
            id=nid, name=names.nations[k], colour=rules.NATION_COLOURS[k], player=(k == 0)
        )
        uid = world.new_id("u")
        world.units[uid] = Unit(uid, nid, "band", ids[i], rules.START_HANDS)
    _prime(world)
    return world


def _prime(world: World) -> None:
    """Turn-one figures, so the first screen reads true before anything has resolved."""

    from stock.game import economy, politics, research, trade

    for n in world.nations.values():
        labour = n.orders["labour"]
        labour.size, labour.share, labour.clout = rules.START_HANDS, 1.0, 1.0
        n.last["extent"] = economy.extent_of(world, n)
        n.last["dol"] = rules.division_of_labour(n.last["extent"], False)
        n.last["ingenuity"] = research.ingenuity(world, n)
        n.last["sway_parts"] = politics.sway_income(world, n)
        n.last["security"] = economy.security_of(world, n)
        trade.update_fog(world, n)


RANDOM_PREFIX = "random"


def spec_for(cfg: WorldGenConfig) -> str:
    return f"{RANDOM_PREFIX}:{cfg.seed}:{cfg.nodes}:{cfg.nations}"


def parse_spec(spec: str | None) -> WorldGenConfig:
    """`random[:seed[:nodes[:nations]]]`; a missing seed draws a fresh one."""

    parts = (spec or RANDOM_PREFIX).strip().split(":")
    if parts[0] != RANDOM_PREFIX:
        raise ValueError(f"unknown world spec {spec!r}")
    nums = [int(p) for p in parts[1:] if p != ""]
    seed = nums[0] if nums else random.SystemRandom().randrange(1, 1_000_000)
    kwargs: dict[str, int] = {"seed": seed}
    if len(nums) > 1:
        kwargs["nodes"] = nums[1]
    if len(nums) > 2:
        kwargs["nations"] = nums[2]
    return WorldGenConfig(**kwargs)
