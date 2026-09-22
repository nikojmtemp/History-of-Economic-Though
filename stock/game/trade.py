"""Contact, fog, routes, goods flows, trade policy, treaties and relations
(design doc §5.3, §11, §16).

A route joins two peoples' markets. Each turn goods move from the market where
they are cheaper to the one where they are dearer, up to the route's capacity,
while the price gap still covers carriage (and any tariff). The gap is the
merchants' profit: it goes to the people who opened the route. Flows are
worked out from last turn's prices and surpluses (the lag rule), before this
turn's production is consumed.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from stock.game import rules
from stock.game.state import Nation, Route, Unit, World

# --- presence, fog, contact ------------------------------------------------------------


def presence(world: World, n: Nation) -> set[str]:
    """Nodes where the nation has people: settled nodes and unit positions."""

    return {nd.id for nd in world.nodes_of(n.id)} | {u.node for u in world.units_of(n.id)}


def update_fog(world: World, n: Nation) -> None:
    seen = set(n.explored)
    seen |= visible(world, n)
    n.explored = sorted(seen)


def visible(world: World, n: Nation) -> set[str]:
    """What we see: around our people, and around our allies' (§16.1)."""

    eyes = presence(world, n)
    for t in world.treaties:
        if t["kind"] == "alliance" and n.id in (t["a"], t["b"]):
            ally = world.nations[t["b"] if t["a"] == n.id else t["a"]]
            eyes |= presence(world, ally)
    vis: set[str] = set()
    for node in eyes:
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


# --- routes ------------------------------------------------------------------------------


def route_between(world: World, a: str, b: str) -> Route | None:
    for r in world.routes.values():
        if {r.a, r.b} == {a, b}:
            return r
    return None


def routes_of(world: World, nation_id: str) -> list[Route]:
    return [r for r in world.routes.values() if nation_id in (r.a, r.b)]


def route_count(world: World, nation_id: str) -> int:
    """Routes this people opened: they take up its slots."""

    return sum(1 for r in world.routes.values() if r.a == nation_id)


def route_slots(world: World, n: Nation) -> int:
    works = [w for nd in world.nodes_of(n.id) for w in nd.works]
    return 1 + works.count("market") + 2 * works.count("port") + (1 if n.knows("barter") else 0)


def embargoed(world: World, a: str, b: str) -> bool:
    na, nb = world.nations[a], world.nations[b]
    return na.embargo.get(b, 0) >= world.turn or nb.embargo.get(a, 0) >= world.turn


def capacity_of(world: World, r: Route) -> float:
    cap = r.capacity
    if world.nations[r.a].knows("bills"):
        cap *= rules.BILLS_CAPACITY
    for x in (r.a, r.b):
        opt = world.nations[x].option("commerce")
        if opt == "tolls":
            cap *= rules.TOLLS_CAPACITY
        elif opt == "free_trade":
            cap *= rules.FREE_TRADE_CAPACITY
    if world.treaty("trade_pact", r.a, r.b):
        cap *= rules.PACT_CAPACITY
    return cap


def carriage_of(r: Route) -> float:
    if r.kind == "sea":
        return rules.CARRIAGE["sea"] * (1 + r.hops / 3.0)
    return rules.CARRIAGE[r.kind] * max(1, r.hops)


def blockaded(world: World, r: Route) -> bool:
    """An enemy of either party standing at either end stops the route (§11.3)."""

    for node in (r.a_node, r.b_node):
        if node is None:
            continue
        for u in world.units_at(node):
            if u.military and (world.hostile(u, r.a) or world.hostile(u, r.b)):
                return True
    return False


def _hops(world: World, a: str, b: str, sea: bool) -> int:
    seen = {a: 0}
    q = deque([a])
    while q:
        cur = q.popleft()
        if cur == b:
            return seen[cur]
        for nxt in world.neighbours(cur, sea=sea):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                q.append(nxt)
    return 6


def open_barter(world: World, a: Nation, b: Nation) -> Route:
    rid = world.new_id("r")
    route = Route(rid, "barter", a.id, b.id, rules.ROUTE_CAPACITY["barter"])
    world.routes[rid] = route
    world.emit(a.id, "route", f"Barter opened with {b.name}.")
    world.emit(b.id, "route", f"{a.name} barter with us.")
    return route


