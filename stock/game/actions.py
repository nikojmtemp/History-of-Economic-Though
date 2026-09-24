"""Every verb the player and the AI can use (design doc §7.2, §9.6, §12, §13, §14).

`check` says why an action is not allowed (or None); `act` applies it. The player and
the AI go through the same two functions: no rival has a verb the player lacks.
"""

from __future__ import annotations

from typing import Any

from stock.game import economy, events, finance, military, politics, research, rules, trade
from stock.game.state import Decision, Nation, Node, Unit, World

Action = dict[str, Any]

# --- small helpers ----------------------------------------------------------------------


def split_cost(n: Nation) -> float:
    return rules.SPLIT_COST_ELDERS if n.knows("elders") else rules.SPLIT_COST


def feast_cost(world: World, n: Nation) -> float:
    """Food for everyone: the more people, the dearer the feast."""

    return rules.FEAST_FOOD_PER_HAND * world.hands_of(n.id)


def _unit(world: World, n: Nation, a: Action) -> Unit | None:
    u = world.units.get(str(a.get("unit", "")))
    return u if u is not None and u.nation == n.id else None


def _own_node(world: World, n: Nation, node_id: Any) -> Node | None:
    nd = world.nodes.get(str(node_id))
    return nd if nd is not None and nd.owner == n.id else None


def work_cost(n: Nation, work: str) -> float:
    cost = rules.WORKS[work].cost
    if work == "manufactory" and n.option("labour") == "guilds":
        cost *= 2
    return cost


def queued_on(n: Nation, node_id: str) -> int:
    """Queued works that will take a slot here (improvements take none)."""

    return sum(1 for q in n.build_queue if q["node"] == node_id and not q.get("improve"))


def grow_blocker(world: World, n: Nation, node_id: Any) -> str | None:
    """Why this settlement cannot grow to the next tier now (§9.2a), or None."""

    nd = _own_node(world, n, node_id)
    if nd is None:
        return "not your settled node"
    if nd.tier >= len(rules.TIERS) - 1:
        return "already a city"
    nxt = rules.TIERS[nd.tier + 1]
    if nd.hands < nxt.hands:
        return f"needs {nxt.hands:.0f} hands (has {nd.hands:.0f})"
    if nd.tier + 1 == 2:
        if economy.security_of(world, n) < rules.TOWN_SECURITY:
            return f"needs Security of {rules.TOWN_SECURITY:.0%}"
        if "market" not in nd.works and not nd.river:
            return "needs a Market Town or a river"
    if nd.tier + 1 == 3:
        if n.seat != "civil":
            return "needs a civil government"
        if "market" not in nd.works:
            return "needs a Market Town"
    if n.stock < nxt.cost:
        return f"needs {nxt.cost:.0f} Stock"
    return None


def improve_blocker(world: World, n: Nation, node_id: Any, work: str) -> str | None:
    """Why this work cannot be improved here now (§9.2b), or None."""

    nd = _own_node(world, n, node_id)
    if nd is None:
        return "not your settled node"
    imp = rules.IMPROVEMENTS.get(work)
    if imp is None:
        return "no improvement for that work"
    if not n.knows(imp.needs):
        return f"needs {rules.DISCOVERIES[imp.needs].name}"
    queued = sum(1 for q in n.build_queue if q["node"] == nd.id and q["work"] == work and q.get("improve"))
    if nd.works.count(work) == 0:
        return f"no {rules.WORKS[work].name} here"
    if nd.works.count(work) - nd.improved_count(work) - queued <= 0:
        return f"every {rules.WORKS[work].name} here is improved"
    return None


def improvement_return(world: World, n: Nation, nd: Node, work: str) -> float:
    """What improving one more of `work` here would add to the town's surplus, per Stock."""

    before = _surplus(world, n, nd)
    had = nd.improved.get(work, 0)
    nd.improved[work] = nd.improved_count(work) + 1
    try:
        after = _surplus(world, n, nd)
    finally:
        nd.improved[work] = had
    return (after - before) / max(rules.IMPROVEMENTS[work].cost, 1.0)


def _improve(world: World, n: Nation, nd: Node, work: str, note: str = "") -> None:
    nd.improved[work] = nd.improved_count(work) + 1
    imp = rules.IMPROVEMENTS[work]
    world.emit(
        n.id, "built", f"{rules.WORKS[work].name} at {nd.name} becomes {imp.name.lower()}{note}.", nd.id
    )


def move_cost(world: World, u: Unit, to: str) -> int | None:
    """Ships keep to sea lanes and the coast; everyone else keeps to land."""

    e = world.edge_between(u.node, to)
    if e is None:
        return None
    if trade.naval(u):
        return 1 if trade.ship_edge_ok(world, u.node, to) else None
    if e.kind == "sea":
        # settlers: a band at its own port may take ship, once the people knows Sail
        here = world.nodes[u.node]
        n = world.nations[u.nation]
        if u.kind == "band" and here.owner == u.nation and "port" in here.works and n.knows("sail"):
            return 1
        return None
    return 1 if u.kind == "scouts" else e.cost()  # scouts climb as easily as they walk


def can_enter(world: World, n: Nation, node_id: str) -> bool:
    """Peaceful passage: open ground or our own. War opens the enemy's ground to soldiers."""

    owner = world.nodes[node_id].owner
    return owner is None or owner == n.id


