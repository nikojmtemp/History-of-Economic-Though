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
    """Ships keep to sea lanes and the coast; everyone else keeps to land."""

    e = world.edge_between(u.node, to)
    if e is None:
        return None
    if trade.naval(u):
        return 1 if trade.ship_edge_ok(world, u.node, to) else None
    if e.kind == "sea":
        # colonists: a band at its own port may take ship, once the people knows Navigation
        here = world.nodes[u.node]
        n = world.nations[u.nation]
        if u.kind == "band" and here.owner == u.nation and "port" in here.works and n.knows("navigation"):
            return 1
        return None
    return e.cost()


def can_enter(world: World, n: Nation, node_id: str) -> bool:
    """Peaceful passage: open ground or our own. War opens the enemy's ground to soldiers."""

    owner = world.nodes[node_id].owner
    return owner is None or owner == n.id


def hostile_at(world: World, n: Nation, node_id: str) -> bool:
    nd = world.nodes[node_id]
    return world.hostile_owner(n.id, nd) or any(world.hostile(u, n.id) for u in world.units_at(node_id))


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
    ret = surplus / max(work_cost(n, work), 1.0)
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
        if u is None or not (u.military or kind == "raid"):
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
    elif kind == "demolish":
        nd = world.nodes[str(a["node"])]
        work = str(a["work"])
        nd.works.remove(work)
        if work == "pasture" and "pasture" not in nd.works:
            nd.herds *= 0.5  # half the herd goes to market
        world.emit(n.id, "demolished", f"{rules.WORKS[work].name} at {nd.name} is pulled down.", nd.id)
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