def trader_blocker(world: World, n: Nation, u: Unit) -> str | None:
    """Why this caravan or merchantman cannot open a route where it stands."""

    if u.kind not in ("caravan", "merchantman"):
        return "not a trader"
    nd = world.nodes[u.node]
    if nd.owner is None or nd.owner == n.id:
        return "walk it to a foreign town"
    other = world.nations[nd.owner]
    if other.id not in n.contacts:
        return "not in contact"
    if world.war_between(n.id, other.id):
        return "at war"
    if embargoed(world, n.id, other.id):
        return "under embargo"
    if u.kind == "merchantman":
        if "port" not in nd.works:
            return "a sea route needs a foreign port"
        if other.option("commerce") == "mercantile" and not world.treaty("trade_pact", n.id, other.id):
            return "their Navigation Act closes their ports to our ships"
    if any(r.a == n.id and r.b_node == nd.id for r in world.routes.values()):
        return "we already trade here"
    if route_count(world, n.id) >= route_slots(world, n):
        return "no free route slot: build a Market Town or Port"
    return None


def open_route(world: World, n: Nation, u: Unit) -> Route:
    nd = world.nodes[u.node]
    other = world.nations[nd.owner or ""]
    kind = "sea" if u.kind == "merchantman" else "caravan"
    home = u.home or u.node
    rid = world.new_id("r")
    r = Route(
        rid,
        kind,
        n.id,
        other.id,
        rules.ROUTE_CAPACITY[kind],
        a_node=home,
        b_node=nd.id,
        hops=_hops(world, home, nd.id, sea=kind == "sea"),
    )
    world.routes[rid] = r
    del world.units[u.id]
    what = "A sea route" if kind == "sea" else "A caravan route"
    world.emit(
        n.id, "route", f"{what} opens from {world.nodes[home].name} to {nd.name} in {other.name}.", nd.id
    )
    world.emit(other.id, "route", f"{n.name} open a {kind} route to {nd.name}.", nd.id)
    return r


def close_routes(world: World, a: str, b: str, why: str) -> None:
    for rid, r in list(world.routes.items()):
        if {r.a, r.b} == {a, b}:
            del world.routes[rid]
            world.emit(r.a, "route", f"Our route to {world.nations[r.b].name} is closed: {why}.")
            world.emit(r.b, "route", f"{world.nations[r.a].name}'s route to us is closed: {why}.")


def update_routes(world: World) -> None:
    """Routes lapse when their ends change hands or their peoples drift apart; trade warms relations."""

    for rid, r in list(world.routes.items()):
        a, b = world.nations[r.a], world.nations[r.b]
        why = None
        if not (a.alive and b.alive):
            why = "a people is gone"
        elif r.kind == "barter" and not in_reach(world, a, b, hops=2):
            why = "we drifted apart"
        elif r.a_node is not None and world.nodes[r.a_node].owner != r.a:
            why = f"{world.nodes[r.a_node].name} is no longer ours"
        elif r.b_node is not None and world.nodes[r.b_node].owner != r.b:
            why = f"{world.nodes[r.b_node].name} changed hands"
        elif world.war_between(r.a, r.b) or embargoed(world, r.a, r.b):
            why = "war or embargo"
        if why:
            del world.routes[rid]
            world.emit(a.id, "route", f"Our route with {b.name} is closed: {why}.")
            world.emit(b.id, "route", f"The route with {a.name} is closed: {why}.")
            continue
        warmth = 1.0 + (0.5 if world.treaty("trade_pact", r.a, r.b) else 0.0)
        for x, y in ((a, b), (b, a)):
            bonus = 0.5 if x.option("commerce") == "free_trade" else 0.0
            if x.relations.get(y.id, 0.0) < 50.0:  # trade makes friends, not brothers
                x.relations[y.id] = min(50.0, x.relations.get(y.id, 0.0) + warmth + bonus)
    for n in world.nations.values():
        for other in list(n.relations):
            if route_between(world, n.id, other) is None:
                v = n.relations[other]
                n.relations[other] = v - 0.5 if v > 0 else v + 0.5 if v < 0 else 0.0


# --- flows -------------------------------------------------------------------------------------

PROTECTED = ("wares", "luxuries")


def _blank() -> dict[str, Any]:
    return {
        "imports": {g: 0.0 for g in rules.GOODS},
        "exports": {g: 0.0 for g in rules.GOODS},
        "profit": 0.0,  # merchants' profit on routes we opened
        "barter": 0.0,  # the same on band-era barter: it goes to the people, not to merchants
        "tolls": 0.0,
        "tariff": 0.0,
        "bounty": 0.0,
        "by_partner": {},  # partner -> value of goods bought from them
        "food_from": {},  # partner -> food bought from them
        "from": {},  # partner -> good -> quantity bought from them (the trade lever)
        "value": 0.0,  # value of goods through our markets
    }


