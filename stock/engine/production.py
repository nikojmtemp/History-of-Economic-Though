"""Production, the split rule, and the rate of profit — year step 1 (DD §4.2-4.4;
MM §4-6).

**Simplification carried forward from Doc 02** (see DEVIATIONS.md): the "tools" and
"materials" multipliers in the Field/Workshop/Manufactory/Mine formulas are held at
1.0 rather than drawn down from a market inventory. A true simultaneous input-output
market clearing is out of scope for sweep 1's first pass — Hunting, Herding, and
Field (the producers the opening scenario's bands can actually reach without any law
being enacted) are implemented to the full formula; Workshop/Manufactory/Mine/Port
get the correct *shape* of formula with the input term pinned at 1.0 until a later
pass wires up input consumption against `Market.inventory`.
"""

from __future__ import annotations

from dataclasses import dataclass

from stock.core.goods import Good
from stock.core.params import Params
from stock.core.producers import (
    HAS_LAND_RENT,
    JOB_CLASS,
    SITE_RENT_TO_LANDLORD,
    MethodId,
    Producer,
    ProducerKind,
)
from stock.core.records import ClassId
from stock.core.world import Location, Nation, World

#: Output composition per unit Q (DD §4.1, §1.2). Rates, not shares — need not sum to
#: 1. Tuned placeholders where DD gives no split (see module docstring).
OUTPUT_MIX: dict[ProducerKind, dict[Good, float]] = {
    ProducerKind.HUNTING: {Good.PROVISIONS: 0.8, Good.MATERIALS: 0.2},
    ProducerKind.HERDING: {},  # set per-producer: MM §4 kappa_prov/kappa_mat * Herd
    ProducerKind.FIELD: {Good.PROVISIONS: 0.85, Good.MATERIALS: 0.15},
    ProducerKind.WORKSHOP: {Good.WARES: 1.0},
    ProducerKind.PUTTING_OUT: {Good.WARES: 1.0},
    ProducerKind.MANUFACTORY: {Good.WARES: 0.6, Good.LUXURIES: 0.2, Good.ARMS: 0.2},
    ProducerKind.MINE: {Good.MATERIALS: 1.0},
    ProducerKind.PORT: {Good.SHIPS: 1.0},
    ProducerKind.STATE: {},
}

#: A Workshop at a `rare` location also makes Luxuries from local craft (DD §6.1).
WORKSHOP_RARE_MIX: dict[Good, float] = {Good.WARES: 0.7, Good.LUXURIES: 0.3}


def ensure_occupation_producers(location: Location) -> None:
    """Occupations exist wherever the corresponding record does (DD §4.1); create the
    Producer lazily rather than requiring the scenario to declare it. HERDING requires
    owners to be created (DD §3, §4.1)."""

    have = {p.kind for p in location.producers}
    if location.record(ClassId.HUNTERS) is not None and ProducerKind.HUNTING not in have:
        location.producers.append(Producer(kind=ProducerKind.HUNTING, location=location.id))
    if location.record(ClassId.HERDSMEN) is not None and ProducerKind.HERDING not in have:
        herding = Producer(
            kind=ProducerKind.HERDING, location=location.id, owners_stock={ClassId.HERD_OWNERS: 1.0}
        )
        location.producers.append(herding)
    # If HERDING already exists but has empty owners_stock, set the proper owner
    if ProducerKind.HERDING in have:
        herding = next(p for p in location.producers if p.kind == ProducerKind.HERDING)
        if not herding.owners_stock:
            herding.owners_stock[ClassId.HERD_OWNERS] = 1.0
    # An occupation with no record left (everyone moved on) is removed so the year
    # loop doesn't keep depleting/filling a ground nobody works.
    if location.record(ClassId.HUNTERS) is None:
        location.producers = [p for p in location.producers if p.kind != ProducerKind.HUNTING]
    if location.record(ClassId.HERDSMEN) is None and location.record(ClassId.HERD_OWNERS) is None:
        location.producers = [p for p in location.producers if p.kind != ProducerKind.HERDING]


