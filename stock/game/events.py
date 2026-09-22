"""Events and decisions (design doc §18): the world's surprises, each a card with
choices and what each would do. Demands live in politics; these are the rest.

An event decision carries the AI's own pick in `data["ai"]`, so rivals answer
the same cards the player does, the same way the player could.
"""

from __future__ import annotations

from typing import Any

from stock.game import rules
from stock.game.economy import clamp
from stock.game.state import Decision, Nation, Unit, World

# chance per nation per turn
HARVEST_FAILURE = 0.04
PLAGUE = 0.006  # doubled at most by trade: routes carry disease
WORKMAN = 0.03
ENCLOSURE = 0.03
SMUGGLING = 0.20
COLONISTS = 0.10
HERDS_MIGRATE = 0.02  # per world per turn
PATENT_TURNS = 10
PUBLISH_INGENUITY = 20.0
SMUGGLING_TURNS = 5


def _card(
    world: World,
    n: Nation,
    event: str,
    title: str,
    text: str,
    choices: list[dict[str, str]],
    ai: str,
    **data: Any,
) -> None:
    n.decisions.append(
        Decision(
            id=world.new_id("d"),
            kind="event",
            title=title,
            text=text,
            choices=choices,
            data={"event": event, "ai": ai, **data},
        )
    )


def roll(world: World, n: Nation) -> None:
    """At most one new event card per nation per turn."""

    if world.turn < 15 or any(d.kind == "event" for d in n.decisions):
        return
    r = world.rng.random
    for check in (_harvest, _plague, _workman, _enclosure, _smuggling, _bank, _colonists):
        if check(world, n, r()):
            return


def world_events(world: World) -> None:
    if world.rng.random() >= HERDS_MIGRATE:
        return
    herds = [nd for nd in world.nodes.values() if "wild_herds" in nd.features]
    open_ground = [
        nd
        for nd in world.nodes.values()
        if nd.terrain in ("GRASSLAND", "HILLS") and "wild_herds" not in nd.features
    ]
    if not herds or not open_ground:
        return
    old, new = world.rng.choice(herds), world.rng.choice(open_ground)
    old.features.remove("wild_herds")
    new.features.append("wild_herds")
    for n in world.nations.values():
        if n.alive and (old.id in n.explored or new.id in n.explored):
            world.emit(n.id, "herds", f"The wild herds leave {old.name} and appear at {new.name}.", new.id)


# --- the cards --------------------------------------------------------------------------------


def _harvest(world: World, n: Nation, r: float) -> bool:
    fields = [nd for nd in world.nodes_of(n.id) if "fields" in nd.works]
    if r >= HARVEST_FAILURE or not fields:
        return False
    nd = world.rng.choice(fields)
    loss = round(0.3 * float(n.last.get("made", {}).get("food", 0.0)), 1)
    n.store["food"] = max(0.0, n.store["food"] - loss)
    p = n.prices["food"]
    if n.seat != "civil":
        world.emit(n.id, "harvest", f"The harvest fails at {nd.name}: {loss:.0f} food lost.", nd.id)
        return True
    cost = round(loss * p * 1.5, 1)
    relief = round(loss * p, 1)
    ai = "import" if n.treasury >= cost else "relief" if n.treasury >= relief else "cap"
    _card(
        world,
        n,
        "harvest",
        f"The harvest fails at {nd.name}",
        f"Blight at {nd.name}: {loss:.0f} food is lost and bread will be dear.",
        [
            {
                "key": "import",
                "label": "Open the grain trade",
                "effect": f"Buy {loss:.0f} food abroad: {cost:.0f} Treasury.",
            },
            {
                "key": "cap",
                "label": "Cap the price",
                "effect": "Bread stays cheap this turn: Labour content +5, Proprietors -10; "
                "growers sell less.",
            },
            {
                "key": "relief",
                "label": "Relief",
                "effect": f"{relief:.0f} Treasury to feed the hungry: half the loss made good, "
                "Labour content +10.",
            },
        ],
        ai,
        loss=loss,
        cost=cost,
        relief=relief,
        node=nd.id,
    )
    return True


