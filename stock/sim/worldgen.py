"""Procedural world generation: a seed -> a scenario dict of the exact shape
`sim.scenario` loads (`locations`, `nations`, `seed`), so a generated world and an
authored one go through the same loader, the same validation and the same UI.

The recipe follows `scripts/gen_three_bands.py`'s hand-drawn map: one ocean side
with a coast, a river valley of arable plains running down from the high ground,
highlands with grazing and ore, forest with game and timber, open steppe, a rare
location, ore and coal somewhere reachable, and each band starting on game far
from the others. Everything is drawn from one `random.Random(seed)`, so a seed is a
world: the same seed always gives the same map.

Steps:
  1. Points — best-candidate ("Mitchell") sampling on a 5:3 canvas, so locations
     are evenly spread with no two on top of each other.
  2. Graph — the Gabriel graph of those points: an edge `ab` exists when no third
     point lies inside the circle with `ab` as diameter. It is planar and
     connected by construction (it contains the minimum spanning tree), which is
     what `api.layout` and `tests/test_layout.py` require of every map.
  3. Relief — the ocean lies along one side; elevation climbs away from it with
     a few random hills on top; moisture is its own noise plus the river.
  4. Rivers — from a high inland location, walk strictly downhill along edges
     towards the coast; the path is the river valley (arable plains).
  5. Terrain, then resources per terrain (yields in the same ranges the authored
     map uses), then the guarantees (a rare location; ore and coal somewhere).
  6. Nations — bands start on game locations chosen by farthest-point sampling;
     the first is the player's, the rest are scripted.

`python -m stock.sim gen --seed 7 --out my_world.yaml` writes one out;
`load_scenario("random:7")` builds one in memory (see `sim.scenario`).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: Canvas aspect (the map pane is 1000x600, `api.layout`).
CANVAS_W, CANVAS_H = 5.0, 3.0
#: Best-candidate sampling: candidates tried per placed point.
CANDIDATES_PER_POINT = 24
#: Yield scale factors carried over from the authored generator (Doc 02 tuning).
GAME_YIELD_FACTOR = 3.5
ARABLE_YIELD_FACTOR = 0.55

#: Location id prefixes by terrain (river plains read as a valley, like the
#: authored map's `valley_1..4`).
_PREFIX = {
    "PLAINS": "plains",
    "HILLS": "highland",
    "FOREST": "forest",
    "MOUNTAIN": "mountain",
    "STEPPE": "steppe",
    "WETLAND": "wetland",
    "COASTAL_PLAIN": "coast",
}


@dataclass(frozen=True)
class WorldGenConfig:
    seed: int = 0
    locations: int = 24
    nations: int = 3
    #: band size range at the start (the authored map uses 200-240)
    start_size_min: float = 200.0
    start_size_max: float = 240.0
    #: `ai` for every nation after the first (the first is the player's seat);
    #: None leaves every seat to the player/none, "scripted" seats Doc 06's AI.
    other_ai: str | None = "scripted"
    #: rivers to carve (each needs a distinct high source; fewer may fit)
    rivers: int = 1

    def __post_init__(self) -> None:
        if self.locations < 4:
            raise ValueError("a world needs at least 4 locations")
        if self.nations < 1:
            raise ValueError("a world needs at least one nation")
        if self.nations > self.locations // 2:
            raise ValueError("too many nations for that many locations (at most half)")


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


# --- terrain and resources -----------------------------------------------------------


def _classify(
    elevation: list[float],
    moisture: list[float],
    distance: list[float],
    on_river: list[bool],
) -> list[str]:
    n = len(elevation)
    order = sorted(range(n), key=lambda i: elevation[i], reverse=True)
    mountain = set(order[: max(1, n // 10)])
    hills = set(order[max(1, n // 10) : max(2, n // 10 + n // 5)])
    coast_band = 0.15
    terrain: list[str] = []
    for i in range(n):
        if distance[i] <= coast_band and i not in mountain:
            terrain.append("COASTAL_PLAIN")
        elif i in mountain:
            terrain.append("MOUNTAIN")
        elif i in hills and not on_river[i]:
            terrain.append("HILLS")
        elif on_river[i]:
            terrain.append("PLAINS")  # the valley
        elif moisture[i] > 0.75 and elevation[i] < 0.35:
            terrain.append("WETLAND")
        elif moisture[i] > 0.55:
            terrain.append("FOREST")
        elif moisture[i] < 0.3:
            terrain.append("STEPPE")
        else:
            terrain.append("PLAINS")
    return terrain


def _resources(
    rng: random.Random, terrain: str, on_river: bool, is_coast: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resource gates and yields for one location, in the authored map's ranges."""

    res: dict[str, Any] = {
        "game": False,
        "grazing": False,
        "arable": False,
        "timber": False,
        "ore": False,
        "coal": False,
        "fishing": False,
        "rare": False,
    }
    cap: dict[str, float] = {}

    def game(lo: float, hi: float, cap_size: float = 1200.0) -> None:
        res["game"] = True
        res["game_yield"] = round(rng.uniform(lo, hi) * GAME_YIELD_FACTOR, 3)
        cap["game_cap"] = cap_size
        cap["game_depletion"] = 0.0

    def grazing(lo: float, hi: float) -> None:
        res["grazing"] = True
        cap["graze_cap"] = float(round(rng.uniform(lo, hi), -2))
        cap["graze_depletion"] = 0.0

    def arable(lo: float, hi: float) -> None:
        res["arable"] = True
        res["arable_yield"] = round(rng.uniform(lo, hi) * ARABLE_YIELD_FACTOR, 3)

    def simple(key: str, lo: float, hi: float) -> None:
        res[key] = True
        res[f"{key}_yield"] = round(rng.uniform(lo, hi), 2)

    chance = rng.random
    if terrain == "PLAINS":
        arable(2.0, 2.4) if on_river else arable(1.6, 2.0)
        if chance() < 0.5:
            game(0.8, 1.2)
        if not on_river and chance() < 0.4:
            grazing(1000, 1500)
        if chance() < 0.25:
            simple("timber", 1.0, 1.2)
    elif terrain == "HILLS":
        grazing(1200, 1600)
        if chance() < 0.6:
            game(0.8, 1.2)
        if chance() < 0.45:
            simple("ore", 0.8, 1.3)
    elif terrain == "FOREST":
        game(1.1, 1.6)
        simple("timber", 1.2, 1.6)
        if chance() < 0.25:
            simple("coal", 0.9, 1.2)
        if chance() < 0.3:
            grazing(900, 1100)
    elif terrain == "MOUNTAIN":
        if chance() < 0.8:
            simple("ore", 1.1, 1.3)
        if chance() < 0.5:
            simple("coal", 1.0, 1.2)
        if chance() < 0.5:
            game(0.5, 0.7)
    elif terrain == "STEPPE":
        grazing(1500, 1800)
        if chance() < 0.8:
            game(1.0, 1.4)
        if chance() < 0.2:
            simple("coal", 0.9, 1.1)
    elif terrain == "WETLAND":
        simple("fishing", 0.9, 1.1)
        game(0.8, 1.0)
        if chance() < 0.7:
            grazing(900, 1100)
    elif terrain == "COASTAL_PLAIN":
        simple("fishing", 1.2, 1.5)
        if on_river or chance() < 0.4:
            arable(1.5, 1.8)
        if chance() < 0.3:
            grazing(800, 1000)
    if on_river and not res["arable"] and terrain != "MOUNTAIN":
        arable(1.8, 2.2)
    if is_coast and not res["fishing"]:
        simple("fishing", 1.0, 1.3)
    return res, cap


