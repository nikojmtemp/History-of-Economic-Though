"""Mobility — year step 8b (DD §2.4; MM §2).

Vertical edges gated by a law (Commutation, Enclosure, guild closing) are not
implemented here — they're applied by politics/legislation.py (Doc 03) via the
`EffectSpec("vertical_flow", ...)` tags already declared on those laws in
`core/laws.py`, calling straight into this module's `vertical_flow`. Doc 02's own
scope is the law-free edges: the three wealth-threshold promotions, and the
horizontal edges within each tier (DD §2.4's table), same-location and
cross-location. Cross-*border* edges (hostility, `f(N_bar_dest)`, treaty terms) are
Doc 04's; `edge_friction` returns 0 until laws exist to read (Doc 03).
"""

from __future__ import annotations

from stock.core.laws import LAW_TABLE, LawId
from stock.core.params import Params
from stock.core.records import ClassId, Record, quantise_move
from stock.core.trees import TreeINode
from stock.core.world import Location, Nation, SeatKind, World

#: Law-free vertical promotions (DD §2.4), gated by wealth per head crossing a
#: threshold. Demotions (serf->tenant, serf/tenant->labourer, craftsman->labourer,
#: labourer->servant) all require either a law or flow into a derived-size class —
#: see the module docstring.
VERTICAL_PROMOTIONS: tuple[tuple[ClassId, ClassId], ...] = (
    (ClassId.HERDSMEN, ClassId.HERD_OWNERS),
    (ClassId.CRAFTSMEN, ClassId.CAPITALISTS),
    (ClassId.LABOURERS, ClassId.CRAFTSMEN),
)

#: Horizontal tiers (DD §2.4 table), excluding derived-size classes (RETAINERS,
#: SERVANTS) and mobilised states (levy, militia — Doc 04), which don't flow here.
HORIZONTAL_TIERS: tuple[tuple[ClassId, ...], ...] = (
    (ClassId.HERDSMEN, ClassId.SERFS),
    (ClassId.LABOURERS, ClassId.SOLDIERS),
    (ClassId.CRAFTSMEN, ClassId.TENANTS, ClassId.MERCHANTS),
    (ClassId.CAPITALISTS, ClassId.MERCHANTS, ClassId.LANDLORDS),
)


def _adjacent_pairs() -> list[tuple[ClassId, ClassId]]:
    pairs: list[tuple[ClassId, ClassId]] = []
    for tier in HORIZONTAL_TIERS:
        for a, b in zip(tier, tier[1:], strict=False):
            pairs.append((a, b))
            pairs.append((b, a))
    return pairs


HORIZONTAL_EDGES: list[tuple[ClassId, ClassId]] = _adjacent_pairs()


def wealth_per_head(record: Record) -> float:
    return record.wealth.total() / record.size if record.size > 0 else 0.0


def _get_or_create(location: Location, cls: ClassId) -> Record:
    record = location.record(cls)
    if record is None:
        record = Record(cls=cls, location=location.id)
        location.records.append(record)
    return record


