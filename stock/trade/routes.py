"""Cross-border routes for goods and stock flows (DD §10; MM §16).

Routes move goods from low-price to high-price markets (arbitrage), and move stock
between locations when returns differ (capital flows). Both flows are capped by route
capacity, which depends on merchant stock committed, Ships, and carriage cost.

Hostility, laws, and treaties all modulate capacity and the gap that drives arbitrage.
"""

from __future__ import annotations

from stock.core.goods import ALL_GOODS, Good
from stock.core.records import ClassId
from stock.core.world import Location, Route, World
from stock.engine.market import carriage_cost, record_demand, record_supply
from stock.engine.mobility import _get_or_create, flow
from stock.trade.hostility import add_hostility, hostility


def discover_routes(world: World) -> None:
    """Create a `Route` for every pair of neighbouring locations whose nations differ
    (both non-None) if none exists yet. Route ids: `f"{a}->{b}"` with `a < b` (location ids).
    Called at the start of `step_routes`."""

    existing_ids = set(world.routes.keys())
    for loc_a_id, loc_a in world.locations.items():
        if loc_a.nation is None:
            continue
        for loc_b_id in loc_a.neighbours:
            loc_b = world.locations.get(loc_b_id)
            if loc_b is None or loc_b.nation is None or loc_b.nation == loc_a.nation:
                continue
            # Carriage cost must be finite (non-infinite neighbours only)
            cost = carriage_cost(loc_a, loc_b_id)
            if cost == float("inf"):
                continue
            # Create route id (sorted)
            a, b = (loc_a_id, loc_b_id) if loc_a_id < loc_b_id else (loc_b_id, loc_a_id)
            route_id = f"{a}->{b}"
            if route_id not in existing_ids:
                world.routes[route_id] = Route(id=route_id, a=a, b=b)


def capacity(route: Route, world: World) -> float:
    """MM §16: k_cap · Σ merchant stock committed · (1 + bills) · max(1, ships)
    · method / carriage_cost · (1 − law_friction) · treaty_factor.

    DD §3: "barter at a shared border is the first route". Use barter formula
    (k_cap · barter_capacity / carriage_cost) when sum(merchant_stock) <= 0
    (no merchant committed by either side).
    law_friction = navigation_friction · enforcement(NAVIGATION_ACT) for whichever side
    has it; (route closed) if a prohibition_law(good) is enacted on either side.

    Returns the total capacity across all goods (before per-good prohibitions).
    Per-good prohibitions are checked in `clear_goods`."""

    loc_a = world.locations.get(route.a)
    loc_b = world.locations.get(route.b)
    if loc_a is None or loc_b is None:
        return 0.0

    # Carriage cost (needed for both regular and barter routes)
    cost = carriage_cost(loc_a, route.b)
    if cost == float("inf") or cost <= 0:
        return 0.0

    # Merchant stock committed: sum over both nations' merchants at this route
    # But filter for EXCLUSIVE_ROUTE: only holder's stock counts
    total_committed = 0.0
    if route.exclusive_to is not None:
        # Only the exclusive holder's stock counts
        total_committed = route.merchant_stock.get(route.exclusive_to, 0.0)
    else:
        total_committed = sum(route.merchant_stock.values())

    # Barter route handling: when sum(merchant_stock) <= 0, use barter capacity
    if total_committed <= 0:
        barter_cap = world.params.trade.k_cap * world.params.trade.barter_capacity / cost
        return float(max(0.0, barter_cap))

    # Bills of exchange (Doc 05 — placeholder 0 for now)
    bills = 0.0

    # Ships multiplier
    ships = max(1.0, route.ships)

    # Method multiplier (Doc 05 lights methods; placeholder 1.0)
    method = 1.0

    # Law friction: NAVIGATION_ACT on either side
    law_friction = 0.0
    for nation_id in [world.locations[route.a].nation, world.locations[route.b].nation]:
        if nation_id is None:
            continue
        nation = world.nations.get(nation_id)
        if nation is None:
            continue
        from stock.core.laws import LawId

        nav_law = nation.laws.get(LawId.NAVIGATION_ACT)
        if nav_law is not None and nav_law.enacted:
            law_friction = max(
                law_friction, world.params.trade.navigation_friction * nav_law.enforcement
            )

    cap = (
        world.params.trade.k_cap
        * total_committed
        * (1.0 + bills)
        * ships
        * method
        / cost
        * (1.0 - law_friction)
        * route.treaty_factor
    )
    return float(max(0.0, cap))


