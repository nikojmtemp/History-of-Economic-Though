"""Taxation: instruments, assessment, evasion, collection, incidence, budget (step 3; Doc 05).

Instruments from DD §12.1 with rates in nation.tax_rates; assessment by class via assess();
evasion and collection via evasion() and collect() per MM §19; incidence computed lagged
(this year's borne_by is derived from last year's assessed_on, per the rule in PLAN.md's
"Step 1 addendum — session 3"). Budget distribution to draws.

Pre-State revenue (DD §12, chief's herd share / tithe flat draw / demesne / feudal dues) and
tax farming (DD §12.1) are pseudo-instruments identified by string keys rather than LawId,
because they either have no enacting law (herd share, demesne) or are a flat draw rather than
a rated instrument (tithe, when LawId.TITHE is not itself enacted).

Two lagged-state problems this module has to solve without adding fields to core/world.py
(out of scope for this task):

- **pi is written by wages.py in the *same* year** (step 2 runs before step 3), so at
  assessment time `record.last_pi` is *this* year's value, not last year's the incidence rule
  needs. It is stashed per class in a pseudo `IncidenceTable` keyed `_pi_key(instrument)` whose
  `assessed_on` dict is repurposed to hold {class: pi} for exactly this reason (see
  DEVIATIONS.md A25-cont: IncidenceTable has no dedicated pi field to touch without editing
  world.py). enf_CA needs no such stash: at step 3 of year t, `nation.laws[COMBINATION_ACT]
  .enforcement` still holds what step 12c wrote in year t-1 (naturally lagged by step order).
- **Tax farming's outstanding advance** is tracked the same way, under the pseudo key
  `_FARM_LOAN_KEY`: `instrument` holds the farmer's `(location_id, ClassId)` key, `collected`
  holds the amount owed back to the farmer next year.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from stock.core.actions import Action, ActionKind, register_cost_fn
from stock.core.goods import Good, basket_cost
from stock.core.laws import LawId
from stock.core.params import TaxParams
from stock.core.producers import JOB_CLASS, ProducerKind
from stock.core.records import ClassId, Record, Wealth, set_size
from stock.core.world import BudgetShares, IncidenceTable, Nation, SeatKind, World
from stock.politics.justice import justice_need
from stock.security.military import Doctrine, active_doctrine, army_basket
from stock.sim.ledger import EventRecord

if TYPE_CHECKING:
    from stock.core.params import Params

#: An instrument key: a real LawId, or one of this module's pseudo-instrument string keys
#: (pre-State revenue, tax farming, and the pi/farm-loan stashes below).
InstrumentId = LawId | str

#: Base type for each revenue instrument (DD §12.1).
Base = str  # "rent" | "field_produce" | "heads" | "wages" | "profit" | etc.

#: Pre-State pseudo-instrument keys (no enacting law; DD §12's "revenue as it grows").
HERD_SHARE = "HERD_SHARE"
TITHE_FLAT = "TITHE_FLAT"
DEMESNE = "DEMESNE"
FEUDAL_DUES = "FEUDAL_DUES"

#: Pseudo-instrument prefix for the lagged pi stash (see module docstring).
_PI_PREFIX = "PI__"

#: Pseudo-instrument key for the outstanding tax-farming advance (see module docstring).
_FARM_LOAN_KEY = "FARM_LOAN"

#: Map instrument -> base for all DD §12.1 rated instruments plus the pre-State draws.
INSTRUMENT_BASE: dict[InstrumentId, Base] = {
    LawId.LAND_TAX: "rent",
    LawId.TITHE: "field_produce",
    LawId.CAPITATION: "heads",
    LawId.WAGE_TAX: "wages",
    LawId.PROFIT_TAX: "profit",
    LawId.EXCISE_PROVISIONS: "consumption_provisions",
    LawId.EXCISE_WARES: "consumption_wares",
    LawId.EXCISE_LUXURIES: "consumption_luxuries",
    LawId.CUSTOMS: "customs",
    LawId.TOLLS: "tolls",
    LawId.TAX_FARMING: "to_be_farmed",
    LawId.SALE_OF_CROWN_LANDS: "crown_lands",
    LawId.SINGLE_TAX_ON_RENT: "rent",
    LawId.POOR_RATE: "rent",
    HERD_SHARE: "herd_share",
    TITHE_FLAT: "field_produce",
    DEMESNE: "demesne",
    FEUDAL_DUES: "feudal_dues",
}

#: Base mobility (evasion propensity) per base type (MM §19).
BASE_MOBILITY: dict[Base, float] = {
    "rent": 0.0,
    "field_produce": 0.0,
    "heads": 0.2,
    "wages": 0.5,
    "profit": 1.0,
    "consumption_provisions": 0.3,
    "consumption_wares": 0.3,
    "consumption_luxuries": 0.3,
    "customs": 0.3,
    "tolls": 0.0,
    "to_be_farmed": 0.5,
    "crown_lands": 0.0,
    "herd_share": 0.0,
    "demesne": 0.0,
    "feudal_dues": 0.0,
}

#: Classes assessed on each rated instrument (DD §12.1). Tithe has no entry here —
#: correction round: DD §12.1's base is "gross field produce", assessed on *whoever
#: owns the fields* (`owners_land`, which varies per producer/scenario — TENANTS in
#: three_bands.yaml's valley); "falls on rent" (§12.2) is incidence, not the payer
#: set, so Tithe's payer classes are computed dynamically by `_field_owner_produce`.
ASSESSED_CLASSES: dict[LawId, frozenset[ClassId]] = {
    LawId.LAND_TAX: frozenset({ClassId.LANDLORDS}),
    LawId.CAPITATION: frozenset({ClassId.LABOURERS, ClassId.SERFS, ClassId.HERDSMEN}),
    LawId.WAGE_TAX: frozenset(
        {ClassId.LABOURERS, ClassId.CRAFTSMEN, ClassId.TENANTS, ClassId.MERCHANTS}
    ),
    LawId.PROFIT_TAX: frozenset({ClassId.MERCHANTS, ClassId.CAPITALISTS}),
    LawId.EXCISE_PROVISIONS: frozenset({ClassId.LABOURERS, ClassId.SERFS}),
    LawId.EXCISE_WARES: frozenset({ClassId.LABOURERS, ClassId.CRAFTSMEN, ClassId.MERCHANTS}),
    LawId.EXCISE_LUXURIES: frozenset(
        {ClassId.LANDLORDS, ClassId.CAPITALISTS, ClassId.MERCHANTS}
    ),
    LawId.CUSTOMS: frozenset({ClassId.MERCHANTS}),
    LawId.TOLLS: frozenset({ClassId.MERCHANTS}),
    LawId.SINGLE_TAX_ON_RENT: frozenset({ClassId.LANDLORDS}),
    LawId.POOR_RATE: frozenset({ClassId.LANDLORDS}),
}

#: Rated instruments whose burden shifts through the wage bargain (MM §8's pi, applied at
#: step 6's incidence rule): wage tax, excises on Provisions/Wares, capitation.
PI_SHIFT_BASES: frozenset[Base] = frozenset(
    {"wages", "consumption_provisions", "consumption_wares", "heads"}
)

#: Bases that never shift (DD §12.2: "rent taxes don't shift"): land tax, single tax on
#: rent, poor rate, tithe (rated or flat), demesne, feudal dues, herd share.
NO_SHIFT_BASES: frozenset[Base] = frozenset(
    {"rent", "field_produce", "herd_share", "demesne", "feudal_dues"}
)

#: Which budget draw each instrument-bearing law funds (DD §12.2's "a Landed Interest that
#: blocks the land tax..."; politics/legislation.py's lapse_unenforceable reads the result).
LAW_PAYER_DRAW: dict[LawId, str] = {
    LawId.STANDING_ARMY_ACT: "defence",
    LawId.MILITIA_ACT: "defence",
    LawId.ADMINISTRATION_OF_JUSTICE: "justice",
    LawId.POOR_RATE: "transfers",
    LawId.PUBLIC_CREDIT: "service",
}


def _pi_key(instrument: InstrumentId) -> str:
    name = instrument.name if isinstance(instrument, LawId) else str(instrument)
    return f"{_PI_PREFIX}{name}"


@dataclass
class Assessment:
    """One instrument's assessment this year: the rate actually used (so `collect`/
    `evasion` never re-derive it from the amount, T1b's fix for the skeleton's garbage
    `assessed/max(assessed,1.0)` rate proxy) and the amount assessed by class."""

    rate: float
    by_class: dict[ClassId, float] = field(default_factory=dict)

    def total(self) -> float:
        return sum(self.by_class.values())


def evasion(
    rate: float, certainty: float, base_mobility: float, enforcement: float, params: TaxParams
) -> float:
    """MM §19: evasion = g_e(rate, certainty, mobility) * (1 - enf_instrument).

    Args:
        rate: tax rate on the base
        certainty: 1 - farmed_share (last year's, naturally lagged by call order)
        base_mobility: base-type mobility (from BASE_MOBILITY)
        enforcement: instrument enforcement strength in [0, 1]
        params: tax parameters
    """

    g_e = (
        rate * params.evasion_rate_slope
        + base_mobility * params.evasion_mobility_weight
        - certainty * params.evasion_certainty_weight
    )
    g_e = max(0.0, min(params.evasion_cap, g_e))
    return g_e * (1.0 - enforcement)


def _rate_for(nation: Nation, law_id: LawId, params: TaxParams) -> float:
    return float(nation.tax_rates.get(law_id, params.default_rate))


def _get_rent_base(nation: Nation) -> float:
    """Total rent (this year's flows['rent'], written by production.py at step 1)."""
    return nation.flows.get("rent", 0.0)


def _get_field_produce_base(nation: Nation, world: World) -> float:
    """Gross field produce: sum of FIELD producers' last_V (this year, step 1)."""
    return sum(
        p.last_V
        for loc in nation.locations(world)
        for p in loc.producers
        if p.kind is ProducerKind.FIELD
    )


def _field_owner_produce(nation: Nation, world: World) -> dict[ClassId, float]:
    """Gross FIELD produce (this year's last_V), attributed to each owning class pro
    rata to that producer's `owners_land` shares. DD §12.1: Tithe's base is "gross
    field produce" and it is assessed on *whoever owns the fields* — "falls on rent"
    (§12.2) describes incidence, not the payer set, so Tithe (rated or the flat
    pre-State draw) must be debited from the actual owners_land classes, not
    LANDLORDS unconditionally (correction round: in three_bands.yaml's valley the
    FIELDs are owned by TENANTS, so a LANDLORDS-only debit was silently always 0)."""

    result: dict[ClassId, float] = {}
    for loc in nation.locations(world):
        for p in loc.producers:
            if p.kind is not ProducerKind.FIELD or p.last_V <= 0 or not p.owners_land:
                continue
            total_share = sum(p.owners_land.values()) or 1.0
            for cls, share in p.owners_land.items():
                result[cls] = result.get(cls, 0.0) + p.last_V * (share / total_share)
    return result


def _assess_by_class(
    nation: Nation, world: World, rate: float, classes: frozenset[ClassId]
) -> dict[ClassId, float]:
    """A per-capita tax by class (capitation)."""
    result: dict[ClassId, float] = {}
    for cls in classes:
        total = sum(r.size for loc in nation.locations(world) for r in loc.records if r.cls is cls)
        if total > 0:
            result[cls] = total * rate
    return result


def _assess_wages(nation: Nation, world: World, rate: float) -> dict[ClassId, float]:
    """Wage tax assessed on the wage bill (this year's gross income) of bargaining classes."""
    result: dict[ClassId, float] = {}
    for cls in ASSESSED_CLASSES[LawId.WAGE_TAX]:
        total = sum(
            max(0.0, r.income)
            for loc in nation.locations(world)
            for r in loc.records
            if r.cls is cls
        )
        if total > 0:
            result[cls] = total * rate
    return result


def _assess_profit(nation: Nation, world: World, rate: float) -> dict[ClassId, float]:
    """Profit tax on MERCHANTS'/CAPITALISTS' stock at r_bar (MM §5's r_bar * stock)."""
    result: dict[ClassId, float] = {}
    r_bar = nation.scalars.r_bar
    if r_bar <= 0:
        return result
    for cls in ASSESSED_CLASSES[LawId.PROFIT_TAX]:
        stock = sum(
            r.wealth.stock_in_place
            for loc in nation.locations(world)
            for r in loc.records
            if r.cls is cls
        )
        if stock > 0:
            result[cls] = r_bar * stock * rate
    return result


def _assess_by_good_consumption(
    nation: Nation, world: World, good: Good, rate: float, classes: frozenset[ClassId]
) -> dict[ClassId, float]:
    """Excise on last year's spend on `good` (lagged naturally: last_spend_by_good is
    written by consumption.py at step 5, read here at step 3 before this year's spend
    exists)."""
    result: dict[ClassId, float] = {}
    for loc in nation.locations(world):
        for r in loc.records:
            if r.cls not in classes:
                continue
            spend = r.last_spend_by_good.get(good, 0.0)
            if spend > 0:
                result[r.cls] = result.get(r.cls, 0.0) + spend * rate
    return result


def _get_customs_base(nation: Nation, world: World) -> float:
    total = 0.0
    for route in world.routes.values():
        if _route_belongs_to_nation(route, nation, world):
            total += route.customs_collected
    return total


def _route_belongs_to_nation(route: Any, nation: Nation, world: World) -> bool:
    for loc_id in (route.a, route.b):
        loc = world.locations.get(loc_id)
        if loc is not None and loc.nation == nation.id:
            return True
    return False


def _get_tolls_base(nation: Nation, world: World, params: TaxParams) -> float:
    if nation.focus is None or nation.focus.kind.name != "PUBLIC_WORKS":
        return 0.0
    trade_vol = sum(
        v
        for (a, b), v in world.trade_volume.items()
        if a == nation.id or b == nation.id
    )
    return trade_vol * params.toll_base_share


def assess(nation: Nation, world: World, params: TaxParams) -> dict[LawId, Assessment]:
    """Assess each enacted rated instrument by class (DD §12.1, MM §19).

    Returns {LawId: Assessment(rate, by_class)}. Pre-State draws and tax farming are
    handled separately by `step_taxation` (they are not laws in the same sense, or —
    for tax farming — the amount depends on last year's collections, not a base × rate
    read here).
    """

    assessed: dict[LawId, Assessment] = {}

    def _enacted(law_id: LawId) -> bool:
        state = nation.laws.get(law_id)
        return state is not None and state.enacted

    for law_id in (LawId.LAND_TAX, LawId.SINGLE_TAX_ON_RENT, LawId.POOR_RATE):
        if not _enacted(law_id):
            continue
        rate = _rate_for(nation, law_id, params)
        base_val = _get_rent_base(nation)
        assessed[law_id] = Assessment(rate, {ClassId.LANDLORDS: base_val * rate})

    if _enacted(LawId.TITHE):
        rate = _rate_for(nation, LawId.TITHE, params)
        by_owner = {
            cls: produce * rate for cls, produce in _field_owner_produce(nation, world).items()
        }
        assessed[LawId.TITHE] = Assessment(rate, by_owner)

    if _enacted(LawId.CAPITATION):
        rate = _rate_for(nation, LawId.CAPITATION, params)
        assessed[LawId.CAPITATION] = Assessment(
            rate, _assess_by_class(nation, world, rate, ASSESSED_CLASSES[LawId.CAPITATION])
        )

    if _enacted(LawId.WAGE_TAX):
        rate = _rate_for(nation, LawId.WAGE_TAX, params)
        assessed[LawId.WAGE_TAX] = Assessment(rate, _assess_wages(nation, world, rate))

    if _enacted(LawId.PROFIT_TAX):
        rate = _rate_for(nation, LawId.PROFIT_TAX, params)
        assessed[LawId.PROFIT_TAX] = Assessment(rate, _assess_profit(nation, world, rate))

    for law_id, good in (
        (LawId.EXCISE_PROVISIONS, Good.PROVISIONS),
        (LawId.EXCISE_WARES, Good.WARES),
        (LawId.EXCISE_LUXURIES, Good.LUXURIES),
    ):
        if not _enacted(law_id):
            continue
        rate = _rate_for(nation, law_id, params)
        assessed[law_id] = Assessment(
            rate, _assess_by_good_consumption(nation, world, good, rate, ASSESSED_CLASSES[law_id])
        )

    if _enacted(LawId.CUSTOMS):
        rate = _rate_for(nation, LawId.CUSTOMS, params)
        base_val = _get_customs_base(nation, world)
        assessed[LawId.CUSTOMS] = Assessment(rate, {ClassId.MERCHANTS: base_val * rate})

    if _enacted(LawId.TOLLS):
        rate = _rate_for(nation, LawId.TOLLS, params)
        base_val = _get_tolls_base(nation, world, params)
        if base_val > 0:
            assessed[LawId.TOLLS] = Assessment(rate, {ClassId.MERCHANTS: base_val * rate})

    sale_law = nation.laws.get(LawId.SALE_OF_CROWN_LANDS)
    if sale_law is not None and sale_law.enacted and nation.state is not None:
        rate = _rate_for(nation, LawId.SALE_OF_CROWN_LANDS, params)
        assessed[LawId.SALE_OF_CROWN_LANDS] = Assessment(
            rate, {ClassId.STATE: nation.state.wealth.land_shares * rate}
        )

    return assessed


def collect(
    assessed: dict[LawId, Assessment], nation: Nation, world: World, params: Params
) -> tuple[float, dict[str, float], float, list[EventRecord]]:
    """Collect assessed taxes from payers, after evasion and cost (MM §19).

    Debits `collected_before_cost = assessed * (1 - evasion)` from payers' income (capped
    at what's available — the rest is recorded as `tax_uncollectable`, not a negative
    income). Of that, `collection_cost_share` is diverted to the COLLECTORS record (the
    caller credits it) rather than vanishing, so the identity payer-loss ==
    revenue-gain + collectors-gain + evaded-and-kept-by-payer holds.

    Returns (total_collected, flows, total_collection_cost, uncollectable_events).
    """

    flows = {"tax_collected": 0.0, "tax_assessed": 0.0}
    collected_total = 0.0
    cost_total = 0.0
    events: list[EventRecord] = []

    n_instruments = len(assessed)
    collection_cost_share = min(
        params.tax.collection_cost_cap, params.tax.collection_cost_per_instrument * n_instruments
    )
    certainty = 1.0 - nation.scalars.farmed_share  # last year's, read before this year's write

    for law_id, entry in assessed.items():
        assessed_amount = entry.total()
        flows["tax_assessed"] += assessed_amount
        if assessed_amount <= 0:
            continue

        base = INSTRUMENT_BASE.get(law_id, "unknown")
        law_state = nation.laws.get(law_id)
        instrument_enforcement = law_state.enforcement if law_state is not None else 0.0
        base_mobility = BASE_MOBILITY.get(base, params.tax.evasion_mobility_default)
        evasion_share = evasion(
            entry.rate, certainty, base_mobility, instrument_enforcement, params.tax
        )

        for cls, amount in entry.by_class.items():
            if amount <= 0:
                continue
            records = [
                r for loc in nation.locations(world) for r in loc.records if r.cls is cls
            ]
            class_total_size = sum(r.size for r in records) or 1.0
            for r in records:
                share = r.size / class_total_size
                owed_before_cost = amount * share * (1.0 - evasion_share)
                to_debit = min(owed_before_cost, max(0.0, r.income))
                if owed_before_cost - to_debit > 1e-9:
                    events.append(
                        EventRecord(
                            year=world.year,
                            nation=nation.id,
                            kind="tax_uncollectable",
                            numbers={
                                "owed": owed_before_cost,
                                "shortfall": owed_before_cost - to_debit,
                            },
                        )
                    )
                r.income -= to_debit
                cost = to_debit * collection_cost_share
                cost_total += cost
                collected_total += to_debit - cost
                flows["tax_collected"] += to_debit - cost

    return collected_total, flows, cost_total, events


def basket_tax(nation: Nation) -> float:
    """Tax on the subsistence basket (EXCISE_PROVISIONS + EXCISE_WARES + WAGE_TAX).

    Used by wages.natural_wage() to adjust w_nat. Reads nation.tax_rates at step 3+.
    This is a read of rates (policy state set by step 14), so the order is safe per the
    lag rule (rates are not this-year flow income).
    """

    from stock.core.goods import BASKET

    prov_rate = nation.tax_rates.get(LawId.EXCISE_PROVISIONS, 0.0)
    wares_rate = nation.tax_rates.get(LawId.EXCISE_WARES, 0.0)
    wage_rate = nation.tax_rates.get(LawId.WAGE_TAX, 0.0)

    return (
        prov_rate * BASKET.get(Good.PROVISIONS, 0.0) + wares_rate * BASKET.get(Good.WARES, 0.0) + wage_rate
    )


# --- Pre-State revenue (DD §12; PLAN.md addendum: "applies whenever seat != BAND") ---


def _chief_herd_share(nation: Nation, world: World, params: TaxParams) -> float:
    """DD §12: "herds: the chief's own herd" — a share of the herd's *produce*, not
    of herd growth itself. Growth sits at ~0 (often slightly negative) once a herd
    reaches `graze_cap` (engine/production.py), which made a growth-based share
    structurally 0 for any mature herd (correction round). HERD_OWNERS' `record.
    income` at step 3 already holds this year's wages/profit/rent from step 1's
    split_rule — production has run, consumption hasn't — so it stands in for "the
    herd's produce" without re-deriving V. Debited from HERD_OWNERS' income pro
    rata, capped at what's available."""

    total_income = sum(
        max(0.0, r.income)
        for loc in nation.locations(world)
        for r in loc.records
        if r.cls is ClassId.HERD_OWNERS
    )
    if total_income <= 0:
        return 0.0
    draw = total_income * params.chief_herd_share
    return _debit_pro_rata(nation, world, ClassId.HERD_OWNERS, draw)


def _tithe_flat_draw(nation: Nation, world: World, params: TaxParams) -> dict[ClassId, float]:
    """A flat draw on gross FIELD produce when Tithe isn't itself an enacted rated
    instrument (DD §12: "fields... tithe"). Debited from each FIELD's `owners_land`
    classes pro rata to their share of gross produce (see `_field_owner_produce` —
    correction round: not LANDLORDS unconditionally, since fields may be
    tenant-owned), capped at what's available. Returns the amount actually debited
    per class."""

    tithe_law = nation.laws.get(LawId.TITHE)
    if tithe_law is not None and tithe_law.enacted:
        return {}  # already a rated instrument; assess()/collect() handle it
    produce_by_owner = _field_owner_produce(nation, world)
    if not produce_by_owner:
        return {}
    debited: dict[ClassId, float] = {}
    for cls, produce in produce_by_owner.items():
        draw = produce * params.tithe_flat_share
        amount = _debit_pro_rata(nation, world, cls, draw)
        if amount > 0:
            debited[cls] = amount
    return debited


def _demesne_rent(nation: Nation, world: World) -> float:
    """Rent on STATE-owned land shares (DD §12: "the crown demesne"). Debited from
    LANDLORDS' income (they hold the flow rent generated by `nation.flows['rent']`, per
    split_rule's payout) pro rata to the State's share of total land shares."""

    if nation.state is None:
        return 0.0
    total_rent = nation.flows.get("rent", 0.0)
    if total_rent <= 0:
        return 0.0
    total_land_shares = sum(
        r.wealth.land_shares for loc in nation.locations(world) for r in loc.records
    ) + nation.state.wealth.land_shares
    if total_land_shares <= 0:
        return 0.0
    demesne_rent = total_rent * (nation.state.wealth.land_shares / total_land_shares)
    return _debit_pro_rata(nation, world, ClassId.LANDLORDS, demesne_rent)


def _feudal_dues(nation: Nation, world: World, params: TaxParams) -> float:
    """A share of serfs' in-kind income under Serfdom (DD §12: "feudal dues")."""

    serfdom = nation.laws.get(LawId.SERFDOM)
    if serfdom is None or not serfdom.enacted:
        return 0.0
    serf_income = sum(
        max(0.0, r.income) for loc in nation.locations(world) for r in loc.records if r.cls is ClassId.SERFS
    )
    if serf_income <= 0:
        return 0.0
    draw = serf_income * params.feudal_dues_share
    return _debit_pro_rata(nation, world, ClassId.SERFS, draw)


def _debit_pro_rata(nation: Nation, world: World, cls: ClassId, amount: float) -> float:
    """Debit `amount` from all `cls` records' income pro rata to available income,
    capped so income never goes negative. Returns what was actually debited."""

    if amount <= 0:
        return 0.0
    records = [r for loc in nation.locations(world) for r in loc.records if r.cls is cls and r.income > 0]
    total_income = sum(r.income for r in records)
    if total_income <= 0:
        return 0.0
    target = min(amount, total_income)
    debited = 0.0
    for r in records:
        take = target * (r.income / total_income)
        r.income -= take
        debited += take
    return debited


# --- Tax farming (DD §12.1: "a credit instrument") ---


def _largest_merchant(nation: Nation, world: World) -> Record | None:
    best: Record | None = None
    best_size = 0.0
    for loc in nation.locations(world):
        for r in loc.records:
            if r.cls is ClassId.MERCHANTS and r.size > best_size:
                best = r
                best_size = r.size
    return best


def _tax_farming(
    nation: Nation,
    world: World,
    params: TaxParams,
    collected_this_year: float,
    last_year_incidence: dict[Any, IncidenceTable] | None,
) -> tuple[float, float]:
    """Repay last year's advance (if any) from this year's collections, then — if
    TAX_FARMING is enacted — advance a new lump sum from the largest MERCHANTS record's
    hoard against last year's actual collections (no more `collected * 0.2` literal).

    "Farmed instruments" are re-derived as whatever is enacted each year rather than a
    fixed cohort remembered from advance time — IncidenceTable can't hold a LawId roster
    without a world.py change; see DEVIATIONS.md.

    Returns (net_revenue_delta, farmed_share). `net_revenue_delta` is this year's advance
    (added to revenue) minus this year's repayment diverted away from revenue (a wash if
    both happen the same year; usually one or the other).
    """

    net_delta = 0.0
    diverted = 0.0

    last_loan = last_year_incidence.get(_FARM_LOAN_KEY) if last_year_incidence else None
    owed = last_loan.collected if last_loan is not None else 0.0
    farmer_key: tuple[str, ClassId] | None = (
        last_loan.instrument if (last_loan is not None and isinstance(last_loan.instrument, tuple)) else None
    )

    if owed > 0 and farmer_key is not None and collected_this_year > 0:
        loc = world.locations.get(farmer_key[0])
        farmer = loc.record(farmer_key[1]) if loc is not None else None
        if farmer is not None:
            diverted = min(owed, collected_this_year)
            payoff = min(diverted, farmer.wealth.loans_out)
            farmer.wealth.loans_out -= payoff
            farmer.income += diverted - payoff  # the premium, as income
            net_delta -= diverted
    owed_remaining = max(0.0, owed - diverted)

    farming_law = nation.laws.get(LawId.TAX_FARMING)
    new_key = farmer_key
    if farming_law is not None and farming_law.enacted:
        farmer = _largest_merchant(nation, world)
        if farmer is not None and farmer.wealth.hoard > 0:
            # Expected collection: last year's total collected across rated instruments
            # (read from this nation's last incidence, 0 in year 1) — DEVIATIONS.md A25.
            expected = sum(
                t.collected for key, t in (last_year_incidence or {}).items() if isinstance(key, LawId)
            )
            advance = min(params.farm_advance_share * expected, farmer.wealth.hoard)
            if advance > 0:
                farmer.wealth.hoard -= advance
                farmer.wealth.loans_out += advance
                net_delta += advance
                owed_remaining += advance * (1.0 + params.farm_premium)
                new_key = (farmer.location, farmer.cls)

    if nation.incidence is None:
        nation.incidence = {}
    if owed_remaining > 0 and new_key is not None:
        nation.incidence[_FARM_LOAN_KEY] = IncidenceTable(
            instrument=new_key, assessed_on={}, borne_by={}, collected=owed_remaining, cost=0.0
        )
    else:
        nation.incidence.pop(_FARM_LOAN_KEY, None)

    farmed_share = diverted / collected_this_year if collected_this_year > 0 else 0.0
    return net_delta, farmed_share


# --- Budget needs (DD §12.2's stacked bar) ---


def _defence_need(nation: Nation, world: World) -> float:
    soldiers_size = sum(
        r.size for loc in nation.locations(world) for r in loc.records if r.cls is ClassId.SOLDIERS
    )
    pay_need = nation.scalars.soldier_pay * soldiers_size if soldiers_size > 0 else 0.0
    doctrine = active_doctrine(nation, world)
    army_need = 0.0
    if doctrine in (Doctrine.STANDING_ARMY, Doctrine.MILITIA):
        basket = army_basket(nation, world, doctrine)
        base_price = world.params.prices.base_price
        army_need = sum(qty * base_price.get(good, 1.0) for good, qty in basket.items())
    return pay_need + army_need


def _transfers_need(nation: Nation, world: World, params: Params) -> float:
    poor_rate = nation.laws.get(LawId.POOR_RATE)
    if poor_rate is None or not poor_rate.enacted:
        return 0.0
    sigma = params.consumption.sigma_substitution
    need = 0.0
    for loc in nation.locations(world):
        cost = basket_cost(loc.market.price, sigma)
        for r in loc.records:
            if r.cls in (ClassId.LABOURERS, ClassId.SERFS):
                shortfall = max(0.0, 1.0 - r.A.subsistence)
                need += shortfall * r.size * cost
    return need


def _normalise_budget(nation: Nation, params: TaxParams) -> None:
    """Guarantee shares sum to 1.0 without ever raising (BudgetShares.validate() does
    raise, so step_taxation must not call it on a nation whose shares have drifted)."""

    b = nation.budget
    total = b.defence + b.justice + b.works + b.service + b.court + b.transfers
    if abs(total - 1.0) <= 1e-6:
        return
    if total > 0:
        nation.budget = BudgetShares(
            defence=b.defence / total,
            justice=b.justice / total,
            works=b.works / total,
            service=b.service / total,
            court=b.court / total,
            transfers=b.transfers / total,
        )
    else:
        d = params.default_budget
        nation.budget = BudgetShares(
            defence=d.get("defence", 0.4),
            justice=d.get("justice", 0.1),
            works=d.get("works", 0.2),
            service=d.get("service", 0.1),
            court=d.get("court", 0.1),
            transfers=d.get("transfers", 0.1),
        )


# --- Incidence (T1b: the core correction — see PLAN.md's addendum) ---


def _pi_by_class(nation: Nation, world: World, classes: frozenset[ClassId]) -> dict[ClassId, float]:
    """This year's pi, weighted by record size, per class (to be stashed and read back
    lagged next year)."""

    result: dict[ClassId, float] = {}
    for cls in classes:
        records = [
            r for loc in nation.locations(world) for r in loc.records if r.cls is cls and r.size > 0
        ]
        total_size = sum(r.size for r in records)
        if total_size <= 0:
            continue
        result[cls] = sum(r.last_pi * r.size for r in records) / total_size
    return result


def _distribute_shifted(
    shifted: float, payer_cls: ClassId, nation: Nation, world: World, borne_by: dict[ClassId, float]
) -> None:
    """The remainder of a shifted wage/consumption/capitation tax lands on the owner
    classes of the producers that employ `payer_cls`, pro rata to `owners_stock` (or
    `owners_land` for FIELDs). Aggregated nation-wide (weighted by filled jobs of that
    class), since Assessment/IncidenceTable are class-keyed, not location-keyed — see
    DEVIATIONS.md. Falls back to the payer if no owner can be identified, so the sum is
    always conserved."""

    if shifted <= 0:
        return
    owner_weight: dict[ClassId, float] = {}
    total_weight = 0.0
    for loc in nation.locations(world):
        for p in loc.producers:
            if JOB_CLASS.get(p.kind) is not payer_cls:
                continue
            weight = p.filled.get(payer_cls, 0.0)
            if weight <= 0:
                continue
            owners = p.owners_land if p.kind is ProducerKind.FIELD else p.owners_stock
            if not owners:
                continue
            for owner_cls, share in owners.items():
                owner_weight[owner_cls] = owner_weight.get(owner_cls, 0.0) + weight * share
                total_weight += weight * share
    if total_weight <= 0:
        borne_by[payer_cls] = borne_by.get(payer_cls, 0.0) + shifted
        return
    for owner_cls, w in owner_weight.items():
        borne_by[owner_cls] = borne_by.get(owner_cls, 0.0) + shifted * (w / total_weight)


def _distribute_profit_shift(
    shifted: float, producer_owner_cls: ClassId, nation: Nation, world: World, borne_by: dict[ClassId, float]
) -> None:
    """Profit tax's shifted share lands on consumers of the taxed class's producers'
    outputs, pro rata to last year's spend on those goods by class (DD §12.2: "re-placed
    away... until returns re-equalise" — approximated here as passed to consumers of the
    goods that class's stock produces, since the placement re-equalisation itself isn't a
    single-year effect this table can show)."""

    if shifted <= 0:
        return
    goods: set[Good] = set()
    for loc in nation.locations(world):
        for p in loc.producers:
            owners = p.owners_stock
            if owners.get(producer_owner_cls, 0.0) > 0:
                goods.update(p.outputs.keys())
    spend_by_class: dict[ClassId, float] = {}
    total_spend = 0.0
    for loc in nation.locations(world):
        for r in loc.records:
            spend = sum(r.last_spend_by_good.get(g, 0.0) for g in goods)
            if spend > 0:
                spend_by_class[r.cls] = spend_by_class.get(r.cls, 0.0) + spend
                total_spend += spend
    if total_spend <= 0:
        borne_by[producer_owner_cls] = borne_by.get(producer_owner_cls, 0.0) + shifted
        return
    for cls, spend in spend_by_class.items():
        borne_by[cls] = borne_by.get(cls, 0.0) + shifted * (spend / total_spend)


def _compute_incidence(
    nation: Nation,
    world: World,
    params: Params,
    assessed: dict[LawId, Assessment],
    pre_state_assessed: dict[str, dict[ClassId, float]],
) -> None:
    """Builds this year's incidence tables: this year's `assessed_on` (from `assessed`
    and the pre-State draws) plus `borne_by` derived from *last* year's stored
    `assessed_on` and lagged pi/enforcement (PLAN.md's addendum rule). Also stashes this
    year's pi-by-class for next year's read."""

    last_year_incidence = nation.incidence
    this_year: dict[Any, IncidenceTable] = {}

    all_by_class: dict[InstrumentId, dict[ClassId, float]] = {
        law_id: entry.by_class for law_id, entry in assessed.items()
    }
    all_by_class.update(pre_state_assessed)

    for instrument, by_class in all_by_class.items():
        this_year[instrument] = IncidenceTable(
            instrument=instrument,
            assessed_on=dict(by_class),
            borne_by={},
            collected=sum(by_class.values()),
            cost=0.0,
        )

    enf_ca = 0.0
    ca_state = nation.laws.get(LawId.COMBINATION_ACT)
    if ca_state is not None and ca_state.enacted:
        enf_ca = ca_state.enforcement  # naturally lagged: step 12c hasn't run this year yet

    if last_year_incidence is not None:
        for instrument, last_table in last_year_incidence.items():
            if isinstance(instrument, str) and (
                instrument.startswith(_PI_PREFIX) or instrument == _FARM_LOAN_KEY
            ):
                continue
            base = INSTRUMENT_BASE.get(instrument, "unknown")
            table = this_year.setdefault(
                instrument,
                IncidenceTable(instrument=instrument, assessed_on={}, borne_by={}, collected=0.0, cost=0.0),
            )
            pi_table = last_year_incidence.get(_pi_key(instrument))

            if base in PI_SHIFT_BASES:
                for cls, amount in last_table.assessed_on.items():
                    pi_r = pi_table.assessed_on.get(cls, 0.0) if pi_table is not None else 0.0
                    borne_direct = amount * (1.0 - pi_r * (1.0 - enf_ca))
                    shifted = amount - borne_direct
                    table.borne_by[cls] = table.borne_by.get(cls, 0.0) + borne_direct
                    _distribute_shifted(shifted, cls, nation, world, table.borne_by)
            elif base == "profit":
                for cls, amount in last_table.assessed_on.items():
                    shift_amount = amount * params.tax.profit_shift_share
                    stays = amount - shift_amount
                    table.borne_by[cls] = table.borne_by.get(cls, 0.0) + stays
                    _distribute_profit_shift(shift_amount, cls, nation, world, table.borne_by)
            elif instrument == LawId.CUSTOMS:
                for _cls, amount in last_table.assessed_on.items():
                    merch_amount = amount * params.tax.customs_merchant_share
                    rest = amount - merch_amount
                    # Consumers of the routed goods aren't identifiable from a route
                    # record alone (no per-good, per-class demand breakdown here) — all
                    # of it lands on MERCHANTS; see DEVIATIONS.md.
                    table.borne_by[ClassId.MERCHANTS] = (
                        table.borne_by.get(ClassId.MERCHANTS, 0.0) + merch_amount + rest
                    )
            elif base in NO_SHIFT_BASES or base in ("crown_lands", "tolls", "to_be_farmed"):
                for cls, amount in last_table.assessed_on.items():
                    table.borne_by[cls] = table.borne_by.get(cls, 0.0) + amount
            else:
                for cls, amount in last_table.assessed_on.items():
                    table.borne_by[cls] = table.borne_by.get(cls, 0.0) + amount

    # Stash this year's pi by class, for every payer class of every pi-shifting instrument
    # assessed this year, to be read back lagged next year.
    for law_id, entry in assessed.items():
        if INSTRUMENT_BASE.get(law_id) not in PI_SHIFT_BASES:
            continue
        pi_values = _pi_by_class(nation, world, frozenset(entry.by_class.keys()))
        if pi_values:
            this_year[_pi_key(law_id)] = IncidenceTable(
                instrument=_pi_key(law_id), assessed_on=pi_values, borne_by={}, collected=0.0, cost=0.0
            )

    # Preserve the farm-loan stash (written directly by _tax_farming into nation.incidence
    # before this function runs — see step_taxation's ordering) and drop stale pi stashes
    # for instruments no longer assessed.
    if nation.incidence is not None and _FARM_LOAN_KEY in nation.incidence:
        this_year[_FARM_LOAN_KEY] = nation.incidence[_FARM_LOAN_KEY]

    nation.incidence = this_year


def step_taxation(world: World) -> None:
    """Step 3: assess and collect taxes, pre-State revenue, tax farming, incidence, and
    the budget (Doc 05 / T1b).
    """

    params = world.params
    if params is None:
        return

    for nation in world.nations.values():
        if nation.ended:
            continue

        if nation.seat is SeatKind.BAND:
            # DD §12: "Revenue as it grows: a band, none."
            nation.scalars.revenue = 0.0
            nation.scalars.farmed_share = 0.0
            nation.scalars.direct_share = 0.0
            continue

        assessed = assess(nation, world, params.tax)
        collected, tax_flows, cost_total, uncollectable = collect(assessed, nation, world, params)
        nation.add_flow("tax_collected", tax_flows.get("tax_collected", 0.0))
        nation.add_flow("tax_assessed", tax_flows.get("tax_assessed", 0.0))
        nation.add_flow("collection_cost", cost_total)
        if world.ledger is not None:
            for e in uncollectable:
                world.ledger.add_event(e)

        # Collection cost is a real resource cost: it goes to the COLLECTORS record's
        # income (they're sized below), not the void the skeleton left it in.
        collectors = None
        if nation.state is not None:
            state_loc = world.locations.get(nation.state.location)
            if state_loc is not None:
                collectors = state_loc.record(ClassId.COLLECTORS)
                if collectors is None:
                    collectors = Record(
                        cls=ClassId.COLLECTORS, location=nation.state.location, size=0.0, wealth=Wealth()
                    )
                    state_loc.records.append(collectors)
                collectors.income += cost_total
                set_size(collectors, len(assessed) * params.tax.collectors_per_instrument)

        # --- Pre-State revenue (DD §12; applies whenever seat != BAND) ---
        pre_state_assessed: dict[str, dict[ClassId, float]] = {}
        herd_share = _chief_herd_share(nation, world, params.tax)
        if herd_share > 0:
            pre_state_assessed[HERD_SHARE] = {ClassId.HERD_OWNERS: herd_share}
        tithe_flat_by_class = _tithe_flat_draw(nation, world, params.tax)
        tithe_flat = sum(tithe_flat_by_class.values())
        if tithe_flat_by_class:
            pre_state_assessed[TITHE_FLAT] = tithe_flat_by_class
        demesne_rent = _demesne_rent(nation, world)
        if demesne_rent > 0:
            pre_state_assessed[DEMESNE] = {ClassId.LANDLORDS: demesne_rent}
        feudal_dues = _feudal_dues(nation, world, params.tax)
        if feudal_dues > 0:
            pre_state_assessed[FEUDAL_DUES] = {ClassId.SERFS: feudal_dues}

        pre_state_revenue = herd_share + tithe_flat + demesne_rent + feudal_dues
        nation.add_flow("tax_collected", pre_state_revenue)
        collected += pre_state_revenue

        # --- Tax farming (DD §12.1) ---
        farm_delta, farmed_share = _tax_farming(
            nation, world, params.tax, collected, nation.incidence
        )
        collected = max(0.0, collected + farm_delta)
        nation.scalars.farmed_share = farmed_share
        nation.scalars.direct_share = 1.0 - farmed_share

        nation.scalars.revenue = collected

        # --- Incidence (T1b's core correction) ---
        _compute_incidence(nation, world, params, assessed, pre_state_assessed)

        # --- Budget ---
        _normalise_budget(nation, params.tax)
        b = nation.budget

        defence_need = _defence_need(nation, world)
        j_need = justice_need(nation, world)
        service_need = nation.scalars.service  # T2 writes this; read as-is until then
        transfers_need = _transfers_need(nation, world, params)

        nation.scalars.defence_draw = b.defence * collected
        nation.scalars.justice_draw = b.justice * collected
        nation.scalars.works_draw = b.works * collected
        service_draw = b.service * collected
        nation.scalars.service_draw = service_draw  # finance/credit.py's step 6 reads this
        nation.scalars.court = b.court * collected
        nation.scalars.transfers_draw = b.transfers * collected

        tol = params.tax.unfunded_tolerance
        unfunded: set[LawId] = set()
        needs = {
            "defence": (defence_need, nation.scalars.defence_draw),
            "justice": (j_need, nation.scalars.justice_draw),
            "transfers": (transfers_need, nation.scalars.transfers_draw),
            "service": (service_need, service_draw),
        }
        for law_id, draw_name in LAW_PAYER_DRAW.items():
            law_state = nation.laws.get(law_id)
            if law_state is None or not law_state.enacted:
                continue
            need, draw = needs[draw_name]
            if need > 0 and draw < need * (1.0 - tol):
                unfunded.add(law_id)
                if world.ledger is not None:
                    world.ledger.add_event(
                        EventRecord(
                            year=world.year,
                            nation=nation.id,
                            kind=f"draw_unfunded_{draw_name}",
                            numbers={"need": need, "draw": draw},
                        )
                    )
        nation.scalars.unfunded_laws = frozenset(unfunded)
        nation.scalars.service_unfunded = service_need > 0 and service_draw < service_need * (1.0 - tol)

        total_draws = (
            nation.scalars.defence_draw
            + nation.scalars.justice_draw
            + nation.scalars.works_draw
            + service_draw
            + nation.scalars.court
            + nation.scalars.transfers_draw
        )
        unspent = max(0.0, collected - total_draws)
        nation.scalars.treasure += unspent
        nation.flows["treasure_in"] = unspent


def apply_action(world: World, action: Action) -> None:
    """Apply SET_TAX_RATE or SET_BUDGET action (step 14)."""

    nation = world.nations.get(action.nation)
    if nation is None:
        return
    params = world.params.tax if world.params is not None else TaxParams()

    if action.kind == ActionKind.SET_TAX_RATE:
        instrument_name = action.payload.get("instrument")
        rate = float(action.payload.get("rate", params.default_rate))
        rate = max(0.0, min(params.max_rate, rate))
        if instrument_name:
            try:
                law_id: InstrumentId = LawId[instrument_name]
            except KeyError:
                law_id = instrument_name
            nation.tax_rates[law_id] = rate

    elif action.kind == ActionKind.SET_BUDGET:
        shares = action.payload.get("shares", {})
        if shares:
            total = sum(shares.values())
            if total > 0:
                normalised = {k: v / total for k, v in shares.items()}
                d = params.default_budget
                nation.budget = BudgetShares(
                    defence=normalised.get("defence", d.get("defence", 0.4)),
                    justice=normalised.get("justice", d.get("justice", 0.1)),
                    works=normalised.get("works", d.get("works", 0.2)),
                    service=normalised.get("service", d.get("service", 0.1)),
                    court=normalised.get("court", d.get("court", 0.1)),
                    transfers=normalised.get("transfers", d.get("transfers", 0.1)),
                )


def cost_set_tax_rate(world: World, action: Action) -> float:
    params = world.params
    return params.tax.cost_tax_change if params else 0.1


def cost_set_budget(world: World, action: Action) -> float:
    params = world.params
    return params.tax.cost_tax_change if params else 0.1


register_cost_fn(ActionKind.SET_TAX_RATE, cost_set_tax_rate)
register_cost_fn(ActionKind.SET_BUDGET, cost_set_budget)
