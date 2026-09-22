"""Military doctrine, strength, and perceived security — year step 13 (Doc 04).

MM §14–15: doctrine from law and available records; strength and supply; loyalty of soldiers;
perceived security with threat and internal unrest terms; matchup ratios.
DD §9–10: doctrine indicators; army as a consumer; mobilisation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from stock.core.goods import Good
from stock.core.laws import LawId
from stock.core.params import Params
from stock.core.records import ClassId, Record
from stock.core.trees import DefenceNode
from stock.core.world import Nation, World
from stock.engine.market import record_demand
from stock.politics.state import events_this_year, order_signal
from stock.politics.unrest import loyalty


class Doctrine(Enum):
    """Military doctrines (DD §9.1, §9.2; MM §14–15)."""

    EVERY_MAN = "EVERY_MAN"
    NATION_IN_ARMS = "NATION_IN_ARMS"
    FEUDAL_HOST = "FEUDAL_HOST"
    MILITIA = "MILITIA"
    STANDING_ARMY = "STANDING_ARMY"


@dataclass
class SecurityResult:
    """Result of perceived_security computation."""

    PSV: float
    PTV_ext: float
    PTV_int_by_class: dict[str, float]
    N_r_by_record: dict[tuple[str, ClassId], float]
    N_bar: float
    f_N_by_record: dict[tuple[str, str, ClassId], float]


def has_firearms(nation: Nation, world: World) -> bool:
    """FIREARMS node is lit in the defence tree."""
    return nation.tree2.defence[DefenceNode.FIREARMS].lit


def has_navy(nation: Nation, world: World) -> bool:
    """NAVY node is lit in the defence tree."""
    return nation.tree2.defence[DefenceNode.NAVY].lit


def active_doctrine(nation: Nation, world: World) -> Doctrine:
    """Determine the active doctrine in priority order (MM §14; DD §9.1).

    STANDING_ARMY if STANDING_ARMY_ACT is enacted and a SOLDIERS record with size > 0 exists;
    else MILITIA if MILITIA_ACT enacted;
    else FEUDAL_HOST if nation has any FIELD producer and total RETAINERS size > 0;
    else NATION_IN_ARMS if any record holds wealth.herd > 0;
    else EVERY_MAN."""

    # The doctrine the nation's classes give it by themselves (no law needed)
    customary = _customary_doctrine(nation, world)
    customary_units = units(nation, world, customary)

    # A law-made doctrine (standing army, militia) displaces the customary one only
    # when it fields at least as many units: a herding nation that enacts the
    # Militia Act with a handful of tenants used to drop from sixty herdsmen in arms
    # to a militia of two, for as long as the law stood (A76).
    doctrine, fielded = customary, customary_units
    militia_law = nation.laws.get(LawId.MILITIA_ACT)
    if militia_law is not None and militia_law.enacted:
        militia = units(nation, world, Doctrine.MILITIA)
        if militia > 0 and militia >= fielded:
            doctrine, fielded = Doctrine.MILITIA, militia

    standing_army_law = nation.laws.get(LawId.STANDING_ARMY_ACT)
    if standing_army_law is not None and standing_army_law.enacted:
        soldiers = units(nation, world, Doctrine.STANDING_ARMY)
        if soldiers > 0 and soldiers >= fielded:
            doctrine = Doctrine.STANDING_ARMY

    return doctrine


def _customary_doctrine(nation: Nation, world: World) -> Doctrine:
    """FEUDAL_HOST if the nation has a field and retainers; else NATION_IN_ARMS if any
    record holds a herd; else EVERY_MAN."""

    # Check FEUDAL_HOST
    has_field = False
    retainers_total = 0.0
    for loc in nation.locations(world):
        for producer in loc.producers:
            from stock.core.producers import ProducerKind
            if producer.kind is ProducerKind.FIELD:
                has_field = True
        retainers = loc.record(ClassId.RETAINERS)
        if retainers is not None:
            retainers_total += retainers.size
    if has_field and retainers_total > 0:
        return Doctrine.FEUDAL_HOST

    # Check NATION_IN_ARMS
    for loc in nation.locations(world):
        for record in loc.records:
            if record.wealth.herd > 0:
                return Doctrine.NATION_IN_ARMS

    # Default to EVERY_MAN
    return Doctrine.EVERY_MAN


def units(nation: Nation, world: World, doctrine: Doctrine) -> float:
    """DD §9.2 "Fights" column: count of fighting units by doctrine.

    EVERY_MAN: hunters;
    NATION_IN_ARMS: herdsmen + herd-owners;
    FEUDAL_HOST: retainers + levy_share·serfs;
    MILITIA: militia_share·(tenants + craftsmen);
    STANDING_ARMY: soldiers."""

    params = world.params

    if doctrine is Doctrine.EVERY_MAN:
        # Hunters
        total = 0.0
        for loc in nation.locations(world):
            hunters = loc.record(ClassId.HUNTERS)
            if hunters is not None:
                total += hunters.size
        return total

    if doctrine is Doctrine.NATION_IN_ARMS:
        # Herdsmen + herd-owners
        total = 0.0
        for loc in nation.locations(world):
            herdsmen = loc.record(ClassId.HERDSMEN)
            if herdsmen is not None:
                total += herdsmen.size
            owners = loc.record(ClassId.HERD_OWNERS)
            if owners is not None:
                total += owners.size
        return total

    if doctrine is Doctrine.FEUDAL_HOST:
        # Retainers + levy_share·serfs
        total = 0.0
        for loc in nation.locations(world):
            retainers = loc.record(ClassId.RETAINERS)
            if retainers is not None:
                total += retainers.size
            serfs = loc.record(ClassId.SERFS)
            if serfs is not None:
                total += params.security.levy_share * serfs.size
        return total

    if doctrine is Doctrine.MILITIA:
        # militia_share·(tenants + craftsmen)
        total = 0.0
        for loc in nation.locations(world):
            tenants = loc.record(ClassId.TENANTS)
            if tenants is not None:
                total += tenants.size
            craftsmen = loc.record(ClassId.CRAFTSMEN)
            if craftsmen is not None:
                total += craftsmen.size
        return float(total * params.security.militia_share)

    if doctrine is Doctrine.STANDING_ARMY:
        # Soldiers
        total = 0.0
        for loc in nation.locations(world):
            soldiers = loc.record(ClassId.SOLDIERS)
            if soldiers is not None:
                total += soldiers.size
        return float(total)

    return 0.0


def equipment(nation: Nation, world: World) -> float:
    """Equipment multiplier: 1 + arms_per_unit_weight · arms_stock / max(units, 1).

    Uses active doctrine's units."""

    doctrine = active_doctrine(nation, world)
    u = units(nation, world, doctrine)
    if u <= 0:
        return 1.0
    arms_stock = nation.scalars.arms_stock
    return float(1.0 + world.params.security.arms_per_unit_weight * arms_stock / max(u, 1.0))


