"""Credit: rates, the private lending market, and public debt (step 6; Doc 05).

`rates()` is a pure function of the nation's own average rate of profit (`r_bar`),
security (`N_bar`), justice (`J`), and — for the sovereign premium — its debt burden,
default history, and treaty standing.

**Step ordering note**: credit (step 6) runs before hoards (step 7) and placement
(step 9) in `sim/year.py`, and before military (step 13). That lets this module debit
`record.wealth.hoard` directly when a record buys bonds or lends privately — step 7's
`hoard_update` then works from the already-reduced base, which is what capital.py's
docstring means by "drawn from hoards" (no separate `bonds_from_hoard` hook into
`engine/capital.py` is needed). It also lets a bond-financed `spending_extra` land in
`defence_draw` in time for step 13's army purchase / soldier pay, while a tax-financed
one does not — the acceptance criterion for the two funding modes.

**Private market, smallest reading** (MM §18's `f_s` has no specified functional form —
see `DEVIATIONS-UNRESOLVED.md` A25 for the analogous tax-incidence case): lendable
supply is each lender record's hoard times `f_s(r_legal − r_bar)`; demand is producers
whose return exceeds `r_legal` plus LABOURERS/SERFS with a subsistence shortfall.
Private debt is tracked in aggregate per nation (`NationScalars.private_debt`), not
per borrower-lender pair — mirroring how public debt is a single `D` against the whole
bondholder roster rather than per-bond records. Interest is paid the following year, as
the doc specifies; principal is not amortised. The doc's per-class default consequences
(land transfer, lease loss, tier demotion, losing Ships, debt bondage) need fields
(lease terms, craftsman tiers, a Ships asset) that do not exist anywhere else in this
codebase; a shortfall instead writes down `private_debt` and lenders' `loans_out`
proportionally, logged as `DEVIATIONS-UNRESOLVED.md` A37.
"""

from __future__ import annotations

from stock.core.actions import Action, ActionKind, register_cost_fn
from stock.core.goods import basket_cost
from stock.core.laws import LawId
from stock.core.params import CreditParams
from stock.core.records import ClassId
from stock.core.world import Nation, SeatKind, World
from stock.sim.ledger import EventRecord

#: Private lenders (DD §11): MERCHANTS, CAPITALISTS supply from hoard.
LENDER_CLASSES: frozenset[ClassId] = frozenset({ClassId.MERCHANTS, ClassId.CAPITALISTS})
#: Borrower classes whose income services private debt (DD §11's borrower list).
BORROWER_CLASSES: frozenset[ClassId] = frozenset(
    {
        ClassId.LANDLORDS,
        ClassId.TENANTS,
        ClassId.CRAFTSMEN,
        ClassId.MERCHANTS,
        ClassId.CAPITALISTS,
        ClassId.LABOURERS,
    }
)
#: Inelastic subsistence borrowers (DD §11).
SUBSISTENCE_CLASSES: frozenset[ClassId] = frozenset({ClassId.LABOURERS, ClassId.SERFS})


def _enacted(nation: Nation, law: LawId) -> bool:
    st = nation.laws.get(law)
    return st is not None and st.enacted


def _log_post_consumption_income(nation: Nation, delta: float) -> None:
    """Credit lands in `record.income` after step 5 already closed the
    `gross_income == consumption + saved` and (via step 7) `to_hoard + to_reinvest
    == saved` identities (Doc 08's invariants) for the year. Bumping both flows by
    the same `delta` keeps both identities exact regardless of whether `delta` is a
    genuinely new inflow (subsistence relief, bond/loan interest) or a transfer's net
    rounding residual (debt service, which nets to ~0 in aggregate)."""

    if delta == 0.0:
        return
    nation.add_flow("saved", delta)
    nation.add_flow("gross_income", delta)


def _credit_params(world: World) -> CreditParams:
    return world.params.credit if world.params is not None else CreditParams()


