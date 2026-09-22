"""Consumption, standing, and dependents — year step 5 (DD §5.1; MM §10).

**Doc 02 design choice** (see DEVIATIONS.md): MM presents "residual = income -
consumption; saved = p*residual" in §11 (hoards) as if independent of §10
(consumption), but applying a propensity split *twice* — once implicitly in how much
standing consumption happens, again in step 7's hoard rule — either double-counts or
leaves value unaccounted for. This module resolves it once: subsistence and comfort
are filled to their targets first, then the leftover splits between standing
consumption and saving via the *same* propensity, computed here and handed to
`engine.capital.hoard_update` as an already-known `saved` amount rather than
recomputed from scratch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from stock.core.goods import BASKET, Good, basket_cost
from stock.core.params import Params
from stock.core.records import ClassId, Record, set_size
from stock.core.world import Location, Nation, World
from stock.engine.market import record_demand
from stock.sim.ledger import EventRecord

#: Classes with no comfort/standing access at all (DD §5.1a table's "all" row) —
#: any surplus beyond subsistence is saved outright, not spent (see module docstring
#: for the general subsistence/comfort/standing/save split; these classes skip
#: straight from subsistence to save).
SUBSISTENCE_ONLY_CLASSES: frozenset[ClassId] = frozenset(
    {
        ClassId.HUNTERS,
        ClassId.HERDSMEN,
        ClassId.SERFS,
        ClassId.RETAINERS,
        ClassId.SERVANTS,
        ClassId.SOLDIERS,
    }
)

#: Whose Attendance purchases maintain RETAINERS vs SERVANTS (DD §2.2, §5.1c).
RETAINER_BUYING_CLASSES: frozenset[ClassId] = frozenset(
    {ClassId.LANDLORDS, ClassId.HERD_OWNERS, ClassId.CLERGY}
)
SERVANT_BUYING_CLASSES: frozenset[ClassId] = frozenset(
    {ClassId.MERCHANTS, ClassId.CAPITALISTS, ClassId.CRAFTSMEN, ClassId.TENANTS}
)


@dataclass
class Spend:
    by_good: dict[Good, float] = field(default_factory=dict)
    subsistence: float = 0.0
    comfort: float = 0.0
    standing_attendance: float = 0.0
    standing_luxuries: float = 0.0
    saved: float = 0.0
    productive: float = 0.0
    unproductive: float = 0.0
    a_subs: float = 1.0  # subsistence satisfaction, feeds population.py


#: Goods tagged unproductive when consumed (DD §5.1d): attendance, and (once they
#: exist) clergy/soldiers/court spending, which aren't goods classes so aren't listed.
UNPRODUCTIVE_GOODS: frozenset[Good] = frozenset({Good.ATTENDANCE})


def vanity(luxuries_reachable: float, params: Params) -> float:
    p = params.consumption
    return p.vanity_min + (p.vanity_max - p.vanity_min) * (
        1.0 - math.exp(-luxuries_reachable / p.vanity_scale_v0)
    )


def _ces_shares(weights_and_prices: dict[Good, tuple[float, float]], sigma: float) -> dict[Good, float]:
    """`share_g ∝ weight_g * P_g^-sigma` (MM §10), normalised to sum to 1."""

    raw = {g: w * (max(p, 1e-9) ** -sigma) for g, (w, p) in weights_and_prices.items() if w > 0}
    total = sum(raw.values())
    if total <= 0:
        return dict.fromkeys(weights_and_prices, 0.0)
    return {g: v / total for g, v in raw.items()}


def consume(record: Record, location: Location, propensity: float, params: Params) -> Spend:
    """MM §10: tiers filled in order, CES shares within a tier, standing split between
    Attendance and Luxuries by their standing yield per basket."""

    prices = location.market.price
    income = record.income
    spend = Spend()

    subsistence_target = record.size * basket_cost(prices, params.consumption.sigma_substitution)
    subsistence_spend = min(income, subsistence_target) if subsistence_target > 0 else 0.0
    if subsistence_target > 0:
        spend.a_subs = min(params.consumption.a_subs_cap, income / subsistence_target)
    elif record.size > 0:
        spend.a_subs = 0.0  # no basket obtainable, no satisfaction
    else:
        spend.a_subs = 1.0  # size is 0
    remaining = income - subsistence_spend

    sub_shares = _ces_shares(
        {g: (w, prices.get(g, 1.0)) for g, w in BASKET.items()}, params.consumption.sigma_substitution
    )
    for g, share in sub_shares.items():
        spend.by_good[g] = spend.by_good.get(g, 0.0) + subsistence_spend * share
    spend.subsistence = subsistence_spend

    if record.cls in SUBSISTENCE_ONLY_CLASSES:
        spend.saved = max(0.0, remaining)
        _tag_productive(spend)
        return spend

    comfort_open = record.cls != ClassId.LABOURERS or _labourer_wage_above_natural(record, prices, params)
    # Comfort's target has no MM anchor (only subsistence does); scaled off the
    # subsistence target by a tuned multiplier (see DEVIATIONS.md).
    m = params.consumption.comfort_target_multiplier
    comfort_target = subsistence_target * m if comfort_open else 0.0
    comfort_spend = min(max(0.0, remaining), comfort_target)
    if comfort_spend > 0:
        spend.by_good[Good.WARES] = spend.by_good.get(Good.WARES, 0.0) + comfort_spend
    spend.comfort = comfort_spend
    remaining -= comfort_spend

    remaining = max(0.0, remaining)
    standing_spend = (1.0 - propensity) * remaining
    saved = propensity * remaining
    spend.saved = saved

    if standing_spend > 0:
        luxuries_reachable = location.market.last_supply.get(Good.LUXURIES, 0.0)
        # No Luxuries reachable -> all standing is Attendance (DD §5.1c): there is
        # nothing to buy, not merely something unappealing, so the weight is a hard
        # 0 rather than vanity's floor `v_min` (which is for *some* access, however
        # thin — see `vanity`'s docstring intent).
        luxuries_weight = (
            params.consumption.s_lux * vanity(luxuries_reachable, params) if luxuries_reachable > 0 else 0.0
        )
        weights = {
            Good.ATTENDANCE: (params.consumption.s_att, prices.get(Good.ATTENDANCE, 1.0)),
            Good.LUXURIES: (luxuries_weight, prices.get(Good.LUXURIES, 1.0)),
        }
        shares = _ces_shares(weights, params.consumption.sigma_substitution)
        att_spend = standing_spend * shares.get(Good.ATTENDANCE, 0.0)
        lux_spend = standing_spend * shares.get(Good.LUXURIES, 0.0)
        spend.by_good[Good.ATTENDANCE] = spend.by_good.get(Good.ATTENDANCE, 0.0) + att_spend
        spend.by_good[Good.LUXURIES] = spend.by_good.get(Good.LUXURIES, 0.0) + lux_spend
        spend.standing_attendance = att_spend
        spend.standing_luxuries = lux_spend

    _tag_productive(spend)
    return spend


def _labourer_wage_above_natural(record: Record, prices: dict[Good, float], params: Params) -> bool:
    if record.size <= 0:
        return False
    return (record.income / record.size) > basket_cost(prices, params.consumption.sigma_substitution)


def _tag_productive(spend: Spend) -> None:
    for good, amount in spend.by_good.items():
        if good in UNPRODUCTIVE_GOODS:
            spend.unproductive += amount
        else:
            spend.productive += amount


def attendance_to_dependents(nation: Nation, world: World) -> list[dict[str, float]]:
    """Sets RETAINERS/SERVANTS sizes from this year's Attendance purchases (DD §5.1c) —
    the sole writer of those classes' `size`. Returns dismissal events (numbers only)."""

    events: list[dict[str, float]] = []
    for location in nation.locations(world):
        retainer_spend = sum(
            r.last_spend_by_good.get(Good.ATTENDANCE, 0.0)
            for r in location.records
            if r.cls in RETAINER_BUYING_CLASSES
        )
        servant_spend = sum(
            r.last_spend_by_good.get(Good.ATTENDANCE, 0.0)
            for r in location.records
            if r.cls in SERVANT_BUYING_CLASSES
        )
        events += _set_dependent_size(location, ClassId.RETAINERS, retainer_spend, world.params)
        events += _set_dependent_size(location, ClassId.SERVANTS, servant_spend, world.params)
    return events


