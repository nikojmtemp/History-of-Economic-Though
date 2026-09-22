"""Contact, fog, routes and relations (design doc §5.3, §11, §16.1).

Barter routes exist now; goods flows, caravans and sea routes arrive with M5.
"""

from __future__ import annotations

from stock.game.state import Nation, Route, World


def presence(world: World, n: Nation) -> set[str]:
    """Nodes where the nation has people: settled nodes and unit positions."""

    return {nd.id for nd in world.nodes_of(n.id)} | {u.node for u in world.units_of(n.id)}


def update_fog(world: World, n: Nation) -> None:
    seen = set(n.explored)
    for node in presence(world, n):
        seen.add(node)
        seen.update(world.neighbours(node))
    n.explored = sorted(seen)


def visible(world: World, n: Nation) -> set[str]:
    vis: set[str] = set()
    for node in presence(world, n):
        vis.add(node)
        vis.update(world.neighbours(node))
    return vis


def in_reach(world: World, a: Nation, b: Nation, hops: int = 1) -> bool:
    pa, pb = presence(world, a), presence(world, b)
    if pa & pb:
        return True
    frontier = set(pa)
    for _ in range(hops):
        frontier = frontier | {x for node in frontier for x in world.neighbours(node)}
        if frontier & pb:
            return True
    return False


def update_contacts(world: World) -> None:
    living = [n for n in world.nations.values() if n.alive]
    for a in living:
        for b in living:
            if a.id >= b.id or b.id in a.contacts:
                continue
            if in_reach(world, a, b):
                a.contacts.append(b.id)
                b.contacts.append(a.id)
                a.relations.setdefault(b.id, 0.0)
                b.relations.setdefault(a.id, 0.0)
                for x, y in ((a, b), (b, a)):
                    world.emit(x.id, "contact", f"First contact with {y.name}.")


def route_between(world: World, a: str, b: str) -> Route | None:
    for r in world.routes.values():
        if {r.a, r.b} == {a, b}:
            return r
    return None


def open_barter(world: World, a: Nation, b: Nation) -> Route:
    rid = world.new_id("r")
    route = Route(rid, "barter", a.id, b.id, 1.0)
    world.routes[rid] = route
    world.emit(a.id, "route", f"Barter opened with {b.name}.")
    world.emit(b.id, "route", f"{a.name} barter with us.")
    return route


def update_routes(world: World) -> None:
    for rid, r in list(world.routes.items()):
        a, b = world.nations[r.a], world.nations[r.b]
        if not (a.alive and b.alive) or (r.kind == "barter" and not in_reach(world, a, b, hops=2)):
            del world.routes[rid]
            world.emit(a.id, "route", f"Barter with {b.name} lapsed: we drifted apart.")
            world.emit(b.id, "route", f"Barter with {a.name} lapsed: we drifted apart.")
            continue
        for x, y in ((a, b), (b, a)):
            x.relations[y.id] = min(100.0, x.relations.get(y.id, 0.0) + 1.0)
    # relations drift toward zero without trade
    for n in world.nations.values():
        for other in list(n.relations):
            if route_between(world, n.id, other) is None:
                v = n.relations[other]
                n.relations[other] = v - 0.5 if v > 0 else v + 0.5 if v < 0 else 0.0


def route_count(world: World, nation_id: str) -> int:
    return sum(1 for r in world.routes.values() if nation_id in (r.a, r.b))


def route_slots(world: World, n: Nation) -> int:
    works = [w for nd in world.nodes_of(n.id) for w in nd.works]
    return 1 + works.count("market") + 2 * works.count("port") + (1 if n.knows("barter") else 0)