# --- the generator ---------------------------------------------------------------------


def generate_scenario(config: WorldGenConfig | None = None, **overrides: Any) -> dict[str, Any]:
    """Builds the scenario dict for `config` (or `WorldGenConfig(**overrides)`)."""

    cfg = config if config is not None else WorldGenConfig(**overrides)
    rng = random.Random(cfg.seed)
    n = cfg.locations

    points = _sample_points(rng, n)
    edges = _gabriel_edges(points)
    nb = _neighbours(n, edges)
    elevation, moisture, distance, side = _relief(rng, points)
    rivers = _carve_rivers(rng, elevation, distance, nb, cfg.rivers)
    on_river = [False] * n
    for path in rivers:
        for i in path[1:]:  # the source itself is high ground, not valley
            on_river[i] = True
    terrain = _classify(elevation, moisture, distance, on_river)
    is_coast = [terrain[i] == "COASTAL_PLAIN" for i in range(n)]
    for path in rivers:  # a river reaching the coast makes its mouth a haven
        if is_coast[path[-1]]:
            on_river[path[-1]] = True

    # ids: `valley_1`, `highland_2`... numbered per prefix in point order
    counters: dict[str, int] = {}
    ids: list[str] = []
    for i in range(n):
        prefix = "valley" if on_river[i] and terrain[i] == "PLAINS" else _PREFIX[terrain[i]]
        counters[prefix] = counters.get(prefix, 0) + 1
        ids.append(f"{prefix}_{counters[prefix]}")

    resources: list[dict[str, Any]] = []
    capacities: list[dict[str, float]] = []
    for i in range(n):
        res, cap = _resources(rng, terrain[i], on_river[i], is_coast[i])
        resources.append(res)
        capacities.append(cap)

    # Guarantees: one rare location (coast first, like the authored map); ore and
    # coal somewhere; at least one arable location; at least `nations` game
    # locations to start bands on.
    def ensure(key: str, lo: float, hi: float, prefer: list[int]) -> None:
        if any(r[key] for r in resources):
            return
        i = prefer[0] if prefer else rng.randrange(n)
        resources[i][key] = True
        resources[i][f"{key}_yield"] = round(rng.uniform(lo, hi), 2)

    rare_pool = [i for i in range(n) if is_coast[i]] or list(range(n))
    resources[rng.choice(rare_pool)]["rare"] = True
    ensure("ore", 0.9, 1.2, [i for i in range(n) if terrain[i] in ("MOUNTAIN", "HILLS")])
    ensure("coal", 0.9, 1.2, [i for i in range(n) if terrain[i] in ("MOUNTAIN", "FOREST", "STEPPE")])
    if not any(r["arable"] for r in resources):
        i = min(range(n), key=lambda k: elevation[k])
        resources[i]["arable"] = True
        resources[i]["arable_yield"] = round(rng.uniform(1.8, 2.2) * ARABLE_YIELD_FACTOR, 3)
    # A band can only start where the hunt feeds it: game at least the authored
    # map's poorest start (`valley_1`'s 1.0 x factor), and not on a mountain.
    start_yield = 1.0 * GAME_YIELD_FACTOR

    def can_start(i: int) -> bool:
        return (
            resources[i]["game"]
            and resources[i].get("game_yield", 0.0) >= start_yield
            and terrain[i] != "MOUNTAIN"
        )

    game_locs = [i for i in range(n) if can_start(i)]
    while len(game_locs) < cfg.nations:
        i = rng.choice([k for k in range(n) if k not in game_locs and terrain[k] != "MOUNTAIN"])
        resources[i]["game"] = True
        resources[i]["game_yield"] = round(rng.uniform(1.0, 1.3) * GAME_YIELD_FACTOR, 3)
        capacities[i]["game_cap"] = 1200.0
        capacities[i]["game_depletion"] = 0.0
        game_locs.append(i)

    # distances: scaled so the median edge is 1.0, like the authored grid
    lengths = [math.dist(points[i], points[j]) for i, j in edges]
    lengths.sort()
    median = lengths[len(lengths) // 2] if lengths else 1.0
    scale = 1.0 / median if median > 0 else 1.0
    neighbours: list[dict[str, float]] = [{} for _ in range(n)]
    for i, j in edges:
        d = round(math.dist(points[i], points[j]) * scale, 2)
        neighbours[i][ids[j]] = d
        neighbours[j][ids[i]] = d

    locations: list[dict[str, Any]] = []
    for i in range(n):
        locations.append(
            {
                "id": ids[i],
                "x": round(points[i][0] * scale, 2),
                "y": round(points[i][1] * scale, 2),
                "terrain": terrain[i],
                "river": on_river[i],
                "coast": is_coast[i],
                "resources": resources[i],
                "capacity": capacities[i],
                "neighbours": neighbours[i],
            }
        )

    # Nations: farthest-point sampling over game locations, the first at random.
    starts = [rng.choice(game_locs)]
    while len(starts) < cfg.nations:
        best = max(
            (i for i in game_locs if i not in starts),
            key=lambda i: min(math.dist(points[i], points[s]) for s in starts),
        )
        starts.append(best)
    nations: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for k, i in enumerate(starts):
        base = f"nation_{ids[i].rsplit('_', 1)[0]}"  # `nation_valley`, like the authored map
        nation_id, suffix = base, 1
        while nation_id in used_ids:
            suffix += 1
            nation_id = f"{base}_{suffix}"
        used_ids.add(nation_id)
        nation: dict[str, Any] = {
            "id": nation_id,
            "start_location": ids[i],
            "start_size": float(round(rng.uniform(cfg.start_size_min, cfg.start_size_max), -1)),
        }
        if k > 0 and cfg.other_ai is not None:
            nation["ai"] = cfg.other_ai
        nations.append(nation)

    return {"seed": cfg.seed, "locations": locations, "nations": nations}


def scenario_header(cfg: WorldGenConfig) -> str:
    return (
        f"# Procedurally generated world: seed {cfg.seed}, {cfg.locations} locations, "
        f"{cfg.nations} nations (stock.sim.worldgen; `python -m stock.sim gen --seed {cfg.seed}`).\n"
    )


def write_scenario(cfg: WorldGenConfig, path: str | Path) -> Path:
    out = Path(path)
    out.write_text(
        scenario_header(cfg) + yaml.safe_dump(generate_scenario(cfg), sort_keys=False, width=100),
        encoding="utf-8",
    )
    return out


#: `load_scenario` accepts `random`, `random:SEED`, `random:SEED:LOCATIONS` or
#: `random:SEED:LOCATIONS:NATIONS` in place of a file path.
RANDOM_PREFIX = "random"


def spec_for(cfg: WorldGenConfig) -> str:
    """The `random:SEED:LOCATIONS:NATIONS` spec that regenerates `cfg`'s world."""

    return f"{RANDOM_PREFIX}:{cfg.seed}:{cfg.locations}:{cfg.nations}"


def new_world_spec(seed: int | None = None, **overrides: Any) -> str:
    """A spec for a fresh world: a seed nobody chose (from the system's entropy) unless
    one is given. The game starts on one of these; the spec is shown so the same
    world can be played again."""

    if seed is None:
        seed = random.SystemRandom().randrange(1, 1_000_000)
    return spec_for(WorldGenConfig(seed=seed, **overrides))


def parse_random_spec(spec: str) -> WorldGenConfig | None:
    """`random[:seed[:locations[:nations]]]` -> config, or None if `spec` isn't one."""

    text = str(spec).strip()
    if text != RANDOM_PREFIX and not text.startswith(RANDOM_PREFIX + ":"):
        return None
    parts = text.split(":")[1:]
    kwargs: dict[str, Any] = {}
    names = ("seed", "locations", "nations")
    for name, value in zip(names, parts, strict=False):
        if value != "":
            kwargs[name] = int(value)
    return WorldGenConfig(**kwargs)