def hostile_at(world: World, n: Nation, node_id: str) -> bool:
    nd = world.nodes[node_id]
    return world.hostile_owner(n.id, nd) or any(world.hostile(u, n.id) for u in world.units_at(node_id))


def _surplus(world: World, n: Nation, nd: Node) -> float:
    """What the town's works earn above wages, at today's prices."""

    wage = float(n.last.get("wage", n.prices["food"]))
    rows = economy._work_jobs(world, n, nd, float(n.last.get("dol", 1.0)))
    return sum(jobs * (value - wage) for _w, jobs, _per, value in rows)


def expected_return(world: World, n: Nation, nd: Node, work: str) -> float:
    """Profit per unit of stock a new work would earn at today's prices (§9.6): what it adds
    to the town's surplus, so a pasture with no herds left to tend adds nothing."""

    if rules.WORKS[work].jobs == 0:
        return 0.0
    before = _surplus(world, n, nd)
    nd.works.append(work)
    try:
        after = _surplus(world, n, nd)
    finally:
        nd.works.pop()
    ret = (after - before) / max(work_cost(n, work), 1.0)
    if work in ("market", "port"):
        ret += rules.TRADE_TOWN_PREMIUM  # the trade a town draws: routes, a wider market
    return ret


def build_blocker(world: World, n: Nation, node_id: Any, work: str) -> str | None:
    nd = _own_node(world, n, node_id)
    if nd is None:
        return "not your settled node"
    if work not in rules.WORKS:
        return "no such work"
    w = rules.WORKS[work]
    if not n.knows(w.needs):
        return f"needs {rules.DISCOVERIES[w.needs].name}" if w.needs else "locked"
    if not nd.site_ok(w.site):
        return {
            "arable": "needs arable ground",
            "grazing": "needs grazing",
            "coast": "needs a coast",
            "mine": "needs ore or coal",
            "rare": "needs a rare resource",
        }.get(w.site or "", "wrong ground")
    if len(nd.works) + queued_on(n, nd.id) >= nd.slots():
        return f"no free slot ({nd.slots()} for {nd.hands:.0f} hands)"
    if work == "manufactory" and n.option("labour") not in rules.FREE_LABOUR:
        return "needs Free Labour"
    if work == "fort" and nd.works.count("fort") >= 2:
        return "already at the highest fort level"
    if w.public and n.seat != "civil":
        return "a public work: needs Civil Government"
    if w.public and n.treasury < w.cost:
        return f"needs {w.cost:.0f} Treasury"
    if work == "pasture" and nd.herds <= 0 and "wild_herds" not in nd.features:
        return "no herds here: settle a horde or use a node with wild herds"
    return None


# --- validation ------------------------------------------------------------------------------


