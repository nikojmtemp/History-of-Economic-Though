"""The opening: bands (DD §3).

**Doc 02 simplification** (see DEVIATIONS.md): DD frames move/follow/settle as
choices a sovereign (player or scripted AI) queues via `core.actions` — but Doc 06's
scripted AI doesn't exist yet, and a genuinely null sovereign would leave a band
sitting motionless forever, which can't satisfy this doc's own acceptance scenario
("at least one nation tames herds by year 80"). DD itself frames the band stage as
needing no government ("government is unnecessary" until the first raid), so Doc 02
runs simple survival heuristics automatically every year for any nation still in
BAND seat, in addition to exposing the mechanics as functions callable from the
action queue for when a real sovereign (player or Doc 06's AI) wants to override them.
Likewise, "Tamed animal to the tamer" and settling are, per DD §3, the *events* that
create property in the first place — they can't wait on Doc 03's Interest/law
machinery to self-enact, so this module fires them directly once their resource
gates are met, and marks the corresponding law pre-enacted so Doc 03 doesn't refire it.
"""

from __future__ import annotations

from stock.core.actions import Action, ActionKind, register_cost_fn
from stock.core.laws import LawId
from stock.core.params import Params
from stock.core.producers import Producer, ProducerKind
from stock.core.records import ClassId, Record, quantise_move
from stock.core.trees import TreeINode
from stock.core.world import LawState, Location, Nation, World


def _get_or_create(location: Location, cls: ClassId) -> Record:
    record = location.record(cls)
    if record is None:
        record = Record(cls=cls, location=location.id)
        location.records.append(record)
    return record


def ground_quality(location: Location) -> float:
    """A rough "how good is it here" number for move/stay comparisons (DD §3's
    "game+grazing x (1-depletion)", surfaced to the UI in Doc 07)."""

    game = location.resources.game_yield * (1.0 - location.capacity.game_depletion)
    grazing = (location.capacity.graze_cap > 0) * (1.0 - location.capacity.graze_depletion)
    return game + grazing


def band_move(
    world: World, nation: Nation, from_location: Location, to_location_id: str, params: Params
) -> bool:
    """Relocates the band. Costs consensus (`A_S`, DD §3); the "year's yield" cost is
    not separately modelled (see DEVIATIONS.md) — production for the year has already
    run before band decisions are made."""

    to_location = world.locations.get(to_location_id)
    if to_location is None or to_location is from_location or to_location.nation not in (None, nation.id):
        # (a "move" onto the band's own location used to empty it: the records were
        # copied onto the location and then cleared from it — see A68)
        return False
    to_location.nation = nation.id
    for record in from_location.records:
        record.location = to_location.id
    to_location.records.extend(from_location.records)
    from_location.records = []
    from_location.producers = []
    from_location.nation = None
    nation.scalars.A_S = max(0.0, nation.scalars.A_S - move_cost(params))
    return True


def move_cost(params: Params) -> float:
    """Consensus a move costs (DD §3): `move_consensus_share · C0`."""

    return params.band.move_consensus_share * params.politics.consensus_c0


def _band_move_cost(world: World, action: Action) -> float:
    return move_cost(world.params)


register_cost_fn(ActionKind.BAND_MOVE, _band_move_cost)


def band_follow_herds(location: Location, nation_id: str, params: Params) -> None:
    """Gains contact, the gate on Domesticated herds (DD §3). More people following
    the herds means more contact: the rate scales with the band's size against
    `contact_reference_size` (a flat rate when that is 0)."""

    if not location.resources.grazing:
        return
    gain = params.band.contact_gain_rate
    reference = params.band.contact_reference_size
    if reference > 0:
        size = sum(r.size for r in location.records)
        gain *= size / reference
    location.contact[nation_id] = location.contact.get(nation_id, 0.0) + gain


def tame_gate_met(location: Location, nation: Nation, world: World) -> bool:
    """Domesticated herds' gate at a grazing location: contact past
    `tree.contact_threshold`, or a band past `band.tame_pop_threshold` people —
    population pressure tames herds without waiting on contact (or on anyone's
    authority)."""

    if not location.resources.grazing:
        return False
    contact = location.contact.get(nation.id, 0.0)
    if contact >= world.params.tree.contact_threshold:
        return True
    pop_threshold = world.params.band.tame_pop_threshold
    if pop_threshold > 0:
        size = sum(r.size for r in location.records)
        if size >= pop_threshold:
            return True
    return False


