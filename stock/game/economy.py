"""The economy (design doc §9–§10, §14.1–14.2): production, the split, taxes,
consumption, standing, accumulation, and population — one pass per turn.

Hunting is resolved for the whole world first because bands of different nations
share the game on a node; everything after that is per nation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from stock.game import rules
from stock.game.state import Nation, Node, World

# --- helpers ----------------------------------------------------------------------------


def clamp(x: float, lo: float, hi: float) -> float:
    if x != x:  # NaN guard
        return lo
    return max(lo, min(hi, x))


def _private_land(n: Nation) -> bool:
    return n.option("property") in rules.PRIVATE_LAND


def _private_herds(n: Nation) -> bool:
    return n.option("property") in rules.PRIVATE_HERDS


def has_stupefaction(world: World, n: Nation) -> bool:
    dol = float(n.last.get("dol", 1.0))
    return n.mode == "commerce" and dol > 2.0


def extent_of(world: World, n: Nation) -> float:
    """§9.4: hands in the nation's largest connected market, plus market towns and routes."""

    owned = {nd.id for nd in world.nodes_of(n.id)}
    ports = {nid for nid in owned if "port" in world.nodes[nid].works}
    seen: set[str] = set()
    best = 0.0
    for start in owned:
        if start in seen:
            continue
        comp, stack = 0.0, [start]
        seen.add(start)
        while stack:
            cur = stack.pop()
            comp += world.nodes[cur].hands
            for e in world.adjacency()[cur]:
                o = e.other(cur)
                if o not in owned or o in seen:
                    continue
                linked = e.kind in ("river", "road") or (e.kind == "sea" and cur in ports and o in ports)
                if linked:
                    seen.add(o)
                    stack.append(o)
        best = max(best, comp)
    mobile = sum(u.hands for u in world.units_of(n.id))
    towns = sum(nd.works.count("market") for nd in world.nodes_of(n.id))
    route_part = 0.0
    for r in world.routes.values():
        if n.id in (r.a, r.b) and r.active:
            partner = r.b if r.a == n.id else r.a
            share = rules.ROUTE_EXTENT_SHARE * (1.5 if n.option("commerce") == "free_trade" else 1.0)
            route_part += share * min(world.hands_of(partner), r.capacity * rules.ROUTE_EXTENT_PER_CAPACITY)
    return best + 0.5 * mobile + towns * rules.EXTENT_PER_MARKET_TOWN + route_part


def security_of(world: World, n: Nation) -> float:
    justice = n.budget.get("justice", 0) if n.seat == "civil" else 0
    owned = world.nodes_of(n.id)
    disorder = (sum(1 for nd in owned if nd.unrest > 70) / len(owned)) if owned else 0.0
    bonus = 0.0
    if n.option("property") == "alienable" or n.option("labour") in rules.FREE_LABOUR:
        bonus += 0.1
    if n.option("revenue") == "tax_farming":
        bonus -= 0.1
    from stock.game.military import defence_ratio as _defence_ratio  # military imports this module

    defence_ratio = _defence_ratio(world, n)
    return clamp(
        rules.SECURITY_BASE + 0.3 * justice / 3 + 0.2 * defence_ratio - 0.2 * disorder + bonus, 0.2, 1.0
    )


# --- the plan: who works where -------------------------------------------------------------


@dataclass
class Job:
    node: str
    work: str  # work key, or "hunt" / "forage" / "herd"
    hands: float
    food: float = 0.0
    wares: float = 0.0
    luxuries: float = 0.0
    herd_growth: float = 0.0  # head of herd added
    service: float = 0.0  # a market town's trade, in baskets: produce, but no goods to consume
    cost: float = 0.0  # stock in the work (for profit)
    source: str = "hunting"  # hunting | pasturage | agriculture | commerce
    paid: str = "labour"  # labour | herds | land | stock


@dataclass
class Plan:
    nation: str
    hands: float = 0.0
    workforce_share: float = 1.0
    owners: dict[str, float] = field(default_factory=dict)
    jobs: list[Job] = field(default_factory=list)
    hunters: dict[str, float] = field(default_factory=dict)  # node -> hunting hands
    open_jobs: float = 0.0
    filled_jobs: float = 0.0