def check(world: World, n: Nation, a: Action) -> str | None:  # noqa: C901 - one table of rules
    kind = a.get("kind")
    if not n.alive:
        return "this nation is gone"
    if kind in ("raise_unit", "declare_war", "offer_peace", "raid", "disband", "upgrade"):
        return _check_war(world, n, a)
    if kind in ("borrow", "repay", "default"):
        return _check_credit(world, n, a)
    if kind in ("send_trader", "open_route", "embargo", "gift", "propose_treaty", "cancel_treaty"):
        return _check_trade(world, n, a)
    if kind in ("move", "split", "merge", "follow", "tame", "settle"):
        u = _unit(world, n, a)
        if u is None:
            return "no such unit"
        if u.kind == "scouts" and kind != "move":
            return "scouts only look: disband them to bring the hands home"
        nd = world.nodes[u.node]
        if kind == "move":
            to = str(a.get("to", ""))
            if to not in world.nodes:
                return "no such node"
            c = move_cost(world, u, to)
            if c is None:
                return "not adjacent by land"
            if u.moves_left <= 0 or (c > u.moves_left and u.moves_left < u.max_moves(set(n.known))):
                return "no moves left this turn"
            if hostile_at(world, n, to):
                return None if u.military else "enemies there: only soldiers can go"
            if u.kind in ("caravan", "merchantman"):
                owner = world.nodes[to].owner
                if owner not in (None, n.id) and trade.embargoed(world, n.id, owner):
                    return "under embargo"
                return None  # merchants are welcome in peacetime
            if u.kind == "scouts":
                return None  # travellers pass through in peacetime
            if not can_enter(world, n, to):
                return "settled by another people: at peace, you may not enter"
            return None
        if kind == "split":
            if u.military:
                return "armies do not split"
            if u.hands < 2 * rules.MIN_UNIT_HANDS:
                return f"needs at least {2 * rules.MIN_UNIT_HANDS:.0f} hands"
            if n.sway < split_cost(n):
                return f"needs {split_cost(n):.0f} Sway"
            return None
        if kind == "merge":
            o = world.units.get(str(a.get("other", "")))
            if o is None or o.nation != n.id or o.id == u.id or o.node != u.node:
                return "needs another of your units on the same node"
            if o.kind != u.kind and (u.military or o.military):
                return "only units of one kind merge"
            return None
        if kind == "follow":
            if "wild_herds" not in nd.features:
                return "no wild herds here"
            if u.kind != "band":
                return "only a band follows wild herds"
            if u.followed:
                return "already following"
            return None
        if kind == "tame":
            if u.military:
                return "soldiers do not tame herds"
            if not n.knows("taming"):
                return "needs Taming"
            if u.kind != "band":
                return "already a horde"
            if "wild_herds" not in nd.features:
                return "no wild herds here"
            return None
        if kind == "settle":
            if u.military:
                return "soldiers do not settle: disband them"
            if nd.owner not in (None, n.id):
                return "settled by another people"
            if nd.owner is None:
                if not n.knows("tillage"):
                    return "needs Tillage"
                if nd.t.arable <= 0:
                    return "nothing grows here"
                if any(x.nation != n.id for x in world.units_at(nd.id)):
                    return "another people camps here"
            return None
    if kind == "found_band":
        home = _own_node(world, n, a.get("node"))
        if home is None:
            return "not your settled node"
        if home.hands < 2 * rules.MIN_UNIT_HANDS:
            return f"needs at least {2 * rules.MIN_UNIT_HANDS:.0f} hands"
        if n.sway < split_cost(n):
            return f"needs {split_cost(n):.0f} Sway"
        return None
    if kind == "barter":
        other = world.nations.get(str(a.get("nation", "")))
        if other is None or other.id == n.id or not other.alive:
            return "no such people"
        if not n.knows("barter"):
            return "needs Barter"
        if other.id not in n.contacts:
            return "not in contact"
        if trade.route_between(world, n.id, other.id):
            return "already trading"
        if military.at_war(world, n.id, other.id):
            return "at war"
        if trade.embargoed(world, n.id, other.id):
            return "under embargo"
        if not trade.in_reach(world, n, other):
            return "too far: bring a band next to them"
        if trade.route_count(world, n.id) >= trade.route_slots(world, n):
            return "no free route slot"
        return None
    if kind == "feast":
        if n.feast_ready > 0:
            return f"feasted recently ({n.feast_ready} turns)"
        need = feast_cost(world, n)
        if n.store["food"] < need:
            return f"needs {need:.0f} stored food"
        return None
    if kind == "research":
        key = str(a.get("key", ""))
        if key not in rules.DISCOVERIES:
            return "no such discovery"
        if key in n.known:
            return "already known"
        if not research.available(n, key):
            return "prerequisites not met"
        return None
    if kind == "queue_research":
        key = str(a.get("key", ""))
        if key not in rules.DISCOVERIES:
            return "no such discovery"
        if key in n.known:
            return "already known"
        if key == n.researching or key in n.research_queue:
            return "already planned"
        return None
    if kind == "unqueue_research":
        if str(a.get("key", "")) not in n.research_queue:
            return "not in the queue"
        return None
    if kind == "auto_invest":
        if not n.knows(rules.AUTO_INVEST_TECH):
            return f"needs {rules.DISCOVERIES[rules.AUTO_INVEST_TECH].name}"
        return None
    if kind == "reorder_queue":
        at, dest = a.get("index"), a.get("to")
        if not all(isinstance(x, int) and 0 <= x < len(n.build_queue) for x in (at, dest)):
            return "no such queue item"
        return None
    if kind == "build":
        return build_blocker(world, n, a.get("node"), str(a.get("work", "")))
    if kind == "improve":
        return improve_blocker(world, n, a.get("node"), str(a.get("work", "")))
    if kind == "grow":
        return grow_blocker(world, n, a.get("node"))
    if kind == "demolish":
        site = _own_node(world, n, a.get("node"))
        if site is None:
            return "not your settled node"
        if str(a.get("work", "")) not in site.works:
            return "no such work there"
        return None
    if kind == "unqueue":
        i = a.get("index")
        if not isinstance(i, int) or not 0 <= i < len(n.build_queue):
            return "no such queue item"
        return None
    if kind == "road":
        x, y = str(a.get("a", "")), str(a.get("b", ""))
        e = world.edge_between(x, y) if x in world.nodes else None
        if e is None or e.kind not in ("path",):
            return "roads go on plain paths"
        if world.nodes[x].owner != n.id or world.nodes[y].owner != n.id:
            return "both ends must be your settled nodes"
        if n.seat in ("council", "interregnum"):
            return "needs a chiefdom or state"
        pay = n.treasury if n.seat == "civil" else n.stock
        return None if pay >= 10.0 else "needs 10 " + ("Treasury" if n.seat == "civil" else "Stock")
    if kind == "institution":
        pillar, option = str(a.get("pillar", "")), str(a.get("option", ""))
        why = politics.institution_blocker(n, pillar, option)
        if why:
            return why
        price = politics.institution_cost(n, pillar, option)
        return None if n.sway >= price else f"needs {price:.0f} Sway"
    if kind == "found_government":
        if n.seat != "chiefdom":
            return "needs a chiefdom" if n.seat == "council" else "already governed"
        if not n.knows("magistracy"):
            return "needs Magistracy"
        return (
            None if n.sway >= rules.FOUND_GOVERNMENT_COST else f"needs {rules.FOUND_GOVERNMENT_COST:.0f} Sway"
        )
    if kind == "restore":
        if n.seat != "interregnum":
            return "the government stands"
        if max(n.orders[o].contentment for o in rules.ORDERS) < 50:
            return "no order is content enough to back you"
        return None if n.sway >= rules.RESTORE_COST else f"needs {rules.RESTORE_COST:.0f} Sway"
    if kind == "tax":
        if n.seat != "civil":
            return "needs Civil Government"
        return None if a.get("rate") in rules.TAX_RATES else "no such rate"
    if kind == "budget":
        if n.seat != "civil":
            return "needs Civil Government"
        if a.get("line") not in rules.BUDGET_LINES or a.get("level") not in (0, 1, 2, 3):
            return "no such budget line or level"
        if a.get("line") == "instruction" and not n.knows("instruction") and a.get("level"):
            return "needs Public Instruction"
        return None
    if kind == "decide":
        if not any(d.id == a.get("id") for d in n.decisions):
            return "no such decision"
        return None
    return f"unknown action {kind!r}"