def doctrine_multiplier(doctrine: Doctrine, firearms: bool, params: Params) -> float:
    """Doctrine combat effectiveness from SecurityParams.doctrine_multiplier,
    with firearms_multiplier applied to STANDING_ARMY only."""

    multipliers = params.security.doctrine_multiplier
    base = multipliers.get(doctrine.value, 1.0)
    if doctrine is Doctrine.STANDING_ARMY and firearms:
        base *= params.security.firearms_multiplier
    return base


def supply(nation: Nation, world: World, doctrine: Doctrine) -> float:
    """Supply level: 1.0 for self-supplied doctrines, or min(1, army_bought/needed).

    EVERY_MAN, NATION_IN_ARMS, FEUDAL_HOST, MILITIA supply themselves (no logistics).
    STANDING_ARMY: min(1, army_bought/needed) where needed = sum of army_basket prices.
    When no defence draw exists, army_bought=0; supply=0 until Doc 05."""

    if doctrine in (Doctrine.EVERY_MAN, Doctrine.NATION_IN_ARMS, Doctrine.FEUDAL_HOST, Doctrine.MILITIA):
        return 1.0

    if doctrine is Doctrine.STANDING_ARMY:
        # Compute needed = sum of army_basket prices at the army's location
        u = units(nation, world, doctrine)
        if u <= 0:
            return 0.0

        # Find army location (STATE record's location, else most populous)
        army_location = None
        if nation.state is not None:
            army_location = world.locations.get(nation.state.location)
        if army_location is None:
            best_size = 0.0
            for loc in nation.locations(world):
                total_size = sum(r.size for r in loc.records)
                if total_size > best_size:
                    best_size = total_size
                    army_location = loc

        if army_location is None:
            return 0.0

        basket = army_basket(nation, world, doctrine)
        needed = 0.0
        for good, qty in basket.items():
            needed += world.params.prices.base_price.get(good, 1.0) * qty

        if needed <= 0:
            return 1.0

        return min(1.0, nation.scalars.army_bought / needed)

    return 1.0


