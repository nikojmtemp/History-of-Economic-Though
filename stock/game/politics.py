"""Orders, Sway, the Seat, institutions, demands, unrest (design doc §6, §7, §10.4, §13, §18)."""

from __future__ import annotations

import math

from stock.game import rules
from stock.game.economy import clamp, has_stupefaction
from stock.game.state import Decision, Nation, World

# --- clout (§6.2) --------------------------------------------------------------------------


def organisation(n: Nation, order: str) -> float:
    if order != "labour":
        return 1.0
    org = 0.3
    if n.seat == "civil":
        org += 0.1 * n.budget.get("justice", 0) + 0.05 * n.budget.get("instruction", 0)
    if n.option("labour") == "poor_laws":
        org += 0.1
    return org


def update_clout(n: Nation) -> None:
    total_income = sum(max(0.0, n.orders[o].income) for o in rules.ORDERS)
    total_size = sum(n.orders[o].size for o in rules.ORDERS)
    raw: dict[str, float] = {}
    for o in rules.ORDERS:
        st = n.orders[o]
        if st.size <= 0:
            raw[o] = 0.0
            continue
        wealth = st.income / total_income if total_income > 0 else 0.0
        heads = st.size / total_size if total_size > 0 else 0.0
        raw[o] = 0.7 * wealth + 0.3 * heads * organisation(n, o)
        if o == "proprietors" and n.mode == "agriculture" and n.retainers > 0:
            raw[o] *= 1.5
    s = sum(raw.values())
    for o in rules.ORDERS:
        n.orders[o].clout = raw[o] / s if s > 0 else (1.0 if o == "labour" else 0.0)


# --- sway (§7.1) ---------------------------------------------------------------------------


def sway_income(world: World, n: Nation) -> dict[str, float]:
    parts: dict[str, float] = {}
    backing = sum(n.orders[o].clout * (n.orders[o].contentment - 50.0) / 25.0 for o in rules.ORDERS)
    if n.seat == "council":
        parts["base"] = 2.0
        parts["bands"] = 0.5 * sum(1 for u in world.units_of(n.id))
        parts["backing"] = backing
    elif n.seat == "chiefdom":
        parts["base"] = 2.0
        herds = world.herds_of(n.id)
        parts["prestige"] = min(4.0, math.log1p(herds) / 2.0)
        parts["backing"] = backing
    elif n.seat == "civil":
        parts["base"] = 3.0
        parts["backing"] = 1.5 * backing
        parts["court"] = 2.0 * n.budget.get("court", 0)
        parts["justice"] = 0.5 * n.budget.get("justice", 0)
    else:  # interregnum
        parts["base"] = 1.0
        parts["loyal"] = max(0.0, max(n.orders[o].contentment for o in rules.ORDERS) - 50.0) / 25.0
    if n.retainers > 0 and n.seat in ("chiefdom", "civil"):
        parts["retainers"] = -0.5 * math.log1p(n.retainers)
    return parts


# --- institutions (§13) ---------------------------------------------------------------------


def institution_cost(n: Nation, pillar: str, option: str) -> float:
    o = rules.PILLARS[pillar].option(option)
    current = rules.PILLARS[pillar].option(n.option(pillar))
    supporters = set(o.supports) | set(current.opposes)
    opponents = set(o.opposes) | set(current.supports)
    opp = sum(n.orders[x].clout for x in opponents if x not in supporters)
    sup = sum(n.orders[x].clout for x in supporters if x not in opponents)
    cost = max(0.0, 10.0 + 30.0 * opp - 10.0 * sup)
    if n.knows("liberty"):
        cost *= 0.75
    if pillar == "property" and option == "herds" and n.option("property") == "killer":
        cost *= 0.5
    return round(cost, 1)


def institution_blocker(n: Nation, pillar: str, option: str) -> str | None:
    """Why this option can't be chosen now, or None."""

    if pillar not in rules.PILLARS:
        return "no such pillar"
    try:
        o = rules.PILLARS[pillar].option(option)
    except KeyError:
        return "no such option"
    if n.option(pillar) == option:
        return "already in force"
    if pillar in n.pending_institutions:
        return "a change is already under way"
    if n.pillar_cooldown.get(pillar, 0) > 0:
        return f"changed recently ({n.pillar_cooldown[pillar]} turns)"
    if not n.knows(o.needs):
        return f"needs {rules.DISCOVERIES[o.needs].name}" if o.needs else "locked"
    if o.state_only and n.seat != "civil":
        return "needs Civil Government"
    if n.seat == "council" and pillar in ("revenue", "commerce") and option not in ("plunder", "barter"):
        return "needs a chiefdom or state"
    if option == "killer" and n.seat != "council":
        return "a band custom"
    return None


