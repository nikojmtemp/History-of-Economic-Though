"""Authority and apportionment — year step 12a (DD §2.5; MM §3)."""

from __future__ import annotations

from stock.core.goods import Good, basket_cost
from stock.core.params import Params
from stock.core.records import CLASS_TABLE, LABOUR_INTEREST_CLASSES, ClassId, InterestId, Record
from stock.core.world import InterestState, Location, Nation, World
from stock.engine.consumption import RETAINER_BUYING_CLASSES, SERVANT_BUYING_CLASSES


def dependents_of(record: Record, location: Location) -> float:
    """`dependents_r`: the RETAINERS/SERVANTS size this record maintains (DD §2.5's
    "d_dep x dependents"). RETAINERS/SERVANTS are one record per location (DD §2.1)
    bought by several buyer classes at once (`engine.consumption`'s buying-class
    sets), so a buyer's own dependents are apportioned by its share of this year's
    Attendance spend among that dependent class's buyers — the only information the
    model keeps that ties a dependent headcount back to a particular buyer."""

    if record.cls in RETAINER_BUYING_CLASSES:
        dependent_cls, buyers = ClassId.RETAINERS, RETAINER_BUYING_CLASSES
    elif record.cls in SERVANT_BUYING_CLASSES:
        dependent_cls, buyers = ClassId.SERVANTS, SERVANT_BUYING_CLASSES
    else:
        return 0.0

    dependent_record = location.record(dependent_cls)
    if dependent_record is None or dependent_record.size <= 0:
        return 0.0

    total_spend = sum(
        r.last_spend_by_good.get(Good.ATTENDANCE, 0.0) for r in location.records if r.cls in buyers
    )
    if total_spend <= 0:
        return 0.0
    own_spend = record.last_spend_by_good.get(Good.ATTENDANCE, 0.0)
    return dependent_record.size * (own_spend / total_spend)


def record_authority(
    record: Record, ell: float, w_nat: float, params: Params, dependents_r: float = 0.0
) -> float:
    """`authority_r = size_r^ks * W_r^kw + d_dep*dependents_r`, `W_r = assets + ell*
    size_r*w_nat` (MM §3). `dependents_r` is precomputed by the caller via
    `dependents_of` (needs `Location` context this function's plain signature
    doesn't carry). Land shares valued at `params.production.land_share_value`."""

    w = record.wealth.total(land_share_value=params.production.land_share_value) + ell * record.size * w_nat
    base = record.size ** params.authority.kappa_s * w ** params.authority.kappa_w
    return float(base + params.authority.d_dep * dependents_r)


def apportion(record: Record, ell: float, w_nat: float) -> dict[InterestId, float]:
    """The *share* (sums to 1) of `record`'s authority held as each Interest's asset
    class (DD §2.5's apportionment table), by wealth composition. LABOUR is
    special-cased: it isn't a `Wealth` field, it's `ell*size*w_nat` (MM §3) for
    records in `LABOUR_INTEREST_CLASSES`."""

    spec = CLASS_TABLE[record.cls]
    labour_component = ell * record.size * w_nat if record.cls in LABOUR_INTEREST_CLASSES else 0.0
    asset_components = {
        interest_id: getattr(record.wealth, field_name)
        for interest_id, field_name in spec.interest_assets.items()
    }

    total = sum(asset_components.values()) + labour_component
    if total <= 0:
        return {}
    shares = {i: v / total for i, v in asset_components.items() if v > 0}
    if labour_component > 0:
        shares[InterestId.LABOUR] = labour_component / total
    return shares


def interest_authority(nation: Nation, world: World) -> dict[InterestId, float]:
    """Recomputes every record's `authority` (written in place, MM §3) and sums each
    Interest's apportioned share across the nation (DD §2.5's "recomputed yearly" —
    not an accumulator; see the module Notes in build/03)."""

    totals: dict[InterestId, float] = dict.fromkeys(InterestId, 0.0)
    ell = nation.scalars.ell
    for location in nation.locations(world):
        w_nat = basket_cost(location.market.price)
        for record in location.records:
            if record.cls is ClassId.STATE:
                continue
            dependents_r = dependents_of(record, location)
            record.authority = record_authority(record, ell, w_nat, world.params, dependents_r)
            for interest_id, share in apportion(record, ell, w_nat).items():
                totals[interest_id] += record.authority * share
    return totals


def step_authority(world: World) -> None:
    """Year step 12a: recompute record authority and each nation's Interest
    authority (overwritten fresh, per the "recomputed yearly" note)."""

    for nation in world.nations.values():
        totals = interest_authority(nation, world)
        for interest_id, total in totals.items():
            nation.interests.setdefault(interest_id, InterestState()).authority = total