def resolve_flows(world: World) -> None:
    """This turn's trade on every route, from last turn's prices and surpluses."""

    living = [n for n in world.nations.values() if n.alive]
    for n in living:
        n.trade = _blank()
    avail: dict[str, dict[str, float]] = {}
    for n in living:
        made = n.last.get("made", {})
        eaten = n.last.get("consumed", {})
        avail[n.id] = {
            g: max(0.0, float(made.get(g, 0.0)) - float(eaten.get(g, 0.0))) + n.store[g] for g in rules.GOODS
        }
    # what each market will take from abroad this turn, shared across all its routes
    wanted = {
        n.id: {g: float(n.demand.get(g, 0.0)) * rules.IMPORT_SHARE for g in rules.GOODS} for n in living
    }
    for r in sorted(world.routes.values(), key=lambda x: x.id):
        r.flows, r.profit = {}, 0.0
        a, b = world.nations[r.a], world.nations[r.b]
        r.active = a.alive and b.alive and not blockaded(world, r)
        if not r.active:
            continue
        room = capacity_of(world, r) * rules.CAPACITY_VALUE
        carriage = carriage_of(r)
        pact = world.treaty("trade_pact", r.a, r.b) is not None
        gaps = sorted(
            rules.GOODS, key=lambda g: -abs(a.prices[g] - b.prices[g]) / min(a.prices[g], b.prices[g])
        )
        profit = 0.0
        for g in gaps:
            exp, imp = (a, b) if a.prices[g] < b.prices[g] else (b, a)
            lo, hi = exp.prices[g], imp.prices[g]
            tariff = (
                rules.MERCANTILE_TARIFF
                if (g in PROTECTED and imp.option("commerce") == "mercantile" and not pact)
                else 0.0
            )
            margin = hi - lo * (1.0 + carriage + tariff)
            if margin <= 0 or room <= 0:
                continue
            q = min(
                room / lo,
                avail[exp.id][g] * rules.EXPORT_SHARE,
                wanted[imp.id][g],
            )
            if q < 0.01:
                continue
            wanted[imp.id][g] -= q
            avail[exp.id][g] -= q
            room -= q * lo
            exp.trade["exports"][g] += q
            imp.trade["imports"][g] += q
            profit += q * margin
            imp.trade["tariff"] += q * lo * tariff
            if g in PROTECTED and exp.option("commerce") == "mercantile":
                exp.trade["bounty"] += q * lo * rules.MERCANTILE_BOUNTY
            imp.trade["by_partner"][exp.id] = imp.trade["by_partner"].get(exp.id, 0.0) + q * hi
            if g == "food":
                imp.trade["food_from"][exp.id] = imp.trade["food_from"].get(exp.id, 0.0) + q
            bought = imp.trade["from"].setdefault(exp.id, {})
            bought[g] = bought.get(g, 0.0) + q
            for x in (exp, imp):
                x.trade["value"] += q * hi
            r.flows[g] = round(q if exp is a else -q, 3)
        for x in (a, b):
            if x.option("commerce") == "tolls" and profit > 0:
                toll = rules.TOLLS_SHARE * profit
                x.trade["tolls"] += toll
                profit -= toll
        r.profit = round(profit, 3)
        a.trade["barter" if r.kind == "barter" else "profit"] += profit
    for n in living:
        if any(q > 0 for q in n.trade["imports"].values()):
            n.counters["importing"] = 1.0


# --- embargo, gifts, treaties ----------------------------------------------------------------


def embargo(world: World, n: Nation, other: Nation) -> None:
    n.embargo[other.id] = world.turn + rules.EMBARGO_TURNS
    close_routes(world, n.id, other.id, f"{n.name} embargo {other.name}")
    other.relations[n.id] = other.relations.get(n.id, 0.0) - 20.0
    other.casus_belli[n.id] = rules.CASUS_BELLI_TURNS


def gift(world: World, n: Nation, other: Nation) -> None:
    if n.stock >= rules.GIFT_COST:
        n.stock -= rules.GIFT_COST
        other.stock += rules.GIFT_COST
    else:
        n.store["food"] -= rules.GIFT_COST
        other.store["food"] += rules.GIFT_COST
    other.relations[n.id] = min(100.0, other.relations.get(n.id, 0.0) + rules.GIFT_RELATIONS)
    n.relations[other.id] = min(100.0, n.relations.get(other.id, 0.0) + rules.GIFT_RELATIONS / 3)
    world.emit(other.id, "gift", f"{n.name} send gifts.")