def _owners(world: World, n: Nation) -> dict[str, float]:
    land_hands = 0.0
    stock_works = 0
    for nd in world.nodes_of(n.id):
        for w in nd.works:
            work = rules.WORKS[w]
            if work.paid == "land":
                land_hands += work.jobs
            elif work.paid == "stock":
                stock_works += 1
    for u in world.units_of(n.id):
        if u.kind == "horde":
            land_hands += u.herds / rules.HERDS_PER_HERDSMAN
    props = 0.0
    if _private_herds(n) and land_hands > 0:
        props = max(0.2, rules.PROPRIETOR_OWNER_SHARE * land_hands)
    merchants = sum(1 for r in world.routes.values() if r.a == n.id and r.kind != "barter")
    stock = rules.STOCK_OWNERS_PER_WORK * (stock_works + merchants)
    return {"proprietors": props, "stock": stock}


def _work_jobs(
    world: World, n: Nation, nd: Node, dol: float
) -> list[tuple[str, int, dict[str, float], float]]:
    """(work, jobs, per-job output, per-job value) for every work on the node."""

    out = []
    prod = rules.SERF_PRODUCTIVITY if n.option("labour") == "serfdom" else 1.0
    if nd.unrest > 70:
        prod *= 0.5
    elif nd.unrest > 40:
        prod *= 0.75
    herdsmen_left = nd.herds / rules.HERDS_PER_HERDSMAN
    extent = float(n.last.get("extent", 0.0))
    for w in nd.works:
        work = rules.WORKS[w]
        if work.jobs == 0:
            continue
        per: dict[str, float] = {}
        jobs = work.jobs
        if w == "pasture":
            # a pasture employs only the herdsmen the node's herd needs
            jobs = min(work.jobs, math.ceil(herdsmen_left - 1e-9))
            herdsmen_left -= jobs
            if jobs <= 0:
                continue
            per = {"food": rules.HERDS_PER_HERDSMAN / rules.HERDS_PER_FOOD}
        elif w == "fields":
            mult = nd.t.arable
            if n.knows("rotation"):
                mult *= 1.5
            if n.mode == "agriculture":
                mult *= 1.25
            if n.option("property") == "alienable":
                mult *= 1.0 + min(0.25, 0.01 * n.counters.get("improving", 0.0))
            per = {"food": work.makes["food"] * mult}
        elif w == "workshop":
            mult = dol**work.dol * (1.2 if n.option("labour") == "guilds" else 1.0)
            if "rare" in nd.features:
                per = {"luxuries": rules.RARE_LUXURY_YIELD * mult, "wares": 0.3 * mult}
            else:
                per = {"wares": work.makes["wares"] * mult}
        elif w == "manufactory":
            mult = dol**work.dol * (1.5 if n.knows("machinery") else 1.0)
            per = {"wares": work.makes["wares"] * mult}
            if "rare" in nd.features:
                per["luxuries"] = 0.4 * mult
        elif w == "market":
            # a market town's trade grows with the market it serves
            # a market town sells no goods of its own: its trade grows with the market it serves
            per = {"service": rules.MARKET_SERVICE_PER_EXTENT * extent}
        else:
            per = dict(work.makes)
        boost = rules.PATENT_BOOST if n.counters.get(f"patent:{nd.id}", 0.0) >= world.turn else 1.0
        per = {g: q * prod * boost for g, q in per.items()}
        value = sum(q * (n.prices[g] if g in n.prices else 1.0) for g, q in per.items())
        if w == "pasture":
            value += rules.HERD_GROWTH * rules.HERDS_PER_HERDSMAN * rules.HERD_VALUE
        out.append((w, jobs, per, value))
    return out