def vertical_flow(
    location: Location, from_cls: ClassId, to_cls: ClassId, share: float, min_size: float = 1.0
) -> float:
    """Moves `share` of `from_cls`'s size to `to_cls` at the same location (MM §2).
    For locations with non-occupation producers: moves ownership shares via `owners_stock`/`owners_land`,
    then caller must call `sync_record_wealth`. For locations without producers: moves wealth directly.
    The move is quantised to whole people (`quantise_move`, `min_size` =
    `PopulationParams.extinct_size_epsilon`): nothing moves if the flow is under one
    person, everyone moves if under one person would be left. Returns the size actually moved."""

    src = location.record(from_cls)
    if src is None or src.size <= 0 or share <= 0:
        return 0.0
    share = min(1.0, share)
    moved_size = quantise_move(src.size, src.size * share, min_size)
    if moved_size <= 0:
        return 0.0
    share = moved_size / src.size
    dst = _get_or_create(location, to_cls)

    from stock.core.producers import OCCUPATIONS

    has_non_occupation_producers = any(p.kind not in OCCUPATIONS for p in location.producers)

    if has_non_occupation_producers:
        for producer in location.producers:
            if producer.kind in OCCUPATIONS:
                continue
            if from_cls in producer.owners_stock:
                moved_ownership = producer.owners_stock[from_cls] * share
                producer.owners_stock[from_cls] -= moved_ownership
                producer.owners_stock[to_cls] = producer.owners_stock.get(to_cls, 0.0) + moved_ownership
            if from_cls in producer.owners_land:
                moved_ownership = producer.owners_land[from_cls] * share
                producer.owners_land[from_cls] -= moved_ownership
                producer.owners_land[to_cls] = producer.owners_land.get(to_cls, 0.0) + moved_ownership
    else:
        dst.wealth.stock_in_place += src.wealth.stock_in_place * share
        src.wealth.stock_in_place -= src.wealth.stock_in_place * share
        dst.wealth.land_shares += src.wealth.land_shares * share
        src.wealth.land_shares -= src.wealth.land_shares * share

    dst.wealth.herd += src.wealth.herd * share
    dst.wealth.fixed_assets += src.wealth.fixed_assets * share
    dst.wealth.hoard += src.wealth.hoard * share
    dst.wealth.bonds += src.wealth.bonds * share
    dst.wealth.tools += src.wealth.tools * share
    dst.wealth.loans_out += src.wealth.loans_out * share
    dst.debt += src.debt * share

    src.wealth.herd -= src.wealth.herd * share
    src.wealth.fixed_assets -= src.wealth.fixed_assets * share
    src.wealth.hoard -= src.wealth.hoard * share
    src.wealth.bonds -= src.wealth.bonds * share
    src.wealth.tools -= src.wealth.tools * share
    src.wealth.loans_out -= src.wealth.loans_out * share
    src.debt -= src.debt * share

    dst.size += moved_size
    src.size -= moved_size
    return moved_size


def apply_vertical_promotions(location: Location, params: Params) -> None:
    threshold = params.mobility.vertical_promotion_threshold
    for from_cls, to_cls in VERTICAL_PROMOTIONS:
        record = location.record(from_cls)
        if record is None or record.size <= 0:
            continue
        if wealth_per_head(record) > threshold:
            vertical_flow(
                location,
                from_cls,
                to_cls,
                params.mobility.rate_v_base,
                params.population.extinct_size_epsilon,
            )
    # Sync record wealth after ownership transfers
    from stock.engine.capital import sync_record_wealth

    sync_record_wealth(location, params)


def income_per_head(record: Record | None, location: Location) -> float:
    """Income per head for a record, used by mobility net_advantage calculations.

    If record is None, returns a plausible entrant's wage (natural_wage).
    If record.size <= 0 but record.last_gross_income > 0, returns that income
    (for recruitment: entrants see a soldier's pay as per-head income).
    Otherwise returns record's income per head or natural wage."""

    if record is None:
        from stock.engine.wages import natural_wage

        return natural_wage(location)
    if record.size <= 0:
        if record.last_gross_income > 0:
            return record.last_gross_income  # entrant's pay (soldier recruitment path)
        from stock.engine.wages import natural_wage

        return natural_wage(location)
    return record.last_gross_income / record.size


#: The free-labour horizontal tier (DD §2.4's table) that Settlement Law's
#: `free_labour_cross_location` friction tag names; approximated here as also
#: damping the same-location edge between them, since neither of `LAW_TABLE`'s two
#: `friction`-tagged laws actually names a same-location `(from_cls, to_cls)` pair
#: — see DEVIATIONS.md (Doc 03).
_FREE_LABOUR_TIER: frozenset[ClassId] = frozenset({ClassId.LABOURERS, ClassId.SOLDIERS})


def edge_friction(nation: Nation, from_cls: ClassId, to_cls: ClassId) -> float:
    """Law friction on a same-location edge (DD §2.4). Doc 03 extension point: reads
    Settlement Law (free-labour edges) and Apprenticeship (edges touching
    CRAFTSMEN), enforcement-scaled — the closest match this signature has to their
    named `friction` tags (see the module-level note and DEVIATIONS.md; both laws'
    tags actually name a cross-location and a producer-hiring friction respectively,
    neither of which this same-location `(from_cls, to_cls)` signature covers
    exactly)."""

    friction = 0.0
    both_free = from_cls in _FREE_LABOUR_TIER and to_cls in _FREE_LABOUR_TIER
    settlement = nation.laws.get(LawId.SETTLEMENT_LAW)
    if settlement is not None and settlement.enacted and both_free:
        friction = max(friction, _friction_x(LawId.SETTLEMENT_LAW) * settlement.enforcement)
    apprenticeship = nation.laws.get(LawId.APPRENTICESHIP)
    if apprenticeship is not None and apprenticeship.enacted and ClassId.CRAFTSMEN in (from_cls, to_cls):
        friction = max(friction, _friction_x(LawId.APPRENTICESHIP) * apprenticeship.enforcement)
    return min(1.0, friction)