def _check_war(world: World, n: Nation, a: Action) -> str | None:
    kind = a["kind"]
    if kind == "raise_unit":
        src: Node | Unit | None = _own_node(world, n, a.get("node")) if a.get("node") else _unit(world, n, a)
        if src is None:
            return "raise at your settlement, or from your band or horde"
        if isinstance(src, Unit) and src.military:
            return "raise from a people, not an army"
        return military.raise_blocker(world, n, src, str(a.get("unit_kind", "")))
    if kind in ("disband", "upgrade", "raid"):
        u = _unit(world, n, a)
        if u is None or not (u.military or kind == "raid" or (kind == "disband" and u.kind == "scouts")):
            return "no such army"
        if kind == "upgrade":
            return military.upgrade_blocker(world, n, u)
        if kind == "raid":
            return military.raid_blocker(world, n, u, str(a.get("to", "")))
        return None
    other = world.nations.get(str(a.get("nation", "")))
    if other is None or other.id == n.id or not other.alive:
        return "no such people"
    if other.id not in n.contacts:
        return "not in contact"
    if kind == "declare_war":
        if military.at_war(world, n.id, other.id):
            return "already at war"
        if n.truce.get(other.id, 0) >= world.turn:
            return f"a truce holds until turn {n.truce[other.id]}"
        cost = 0.0 if other.id in n.casus_belli else rules.WAR_COST
        return None if n.sway >= cost else f"needs {cost:.0f} Sway (no just cause)"
    w = world.war_between(n.id, other.id)
    if w is None:
        return "not at war"
    if world.turn - int(w["since"]) < rules.PEACE_MIN_TURNS:
        return f"the war is barely begun ({rules.PEACE_MIN_TURNS} turns)"
    if a.get("terms") not in ("white", "tribute", "submit"):
        return "terms: white, tribute or submit"
    if any(d.kind == "peace" and d.data.get("from") == n.id for d in other.decisions):
        return "an offer is already waiting"
    return None


# --- application ---------------------------------------------------------------------------------