def treaty_blocker(world: World, n: Nation, other: Nation, kind: str) -> str | None:
    t = rules.TREATIES.get(kind)
    if t is None:
        return "no such treaty"
    if not n.knows(t.needs):
        return f"needs {rules.DISCOVERIES[t.needs].name}" if t.needs else "locked"
    if other.id not in n.contacts:
        return "not in contact"
    if world.war_between(n.id, other.id):
        return "at war: make peace first"
    if world.treaty(kind, n.id, other.id):
        return "already agreed"
    if kind == "protection":
        from stock.game.military import military_strength

        if military_strength(world, other.id) >= military_strength(world, n.id):
            return "they are as strong as we are: they need no protector"
        if any(t["kind"] == "protection" and t["b"] == other.id for t in world.treaties):
            return "they already have a protector"
    if n.sway < t.sway:
        return f"needs {t.sway:.0f} Sway"
    return None


def would_accept(world: World, n: Nation, other: Nation, kind: str) -> bool:
    """An AI people's answer to a proposal from `n` (§16.2)."""

    rel = other.relations.get(n.id, 0.0)
    if kind == "non_aggression":
        return rel >= -10
    if kind == "trade_pact":
        return rel >= 10 or route_between(world, n.id, other.id) is not None
    if kind == "alliance":
        shared = set(_enemies(world, n.id)) & set(_enemies(world, other.id))
        return rel >= 0 and bool(shared)  # an alliance needs a common enemy
    if kind == "protection":
        from stock.game.military import military_strength

        ours, theirs = military_strength(world, n.id), military_strength(world, other.id)
        threatened = bool(_enemies(world, other.id)) or any(
            other.relations.get(x, 0.0) < -20 and military_strength(world, x) > theirs for x in other.contacts
        )
        return ours >= 1.5 * theirs + 1.0 and rel >= -10 and (threatened or rel >= 30)
    return False


def _enemies(world: World, nation_id: str) -> list[str]:
    return [w["b"] if w["a"] == nation_id else w["a"] for w in world.wars if nation_id in (w["a"], w["b"])]


def sign(world: World, a: Nation, b: Nation, kind: str) -> None:
    world.treaties.append({"kind": kind, "a": a.id, "b": b.id, "since": world.turn})
    name = rules.TREATIES[kind].name
    for x, y in ((a, b), (b, a)):
        x.relations[y.id] = min(100.0, x.relations.get(y.id, 0.0) + 10.0)
        world.emit(x.id, "treaty", f"{name} signed with {y.name}.")


def break_treaties(world: World, breaker: Nation, victim: Nation) -> None:
    """Attacking a people we have a treaty with breaks it, and our word with everyone."""

    broken = [t for t in world.treaties if {t["a"], t["b"]} == {breaker.id, victim.id}]
    if not broken:
        return
    for t in broken:
        world.treaties.remove(t)
    for other in world.nations.values():
        if other.id != breaker.id:
            other.relations[breaker.id] = other.relations.get(breaker.id, 0.0) - rules.BREAK_FAITH_RELATIONS
    world.emit(None, "treaty", f"{breaker.name} break faith with {victim.name}.")


def allies_of(world: World, nation_id: str) -> list[str]:
    """Who comes to our aid: allies, and our protector (a protection treaty binds one way)."""

    out = [
        t["b"] if t["a"] == nation_id else t["a"]
        for t in world.treaties
        if t["kind"] == "alliance" and nation_id in (t["a"], t["b"])
    ]
    out += [t["a"] for t in world.treaties if t["kind"] == "protection" and t["b"] == nation_id]
    return out


def dependence(world: World, n: Nation) -> dict[str, float]:
    """Share of our consumption bought from each partner last turn (the trade lever, §17.2)."""

    eaten = n.last.get("consumed", {})
    total = sum(float(eaten.get(g, 0.0)) * n.prices[g] for g in rules.GOODS)
    if total <= 0:
        return {}
    return {p: round(v / total, 3) for p, v in n.trade.get("by_partner", {}).items()}


def food_dependence(world: World, n: Nation) -> dict[str, float]:
    eaten = float(n.last.get("consumed", {}).get("food", 0.0))
    if eaten <= 0:
        return {}
    return {p: round(q / eaten, 3) for p, q in n.trade.get("food_from", {}).items()}


# --- trader movement -----------------------------------------------------------------------------


def naval(u: Unit) -> bool:
    return u.kind in ("merchantman", "fleet")


def ship_edge_ok(world: World, a: str, b: str) -> bool:
    e = world.edge_between(a, b)
    if e is None:
        return False
    if e.kind == "sea":
        return True
    return world.nodes[a].coast and world.nodes[b].coast and e.kind != "rough"  # coasting