def _friction_x(law: LawId) -> float:
    """Reads the `x` magnitude off the law's own `friction` `EffectSpec` (already
    declared in `LAW_TABLE`, Doc 01) rather than duplicating it as a literal here."""

    spec = LAW_TABLE[law]
    for effect in spec.effects:
        if effect.kind == "friction":
            return float(effect.params["x"])
    return 0.0


def net_advantage(record: Record | None, target_cls: ClassId, location: Location) -> float:
    """`NA = income per head + non-monetary terms` (MM §2). Non-monetary terms
    (agreeableness, learning cost, constancy, trust, chance) are not modelled in Doc
    02's first pass — income per head is the whole of it for now."""

    target = location.record(target_cls)
    return income_per_head(target, location) - income_per_head(record, location)


def flow(size_r: float, rate_edge: float, friction: float, na: float) -> float:
    """`flow(r->r') = size_r * rate_edge * (1-friction) * max(0, NA)` (MM §2), returned
    as a share of `size_r` in `[0, 1]` for the caller to apply via `vertical_flow`."""

    if na <= 0 or size_r <= 0:
        return 0.0
    return min(1.0, rate_edge * (1.0 - friction) * min(1.0, na))


def apply_horizontal_flows(nation: Nation, location: Location, params: Params) -> None:
    for from_cls, to_cls in HORIZONTAL_EDGES:
        record = location.record(from_cls)
        if record is None or record.size <= 0:
            continue
        na = net_advantage(record, to_cls, location)
        friction = edge_friction(nation, from_cls, to_cls)
        share = flow(record.size, params.mobility.rate_edge_base, friction, na)
        # same mechanic, any edge
        vertical_flow(location, from_cls, to_cls, share, params.population.extinct_size_epsilon)
    # Sync record wealth after ownership transfers
    from stock.engine.capital import sync_record_wealth

    sync_record_wealth(location, params)


def apply_cross_location_flows(nation: Nation, world: World) -> None:
    """DD §2.4: "every edge also runs to the same tier in neighbouring locations,
    friction = distance / (river or road factor)"; same-nation. Also extends across
    borders (Doc 04) for free labour (LABOURERS, SOLDIERS, SERVANTS) as emigration."""

    from stock.engine.market import carriage_cost

    locations = nation.locations(world)
    all_classes = {cls for tier in HORIZONTAL_TIERS for cls in tier}
    min_size = world.params.population.extinct_size_epsilon

    # Same-nation cross-location flows
    for loc in locations:
        for neighbour_id in loc.neighbours:
            neighbour = world.locations.get(neighbour_id)
            if neighbour is None or neighbour.nation != nation.id:
                continue
            cost = carriage_cost(loc, neighbour_id)
            if cost == float("inf"):
                continue
            friction = min(1.0, cost / world.params.prices.c_max) if world.params.prices.c_max > 0 else 1.0
            for cls in all_classes:
                record = loc.record(cls)
                if record is None or record.size <= 0:
                    continue
                na = income_per_head(neighbour.record(cls), neighbour) - income_per_head(record, loc)
                share = flow(record.size, world.params.mobility.rate_edge_base, friction, na)
                _cross_location_move(loc, neighbour, cls, share, min_size)

    # Cross-border flows (free labour only: emigration)
    # SERVANTS are derived-size classes and must not flow cross-border (Doc 02)
    free_labour_classes = (ClassId.LABOURERS, ClassId.SOLDIERS)
    for loc in locations:
        for neighbour_id in loc.neighbours:
            neighbour = world.locations.get(neighbour_id)
            if neighbour is None or neighbour.nation == nation.id or neighbour.nation is None:
                continue
            cost = carriage_cost(loc, neighbour_id)
            if cost == float("inf"):
                continue
            # Border friction for cross-border flows
            from stock.trade.routes import border_friction
            b_friction = border_friction(loc.id, neighbour_id, world)
            for cls in free_labour_classes:
                record = loc.record(cls)
                if record is None or record.size <= 0:
                    continue
                target = neighbour.record(cls)
                dest_income = income_per_head(target, neighbour)
                src_income = income_per_head(record, loc)
                na = dest_income - src_income + record.emigration_pressure
                if na <= 0:
                    continue
                share = flow(record.size, world.params.mobility.rate_edge_base, b_friction, na)
                if share <= 0:
                    continue
                moved = _cross_location_move(loc, neighbour, cls, share, min_size)
                if moved <= 0:
                    continue
                # Track migration flows
                nation.add_flow("migration_out", moved)
                neighbour_nation = world.nations.get(neighbour.nation)
                if neighbour_nation is not None:
                    neighbour_nation.add_flow("migration_in", moved)