def _set_dependent_size(
    location: Location, cls: ClassId, new_size: float, params: Params
) -> list[dict[str, float]]:
    record = location.record(cls)
    events: list[dict[str, float]] = []
    # One person is the smallest household: an Attendance purchase that would keep
    # less than that keeps nobody (`PopulationParams.extinct_size_epsilon`).
    if new_size < params.population.extinct_size_epsilon:
        new_size = 0.0
    if record is None:
        if new_size <= 0:
            return events
        record = Record(cls=cls, location=location.id)
        location.records.append(record)
    old_size = record.size
    if old_size > 0 and new_size < old_size * params.consumption.dismissal_threshold:
        dismissed = old_size - new_size
        events.append({"dismissed": dismissed, "old_size": old_size, "new_size": new_size})
        _dismiss_to_labourers(location, dismissed)
    set_size(record, new_size, allow_derived=True)
    return events


def _dismiss_to_labourers(location: Location, dismissed: float) -> None:
    """A dismissed dependent becomes a free labourer (DD §2.4: "retainer -> labourer
    (dismissal)"); dependents own no wealth (CLASS_TABLE), so nothing moves but size."""

    labourers = location.record(ClassId.LABOURERS)
    if labourers is None:
        labourers = Record(cls=ClassId.LABOURERS, location=location.id)
        location.records.append(labourers)
    labourers.size += dismissed


