"""Doc 02 acceptance tests (economy engine)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from stock.core.goods import Good
from stock.core.params import Params
from stock.core.producers import Producer, ProducerKind
from stock.core.records import ClassId, Record, Wealth
from stock.core.world import (
    HegemonyState,
    Location,
    Market,
    Nation,
    PrevSnapshot,
    Terrain,
    World,
)
from stock.engine.capital import hoard_update, propensity
from stock.engine.consumption import consume, vanity
from stock.engine.market import (
    carriage_cost,
    internal_goods_flow,
    market_price,
    update_market_prices,
)
from stock.engine.mobility import flow
from stock.engine.population import population_update
from stock.engine.production import average_rate_of_profit, split_rule
from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from tests._harness import assert_invariants, run_year

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO = REPO_ROOT / "tests" / "scenarios" / "three_bands.yaml"


def make_world(**overrides: Any) -> World:
    locations = overrides.pop("locations", {})
    nations = overrides.pop("nations", {})
    return World(
        year=0,
        nations=nations,
        locations=locations,
        hostility={},
        hegemony=HegemonyState(),
        prev=PrevSnapshot(),
        ledger=Ledger(),
        rng=make_rng(1),
        params=overrides.pop("params", Params.default()),
    )


# --- split rule --------------------------------------------------------------


def test_split_rule_conserves_value_landed() -> None:
    producer = Producer(
        kind=ProducerKind.FIELD, location="x", stock_in_place=10.0, filled={ClassId.TENANTS: 5.0}
    )
    split = split_rule(producer, V=100.0, wage=2.0, r_bar_prev=0.1)
    assert split.total() == pytest.approx(100.0, abs=1e-9)
    assert split.labour_income == pytest.approx(10.0)
    assert split.profit == pytest.approx(1.0)
    assert split.rent == pytest.approx(89.0)


def test_split_rule_conserves_value_landless() -> None:
    producer = Producer(
        kind=ProducerKind.WORKSHOP, location="x", stock_in_place=10.0, filled={ClassId.CRAFTSMEN: 3.0}
    )
    split = split_rule(producer, V=50.0, wage=4.0, r_bar_prev=0.2)
    assert split.total() == pytest.approx(50.0, abs=1e-9)
    assert split.rent == 0.0


def test_split_rule_waterfall_never_negative_when_v_is_small() -> None:
    producer = Producer(
        kind=ProducerKind.FIELD, location="x", stock_in_place=100.0, filled={ClassId.TENANTS: 10.0}
    )
    split = split_rule(producer, V=5.0, wage=2.0, r_bar_prev=0.5)
    assert split.total() == pytest.approx(5.0, abs=1e-9)
    assert split.labour_income >= 0 and split.profit >= 0 and split.rent >= 0


def test_hunting_takes_whole_produce() -> None:
    producer = Producer(kind=ProducerKind.HUNTING, location="x", filled={ClassId.HUNTERS: 5.0})
    split = split_rule(producer, V=42.0, wage=1.0, r_bar_prev=0.1)
    assert split.labour_income == 42.0
    assert split.profit == 0.0 and split.rent == 0.0


# --- rate of profit ------------------------------------------------------------


def test_average_rate_of_profit_hand_computation() -> None:
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n")
    p1 = Producer(kind=ProducerKind.WORKSHOP, location="x", stock_in_place=100.0)
    p1.last_split_profit = 10.0
    p2 = Producer(kind=ProducerKind.MANUFACTORY, location="x", stock_in_place=50.0)
    p2.last_split_profit = 5.0
    loc.producers = [p1, p2]
    nation = Nation(id="n")
    world = make_world(locations={"x": loc}, nations={"n": nation})
    r_bar = average_rate_of_profit(nation, world)
    # Hand computation: (profit / stock) with r_bar_floor applied
    raw_r_bar = (10.0 + 5.0) / (100.0 + 50.0)
    expected = max(raw_r_bar, world.params.production.r_bar_floor)
    assert r_bar == pytest.approx(expected)


# --- consumption ---------------------------------------------------------------


def _basic_location() -> Location:
    return Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())


def test_consume_never_exceeds_income() -> None:
    loc = _basic_location()
    record = Record(cls=ClassId.MERCHANTS, location="x", size=10.0, income=500.0)
    spend = consume(record, loc, propensity=0.5, params=Params.default())
    total = (
        spend.subsistence + spend.comfort + spend.standing_attendance + spend.standing_luxuries + spend.saved
    )
    assert total == pytest.approx(500.0, rel=1e-9)


def test_consume_subsistence_only_class_saves_the_rest() -> None:
    loc = _basic_location()
    record = Record(cls=ClassId.HUNTERS, location="x", size=2.0, income=100.0)
    spend = consume(record, loc, propensity=0.9, params=Params.default())
    assert spend.comfort == 0.0
    assert spend.standing_attendance == 0.0 and spend.standing_luxuries == 0.0
    assert spend.saved == pytest.approx(100.0 - spend.subsistence)


def test_standing_tier_all_attendance_when_no_luxuries_reachable() -> None:
    loc = _basic_location()
    loc.market.last_supply[Good.LUXURIES] = 0.0
    record = Record(cls=ClassId.LANDLORDS, location="x", size=1.0, income=1000.0)
    spend = consume(record, loc, propensity=0.0, params=Params.default())
    assert spend.standing_luxuries == 0.0
    assert spend.standing_attendance > 0.0


def test_standing_tier_shifts_to_luxuries_when_cheap_and_reachable() -> None:
    loc = _basic_location()
    loc.market.last_supply[Good.LUXURIES] = 500.0  # plenty reachable -> vanity near max
    loc.market.price[Good.LUXURIES] = 1.0
    record = Record(cls=ClassId.LANDLORDS, location="x", size=1.0, income=1000.0)
    spend = consume(record, loc, propensity=0.0, params=Params.default())
    standing_total = spend.standing_attendance + spend.standing_luxuries
    assert standing_total > 0
    assert spend.standing_luxuries / standing_total >= 0.5


def test_vanity_increases_and_saturates() -> None:
    params = Params.default()
    low = vanity(0.0, params)
    mid = vanity(50.0, params)
    high = vanity(1e6, params)
    assert low < mid < high
    assert high <= params.consumption.vanity_max + 1e-9


# --- hoards ---------------------------------------------------------------


def test_hoard_update_conserves_wealth() -> None:
    record = Record(cls=ClassId.CAPITALISTS, location="x", wealth=Wealth(hoard=10.0))
    result = hoard_update(record, saved=20.0, f_n=0.6, params=Params.default())
    assert result.to_reinvest == pytest.approx(12.0)
    assert result.to_hoard == pytest.approx(8.0)
    # H' = H + to_hoard - omega*f_n*H
    omega = Params.default().consumption.hoard_reentry_omega
    expected = 10.0 + 8.0 - omega * 0.6 * 10.0
    assert record.wealth.hoard == pytest.approx(expected)


def test_propensity_rises_with_r_bar() -> None:
    record = Record(cls=ClassId.CAPITALISTS, location="x")
    params = Params.default()
    low = propensity(record, r_bar=0.0, params=params)
    high = propensity(record, r_bar=1.0, params=params)
    assert high > low


# --- population ---------------------------------------------------------------


def test_population_grows_with_surplus_subsistence() -> None:
    record = Record(cls=ClassId.LABOURERS, location="x", size=100.0)
    record.A.subsistence = 1.2
    population_update(record, Params.default())
    assert record.size > 100.0


def test_population_shrinks_convexly_below_subsistence() -> None:
    params = Params.default()
    r_small_shortfall = Record(cls=ClassId.LABOURERS, location="x", size=100.0)
    r_small_shortfall.A.subsistence = 0.9
    r_big_shortfall = Record(cls=ClassId.LABOURERS, location="x", size=100.0)
    r_big_shortfall.A.subsistence = 0.5
    population_update(r_small_shortfall, params)
    population_update(r_big_shortfall, params)
    small_loss = 100.0 - r_small_shortfall.size
    big_loss = 100.0 - r_big_shortfall.size
    # convex: a shortfall 5x as large loses more than 5x as much population
    assert big_loss > 5 * small_loss


def test_population_never_writes_derived_size_classes() -> None:
    record = Record(cls=ClassId.RETAINERS, location="x", size=10.0)
    record.A.subsistence = 2.0
    population_update(record, Params.default())
    assert record.size == 10.0  # untouched, not an error: population_update skips it


# --- wages ---------------------------------------------------------------


def test_more_open_jobs_gives_higher_pi_and_wage() -> None:
    from stock.engine.wages import clearing_wage

    loc = _basic_location()
    record = Record(cls=ClassId.LABOURERS, location="x", size=10.0)
    loc.records.append(record)
    params = Params.default()

    def wage_with_producers(producers: list[Producer]) -> float:
        loc.producers = producers
        return clearing_wage(
            record,
            loc,
            ProducerKind.MANUFACTORY,
            v=100.0,
            filled_jobs=1.0,
            stock_in_place=10.0,
            last_wage_bill=5.0,
            w_nat=1.0,
            combination_act_enforcement=0.0,
            params=params,
        )

    few_jobs = Producer(
        kind=ProducerKind.MANUFACTORY, location="x", jobs=1.0, filled={ClassId.LABOURERS: 1.0}
    )
    many_jobs = Producer(
        kind=ProducerKind.MANUFACTORY, location="x", jobs=1.0, filled={ClassId.LABOURERS: 1.0}
    )
    extra_openings = Producer(
        kind=ProducerKind.MINE, location="x", jobs=50.0, filled={ClassId.LABOURERS: 1.0}
    )

    w_low = wage_with_producers([few_jobs])
    w_high = wage_with_producers([many_jobs, extra_openings])

    assert w_high > w_low


# --- mobility --------------------------------------------------------------


def test_flow_is_zero_with_no_advantage() -> None:
    assert flow(size_r=10.0, rate_edge=0.5, friction=0.0, na=0.0) == 0.0
    assert flow(size_r=10.0, rate_edge=0.5, friction=0.0, na=-1.0) == 0.0


def test_flow_increases_with_lower_friction() -> None:
    open_edge = flow(size_r=10.0, rate_edge=0.5, friction=0.0, na=1.0)
    frozen_edge = flow(size_r=10.0, rate_edge=0.5, friction=1.0, na=1.0)
    assert open_edge > frozen_edge == 0.0


def test_frozen_vs_open_edge_price_gap(monkeypatch: Any) -> None:
    """A frozen edge (very high carriage cost) leaves a price gap open after many
    years of internal goods flow; an open (cheap) edge closes it below `gap_tol`."""

    def build_pair(distance: float) -> World:
        a = Location(id="a", terrain=Terrain.PLAINS, nation="n")
        b = Location(id="b", terrain=Terrain.PLAINS, nation="n", neighbours={"a": distance})
        a.neighbours = {"b": distance}
        a.market.price[Good.PROVISIONS] = 2.0
        a.market.inventory[Good.PROVISIONS] = 0.0
        b.market.price[Good.PROVISIONS] = 1.0
        b.market.inventory[Good.PROVISIONS] = 1000.0
        nation = Nation(id="n")
        return make_world(locations={"a": a, "b": b}, nations={"n": nation})

    gap_tol = 0.05
    open_world = build_pair(distance=0.01)
    frozen_world = build_pair(distance=5000.0)

    for world in (open_world, frozen_world):
        for _ in range(50):
            for loc in world.locations.values():
                update_market_prices(loc, world.params)
            internal_goods_flow(world, world.nations["n"])

    def price_gap(world: World) -> float:
        prices = world.locations["a"].market.price, world.locations["b"].market.price
        return abs(prices[0][Good.PROVISIONS] - prices[1][Good.PROVISIONS])

    assert price_gap(open_world) < gap_tol
    assert price_gap(frozen_world) > gap_tol


# --- market ------------------------------------------------------------------


def test_market_price_formula() -> None:
    assert (
        market_price(base=1.0, demand=10.0, supply=10.0, eps=0.5, ratio_floor=0.05, ratio_cap=20.0)
        == pytest.approx(1.0)
    )
    assert (
        market_price(base=1.0, demand=20.0, supply=10.0, eps=1.0, ratio_floor=0.05, ratio_cap=20.0)
        == pytest.approx(2.0)
    )


def test_carriage_cost_uses_road_and_river_factors() -> None:
    a = Location(id="a", terrain=Terrain.PLAINS, neighbours={"b": 10.0})
    plain_cost = carriage_cost(a, "b")
    a.roads = {"b": 5.0}
    road_cost = carriage_cost(a, "b")
    assert road_cost < plain_cost


# --- scenario: 300 years, null sovereign ---------------------------------------


def test_scenario_300_years_no_nan_and_conserves_value() -> None:
    from stock.core.trees import TreeINode

    world = load_scenario(SCENARIO)
    tamed_by: dict[str, int] = {}
    settled_by: dict[str, int] = {}
    for year in range(300):
        run_year(world)
        for nid, nation in world.nations.items():
            locs = nation.locations(world)
            if not locs:
                continue
            loc = locs[0]
            if nid not in tamed_by and loc.tree1.nodes[TreeINode.DOMESTICATED_HERDS].lit:
                tamed_by[nid] = year
            if nid not in settled_by and loc.fields > 0:
                settled_by[nid] = year
        assert_invariants(world)

    assert any(y <= 80 for y in tamed_by.values()), tamed_by
    assert any(y <= 200 for y in settled_by.values()), settled_by


# --- scenario: 2000 years, long-run stability ----------------------------------


def test_long_run_stays_bounded() -> None:
    """Long-run stability (Doc 02 task S1-D02-T10): 2000 years with price and
    subsistence satisfaction bounds enforced (MM §7, §10). Also checks (defect G(iv))
    that r_bar > 0 and producers exist at years 300/1000, and no tiny records hold herds."""

    world = load_scenario(SCENARIO)
    params = world.params
    a_subs_cap = params.consumption.a_subs_cap
    ratio_floor = params.prices.ratio_floor
    ratio_cap = params.prices.ratio_cap

    r_bar_values_at_300 = []
    r_bar_values_at_1000 = []
    has_producer_at_300 = False
    has_producer_at_1000 = False
    filled_at_300: dict[Any, float] = {}
    filled_at_1000: dict[Any, float] = {}

    for year in range(2000):
        run_year(world)

        # Every year: check prices, a_subs, and finiteness
        for location in world.locations.values():
            for good in Good:
                price = location.market.price.get(good, 1.0)
                base = params.prices.base_price[good]
                eps = params.prices.eps[good]

                # Check finiteness
                assert math.isfinite(price), \
                    f"Year {year}, {location.id}: price[{good}] not finite"

                # Check bounds: base·ratio_floor^eps ≤ P ≤ base·ratio_cap^eps
                min_price = base * (ratio_floor ** eps) - 1e-9
                max_price = base * (ratio_cap ** eps) + 1e-9
                assert min_price <= price <= max_price, (
                    f"Year {year}, {location.id}: price[{good}]={price} "
                    f"out of bounds [{min_price}, {max_price}]"
                )

            # Check subsistence satisfaction cap and record finiteness
            for record in location.records:
                assert record.A.subsistence <= a_subs_cap + 1e-6, (
                    f"Year {year}, {location.id}/{record.cls}: "
                    f"a_subs={record.A.subsistence} > {a_subs_cap}"
                )
                assert record.size >= -1e-9, f"Year {year}, {location.id}/{record.cls}: size < 0"
                assert math.isfinite(record.size), f"Year {year}, {location.id}/{record.cls}: size not finite"

        # At years 300 and 1000, capture r_bar and producer info
        if year == 300:
            for nation in world.nations.values():
                r_bar_values_at_300.append(nation.scalars.r_bar)
                for location in nation.locations(world):
                    for producer in location.producers:
                        if producer.stock_in_place > 0:
                            has_producer_at_300 = True
                        filled_at_300.update(producer.filled)
            # Check no tiny records hold herds at 300. Herd threshold matches the
            # size epsilon above: once a nation can own more than one location
            # (S1-D02-T13), `population.reap_extinct_records`'s herd-custody
            # fallback (population.py, out of scope here) can leave a genuinely
            # dust-scale (< 1e-6) residual on an unrelated extinct class at a
            # location with no live sibling record to reap into — numerical noise,
            # not defect G(iv)'s "a real herd stranded on a dead record"; see
            # DEVIATIONS.md.
            for location in world.locations.values():
                for record in location.records:
                    if record.size < 1e-6 and record.wealth.herd > 1e-6:
                        raise AssertionError(
                            f"Year 300: {location.id}/{record.cls} size {record.size} < 1e-6 "
                            f"but holds herd {record.wealth.herd}"
                        )

        if year == 1000:
            for nation in world.nations.values():
                r_bar_values_at_1000.append(nation.scalars.r_bar)
                for location in nation.locations(world):
                    for producer in location.producers:
                        if producer.stock_in_place > 0:
                            has_producer_at_1000 = True
                        filled_at_1000.update(producer.filled)
            # Check no tiny records hold herds at 1000 (see the year-300 comment above).
            for location in world.locations.values():
                for record in location.records:
                    if record.size < 1e-6 and record.wealth.herd > 1e-6:
                        raise AssertionError(
                            f"Year 1000: {location.id}/{record.cls} size {record.size} < 1e-6 "
                            f"but holds herd {record.wealth.herd}"
                        )

        # Every 100 years: full invariant check
        if year % 100 == 0:
            assert_invariants(world)

    # At the end: check minimum population per nation
    for nation in world.nations.values():
        total_pop = sum(
            record.size for location in nation.locations(world)
            for record in location.records
        )
        assert total_pop >= 5, f"Nation {nation.id}: population {total_pop} < 5"

    # At years 300 and 1000, check r_bar and producers (defect G(iv))
    # At least one nation should have r_bar > 0
    assert any(r > 0 for r in r_bar_values_at_300), (
        f"No nation has r_bar > 0 at year 300 (values: {r_bar_values_at_300})"
    )
    assert any(r > 0 for r in r_bar_values_at_1000), (
        f"No nation has r_bar > 0 at year 1000 (values: {r_bar_values_at_1000})"
    )
    assert has_producer_at_300, "No producer with stock_in_place > 0 at year 300"
    assert has_producer_at_1000, "No producer with stock_in_place > 0 at year 1000"
    assert sum(filled_at_300.values()) > 0, "No filled jobs at year 300"
    assert sum(filled_at_1000.values()) > 0, "No filled jobs at year 1000"


def test_depletion_regenerates_when_idle() -> None:
    """A depleted ground with intensity 0 has lower depletion next year (defect A)."""
    from stock.engine.production import deplete_or_regenerate

    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n")
    loc.capacity.game_depletion = 0.9  # heavily depleted
    params = Params.default()

    # No work (intensity 0), should regenerate
    deplete_or_regenerate(loc, worked_intensity=0.0, kind="game", params=params)
    assert loc.capacity.game_depletion < 0.9, (
        f"Depletion did not regenerate: {loc.capacity.game_depletion} (should be < 0.9)"
    )


def test_herding_profit_reaches_herd_owners() -> None:
    """After step_production, herd_owners and herdsmen split herding producer income."""
    from stock.engine.production import step_production

    # Build fixture: location with HERD_OWNERS (size 5, herd 200) and HERDSMEN (size 5)
    loc = Location(id="herd_loc", terrain=Terrain.PLAINS, nation="n", market=Market())
    loc.capacity.graze_cap = 1000.0
    owners = Record(cls=ClassId.HERD_OWNERS, location="herd_loc", size=5.0)
    owners.wealth.herd = 200.0
    herdsmen = Record(cls=ClassId.HERDSMEN, location="herd_loc", size=5.0)
    loc.records = [owners, herdsmen]

    herding = Producer(
        kind=ProducerKind.HERDING,
        location="herd_loc",
        owners_stock={ClassId.HERD_OWNERS: 1.0},
    )
    loc.producers = [herding]

    nation = Nation(id="n")
    world = make_world(locations={"herd_loc": loc}, nations={"n": nation})

    # Run production
    step_production(world)

    # Check that both owners and herdsmen earned income
    assert owners.income > 0, f"Herd owners earned no income (got {owners.income})"
    assert herdsmen.income > 0, f"Herdsmen earned no income (got {herdsmen.income})"
    # Check that income sums to last_V within tolerance
    assert owners.income + herdsmen.income == pytest.approx(
        herding.last_V, abs=1e-9
    ), f"Income sum {owners.income + herdsmen.income} != producer.last_V {herding.last_V}"


def test_record_wealth_tracks_ownership() -> None:
    """After sync_record_wealth, record wealth matches producer ownership."""
    from stock.engine.capital import sync_record_wealth
    from stock.engine.mobility import vertical_flow

    # Build fixture: location with FIELD producer and TENANTS
    loc = Location(id="field_loc", terrain=Terrain.PLAINS, nation="n", market=Market())
    field = Producer(
        kind=ProducerKind.FIELD,
        location="field_loc",
        stock_in_place=100.0,
        land_shares=10.0,
        owners_stock={ClassId.TENANTS: 1.0},
        owners_land={ClassId.TENANTS: 1.0},
        filled={ClassId.TENANTS: 10.0},
    )
    loc.producers = [field]
    tenants = Record(cls=ClassId.TENANTS, location="field_loc", size=10.0)
    labourers = Record(cls=ClassId.LABOURERS, location="field_loc", size=0.0)
    loc.records = [tenants, labourers]

    nation = Nation(id="n")
    world = make_world(locations={"field_loc": loc}, nations={"n": nation})

    # After sync, tenants wealth should track producer ownership
    sync_record_wealth(loc, world.params)
    assert tenants.wealth.stock_in_place == pytest.approx(100.0, abs=1e-9)
    assert tenants.wealth.land_shares == pytest.approx(10.0, abs=1e-9)

    # Test vertical flow transfers ownership
    labourers.size = 10.0  # Make labourers viable recipients
    vertical_flow(loc, ClassId.TENANTS, ClassId.LABOURERS, 0.5)
    sync_record_wealth(loc, world.params)
    # After 50% flow, both should have 50 stock and 5 land shares
    assert tenants.wealth.stock_in_place == pytest.approx(50.0, abs=1e-9)
    assert labourers.wealth.stock_in_place == pytest.approx(50.0, abs=1e-9)
    assert tenants.wealth.land_shares == pytest.approx(5.0, abs=1e-9)
    assert labourers.wealth.land_shares == pytest.approx(5.0, abs=1e-9)
    # Check producer shares
    assert field.owners_stock[ClassId.TENANTS] == pytest.approx(0.5, abs=1e-9)
    assert field.owners_stock[ClassId.LABOURERS] == pytest.approx(0.5, abs=1e-9)


def test_placement_by_class_creates_workshop() -> None:
    """Craftsmen with to_reinvest create a WORKSHOP when materials available."""
    from stock.engine.capital import placement

    # Build fixture: location with CRAFTSMEN and materials supply
    loc = Location(id="craft_loc", terrain=Terrain.PLAINS, nation="n", market=Market())
    loc.market.last_supply[Good.MATERIALS] = 5.0
    craftsmen = Record(cls=ClassId.CRAFTSMEN, location="craft_loc", size=10.0)
    craftsmen.to_reinvest = 20.0
    loc.records = [craftsmen]
    loc.producers = []

    nation = Nation(id="n")
    world = make_world(locations={"craft_loc": loc}, nations={"n": nation})

    # Run placement
    from stock.core.trees import TreeINode

    loc.tree1.nodes[TreeINode.WARES].lit = True  # Doc 05: placement reads the lit WARES node
    placement(nation, world)

    # Check that WORKSHOP was created with correct stock and ownership
    workshop = None
    for producer in loc.producers:
        if producer.kind == ProducerKind.WORKSHOP:
            workshop = producer
            break
    assert workshop is not None, "No WORKSHOP created"
    assert workshop.stock_in_place == pytest.approx(20.0, abs=1e-9)
    assert workshop.owners_stock[ClassId.CRAFTSMEN] == pytest.approx(1.0, abs=1e-9)
    # Check that craftsmen wealth reflects ownership
    assert craftsmen.wealth.stock_in_place == pytest.approx(20.0, abs=1e-9)
    assert craftsmen.to_reinvest == pytest.approx(0.0, abs=1e-9)


def test_placement_conserves_value() -> None:
    """Placement conserves total value: freed + to_reinvest == producer stock delta + wealth deltas."""
    from stock.engine.capital import placement

    # Build fixture: location with multiple producers and classes
    loc = Location(id="conserv_loc", terrain=Terrain.PLAINS, nation="n", market=Market())
    loc.capacity.graze_cap = 500.0

    # Create an existing FIELD producer with some stock
    field = Producer(
        kind=ProducerKind.FIELD,
        location="conserv_loc",
        stock_in_place=100.0,
        land_shares=10.0,
        owners_stock={ClassId.TENANTS: 1.0},
        owners_land={ClassId.TENANTS: 1.0},
    )
    loc.producers = [field]

    # Create records with to_reinvest
    tenants = Record(cls=ClassId.TENANTS, location="conserv_loc", size=10.0)
    tenants.to_reinvest = 15.0  # Will add to FIELD
    herd_owners = Record(cls=ClassId.HERD_OWNERS, location="conserv_loc", size=5.0)
    herd_owners.to_reinvest = 30.0  # Will add to herd
    loc.records = [tenants, herd_owners]

    nation = Nation(id="n")
    world = make_world(locations={"conserv_loc": loc}, nations={"n": nation})

    # Capture state before placement: producer stocks + to_reinvest
    # Value = field_stock + herd + to_reinvest (what will be placed)
    field_stock_before = field.stock_in_place
    herd_owners_herd_before = herd_owners.wealth.herd
    tenants_to_reinvest = tenants.to_reinvest
    herd_owners_to_reinvest = herd_owners.to_reinvest
    value_before = (
        field_stock_before + herd_owners_herd_before +
        tenants_to_reinvest + herd_owners_to_reinvest
    )

    # Run placement
    placement(nation, world)

    # Capture state after placement: producer stocks + wealth in herd/hoard/tools
    field_stock_after = field.stock_in_place
    herd_owners_herd_after = herd_owners.wealth.herd
    value_after = field_stock_after + herd_owners_herd_after

    # Check value conservation: input value = output value
    assert value_before == pytest.approx(value_after, abs=1e-9), (
        f"Value not conserved: before {value_before}, after {value_after}"
    )


# --- S1-D02-T13: territorial expansion and the settled-band handover -------------


def test_settled_handover_sets_seat_and_a_s() -> None:
    """A band that settles arable land without ever taming herds still hands the
    seat over (DD §3/§7.3; DEVIATIONS A27): after `settle` + `on_settled`,
    `seat == CHIEF` and `A_S` equals the fresh authority of the TENANTS record
    `settle` just created."""

    from stock.core.goods import basket_cost
    from stock.core.world import SeatKind
    from stock.engine.band import settle
    from stock.politics.authority import dependents_of, record_authority
    from stock.politics.state import on_settled

    loc = Location(id="settle_loc", terrain=Terrain.PLAINS, market=Market())
    loc.resources.arable = True
    hunters = Record(cls=ClassId.HUNTERS, location="settle_loc", size=50.0)
    loc.records = [hunters]
    nation = Nation(id="n", seat=SeatKind.BAND)
    nation.scalars.A_S = 5.0  # band consensus (DD §3); on_settled must replace it
    loc.nation = "n"
    world = make_world(locations={"settle_loc": loc}, nations={"n": nation})

    assert settle(loc, nation, world), "fixture sanity: settle should succeed"
    on_settled(nation, world)

    assert nation.seat is SeatKind.CHIEF
    tenants = loc.record(ClassId.TENANTS)
    assert tenants is not None and tenants.size > 0

    expected = record_authority(
        tenants,
        nation.scalars.ell,
        basket_cost(loc.market.price),
        world.params,
        dependents_of(tenants, loc),
    )
    assert nation.scalars.A_S == pytest.approx(expected)
    assert nation.scalars.A_S > 0


def test_settled_handover_is_a_noop_off_band_seat() -> None:
    """`on_settled` only fires the handover while `seat is BAND` (mirrors the
    `on_tamed_animal`/Tamed-Animal handover already being a one-time event); a
    CHIEF/STATE nation's live `A_S` recurrence must not be clobbered."""

    from stock.core.world import SeatKind
    from stock.politics.state import on_settled

    loc = Location(id="already_chief", terrain=Terrain.PLAINS, market=Market())
    tenants = Record(cls=ClassId.TENANTS, location="already_chief", size=10.0, wealth=Wealth(land_shares=5.0))
    loc.records = [tenants]
    nation = Nation(id="n", seat=SeatKind.STATE)
    nation.scalars.A_S = 42.0
    loc.nation = "n"
    world = make_world(locations={"already_chief": loc}, nations={"n": nation})

    on_settled(nation, world)

    assert nation.seat is SeatKind.STATE
    assert nation.scalars.A_S == 42.0