def _move_wealth_share(src: Record, dst: Record, share: float, min_size: float = 1.0) -> float:
    """Pro-rata move of `share` of `src`'s size, debt, and cross-location-mobile
    wealth fields (herd, fixed_assets, hoard, bonds, tools, loans_out) onto `dst`.
    `land_shares`/`stock_in_place` stay put — land is immobile and stock is tied to
    its producer at the source location. Quantised to whole people like
    `vertical_flow`. Returns the size moved. Shared by `_cross_location_move` (same
    class, same-nation neighbour) and `apply_frontier_flows` (crossing into unowned
    ground, possibly landing on a different destination class — e.g. LABOURERS
    arriving as TENANTS)."""

    if src.size <= 0 or share <= 0:
        return 0.0
    share = min(1.0, share)
    moved = quantise_move(src.size, src.size * share, min_size)
    if moved <= 0:
        return 0.0
    share = moved / src.size
    wealth_fields = ("herd", "fixed_assets", "hoard", "bonds", "tools", "loans_out")
    for field_name in wealth_fields:
        amount = getattr(src.wealth, field_name) * share
        setattr(dst.wealth, field_name, getattr(dst.wealth, field_name) + amount)
        setattr(src.wealth, field_name, getattr(src.wealth, field_name) - amount)
    dst.debt += src.debt * share
    src.debt -= src.debt * share
    dst.size += moved
    src.size -= moved
    return moved


def _cross_location_move(
    src_loc: Location, dst_loc: Location, cls: ClassId, share: float, min_size: float = 1.0
) -> float:
    """Cross-location move: wealth moves pro rata but ownership stays with source location
    (land is immobile; stock in place is tied to its producer). Only herd, hoard, bonds,
    loans_out, tools, and debt move; land_shares and stock_in_place stay. Returns the
    size moved (0 when the flow quantises to nothing — no record is created then)."""

    src = src_loc.record(cls)
    if src is None or src.size <= 0 or share <= 0:
        return 0.0
    if quantise_move(src.size, src.size * min(1.0, share), min_size) <= 0:
        return 0.0
    dst = _get_or_create(dst_loc, cls)
    return _move_wealth_share(src, dst, share, min_size)


#: Occupation-edge classes for the frontier (DD §3's mobile band classes):
#: HUNTERS and HERDSMEN move on ground quality; HERD_OWNERS rides along with its
#: herdsmen at the same share (DEVIATIONS A28).
_FRONTIER_OCCUPATION_CLASSES: tuple[ClassId, ...] = (ClassId.HUNTERS, ClassId.HERDSMEN, ClassId.HERD_OWNERS)

#: Cultivation-edge classes: TENANTS and LABOURERS are mobile; SERFS are not
#: (Serfdom binds them to the land, DD §2.4) and so are excluded (DEVIATIONS A28).
_FRONTIER_CULTIVATION_CLASSES: tuple[ClassId, ...] = (ClassId.TENANTS, ClassId.LABOURERS)


