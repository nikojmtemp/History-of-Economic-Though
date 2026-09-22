"""Population — year step 8a (DD §2.3; MM §1)."""

from __future__ import annotations

from stock.core.params import Params
from stock.core.records import DERIVED_SIZE_CLASSES, ClassId, Record, quantise_move, set_size
from stock.core.world import Location, Nation, World
from stock.sim.ledger import EventRecord


def population_update(record: Record, params: Params) -> None:
    """`size' = size*(1+beta*(A_subs-1)) - m*size*max(0,1-A_subs)^2` (MM §1), with the
    growth term clamped at `max_growth` (a class never grows faster than that
    however large its surplus). Dependent (derived-size) records are excluded —
    their size is set by the Attendance purchase, not this rule (DD §2.3)."""

    if record.cls in DERIVED_SIZE_CLASSES or record.cls is ClassId.STATE:
        return
    p = params.population
    a_subs = record.A.subsistence
    growth = min(p.max_growth, p.beta * (a_subs - 1.0))
    mortality = p.mortality_m * max(0.0, 1.0 - a_subs) ** 2
    new_size = record.size * (1.0 + growth) - mortality * record.size
    set_size(record, max(0.0, new_size))


def _vertical_down_neighbour(cls: ClassId) -> ClassId | None:
    """Returns the class that absorbs wealth when this class goes extinct (DD §2.4 vertical down)."""
    vertical_down = {
        ClassId.HERD_OWNERS: ClassId.HERDSMEN,
        ClassId.LANDLORDS: ClassId.TENANTS,
        ClassId.CAPITALISTS: ClassId.CRAFTSMEN,
        ClassId.MERCHANTS: ClassId.CRAFTSMEN,
        ClassId.CRAFTSMEN: ClassId.LABOURERS,
        ClassId.TENANTS: ClassId.LABOURERS,
    }
    return vertical_down.get(cls)