def tame_herd(location: Location, nation: Nation, world: World) -> bool:
    """"The tamed animal belongs to the tamer" (DD §3): herds become property; owner
    and herdsman records appear."""

    node = location.tree1.nodes[TreeINode.DOMESTICATED_HERDS]
    if node.lit:
        return False
    if not tame_gate_met(location, nation, world):
        return False
    hunters = location.record(ClassId.HUNTERS)
    if hunters is None or hunters.size <= 0:
        return False

    params = world.params
    min_size = params.population.extinct_size_epsilon
    owner_share = 0.2
    moved = quantise_move(hunters.size, hunters.size * params.band.tame_conversion_share, min_size)
    # Both new records must be at least one person (`quantise_move`'s rule); a band
    # too small to field one owner and one herdsman can't tame.
    if moved * owner_share < min_size or moved * (1.0 - owner_share) < min_size:
        return False
    owners = _get_or_create(location, ClassId.HERD_OWNERS)
    herdsmen = _get_or_create(location, ClassId.HERDSMEN)
    owners.size += moved * owner_share
    # Seed herd, capped by graze capacity if set
    seeded_herd = params.band.initial_herd_per_owner
    if location.capacity.graze_cap > 0:
        seeded_herd = min(seeded_herd, location.capacity.graze_cap)
    owners.wealth.herd += seeded_herd
    herdsmen.size += moved * (1.0 - owner_share)
    hunters.size -= moved

    node.lit = True
    node.lit_year = world.year
    law_state = nation.laws.setdefault(LawId.TAMED_ANIMAL_TO_TAMER, LawState())
    law_state.enacted = True
    from stock.politics.legislation import enforcement
    law_state.enforcement = enforcement(LawId.TAMED_ANIMAL_TO_TAMER, nation, world)
    return True


def found_field(location: Location, record: Record, world: World) -> Producer | None:
    """Founds a FIELD producer wholly owned by `record`'s class on arable land (DD
    §3's first field; `engine.mobility.apply_frontier_flows` reuses this for a
    settled nation's cultivation-edge expansion — DEVIATIONS A28). Land shares seed
    1:1 with the record's size (`settle`'s original convention: one land share per
    settling/arriving head). Returns the new Producer, or None if the location
    can't found one (not arable, already has a field, or the record is empty)."""

    if not location.resources.arable or location.fields > 0 or record.size <= 0:
        return None

    from stock.engine.capital import sync_record_wealth

    location.fields = record.size
    field = Producer(
        kind=ProducerKind.FIELD,
        location=location.id,
        land_shares=location.fields,
        owners_land={record.cls: 1.0},
        owners_stock={record.cls: 1.0},
    )
    location.producers.append(field)
    sync_record_wealth(location, world.params)
    location.tree1.nodes[TreeINode.GRAIN].lit = True
    location.tree1.nodes[TreeINode.GRAIN].lit_year = world.year
    return field


def settle(location: Location, nation: Nation, world: World) -> bool:
    """A record builds the first field on arable land and stops moving (DD §3).
    Delegates producer creation to `found_field`, kept behaviourally identical to
    the original inline version."""

    if not location.resources.arable or location.fields > 0:
        return False
    band_record = location.record(ClassId.HUNTERS) or location.record(ClassId.HERDSMEN)
    if band_record is None or band_record.size <= 0:
        return False

    if location.nation is None:
        location.nation = nation.id  # no-op guard: already set for the band's home

    params = world.params
    moved = quantise_move(
        band_record.size,
        band_record.size * params.band.settle_conversion_share,
        params.population.extinct_size_epsilon,
    )
    if moved <= 0:
        return False
    tenants = _get_or_create(location, ClassId.TENANTS)
    tenants.size += moved
    band_record.size -= moved

    return found_field(location, tenants, world) is not None


def band_barter(location: Location, other: Location, world: World) -> None:
    """Border barter at labour-time ratios (DD §3, §4.5): creates/gets a Route.

    Capacity for barter = k_cap · barter_capacity / carriage_cost. Prices at
    labour-time ratios (the basket) = markets' current prices; clear_goods applies unchanged."""

    if location.nation is None or other.nation is None or location.nation == other.nation:
        return

    from stock.core.world import Route
    from stock.engine.market import carriage_cost

    cost = carriage_cost(location, other.id)
    if cost == float("inf") or cost <= 0:
        return

    # Create or get route id (sorted)
    a, b = (location.id, other.id) if location.id < other.id else (other.id, location.id)
    route_id = f"{a}->{b}"

    if route_id not in world.routes:
        world.routes[route_id] = Route(id=route_id, a=a, b=b, merchant_stock={})

    route = world.routes[route_id]
    # Barter capacity: k_cap · barter_capacity / carriage_cost
    route.ships = world.params.trade.barter_capacity / cost if cost > 0 else 0.0


