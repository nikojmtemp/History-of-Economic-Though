"""Hoards, propensity, and placement — year steps 7 and 9 (DD §5.2-5.3, §4.4; MM
§6, §11)."""

from __future__ import annotations

from dataclasses import dataclass

from stock.core.params import Params
from stock.core.producers import OCCUPATIONS, MethodId, Producer, ProducerKind
from stock.core.records import CLASS_TABLE, ClassId, Record
from stock.core.trees import TreeINode
from stock.core.world import Location, Nation, World

#: Base return ranking when a producer has no stock yet to compute an empirical
#: return from (MM §6: "cultivation > domestic manufacture > foreign trade"), reordered
#: elsewhere by charters/bounties/tariffs (Doc 03/04 — not wired in yet).
BASE_RETURN_RANK: dict[ProducerKind, float] = {
    ProducerKind.FIELD: 0.15,
    ProducerKind.WORKSHOP: 0.10,
    ProducerKind.PUTTING_OUT: 0.10,
    ProducerKind.MANUFACTORY: 0.10,
    ProducerKind.MINE: 0.10,
    ProducerKind.PORT: 0.05,
}


@dataclass
class HoardResult:
    to_reinvest: float
    to_hoard: float


def sync_record_wealth(location: Location, params: Params) -> None:
    """Synchronizes record wealth fields with producer ownership (DD §4.3, §4.4).
    For each record at the location, computes `stock_in_place` and `land_shares` as
    the sum of their ownership shares across all non-occupation producers."""

    from stock.core.producers import OCCUPATIONS

    # Zero the fields first to avoid stale values
    for record in location.records:
        record.wealth.stock_in_place = 0.0
        record.wealth.land_shares = 0.0

    # Accumulate from non-occupation producers
    for producer in location.producers:
        if producer.kind in OCCUPATIONS:
            continue
        for cls, share in producer.owners_stock.items():
            owner = location.record(cls)
            if owner is not None:
                owner.wealth.stock_in_place += share * producer.stock_in_place
        for cls, share in producer.owners_land.items():
            owner = location.record(cls)
            if owner is not None:
                owner.wealth.land_shares += share * producer.land_shares


def propensity(
    record: Record,
    r_bar: float,
    params: Params,
    *,
    charter_modifier: float = 1.0,
    standing_saturated: bool = False,
) -> float:
    """DD §5.3: `p = p_base * (1 + p_prof*r_bar) * charter_modifier * saturation`.
    `charter_modifier` (Doc 04/06) defaults to 1.0; a saturated standing need raises
    `p` a little (DD §5.3) until Doc 03's E/A comparison is wired in."""

    spec = CLASS_TABLE[record.cls]
    p = spec.base_propensity * (1.0 + params.consumption.propensity_profit_weight * r_bar)
    if standing_saturated:
        p *= 1.1
    return min(1.0, max(0.0, p * charter_modifier))


def hoard_update(record: Record, saved: float, f_n: float, params: Params) -> HoardResult:
    """MM §11. `saved` is handed in already computed (see engine.consumption's module
    docstring for why): `to_reinvest = saved*f(N)`, `to_hoard = saved*(1-f(N))`,
    `H' = H + to_hoard - omega*f(N)*H - deposits - bonds_from_hoard` (the last two are
    0 until Doc 05's credit module exists). Writes to `record.to_reinvest` for
    per-record placement at step 9."""

    to_reinvest = saved * f_n
    to_hoard = saved * (1.0 - f_n)
    omega = params.consumption.hoard_reentry_omega
    record.wealth.hoard = max(0.0, record.wealth.hoard + to_hoard - omega * f_n * record.wealth.hoard)
    record.to_reinvest = to_reinvest  # stored for placement at step 9
    record.income = 0.0  # fully allocated: hoarded above, reinvested via record.to_reinvest
    return HoardResult(to_reinvest=to_reinvest, to_hoard=to_hoard)


def step_hoards(world: World, f_n_by_record: dict[tuple[str, str], float] | None = None) -> None:
    """Year step 7. Per-record reinvestment amounts are stored in `record.to_reinvest`
    for placement at step 9. f(N_r) is read from `world.prev.record_f_n` (computed by
    Doc 04's security module); when absent, defaults to 1.0 (no insecurity).

    `f_n_by_record` parameter (legacy, for tests) keys by (location_id, class_name);
    when provided, it overrides world.prev.record_f_n."""

    # Use provided f_n_by_record if given, else read from prev snapshot
    if f_n_by_record is None:
        f_n_by_record = {}

    for nation in world.nations.values():
        for location in nation.locations(world):
            for record in location.records:
                saved = record.income  # left in place by engine.consumption's step 5
                if saved <= 0:
                    continue

                # Try parameter first (legacy), then prev snapshot, then default 1.0
                key_by_name = (location.id, record.cls.name)
                key_by_cls = (location.id, record.cls)
                if key_by_name in f_n_by_record:
                    f_n = f_n_by_record[key_by_name]
                else:
                    f_n = world.prev.record_f_n.get(key_by_cls, 1.0)

                # Calculate hoard_reentry before hoard is modified
                hoard_reentry = world.params.consumption.hoard_reentry_omega * f_n * record.wealth.hoard
                hoard_result = hoard_update(record, saved, f_n, world.params)
                nation.add_flow("to_hoard", hoard_result.to_hoard)
                nation.add_flow("to_reinvest", hoard_result.to_reinvest)
                nation.add_flow("hoard_reentry", hoard_reentry)