def loyalty_factor(nation: Nation, world: World, doctrine: Doctrine) -> float:
    """Loyalty factor: STANDING_ARMY → loyalty(soldiers); else 1.0.

    For STANDING_ARMY, reads soldiers' subsistence satisfaction.
    Other doctrines assume full loyalty."""

    if doctrine is not Doctrine.STANDING_ARMY:
        return 1.0

    # Find SOLDIERS record
    for loc in nation.locations(world):
        soldiers = loc.record(ClassId.SOLDIERS)
        if soldiers is not None and soldiers.size > 0:
            return loyalty(soldiers)

    return 1.0


def strength(nation: Nation, world: World) -> tuple[float, float]:
    """Compute military strength (M, M_state) per MM §14.

    M = units × equipment × doctrine_multiplier × supply × loyalty.
    M_state = M for STANDING_ARMY/NAVY, else 0.

    Writes nation.scalars.M and M_state."""

    doctrine = active_doctrine(nation, world)
    nation.scalars.active_doctrine = doctrine.value

    u = units(nation, world, doctrine)
    if u <= 0:
        nation.scalars.M = 0.0
        nation.scalars.M_state = 0.0
        return 0.0, 0.0

    eq = equipment(nation, world)
    dm = doctrine_multiplier(doctrine, has_firearms(nation, world), world.params)
    sup = supply(nation, world, doctrine)
    loy = loyalty_factor(nation, world, doctrine)

    M = u * eq * dm * sup * loy

    # M_state is M for STANDING_ARMY/NAVY, else 0
    if doctrine is Doctrine.STANDING_ARMY or has_navy(nation, world):
        M_state = M
    else:
        M_state = 0.0

    nation.scalars.M = M
    nation.scalars.M_state = M_state
    return M, M_state


def army_basket(nation: Nation, world: World, doctrine: Doctrine) -> dict[Good, float]:
    """Army consumption basket per doctrine (DD §9.2 "Eats").

    FEUDAL_HOST: {PROVISIONS: units}
    MILITIA: {PROVISIONS: units, ARMS: arms_share·units}
    STANDING_ARMY: {PROVISIONS: units, WARES: wares_share·units, ARMS: arms_share·units}
    Others: {}

    Basket is multiplied by wartime_basket_multiplier when at_war."""

    u = units(nation, world, doctrine)
    params = world.params.security
    basket: dict[Good, float] = {}

    if doctrine is Doctrine.FEUDAL_HOST:
        basket[Good.PROVISIONS] = u
    elif doctrine is Doctrine.MILITIA:
        basket[Good.PROVISIONS] = u
        basket[Good.ARMS] = params.arms_share * u
    elif doctrine is Doctrine.STANDING_ARMY:
        basket[Good.PROVISIONS] = u
        basket[Good.WARES] = params.wares_share * u
        basket[Good.ARMS] = params.arms_share * u

    # Apply wartime multiplier
    if nation.scalars.at_war:
        multiplier = world.params.security.wartime_basket_multiplier
        for good in basket:
            basket[good] *= multiplier

    return basket