def reap_extinct_records(location: Location, world: World, nation: Nation | None = None) -> None:
    """Folds extinct records into their vertical-down neighbours (or the largest live
    record if no neighbour exists): the last few people, their wealth and their
    ownership shares all go to the recipient. An extinct record has
    `0 < size < extinct_size_epsilon` (one person, by default) — or is empty but
    still holds wealth or shares. Emits a record_extinct event if ledger is
    available (DD §2.4, task defect F)."""

    params = world.params
    extinct_threshold = params.population.extinct_size_epsilon
    records_to_reap = []

    # Identify extinct records
    for record in location.records:
        if record.size >= extinct_threshold:
            continue
        if record.cls in DERIVED_SIZE_CLASSES or record.cls is ClassId.STATE:
            continue
        if record.size <= 0:
            wealth_total = record.wealth.total()
            if wealth_total <= 0 and record.wealth.herd <= 0:
                # Check if record has ownership shares
                has_ownership = False
                for producer in location.producers:
                    if record.cls in producer.owners_stock or record.cls in producer.owners_land:
                        has_ownership = True
                        break
                if not has_ownership:
                    continue
        records_to_reap.append(record)

    if not records_to_reap:
        return

    # Find recipient classes: prefer vertical-down, else largest live record
    def get_recipient(extinct_cls: ClassId) -> ClassId | None:
        down = _vertical_down_neighbour(extinct_cls)
        if down is not None:
            recipient = location.record(down)
            if recipient is not None and recipient.size >= extinct_threshold:
                return down
        # Fallback to largest record at location
        largest = None
        largest_size = 0.0
        for r in location.records:
            if r.cls not in DERIVED_SIZE_CLASSES and r.size >= extinct_threshold and r.size > largest_size:
                largest = r.cls
                largest_size = r.size
        return largest

    # Reap each extinct record
    from stock.engine.capital import sync_record_wealth

    for extinct_record in records_to_reap:
        recipient_cls = get_recipient(extinct_record.cls)
        if recipient_cls is None:
            # Nobody left here to fold into: the last few people walk to the
            # nation's most populous other location, keeping their class and
            # taking what travels (herd, hoard...; land and stock stay put, as in
            # any cross-location move). A nation with nowhere to go keeps them.
            _fold_into_another_location(extinct_record, location, world, nation, extinct_threshold)
            continue
        recipient = location.record(recipient_cls)
        if recipient is None:
            recipient = Record(cls=recipient_cls, location=location.id)
            location.records.append(recipient)

        # Special handling: if extinct record holds herd and receiver is not a herding class,
        # move herd to HERDSMEN instead (per DD §5.3 herd custody)
        # A herd too small to occupy one custodian (herd/h below the extinct threshold)
        # goes with the rest of the wealth instead: the custody path would otherwise
        # fabricate a dust-sized HERDSMEN record every year (see DEVIATIONS.md A30).
        herd_needs_custody = (
            extinct_record.wealth.herd / params.production.head_per_herdsman >= extinct_threshold
        )
        if (
            extinct_record.wealth.herd > 0
            and herd_needs_custody
            and recipient_cls not in (ClassId.HERD_OWNERS, ClassId.HERDSMEN)
        ):
            # Find or create HERDSMEN record
            herdsmen = location.record(ClassId.HERDSMEN)
            if herdsmen is None:
                herdsmen = Record(cls=ClassId.HERDSMEN, location=location.id)
                location.records.append(herdsmen)
            # Move herd to herdsmen
            herdsmen.wealth.herd += extinct_record.wealth.herd
            # Move some persons from recipient to herdsmen for herd custody
            herd_custody_share = params.population.herd_custody_share
            moved = min(
                recipient.size * herd_custody_share,
                extinct_record.wealth.herd / params.production.head_per_herdsman,
            )
            moved = quantise_move(recipient.size, moved, extinct_threshold)
            if moved > 0:
                set_size(recipient, recipient.size - moved)
                set_size(herdsmen, herdsmen.size + moved, allow_derived=False)
            # Clear herd from extinct record so it doesn't get transferred again
            extinct_record.wealth.herd = 0.0

        # Transfer wealth
        recipient.wealth.herd += extinct_record.wealth.herd
        recipient.wealth.land_shares += extinct_record.wealth.land_shares
        recipient.wealth.fixed_assets += extinct_record.wealth.fixed_assets
        recipient.wealth.hoard += extinct_record.wealth.hoard
        recipient.wealth.bonds += extinct_record.wealth.bonds
        recipient.wealth.tools += extinct_record.wealth.tools
        recipient.wealth.loans_out += extinct_record.wealth.loans_out
        recipient.debt += extinct_record.debt

        # Transfer ownership shares
        for producer in location.producers:
            if extinct_record.cls in producer.owners_stock:
                share = producer.owners_stock.pop(extinct_record.cls)
                producer.owners_stock[recipient_cls] = producer.owners_stock.get(recipient_cls, 0.0) + share
            if extinct_record.cls in producer.owners_land:
                share = producer.owners_land.pop(extinct_record.cls)
                producer.owners_land[recipient_cls] = producer.owners_land.get(recipient_cls, 0.0) + share

        # Emit event if ledger available
        if world.ledger is not None:
            event = EventRecord(
                year=world.year,
                nation=location.nation or "",
                kind="record_extinct",
                numbers={
                    "size": extinct_record.size,
                    "wealth_total": extinct_record.wealth.total(),
                    "herd": extinct_record.wealth.herd,
                },
            )
            world.ledger.add_event(event)

        # The last few people go with their wealth (one person is the smallest unit
        # that works a job — see `PopulationParams.extinct_size_epsilon`).
        reaped_size = extinct_record.size
        set_size(recipient, recipient.size + reaped_size)
        set_size(extinct_record, 0.0)
        extinct_record.wealth = Record(cls=extinct_record.cls, location=location.id).wealth
        extinct_record.debt = 0.0
        if nation is not None:
            nation.add_flow("reaped", reaped_size)

    # Sync wealth after transfers
    sync_record_wealth(location, params)


def _fold_into_another_location(
    extinct_record: Record, location: Location, world: World, nation: Nation | None, threshold: float
) -> None:
    if nation is None or extinct_record.size <= 0:
        return
    from stock.engine.mobility import _move_wealth_share

    candidates = [
        loc
        for loc in nation.locations(world)
        if loc is not location and sum(r.size for r in loc.records) >= threshold
    ]
    if not candidates:
        return
    destination = max(candidates, key=lambda loc: sum(r.size for r in loc.records))
    target = destination.record(extinct_record.cls)
    if target is None:
        target = Record(cls=extinct_record.cls, location=destination.id)
        destination.records.append(target)
    moved = _move_wealth_share(extinct_record, target, 1.0, 0.0)
    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=nation.id,
                kind="record_extinct",
                numbers={"size": moved, "wealth_total": target.wealth.total(), "herd": target.wealth.herd},
            )
        )
    nation.add_flow("reaped", moved)


def step_population(world: World) -> None:
    for nation in world.nations.values():
        for location in nation.locations(world):
            for record in location.records:
                old_size = record.size
                population_update(record, world.params)
                size_change = record.size - old_size
                nation.add_flow("births_deaths", size_change)
            reap_extinct_records(location, world, nation)


def sweep_dust(world: World) -> None:
    """Late-year pass of `reap_extinct_records` over every location: casualties (step
    13), plague (13b) and dismissals leave sub-person records behind after step 8a
    has run, and nothing below one person should be working a producer when step 1
    comes round again."""

    for nation in world.nations.values():
        if nation.ended:
            continue
        for location in nation.locations(world):
            reap_extinct_records(location, world, nation)