def deplete_or_regenerate(location: Location, worked_intensity: float, kind: str, params: Params) -> None:
    """MM §4 depletion rule with the stored *depletion* convention (0 = pristine,
    1 = depleted): `depletion' = clamp(depletion + δ_dep·use − ρ_dep·depletion·idle, 0, 1)`.
    With `use` and `idle = 1 - use` read as a continuous worked intensity in [0, 1]
    rather than a 0/1 flag, so partial harvesting depletes/regenerates proportionally."""

    p = params.production
    idle = 1.0 - worked_intensity
    if kind == "game":
        dep = location.capacity.game_depletion
        location.capacity.game_depletion = min(
            1.0, max(0.0, dep + p.delta_dep * worked_intensity - p.rho_dep * dep * idle)
        )
    elif kind == "grazing":
        dep = location.capacity.graze_depletion
        location.capacity.graze_depletion = min(
            1.0, max(0.0, dep + p.delta_dep * worked_intensity - p.rho_dep * dep * idle)
        )


def herd_total(location: Location) -> float:
    """Sum herd held by all records at the location (MM §4, §5; ownership via producers)."""
    return sum(record.wealth.herd for record in location.records)


def production_function(producer: Producer, location: Location, params: Params) -> float:
    """MM §4, by ProducerKind. Returns the scalar Q; `OUTPUT_MIX` (or the per-producer
    override for Herding) turns Q into physical output per good."""

    p = params.production
    kind = producer.kind

    if kind is ProducerKind.HUNTING:
        hunters = location.record(ClassId.HUNTERS)
        # If the hunters record is mobilised, return 0 (Doc 04)
        if hunters is not None and hunters.mobilised:
            return 0.0
        h = hunters.size if hunters is not None else 0.0
        capacity = location.capacity.game_cap
        yield_rate = location.resources.game_yield
        q = yield_rate * (h**p.eta) * (1.0 - location.capacity.game_depletion)
        intensity = min(1.0, q / capacity) if capacity > 0 else 0.0
        deplete_or_regenerate(location, intensity, "game", params)
        return float(q)

    if kind is ProducerKind.HERDING:
        # Q = Herd (MM §4): the flow of Provisions/Materials is proportional to the
        # current herd, via kappa_prov/kappa_mat, not a labour-elasticity formula.
        # If herdsmen are mobilised, return 0 (Doc 04)
        herdsmen = location.record(ClassId.HERDSMEN)
        if herdsmen is not None and herdsmen.mobilised:
            return 0.0
        herd = herd_total(location)
        capacity = location.capacity.graze_cap
        intensity = min(1.0, herd / capacity) if capacity > 0 else 0.0
        deplete_or_regenerate(location, intensity, "grazing", params)
        return herd

    if kind is ProducerKind.FIELD:
        labour = sum(producer.filled.values())
        rotation = 0.5 if producer.method is MethodId.THREE_FIELD_ROTATION else 0.0
        tools = 1.0  # simplification, see module docstring
        return float(
            location.resources.arable_yield * producer.land_shares * (labour**p.eta) * (1 + rotation) * tools
        )

    if kind is ProducerKind.WORKSHOP or kind is ProducerKind.PUTTING_OUT:
        workers = sum(producer.filled.values())
        tools = 1.0
        materials = 1.0  # simplification, see module docstring
        return p.q_workshop * workers * tools * materials

    if kind is ProducerKind.MANUFACTORY:
        labourers = sum(producer.filled.values())
        if labourers <= 0:
            return 0.0
        stock_per_labourer = producer.stock_in_place / labourers
        dol = 1.0  # DoL(market_size); wired up once engine.market.dol exists per-call
        machinery = 1.0
        materials = 1.0  # simplification, see module docstring
        return float(p.q_manufactory * labourers * (stock_per_labourer**p.zeta) * dol * machinery * materials)

    if kind is ProducerKind.MINE:
        labourers = sum(producer.filled.values())
        resource = max(
            location.resources.ore_yield, location.resources.coal_yield, location.resources.timber_yield
        )
        return p.q_mine * labourers * resource

    if kind is ProducerKind.PORT:
        merchants = sum(producer.filled.values())
        return p.q_workshop * merchants  # placeholder shape; capacity is Doc 04's

    if kind is ProducerKind.STATE:
        return 0.0

    raise AssertionError(f"unhandled ProducerKind {kind}")