def _f_s(gap: float, params: CreditParams) -> float:
    """Private lenders' willingness to lend rather than self-invest (MM §18's `f_s`,
    unspecified form — smallest monotone choice: linear in the rate gap, clamped)."""
    return max(0.0, min(1.0, params.f_s_base + params.f_s_slope * gap))


def usury_cap(nation: Nation, params: CreditParams) -> float:
    """DD §11's Usury Law settings, folded into a single ceiling on `r_legal`:
    prohibition forces everything informal (cap 0); a cap (above or below market) is
    whatever rate is enacted; no law leaves lending uncapped."""

    if _enacted(nation, LawId.USURY_PROHIBITION):
        return 0.0
    if _enacted(nation, LawId.USURY_CAP):
        return nation.tax_rates.get(LawId.USURY_CAP, params.usury_cap_default)
    return float("inf")


def _treaty_standing(nation: Nation, world: World, params: CreditParams) -> float:
    """Net effect of this nation's treaties on `r_sovereign`'s premium: an active
    breach raises it, a treaty kept without breach lowers it (DD §11's "treaty
    standing")."""

    standing = 0.0
    for ref in nation.treaties:
        treaty = world.treaties.get(ref.id)
        if treaty is None:
            continue
        if treaty.breached_years.get(nation.id, 0) > 0:
            standing += params.sigma_breach_penalty
        elif treaty.kept_years > 0:
            standing -= params.sigma_treaty_bonus
    return standing


def rates(nation: Nation, world: World) -> tuple[float, float, float]:
    """MM §18: `r_market = s*r_bar + rho(N_bar, J)`; `r_legal = min(r_market,
    usury_cap)`; `r_sovereign = r_market + sigma(D/revenue, default_history, J,
    treaty standing)`."""

    params = _credit_params(world)
    s = nation.scalars
    rho = (
        params.risk_premium_base
        + params.risk_premium_security_weight * max(0.0, -s.N_bar)
        + params.risk_premium_justice_weight * max(0.0, 1.0 - s.J)
    )
    r_market = params.lender_share_s * s.r_bar + rho
    r_legal = min(r_market, usury_cap(nation, params))

    if s.revenue > 1e-9:
        debt_ratio = min(s.debt / s.revenue, params.debt_ratio_cap)
    else:
        debt_ratio = params.debt_ratio_cap if s.debt > 0 else 0.0
    sigma = (
        params.sovereign_premium_base
        + params.sovereign_premium_debt_weight * debt_ratio
        + params.sovereign_premium_default_weight * (1.0 if s.default_history else 0.0)
        + _treaty_standing(nation, world, params)
    )
    r_sovereign = r_market + max(0.0, sigma)
    return r_market, r_legal, r_sovereign


# --- Private market ---


def _lendable_supply(
    nation: Nation, world: World, r_legal: float, params: CreditParams
) -> dict[tuple[str, ClassId], float]:
    supply: dict[tuple[str, ClassId], float] = {}
    r_bar = nation.scalars.r_bar
    for loc in nation.locations(world):
        for r in loc.records:
            if r.cls not in LENDER_CLASSES or r.wealth.hoard <= 0:
                continue
            amount = r.wealth.hoard * _f_s(r_legal - r_bar, params)
            if amount > 0:
                supply[(loc.id, r.cls)] = amount
    return supply


def _project_demand(nation: Nation, world: World, r_legal: float, params: CreditParams) -> dict[str, float]:
    """Producers whose return exceeds `r_legal` (DD §11: "projects with return above
    r_legal"): demand scales with the return gap, capped as a share of the producer's
    own stock (smallest monotone choice, as `f_s` above)."""

    demand: dict[str, float] = {}
    for loc in nation.locations(world):
        for i, producer in enumerate(loc.producers):
            if producer.stock_in_place <= 0:
                continue
            ret = producer.last_split_profit / producer.stock_in_place
            gap = ret - r_legal
            if gap <= 0:
                continue
            share = max(0.0, min(params.demand_cap_share, params.demand_k * gap))
            amount = producer.stock_in_place * share
            if amount > 0:
                demand[f"{loc.id}:{i}"] = amount
    return demand