def army_purchase(nation: Nation, world: World) -> None:
    """Purchase army basket at the army's location market.

    Budget = defence_draw - soldier_pay·soldiers.size.
    Buys ARMS first up to arms_share, then PROVISIONS/WARES.
    Increments arms_stock and army_bought."""

    doctrine = active_doctrine(nation, world)

    # Find army location
    army_location = None
    if nation.state is not None:
        army_location = world.locations.get(nation.state.location)
    if army_location is None:
        best_size = 0.0
        for loc in nation.locations(world):
            total_size = sum(r.size for r in loc.records)
            if total_size > best_size:
                best_size = total_size
                army_location = loc

    if army_location is None:
        nation.scalars.army_bought = 0.0
        return

    # Compute budget
    soldiers_size = 0.0
    for loc in nation.locations(world):
        soldiers = loc.record(ClassId.SOLDIERS)
        if soldiers is not None:
            soldiers_size += soldiers.size

    pay_bill = nation.scalars.soldier_pay * max(soldiers_size, 1.0)
    budget = nation.scalars.defence_draw - pay_bill

    if budget <= 0:
        nation.scalars.army_bought = 0.0
        return

    basket = army_basket(nation, world, doctrine)
    remaining_budget = budget
    total_bought = 0.0
    arms_bought = 0.0

    # Buy ARMS first
    if Good.ARMS in basket:
        arms_qty = basket[Good.ARMS]
        arms_price = world.params.prices.base_price.get(Good.ARMS, 1.0)
        arms_available = min(arms_qty, remaining_budget / arms_price) if arms_price > 0 else 0.0
        arms_bought = arms_available * arms_price
        remaining_budget -= arms_bought
        total_bought += arms_bought
        record_demand(army_location, Good.ARMS, arms_available)

    # Buy PROVISIONS and WARES
    for good in [Good.PROVISIONS, Good.WARES]:
        if good not in basket or remaining_budget <= 0:
            continue
        qty = basket[good]
        price = world.params.prices.base_price.get(good, 1.0)
        available = min(qty, remaining_budget / price) if price > 0 else 0.0
        cost = price * available
        remaining_budget -= cost
        total_bought += cost
        record_demand(army_location, good, available)

    nation.scalars.arms_stock += arms_bought / world.params.prices.base_price.get(Good.ARMS, 1.0)
    nation.scalars.army_bought = total_bought


def mobilise(nation: Nation, world: World, on: bool) -> None:
    """Set/unset mobilised flag on doctrine's fighting records.

    NATION_IN_ARMS: herdsmen/herd-owners
    FEUDAL_HOST: retainers/serfs
    MILITIA: tenants/craftsmen
    STANDING_ARMY: soldiers
    EVERY_MAN: hunters"""

    doctrine = active_doctrine(nation, world)

    if doctrine is Doctrine.EVERY_MAN:
        for loc in nation.locations(world):
            hunters = loc.record(ClassId.HUNTERS)
            if hunters is not None:
                hunters.mobilised = on

    elif doctrine is Doctrine.NATION_IN_ARMS:
        for loc in nation.locations(world):
            for cls in [ClassId.HERDSMEN, ClassId.HERD_OWNERS]:
                record = loc.record(cls)
                if record is not None:
                    record.mobilised = on

    elif doctrine is Doctrine.FEUDAL_HOST:
        for loc in nation.locations(world):
            for cls in [ClassId.RETAINERS, ClassId.SERFS]:
                record = loc.record(cls)
                if record is not None:
                    record.mobilised = on

    elif doctrine is Doctrine.MILITIA:
        for loc in nation.locations(world):
            for cls in [ClassId.TENANTS, ClassId.CRAFTSMEN]:
                record = loc.record(cls)
                if record is not None:
                    record.mobilised = on

    elif doctrine is Doctrine.STANDING_ARMY:
        for loc in nation.locations(world):
            soldiers = loc.record(ClassId.SOLDIERS)
            if soldiers is not None:
                soldiers.mobilised = on


