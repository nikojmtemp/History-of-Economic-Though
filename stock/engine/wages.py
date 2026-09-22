"""Wage bargaining — year step 2 (DD §4.6; MM §8).

Only classes with a genuinely bargained wage run `clearing_wage`: LABOURERS,
CRAFTSMEN, TENANTS, MERCHANTS (DD §2.4's free/independent/merchant tiers). Dependent
labour paid in kind (HERDSMEN, SERFS) is simply paid `w_nat`; HUNTERS take the whole
produce and never reach this module at all (handled directly in `split_rule`). This
is Doc 02's own simplification — MM §8 only ever names "the free-labour record", so
which classes besides LABOURERS actually bargain is a design choice; see DEVIATIONS.md.
"""

from __future__ import annotations

from stock.core.goods import basket_cost
from stock.core.laws import LawId
from stock.core.params import Params
from stock.core.producers import JOB_CLASS, ProducerKind
from stock.core.records import ClassId, Record
from stock.core.world import Location, Nation, World

#: Paid w_nat directly, no bargain (DD §4.6: "dependent labour: the basket in kind").
DEPENDENT_WAGE_CLASSES: frozenset[ClassId] = frozenset({ClassId.HERDSMEN, ClassId.SERFS})

#: Classes whose wage is bargained via `clearing_wage` (DD §2.4's free/independent/
#: merchant tiers; HUNTERS are excluded — they take the whole produce, DD §2.2).
BARGAINING_CLASSES: frozenset[ClassId] = frozenset(
    {ClassId.LABOURERS, ClassId.CRAFTSMEN, ClassId.TENANTS, ClassId.MERCHANTS}
)


def natural_wage(location: Location, tax_on_basket: float = 0.0, sigma: float = 2.0) -> float:
    """`w_nat = P(basket)` including taxes on necessaries/wages (MM §8).

    Args:
        location: the market location
        tax_on_basket: tax on the basket (default 0.0)
        sigma: CES substitution elasticity (default 2.0 from ConsumptionParams)
    """

    return basket_cost(location.market.price, sigma) * (1.0 + tax_on_basket)


def walk_away_labour(record: Record, location: Location, w_nat: float, params: Params) -> float:
    """`wa_L` (MM §8): open jobs on the record's edges, Poor Rate transfer, hoard per
    head, credit available, and a scarcity premium, as shares of income. Poor Rate and
    credit are 0 until Docs 05; the edge search is same-location only until Doc 02's
    own `mobility.py` cross-location edges are wired in by the caller (Doc 04 adds
    cross-border). Decays by `rho_h` per year the record has been on strike."""

    size = max(record.size, 1.0)
    open_jobs = sum(
        max(0.0, p.jobs - sum(p.filled.values()))
        for p in location.producers
        if JOB_CLASS.get(p.kind) == record.cls
    )
    open_jobs_share = open_jobs / size
    hoard_share = (record.wealth.hoard / size) / max(w_nat, 1e-9)
    wa_l = open_jobs_share + hoard_share
    if record.strike_years > 0:
        wa_l *= (1.0 - params.wages.strike_decay_rho_h) ** record.strike_years
    return max(0.0, wa_l)


def patience_masters(producer_kind: ProducerKind, stock_in_place: float, last_wage_bill: float) -> float:
    """`patience_M = stock in place / annual wage bill` (+ a silent combination
    modifier, applied by the caller once Doc 03's law state exists)."""

    if last_wage_bill <= 0:
        return stock_in_place / 1e-6 if stock_in_place > 0 else 1.0
    return stock_in_place / last_wage_bill


def clearing_wage(
    record: Record,
    location: Location,
    producer_kind: ProducerKind,
    v: float,
    filled_jobs: float,
    stock_in_place: float,
    last_wage_bill: float,
    w_nat: float,
    combination_act_enforcement: float,
    params: Params,
    *,
    wa_l: float | None = None,
) -> float:
    """`w = w_nat + pi * surplus * (1 - enf_CombinationAct)`, `pi = wa_L/(wa_L+patience_M)`
    (MM §8). `wa_l` may be supplied by the caller: `walk_away_labour` depends only on
    `(record, location, w_nat, params)`, not on which producer is asking, so a caller
    bargaining several producers of the same class at the same location (`step_wages`)
    computes it once and passes it in rather than paying for it again per producer."""

    if filled_jobs <= 0:
        return w_nat
    surplus = v / filled_jobs - w_nat
    if wa_l is None:
        wa_l = walk_away_labour(record, location, w_nat, params)
    patience_m = patience_masters(producer_kind, stock_in_place, last_wage_bill)
    pi = wa_l / (wa_l + patience_m) if (wa_l + patience_m) > 0 else 0.0
    return w_nat + pi * surplus * (1.0 - combination_act_enforcement)


def _combination_act_enforcement(nation: Nation) -> float:
    state = nation.laws.get(LawId.COMBINATION_ACT)
    return state.enforcement if state is not None and state.enacted else 0.0


def step_wages(world: World) -> None:
    """Year step 2. Sets `producer.last_wage`/`last_wage_bill` for step 1 next year
    (the lag is natural sequencing: step 1 this year already ran on last year's
    values before this step overwrites them)."""

    for nation in world.nations.values():
        enf = _combination_act_enforcement(nation)
        # Lazy import of basket_tax helper from finance module (Doc 05, step 3).
        # Tax rates are policy state set by step 14, so reading them here is safe per the lag rule.
        from stock.finance.taxation import basket_tax

        tax_on_basket = basket_tax(nation)
        sigma = world.params.consumption.sigma_substitution
        for location in nation.locations(world):
            w_nat = natural_wage(location, tax_on_basket=tax_on_basket, sigma=sigma)
            # `walk_away_labour` depends only on (record, location, w_nat, params) —
            # not on which producer is asking — so it's cached per class instead of
            # recomputed for every producer that class staffs. Without this, a
            # location with several producers of the same bargaining class (or just
            # many producers overall, since walk_away_labour's own open-jobs search
            # scans every producer at the location) paid for that scan once per
            # producer instead of once per class.
            wa_l_cache: dict[ClassId, float] = {}
            for producer in location.producers:
                job_cls = JOB_CLASS[producer.kind]
                if producer.kind is ProducerKind.HUNTING:
                    continue  # whole produce, no wage concept (split_rule handles it)
                if job_cls in DEPENDENT_WAGE_CLASSES or job_cls not in BARGAINING_CLASSES:
                    wage = w_nat
                else:
                    record = location.record(job_cls)
                    filled = sum(producer.filled.values())
                    if record is not None:
                        if job_cls not in wa_l_cache:
                            wa_l_cache[job_cls] = walk_away_labour(record, location, w_nat, world.params)
                        wa_l = wa_l_cache[job_cls]
                        wage = clearing_wage(
                            record,
                            location,
                            producer.kind,
                            producer.last_V,
                            filled,
                            producer.stock_in_place,
                            producer.last_wage_bill,
                            w_nat,
                            enf,
                            world.params,
                            wa_l=wa_l,
                        )
                        # Doc 05: expose this year's pi (MM §8) for taxation's
                        # incidence rule, which reads it one year lagged.
                        patience_m = patience_masters(
                            producer.kind, producer.stock_in_place, producer.last_wage_bill
                        )
                        record.last_pi = (
                            wa_l / (wa_l + patience_m) if (wa_l + patience_m) > 0 else 0.0
                        )
                    else:
                        wage = w_nat
                producer.last_wage_bill = wage * sum(producer.filled.values())
                producer.last_wage = wage