def border_friction(loc_a_id: str, loc_b_id: str, world: World) -> float:
    """MM §2 cross-border friction: carriage_cost/c_max + h_ij + (1 − f(N̄_dest))
    + treaty_terms, clamped to [0, 1].

    f(N̄_dest) = 1/(1+e^{−κf(N̄_dest − N0)}) on the destination nation's scalars.N_bar.
    treaty_terms = 0 unless T5 sets route.treaty_factor < 1 (use 1 − treaty_factor).
    """

    loc_a = world.locations.get(loc_a_id)
    loc_b = world.locations.get(loc_b_id)
    if loc_a is None or loc_b is None:
        return 1.0

    nation_a = loc_a.nation
    nation_b = loc_b.nation
    if nation_a is None or nation_b is None:
        return 1.0

    # Carriage cost component
    cost = carriage_cost(loc_a, loc_b_id)
    if cost == float("inf"):
        cost = world.params.prices.c_max * 10  # Very high cost
    carriage_term = cost / world.params.prices.c_max if world.params.prices.c_max > 0 else 0.5

    # Hostility component
    h_ij = hostility(world, nation_a, nation_b)

    # Security sigmoid on destination nation
    n_bar_dest = world.nations[nation_b].scalars.N_bar
    kappa = world.params.security.sigmoid_slope_kappa_f
    n0 = world.params.security.sigmoid_centre_n0
    f_n_bar = 1.0 / (1.0 + 2.718281828 ** (-kappa * (n_bar_dest - n0)))  # e^x approximation

    # Treaty terms (0 until T5 sets route.treaty_factor)
    treaty_term = 0.0
    # TODO: look up route and compute treaty_term from 1 - treaty_factor

    friction = carriage_term + h_ij + (1.0 - f_n_bar) + treaty_term
    return float(min(1.0, max(0.0, friction)))