def output_mix(producer: Producer, location: Location, params: Params) -> dict[Good, float]:
    if producer.kind is ProducerKind.HERDING:
        p = params.production
        return {Good.PROVISIONS: p.kappa_prov, Good.MATERIALS: p.kappa_mat}
    if producer.kind is ProducerKind.WORKSHOP and location.resources.rare:
        return WORKSHOP_RARE_MIX
    return OUTPUT_MIX[producer.kind]


@dataclass
class Split:
    labour_income: float
    profit: float
    rent: float

    def total(self) -> float:
        return self.labour_income + self.profit + self.rent


def split_rule(producer: Producer, V: float, wage: float, r_bar_prev: float) -> Split:
    """MM §5: wages first, normal profit next, rent last, as a waterfall so the three
    shares always sum exactly to V (labour/profit/rent never go negative even when V
    falls short of covering the nominal wage bill or the normal return).

    Hunters take the whole produce (DD §2.2, §0.1 "whole produce to the labourer") —
    there is no separate owner extracting profit or rent from a kill, so Hunting
    bypasses the wage-based cap entirely rather than being capped at `wage * jobs`.
    """

    if producer.kind is ProducerKind.HUNTING:
        return Split(labour_income=V, profit=0.0, rent=0.0)

    remaining = V
    labour_income = min(sum(producer.filled.values()) * wage, remaining)
    remaining -= labour_income

    if producer.kind in HAS_LAND_RENT:
        profit = min(r_bar_prev * producer.stock_in_place, remaining)
        remaining -= profit
        rent = remaining
    elif producer.kind in SITE_RENT_TO_LANDLORD:
        rent = min(producer.site_rent, remaining)
        remaining -= rent
        profit = remaining
    else:
        rent = 0.0
        profit = remaining

    return Split(labour_income=labour_income, profit=profit, rent=rent)


def pay_out(split: Split, producer: Producer, location: Location) -> None:
    """Routes labour income to the filled job class, profit to `owners_stock`, rent to
    `owners_land` (DD §4.3). Dependents (RETAINERS, SERVANTS) never fill a producer's
    jobs, so they receive nothing here (DD §5.1c: paid in consumption)."""

    job_cls = JOB_CLASS[producer.kind]
    job_record = location.record(job_cls)
    if job_record is not None and split.labour_income:
        job_record.income += split.labour_income

    for cls, share in producer.owners_stock.items():
        record = location.record(cls)
        if record is not None:
            record.income += split.profit * share

    for cls, share in producer.owners_land.items():
        record = location.record(cls)
        if record is not None:
            record.income += split.rent * share


def fill_jobs(producer: Producer, location: Location, params: Params) -> None:
    """Occupations: the whole record works (no hiring). Buildings: `jobs = stock /
    stock_per_job` (or `land_shares * jobs_per_share` for Field); free labour fills up
    to that many jobs from the location's job-class record (DD §4.2; the full
    wage-attractiveness allocation across competing producers is Doc 02's mobility
    edge, not repeated here)."""

    p = params.production
    job_cls = JOB_CLASS[producer.kind]
    record = location.record(job_cls)
    available = record.size if record is not None else 0.0

    if producer.kind in (ProducerKind.HUNTING, ProducerKind.HERDING):
        producer.jobs = available
        producer.filled = {job_cls: available}
        return

    if producer.kind is ProducerKind.FIELD:
        producer.jobs = producer.land_shares * p.jobs_per_share
    else:
        producer.jobs = producer.stock_in_place / p.stock_per_job if p.stock_per_job else 0.0

    filled = min(producer.jobs, available)
    producer.filled = {job_cls: filled}