def step_consumption(world: World) -> None:
    """Year step 5. Stores `last_spend_by_good` for `market_size` (Doc 02's
    engine.market) to read next time it runs, and hands `saved` off to `record.income`
    ready for step 7's hoard_update (which receives it as an already-known amount).

    Also handles STATE record consumption (court draw, Doc 05) and Poor Rate transfers (Doc 05).
    """

    from stock.engine.capital import propensity as compute_propensity

    for nation in world.nations.values():
        # --- Poor Rate transfers (Doc 05) — paid *before* the records consume, so the
        # transfer is income this year and `saved` is logged once; the shortfall that
        # sizes each record's share is last year's `A.subsistence` (lag rule).
        transfers_draw = nation.scalars.transfers_draw
        if transfers_draw > 0:
            shortfall_records: list[tuple[Record, float]] = []
            total_shortfall = 0.0
            for location in nation.locations(world):
                for r in location.records:
                    if r.cls in (ClassId.LABOURERS, ClassId.SERFS):
                        shortfall = max(0.0, 1.0 - r.A.subsistence)
                        if shortfall > 0:
                            shortfall_records.append((r, shortfall))
                            total_shortfall += shortfall
            if total_shortfall > 0:
                for r, shortfall in shortfall_records:
                    r.income += transfers_draw * (shortfall / total_shortfall)
                nation.add_flow("transfers", transfers_draw)

        for location in nation.locations(world):
            for record in location.records:
                if record.cls is ClassId.STATE:
                    continue  # handled below: the court draw (Doc 05)
                record.last_gross_income = record.income
                nation.add_flow("gross_income", record.income)
                p = compute_propensity(record, nation.scalars.r_bar, world.params)
                spend = consume(record, location, p, world.params)
                record.last_spend_by_good = spend.by_good
                record.A.subsistence = spend.a_subs  # feeds population.py's A_subs
                record.income = spend.saved  # residual carried to step 7 as pre-saved
                consumption_total = sum(spend.by_good.values())
                nation.add_flow("consumption", consumption_total)
                nation.add_flow("consumption_productive", spend.productive)
                nation.add_flow("consumption_unproductive", spend.unproductive)
                nation.add_flow("saved", spend.saved)
                for good, amount in spend.by_good.items():
                    if amount > 0:
                        record_demand(location, good, amount)

            # --- STATE record consumption (court draw, Doc 05) ---
            state_record = location.record(ClassId.STATE)
            if state_record is not None:
                state_record.income = nation.scalars.court
                state_record.last_gross_income = state_record.income
                nation.add_flow("gross_income", state_record.income)
                spend = consume(state_record, location, 1.0, world.params)  # p=1.0 (always consume)
                state_record.last_spend_by_good = spend.by_good
                nation.add_flow("consumption", sum(spend.by_good.values()))
                nation.add_flow("consumption_unproductive", sum(spend.by_good.values()))
                # DD §5.3: "The State: revenue unspent -> treasure". The unspent court draw
                # is the State's hoard, so it is logged as saved/to_hoard (Doc 08's hoard
                # identity) and never reaches step 7's per-record hoard rule.
                nation.add_flow("saved", spend.saved)
                nation.add_flow("to_hoard", spend.saved)
                nation.scalars.treasure += spend.saved
                state_record.income = 0.0
                for good, amount in spend.by_good.items():
                    if amount > 0:
                        record_demand(location, good, amount)

        events = attendance_to_dependents(nation, world)
        if world.ledger is not None:
            for e in events:
                world.ledger.add_event(
                    EventRecord(year=world.year, nation=nation.id, kind="retainer_dismissal", numbers=e)
                )