def plan_labour(world: World, n: Nation) -> Plan:
    plan = Plan(n.id)
    plan.hands = world.hands_of(n.id)
    if plan.hands <= 0:
        return plan
    plan.owners = _owners(world, n)
    nonwork = min(0.4 * plan.hands, n.retainers + sum(plan.owners.values()))
    plan.workforce_share = 1.0 - nonwork / plan.hands
    dol = float(n.last.get("dol", 1.0))
    free = n.option("labour") in rules.FREE_LABOUR
    for nd in world.nodes_of(n.id):
        if nd.siege is not None:
            continue  # a besieged town neither sows nor trades
        workforce = nd.hands * plan.workforce_share
        jobs = _work_jobs(world, n, nd, dol)
        plan.open_jobs += sum(j[1] for j in jobs)
        if free:
            jobs.sort(key=lambda j: j[3], reverse=True)  # best-paid work first
        for w, count, per, _value in jobs:
            take = min(workforce, float(count))
            if take <= 0:
                break
            workforce -= take
            plan.filled_jobs += take
            work = rules.WORKS[w]
            job = Job(nd.id, w, take, cost=work.cost * take / max(work.jobs, 1))
            job.food, job.wares, job.luxuries = (per.get(g, 0.0) * take for g in rules.GOODS)
            job.service = per.get("service", 0.0) * take
            if w == "pasture":
                job.source, job.paid = "pasturage", "herds"
            elif work.paid == "land":
                job.source, job.paid = ("agriculture", "land") if w == "fields" else ("commerce", "land")
            else:
                job.source, job.paid = "commerce", "stock"
            plan.jobs.append(job)
        if workforce > 0:
            if nd.t.game > 0 and nd.game > 0.05:
                plan.hunters[nd.id] = plan.hunters.get(nd.id, 0.0) + workforce
            else:
                plan.jobs.append(Job(nd.id, "forage", workforce, food=workforce * rules.FORAGE_YIELD))
    for u in world.units_of(n.id):
        if u.military:
            continue  # soldiers eat, but do not work
        workforce = u.hands * plan.workforce_share
        if u.kind == "horde" and u.herds > 0:
            herdsmen = min(workforce, u.herds / rules.HERDS_PER_HERDSMAN)
            workforce -= herdsmen
            plan.jobs.append(Job(u.node, "herd", herdsmen, source="pasturage", paid="herds"))
        if u.followed:
            workforce *= 0.5  # half the band follows the herds instead of hunting
        if workforce > 0:
            plan.hunters[u.node] = plan.hunters.get(u.node, 0.0) + workforce
    return plan


# --- hunting, for the whole world -----------------------------------------------------------


def resolve_hunting(world: World, plans: dict[str, Plan]) -> None:
    by_node: dict[str, float] = {}
    for p in plans.values():
        for node, h in p.hunters.items():
            by_node[node] = by_node.get(node, 0.0) + h
    for node_id, total in by_node.items():
        nd = world.nodes[node_id]
        t = nd.t
        game_yield = rules.HUNT_YIELD * t.game * nd.game
        fish_hands = min(total, rules.FISH_HANDS_CAP) if t.fish > 0 else 0.0
        for p in plans.values():
            h = p.hunters.get(node_id, 0.0)
            if h <= 0:
                continue
            n = world.nations[p.nation]
            bonus = 1.1 if n.option("property") == "killer" else 1.0
            fish_mult = 2.0 if n.knows("fishing") else 1.0
            fish = fish_hands * (h / total) * t.fish * rules.HUNT_YIELD * fish_mult
            p.jobs.append(Job(node_id, "hunt", h, food=h * game_yield * bonus + fish))
        nd.game = clamp(nd.game - rules.GAME_DEPLETION * total * nd.game, 0.0, 1.0)
    for nd in world.nodes.values():
        nd.game = clamp(nd.game + rules.GAME_REGEN * (1.0 - nd.game), 0.0, 1.0)


# --- herds --------------------------------------------------------------------------------


