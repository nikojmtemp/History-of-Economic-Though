"""The order signal, State authority, and its handovers — year step 12b (DD §7.1,
§7.3; MM §12)."""

from __future__ import annotations

import math

from stock.core.goods import basket_cost
from stock.core.laws import LAW_TABLE, TRADE_LAW_TABLE, LawId
from stock.core.params import Params
from stock.core.records import ClassId, InterestId, Record
from stock.core.world import InterestState, LawState, Nation, SeatKind, World
from stock.politics.authority import dependents_of, record_authority
from stock.politics.justice import convert_disorder, justice_level, legibility_update
from stock.sim.ledger import EventRecord

#: `O`'s event weights (DD §7.1; MM §12). Only kinds a step in this codebase can
#: actually emit today (riot, revolt, mutiny from unrest.py; law_lapsed from
#: legislation.py) contribute until Docs 04/05 add the war/treaty/default events —
#: unknown kinds default to 0, so `O` degrades gracefully as those docs land.
_EVENT_WEIGHTS: dict[str, float] = {
    "victory": 2.0,
    "defence": 1.0,
    "raid": -1.0,
    "defeat": -2.0,
    "location_lost": -2.0,
    "location_taken": 0.0,  # not in DD §7.1; winner's O handled by victory
    "riot": -1.0,
    "revolt": -2.0,
    "mutiny": -3.0,
    "default": -1.0,
    "law_lapsed": -1.0,
    "treaty_broken_against_us": -1.0,
    "aggression": -1.0,  # DD §10.4 implied; war without casus belli incurs O cost
}


def events_this_year(nation_id: str, world: World) -> list[EventRecord]:
    """`nation.events_this_year` (DD §7's phrasing): realised as a query over the
    ledger, the single append-only event store, rather than a duplicate list kept on
    `Nation` (see DEVIATIONS.md)."""

    if world.ledger is None:
        return []
    return [e for e in world.ledger.events_in_year(world.year) if e.nation == nation_id]


def order_signal(events: list[EventRecord], params: Params) -> float:
    """`O = Sum events: weight` (DD §7.1; MM §12), events only."""

    return sum(_EVENT_WEIGHTS.get(e.kind, 0.0) for e in events)


def _law_weight(law: LawId | str) -> float:
    spec = LAW_TABLE.get(law) if isinstance(law, LawId) else TRADE_LAW_TABLE.get(law)
    return spec.weight if spec is not None else 0.0


def r_private(nation: Nation, world: World) -> float:
    """`R_private` = size of RETAINERS when the feudal host is the active doctrine
    (DD §7.1, MM §12). Returns 0 if FEUDAL_HOST is not the active doctrine."""

    if nation.scalars.active_doctrine != "FEUDAL_HOST":
        return 0.0
    return sum(r.size for loc in nation.locations(world) for r in loc.records if r.cls is ClassId.RETAINERS)


def state_authority_update(nation: Nation, world: World, params: Params) -> None:
    """MM §12's full recurrence, minus the `-spent` term: spending is deducted
    immediately at the point of expenditure (`legislation.enact`/`repeal`/`veto`,
    Focus upkeep), which is the only way `actions.validate` can gate a sovereign
    from overspending within a year — see DEVIATIONS.md for why re-subtracting a
    `spent` figure here would double-count."""

    p = params.politics
    s = nation.scalars
    m_term = (s.M_state / s.M) * math.log1p(s.M) if s.M > 0 else 0.0
    law_term = sum(
        _law_weight(law) * state.enforcement for law, state in nation.laws.items() if state.enacted
    )
    s.R_private = r_private(nation, world)

    a_s = (
        (1.0 - p.a_s_decay) * s.A_S
        + p.a1 * m_term
        + p.a2 * s.J
        + p.a3 * law_term
        + p.a4 * s.direct_share
        + p.a5 * max(0.0, s.O)
        + p.a6 * math.log1p(max(0.0, s.court))
        - p.b1 * max(0.0, -s.O)
        - p.b2 * math.log1p(max(0.0, s.R_private))
        - p.b3 * math.log1p(max(0.0, s.U_dis))
        - p.b4 * s.farmed_share
    )
    s.A_S = max(0.0, a_s)


def on_tamed_animal(nation: Nation, world: World) -> None:
    """Handover (DD §3, §7.3): `A_S := authority of the largest herd-owner record`;
    `seat := CHIEF`. Computes that record's authority fresh (rather than reading a
    possibly-stale `record.authority`) since band.py's automatic taming can create
    the HERD_OWNERS record the same year, before step 12a has had a chance to run
    on it."""

    best_authority = 0.0
    for location in nation.locations(world):
        record = location.record(ClassId.HERD_OWNERS)
        if record is None or record.size <= 0:
            continue
        w_nat = basket_cost(location.market.price)
        dependents_r = dependents_of(record, location)
        record.authority = record_authority(record, nation.scalars.ell, w_nat, world.params, dependents_r)
        best_authority = max(best_authority, record.authority)
    nation.scalars.A_S = best_authority
    nation.seat = SeatKind.CHIEF