def nation_distance(world: World, a: str, b: str) -> float:
    """Minimum Dijkstra carriage distance between any location pair of two nations.

    Uses reachable_within with c_max=inf. Returns inf if unreachable."""

    from stock.engine.market import reachable_within

    a_nation = world.nations.get(a)
    b_nation = world.nations.get(b)
    if a_nation is None or b_nation is None:
        return float("inf")

    min_dist = float("inf")
    for a_loc in a_nation.locations(world):
        reachable = reachable_within(world, a_loc, c_max=float("inf"))
        for b_loc in b_nation.locations(world):
            dist = reachable.get(b_loc.id, float("inf"))
            if dist < min_dist:
                min_dist = dist

    return min_dist


def perceived_security(nation: Nation, world: World) -> SecurityResult:
    """Compute perceived security (MM §14).

    PSV' = λ·PSV + (1−λ)·a·ln(1+M) + p·O
    PTV_ext = Σ_i b·ln(1+M_i)·h_i·g(d_i)
    PTV_int,r = c_r·ln(1+R_private) + u·ln(1+U_dis)
    N_r = PSV − PTV_ext − PTV_int,r
    N̄ = Σ authority_r·N_r / Σ authority_r
    f(N_r) = 1/(1+e^{−κ(N_r−N0)})

    Stores PSV, PTV_ext, N_bar in nation.scalars.
    Stores f(N_r) in world._f_n_by_record."""

    params = world.params
    s = nation.scalars

    # Order signal from this year's events
    events = events_this_year(nation.id, world)
    O = order_signal(events, params)
    s.O = O

    # PSV update
    M = s.M
    psv_term = (1.0 - params.security.psv_lag_lambda) * params.security.security_scale_a * math.log1p(M)
    psv_new = (
        params.security.psv_lag_lambda * s.PSV +
        psv_term +
        params.security.psv_event_weight_p * O
    )
    s.PSV = max(0.0, psv_new)

    # External threat (PTV_ext)
    PTV_ext = 0.0
    living_rivals = [
        (nid, n) for nid, n in world.nations.items()
        if nid != nation.id and not n.ended
    ]

    # Get treaty partners for this nation to reduce h_ij for treaty partners
    from stock.trade.treaties import partners_with_kept_treaty

    treaty_partners = partners_with_kept_treaty(world, nation.id)

    for rival_id, _rival in living_rivals:
        from stock.trade.hostility import hostility as get_hostility

        rival_M = world.prev.M.get(rival_id, 0.0)
        h_ij = get_hostility(world, nation.id, rival_id)

        # Reduce h_ij for treaty partners (MM §17: treaty reduces PTV_ext)
        if rival_id in treaty_partners:
            h_ij = h_ij * (1.0 - params.trade.treaty_ptv_reduction)

        d_ij = nation_distance(world, nation.id, rival_id)

        if d_ij == float("inf"):
            continue

        g_d = 1.0 / (1.0 + d_ij / params.security.distance_decay_d0)
        PTV_ext += (
            params.security.threat_scale_b * math.log1p(rival_M) *
            h_ij * g_d
        )

    s.PTV_ext = PTV_ext

    # Compute R_private fresh (not lagged) for this year's internal threat
    from stock.politics.state import r_private as compute_r_private
    r_priv = compute_r_private(nation, world)
    s.R_private = r_priv

    # Internal threat per class and N_r per record
    PTV_int_by_class: dict[str, float] = {}
    N_r_by_record: dict[tuple[str, ClassId], float] = {}

    for loc in nation.locations(world):
        for record in loc.records:
            if record.cls is ClassId.STATE or record.size <= 0:
                continue

            cls_name = record.cls.name
            c_r = params.security.internal_threat_c_r.get(cls_name, 0.0)
            PTV_int_r = (
                c_r * math.log1p(r_priv) +
                params.security.disorder_weight_u * math.log1p(s.U_dis)
            )
            PTV_int_by_class[cls_name] = PTV_int_r

            N_r = s.PSV - PTV_ext - PTV_int_r
            key = (nation.id, loc.id, record.cls)
            N_r_by_record[(loc.id, record.cls)] = N_r

            # f(N_r) = 1/(1+e^{-κ(N_r-N0)})
            exp_arg = params.security.sigmoid_slope_kappa_f * (N_r - params.security.sigmoid_centre_n0)
            # Clamp exponent to avoid overflow
            exp_arg = max(-100.0, min(100.0, exp_arg))
            f_N = 1.0 / (1.0 + math.exp(-exp_arg))
            # Clamp to (0, 1) strictly to avoid boundary issues
            f_N = max(1e-9, min(1.0 - 1e-9, f_N))
            world._f_n_by_record[key] = f_N

    # N̄ = Σ authority_r·N_r / Σ authority_r
    auth_sum = 0.0
    auth_weighted_N = 0.0
    for loc in nation.locations(world):
        for record in loc.records:
            if record.cls is ClassId.STATE or record.size <= 0:
                continue
            N_r = N_r_by_record.get((loc.id, record.cls), 0.0)
            auth_sum += record.authority
            auth_weighted_N += record.authority * N_r

    if auth_sum > 0:
        N_bar = auth_weighted_N / auth_sum
    else:
        # Plain mean when no authority
        N_r_values = list(N_r_by_record.values())
        N_bar = sum(N_r_values) / len(N_r_values) if N_r_values else 0.0

    s.N_bar = N_bar

    return SecurityResult(
        PSV=s.PSV,
        PTV_ext=PTV_ext,
        PTV_int_by_class=PTV_int_by_class,
        N_r_by_record=N_r_by_record,
        N_bar=N_bar,
        f_N_by_record=dict(world._f_n_by_record),
    )