def apply_pending_institutions(world: World, n: Nation) -> None:
    for pillar, option in list(n.pending_institutions.items()):
        n.institutions[pillar] = option
        n.pillar_cooldown[pillar] = rules.INSTITUTION_COOLDOWN
        world.emit(
            n.id,
            "institution",
            f"{rules.PILLARS[pillar].name}: {rules.PILLARS[pillar].option(option).name} is now in force.",
        )
    n.pending_institutions.clear()
    for k in list(n.pillar_cooldown):
        n.pillar_cooldown[k] = max(0, n.pillar_cooldown[k] - 1)
    # options that no longer fit the seat fall back
    if n.seat != "civil":
        if rules.PILLARS["revenue"].option(n.option("revenue")).state_only:
            n.institutions["revenue"] = "plunder"
        if n.option("defence") == "standing":
            n.institutions["defence"] = "warriors"


# --- the seat (§7) ---------------------------------------------------------------------------


def update_seat(world: World, n: Nation) -> None:
    has_props = n.orders["proprietors"].size > 0
    if n.seat == "council" and has_props:
        n.seat = "chiefdom"
        world.emit(
            n.id,
            "seat",
            "Herds and land now have owners. The council becomes a chiefdom: Sway now "
            "comes from the chief's prestige.",
        )
    elif n.seat == "civil" and n.sway <= 0.0:
        revolting = [o for o in rules.ORDERS if n.orders[o].contentment < 20 and n.orders[o].clout >= 0.3]
        if revolting:
            n.seat = "interregnum"
            world.emit(
                n.id,
                "seat",
                f"Government collapses: {rules.ORDER_NAMES[revolting[0]]} will not obey. "
                "Taxes stop; you keep the chiefdom's powers until you Restore.",
            )
            apply_pending_institutions(world, n)


# --- unrest (§10.4) ---------------------------------------------------------------------------


def update_unrest(world: World, n: Nation) -> None:
    labour = n.orders["labour"]
    stupor = 0.0
    if has_stupefaction(world, n):
        dol = float(n.last.get("dol", 1.0))
        stupor = (dol - 2.0) * 5.0 * (1.0 - n.budget.get("instruction", 0) / 3.0)
        if any("academy" in nd.works for nd in world.nodes_of(n.id)):
            stupor *= 0.5
    tax = rules.TAX_UNREST[n.tax_rate] if n.seat == "civil" and n.option("revenue") != "plunder" else 0.0
    if n.option("revenue") == "tax_farming":
        tax += 10.0
    hunger = max(0.0, 1.0 - labour.food_sat) * 100.0
    target = clamp(
        max(0.0, 50.0 - labour.contentment) * 1.5 + hunger + stupor + tax - 5.0 * n.budget.get("justice", 0),
        0.0,
        100.0,
    )
    hands = world.hands_of(n.id)
    for nd in world.nodes_of(n.id):
        before = nd.unrest
        nd.unrest = clamp(0.7 * nd.unrest + 0.3 * target, 0.0, 100.0)
        big_enough = (
            nd.hands >= rules.UNREST_EVENT_MIN_HANDS and nd.hands >= rules.UNREST_EVENT_MIN_SHARE * hands
        )
        if big_enough and before <= 70 < nd.unrest:
            world.emit(n.id, "riot", f"Riots in {nd.name}: output halved until unrest falls below 70.", nd.id)


# --- demands (§18) -----------------------------------------------------------------------------


def maybe_demand(world: World, n: Nation) -> None:
    if any(d.kind == "demand" for d in n.decisions):
        return
    for o in rules.ORDERS:
        st = n.orders[o]
        if st.size <= 0 or st.contentment >= 35 or st.clout < 0.25:
            continue
        wanted = []
        for pk, pillar in rules.PILLARS.items():
            for opt in pillar.options:
                if o in opt.supports and institution_blocker(n, pk, opt.key) is None:
                    wanted.append((pk, opt))
        if not wanted:
            continue
        pk, opt = world.rng.choice(wanted)
        name = rules.ORDER_NAMES[o]
        n.decisions.append(
            Decision(
                id=world.new_id("d"),
                kind="demand",
                title=f"{name} demand {opt.name}",
                text=f"{name} (clout {st.clout:.0%}, contentment {st.contentment:.0f}) demand "
                f"{rules.PILLARS[pk].name}: {opt.name}. {opt.effect}",
                choices=[
                    {"key": "grant", "label": "Grant", "effect": "Enacted at no Sway cost next turn."},
                    {"key": "refuse", "label": "Refuse", "effect": f"Sway -10; {name} contentment -10."},
                ],
                data={"order": o, "pillar": pk, "option": opt.key},
            )
        )
        return


def resolve_decision(world: World, n: Nation, decision_id: str, choice: str) -> str | None:
    d = next((x for x in n.decisions if x.id == decision_id), None)
    if d is None:
        return "no such decision"
    if choice not in {c["key"] for c in d.choices}:
        return "no such choice"
    if d.kind == "demand":
        order, pillar, option = d.data["order"], d.data["pillar"], d.data["option"]
        if choice == "grant":
            if institution_blocker(n, pillar, option) is None:
                n.pending_institutions[pillar] = option
            n.orders[order].contentment = clamp(n.orders[order].contentment + 15, 0, 100)
        else:
            n.sway = max(0.0, n.sway - 10.0)
            n.orders[order].contentment = clamp(n.orders[order].contentment - 10, 0, 100)
    n.decisions.remove(d)
    return None