def band_raid(world: World, attacker: Nation, target_location: Location, params: Params) -> dict[str, float]:
    """A raid takes stealable goods and herds (DD §3); full war/strength resolution is
    Doc 04's security.war.raid — this delegates to that for one raid formula."""

    from stock.security.war import raid

    return raid(world, attacker.id, target_location, world.rng)


def step_band(world: World) -> None:
    """Automatic band-stage survival heuristics for every BAND-seat nation (see module
    docstring). A real sovereign's queued BAND_* actions (Doc 06/07) can call the
    functions above directly instead.

    The heuristics steer a band nobody else steers. Moving and settling are the
    band's two choices (DD §3: "move or stay", settle "when the ground gives out"),
    so a nation with a player at the seat (`nation.ai == "player"`) is never moved
    or settled here — it moves and settles through `BAND_MOVE`/`BAND_SETTLE`. An
    unsteered band settles only once its ground is giving out: depleted past
    `settle_depletion_threshold` (Doc 02's own parameter), or the hunt has fallen
    short of subsistence for `settle_pressed_years` running. Taming stays automatic
    for everyone: it is the contact-gated *event* that creates the first property,
    not a decision. See DEVIATIONS-IN-PROGRESS.md A68."""

    from stock.core.world import SeatKind

    for nation in world.nations.values():
        if nation.seat is not SeatKind.BAND:
            continue
        locations = nation.locations(world)
        if not locations:
            continue
        location = locations[0]  # a band holds exactly one location by construction
        steered = nation.ai == "player"

        # Refill consensus to C₀ at the start of each year; moves deduct from it (DD §3, MM §12).
        nation.scalars.A_S = world.params.politics.consensus_c0

        # Last year's curve (step 13c runs after this step): is the hunt feeding the band?
        pph = nation.curves.get("produce_per_head")
        pressed = pph is not None and pph < 1.0
        nation.scalars.pressed_years = nation.scalars.pressed_years + 1 if pressed else 0

        if tame_herd(location, nation, world):
            # Doc 03's handover (DD §7.3: A_S := largest herd-owner's authority,
            # seat := CHIEF) — band.py fires taming directly rather than through
            # legislation (see this module's docstring), so Doc 03 hooks the
            # handover in here rather than through the self-enactment pipeline;
            # see DEVIATIONS.md.
            from stock.politics.state import on_tamed_animal

            on_tamed_animal(nation, world)
            continue
        depleted = max(location.capacity.game_depletion, location.capacity.graze_depletion)
        ground_giving_out = (
            depleted > world.params.band.settle_depletion_threshold
            or nation.scalars.pressed_years >= world.params.band.settle_pressed_years
        )
        if not steered and ground_giving_out and settle(location, nation, world):
            # Doc 03's handover (DD §3/§7.3, DEVIATIONS A27): a band that settles
            # arable land without ever taming herds still hands the seat over —
            # otherwise `seat == BAND` blocks legislation forever and step_band
            # would even move it off its own field. Same fire-directly reasoning
            # as the Tamed Animal handover above.
            from stock.politics.state import on_settled

            on_settled(nation, world)
            continue

        # A sovereign that has already queued its own move this year (Doc 06's
        # scripts, Doc 07's player) decides where the band goes; the depletion
        # heuristic only moves a band nobody is steering. Everything else below
        # (contact, barter) still runs. See DEVIATIONS-IN-PROGRESS.md.
        move_queued = any(getattr(a.kind, "name", "") == "BAND_MOVE" for a in nation.queue)
        # A band moves off worked-out ground — or off ground that never fed it in
        # the first place (`ground_giving_out` with nothing arable to settle), rather
        # than starving in place on a poor start.
        should_move = depleted > world.params.band.move_depletion_threshold or ground_giving_out
        if not steered and should_move and not move_queued:
            best_neighbour = max(
                location.neighbours,
                key=lambda nid: ground_quality(world.locations[nid]),
                default=None,
            )
            if best_neighbour is not None and world.locations[best_neighbour].nation is None:
                if ground_quality(world.locations[best_neighbour]) > ground_quality(location):
                    band_move(world, nation, location, best_neighbour, world.params)
                    continue

        band_follow_herds(location, nation.id, world.params)

        # Band barter with neighbouring band-stage nations
        from stock.core.world import SeatKind
        from stock.trade.hostility import hostility as get_hostility
        for neighbour_id in location.neighbours:
            neighbour = world.locations.get(neighbour_id)
            if neighbour is None or neighbour.nation is None or neighbour.nation == nation.id:
                continue
            neighbour_nation = world.nations.get(neighbour.nation)
            if neighbour_nation is None or neighbour_nation.seat != SeatKind.BAND:
                continue
            # Check hostility
            h = get_hostility(world, nation.id, neighbour.nation)
            if h < world.params.trade.barter_hostility_max:
                band_barter(location, neighbour, world)