def matchup(
    attacker: Doctrine, defender: Doctrine, firearms_att: bool, firearms_def: bool, params: Params
) -> float:
    """Ratio of attacker's doctrine_multiplier to defender's (MM §15).

    Encodes the doctrine matchup ordering (standing army + firearms > all others)."""

    att_mult = doctrine_multiplier(attacker, firearms_att, params)
    def_mult = doctrine_multiplier(defender, firearms_def, params)
    if def_mult <= 0:
        return float("inf")
    return att_mult / def_mult


def step_security(world: World) -> None:
    """Year step 13a (after legislation, before band loop).

    Pass 1: compute strength for every living nation.
    Pass 2: compute perceived_security for every living nation.
    Pass 3: hostility_update.
    """

    from stock.trade.hostility import hostility_update

    # Pass 1: strength
    for nation in world.nations.values():
        if nation.ended:
            continue
        strength(nation, world)

    # Pass 2: perceived_security
    for nation in world.nations.values():
        if nation.ended:
            continue
        perceived_security(nation, world)

    # Pass 3: set soldier pay for recruitment (DD §9.2 recruitment via mobility)
    from stock.core.laws import LawId
    for nation in world.nations.values():
        if nation.ended:
            continue
        standing_army_law = nation.laws.get(LawId.STANDING_ARMY_ACT)
        if standing_army_law is not None and standing_army_law.enacted:
            # Find or create SOLDIERS record at army location
            army_location = None
            if nation.state is not None:
                army_location = world.locations.get(nation.state.location)
            if army_location is None:
                best_size = 0.0
                for loc in nation.locations(world):
                    total_size = sum(r.size for r in loc.records)
                    if total_size > best_size:
                        best_size = total_size
                        army_location = loc

            if army_location is not None:
                soldiers = army_location.record(ClassId.SOLDIERS)
                if soldiers is None:
                    soldiers = Record(cls=ClassId.SOLDIERS, location=army_location.id, size=0.0)
                    army_location.records.append(soldiers)
                # Set last_gross_income = soldier_pay * max(size, 1)
                soldiers.last_gross_income = nation.scalars.soldier_pay * max(soldiers.size, 1.0)

    # Pass 4: hostility decrements
    hostility_update(world)


def step_army_purchase(world: World) -> None:
    """Year step 5a (after step_consumption).

    For each living nation with STANDING_ARMY doctrine and a defence_draw,
    purchase the army basket."""

    for nation in world.nations.values():
        if nation.ended:
            continue
        doctrine = active_doctrine(nation, world)
        if doctrine is Doctrine.STANDING_ARMY:
            army_purchase(nation, world)