def _add_stock(producer: Producer, cls: ClassId, amount: float) -> None:
    """Add stock to a producer, updating ownership shares proportionally.
    Existing owners' shares are scaled by stock/(stock+amount), then the new class
    gets amount/(stock+amount)."""
    if amount <= 0:
        return
    total = producer.stock_in_place + amount
    if total <= 0:
        return
    # Scale existing owners' shares
    for c in list(producer.owners_stock.keys()):
        producer.owners_stock[c] *= producer.stock_in_place / total
    # Add new class share
    producer.owners_stock[cls] = producer.owners_stock.get(cls, 0.0) + amount / total
    # Update stock
    producer.stock_in_place = total


def _producer_return(producer: Producer) -> float:
    if producer.stock_in_place > 0:
        return producer.last_split_profit / producer.stock_in_place
    return BASE_RETURN_RANK.get(producer.kind, 0.0)


def place_record(
    record: Record, location: Location, nation: Nation, world: World
) -> None:
    """Places a single record's to_reinvest amount by class per DD §5.3. Updates
    wealth fields (herd, tools, hoard, stock_in_place) and producer shares. Clears
    record.to_reinvest after use."""

    amount = record.to_reinvest
    if amount <= 0:
        record.to_reinvest = 0.0
        return

    cls = record.cls

    if cls in (ClassId.HERD_OWNERS, ClassId.HERDSMEN):
        # Herd: buy as much as graze capacity allows, remainder to hoard
        from stock.engine.production import herd_total

        current_herd = herd_total(location)
        graze_cap = location.capacity.graze_cap
        if graze_cap > 0:
            available_herd = graze_cap - current_herd
            herd_to_buy = max(0.0, min(amount, available_herd))  # a herd over its cap buys none, never sells
            record.wealth.herd += herd_to_buy
            record.wealth.hoard += amount - herd_to_buy
        else:
            record.wealth.hoard += amount

    elif cls in (ClassId.TENANTS, ClassId.LANDLORDS):
        # Stock into FIELD producer
        field_producer = None
        for producer in location.producers:
            if producer.kind == ProducerKind.FIELD:
                field_producer = producer
                break
        if field_producer is not None:
            _add_stock(field_producer, cls, amount)
        else:
            record.wealth.hoard += amount

    elif cls == ClassId.CRAFTSMEN:
        # Stock into WORKSHOP; create if none but materials available
        workshop = None
        for producer in location.producers:
            if producer.kind == ProducerKind.WORKSHOP:
                workshop = producer
                break
        if workshop is not None:
            _add_stock(workshop, cls, amount)
        else:
            # Tree I gate (Doc 05 meta.trees.evaluate_gates, step 10, lagged to last
            # year per the lag rule since placement is step 9): WORKSHOP allowed iff
            # the location's WARES node is lit, or LUXURIES for a `rare` workshop.
            workshop_allowed = location.tree1.nodes[TreeINode.WARES].lit or (
                location.resources.rare and location.tree1.nodes[TreeINode.LUXURIES].lit
            )
            if workshop_allowed:
                # Create new WORKSHOP
                workshop = Producer(
                    kind=ProducerKind.WORKSHOP,
                    location=location.id,
                    method=MethodId.HANDICRAFT,
                    stock_in_place=amount,
                    owners_stock={ClassId.CRAFTSMEN: 1.0},
                )
                location.producers.append(workshop)
            else:
                record.wealth.tools += amount

    elif cls == ClassId.CAPITALISTS:
        # Find best-return producer: existing or virtual
        candidates: dict[ProducerKind, tuple[float, Producer | None]] = {}

        # Check existing producers at location
        for producer in location.producers:
            if producer.kind in (
                ProducerKind.MANUFACTORY,
                ProducerKind.MINE,
                ProducerKind.WORKSHOP,
            ):
                ret = _producer_return(producer)
                if producer.kind not in candidates or ret > candidates[producer.kind][0]:
                    candidates[producer.kind] = (ret, producer)

        # Check virtual producers
        from stock.core.laws import LawId

        # MANUFACTORY: Tree II gate (Doc 05, lagged to last year like the WORKSHOP
        # gate above), LABOURERS at location (no Tree II equivalent — a location-
        # level requirement the nation-wide lit flag doesn't capture, so kept), no
        # GUILD_CHARTER (no Tree equivalent either — kept).
        if nation.tree2.production[MethodId.MANUFACTORY].lit:
            has_labourers = False
            for r in location.records:
                if r.cls == ClassId.LABOURERS and r.size >= 1.0:
                    has_labourers = True
                    break
            guild_charter_law = nation.laws.get(LawId.GUILD_CHARTER)
            guild_charter_enacted = guild_charter_law.enacted if guild_charter_law else False
            if has_labourers and not guild_charter_enacted:
                ret = BASE_RETURN_RANK[ProducerKind.MANUFACTORY]
                if (
                    ProducerKind.MANUFACTORY not in candidates
                    or ret > candidates[ProducerKind.MANUFACTORY][0]
                ):
                    candidates[ProducerKind.MANUFACTORY] = (ret, None)

        # MINE: needs resources, LABOURERS at location
        has_resources = (
            location.resources.ore or location.resources.coal or location.resources.timber
        )
        if has_resources:
            has_labourers = False
            for r in location.records:
                if r.cls == ClassId.LABOURERS and r.size >= 1.0:
                    has_labourers = True
                    break
            if has_labourers:
                ret = BASE_RETURN_RANK[ProducerKind.MINE]
                if ProducerKind.MINE not in candidates or ret > candidates[ProducerKind.MINE][0]:
                    candidates[ProducerKind.MINE] = (ret, None)

        # WORKSHOP: Tree I gate, same as the CRAFTSMEN branch above.
        workshop_allowed = location.tree1.nodes[TreeINode.WARES].lit or (
            location.resources.rare and location.tree1.nodes[TreeINode.LUXURIES].lit
        )
        if workshop_allowed:
            ret = BASE_RETURN_RANK[ProducerKind.WORKSHOP]
            if ProducerKind.WORKSHOP not in candidates or ret > candidates[ProducerKind.WORKSHOP][0]:
                candidates[ProducerKind.WORKSHOP] = (ret, None)

        if candidates:
            # Find best candidate
            best_kind, (best_ret, best_producer) = max(candidates.items(), key=lambda x: x[1][0])
            if best_producer is not None:
                # Existing producer
                _add_stock(best_producer, cls, amount)
            else:
                # Create new producer
                method = MethodId.MANUFACTORY if best_kind == ProducerKind.MANUFACTORY else MethodId.NONE
                new_producer = Producer(
                    kind=best_kind,
                    location=location.id,
                    method=method,
                    stock_in_place=amount,
                    owners_stock={ClassId.CAPITALISTS: 1.0},
                )
                location.producers.append(new_producer)
        else:
            record.wealth.hoard += amount

    elif cls == ClassId.MERCHANTS:
        # PORT at location: Tree I gate (SHIPS implies coast, DD §6.1, so this
        # subsumes the old coast-only check).
        if location.tree1.nodes[TreeINode.SHIPS].lit:
            port = None
            for producer in location.producers:
                if producer.kind == ProducerKind.PORT:
                    port = producer
                    break
            if port is not None:
                _add_stock(port, cls, amount)
            else:
                # Create new PORT
                port = Producer(
                    kind=ProducerKind.PORT,
                    location=location.id,
                    method=MethodId.NONE,
                    stock_in_place=amount,
                    owners_stock={ClassId.MERCHANTS: 1.0},
                )
                location.producers.append(port)
        else:
            record.wealth.hoard += amount

    else:
        # All other classes: HUNTERS, LABOURERS, SERFS, SOLDIERS, dependents, STATE
        record.wealth.hoard += amount

    record.to_reinvest = 0.0


