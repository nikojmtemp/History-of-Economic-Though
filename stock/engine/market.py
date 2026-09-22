"""Prices and the extent of the market — year step 4, goods only (DD §4.5, §4.7; MM
§7, §9). Cross-border routes are Doc 04's; this module only moves goods between two
locations of the *same* nation, and only by carriage cost (DD §4.7's "capacity from
carriage only" for the within-nation case)."""

from __future__ import annotations

import heapq

from stock.core.goods import ALL_GOODS, CONSUMABLE_GOODS, TIER, Good
from stock.core.params import Params
from stock.core.producers import Producer
from stock.core.world import Location, Nation, World


def market_price(
    base: float, demand: float, supply: float, eps: float, ratio_floor: float, ratio_cap: float
) -> float:
    """`P_g = base_g * (D_g/S_g)^eps_g` (MM §7), with numerical stability bounds
    applied to the D/S ratio before the exponent."""

    ratio = demand / max(supply, 1e-9)
    ratio = min(max(ratio, ratio_floor), ratio_cap)
    return float(base * (ratio**eps))


def natural_price(good: Good, producers: list[Producer], r_bar: float) -> float | None:
    """`P_nat,g = w*labour_per_unit + r_bar*stock_per_unit + rent_per_unit`, at the
    average rates of `good`'s producers (MM §7). `None` if no producer makes `good`."""

    weighted_sum = 0.0
    weight_total = 0.0
    for p in producers:
        rate = p.outputs.get(good, 0.0) if p.outputs else 0.0
        if rate <= 0 or p.last_Q <= 0:
            continue
        output_of_good = p.last_Q * rate
        labour_cost = sum(p.filled.values()) * p.last_wage
        stock_cost = r_bar * p.stock_in_place
        rent_cost = p.last_V - labour_cost - stock_cost  # this year's realised rent share
        per_unit_q = (labour_cost + stock_cost + max(0.0, rent_cost)) / p.last_Q
        per_unit_good = per_unit_q / rate
        weighted_sum += per_unit_good * output_of_good
        weight_total += output_of_good
    if weight_total <= 0:
        return None
    return weighted_sum / weight_total


def update_market_prices(location: Location, params: Params, producible: set[Good] | None = None) -> None:
    """Recompute this year's price from last year's recorded demand/supply (the
    natural cobweb lag: this year's actual demand/supply for `good` isn't known until
    steps 1 and 5 run, both of which touch this same step-4 window across the year
    boundary — so, like DD §4.3's "V at last year's price", the price sets from what's
    already on the books). Carries and decays unsold inventory (MM §7).

    If `producible` is provided (set of goods made by any producer in the nation),
    a good with no supply, no demand, and no inventory (unobtainable) leaves its price
    unchanged unless it's producible in the nation."""

    if producible is None:
        producible = set(ALL_GOODS)

    market = location.market
    for good in ALL_GOODS:
        eps = params.prices.eps.get(good, 1.0)
        base = params.prices.base_price.get(good, 1.0)
        demand = market.last_demand.get(good, 0.0)
        supply = market.last_supply.get(good, 0.0)
        inventory = market.inventory.get(good, 0.0)

        # Leave price unchanged if good is unobtainable and not producible in the nation
        if demand == 0 and supply == 0 and inventory == 0 and good not in producible:
            pass  # price unchanged
        elif demand > 0 or supply > 0:
            market.price[good] = market_price(
                base, demand, supply, eps, params.prices.ratio_floor, params.prices.ratio_cap
            )

        unsold = max(0.0, supply - demand)
        market.inventory[good] = (market.inventory.get(good, 0.0) + unsold) * (
            1.0 - params.prices.inventory_decay
        )


def record_supply(location: Location, good: Good, quantity: float) -> None:
    location.market.last_supply[good] = location.market.last_supply.get(good, 0.0) + quantity


def record_demand(location: Location, good: Good, quantity: float) -> None:
    location.market.last_demand[good] = location.market.last_demand.get(good, 0.0) + quantity


def carriage_cost(a: Location, b_id: str) -> float:
    distance = a.neighbours.get(b_id)
    if distance is None:
        return float("inf")
    factor = a.roads.get(b_id, 1.0)
    if a.river:
        factor *= 1.5  # inferred multiplier (DD gives no number); see DEVIATIONS.md
    return distance / factor if factor > 0 else float("inf")


def reachable_within(world: World, origin: Location, c_max: float) -> dict[str, float]:
    """Dijkstra over the location graph; returns {location_id: cumulative carriage
    cost} for every location within `c_max`, origin included at cost 0."""

    dist: dict[str, float] = {origin.id: 0.0}
    heap: list[tuple[float, str]] = [(0.0, origin.id)]
    while heap:
        d, loc_id = heapq.heappop(heap)
        if d > dist.get(loc_id, float("inf")):
            continue
        loc = world.locations[loc_id]
        for neighbour_id in loc.neighbours:
            cost = carriage_cost(loc, neighbour_id)
            nd = d + cost
            if nd <= c_max and nd < dist.get(neighbour_id, float("inf")):
                dist[neighbour_id] = nd
                heapq.heappush(heap, (nd, neighbour_id))
    return dist