def _subsistence_demand(nation: Nation, world: World) -> dict[tuple[str, ClassId], float]:
    demand: dict[tuple[str, ClassId], float] = {}
    sigma = world.params.consumption.sigma_substitution if world.params else 1.0
    for loc in nation.locations(world):
        cost = basket_cost(loc.market.price, sigma)
        for r in loc.records:
            if r.cls not in SUBSISTENCE_CLASSES:
                continue
            shortfall = max(0.0, 1.0 - r.A.subsistence)
            if shortfall <= 0:
                continue
            demand[(loc.id, r.cls)] = shortfall * r.size * cost
    return demand


def _clear_private_credit(nation: Nation, world: World, r_legal: float, params: CreditParams) -> None:
    supply = _lendable_supply(nation, world, r_legal, params)
    total_supply = sum(supply.values())
    if total_supply <= 0:
        return

    subs_demand = _subsistence_demand(nation, world)
    proj_demand = _project_demand(nation, world, r_legal, params)
    total_demand = sum(subs_demand.values()) + sum(proj_demand.values())
    if total_demand <= 0:
        return

    lent_total = min(total_supply, total_demand)
    supply_scale = lent_total / total_supply
    loc_by_id = {loc.id: loc for loc in nation.locations(world)}

    for (loc_id, cls), amount in supply.items():
        lent = amount * supply_scale
        if lent <= 0:
            continue
        record = loc_by_id[loc_id].record(cls)
        if record is None:
            continue
        record.wealth.hoard -= lent
        record.wealth.loans_out += lent

    subs_total = sum(subs_demand.values())
    subs_scale = min(1.0, lent_total / subs_total) if subs_total > 0 else 0.0
    subs_income_added = 0.0
    for (loc_id, cls), amount in subs_demand.items():
        granted = amount * subs_scale
        if granted <= 0:
            continue
        record = loc_by_id[loc_id].record(cls)
        if record is not None:
            record.income += granted
            subs_income_added += granted
    _log_post_consumption_income(nation, subs_income_added)

    remaining = max(0.0, lent_total - subs_total * subs_scale)
    proj_total = sum(proj_demand.values())
    proj_scale = min(1.0, remaining / proj_total) if proj_total > 0 else 0.0
    for key, amount in proj_demand.items():
        granted = amount * proj_scale
        if granted <= 0:
            continue
        loc_id, idx_str = key.split(":", 1)
        loc_by_id[loc_id].producers[int(idx_str)].stock_in_place += granted

    nation.scalars.private_debt += lent_total
    nation.add_flow("credit_extended", lent_total)


def _write_down_lenders(nation: Nation, world: World, write_off: float) -> None:
    if write_off <= 0:
        return
    total_out = sum(r.wealth.loans_out for loc in nation.locations(world) for r in loc.records)
    if total_out <= 0:
        return
    frac = min(1.0, write_off / total_out)
    for loc in nation.locations(world):
        for r in loc.records:
            if r.wealth.loans_out > 0:
                r.wealth.loans_out -= r.wealth.loans_out * frac