def apply_frontier_flows(nation: Nation, world: World) -> None:
    """MM §2's horizontal edge whose destination is empty ground (DEVIATIONS A28;
    DD §1.1 "settled ... one at a time"): the occupation edge (HUNTERS, HERDSMEN,
    and HERD_OWNERS riding with its herdsmen) pushes into a better unowned
    neighbour when home ground is pressed (depletion past `frontier_pressure`); the
    cultivation edge (TENANTS, LABOURERS — not SERFS, immobile under Serfdom)
    pushes into an arable unowned neighbour when fields per cultivating head at
    home falls below `frontier_land_per_head`, founding a FIELD there via
    `band.found_field` (LABOURERS arrive as TENANTS: DD §2.4's labourer-to-tenant
    edge at settlement). Bands are excluded — a band holds exactly one location by
    construction and `step_band`/`band_move` already relocates it. At most one
    claim fires per nation per year: the cheapest qualifying (location, neighbour)
    pair by `carriage_cost`. Neither edge changes producer ownership at the
    source, so — like `apply_cross_location_flows` — no `sync_record_wealth` call
    is needed there; `found_field` syncs the destination itself."""

    if nation.seat is SeatKind.BAND or nation.ended:
        return

    from stock.engine.band import found_field, ground_quality
    from stock.engine.market import carriage_cost
    from stock.sim.ledger import EventRecord

    p = world.params.mobility
    min_size = world.params.population.extinct_size_epsilon
    # (cost, kind_rank, loc_id, nb_id, loc, nb) — kind_rank/ids make the sort
    # deterministic on ties rather than relying on dict iteration order.
    candidates: list[tuple[float, int, str, str, Location, Location]] = []

    for loc in nation.locations(world):
        for nb_id in loc.neighbours:
            nb = world.locations.get(nb_id)
            if nb is None or nb.nation is not None:
                continue
            cost = carriage_cost(loc, nb_id)
            if cost == float("inf"):
                continue

            depleted = max(loc.capacity.game_depletion, loc.capacity.graze_depletion)
            if depleted > p.frontier_pressure and ground_quality(nb) > ground_quality(loc) * (
                1.0 + p.frontier_margin
            ):
                candidates.append((cost, 0, loc.id, nb_id, loc, nb))

            if nb.resources.arable:
                cultivators = sum(
                    r.size for r in loc.records if r.cls in _FRONTIER_CULTIVATION_CLASSES
                )
                if cultivators > 0 and loc.fields / cultivators < p.frontier_land_per_head:
                    candidates.append((cost, 1, loc.id, nb_id, loc, nb))

    if not candidates:
        return
    candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
    _, kind_rank, _, _, loc, nb = candidates[0]

    nb.nation = nation.id
    moved = 0.0

    if kind_rank == 0:  # occupation edge
        herd_moved = False
        for cls in _FRONTIER_OCCUPATION_CLASSES:
            if cls in (ClassId.HERDSMEN, ClassId.HERD_OWNERS) and not nb.resources.grazing:
                # Herding can't take root without grazing (same gate as
                # `band.tame_herd`) — `nb` may still qualify on game alone;
                # HUNTERS can still move in.
                continue
            src = loc.record(cls)
            if src is None or src.size <= 0:
                continue
            if quantise_move(src.size, src.size * p.rate_frontier, min_size) <= 0:
                continue
            dst = _get_or_create(nb, cls)
            share_moved = _move_wealth_share(src, dst, p.rate_frontier, min_size)
            moved += share_moved
            if cls in (ClassId.HERDSMEN, ClassId.HERD_OWNERS) and share_moved > 0:
                herd_moved = True
        if herd_moved:
            # A nation's herding population spreading to a new location is the
            # same fact DD §3 lights DOMESTICATED_HERDS for at the taming
            # location — light it here too, symmetrically with `found_field`
            # lighting GRAIN on the cultivation edge below (DEVIATIONS A28).
            node = nb.tree1.nodes[TreeINode.DOMESTICATED_HERDS]
            if not node.lit:
                node.lit = True
                node.lit_year = world.year
    else:  # cultivation edge
        dst_tenants = _get_or_create(nb, ClassId.TENANTS)
        for cls in _FRONTIER_CULTIVATION_CLASSES:
            src = loc.record(cls)
            if src is None or src.size <= 0:
                continue
            moved += _move_wealth_share(src, dst_tenants, p.rate_frontier, min_size)
        found_field(nb, dst_tenants, world)

    nation.add_flow("migration_frontier", moved)
    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=nation.id,
                kind="location_claimed",
                numbers={"size": moved, "fields": nb.fields},
            )
        )


def step_mobility(world: World) -> None:
    """Year step 8b."""

    for nation in world.nations.values():
        for location in nation.locations(world):
            apply_vertical_promotions(location, world.params)
            apply_horizontal_flows(nation, location, world.params)
        apply_cross_location_flows(nation, world)
        apply_frontier_flows(nation, world)
        # Ensure migration flows exist (populated by apply_cross_location_flows)
        if "migration_out" not in nation.flows:
            nation.add_flow("migration_out", 0.0)
        if "migration_in" not in nation.flows:
            nation.add_flow("migration_in", 0.0)