def act(world: World, nation_id: str, a: Action) -> str | None:
    """Apply `a` for `nation_id`; returns the reason it was refused, or None."""

    n = world.nations[nation_id]
    why = check(world, n, a)
    if why:
        return why
    kind = a["kind"]
    if kind in ("raise_unit", "declare_war", "offer_peace", "raid", "disband", "upgrade"):
        return _act_war(world, n, a)
    if kind in ("borrow", "repay", "default"):
        return _act_credit(world, n, a)
    if kind in ("send_trader", "open_route", "embargo", "gift", "propose_treaty", "cancel_treaty"):
        return _act_trade(world, n, a)
    if kind == "move":
        u = _unit(world, n, a)
        assert u is not None
        to = str(a["to"])
        c = move_cost(world, u, to) or 1
        e = world.edge_between(u.node, to)
        if e is not None and e.kind == "road" and u.kind in ("regiment", "musketeers") and not u.road_used:
            u.road_used = True  # one free step on a road each turn: +1 move
        else:
            u.moves_left = max(0, u.moves_left - c)
        if hostile_at(world, n, to):
            military.advance(world, u, to)
        else:
            u.node = to
        trade.update_fog(world, n)
        trade.update_contacts(world)
    elif kind == "split":
        u = _unit(world, n, a)
        assert u is not None
        half = u.hands / 2.0
        uid = world.new_id("u")
        herds = u.herds / 2.0
        world.units[uid] = Unit(uid, n.id, u.kind, u.node, half, herds, moves_left=u.moves_left)
        u.hands -= half
        u.herds -= herds
        n.sway -= split_cost(n)
    elif kind == "merge":
        u, o = _unit(world, n, a), world.units[str(a["other"])]
        assert u is not None
        u.hands += o.hands
        u.herds += o.herds
        if o.kind == "horde":
            u.kind = "horde"
        u.moves_left = min(u.moves_left, o.moves_left)
        del world.units[o.id]
    elif kind == "follow":
        u = _unit(world, n, a)
        assert u is not None
        u.followed = True
    elif kind == "tame":
        u = _unit(world, n, a)
        assert u is not None
        u.kind, u.herds = "horde", u.herds + rules.TAME_HERDS
        u.moves_left = min(u.moves_left, 0)
        if "first_herd" not in n.moments:
            n.moments.append("first_herd")
            world.emit(
                n.id,
                "moment",
                f"{n.name} tames its first herd. Herds grow by themselves: the first "
                "stock that can be accumulated, and so the first that can be owned.",
                u.node,
                quote=rules.MOMENT_QUOTES["first_herd"],
            )
    elif kind == "settle":
        u = _unit(world, n, a)
        assert u is not None
        nd = world.nodes[u.node]
        first = nd.owner is None
        nd.owner = n.id
        nd.hands += u.hands
        nd.herds += u.herds
        del world.units[u.id]
        if first:
            if nd.t.arable > 0 and n.knows("tillage"):
                for _ in range(max(1, min(nd.slots() - len(nd.works), round(nd.hands / 4)))):
                    nd.works.append("fields")
            if nd.herds > 0 and nd.t.grazing > 0 and len(nd.works) < nd.slots():
                nd.works.append("pasture")
        if first and "first_field" not in n.moments and "fields" in nd.works:
            n.moments.append("first_field")
            world.emit(
                n.id,
                "moment",
                f"{n.name} settles {nd.name} and plants its first fields: ground that "
                "cannot be carried away, and so is worth defending, and worth taking.",
                nd.id,
                quote=rules.MOMENT_QUOTES["first_field"],
            )
        trade.update_fog(world, n)
    elif kind == "found_band":
        nd = world.nodes[str(a["node"])]
        take = max(rules.MIN_UNIT_HANDS, min(4.0, nd.hands / 3.0))
        nd.hands -= take
        uid = world.new_id("u")
        world.units[uid] = Unit(uid, n.id, "band", nd.id, take, moves_left=1)
        n.sway -= split_cost(n)
    elif kind == "barter":
        trade.open_barter(world, n, world.nations[str(a["nation"])])
    elif kind == "feast":
        n.store["food"] -= feast_cost(world, n)
        n.counters["feast_growth"] = rules.FEAST_GROWTH
        n.sway = min(rules.SWAY_CAP, n.sway + rules.FEAST_SWAY + (1.0 if n.knows("elders") else 0.0))
        for order in rules.ORDERS:
            n.orders[order].contentment = economy.clamp(n.orders[order].contentment + 5.0, 0.0, 100.0)
        n.feast_ready = rules.FEAST_COOLDOWN
    elif kind == "research":
        key = str(a["key"])
        if n.researching is not None and n.researching != key:
            n.research_queue.insert(0, n.researching)  # set aside, not forgotten
        n.researching = key
        research.next_from_queue(n)
    elif kind == "queue_research":
        n.research_queue.extend(research.path_to(n, str(a["key"])))
        research.next_from_queue(n)
    elif kind == "unqueue_research":
        n.research_queue.remove(str(a["key"]))
    elif kind == "auto_invest":
        n.auto_invest = bool(a.get("on", not n.auto_invest))
    elif kind == "reorder_queue":
        item = n.build_queue.pop(int(a["index"]))
        n.build_queue.insert(int(a["to"]), item)
    elif kind == "build":
        work = str(a["work"])
        if rules.WORKS[work].public:
            n.treasury -= rules.WORKS[work].cost
            world.nodes[str(a["node"])].works.append(work)
            world.emit(
                n.id,
                "built",
                f"{rules.WORKS[work].name} built at {world.nodes[str(a['node'])].name}.",
                str(a["node"]),
            )
        else:
            n.build_queue.append({"node": str(a["node"]), "work": work, "status": "waiting"})
    elif kind == "improve":
        n.build_queue.append(
            {"node": str(a["node"]), "work": str(a["work"]), "improve": True, "status": "waiting"}
        )
    elif kind == "grow":
        nd = world.nodes[str(a["node"])]
        nd.tier += 1
        tier = rules.TIERS[nd.tier]
        n.stock -= tier.cost
        world.emit(
            n.id,
            "grew",
            f"{nd.name} grows into a {tier.name.lower()}: room for {tier.slots} works"
            + (f", and Ingenuity +{tier.ingenuity:.0f}" if tier.ingenuity else "")
            + ".",
            nd.id,
        )
    elif kind == "demolish":
        _pull_down(world, n, world.nodes[str(a["node"])], str(a["work"]))
    elif kind == "unqueue":
        n.build_queue.pop(int(a["index"]))
    elif kind == "road":
        e = world.edge_between(str(a["a"]), str(a["b"]))
        assert e is not None
        e.kind = "road"
        if n.seat == "civil":
            n.treasury -= 10.0
        else:
            n.stock -= 10.0
    elif kind == "institution":
        pillar, option = str(a["pillar"]), str(a["option"])
        n.sway -= politics.institution_cost(n, pillar, option)
        n.pending_institutions[pillar] = option
    elif kind == "found_government":
        n.sway -= rules.FOUND_GOVERNMENT_COST
        n.seat = "civil"
        n.budget["justice"] = max(n.budget.get("justice", 0), 1)
        if "civil_government" not in n.moments:
            n.moments.append("civil_government")
            world.emit(
                n.id,
                "moment",
                f"{n.name} founds a civil government: a treasury, taxes and courts. "
                "Choose a Revenue institution to fill the treasury.",
                quote=rules.MOMENT_QUOTES["civil_government"],
            )
    elif kind == "restore":
        n.sway -= rules.RESTORE_COST
        n.seat = "civil"
        world.emit(n.id, "seat", "The government is restored.")
    elif kind == "tax":
        n.tax_rate = str(a["rate"])
    elif kind == "budget":
        n.budget[str(a["line"])] = int(a["level"])
    elif kind == "decide":
        d = next(x for x in n.decisions if x.id == a["id"])
        if d.kind == "event":
            if a.get("choice") not in {c["key"] for c in d.choices}:
                return "no such choice"
            n.decisions.remove(d)
            events.resolve(world, n, d, str(a["choice"]))
            return None
        if d.kind == "capture":
            if a.get("choice") not in {c["key"] for c in d.choices}:
                return "no such choice"
            n.decisions.remove(d)
            military.resolve_capture(world, n, d.data["node"], str(a["choice"]), d.data.get("from"))
            return None
        if d.kind == "loan":
            n.decisions.remove(d)
            borrower = world.nations[d.data["from"]]
            amount = float(d.data["amount"])
            if a.get("choice") == "accept" and n.stock >= amount and borrower.alive:
                finance.lend(world, n, borrower, amount)
            return None
        if d.kind == "treaty":
            n.decisions.remove(d)
            other = world.nations[d.data["from"]]
            if a.get("choice") == "accept" and trade.treaty_blocker(world, other, n, d.data["treaty"]) in (
                None,
                f"needs {rules.TREATIES[d.data['treaty']].sway:.0f} Sway",
            ):
                other.sway = max(0.0, other.sway - rules.TREATIES[d.data["treaty"]].sway)
                trade.sign(world, other, n, d.data["treaty"])
            return None
        if d.kind == "peace":
            n.decisions.remove(d)
            if a.get("choice") == "accept":
                military.make_peace(world, world.nations[d.data["from"]], n, d.data.get("payer"))
            return None
        return politics.resolve_decision(world, n, str(a["id"]), str(a.get("choice", "")))
    return None