def _service_private_debt(nation: Nation, world: World, r_legal: float) -> None:
    """Interest on last year's private debt (DD §11: "interest is paid the following
    year"), drawn from borrowers' income in aggregate; a shortfall writes down the
    debt and lenders' claims proportionally (A37 — see module docstring)."""

    debt = nation.scalars.private_debt
    if debt <= 0:
        return
    due = debt * r_legal
    if due <= 0:
        return

    borrower_records = [
        r
        for loc in nation.locations(world)
        for r in loc.records
        if r.cls in BORROWER_CLASSES and r.income > 0
    ]
    available = sum(r.income for r in borrower_records)
    paid = min(due, available)
    # Tracks the *actual* net change to `record.income` this function makes (not the
    # idealised `paid`, which the borrower and lender sides only sum to up to
    # floating-point rounding) — Doc 08's hoard-conservation invariant needs "saved"
    # to match whatever step 7 will actually see in `record.income`.
    income_delta = 0.0
    if available > 0 and paid > 0:
        scale = paid / available
        for r in borrower_records:
            debit = r.income * scale
            r.income -= debit
            income_delta -= debit

    shortfall = due - paid
    if shortfall > 1e-9:
        write_off = min(shortfall, debt)
        nation.scalars.private_debt = max(0.0, debt - write_off)
        _write_down_lenders(nation, world, write_off)
        if world.ledger is not None:
            world.ledger.add_event(
                EventRecord(
                    year=world.year,
                    nation=nation.id,
                    kind="private_credit_default",
                    numbers={"written_off": write_off},
                )
            )

    total_out = sum(r.wealth.loans_out for loc in nation.locations(world) for r in loc.records)
    if total_out > 0 and paid > 0:
        for loc in nation.locations(world):
            for r in loc.records:
                if r.wealth.loans_out > 0:
                    credit = paid * (r.wealth.loans_out / total_out)
                    r.income += credit
                    income_delta += credit
    nation.add_flow("private_debt_service", paid)
    _log_post_consumption_income(nation, income_delta)


# --- Public credit ---


def public_credit_open(nation: Nation, world: World) -> bool:
    if not _enacted(nation, LawId.PUBLIC_CREDIT):
        return False
    closed_until = nation.scalars.public_credit_closed_until
    return closed_until is None or world.year >= closed_until


def issue_bonds(nation: Nation, world: World, r_sovereign: float, params: CreditParams) -> float:
    """`bonds_t = max(0, spending − revenue)` (MM §18): here, `spending` is this
    year's `spending_extra` (a war's cost or a sovereign's request beyond the ordinary
    budget draws, which are already fully tax-funded by `finance/taxation.py`), and
    `revenue` is nothing further — the ordinary revenue is already spoken for. Bonds
    are drawn from any record's hoard, pro-rata to its willingness `f_s(r_sovereign −
    r_bar)`, up to what is offered; any unmet balance stays in `spending_extra` for the
    sovereign to fund by other means."""

    needed = max(0.0, nation.scalars.spending_extra)
    if needed <= 0 or nation.funding_mode != "BONDS" or not public_credit_open(nation, world):
        return 0.0

    r_bar = nation.scalars.r_bar
    lenders = [r for loc in nation.locations(world) for r in loc.records if r.wealth.hoard > 0]
    offers = {id(r): (r, r.wealth.hoard * _f_s(r_sovereign - r_bar, params)) for r in lenders}
    total_offered = sum(amount for _, amount in offers.values())
    if total_offered <= 0:
        return 0.0

    issued = min(needed, total_offered)
    scale = issued / total_offered
    for r, amount in offers.values():
        lent = amount * scale
        if lent <= 0:
            continue
        r.wealth.hoard -= lent
        r.wealth.bonds += lent

    nation.scalars.defence_draw += issued
    nation.scalars.debt += issued
    nation.scalars.bonds_issued = issued
    nation.scalars.spending_extra = max(0.0, needed - issued)
    nation.add_flow("bonds_issued", issued)
    return issued


def _pay_bondholders(nation: Nation, world: World, paid: float) -> float:
    """Returns the actual total credited to bondholders' `income` (matches `paid`
    up to floating-point rounding across however many bondholders there are)."""

    if paid <= 0:
        return 0.0
    total_bonds = sum(r.wealth.bonds for loc in nation.locations(world) for r in loc.records)
    if total_bonds <= 0:
        return 0.0
    income_added = 0.0
    for loc in nation.locations(world):
        for r in loc.records:
            if r.wealth.bonds > 0:
                credit = paid * (r.wealth.bonds / total_bonds)
                r.income += credit
                income_added += credit
    return income_added