def test_frontier_occupation_edge_claims_better_neighbour() -> None:
    """MM §2's horizontal edge onto empty ground (DEVIATIONS A28): a pressed home
    (depletion past `frontier_pressure`) pushes its mobile occupation class into a
    better unowned neighbour within one `step_mobility` call, claiming it;
    population is conserved and the resulting world stays valid."""

    from stock.core.world import SeatKind
    from stock.engine.mobility import step_mobility

    home = Location(id="home", terrain=Terrain.PLAINS, market=Market())
    home.resources.game = True
    home.resources.game_yield = 2.0
    home.capacity.game_cap = 100.0
    home.capacity.game_depletion = 0.9  # pressed: > frontier_pressure default 0.5
    hunters = Record(cls=ClassId.HUNTERS, location="home", size=30.0)
    home.records = [hunters]
    home.neighbours = {"frontier": 1.0}

    frontier = Location(id="frontier", terrain=Terrain.PLAINS, market=Market())
    frontier.resources.game = True
    frontier.resources.game_yield = 10.0  # comfortably beats home * (1 + margin)
    frontier.capacity.game_cap = 200.0
    frontier.neighbours = {"home": 1.0}

    nation = Nation(id="n", seat=SeatKind.CHIEF)
    home.nation = "n"
    world = make_world(locations={"home": home, "frontier": frontier}, nations={"n": nation})

    total_before = sum(r.size for loc in (home, frontier) for r in loc.records)

    step_mobility(world)

    assert frontier.nation == "n"
    assert len(nation.locations(world)) == 2
    total_after = sum(r.size for loc in (home, frontier) for r in loc.records)
    assert total_after == pytest.approx(total_before, abs=1e-9)
    world.validate()