def _grow_herds(world: World, n: Nation, plan: Plan) -> float:
    """Grows every herd the nation keeps; returns head added (pasturage produce)."""

    growth_mult = (1.2 if n.option("property") == "herds" else 1.0) * (1.1 if n.mode == "pasturage" else 1.0)
    added = 0.0
    herdsmen_at: dict[str, float] = {}
    for j in plan.jobs:
        if j.work == "pasture":
            herdsmen_at[j.node] = herdsmen_at.get(j.node, 0.0) + j.hands
    # herds on a node are shared grazing: cap by the node's grazing
    for u in world.units_of(n.id):
        if u.kind != "horde" or u.herds <= 0:
            continue
        nd = world.nodes[u.node]
        cap = rules.HERD_CAP_PER_GRAZING * nd.t.grazing
        load = sum(x.herds for x in world.units_at(u.node)) + nd.herds
        herdsmen = next((j.hands for j in plan.jobs if j.work == "herd" and j.node == u.node), 0.0)
        tended = clamp(herdsmen * rules.HERDS_PER_HERDSMAN / u.herds, 0.0, 1.0)
        room = clamp(1.0 - load / cap, -0.5, 1.0) if cap > 0 else -0.5
        g = u.herds * rules.HERD_GROWTH * growth_mult * tended * room
        u.herds = max(0.0, u.herds + g)
        added += g
        food = u.herds * tended / rules.HERDS_PER_FOOD
        for j in plan.jobs:
            if j.work == "herd" and j.node == u.node:
                j.food += food
                j.herd_growth += max(0.0, g)  # a shrinking herd is lost capital, not negative produce
                break
    for nd in world.nodes_of(n.id):
        if nd.herds <= 0:
            continue
        cap = rules.HERD_CAP_PER_GRAZING * nd.t.grazing
        tended = clamp(herdsmen_at.get(nd.id, 0.0) * rules.HERDS_PER_HERDSMAN / nd.herds, 0.0, 1.0)
        room = clamp(1.0 - nd.herds / cap, -0.5, 1.0) if cap > 0 else -0.5
        g = nd.herds * rules.HERD_GROWTH * growth_mult * tended * room if tended > 0 else -0.1 * nd.herds
        nd.herds = max(0.0, nd.herds + g)
        added += g
        for j in plan.jobs:
            if j.work == "pasture" and j.node == nd.id:
                j.herd_growth += max(0.0, g) * j.hands / max(herdsmen_at[nd.id], 1e-9)
    return added


# --- one nation's year ---------------------------------------------------------------------