def _act_war(world: World, n: Nation, a: Action) -> str | None:
    kind = a["kind"]
    if kind == "raise_unit":
        src: Node | Unit | None = _own_node(world, n, a.get("node")) if a.get("node") else _unit(world, n, a)
        assert src is not None
        raised = military.raise_unit(world, n, src, str(a["unit_kind"]))
        name = rules.UNITS[raised.kind].name
        world.emit(n.id, "raised", f"{name} raised at {world.nodes[raised.node].name}.", raised.node)
    elif kind in ("disband", "upgrade", "raid"):
        unit = _unit(world, n, a)
        assert unit is not None
        if kind == "disband":
            military.disband(world, unit)
        elif kind == "upgrade":
            t = rules.UNITS["musketeers"]
            n.store["wares"] -= t.wares
            n.treasury -= t.treasury
            unit.kind = "musketeers"
        else:
            military.raid(world, n, unit, str(a["to"]))
    elif kind == "declare_war":
        other = world.nations[str(a["nation"])]
        if other.id not in n.casus_belli:
            n.sway -= rules.WAR_COST
        military.declare_war(world, n, other)
    elif kind == "offer_peace":
        other = world.nations[str(a["nation"])]
        made = military.offer_peace(world, n, other, str(a["terms"]))
        if not other.player and not made:
            return "refused"
    return None


# --- the investment queue (§9.6) ------------------------------------------------------------------


def process_build_queue(world: World, n: Nation) -> None:
    r = float(n.last.get("r", rules.R0))
    keep: list[dict[str, Any]] = []
    blocked = False
    for item in n.build_queue:
        nd = world.nodes.get(item["node"])
        work = item["work"]
        if nd is None or nd.owner != n.id:
            continue
        if blocked:
            keep.append(item)
            continue
        improve = bool(item.get("improve"))
        if improve and nd.works.count(work) - nd.improved_count(work) <= 0:
            continue  # nothing left here to improve: the work was pulled down or taken
        cost = rules.IMPROVEMENTS[work].cost if improve else work_cost(n, work)
        if n.stock < cost:
            item["status"] = f"waiting for Stock ({n.stock:.0f}/{cost:.0f})"
            keep.append(item)
            blocked = True
            continue
        ret = improvement_return(world, n, nd, work) if improve else expected_return(world, n, nd, work)
        bounty = 0.0
        if ret < r:
            bounty = round(cost * (r - ret) * 5.0, 1)
            if n.seat != "civil" or n.treasury < bounty:
                item["status"] = f"unprofitable: returns {ret:.0%} against {r:.0%}; " + (
                    "a bounty needs a Treasury" if n.seat != "civil" else f"needs a {bounty:.0f} bounty"
                )
                keep.append(item)
                continue
            n.treasury -= bounty
        n.stock -= cost
        note = f" (bounty {bounty:.0f} from the Treasury)" if bounty else ""
        if improve:
            _improve(world, n, nd, work, note)
        else:
            _raise_work(world, n, nd, work, note)
    n.build_queue = keep
    if n.auto_invest and not blocked and n.knows(rules.AUTO_INVEST_TECH):
        _investors_choose(world, n, r)


def best_investment(world: World, n: Nation, r: float) -> tuple[float, Node, str, bool] | None:
    """The private work, or improvement, that would pay best anywhere we hold, if it beats the
    rate of profit: (return, node, work, is an improvement)."""

    best: tuple[float, Node, str, bool] | None = None
    for nd in world.nodes_of(n.id):
        for work, w in rules.WORKS.items():
            if w.public or build_blocker(world, n, nd.id, work) is not None:
                continue
            ret = expected_return(world, n, nd, work)
            if ret >= r and (best is None or ret > best[0]):
                best = (ret, nd, work, False)
        for work in rules.IMPROVEMENTS:
            if improve_blocker(world, n, nd.id, work) is not None:
                continue
            ret = improvement_return(world, n, nd, work)
            if ret >= r and (best is None or ret > best[0]):
                best = (ret, nd, work, True)
    return best


