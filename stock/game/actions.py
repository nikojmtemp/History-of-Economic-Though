"""Every verb the player and the AI can use (design doc §7.2, §9.6, §12, §13, §14).

`check` says why an action is not allowed (or None); `act` applies it. The player and
the AI go through the same two functions: no rival has a verb the player lacks.
"""

from __future__ import annotations

from typing import Any

from stock.game import economy, politics, research, rules, trade
from stock.game.state import Nation, Node, Unit, World

Action = dict[str, Any]

# --- small helpers ----------------------------------------------------------------------


def split_cost(n: Nation) -> float:
    return rules.SPLIT_COST_ELDERS if n.knows("elders") else rules.SPLIT_COST


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
    return sum(1 for q in n.build_queue if q["node"] == node_id)


def move_cost(world: World, u: Unit, to: str) -> int | None:
    e = world.edge_between(u.node, to)
    if e is None or e.kind == "sea":
        return None
    return e.cost()


def can_enter(world: World, n: Nation, node_id: str) -> bool:
    owner = world.nodes[node_id].owner
    return owner is None or owner == n.id


def expected_return(world: World, n: Nation, nd: Node, work: str) -> float:
    """Profit per unit of stock a new work would earn at today's prices (§9.6)."""

    w = rules.WORKS[work]
    if w.jobs == 0:
        return 0.0
    nd.works.append(work)
    try:
        rows = economy._work_jobs(world, n, nd, float(n.last.get("dol", 1.0)))
    finally:
        nd.works.pop()
    row = next((r for r in reversed(rows) if r[0] == work), None)
    if row is None:
        return 0.0
    _w, jobs, _per, value_per_job = row
    wage = float(n.last.get("wage", n.prices["food"]))
    surplus = jobs * (value_per_job - wage)
    return surplus / max(work_cost(n, work), 1.0)


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
    if kind in ("move", "split", "merge", "follow", "tame", "settle"):
        u = _unit(world, n, a)
        if u is None:
            return "no such unit"
        nd = world.nodes[u.node]
        if kind == "move":
            to = str(a.get("to", ""))
            if to not in world.nodes:
                return "no such node"
            c = move_cost(world, u, to)
            if c is None:
                return "not adjacent by land"
            if not can_enter(world, n, to):
                return "settled by another people"
            if u.moves_left <= 0 or (c > u.moves_left and u.moves_left < u.max_moves(set(n.known))):
                return "no moves left this turn"
            return None
        if kind == "split":
            if u.hands < 2 * rules.MIN_UNIT_HANDS:
                return f"needs at least {2 * rules.MIN_UNIT_HANDS:.0f} hands"
            if n.sway < split_cost(n):
                return f"needs {split_cost(n):.0f} Sway"
            return None
        if kind == "merge":
            o = world.units.get(str(a.get("other", "")))
            if o is None or o.nation != n.id or o.id == u.id or o.node != u.node:
                return "needs another of your units on the same node"
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
            if not n.knows("taming"):
                return "needs Taming"
            if u.kind != "band":
                return "already a horde"
            if "wild_herds" not in nd.features:
                return "no wild herds here"
            return None
        if kind == "settle":
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
        if not trade.in_reach(world, n, other):
            return "too far: bring a band next to them"
        if trade.route_count(world, n.id) >= trade.route_slots(world, n):
            return "no free route slot"
        return None
    if kind == "feast":
        if n.feast_ready > 0:
            return f"feasted recently ({n.feast_ready} turns)"
        need = rules.FEAST_FOOD_PER_HAND * world.hands_of(n.id)
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
    if kind == "build":
        return build_blocker(world, n, a.get("node"), str(a.get("work", "")))
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


# --- application ---------------------------------------------------------------------------------


def act(world: World, nation_id: str, a: Action) -> str | None:
    """Apply `a` for `nation_id`; returns the reason it was refused, or None."""

    n = world.nations[nation_id]
    why = check(world, n, a)
    if why:
        return why
    kind = a["kind"]
    if kind == "move":
        u = _unit(world, n, a)
        assert u is not None
        c = move_cost(world, u, str(a["to"])) or 1
        u.moves_left = max(0, u.moves_left - c)
        u.node = str(a["to"])
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
        n.store["food"] -= rules.FEAST_FOOD_PER_HAND * world.hands_of(n.id)
        n.sway = min(rules.SWAY_CAP, n.sway + rules.FEAST_SWAY + (1.0 if n.knows("elders") else 0.0))
        for order in rules.ORDERS:
            n.orders[order].contentment = economy.clamp(n.orders[order].contentment + 5.0, 0.0, 100.0)
        n.feast_ready = rules.FEAST_COOLDOWN
    elif kind == "research":
        n.researching = str(a["key"])
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
        return politics.resolve_decision(world, n, str(a["id"]), str(a.get("choice", "")))
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
        cost = work_cost(n, work)
        if n.stock < cost:
            item["status"] = f"waiting for Stock ({n.stock:.0f}/{cost:.0f})"
            keep.append(item)
            blocked = True
            continue
        ret = expected_return(world, n, nd, work)
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
        if work == "pasture" and nd.herds <= 0:
            nd.herds = rules.TAME_HERDS / 2
        nd.works.append(work)
        extra = f" (bounty {bounty:.0f} from the Treasury)" if bounty else ""
        world.emit(n.id, "built", f"{rules.WORKS[work].name} built at {nd.name}{extra}.", nd.id)
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
    n.build_queue = keep