def service_public_debt(nation: Nation, world: World, r_sovereign: float) -> None:
    """`D' = D*(1+r_sovereign) - service` (MM §18); `service` is this year's actual
    `service_draw` (written by `finance/taxation.py`'s step 3 from last year's
    `service_due`, which this function now recomputes for next year)."""

    s = nation.scalars
    paid = s.service_draw
    s.debt = max(0.0, s.debt * (1.0 + r_sovereign) - paid)
    income_added = _pay_bondholders(nation, world, paid)
    _log_post_consumption_income(nation, income_added)
    s.service_due = s.debt * r_sovereign
    s.service = s.service_due  # read by taxation.py's step 3 next year as the need


def default_public_debt(nation: Nation, world: World, params: CreditParams) -> None:
    """`D := 0`; bondholders' `bonds := 0`; `default_history := 1`; Public Credit
    closed `k` years; `O -= 1` (MM §18)."""

    for loc in nation.locations(world):
        for r in loc.records:
            r.wealth.bonds = 0.0
    s = nation.scalars
    written_off = s.debt
    s.debt = 0.0
    s.service_due = 0.0
    s.service = 0.0
    s.default_history = True
    s.public_credit_closed_until = world.year + params.default_closure_years
    s.O -= 1
    law = nation.laws.get(LawId.PUBLIC_CREDIT)
    if law is not None:
        law.enacted = False
    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=nation.id,
                kind="default",
                numbers={"debt_written_off": written_off},
            )
        )


def debt_choice(nation: Nation, world: World, params: CreditParams) -> str:
    """DD §11: when `service > tau_d * revenue`, TAX/ROLLOVER/DEFAULT is exposed for
    the sovereign; a null sovereign never moves `debt_policy` off its default
    ROLLOVER. TAX (raising the `service` budget share going forward) is Doc 06/07's to
    act on; only DEFAULT changes this module's own behaviour."""

    s = nation.scalars
    triggered = s.revenue > 0 and s.service_draw > params.tau_d * s.revenue
    if not triggered:
        return "ROLLOVER"
    return nation.debt_policy if nation.debt_policy in ("TAX", "ROLLOVER", "DEFAULT") else "ROLLOVER"


# --- Step ---


def step_credit(world: World) -> None:
    """Step 6: rates, the private market, and public debt."""

    if world.params is None:
        return
    params = world.params.credit

    for nation in world.nations.values():
        if nation.ended or nation.seat is SeatKind.BAND:
            continue

        r_market, r_legal, r_sovereign = rates(nation, world)
        s = nation.scalars
        s.r_market, s.r_legal, s.r_sovereign = r_market, r_legal, r_sovereign

        _clear_private_credit(nation, world, r_legal, params)
        _service_private_debt(nation, world, r_legal)

        if debt_choice(nation, world, params) == "DEFAULT":
            default_public_debt(nation, world, params)
            continue

        issue_bonds(nation, world, r_sovereign, params)
        service_public_debt(nation, world, r_sovereign)


# --- Actions ---


def apply_action(world: World, action: Action) -> None:
    """Apply SET_DEBT_POLICY or SET_FUNDING_MODE (step 14)."""

    nation = world.nations.get(action.nation)
    if nation is None:
        return
    if action.kind == ActionKind.SET_DEBT_POLICY:
        policy = action.payload.get("policy")
        if policy in ("TAX", "ROLLOVER", "DEFAULT"):
            nation.debt_policy = policy
    elif action.kind == ActionKind.SET_FUNDING_MODE:
        mode = action.payload.get("mode")
        if mode in ("BONDS", "TAX"):
            nation.funding_mode = mode


def cost_set_debt_policy(world: World, action: Action) -> float:
    return world.params.credit.cost_debt_change if world.params else 0.1


register_cost_fn(ActionKind.SET_DEBT_POLICY, cost_set_debt_policy)
register_cost_fn(ActionKind.SET_FUNDING_MODE, cost_set_debt_policy)