def _investors_choose(world: World, n: Nation, r: float) -> None:
    """With our own queue served, Stock-holders put what is left where it pays best."""

    replaced = False
    for _ in range(rules.AUTO_INVEST_PER_TURN):
        best = best_investment(world, n, r)
        swap = None
        if best is None and not replaced and n.knows(rules.REINVEST_TECH):
            swap = best_replacement(world, n, r)
            if swap is not None:
                best = (swap[0], swap[1], swap[2], False)
        if best is None:
            return
        ret, nd, work, improve = best
        cost = rules.IMPROVEMENTS[work].cost if improve else work_cost(n, work)
        if n.stock - cost < rules.AUTO_INVEST_RESERVE:
            return
        if swap is not None:
            old, old_ret = swap[3], swap[4]
            _pull_down(world, n, nd, old, f" by its investors (it returned {old_ret:.0%})")
            replaced = True  # one a turn: capital moves, but not all at once
        n.stock -= cost
        if improve:
            _improve(world, n, nd, work, f" by its investors, for a return of {ret:.0%}")
        else:
            _raise_work(world, n, nd, work, f" by its investors, for a return of {ret:.0%}")


def work_return(world: World, n: Nation, nd: Node, work: str) -> float:
    """What one standing work adds to its town's surplus, per unit of the stock in it: what
    would be lost if it were pulled down. A pasture with no herds to tend earns nothing."""

    if work not in nd.works:
        return 0.0
    before = _surplus(world, n, nd)
    i = len(nd.works) - 1 - nd.works[::-1].index(work)
    nd.works.pop(i)
    try:
        after = _surplus(world, n, nd)
    finally:
        nd.works.insert(i, work)
    ret = (before - after) / max(work_cost(n, work), 1.0)
    if work in ("market", "port"):
        ret += rules.TRADE_TOWN_PREMIUM
    return ret


def food_to_spare(n: Nation) -> bool:
    """Whether a food work could be pulled down without hunger: we made enough and more."""

    made = float(n.last.get("made", {}).get("food", 0.0))
    eaten = float(n.last.get("consumed", {}).get("food", 0.0))
    return eaten > 0 and made >= rules.FOOD_SPARE * eaten


def replaceable(n: Nation, nd: Node) -> list[str]:
    """The works investors may pull down: private ones, trade towns kept, and food works
    only while the people has food to spare."""

    spare = food_to_spare(n)
    return [
        w
        for w in set(nd.works)
        if not rules.WORKS[w].public
        and w not in rules.NEVER_REPLACED
        and (spare or w not in rules.FOOD_WORKS)
    ]


def best_replacement(world: World, n: Nation, r: float) -> tuple[float, Node, str, str, float] | None:
    """In a town with no free slot: (return, node, new work, the work it replaces, that work's
    return), when the new one beats the rate of profit and pays REINVEST_FACTOR times the old."""

    best: tuple[float, Node, str, str, float] | None = None
    for nd in world.nodes_of(n.id):
        if len(nd.works) + queued_on(n, nd.id) < nd.slots():
            continue
        candidates = replaceable(n, nd)
        if not candidates:
            continue
        old = min(candidates, key=lambda w: work_return(world, n, nd, w))
        old_ret = work_return(world, n, nd, old)
        nd.works.remove(old)  # try the town with the slot freed
        try:
            for work, w in rules.WORKS.items():
                if w.public or work == old or build_blocker(world, n, nd.id, work) is not None:
                    continue
                ret = expected_return(world, n, nd, work)
                if ret >= r and ret >= rules.REINVEST_FACTOR * max(old_ret, 0.01):
                    if best is None or ret - old_ret > best[0] - best[4]:
                        best = (ret, nd, work, old, old_ret)
        finally:
            nd.works.append(old)
    return best


def _pull_down(world: World, n: Nation, nd: Node, work: str, note: str = "") -> None:
    nd.works.pop(len(nd.works) - 1 - nd.works[::-1].index(work))  # the last: an unimproved one if any
    if work in nd.improved:
        nd.improved[work] = nd.improved_count(work)
    if work == "pasture" and "pasture" not in nd.works:
        nd.herds *= 0.5  # half the herd goes to market
    world.emit(n.id, "demolished", f"{rules.WORKS[work].name} at {nd.name} is pulled down{note}.", nd.id)


def _raise_work(world: World, n: Nation, nd: Node, work: str, note: str = "") -> None:
    if work == "pasture" and nd.herds <= 0:
        nd.herds = rules.TAME_HERDS / 2
    nd.works.append(work)
    world.emit(n.id, "built", f"{rules.WORKS[work].name} built at {nd.name}{note}.", nd.id)
    if work == "market" and "first_town" not in n.moments:
        n.moments.append("first_town")
        world.emit(
            n.id,
            "moment",
            f"{nd.name} becomes a market town: the market widens, and with it the division of labour.",
            nd.id,
            quote=rules.MOMENT_QUOTES["first_town"],
        )
    if work == "manufactory" and "first_manufactory" not in n.moments:
        n.moments.append("first_manufactory")
        world.emit(
            n.id,
            "moment",
            f"The first manufactory opens at {nd.name}: one trade divided into many operations.",
            nd.id,
            quote=rules.MOMENT_QUOTES["first_manufactory"],
        )


# --- trade and diplomacy (§11, §16) ---------------------------------------------------------------


def traders_out(world: World, n: Nation) -> int:
    return sum(1 for u in world.units_of(n.id) if u.kind in ("caravan", "merchantman"))