def placement(nation: Nation, world: World) -> None:
    """MM §6: free `tau_turn` of every (non-occupation) producer's stock, hand it back
    to owner records by ownership share; then place each record's `to_reinvest` by class
    per DD §5.3. Creates new producers when location can hold one and none exists.
    Syncs record wealth with producer ownership after placement."""

    params = world.params
    locations_touched: set[str] = set()

    # Step 1: Free τ_turn from non-occupation producers and hand back by ownership share
    for location in nation.locations(world):
        for producer in location.producers:
            if producer.kind in OCCUPATIONS:
                continue
            withdrawal = producer.stock_in_place * params.production.tau_turn
            if withdrawal > 0:
                # Hand back to owners by share
                for cls, share in producer.owners_stock.items():
                    record = location.record(cls)
                    if record is not None:
                        record.to_reinvest += withdrawal * share
                    # else: amount stays in producer (not added to anyone's to_reinvest)
            producer.stock_in_place -= withdrawal
            locations_touched.add(location.id)

    # Step 2: Place each record's to_reinvest by class
    for location in nation.locations(world):
        for record in location.records:
            if record.to_reinvest > 0:
                place_record(record, location, nation, world)
        locations_touched.add(location.id)

    # Clear the nation-level pool (no longer written)
    nation.scalars.to_reinvest_pool = 0.0

    # Step 3: Sync record wealth after placement for all touched locations
    for location in nation.locations(world):
        sync_record_wealth(location, params)