def _plague(world: World, n: Nation, r: float) -> bool:
    routes = sum(1 for x in world.routes.values() if n.id in (x.a, x.b))
    if r >= PLAGUE * (1 + min(routes, 8) / 8) or world.turn < 20:
        return False
    share = world.rng.uniform(0.10, 0.25)
    for nd in world.nodes_of(n.id):
        nd.hands = max(1.0, nd.hands * (1 - share))
    for u in world.units_of(n.id):
        if u.hands > 0:
            u.hands = max(0.5, u.hands * (1 - share))
    world.emit(n.id, "plague", f"Plague: {share:.0%} of our people die. Hands are scarce; wages will rise.")
    return True


def _workman(world: World, n: Nation, r: float) -> bool:
    sites = [nd for nd in world.nodes_of(n.id) if "workshop" in nd.works or "manufactory" in nd.works]
    if r >= WORKMAN or not sites:
        return False
    nd = world.rng.choice(sites)
    ai = "patent" if n.orders["stock"].clout >= 0.3 else "publish"
    _card(
        world,
        n,
        "workman",
        "An ingenious workman",
        f"A workman at {nd.name} has contrived a better way of working.",
        [
            {
                "key": "patent",
                "label": "Patent",
                "effect": f"His masters keep it: the works at {nd.name} produce 30% more for "
                f"{PATENT_TURNS} turns; Stock-holders content +10.",
            },
            {
                "key": "publish",
                "label": "Publish",
                "effect": f"Everyone may use it: Ingenuity +{PUBLISH_INGENUITY:.0f} for us, "
                "and a little for every people we trade with.",
            },
        ],
        ai,
        node=nd.id,
    )
    return True


def _enclosure(world: World, n: Nation, r: float) -> bool:
    if r >= ENCLOSURE or n.option("property") != "alienable" or not n.knows("taming"):
        return False
    fields = [nd for nd in world.nodes_of(n.id) if nd.works.count("fields") >= 2 and nd.t.grazing > 0]
    if not fields:
        return False
    nd = world.rng.choice(fields)
    ai = "enclose" if n.orders["proprietors"].clout > n.orders["labour"].clout else "refuse"
    _card(
        world,
        n,
        "enclosure",
        "A petition to enclose",
        f"The landowners of {nd.name} petition to enclose the common fields for sheep.",
        [
            {
                "key": "enclose",
                "label": "Enclose",
                "effect": f"Fields at {nd.name} become pasture: fewer hands needed, "
                "Proprietors content +10, unrest there +20.",
            },
            {"key": "refuse", "label": "Refuse", "effect": "The fields stay; Proprietors content -10."},
        ],
        ai,
        node=nd.id,
    )
    return True


def _smuggling(world: World, n: Nation, r: float) -> bool:
    if r >= SMUGGLING or n.seat != "civil" or n.option("revenue") != "customs" or n.tax_rate != "heavy":
        return False
    _card(
        world,
        n,
        "smuggling",
        "Smugglers",
        "Heavy customs have made smuggling pay: goods slip past the collectors.",
        [
            {
                "key": "crack",
                "label": "Crack down",
                "effect": "10 Treasury on revenue officers; justice raised a level.",
            },
            {"key": "lower", "label": "Lower the rate", "effect": "Customs to moderate: less to smuggle."},
            {
                "key": "ignore",
                "label": "Ignore it",
                "effect": f"Customs bring in half for {SMUGGLING_TURNS} turns.",
            },
        ],
        "lower",
    )
    return True


def _bank(world: World, n: Nation, r: float) -> bool:
    if not any("bank" in nd.works for nd in world.nodes_of(n.id)):
        n.counters["boom"] = 0.0
        return False
    growth = float(n.last.get("to_stock", 0.0)) / max(n.stock, 1.0)
    n.counters["boom"] = n.counters.get("boom", 0.0) + 1 if growth > 0.15 else 0.0
    if n.counters["boom"] < 3:
        return False
    n.counters["boom"] = 0.0
    lost = round(0.2 * n.stock, 1)
    n.stock -= lost
    bail = round(min(n.treasury, 0.5 * lost), 1)
    ai = "bailout" if bail > 0 and n.seat == "civil" else "fail"
    _card(
        world,
        n,
        "bank",
        "The banks stop payment",
        f"After three years of easy credit, the banks fail: {lost:.0f} of Stock is lost.",
        [
            {
                "key": "bailout",
                "label": "Bail them out",
                "effect": f"{bail:.0f} Treasury restores part of the Stock; Stock-holders content +10.",
            },
            {"key": "fail", "label": "Let them fail", "effect": "Stock-holders content -20."},
        ],
        ai,
        bail=bail,
    )
    return True