def clear_goods(route: Route, world: World) -> None:
    """Move each good from low-price to high-price market up to capacity and arbitrage volume.
    Merchant income = volume · (p_high − p_low − carriage) split by nation's merchant stock share.
    Accumulates route_volume to world.trade_volume (both directions).
    If two nations' merchants both commit stock, add hostility for route competition.
    """

    from stock.core.laws import prohibition_law, tariff_law

    loc_a = world.locations.get(route.a)
    loc_b = world.locations.get(route.b)
    if loc_a is None or loc_b is None:
        return

    nation_a = loc_a.nation
    nation_b = loc_b.nation
    if nation_a is None or nation_b is None:
        return

    # Compute capacity once
    cap = capacity(route, world)
    capacity_remaining = cap
    route.last_volume_by_good.clear()
    route.last_gap_by_good.clear()
    route.last_capacity = cap

    # If capacity is 0, still record gaps so ledger shows why routes didn't clear
    if cap <= 0:
        for good in ALL_GOODS:
            if good == Good.ATTENDANCE:
                continue
            p_a = loc_a.market.price.get(good, 1.0)
            p_b = loc_b.market.price.get(good, 1.0)
            cost = carriage_cost(loc_a, route.b)
            if cost == float("inf") or cost <= 0:
                continue
            gap = max(p_a, p_b) - min(p_a, p_b) - cost
            route.last_gap_by_good[good] = max(0.0, gap)
        return

    # Track if both nations committed stock (for hostility)
    both_committed = (
        route.merchant_stock.get(nation_a, 0.0) > 0
        and route.merchant_stock.get(nation_b, 0.0) > 0
    )

    # Iterate over goods (all except ATTENDANCE)
    for good in ALL_GOODS:
        if good == Good.ATTENDANCE:
            continue

        if capacity_remaining <= 0:
            break

        # Market prices
        p_a = loc_a.market.price.get(good, 1.0)
        p_b = loc_b.market.price.get(good, 1.0)

        # Identify low and high sides
        if p_a < p_b:
            p_low, p_high = p_a, p_b
            low_loc, high_loc = loc_a, loc_b
            low_nation, high_nation = nation_a, nation_b
        else:
            p_low, p_high = p_b, p_a
            low_loc, high_loc = loc_b, loc_a
            low_nation, high_nation = nation_b, nation_a

        cost = carriage_cost(low_loc, high_loc.id)
        if cost == float("inf") or cost <= 0:
            continue

        # Convert carriage distance to baskets (MM §16: P_high - P_low - carriage)
        carriage_baskets = cost * world.params.trade.carriage_price_per_unit
        gap = p_high - p_low - carriage_baskets

        # Check for prohibition on either side
        prohibited = False
        for nation_id in [nation_a, nation_b]:
            if nation_id is None:
                continue
            nation = world.nations.get(nation_id)
            if nation is None:
                continue
            prob_law = nation.laws.get(prohibition_law(good))
            if prob_law is not None and prob_law.enacted:
                prohibited = True
                break

        if prohibited or gap <= 0:
            route.last_gap_by_good[good] = max(0.0, gap)
            continue

        # Apply tariff if enacted on importing side
        tariff_wedge = 0.0
        if gap > 0:
            importing_nation = high_nation
            importing_nation_obj = world.nations.get(importing_nation) if importing_nation else None
            importing_laws = importing_nation_obj.laws if importing_nation_obj else {}
            tariff = importing_laws.get(tariff_law(good)) if importing_laws else None
            if tariff is not None and tariff.enacted:
                tariff_wedge = world.params.trade.tariff_rate * p_low * tariff.enforcement
                gap = max(0.0, gap - tariff_wedge)

        # Arbitrage volume: check inventory on low side
        # inventory is only filled by unsold output (step 2: output → inventory).
        # If inventory is empty, use this year's production surplus (last_supply − last_demand).
        low_inventory = low_loc.market.inventory.get(good, 0.0)
        if low_inventory <= 0:
            # No prior inventory; use this year's production surplus (step 1 already ran)
            last_supply = low_loc.market.last_supply.get(good, 0.0)
            last_demand = low_loc.market.last_demand.get(good, 0.0)
            sellable_surplus = max(0.0, last_supply - last_demand)
            low_inventory = sellable_surplus
        arbitrage_vol = min(low_inventory, gap / max(carriage_baskets, 1e-6))
        arbitrage_vol = max(0.0, arbitrage_vol)

        # Actual volume
        volume = min(capacity_remaining, arbitrage_vol)
        if volume <= 0:
            route.last_gap_by_good[good] = max(0.0, gap)
            continue

        # Move inventory
        low_loc.market.inventory[good] = low_loc.market.inventory.get(good, 0.0) - volume
        high_loc.market.inventory[good] = high_loc.market.inventory.get(good, 0.0) + volume

        # Record supply/demand
        record_demand(low_loc, good, volume)
        record_supply(high_loc, good, volume)

        # Merchant income
        merchant_income = volume * gap
        if merchant_income > 0:
            # Split by nation's committed stock share
            a_committed = route.merchant_stock.get(low_nation, 0.0)
            b_committed = route.merchant_stock.get(high_nation, 0.0)
            total_committed = a_committed + b_committed
            if total_committed > 0:
                a_share = a_committed / total_committed
                b_share = b_committed / total_committed
                # Add to MERCHANTS records in their home locations
                _add_merchant_income(world, low_nation, merchant_income * a_share)
                _add_merchant_income(world, high_nation, merchant_income * b_share)

            # Accumulate customs collected if tariff applied
            if tariff_wedge > 0:
                route.customs_collected += tariff_wedge * volume

        # Trade volume (symmetric)
        volume_key_a = (low_nation, high_nation) if low_nation < high_nation else (high_nation, low_nation)
        volume_key_b = (high_nation, low_nation) if low_nation < high_nation else (low_nation, high_nation)
        world.trade_volume[volume_key_a] = world.trade_volume.get(volume_key_a, 0.0) + volume
        if volume_key_a != volume_key_b:
            world.trade_volume[volume_key_b] = world.trade_volume.get(volume_key_b, 0.0) + volume

        route.last_volume_by_good[good] = volume
        route.last_gap_by_good[good] = gap
        capacity_remaining -= volume

    # Hostility for route competition
    if both_committed and sum(route.last_volume_by_good.values()) > 0:
        add_hostility(world, nation_a, nation_b, world.params.trade.h_route_competition)


def _add_merchant_income(world: World, nation_id: str, income: float) -> None:
    """Add income to the MERCHANTS record at the nation's largest MERCHANTS location,
    or create one if none exists."""

    nation = world.nations.get(nation_id)
    if nation is None:
        return

    # Find MERCHANTS record at the route endpoint (if exists)
    locations = nation.locations(world)
    merchant_records = [
        r for loc in locations for r in loc.records if r.cls == ClassId.MERCHANTS
    ]
    if not merchant_records:
        return

    # Pick the largest by size, or first by location if tied
    largest = max(merchant_records, key=lambda r: (r.size, world.locations[r.location].id))
    largest.income += income


def route_demand(good: Good, location: Location, world: World) -> float:
    """MM §9 'route demand at capacity': Σ over routes touching `location` of last year's
    export volume of `good` at capacity. Used to compute market_size."""

    total = 0.0
    loc_id = location.id
    for route in world.routes.values():
        if route.a != loc_id and route.b != loc_id:
            continue
        # Only count if this location is the exporting side
        # (we count what's exported from this location to the other)
        vol = route.last_volume_by_good.get(good, 0.0)
        if vol > 0:
            total += vol
    return total