def _check_trade(world: World, n: Nation, a: Action) -> str | None:
    kind = a["kind"]
    if kind == "send_trader":
        nd = _own_node(world, n, a.get("node"))
        which = str(a.get("trader", ""))
        if nd is None:
            return "not your settled node"
        if which not in rules.TRADER_COST:
            return "caravan or merchantman"
        need = "market" if which == "caravan" else "port"
        if need not in nd.works:
            return (
                "a caravan sets out from a Market Town"
                if which == "caravan"
                else "a merchantman sails from a Port"
            )
        if n.stock < rules.TRADER_COST[which]:
            return f"needs {rules.TRADER_COST[which]:.0f} Stock"
        if trade.route_count(world, n.id) + traders_out(world, n) >= trade.route_slots(world, n):
            return "no free route slot"
        return None
    if kind == "open_route":
        u = _unit(world, n, a)
        if u is None:
            return "no such trader"
        return trade.trader_blocker(world, n, u)
    other = world.nations.get(str(a.get("nation", "")))
    if other is None or other.id == n.id or not other.alive:
        return "no such people"
    if other.id not in n.contacts:
        return "not in contact"
    if kind == "embargo":
        if n.embargo.get(other.id, 0) >= world.turn:
            return "already under our embargo"
        if n.seat in ("council", "interregnum"):
            return "needs a chiefdom or state"
        return None if n.sway >= rules.EMBARGO_COST else f"needs {rules.EMBARGO_COST:.0f} Sway"
    if kind == "gift":
        if military.at_war(world, n.id, other.id):
            return "at war"
        if n.stock < rules.GIFT_COST and n.store["food"] < rules.GIFT_COST:
            return f"needs {rules.GIFT_COST:.0f} Stock or food"
        if n.counters.get(f"gift_{other.id}", -99) >= world.turn - 2:
            return "we gave lately"
        return None
    treaty = str(a.get("treaty", ""))
    if kind == "cancel_treaty":
        return None if world.treaty(treaty, n.id, other.id) else "no such treaty"
    why = trade.treaty_blocker(world, n, other, treaty)
    if why:
        return why
    if any(d.kind == "treaty" and d.data.get("from") == n.id for d in other.decisions):
        return "a proposal is already waiting"
    return None


def _act_trade(world: World, n: Nation, a: Action) -> str | None:
    kind = a["kind"]
    if kind == "send_trader":
        nd = world.nodes[str(a["node"])]
        which = str(a["trader"])
        n.stock -= rules.TRADER_COST[which]
        uid = world.new_id("u")
        world.units[uid] = Unit(uid, n.id, which, nd.id, 0.0, moves_left=0, home=nd.id)
        world.emit(n.id, "trader", f"A {rules.UNITS[which].name.lower()} sets out from {nd.name}.", nd.id)
    elif kind == "open_route":
        u = _unit(world, n, a)
        assert u is not None
        trade.open_route(world, n, u)
    elif kind == "embargo":
        other = world.nations[str(a["nation"])]
        n.sway -= rules.EMBARGO_COST
        trade.embargo(world, n, other)
    elif kind == "gift":
        other = world.nations[str(a["nation"])]
        n.counters[f"gift_{other.id}"] = float(world.turn)
        trade.gift(world, n, other)
    elif kind == "cancel_treaty":
        t = world.treaty(str(a["treaty"]), n.id, str(a["nation"]))
        assert t is not None
        world.treaties.remove(t)
        other = world.nations[str(a["nation"])]
        other.relations[n.id] = other.relations.get(n.id, 0.0) - 10.0
        for x, y in ((n, other), (other, n)):
            world.emit(
                x.id, "treaty", f"The {rules.TREATIES[t['kind']].name.lower()} with {y.name} is ended."
            )
    elif kind == "propose_treaty":
        other = world.nations[str(a["nation"])]
        treaty = str(a["treaty"])
        name = rules.TREATIES[treaty].name
        if other.player:
            other.decisions.append(
                Decision(
                    id=world.new_id("d"),
                    kind="treaty",
                    title=f"{n.name} propose a {name.lower()}",
                    text=f"{n.name} propose a {name.lower()}. {rules.TREATIES[treaty].effect}",
                    choices=[
                        {"key": "accept", "label": "Accept", "effect": "Signed at no cost to us."},
                        {"key": "refuse", "label": "Refuse", "effect": "Nothing changes."},
                    ],
                    data={"from": n.id, "treaty": treaty},
                )
            )
            return None
        if not trade.would_accept(world, n, other, treaty):
            return "refused"
        n.sway -= rules.TREATIES[treaty].sway
        trade.sign(world, n, other, treaty)
    return None


# --- public credit (§14.4) --------------------------------------------------------------------------


def _check_credit(world: World, n: Nation, a: Action) -> str | None:
    kind = a["kind"]
    if kind == "borrow":
        try:
            amount = float(a.get("amount", 0.0))
        except (TypeError, ValueError):
            return "borrow a number"
        return finance.borrow_blocker(world, n, str(a.get("source", finance.DOMESTIC)), amount)
    if not n.debts:
        return "we owe nothing"
    if kind == "repay":
        return None if n.treasury >= 1.0 else "the Treasury is empty"
    return None  # default: always possible, never free


def _act_credit(world: World, n: Nation, a: Action) -> str | None:
    kind = a["kind"]
    if kind == "borrow":
        amount = float(a["amount"])
        source = str(a.get("source", finance.DOMESTIC))
        if source == finance.DOMESTIC:
            finance.lend(world, None, n, amount)
            return None
        if not finance.request_foreign(world, n, world.nations[source], amount):
            return None if world.nations[source].player else "refused"
    elif kind == "repay":
        lender = a.get("lender")
        finance.repay(world, n, str(lender) if lender else None, float(a.get("amount", n.treasury)))
    elif kind == "default":
        finance.default(world, n)
    return None