def run_nation(world: World, n: Nation, plan: Plan) -> dict[str, Any]:
    p = n.prices
    herd_added = _grow_herds(world, n, plan)
    hands = plan.hands
    workforce = hands * plan.workforce_share

    # produce, by source and by good
    made = {g: 0.0 for g in rules.GOODS}
    sources = {m: 0.0 for m in rules.MODES}
    for j in plan.jobs:
        for g in rules.GOODS:
            made[g] += getattr(j, g)
        sources[j.source] += (
            j.food * p["food"]
            + j.wares * p["wares"]
            + j.luxuries * p["luxuries"]
            + (j.herd_growth * rules.HERD_VALUE)
            + j.service
        )
    # trade (§11): the merchants' margin on routes we opened is commerce produce
    tr = n.trade or {}
    merchant_profit = float(tr.get("profit", 0.0))
    barter_gain = float(tr.get("barter", 0.0))
    sources["commerce"] += merchant_profit + barter_gain
    produce = sum(sources.values())
    by_node: dict[str, float] = {}
    for j in plan.jobs:
        v = (
            j.food * p["food"]
            + j.wares * p["wares"]
            + j.luxuries * p["luxuries"]
            + j.herd_growth * rules.HERD_VALUE
            + j.service
        )
        by_node[j.node] = by_node.get(j.node, 0.0) + v

    # the split: wages first, profit next, rent last (§10.1)
    labour_opt = n.option("labour")
    if labour_opt == "custom":
        bargaining = 0.0
    elif labour_opt == "serfdom":
        bargaining = -0.2
    else:
        scarcity = plan.open_jobs / workforce if workforce > 0 else 1.0
        bargaining = clamp(0.5 * (scarcity - 1.0), *rules.BARGAIN_CLAMP)
        if labour_opt == "poor_laws":
            bargaining = max(bargaining, 0.1)
    wage = p["food"] * (1.0 + bargaining)
    r = float(n.last.get("r", rules.R0))
    income = {o: 0.0 for o in rules.ORDERS}
    split = {"wages": 0.0, "profit": 0.0, "rent": 0.0}

    def pay(order: str, kind: str, amount: float) -> None:
        income[order] += amount
        split[kind] += amount

    for j in plan.jobs:
        value = (
            j.food * p["food"]
            + j.wares * p["wares"]
            + j.luxuries * p["luxuries"]
            + (j.herd_growth * rules.HERD_VALUE)
            + j.service
        )
        if value <= 0:
            continue
        if (
            j.paid == "labour"
            or (j.paid == "herds" and not _private_herds(n))
            or (j.paid == "land" and not _private_land(n) and j.work == "fields")
        ):
            pay("labour", "wages", value)
            continue
        wages = min(value, j.hands * wage * (1.2 if (j.paid == "stock" and labour_opt == "guilds") else 1.0))
        pay("labour", "wages", wages)
        rest = value - wages
        if j.paid == "stock":
            pay("stock", "profit", rest)
        elif j.paid == "herds":
            pay("proprietors", "rent", rest)
        else:  # land: fields, mines
            profit = 0.0
            if n.option("property") == "alienable" or j.work == "mine":
                profit = min(rest, r * j.cost)
                pay("stock", "profit", profit)
            if _private_land(n) or j.work == "mine":
                owner = "proprietors" if _private_land(n) else "stock"
                pay(owner, "rent", rest - profit)
            else:
                pay("labour", "rent", rest - profit)
    pay("stock", "profit", merchant_profit)
    pay("labour", "wages", barter_gain)  # a band's barter profits its people

    # taxes (§14.1–14.2): nominal payer vs actual payer
    nominal = {o: 0.0 for o in rules.ORDERS}
    actual = {o: 0.0 for o in rules.ORDERS}
    collected = 0.0
    rev = n.option("revenue")
    if n.seat == "civil" and rev != "plunder":
        rate = rules.TAX_RATES[n.tax_rate]
        eff = 0.5 + 0.5 * n.budget.get("justice", 0) / 3
        rent = split["rent"] if _private_land(n) or _private_herds(n) else 0.0
        if rev == "feudal_dues":
            levy = rate * income["proprietors"] * 0.5 * eff
            nominal["proprietors"] = levy
            actual["proprietors"], actual["labour"] = 0.4 * levy, 0.6 * levy
        elif rev == "land_tax":
            levy = rate * rent * 0.85 * eff
            nominal["proprietors"] = actual["proprietors"] = levy
        elif rev == "excise":
            levy = rate * income["labour"] * eff
            nominal["labour"] = levy
            keep = 1.0 - clamp(bargaining, 0.0, 1.5) / 1.5
            actual["labour"] = levy * keep
            actual["stock"] = levy * (1 - keep) * 0.7
            actual["proprietors"] = levy * (1 - keep) * 0.3
        elif rev == "tax_farming":
            assessed = rate * produce
            levy = assessed * 0.7 * 0.9 * eff
            for o in rules.ORDERS:
                share = income[o] / produce if produce > 0 else 0.0
                nominal[o] = actual[o] = assessed * 0.9 * share
        elif rev == "customs":
            base = float(tr.get("value", 0.0))
            if n.counters.get("smuggling_until", 0.0) >= world.turn:
                base *= 0.5  # half the goods come in by night
            levy = rate * base * eff
            nominal["stock"] = levy
            actual["stock"] = levy * 0.5
            actual["labour"] = levy * 0.3
            actual["proprietors"] = levy * 0.2
        else:
            levy = 0.0
        for o in rules.ORDERS:
            take = min(income[o], actual[o])
            income[o] -= take
            collected += take
        if rev == "tax_farming":  # the farmers keep 30% of what they collect
            cut = 0.3 * collected
            income["stock"] += cut
            collected -= cut
        n.treasury += collected

    # trade policy (§11.4): tariffs are paid by consumers; tolls and bounties are transfers
    transfers = 0.0
    tariff = float(tr.get("tariff", 0.0))
    if tariff > 0 and n.seat == "civil":
        total_income = sum(max(0.0, v) for v in income.values())
        take_all = min(tariff, total_income)
        for o in rules.ORDERS:
            share = max(0.0, income[o]) / total_income if total_income > 0 else 0.0
            income[o] -= take_all * share
            actual[o] += take_all * share
        nominal["stock"] += take_all
        n.treasury += take_all
        collected += take_all
    tolls = float(tr.get("tolls", 0.0))
    if tolls > 0:
        if n.seat == "civil":
            n.treasury += tolls
        else:
            income["proprietors"] += tolls
            transfers += tolls
    bounty = min(float(tr.get("bounty", 0.0)), n.treasury) if n.seat == "civil" else 0.0
    if bounty > 0:
        n.treasury -= bounty
        income["stock"] += bounty
        transfers += bounty

    tax = {
        "collected": collected,
        "nominal": nominal,
        "actual": actual,
        "tariff": tariff,
        "tolls": tolls,
        "bounty": bounty,
    }

    # order sizes
    size = {
        "proprietors": plan.owners.get("proprietors", 0.0) + n.retainers,
        "stock": plan.owners.get("stock", 0.0),
    }
    size["labour"] = max(0.0, hands - size["proprietors"] - size["stock"])
    owners_only = {
        "labour": size["labour"],
        "proprietors": plan.owners.get("proprietors", 0.0),
        "stock": size["stock"],
    }

    # consumption (§10.2–10.3)
    lux_price = p["luxuries"] * (0.75 if n.mode == "commerce" else 1.0)
    imports = tr.get("imports", {})
    exports = tr.get("exports", {})
    supply = {
        g: max(0.0, made[g] + n.store[g] + float(imports.get(g, 0.0)) - float(exports.get(g, 0.0)))
        for g in rules.GOODS
    }
    want = {o: {g: 0.0 for g in rules.GOODS} for o in rules.ORDERS}
    need = {o: {"food": 0.0, "comfort": 0.0} for o in rules.ORDERS}
    savings = {o: 0.0 for o in rules.ORDERS}
    standing_budget = 0.0
    for o in rules.ORDERS:
        heads = owners_only[o]
        inc = income[o]
        if o == "labour":
            above = max(0.0, inc - rules.LABOUR_SAVE_ABOVE * heads * p["food"])
            save = rules.SAVE_RATE["labour"] * above
        else:
            save = (rules.SAVE_RATE[o] + (0.1 if o == "stock" and n.mode == "commerce" else 0.0)) * inc
        budget = inc - save
        need[o]["food"] = heads
        food_spend = min(budget, heads * p["food"])
        want[o]["food"] = food_spend / p["food"]
        budget -= food_spend
        if o == "labour":
            # labour wants comforts as its pay rises above bare subsistence
            per_head = inc / heads if heads > 0 else 0.0
            eager = clamp((per_head - 0.9 * p["food"]) / (0.6 * p["food"]), 0.0, 1.0)
            need[o]["comfort"] = rules.COMFORT_NEED[o] * heads * eager
        else:
            need[o]["comfort"] = rules.COMFORT_NEED[o] * heads
        ware_spend = min(budget, need[o]["comfort"] * p["wares"])
        want[o]["wares"] = ware_spend / p["wares"]
        budget -= ware_spend
        if o == "proprietors":
            standing_budget = budget
            budget = 0.0
        elif o == "stock":
            lux = min(budget, rules.STOCK_LUXURY_NEED * heads * lux_price)
            want[o]["luxuries"] = lux / lux_price
            budget -= lux
        savings[o] = save + budget

    # standing: retainers or luxuries (§10.2)
    vanity = rules.VANITY_MIN + (rules.VANITY_MAX - rules.VANITY_MIN) * min(
        1.0, n.luxury_turns / rules.VANITY_TURNS
    )
    lux_for_props = max(0.0, supply["luxuries"] - want["stock"]["luxuries"])
    affordable = standing_budget / lux_price if lux_price > 0 else 0.0
    availability = lux_for_props / affordable if affordable > 0 else 0.0
    lux_share = clamp(availability * vanity, 0.0, 1.0)
    want["proprietors"]["luxuries"] = lux_share * affordable
    retainer_budget = standing_budget * (1.0 - lux_share)
    settled = sum(nd.hands for nd in world.nodes_of(n.id))
    target = (
        min(retainer_budget / p["food"], rules.RETAINER_CAP_SHARE * settled) if _private_herds(n) else 0.0
    )
    before = n.retainers
    n.retainers = max(0.0, n.retainers + rules.RETAINER_ADJUST * (target - n.retainers))
    if n.retainers < 0.05:
        n.retainers = 0.0
    unspent_standing = max(0.0, retainer_budget - n.retainers * p["food"])
    savings["proprietors"] += 0.5 * unspent_standing  # the rest is idle display
    if before >= 2.0 and n.retainers < 0.8 * before and "retainers_dismissed" not in n.moments:
        n.moments.append("retainers_dismissed")
        world.emit(
            n.id,
            "moment",
            f"Retainers dismissed: {before - n.retainers:.1f} hands leave the lords' "
            "households for productive work as luxuries replace them.",
            quote=rules.MOMENT_QUOTES["retainers_dismissed"],
        )
    retainer_food = n.retainers  # retainers eat one food each

    # physical allocation: ration each good if demand exceeds supply
    got: dict[str, dict[str, float]] = {o: {g: 0.0 for g in rules.GOODS} for o in rules.ORDERS}
    demand_total = {g: sum(want[o][g] for o in rules.ORDERS) for g in rules.GOODS}
    demand_total["food"] += retainer_food
    ration = {g: (min(1.0, supply[g] / demand_total[g]) if demand_total[g] > 0 else 1.0) for g in rules.GOODS}
    for o in rules.ORDERS:
        for g in rules.GOODS:
            got[o][g] = want[o][g] * ration[g]
    retainers_fed = retainer_food * ration["food"]
    used = {g: demand_total[g] * ration[g] for g in rules.GOODS}
    for g in rules.GOODS:
        n.store[g] = max(0.0, (supply[g] - used[g]) * (1.0 - rules.STORE_DECAY[g]))
    n.luxury_turns = n.luxury_turns + 1 if supply["luxuries"] > 0.1 else max(0, n.luxury_turns - 1)

    # satisfaction and contentment (§10.3)
    for o in rules.ORDERS:
        st = n.orders[o]
        st.size, st.income = size[o], income[o]
        st.share = income[o] / produce if produce > 0 else (1.0 if o == "labour" else 0.0)
        if size[o] <= 0:
            st.contentment, st.satisfaction, st.clout = 50.0, 0.0, 0.0
            continue
        fs = got[o]["food"] / need[o]["food"] if need[o]["food"] > 0 else 1.0
        if o == "proprietors" and n.retainers > 0:
            fs = (got[o]["food"] + retainers_fed) / (need[o]["food"] + retainer_food)
        cs = (
            got[o]["wares"] / need[o]["comfort"]
            if need[o]["comfort"] > 1e-6
            else (1.0 if o != "labour" else 0.6)
        )
        if o == "proprietors":
            spent = got[o]["luxuries"] * lux_price + retainers_fed * p["food"]
            ss = clamp(spent / max(0.5 * income[o], 1e-9), 0.0, 1.0) if income[o] > 0 else 0.0
        elif o == "stock":
            ss = (
                got[o]["luxuries"] / (rules.STOCK_LUXURY_NEED * owners_only[o]) if owners_only[o] > 0 else 1.0
            )
        else:
            ss = 1.0
        fs, cs, ss = clamp(fs, 0, 1), clamp(cs, 0, 1), clamp(ss, 0, 1)
        w1, w2, w3 = rules.TIER_WEIGHTS
        s = (w1 * fs + w2 * cs + w3 * ss) / (w1 + w2 + w3)
        st.food_sat, st.comfort_sat, st.standing_sat, st.satisfaction = fs, cs, ss, s
        st.expectation = clamp(
            st.expectation
            + rules.EXPECT_UP * max(0.0, s - st.expectation)
            - rules.EXPECT_DOWN * max(0.0, st.expectation - s),
            0.0,
            1.0,
        )
        st.contentment = clamp(50.0 + 100.0 * (s - st.expectation) + 40.0 * (s - 0.85), 0.0, 100.0)
        if n.mode == "hunting":
            st.contentment = max(st.contentment, 50.0)

    # accumulation (§9.6–9.7)
    security = security_of(world, n)
    saved = sum(savings.values())
    to_stock = saved * security
    n.hoard += saved - to_stock
    bank = sum(nd.works.count("bank") for nd in world.nodes_of(n.id))
    n.stock = n.stock + to_stock + (0.1 * n.stock * min(bank, 1))
    opportunities = sum(rules.WORKS[w].cost for nd in world.nodes_of(n.id) for w in nd.works)
    new_r = clamp(rules.R0 * math.sqrt((100.0 + opportunities) / (100.0 + n.stock)), *rules.R_CLAMP)
    if n.option("property") == "alienable":
        n.counters["improving"] = n.counters.get("improving", 0.0) + 1.0

    # population (§20): grows with food, shrinks with hunger
    food_need = hands + 0.0
    net_food = made["food"] + float(imports.get("food", 0.0)) - float(exports.get("food", 0.0))
    food_ratio = clamp((net_food + n.store["food"] * 0.5) / food_need, 0.0, 2.0) if food_need > 0 else 1.0
    fed = ration["food"]
    growth = clamp(rules.GROWTH_PER_SURPLUS * (min(food_ratio, 1.6) - 1.0), *rules.GROWTH_CLAMP)
    if fed < 0.999:
        growth = min(growth, -0.3 * (1.0 - fed))
    if hands > 0 and income["labour"] / max(size["labour"], 1e-9) > 1.5 * p["food"]:
        growth += rules.HIGH_WAGE_BONUS
    growth += n.counters.pop("feast_growth", 0.0)
    for nd in world.nodes_of(n.id):
        nd.hands = max(1.0, nd.hands * (1.0 + growth))
    for u in world.units_of(n.id):
        if u.kind in ("band", "horde"):  # armies and traders do not breed
            u.hands = max(1.0, u.hands * (1.0 + growth))

    # prices for next turn (§9.8)
    for g in rules.GOODS:
        d = demand_total[g]
        s_ = supply[g]
        if d <= 0 and s_ <= 0:
            continue
        ratio = (d + 0.01) / (s_ + 0.01)
        target_p = rules.BASE_PRICE[g] * clamp(ratio**rules.PRICE_ELASTICITY, *rules.PRICE_CLAMP)
        p[g] = round(0.5 * p[g] + 0.5 * target_p, 4)
    n.demand = demand_total

    return {
        "produce": produce,
        "sources": sources,
        "split": split,
        "income": income,
        "made": made,
        "tax": tax,
        "savings": saved,
        "to_stock": to_stock,
        "security": security,
        "r": new_r,
        "wage": wage,
        "bargaining": bargaining,
        "growth": growth,
        "food_ratio": food_ratio,
        "ration": ration,
        "retainers": n.retainers,
        "herd_added": herd_added,
        "hands": hands,
        "consumed": used,
        "workforce": workforce,
        "open_jobs": plan.open_jobs,
        "filled_jobs": plan.filled_jobs,
        "lux_share": lux_share,
        "transfers": transfers,
        "node_produce": {k: round(v, 2) for k, v in by_node.items()},
        "trade": {k: v for k, v in tr.items()},
        "supply": supply,
    }


