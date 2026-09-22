"""Expected needs, unrest, and its expression — year step 11 (DD §8; MM §20)."""

from __future__ import annotations

from enum import Enum, auto

from stock.core.goods import Tier, basket_cost
from stock.core.params import Params
from stock.core.records import ClassId, InterestId, Record
from stock.core.world import InterestState, World
from stock.politics.authority import apportion
from stock.politics.interests import radicalism_update
from stock.sim.ledger import EventRecord

_TIERS: tuple[Tier, ...] = (Tier.SUBSISTENCE, Tier.COMFORT, Tier.STANDING)


def expected_needs_update(record: Record, alpha_up: float, alpha_down: float) -> None:
    """`E' = E + alpha_up*max(0,A-E) - alpha_down*max(0,E-A)` (MM §20), per tier.
    During a regression, Doc 05 passes `params.unrest.alpha_collapse` in place of
    `alpha_down` (DD §8.1) — this function doesn't branch on a flag itself."""

    for tier in _TIERS:
        a, e = record.A[tier], record.E[tier]
        record.E[tier] = e + alpha_up * max(0.0, a - e) - alpha_down * max(0.0, e - a)


def unrest(record: Record, params: Params) -> float:
    """`U_r = size_r * Sum_tier w_tier*phi_tier(shortfall_tier)`, `shortfall = max(0,
    E-A)/E`, `phi_subs = x^2`, others linear (MM §20)."""

    p = params.unrest
    weights = (
        (Tier.SUBSISTENCE, p.w_tier_subsistence),
        (Tier.COMFORT, p.w_tier_comfort),
        (Tier.STANDING, p.w_tier_standing),
    )
    total = 0.0
    for tier, w in weights:
        a, e = record.A[tier], record.E[tier]
        shortfall = max(0.0, e - a) / e if e > 0 else 0.0
        phi = shortfall * shortfall if tier is Tier.SUBSISTENCE else shortfall
        total += w * phi
    return record.size * total


class Expression(Enum):
    DISORDER = auto()
    DEMAND = auto()


def expression(record: Record, params: Params) -> Expression:
    """`authority_r/size_r < a_split` -> DISORDER, else DEMAND (DD §8.2)."""

    if record.size <= 0:
        return Expression.DEMAND
    is_disorder = (record.authority / record.size) < params.unrest.a_split
    return Expression.DISORDER if is_disorder else Expression.DEMAND


def loyalty(soldier_record: Record) -> float:
    """`loyalty = 1 - shortfall_subs` (MM §20)."""

    a, e = soldier_record.A[Tier.SUBSISTENCE], soldier_record.E[Tier.SUBSISTENCE]
    shortfall = max(0.0, e - a) / e if e > 0 else 0.0
    return 1.0 - shortfall


def _disorder_events(
    record: Record, u: float, params: Params, year: int, nation_id: str
) -> list[EventRecord]:
    """Strike at `u1`; riot at `u2` (desertion instead, for SOLDIERS); revolt at `u3`
    (mutiny instead, for SOLDIERS) — MM §20's threshold events, split per DD §8's
    doc-03 deliverable listing all four by name. `record.strike_years` (read by
    engine/wages.py) is written here."""

    p = params.unrest
    events: list[EventRecord] = []
    ratio = u / record.size if record.size > 0 else 0.0
    is_soldiers = record.cls is ClassId.SOLDIERS
    numbers = {"U": u, "size": record.size, "ratio": ratio}

    if ratio > p.u1:
        record.strike_years += 1
        events.append(EventRecord(year=year, nation=nation_id, kind="strike", numbers=numbers))
    else:
        record.strike_years = 0

    if ratio > p.u3:
        kind = "mutiny" if is_soldiers else "revolt"
        events.append(EventRecord(year=year, nation=nation_id, kind=kind, numbers=numbers))
    elif ratio > p.u2:
        kind = "desertion" if is_soldiers else "riot"
        events.append(EventRecord(year=year, nation=nation_id, kind=kind, numbers=numbers))

    return events


def step_unrest(world: World) -> None:
    """Year step 11. Updates `E`, computes `U_r`, classifies disorder vs. demand,
    fires threshold events, sets `emigration_pressure`, accumulates `U_dis`, and
    feeds demand-branch unrest into each Interest's radicalism (apportioned by the
    same wealth-composition shares `politics.authority.apportion` uses for
    authority — the natural reading of "high-authority records" turning into a
    named Interest's political demand).

    Under repression (nation.scalars.army_inside), strike/riot/revolt events are
    suppressed, but U_dis is still computed for later use."""

    p = world.params
    for nation in world.nations.values():
        u_dis = 0.0
        demand_unrest_by_interest: dict[InterestId, float] = {}
        # A record below `event_min_share` of the nation's people has nobody to
        # fill a street: its unrest still counts in U_dis, but it fires no event
        # (a one-person record's yearly "revolt" was a regression trigger every
        # year — see DEVIATIONS-IN-PROGRESS.md A70).
        people = sum(r.size for loc in nation.locations(world) for r in loc.records)
        crowd = p.unrest.event_min_share * people
        for location in nation.locations(world):
            w_nat = basket_cost(location.market.price)
            for record in location.records:
                # A record below the extinct threshold has nobody to strike: it is dust
                # awaiting step 8's reaper, and its `U/size` ratio is meaningless (a
                # 1e-300-person record "revolted" every year, an `O -2` that drained
                # A_S in every STATE nation — see DEVIATIONS.md A31).
                if record.cls is ClassId.STATE or record.size < p.population.extinct_size_epsilon:
                    continue
                expected_needs_update(record, p.unrest.alpha_up, p.unrest.alpha_down)
                u = unrest(record, p)
                expr = expression(record, p)
                if expr is Expression.DISORDER:
                    u_dis += u
                    record.emigration_pressure = min(1.0, u / record.size) if record.size > 0 else 0.0
                    # Suppress disorder events under repression
                    if not nation.scalars.army_inside:
                        # (always classified, so `record.strike_years` keeps counting
                        # and resetting for engine/wages.py; only the event is gated)
                        events = _disorder_events(record, u, p, world.year, nation.id)
                        if world.ledger is not None and record.size >= crowd:
                            for e in events:
                                world.ledger.add_event(e)
                else:
                    record.emigration_pressure = 0.0
                    for interest_id, share in apportion(record, nation.scalars.ell, w_nat).items():
                        prior = demand_unrest_by_interest.get(interest_id, 0.0)
                        demand_unrest_by_interest[interest_id] = prior + u * share

        nation.scalars.U_dis = u_dis
        for interest_id, demand_unrest in demand_unrest_by_interest.items():
            state = nation.interests.setdefault(interest_id, InterestState())
            state.radicalism = radicalism_update(state.radicalism, demand_unrest, met=False, params=p)
