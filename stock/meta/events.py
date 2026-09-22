"""Exogenous events (step 13b; Doc 05).

Six probability rolls per year, never triggered by the simulation's own state:
plague, harvest failure, the Watt event (unlocks MACHINERY_STEAM via
`meta/trees.py`'s gate), a trade fair becoming a town, a new ore or coal find, and
wild herds migrating into a location. Each applies its effect through an existing
field of the module it touches — no new bespoke mechanics.
"""

from __future__ import annotations

from stock.core.params import EventParams
from stock.core.producers import MethodId, ProducerKind
from stock.core.records import DERIVED_SIZE_CLASSES, ClassId, Record
from stock.core.world import Location, Nation, World
from stock.sim.ledger import EventRecord


def _roll(world: World, prob: float) -> bool:
    return bool(world.rng.random() < prob)


def _emit(world: World, nation_id: str, kind: str, numbers: dict[str, float]) -> None:
    if world.ledger is not None:
        world.ledger.add_event(EventRecord(year=world.year, nation=nation_id, kind=kind, numbers=numbers))


def _plague(loc: Location, nation: Nation, world: World, p: EventParams) -> None:
    if not _roll(world, p.plague_prob):
        return
    for r in loc.records:
        # RETAINERS/SERVANTS' size is derived solely from their masters' Attendance
        # spend (`set_size`'s guard; `engine.consumption.attendance_to_dependents`)
        # — shrinking them here directly would desync that invariant until the next
        # dismissal. Their masters shrink like everyone else, which naturally carries
        # through to a smaller derived size next year.
        if r.cls in DERIVED_SIZE_CLASSES:
            continue
        r.size = max(0.0, r.size * (1.0 - p.plague_shrink))
    nation.flags.add(f"plague:{world.year}")
    _emit(world, nation.id, "plague", {"location": float(hash(loc.id) % 1000), "shrink": p.plague_shrink})


def _harvest_failure(loc: Location, nation: Nation, world: World, p: EventParams) -> None:
    if not loc.resources.arable or not _roll(world, p.harvest_failure_prob):
        return
    lost = 0.0
    for producer in loc.producers:
        if producer.kind is ProducerKind.FIELD:
            cut = producer.stock_in_place * p.harvest_failure_loss
            producer.stock_in_place = max(0.0, producer.stock_in_place - cut)
            lost += cut
    if lost > 0:
        _emit(world, nation.id, "harvest_failure", {"location": float(hash(loc.id) % 1000), "lost": lost})


def _watt(nation: Nation, world: World, p: EventParams) -> None:
    if "watt" in world.flags:
        return
    if not nation.tree2.production[MethodId.MACHINE_PRODUCTION].lit:
        return
    if not _roll(world, p.watt_prob):
        return
    world.flags.add("watt")
    _emit(world, nation.id, "watt", {})


def _trade_fair(loc: Location, nation: Nation, world: World, p: EventParams) -> None:
    if loc.is_town() or not _roll(world, p.trade_fair_prob):
        return
    merchants = loc.record(ClassId.MERCHANTS)
    if merchants is None:
        merchants = Record(cls=ClassId.MERCHANTS, location=loc.id)
        loc.records.append(merchants)
    merchants.size += p.trade_fair_merchants_added
    _emit(
        world,
        nation.id,
        "trade_fair",
        {"location": float(hash(loc.id) % 1000), "merchants_added": p.trade_fair_merchants_added},
    )


def _ore_or_coal_find(loc: Location, nation: Nation, world: World, p: EventParams) -> None:
    if not loc.resources.ore and _roll(world, p.ore_find_prob):
        loc.resources.ore = True
        loc.resources.ore_yield = max(loc.resources.ore_yield, p.ore_find_yield)
        _emit(world, nation.id, "ore_find", {"location": float(hash(loc.id) % 1000)})
    if not loc.resources.coal and _roll(world, p.coal_find_prob):
        loc.resources.coal = True
        loc.resources.coal_yield = max(loc.resources.coal_yield, p.coal_find_yield)
        _emit(world, nation.id, "coal_find", {"location": float(hash(loc.id) % 1000)})


def _wild_herds(loc: Location, nation: Nation, world: World, p: EventParams) -> None:
    if not _roll(world, p.wild_herds_prob):
        return
    loc.resources.game = True
    loc.resources.game_yield += p.wild_herds_game_yield
    _emit(world, nation.id, "wild_herds", {"location": float(hash(loc.id) % 1000)})


def step_events(world: World) -> None:
    """Step 13b: rolls each of the six events for every living nation's locations."""

    if world.params is None or world.rng is None:
        return
    p = world.params.event

    for nation in world.nations.values():
        if nation.ended:
            continue
        _watt(nation, world, p)
        for loc in nation.locations(world):
            _plague(loc, nation, world, p)
            _harvest_failure(loc, nation, world, p)
            _trade_fair(loc, nation, world, p)
            _ore_or_coal_find(loc, nation, world, p)
            _wild_herds(loc, nation, world, p)