def revenue_estimate(world: World, n: Nation, option: str) -> float:
    """What `option` would have collected last turn at the current rate (§14.1); for
    the Treasury screen and the AI's choice of revenue."""

    L = n.last
    if "income" not in L:
        return 0.0
    rate = rules.TAX_RATES[n.tax_rate]
    eff = 0.5 + 0.5 * n.budget.get("justice", 0) / 3
    income, split, produce = L["income"], L["split"], float(L["produce"])
    rent = float(split.get("rent", 0.0)) if _private_land(n) or _private_herds(n) else 0.0
    routes = sum(rt.capacity for rt in world.routes.values() if n.id in (rt.a, rt.b)) * 2.0
    return {
        "feudal_dues": rate * float(income.get("proprietors", 0.0)) * 0.5 * eff,
        "land_tax": rate * rent * 0.85 * eff,
        "excise": rate * float(income.get("labour", 0.0)) * eff,
        "tax_farming": rate * produce * 0.9 * 0.7,
        "customs": rate * routes * eff,
    }.get(option, 0.0)


def spend_budget(world: World, n: Nation) -> dict[str, float]:
    """The state's spending lines (§14.3), cut back to what the Treasury can pay."""

    if n.seat != "civil":
        return {}
    hands = world.hands_of(n.id)
    costs = {
        "justice": rules.JUSTICE_COST_PER_10_HANDS * hands / 10.0,
        "instruction": rules.INSTRUCTION_COST_PER_10_HANDS * hands / 10.0,
        "court": rules.COURT_COST,
    }
    spent: dict[str, float] = {}
    for line in rules.BUDGET_LINES:
        level = n.budget.get(line, 0)
        while level > 0 and costs[line] * level > n.treasury:
            level -= 1
        n.budget[line] = level
        spent[line] = costs[line] * level
        n.treasury -= spent[line]
    return spent