def on_settled(nation: Nation, world: World) -> None:
    """Handover when a band settles arable land without ever taming herds (DD §3,
    §7.3; DEVIATIONS A27): `A_S := authority of the largest land-share-holding
    record in the nation` (after `settle`/`found_field`, that's the TENANTS record
    it just created); `seat := CHIEF`. Structurally parallel to `on_tamed_animal`:
    computes that record's authority fresh (rather than reading a possibly-stale
    `record.authority`) since band.py's automatic settling can create the TENANTS
    record the same year, before step 12a has had a chance to run on it. No-ops if
    the nation has already handed over (e.g. via Tamed Animal)."""

    if nation.seat is not SeatKind.BAND:
        return

    best_record: Record | None = None
    best_location = None
    for location in nation.locations(world):
        for record in location.records:
            if record.wealth.land_shares <= 0:
                continue
            if best_record is None or record.wealth.land_shares > best_record.wealth.land_shares:
                best_record = record
                best_location = location

    a_s = 0.0
    size = 0.0
    if best_record is not None and best_location is not None:
        w_nat = basket_cost(best_location.market.price)
        dependents_r = dependents_of(best_record, best_location)
        best_record.authority = record_authority(
            best_record, nation.scalars.ell, w_nat, world.params, dependents_r
        )
        a_s = best_record.authority
        size = best_record.size

    nation.scalars.A_S = a_s
    nation.seat = SeatKind.CHIEF

    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=nation.id,
                kind="settled_handover",
                numbers={"A_S": a_s, "size": size},
            )
        )


def protection_of_property_condition(nation: Nation, world: World) -> tuple[bool, float, float, float]:
    """A one-time handover (structurally parallel to Tamed Animal), not a cycled
    demand-table entry: DD §7.4's named demand tables don't list it, and DD §7.3
    describes it the same way as the Tamed Animal handover. Not MM §13's
    self-enactment bar verbatim: that bar compares Landed's authority against
    `A_S + opposition`, but `on_tamed_animal` *initialises* `A_S` from a herd-
    owner's authority in the first place, so `A_S` starts at or above the very
    Landed authority the bar would need to beat — self-defeating by construction
    (see DEVIATIONS.md). Instead this reads DD §7.3's "small beside the Landed
    Interest" literally: Landed's authority is compared against a nominal weak-
    government baseline (`theta_prime * consensus_c0`, reusing the band-consensus
    constant as "what a minimal government commands") rather than against the
    nation's own (Landed-derived) `A_S`. Returns `(fires, authority_I, A_S,
    threshold)`."""

    landed = nation.interests.get(InterestId.LANDED, InterestState())
    lhs = landed.authority * (1.0 + landed.radicalism)
    threshold = world.params.politics.theta_prime * world.params.politics.consensus_c0
    fires = lhs > threshold
    # The other trigger: enough people that property needs protecting whatever the
    # Landed Interest commands (`PoliticsParams.custom_protection_of_property_pop`;
    # a threshold < 0 disables it).
    pop_threshold = world.params.politics.custom_protection_of_property_pop
    if pop_threshold >= 0 and nation.population(world) >= pop_threshold:
        fires = True
    return fires, landed.authority, nation.scalars.A_S, threshold


def on_protection_of_property(nation: Nation, world: World) -> None:
    """Handover (DD §7.3): the State record is created with `A_S` unchanged;
    `seat := STATE`. The State record is placed at the nation's most populous
    location (no "capital" concept exists yet — a reasonable stand-in, see
    DEVIATIONS.md)."""

    if nation.state is not None:
        return
    locations = nation.locations(world)
    if not locations:
        return
    capital = max(locations, key=lambda loc: sum(r.size for r in loc.records))
    state_record = Record(cls=ClassId.STATE, location=capital.id)
    capital.records.append(state_record)
    nation.state = state_record
    nation.seat = SeatKind.STATE
    law_state = nation.laws.setdefault(LawId.PROTECTION_OF_PROPERTY, LawState())
    law_state.enacted = True
    law_state.enacted_year = world.year
    from stock.politics.legislation import enforcement
    law_state.enforcement = enforcement(LawId.PROTECTION_OF_PROPERTY, nation, world)


def step_state(world: World) -> None:
    """Year step 12b: order signal, handovers, State authority, then justice and
    legibility (DD §7's own ordering within step 12). `state_authority_update`
    reads `nation.scalars.J` before this function's own justice pass overwrites it,
    so it naturally sees last year's `J` — the lag rule via plain sequencing, no
    `PrevSnapshot` extension needed."""

    for nation in world.nations.values():
        if nation.seat is SeatKind.BAND:
            continue  # the band's A_S is consensus, refilled in engine.band (Doc 02)

        nation.scalars.O = order_signal(events_this_year(nation.id, world), world.params)

        if nation.seat is SeatKind.CHIEF and nation.state is None:
            fires, authority_i, a_s, threshold = protection_of_property_condition(nation, world)
            if fires:
                on_protection_of_property(nation, world)
                if world.ledger is not None:
                    world.ledger.add_event(
                        EventRecord(
                            year=world.year,
                            nation=nation.id,
                            kind="protection_of_property",
                            numbers={"authority_I": authority_i, "A_S": a_s, "threshold": threshold},
                        )
                    )

        state_authority_update(nation, world, world.params)

        j = justice_level(nation, draw=nation.scalars.justice_draw, world=world)
        converted = convert_disorder(nation, j)
        nation.scalars.ell = legibility_update(nation, j, converted, world.params)
        nation.scalars.J = j