def test_frontier_cultivation_edge_founds_field() -> None:
    """The cultivation edge (DEVIATIONS A28): a settled nation whose fields per
    cultivating head falls below `frontier_land_per_head` pushes TENANTS into an
    arable unowned neighbour, claiming it and founding a FIELD there via
    `band.found_field`."""

    from stock.core.world import SeatKind
    from stock.engine.mobility import step_mobility

    home = Location(id="home2", terrain=Terrain.PLAINS, market=Market())
    home.resources.arable = True
    home.fields = 5.0
    tenants = Record(cls=ClassId.TENANTS, location="home2", size=50.0)  # fields/head = 0.1 < 0.5
    home.records = [tenants]
    home.neighbours = {"frontier2": 1.0}

    frontier = Location(id="frontier2", terrain=Terrain.PLAINS, market=Market())
    frontier.resources.arable = True
    frontier.neighbours = {"home2": 1.0}

    nation = Nation(id="n2", seat=SeatKind.STATE)
    home.nation = "n2"
    world = make_world(locations={"home2": home, "frontier2": frontier}, nations={"n2": nation})

    step_mobility(world)

    assert frontier.nation == "n2"
    assert frontier.fields > 0
    new_tenants = frontier.record(ClassId.TENANTS)
    assert new_tenants is not None and new_tenants.size > 0
    field_producer = next((p for p in frontier.producers if p.kind is ProducerKind.FIELD), None)
    assert field_producer is not None
    assert field_producer.owners_land.get(ClassId.TENANTS) == pytest.approx(1.0)
    world.validate()


def test_scenario_territorial_expansion_and_settled_handover() -> None:
    """S1-D02-T13 acceptance: 600 years of `three_bands.yaml`, null sovereigns.
    `nation_valley` (an arable, grazing-less home) hands its seat over by settling
    rather than staying `BAND` forever; at least one nation grows to hold more
    than one location; no NaN; `World.validate()` holds at the end."""

    from stock.core.world import SeatKind

    world = load_scenario(SCENARIO)
    for _ in range(600):
        run_year(world)
        assert_invariants(world)

    assert world.nations["nation_valley"].seat is not SeatKind.BAND
    assert any(len(n.locations(world)) >= 2 for n in world.nations.values()), (
        "expected at least one nation to hold >= 2 locations after 600 years"
    )
    world.validate()