def _colonists(world: World, n: Nation, r: float) -> bool:
    ports = [nd for nd in world.nodes_of(n.id) if "port" in nd.works]
    if r >= COLONISTS or not n.knows("navigation") or not ports or n.orders["labour"].contentment >= 40:
        return False
    _card(
        world,
        n,
        "colonists",
        "Colonists petition",
        "Discontented families ask for a charter to settle beyond the sea.",
        [
            {
                "key": "charter",
                "label": "Charter a colony",
                "effect": "A band of 2 hands sets out from our port; Labour content +10.",
            },
            {"key": "refuse", "label": "Refuse", "effect": "Nothing changes."},
        ],
        "charter",
        node=ports[0].id,
    )
    return True


# --- choices ------------------------------------------------------------------------------------


def resolve(world: World, n: Nation, d: Decision, choice: str) -> None:
    ev, data = d.data["event"], d.data
    orders = n.orders

    def content(order: str, delta: float) -> None:
        orders[order].contentment = clamp(orders[order].contentment + delta, 0.0, 100.0)

    if ev == "harvest":
        if choice == "import" and n.treasury >= data["cost"]:
            n.treasury -= data["cost"]
            n.store["food"] += data["loss"]
        elif choice == "relief" and n.treasury >= data["relief"]:
            n.treasury -= data["relief"]
            n.store["food"] += data["loss"] / 2
            content("labour", 10)
        else:  # the cap
            n.prices["food"] = min(n.prices["food"], rules.BASE_PRICE["food"])
            content("labour", 5)
            content("proprietors", -10)
    elif ev == "workman":
        if choice == "patent":
            n.counters[f"patent:{data['node']}"] = float(world.turn + PATENT_TURNS)
            content("stock", 10)
        else:
            n.research_progress += PUBLISH_INGENUITY
            for other in world.nations.values():
                if other.id != n.id and any({x.a, x.b} == {n.id, other.id} for x in world.routes.values()):
                    other.research_progress += PUBLISH_INGENUITY / 4
    elif ev == "enclosure":
        nd = world.nodes[data["node"]]
        if choice == "enclose" and "fields" in nd.works:
            nd.works[nd.works.index("fields")] = "pasture"
            nd.herds += rules.TAME_HERDS
            nd.unrest = clamp(nd.unrest + 20, 0.0, 100.0)
            content("proprietors", 10)
            world.emit(n.id, "enclosure", f"{nd.name} is enclosed: fields become pasture.", nd.id)
        else:
            content("proprietors", -10)
    elif ev == "smuggling":
        if choice == "crack" and n.treasury >= 10:
            n.treasury -= 10
            n.budget["justice"] = min(3, n.budget.get("justice", 0) + 1)
        elif choice == "lower":
            n.tax_rate = "moderate"
        else:
            n.counters["smuggling_until"] = float(world.turn + SMUGGLING_TURNS)
    elif ev == "bank":
        if choice == "bailout":
            paid = min(n.treasury, float(data["bail"]))
            n.treasury -= paid
            n.stock += paid
            content("stock", 10)
        else:
            content("stock", -20)
    elif ev == "colonists" and choice == "charter":
        home = max(world.nodes_of(n.id), key=lambda x: x.hands, default=None)
        port = world.nodes.get(data["node"])
        if home is not None and port is not None and port.owner == n.id and home.hands > 3:
            home.hands -= 2.0
            uid = world.new_id("u")
            world.units[uid] = Unit(uid, n.id, "band", port.id, 2.0, moves_left=0)
            content("labour", 10)
            world.emit(n.id, "colony", f"Colonists gather at {port.name}, ready to sail.", port.id)
