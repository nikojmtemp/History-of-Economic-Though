"""Discoveries (design doc §12): Ingenuity, observations, diffusion, progress."""

from __future__ import annotations

from stock.game import rules
from stock.game.economy import has_stupefaction
from stock.game.state import Nation, World


def metrics(world: World, n: Nation) -> dict[str, float]:
    """Everything an observation can test, measured now."""

    nodes = world.nodes_of(n.id)
    units = world.units_of(n.id)
    works = [w for nd in nodes for w in nd.works]
    produce = float(n.last.get("produce", 0.0)) or 1.0
    split = n.last.get("split", {})
    hands = world.hands_of(n.id) or 1.0
    return {
        "followed_herds": n.counters.get("followed_herds", 0.0),
        "contacts": float(len(n.contacts)),
        "skirmishes_won": n.counters.get("skirmishes_won", 0.0),
        "on_coast": float(any(world.nodes[u.node].coast for u in units) or any(nd.coast for nd in nodes)),
        "bands": float(len(units)),
        "herds": world.herds_of(n.id),
        "pastures": float(works.count("pasture") + sum(1 for u in units if u.kind == "horde")),
        "camped_arable": float(
            any(world.nodes[u.node].t.arable >= 0.7 for u in units) or any(nd.t.arable >= 0.7 for nd in nodes)
        ),
        "proprietors": float(n.orders["proprietors"].size > 0),
        "raids_won": n.counters.get("raids_won", 0.0),
        "own_ore": float(any("ore" in nd.features for nd in nodes)),
        "best_relations": max(n.relations.values(), default=0.0),
        "fields": float(works.count("fields")),
        "field_nodes": float(sum(1 for nd in nodes if "fields" in nd.works)),
        "proprietor_clout": n.orders["proprietors"].clout,
        "besieged": n.counters.get("besieged", 0.0),
        "retainers": n.retainers,
        "routes": float(sum(1 for r in world.routes.values() if n.id in (r.a, r.b))),
        "extent": float(n.last.get("extent", 0.0)),
        "own_coast": float(any(nd.coast for nd in nodes)),
        "workshops": float(works.count("workshop")),
        "rent_share": float(split.get("rent", 0.0)) / produce,
        "stock_share": n.orders["stock"].size / hands,
        "importing": n.counters.get("importing", 0.0),
        "ports": float(works.count("port")),
        "treasury": n.treasury,
        "mines": float(works.count("mine")),
        "stock": n.stock,
        "deficit": n.counters.get("deficit", 0.0),
        "free_labour": float(n.option("labour") in rules.FREE_LABOUR),
        "manufactories": float(works.count("manufactory")),
        "stupefaction": float(has_stupefaction(world, n)),
    }


def available(n: Nation, key: str) -> bool:
    d = rules.DISCOVERIES[key]
    if key in n.known:
        return False
    return all(any(req in n.known for req in group) for group in d.requires)


def observation_met(n: Nation, key: str, m: dict[str, float]) -> bool:
    obs = rules.DISCOVERIES[key].observation
    return obs is not None and m.get(obs[0], 0.0) >= obs[1]


def diffusion(world: World, n: Nation, key: str) -> float:
    knowers = {o.id for o in world.nations.values() if o.alive and o.id != n.id and key in o.known}
    contacts = sum(1 for c in n.contacts if c in knowers)
    routes = sum(
        1
        for r in world.routes.values()
        if (r.a == n.id and r.b in knowers) or (r.b == n.id and r.a in knowers)
    )
    return min(
        rules.DIFFUSION_MAX, rules.DIFFUSION_PER_CONTACT * contacts + rules.DIFFUSION_PER_ROUTE * routes
    )


def cost(world: World, n: Nation, key: str, m: dict[str, float] | None = None) -> float:
    m = m if m is not None else metrics(world, n)
    base = rules.ERA_COST[rules.DISCOVERIES[key].era]
    if observation_met(n, key, m):
        base *= 0.5
    return round(base * (1.0 - diffusion(world, n, key)), 1)


def ingenuity(world: World, n: Nation) -> dict[str, float]:
    nodes = world.nodes_of(n.id)
    works = [w for nd in nodes for w in nd.works]
    dol = float(n.last.get("dol", 1.0))
    parts = {
        "base": 2.0,
        "people": 0.05 * world.hands_of(n.id),
        "workshops": 1.0 * works.count("workshop"),
        "towns": 2.0 * works.count("market"),
        "academies": 3.0 * works.count("academy"),
        "division": (dol - 1.0) * 2.0,
        "routes": float(sum(1 for r in world.routes.values() if n.id in (r.a, r.b))),
    }
    if n.seat == "civil":
        parts["instruction"] = 2.0 * n.budget.get("instruction", 0) / 3.0
    return {k: v for k, v in parts.items() if v}


def advance(world: World, n: Nation) -> None:
    n.research_progress += sum(ingenuity(world, n).values())
    m = metrics(world, n)
    for _ in range(3):  # at most a few discoveries a turn
        key = n.researching
        if key is None or not available(n, key):
            n.researching = None
            return
        c = cost(world, n, key, m)
        if n.research_progress < c:
            return
        n.research_progress -= c
        n.known.append(key)
        n.researching = None
        d = rules.DISCOVERIES[key]
        world.emit(n.id, "discovery", f"Discovered {d.name}: {d.unlocks}.", quote=d.quote)