def market_size(
    good: Good, location: Location, world: World, route_demand: float = 0.0, army_demand: float = 0.0
) -> float:
    """MM §9: spending on `good`'s tier, summed over locations reachable within
    `c_max`, plus army demand and route demand at capacity (both 0 until Doc 04)."""

    reach = reachable_within(world, location, world.params.prices.c_max)
    total = 0.0
    tier = TIER.get(good)
    for loc_id in reach:
        loc = world.locations[loc_id]
        for record in loc.records:
            if tier is not None:
                total += record.last_spend_by_good.get(good, 0.0)
    return total + route_demand + army_demand


def dol(market_size_value: float, params: Params) -> float:
    """Division of labour, increasing and saturating in market size (MM §9)."""

    scale = params.prices.dol_scale
    return market_size_value / (market_size_value + scale) if scale > 0 else 0.0


def internal_goods_flow(world: World, nation: Nation) -> None:
    """A simple within-nation route (DD §4.7): goods move from the cheaper to the
    dearer of two same-nation neighbouring locations, capacity set by carriage cost
    alone (no merchant stock/Ships yet — that's Doc 04's cross-border routes)."""

    locations = nation.locations(world)
    seen_pairs: set[frozenset[str]] = set()
    for loc in locations:
        for neighbour_id in loc.neighbours:
            neighbour = world.locations.get(neighbour_id)
            if neighbour is None or neighbour.nation != nation.id:
                continue
            pair = frozenset((loc.id, neighbour_id))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            cost = carriage_cost(loc, neighbour_id)
            if cost == float("inf") or cost <= 0:
                continue
            for good in CONSUMABLE_GOODS:
                p_a = loc.market.price.get(good, 1.0)
                p_b = neighbour.market.price.get(good, 1.0)
                gap = abs(p_a - p_b)
                carriage_baskets = cost * world.params.trade.carriage_price_per_unit
                if gap <= carriage_baskets:  # not worth carrying (transport-cost floor)
                    continue
                cheap_side_stock = (
                    loc.market.inventory.get(good, 0.0)
                    if p_a < p_b
                    else neighbour.market.inventory.get(good, 0.0)
                )
                volume = min(cheap_side_stock, gap / max(cost, 1e-6))
                volume = max(0.0, volume)
                if volume <= 0:
                    continue
                # The cheap side loses supply (its price should firm up next update);
                # the dear side gains it (its price should soften) — recorded as
                # demand/supply so `update_market_prices` actually reacts next year,
                # rather than the move being invisible until something else notices.
                if p_a < p_b:
                    loc.market.inventory[good] = loc.market.inventory.get(good, 0.0) - volume
                    neighbour.market.inventory[good] = neighbour.market.inventory.get(good, 0.0) + volume
                    record_demand(loc, good, volume)
                    record_supply(neighbour, good, volume)
                else:
                    neighbour.market.inventory[good] = neighbour.market.inventory.get(good, 0.0) - volume
                    loc.market.inventory[good] = loc.market.inventory.get(good, 0.0) + volume
                    record_demand(neighbour, good, volume)
                    record_supply(loc, good, volume)


def reset_market_flow_accumulators(world: World) -> None:
    """Zero `last_demand`/`last_supply` at the start of the year's price-setting pass
    — the values steps 1/5 accumulate this year become *next* year's lagged basis."""

    for location in world.locations.values():
        for good in ALL_GOODS:
            location.market.last_demand[good] = 0.0
            location.market.last_supply[good] = 0.0


def step_market(world: World) -> None:
    """Year step 4 (goods only). Updates prices from last year's recorded flow, then
    resets the accumulators *before* this year's flow (production's supply, and the
    within-nation route) records into them — so what's recorded now survives to be
    read as *next* year's lagged basis, instead of being wiped straight after."""

    # Compute producible goods per nation (for unobtainable good price logic)
    producible_by_nation: dict[str, set[Good]] = {}
    for nation in world.nations.values():
        producible: set[Good] = set()
        for location in nation.locations(world):
            for producer in location.producers:
                for good in producer.outputs.keys():
                    producible.add(good)
        producible_by_nation[nation.id] = producible

    for location in world.locations.values():
        producible = producible_by_nation.get(location.nation or "", set(ALL_GOODS))
        update_market_prices(location, world.params, producible=producible)

    reset_market_flow_accumulators(world)

    for location in world.locations.values():
        for producer in location.producers:
            if producer.last_Q <= 0:
                continue
            for good, rate in producer.outputs.items():
                record_supply(location, good, producer.last_Q * rate)

    for nation in world.nations.values():
        internal_goods_flow(world, nation)