def average_rate_of_profit(nation: Nation, world: World) -> float:
    """MM §5: `r_bar = sum(profit) / sum(stock_in_place)` floored at r_bar_floor to
    bootstrap the fixed point at 0. Herding's contribution to the numerator is its
    herd growth (MM §5's parenthetical "herd increase counts as profit on herd stock"),
    not the split-rule profit share of selling this year's output — the owner's return
    on herd capital is the herd's own growth."""

    total_profit = 0.0
    total_stock = 0.0
    for location in nation.locations(world):
        for producer in location.producers:
            total_stock += producer.stock_in_place
            if producer.kind is ProducerKind.HERDING:
                total_profit += producer.last_herd_growth
            else:
                total_profit += producer.last_split_profit
    if total_stock <= 0:
        return 0.0
    r_bar = total_profit / total_stock
    return float(max(r_bar, world.params.production.r_bar_floor))


def herding_growth(location: Location, params: Params) -> float:
    """Gross herd growth before carrying-capacity cap: ΔHerd = γ·Herd·min(1,
    herdsmen/(Herd/h))·(1−graze_depletion) (MM §4). Capping handled in step_production
    after growth is distributed to records."""

    p = params.production
    herd = herd_total(location)
    if herd <= 0:
        return 0.0
    herdsmen = location.record(ClassId.HERDSMEN)
    herdsmen_size = herdsmen.size if herdsmen is not None else 0.0
    needed = herd / p.head_per_herdsman
    graze_depletion = location.capacity.graze_depletion
    return (
        p.gamma_herd
        * herd
        * min(1.0, herdsmen_size / needed if needed > 0 else 0.0)
        * (1.0 - graze_depletion)
    )


def step_production(world: World) -> None:
    """Year step 1 (DD §1.3). Iterates every nation's locations; occupations are
    (re)bound, produced, and their ground worked; buildings run the full split rule."""

    r_bar_prev_by_nation = world.prev.r_bar
    for nation in world.nations.values():
        for location in nation.locations(world):
            ensure_occupation_producers(location)
            for producer in location.producers:
                fill_jobs(producer, location, world.params)
                q = production_function(producer, location, world.params)
                producer.last_Q = q
                mix = output_mix(producer, location, world.params)
                producer.outputs = mix
                prev_price = world.prev.price
                v = sum(prev_price.get((location.id, g), 1.0) * q * rate for g, rate in mix.items())
                producer.last_V = v

                split = split_rule(producer, v, producer.last_wage, r_bar_prev_by_nation.get(nation.id, 0.0))
                pay_out(split, producer, location)
                producer.last_split_profit = split.profit
                nation.add_flow("V", v)
                nation.add_flow("labour_income", split.labour_income)
                nation.add_flow("profit", split.profit)
                nation.add_flow("rent", split.rent)

                if producer.kind is ProducerKind.HERDING:
                    # Compute gross growth and distribute it pro rata to all herd-holding records
                    herd_before = herd_total(location)
                    gross_growth = herding_growth(location, world.params)
                    if gross_growth > 0 and herd_before > 0:
                        # Distribute growth pro rata to each record's herd share
                        for record in location.records:
                            if record.wealth.herd > 0:
                                share = record.wealth.herd / herd_before
                                record.wealth.herd += gross_growth * share

                    # Apply carrying-capacity cap (MM §4)
                    herd_after_growth = herd_total(location)
                    graze_cap = location.capacity.graze_cap
                    if graze_cap > 0 and herd_after_growth > graze_cap:
                        # Scale all records' herd down pro rata to fit the cap
                        if herd_after_growth > 0:
                            scale = graze_cap / herd_after_growth
                            for record in location.records:
                                record.wealth.herd *= scale

                    # Net growth is final herd minus starting herd
                    herd_final = herd_total(location)
                    net_growth = herd_final - herd_before
                    producer.last_herd_growth = net_growth
                    producer.stock_in_place = herd_final
                    nation.add_flow("herd_growth", net_growth)

        nation.scalars.r_bar = average_rate_of_profit(nation, world)