def clear_stock(route: Route, world: World) -> None:
    """Cross-border owners-of-stock edge (DD §10.2; MM §2): move stock from low-return
    to high-return location. For MERCHANTS and CAPITALISTS at each endpoint:
    na = r_bar_other − r_bar_own − border_friction(a, b);
    if na > 0, move share = flow(1.0, rate_edge_base, 0, na) of hoard to same-class
    record at other endpoint (wealth-only mode: size does not move).
    """


    loc_a = world.locations.get(route.a)
    loc_b = world.locations.get(route.b)
    if loc_a is None or loc_b is None:
        return

    nation_a = loc_a.nation
    nation_b = loc_b.nation
    if nation_a is None or nation_b is None:
        return

    nation_a_obj = world.nations.get(nation_a)
    nation_b_obj = world.nations.get(nation_b)
    if nation_a_obj is None or nation_b_obj is None:
        return

    r_bar_a = nation_a_obj.scalars.r_bar
    r_bar_b = nation_b_obj.scalars.r_bar
    friction = border_friction(route.a, route.b, world)

    # Classes that flow in the owners-of-stock tier
    owner_classes = (ClassId.MERCHANTS, ClassId.CAPITALISTS)

    # A -> B
    for cls in owner_classes:
        rec_a = loc_a.record(cls)
        if rec_a is None or rec_a.size <= 0:
            continue
        na_b = r_bar_b - r_bar_a - friction
        if na_b <= 0:
            continue
        share = flow(1.0, world.params.mobility.rate_edge_base, 0.0, na_b)
        if share <= 0:
            continue
        # Move hoard only (wealth-only mode): size does not move
        moved_hoard = rec_a.wealth.hoard * share
        rec_a.wealth.hoard -= moved_hoard
        # Get or create destination record
        rec_b = loc_b.record(cls)
        if rec_b is None:
            rec_b = _get_or_create(loc_b, cls)
        rec_b.wealth.hoard += moved_hoard
        rec_b.flags.add("foreign_stock")

    # B -> A
    for cls in owner_classes:
        rec_b = loc_b.record(cls)
        if rec_b is None or rec_b.size <= 0:
            continue
        na_a = r_bar_a - r_bar_b - friction
        if na_a <= 0:
            continue
        share = flow(1.0, world.params.mobility.rate_edge_base, 0.0, na_a)
        if share <= 0:
            continue
        moved_hoard = rec_b.wealth.hoard * share
        rec_b.wealth.hoard -= moved_hoard
        rec_a = loc_a.record(cls)
        if rec_a is None:
            rec_a = _get_or_create(loc_a, cls)
        rec_a.wealth.hoard += moved_hoard
        rec_a.flags.add("foreign_stock")


def step_routes(world: World) -> None:
    """Year step 4 (after step_market): discover routes, commit merchant stock,
    clear goods and stock for every route."""

    # Step 1: Discover new routes
    discover_routes(world)

    # Step 2: Commit merchant stock from each nation's MERCHANTS records
    for route in world.routes.values():
        route.merchant_stock.clear()
        for nation_id in [world.locations[route.a].nation, world.locations[route.b].nation]:
            if nation_id is None:
                continue
            nation = world.nations.get(nation_id)
            if nation is None:
                continue

            # Find MERCHANTS records at the route endpoints and the nation's largest
            merchants_at_a = []
            merchants_at_b = []
            for loc in nation.locations(world):
                for r in loc.records:
                    if r.cls == ClassId.MERCHANTS:
                        if loc.id == route.a:
                            merchants_at_a.append(r)
                        elif loc.id == route.b:
                            merchants_at_b.append(r)

            # Use endpoint merchant if present, else the largest in the nation
            merchant_records = merchants_at_a if merchants_at_a else (
                merchants_at_b if merchants_at_b else None
            )
            if merchant_records is None:
                # Find the largest MERCHANTS record anywhere in the nation
                all_merchants = [
                    r for loc in nation.locations(world) for r in loc.records
                    if r.cls == ClassId.MERCHANTS
                ]
                if not all_merchants:
                    route.merchant_stock[nation_id] = 0.0
                    continue
                merchant_records = [max(all_merchants, key=lambda x: x.size)]

            # Compute committed stock
            committed = 0.0
            for r in merchant_records:
                basis = r.wealth.hoard + r.wealth.stock_in_place
                committed += basis * world.params.trade.merchant_commit_share

            route.merchant_stock[nation_id] = committed

    # Step 3: Clear goods on each route
    for route in world.routes.values():
        clear_goods(route, world)

    # Step 4: Clear stock flows on each route
    for route in world.routes.values():
        clear_stock(route, world)
