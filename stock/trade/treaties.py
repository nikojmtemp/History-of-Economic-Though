"""Treaties: terms, enforcement, breach, casus belli (Doc 04 task 5).

Treaties bind nations with terms from DD §10.4: tariff ceilings, route access,
port restrictions, exclusive routes, tribute, cessions, grain guarantees, and
non-aggression pacts. Enforcement is per-side via the law the term binds; breach
emits events, hostility increments, and casus belli.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from stock.core.records import InterestId
from stock.sim.ledger import EventRecord


# Register action handlers
def _register_action_handlers() -> None:
    """Register cost functions for treaty actions."""
    from stock.core.actions import ActionKind, register_cost_fn

    def _cost_propose_treaty(world: Any, action: Any) -> float:
        return float(world.params.trade.cost_treaty)

    def _cost_accept_treaty(world: Any, action: Any) -> float:
        return float(world.params.trade.cost_treaty)

    register_cost_fn(ActionKind.PROPOSE_TREATY, _cost_propose_treaty)
    register_cost_fn(ActionKind.ACCEPT_TREATY, _cost_accept_treaty)


_register_action_handlers()


class TermKind(Enum):
    """Treaty term types (DD §10.4)."""

    TARIFF_CEILING = auto()
    ROUTE_ACCESS = auto()
    PORT_ACCESS = auto()
    EXCLUSIVE_ROUTE = auto()
    MOST_FAVOURED = auto()
    TRIBUTE = auto()
    CESSION = auto()
    GRAIN_GUARANTEE = auto()
    NON_AGGRESSION = auto()


@dataclass
class Term:
    """A single term in a treaty.

    kind: the type of term.
    bound: the nation the term binds (restricts).
    beneficiary: the nation that benefits from the term.
    goods: tuple of Good for tariff/grain terms (default empty).
    rate: tariff ceiling rate, as a share (default 0.0).
    route_id: for route-access terms, the route id (default None).
    location: for port-access terms, the port location id (default None).
    amount: for tribute terms, annual amount in baskets (default 0.0).
    years: for tribute terms, duration in years (default 0).
    """

    kind: TermKind
    bound: str
    beneficiary: str
    goods: tuple[Any, ...] = ()  # tuple[Good, ...]; Any to avoid serialize issues
    rate: float = 0.0
    route_id: str | None = None
    location: str | None = None
    amount: float = 0.0
    years: int = 0


@dataclass
class Treaty:
    """A treaty between two nations.

    id: unique treaty identifier.
    a, b: the two nation ids.
    terms: list of Term objects.
    signed: the year signed.
    imposed: True if imposed at peace (loser pays nothing), False if negotiated.
    breached_years: per-side dict of years a breach was active (side -> count).
    kept_years: number of years with no breach.
    penalty_until: per-side dict of the year a breach penalty expires (side -> year).
    h_at_signing: hostility between a and b when signed (for renegotiability).
    m_ratio_at_signing: M_a / M_b when signed (for renegotiability).
    """

    id: str
    a: str
    b: str
    terms: list[Term] = field(default_factory=list)
    signed: int = 0
    imposed: bool = False
    breached_years: dict[str, int] = field(default_factory=dict)
    kept_years: int = 0
    penalty_until: dict[str, int] = field(default_factory=dict)
    h_at_signing: float = 0.0
    m_ratio_at_signing: float = 1.0


def bound_interest(term: Term) -> InterestId | None:
    """Return the Interest a term binds on the bound side, via the law it forbids/opens.

    TARIFF_CEILING → INDUSTRIAL (the producer).
    PORT_ACCESS/ROUTE_ACCESS/EXCLUSIVE_ROUTE/MOST_FAVOURED → MERCHANT.
    GRAIN_GUARANTEE → LANDED (prohibition_law(PROVISIONS)'s supporters).
    TRIBUTE/CESSION/NON_AGGRESSION → None (State-level).
    """

    if term.kind == TermKind.TARIFF_CEILING:
        return InterestId.INDUSTRIAL
    elif term.kind in (
        TermKind.PORT_ACCESS,
        TermKind.ROUTE_ACCESS,
        TermKind.EXCLUSIVE_ROUTE,
        TermKind.MOST_FAVOURED,
    ):
        return InterestId.MERCHANT
    elif term.kind == TermKind.GRAIN_GUARANTEE:
        return InterestId.LANDED
    else:  # TRIBUTE, CESSION, NON_AGGRESSION
        return None


def enforcement_of_term(
    treaty: Treaty, side: str, world: Any  # world is core.world.World
) -> float:
    """Compute enforcement of a term on one side.

    For terms with a bound_interest, compute via legislation.enforcement.
    For State-level terms, return nation.scalars.J directly.
    """
    term = None
    for t in treaty.terms:
        if t.bound == side:
            term = t
            break

    if term is None:
        return 0.0

    nation = world.nations.get(side)
    if nation is None:
        return 0.0

    interest = bound_interest(term)
    if interest is None:
        # State-level term: return J
        return float(nation.scalars.J)

    # Look up the law the term forbids/opens and compute enforcement
    law_key: str | Any = None

    if term.kind == TermKind.TARIFF_CEILING and term.goods:
        from stock.core.laws import tariff_law
        law_key = tariff_law(term.goods[0])
    elif term.kind == TermKind.PORT_ACCESS:
        from stock.core.laws import LawId
        law_key = LawId.NAVIGATION_ACT
    elif term.kind == TermKind.EXCLUSIVE_ROUTE:
        from stock.core.laws import LawId
        law_key = LawId.CHARTERED_COMPANY
    elif term.kind == TermKind.GRAIN_GUARANTEE:
        from stock.core.goods import Good
        from stock.core.laws import prohibition_law
        law_key = prohibition_law(Good.PROVISIONS)
    else:
        return 0.0

    from stock.politics.legislation import enforcement
    return enforcement(law_key, nation, world)


def negotiate(world: Any, a: str, b: str, terms: list[Term]) -> Treaty:
    """Create a treaty by negotiation (both sides spend A_S).

    Returns the Treaty and appends TreatyRef to both nations' treaties lists.
    """

    from stock.core.world import TreatyRef
    from stock.trade.hostility import hostility

    nation_a = world.nations.get(a)
    nation_b = world.nations.get(b)

    if nation_a is None or nation_b is None:
        raise ValueError(f"Invalid nations: {a}, {b}")

    # Create treaty
    treaty_id = f"treaty_{world.year}_{a}_{b}_{len(world.treaties)}"
    h_ij = hostility(world, a, b)
    m_a = nation_a.scalars.M
    m_b = nation_b.scalars.M
    m_ratio = m_a / m_b if m_b > 0 else 1.0

    treaty = Treaty(
        id=treaty_id,
        a=a,
        b=b,
        terms=terms,
        signed=world.year,
        imposed=False,
        h_at_signing=h_ij,
        m_ratio_at_signing=m_ratio,
    )

    world.treaties[treaty_id] = treaty
    nation_a.treaties.append(TreatyRef(id=treaty_id, other_nation=b))
    nation_b.treaties.append(TreatyRef(id=treaty_id, other_nation=a))

    return treaty


def impose(world: Any, winner: str, loser: str, terms: list[Term]) -> Treaty:
    """Create a treaty by imposition at peace (loser pays nothing, consent not required).

    Returns the Treaty and appends TreatyRef to both nations' treaties lists.
    """

    from stock.core.world import TreatyRef

    nation_winner = world.nations.get(winner)
    nation_loser = world.nations.get(loser)

    if nation_winner is None or nation_loser is None:
        raise ValueError(f"Invalid nations: {winner}, {loser}")

    # Create treaty
    treaty_id = f"treaty_{world.year}_{winner}_{loser}_{len(world.treaties)}"
    from stock.trade.hostility import hostility

    h_ij = hostility(world, winner, loser)
    m_a = nation_winner.scalars.M
    m_b = nation_loser.scalars.M
    m_ratio = m_a / m_b if m_b > 0 else 1.0

    treaty = Treaty(
        id=treaty_id,
        a=winner,
        b=loser,
        terms=terms,
        signed=world.year,
        imposed=True,
        h_at_signing=h_ij,
        m_ratio_at_signing=m_ratio,
    )

    world.treaties[treaty_id] = treaty
    nation_winner.treaties.append(TreatyRef(id=treaty_id, other_nation=loser))
    nation_loser.treaties.append(TreatyRef(id=treaty_id, other_nation=winner))

    return treaty


def check_breach(treaty: Treaty, world: Any) -> list[EventRecord]:
    """Check for treaty breaches each year, per bound side.

    Returns list of breach events. Per-side: on breach, adds to breached_years,
    emits breach event, increments hostility, grants casus_belli, and sets
    penalty_until.
    """

    from stock.core.goods import Good
    from stock.core.laws import LawId, prohibition_law, tariff_law

    events: list[EventRecord] = []
    params = world.params

    for term in treaty.terms:
        breacher = None
        beneficiary = term.beneficiary
        bound = term.bound

        # TARIFF_CEILING: breached if tariff_law(good) is enacted with enforcement > 0
        # and rate above ceiling
        if term.kind == TermKind.TARIFF_CEILING:
            if not term.goods:
                continue
            good = term.goods[0]
            nation = world.nations.get(bound)
            if nation is None:
                continue

            law_key = tariff_law(good)
            law_state = nation.laws.get(law_key)
            if law_state is None or not law_state.enacted:
                continue

            enf = enforcement_of_term(treaty, bound, world)
            if enf > 0 and params.trade.tariff_rate > term.rate:
                breacher = bound

        # PORT_ACCESS: breached if NAVIGATION_ACT enacted or route treaty_factor == 0
        elif term.kind == TermKind.PORT_ACCESS:
            if term.location is None:
                continue
            nation = world.nations.get(bound)
            if nation is None:
                continue

            nav_law = nation.laws.get(LawId.NAVIGATION_ACT)
            if nav_law is not None and nav_law.enacted:
                breacher = bound
            else:
                # Check if port location's routes to beneficiary have treaty_factor == 0
                for _route_id, route in world.routes.items():
                    loc_a = world.locations.get(route.a)
                    loc_b = world.locations.get(route.b)
                    if loc_a is None or loc_b is None:
                        continue
                    if (route.a == term.location or route.b == term.location) and (
                        loc_a.nation == beneficiary or loc_b.nation == beneficiary
                    ):
                        if route.treaty_factor == 0.0:
                            breacher = bound
                            break

        # GRAIN_GUARANTEE: breached if prohibition_law(PROVISIONS) enacted in bound
        # nation while beneficiary's Provisions price exceeds dearth_price_multiple
        elif term.kind == TermKind.GRAIN_GUARANTEE:
            nation_bound = world.nations.get(bound)
            nation_benef = world.nations.get(beneficiary)
            if nation_bound is None or nation_benef is None:
                continue

            prov_law = nation_bound.laws.get(prohibition_law(Good.PROVISIONS))
            if prov_law is None or not prov_law.enacted:
                continue

            # Check beneficiary's Provisions price
            benef_locs = nation_benef.locations(world)
            dearth_threshold = params.trade.dearth_price_multiple
            for loc in benef_locs:
                prov_price = loc.market.price.get(Good.PROVISIONS, 1.0)
                if prov_price > dearth_threshold:
                    breacher = bound
                    break

        # ROUTE_ACCESS: breached if bound side enacts prohibition on any route good
        elif term.kind == TermKind.ROUTE_ACCESS:
            if term.route_id is None:
                continue
            route = world.routes.get(term.route_id)
            if route is None:
                continue

            nation = world.nations.get(bound)
            if nation is None:
                continue

            # Check if any good on the route is prohibited
            for good in [Good.PROVISIONS, Good.MATERIALS, Good.WARES, Good.LUXURIES, Good.ARMS, Good.SHIPS]:
                law_key = prohibition_law(good)
                law_state = nation.laws.get(law_key)
                if law_state is not None and law_state.enacted:
                    breacher = bound
                    break

        # NON_AGGRESSION: breached by declare_war
        elif term.kind == TermKind.NON_AGGRESSION:
            # Check if there's a war between beneficiary and bound
            war_key_a = (beneficiary, bound)
            war_key_b = (bound, beneficiary)
            if war_key_a in world.wars or war_key_b in world.wars:
                breacher = bound

        # If breached, emit event and update state
        if breacher is not None:
            treaty.breached_years[breacher] = treaty.breached_years.get(breacher, 0) + 1
            enf = enforcement_of_term(treaty, breacher, world)

            if world.ledger is not None:
                events.append(
                    EventRecord(
                        year=world.year,
                        nation=beneficiary,
                        kind="breach",
                        numbers={
                            "term_kind": float(term.kind.value),
                            "enforcement": enf,
                            "years_breached": float(
                                treaty.breached_years.get(breacher, 0)
                            ),
                        },
                    )
                )
                events.append(
                    EventRecord(
                        year=world.year,
                        nation=breacher,
                        kind="treaty_broken_against_us",
                        numbers={
                            "term_kind": float(term.kind.value),
                            "enforcement": enf,
                        },
                    )
                )

            # Increment hostility
            from stock.trade.hostility import add_hostility

            add_hostility(world, beneficiary, breacher, params.trade.h_breach)

            # Grant casus belli
            world.casus_belli.add((beneficiary, breacher))

            # Set penalty_until
            treaty.penalty_until[breacher] = world.year + params.trade.k_penalty

    return events


def lapse_on_end(world: Any) -> None:
    """Remove treaties whose signatory has ended = True."""


    to_remove = []
    for treaty_id, treaty in world.treaties.items():
        nation_a = world.nations.get(treaty.a)
        nation_b = world.nations.get(treaty.b)

        if (nation_a is not None and nation_a.ended) or (
            nation_b is not None and nation_b.ended
        ):
            to_remove.append(treaty_id)

    for treaty_id in to_remove:
        treaty = world.treaties.pop(treaty_id)
        # Also remove from nations' treaty lists
        for nation_id in [treaty.a, treaty.b]:
            nation = world.nations.get(nation_id)
            if nation is not None:
                nation.treaties = [
                    tr
                    for tr in nation.treaties
                    if tr.id != treaty_id
                ]


def renegotiable(treaty: Treaty, world: Any) -> bool:
    """Return True if treaty is renegotiable based on hostility and M ratio changes.

    Renegotiable when |Δh_ij| since signing > renegotiate_h_delta or the ratio M_a/M_b
    has moved by more than renegotiate_m_ratio from its value at signing.
    """

    from stock.trade.hostility import hostility

    params = world.params

    # Hostility change
    h_current = hostility(world, treaty.a, treaty.b)
    h_delta = abs(h_current - treaty.h_at_signing)

    if h_delta > params.trade.renegotiate_h_delta:
        return True

    # M ratio change
    nation_a = world.nations.get(treaty.a)
    nation_b = world.nations.get(treaty.b)
    if nation_a is None or nation_b is None:
        return False

    m_a = nation_a.scalars.M
    m_b = nation_b.scalars.M
    m_ratio_current = m_a / m_b if m_b > 0 else 1.0

    m_ratio_delta = (
        m_ratio_current / treaty.m_ratio_at_signing
        if treaty.m_ratio_at_signing > 0
        else 1.0
    )
    if m_ratio_delta > params.trade.renegotiate_m_ratio or m_ratio_delta < (
        1.0 / params.trade.renegotiate_m_ratio
    ):
        return True

    return False


def partners_with_kept_treaty(world: Any, nation_id: str) -> set[str]:
    """Return the set of nation ids that have a kept (unbreached) treaty with nation_id
    in the current year."""


    partners = set()

    for _treaty_id, treaty in world.treaties.items():
        # Check if this treaty involves nation_id
        other_id = None
        if treaty.a == nation_id:
            other_id = treaty.b
        elif treaty.b == nation_id:
            other_id = treaty.a
        else:
            continue

        # Check if unbreached this year
        if not treaty.breached_years:
            partners.add(other_id)

    return partners


def sigma_adjustment(world: Any, nation_id: str) -> float:
    """Return the σ (sovereign risk premium) adjustment due to treaty standing.

    +CreditParams.sigma_breach_penalty while under a breach penalty.
    −CreditParams.sigma_treaty_bonus per kept treaty (capped at −0.1 total).
    """


    params = world.params

    adjustment = 0.0

    # Breach penalty
    for _treaty_id, treaty in world.treaties.items():
        if (treaty.a == nation_id or treaty.b == nation_id) and (
            nation_id in treaty.penalty_until
        ):
            if treaty.penalty_until[nation_id] > world.year:
                adjustment += params.credit.sigma_breach_penalty

    # Kept treaty bonus
    partners = partners_with_kept_treaty(world, nation_id)
    kept_count = len(partners)
    adjustment -= params.credit.sigma_treaty_bonus * kept_count
    adjustment = max(adjustment, -0.1)

    return float(adjustment)


def route_penalty_factor(world: Any, nation_id: str) -> float:
    """Return the multiplier for route treaty_factor when nation_id is under breach penalty.

    Returns (1 - phi_breach) while under penalty, else 1.0.
    """


    params = world.params

    for _treaty_id, treaty in world.treaties.items():
        if (treaty.a == nation_id or treaty.b == nation_id) and (
            nation_id in treaty.penalty_until
        ):
            if treaty.penalty_until[nation_id] > world.year:
                return float(1.0 - params.trade.phi_breach)

    return 1.0


def step_treaties(world: Any) -> list[EventRecord]:
    """Step after step_war: manage treaties.

    - Lapse treaties whose signatory ended
    - Per-treaty check_breach
    - Update kept_treaties_count for hostility_update
    - Apply route effects (ROUTE_ACCESS/PORT_ACCESS/MOST_FAVOURED set treaty_factor)
    - Handle null sovereign treaty acceptance via null_sovereign_treaty_policy
    - Handle merchant charter (CHARTERED_COMPANY self-enactment) charter placement
    """

    from stock.core.laws import LawId
    from stock.core.records import ClassId

    params = world.params
    events: list[EventRecord] = []

    # Handle merchant charter placement (DD §7.4)
    # Look for law_self_enacted events of CHARTERED_COMPANY this year
    for nation in world.nations.values():
        # Find if CHARTERED_COMPANY was self-enacted
        cc_law = nation.laws.get(LawId.CHARTERED_COMPANY)
        if cc_law is not None and cc_law.enacted and cc_law.enacted_year == world.year:
            # Find the nation's route with smallest last_gap (and positive)
            best_route_id = None
            smallest_gap = float("inf")
            for route_id, route in world.routes.items():
                # Check if route involves this nation
                loc_a = world.locations.get(route.a)
                loc_b = world.locations.get(route.b)
                if loc_a is None or loc_b is None:
                    continue
                if loc_a.nation != nation.id and loc_b.nation != nation.id:
                    continue

                # Sum gaps
                total_gap = sum(route.last_gap_by_good.values())
                if total_gap > 0 and total_gap < smallest_gap:
                    smallest_gap = total_gap
                    best_route_id = route_id

            # Set charter holder on that route
            if best_route_id is not None:
                route = world.routes[best_route_id]
                # Find largest MERCHANTS record
                merchants_records = [
                    r
                    for r in nation.all_records(world)
                    if r.cls == ClassId.MERCHANTS
                ]
                if merchants_records:
                    largest = max(merchants_records, key=lambda r: r.size)
                    route.charter_holder = (nation.id, largest.cls)

    # Lapse treaties whose signatories ended
    lapse_on_end(world)

    # Check breaches for all treaties
    for _treaty_id, treaty in list(world.treaties.items()):
        breach_events = check_breach(treaty, world)
        events.extend(breach_events)

    # Update kept_treaties_count: recompute per pair as count of unbreached treaties
    world.kept_treaties_count.clear()
    for _treaty_id, treaty in world.treaties.items():
        # Check if unbreached this year (no entries in breached_years)
        if treaty.breached_years:
            continue

        # Increment kept count for canonical pair ordering
        if treaty.a < treaty.b:
            key = (treaty.a, treaty.b)
        else:
            key = (treaty.b, treaty.a)

        world.kept_treaties_count[key] = world.kept_treaties_count.get(key, 0.0) + 1.0
        treaty.kept_years += 1

    # Apply route effects
    for route_id, route in world.routes.items():
        # Find treaties that affect this route and apply treaty_factor
        route_factor = 1.0
        exclusive_to = None

        for _treaty_id, treaty in world.treaties.items():
            # Skip if treaty breached this year
            if treaty.breached_years:
                continue

            for term in treaty.terms:
                if term.kind == TermKind.ROUTE_ACCESS and term.route_id == route_id:
                    route_factor = max(route_factor, 1.0 + params.trade.treaty_route_bonus)
                elif term.kind == TermKind.PORT_ACCESS and term.location in [route.a, route.b]:
                    route_factor = max(route_factor, 1.0 + params.trade.treaty_route_bonus)
                elif term.kind == TermKind.MOST_FAVOURED:
                    route_factor = max(route_factor, 1.0 + params.trade.treaty_route_bonus)
                elif term.kind == TermKind.EXCLUSIVE_ROUTE and term.route_id == route_id:
                    exclusive_to = term.beneficiary

        route.treaty_factor = route_factor
        route.exclusive_to = exclusive_to

    # Null sovereign peace acceptance: auto-accept peace offers for null sovereigns
    for war_key, war in list(world.wars.items()):
        if war.peace_offer is not None:
            # Check if defender is a null sovereign
            defender = world.nations.get(war.defender)
            if defender is not None and defender.ai == "null":
                # Auto-accept the peace offer
                from stock.security.war import accept_peace
                accept_peace(world, war_key, war.defender)

    # Null sovereign treaty proposal acceptance
    null_sovereign_treaty_policy(world)

    return events


def null_sovereign_treaty_policy(world: Any) -> None:
    """Null sovereigns auto-accept treaty proposals that lower their PTV_ext estimate.

    For simplicity: null sovereigns accept any proposal (placeholder rule for Doc 06).
    """



    # This is a placeholder: in Doc 06, the AI will have more sophisticated rules.
    # For now, null sovereigns accept proposals that don't harm them.
    to_accept = []
    for i, proposal in enumerate(world.treaty_proposals):
        target = proposal.get("target")
        if target is None:
            continue

        target_nation = world.nations.get(target)
        if target_nation is None or target_nation.ai != "null":
            continue

        # Accept if it's offered to this nation
        to_accept.append(i)

    # Accept in reverse order to avoid index shifting
    for i in reversed(to_accept):
        proposal = world.treaty_proposals.pop(i)
        initiator = proposal.get("initiator")
        terms = proposal.get("terms", [])

        if initiator:
            # Call negotiate
            try:
                negotiate(world, initiator, target, terms)
            except Exception:
                pass  # Ignore errors in proposal acceptance
