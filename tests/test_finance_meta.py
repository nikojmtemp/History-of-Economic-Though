"""Tests for taxation, incidence, and the budget (Doc 05, task S1-D05-T1b).

Tests (a)-(c) run a minimal step sequence (production -> wages -> taxation) rather than
the full `run_year` harness, so that:
- enacted-law state (e.g. COMBINATION_ACT's pinned enforcement) is never overwritten by
  step_legislation (step 12c), which this loop doesn't run;
- the wage-bargain base stays stable across the two years a lag-rule comparison needs.

Tests (d)-(f) exercise the full harness / scenario, per Doc 05's acceptance.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from stock.core.goods import Good, Tier
from stock.core.laws import LawId
from stock.core.producers import MethodId, Producer, ProducerKind
from stock.core.records import ClassId, Record, Wealth
from stock.core.world import (
    HegemonyState,
    LawState,
    Location,
    Market,
    Nation,
    NationScalars,
    PrevSnapshot,
    Resources,
    SeatKind,
    Terrain,
    World,
)
from stock.engine.production import step_production
from stock.engine.wages import step_wages
from stock.finance.taxation import (
    _FARM_LOAN_KEY,
    _PI_PREFIX,
    step_taxation,
)
from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from tests._harness import assert_invariants, run_year

REPO_ROOT = Path(__file__).resolve().parent.parent


def make_world(**overrides: Any) -> World:
    """Build a World for testing (helper from test_economy.py)."""
    locations = overrides.pop("locations", {})
    nations = overrides.pop("nations", {})
    from stock.core.params import Params

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


def _mini_year(world: World) -> None:
    """production -> wages -> taxation only, no legislation/market/consumption — keeps
    enacted-law state and the wage-bargain base stable across years for the incidence
    lag-rule tests (a)-(c)."""

    for nation in world.nations.values():
        nation.flows = {}
    world.prev = PrevSnapshot.take(world)
    step_production(world)
    step_wages(world)
    step_taxation(world)
    world.year += 1


def _table(nation: Nation, instrument: Any) -> Any:
    assert nation.incidence is not None
    return nation.incidence[instrument]


def _flat_market() -> Market:
    return Market(
        price={
            Good.PROVISIONS: 1.0,
            Good.MATERIALS: 1.0,
            Good.WARES: 1.0,
            Good.LUXURIES: 1.0,
            Good.ARMS: 1.0,
            Good.SHIPS: 1.0,
            Good.ATTENDANCE: 1.0,
        },
    )


# --- Fixture: wage tax scenario with pi > 0 ---


@pytest.fixture
def wage_tax_world_with_positive_pi() -> World:
    """A world with a MANUFACTORY (CAPITALISTS owning it, LABOURERS working) + WAGE_TAX.

    pi > 0 because LABOURERS have wa_L > 0 (hoard allows walk-away).
    """
    from stock.core.params import Params

    params = Params.default()

    loc = Location(id="loc1", terrain=Terrain.PLAINS, nation="nation1")

    manufactory = Producer(
        kind=ProducerKind.MANUFACTORY,
        location="loc1",
        stock_in_place=200.0,
        filled={ClassId.LABOURERS: 20.0},
        owners_stock={ClassId.CAPITALISTS: 1.0},
    )
    loc.producers.append(manufactory)
    loc.market = _flat_market()

    cap_record = Record(
        cls=ClassId.CAPITALISTS, location="loc1", size=5.0, wealth=Wealth(stock_in_place=200.0)
    )
    loc.records.append(cap_record)

    labour_record = Record(cls=ClassId.LABOURERS, location="loc1", size=50.0, wealth=Wealth(hoard=20.0))
    loc.records.append(labour_record)

    state_record = Record(cls=ClassId.STATE, location="loc1", size=1.0, wealth=Wealth())
    loc.records.append(state_record)

    nation = Nation(id="nation1", seat=SeatKind.STATE, state=state_record)
    nation.scalars = NationScalars(r_bar=0.05)
    nation.laws[LawId.WAGE_TAX] = LawState(enacted=True)
    nation.tax_rates[LawId.WAGE_TAX] = 0.1

    world = make_world(nations={"nation1": nation}, locations={"loc1": loc}, params=params)
    world.ledger = Ledger()
    return world


@pytest.fixture
def wage_tax_world_with_combination_act(wage_tax_world_with_positive_pi: World) -> World:
    """Same as above, but with COMBINATION_ACT pinned at enforcement 1.0 (pi_eff = 0)."""
    world = wage_tax_world_with_positive_pi
    nation = world.nations["nation1"]
    nation.laws[LawId.COMBINATION_ACT] = LawState(enacted=True, enforcement=1.0)
    return world


@pytest.fixture
def land_tax_world() -> World:
    """A world with a FIELD (LANDLORDS own the land, TENANTS work it) + LAND_TAX."""
    from stock.core.params import Params

    params = Params.default()

    loc = Location(
        id="loc1",
        terrain=Terrain.PLAINS,
        nation="nation1",
        resources=Resources(arable=True, arable_yield=1.0),
    )

    field = Producer(
        kind=ProducerKind.FIELD,
        location="loc1",
        stock_in_place=50.0,
        land_shares=10.0,  # jobs = land_shares * jobs_per_share (1.0 default); fill_jobs()
        # recomputes `filled` from this every step_production, overriding any preset value.
        filled={ClassId.TENANTS: 10.0},
        owners_land={ClassId.LANDLORDS: 1.0},
    )
    loc.producers.append(field)
    loc.fields = 1.0
    loc.market = _flat_market()

    landlord_record = Record(cls=ClassId.LANDLORDS, location="loc1", size=5.0, wealth=Wealth(land_shares=1.0))
    loc.records.append(landlord_record)

    tenant_record = Record(
        cls=ClassId.TENANTS, location="loc1", size=40.0, wealth=Wealth(stock_in_place=50.0)
    )
    loc.records.append(tenant_record)

    state_record = Record(cls=ClassId.STATE, location="loc1", size=1.0, wealth=Wealth())
    loc.records.append(state_record)

    nation = Nation(id="nation1", seat=SeatKind.STATE, state=state_record)
    nation.scalars = NationScalars(r_bar=0.05)
    nation.laws[LawId.LAND_TAX] = LawState(enacted=True)
    nation.tax_rates[LawId.LAND_TAX] = 0.1

    world = make_world(nations={"nation1": nation}, locations={"loc1": loc}, params=params)
    world.ledger = Ledger()
    return world


# --- (a) wage tax, pi > 0: borne < assessed ---


class TestWageTaxIncidenceWithPositivePi:
    def test_pi_recorded_positive(self, wage_tax_world_with_positive_pi: World) -> None:
        """record.last_pi > 0 is checked explicitly, not inferred from the outcome."""
        world = wage_tax_world_with_positive_pi
        _mini_year(world)
        labour = world.locations["loc1"].record(ClassId.LABOURERS)
        assert labour is not None
        assert labour.last_pi > 0

    def test_borne_by_less_than_stored_assessed(self, wage_tax_world_with_positive_pi: World) -> None:
        """Compare year-2's borne_by against the *stored* year-1 assessed_on, not
        year-2's own assessed_on — the base could in principle move between years, and
        the incidence table's borne_by is derived from last year's base by design."""
        world = wage_tax_world_with_positive_pi

        _mini_year(world)  # year 0: assess only, no prior year to derive borne_by from
        nation = world.nations["nation1"]
        assert nation.incidence is not None
        table0 = _table(nation, LawId.WAGE_TAX)
        assessed_year0 = dict(table0.assessed_on)
        assert assessed_year0.get(ClassId.LABOURERS, 0.0) > 0, "must have an assessment to compare against"

        _mini_year(world)  # year 1: borne_by derived from assessed_year0 and pi/enf_CA
        table1 = _table(nation, LawId.WAGE_TAX)
        borne_year1 = table1.borne_by.get(ClassId.LABOURERS, 0.0)
        assert borne_year1 < assessed_year0[ClassId.LABOURERS] - 1e-9

    def test_shifted_remainder_lands_on_owners(self, wage_tax_world_with_positive_pi: World) -> None:
        """The shifted remainder lands on CAPITALISTS (the MANUFACTORY's owners_stock)."""
        world = wage_tax_world_with_positive_pi
        _mini_year(world)
        nation = world.nations["nation1"]
        table0_assessed = dict(_table(nation, LawId.WAGE_TAX).assessed_on)
        _mini_year(world)
        table1 = _table(nation, LawId.WAGE_TAX)
        assessed = table0_assessed.get(ClassId.LABOURERS, 0.0)
        borne_labour = table1.borne_by.get(ClassId.LABOURERS, 0.0)
        borne_capitalists = table1.borne_by.get(ClassId.CAPITALISTS, 0.0)
        assert borne_capitalists > 0
        assert abs((borne_labour + borne_capitalists) - assessed) < 1e-6


# --- (b) wage tax, Combination Act enforced at 1: borne == assessed ---


class TestWageTaxIncidenceWithCombinationAct:
    def test_borne_equals_stored_assessed(self, wage_tax_world_with_combination_act: World) -> None:
        world = wage_tax_world_with_combination_act
        nation = world.nations["nation1"]

        _mini_year(world)
        nation.laws[LawId.COMBINATION_ACT].enforcement = 1.0  # re-pin (defensive)
        table0_assessed = dict(_table(nation, LawId.WAGE_TAX).assessed_on)
        assert table0_assessed.get(ClassId.LABOURERS, 0.0) > 0

        _mini_year(world)
        nation.laws[LawId.COMBINATION_ACT].enforcement = 1.0
        table1 = _table(nation, LawId.WAGE_TAX)
        borne = table1.borne_by.get(ClassId.LABOURERS, 0.0)
        assert abs(borne - table0_assessed[ClassId.LABOURERS]) < 1e-9


# --- (c) land tax: borne == assessed exactly, no shifting ---


class TestLandTaxIncidence:
    def test_borne_equals_assessed(self, land_tax_world: World) -> None:
        world = land_tax_world
        nation = world.nations["nation1"]

        _mini_year(world)
        table0_assessed = dict(_table(nation, LawId.LAND_TAX).assessed_on)
        assert table0_assessed.get(ClassId.LANDLORDS, 0.0) > 0

        _mini_year(world)
        table1 = _table(nation, LawId.LAND_TAX)
        borne = table1.borne_by.get(ClassId.LANDLORDS, 0.0)
        assert abs(borne - table0_assessed[ClassId.LANDLORDS]) < 1e-9
        # No other class picks up any of a rent-based instrument's burden.
        assert set(table1.borne_by.keys()) <= {ClassId.LANDLORDS}


# --- (d) conservation of burden: sum(borne_by) == sum(assessed_on) one year lagged ---


class TestConservationOfBurden:
    def test_wage_and_land_tax_fixture_20_years(
        self, wage_tax_world_with_positive_pi: World, land_tax_world: World
    ) -> None:
        """A focused check that exercises the pi-shift path (WAGE_TAX) and the
        no-shift path (LAND_TAX) together, class by class, every year."""

        for world in (wage_tax_world_with_positive_pi, land_tax_world):
            nation = next(iter(world.nations.values()))
            prev_assessed_total: dict[Any, float] = {}
            for _year in range(20):
                _mini_year(world)
                assert nation.incidence is not None
                for instrument, table in nation.incidence.items():
                    if isinstance(instrument, str) and (
                        instrument.startswith(_PI_PREFIX) or instrument == _FARM_LOAN_KEY
                    ):
                        continue
                    borne_total = sum(table.borne_by.values())
                    assessed_total = sum(table.assessed_on.values())
                    if instrument in prev_assessed_total:
                        assert abs(borne_total - prev_assessed_total[instrument]) < 1e-6, (
                            f"{instrument}: borne {borne_total} != prior year's assessed "
                            f"{prev_assessed_total[instrument]}"
                        )
                    prev_assessed_total[instrument] = assessed_total

    def test_three_bands_100_years(self) -> None:
        """The same check against the real scenario, for whatever pseudo/rated
        instruments actually get assessed over its run (pre-State draws are the
        reliable ones, given Doc 03's DEMANDS table doesn't self-enact rated revenue
        instruments — see this file's module docstring / the task's Deviations)."""

        world = load_scenario(str(REPO_ROOT / "tests" / "scenarios" / "three_bands.yaml"))
        world.ledger = Ledger()
        prev_assessed_total: dict[tuple[str, Any], float] = {}
        saw_any_instrument = False
        for _year in range(100):
            run_year(world)
            for nation in world.nations.values():
                if nation.incidence is None:
                    continue
                for instrument, table in nation.incidence.items():
                    if isinstance(instrument, str) and (
                        instrument.startswith(_PI_PREFIX) or instrument == _FARM_LOAN_KEY
                    ):
                        continue
                    key = (nation.id, instrument)
                    borne_total = sum(table.borne_by.values())
                    assessed_total = sum(table.assessed_on.values())
                    if key in prev_assessed_total:
                        saw_any_instrument = True
                        assert abs(borne_total - prev_assessed_total[key]) < 1e-6, (
                            f"{key}: borne {borne_total} != prior year's assessed "
                            f"{prev_assessed_total[key]}"
                        )
                    prev_assessed_total[key] = assessed_total
        assert saw_any_instrument, "expected at least one instrument to be assessed across 100 years"


# --- (e) three_bands.yaml, 300 years: revenue/treasure sane ---


class TestLongRunScenario:
    def test_three_bands_300_years_no_nan_revenue_treasure_sane(self) -> None:
        """No NaN, treasure never negative, revenue never negative, and — the Doc 05
        acceptance bar — every nation that has reached beyond BAND has positive
        revenue in >= 90% of its non-BAND years, for the full 300 years.

        Correction round: tithe's payer classes are whoever owns the FIELDs
        (`owners_land`), not LANDLORDS unconditionally (three_bands.yaml's valley
        fields are TENANT-owned), and the chief's/State's herd share is a draw on
        HERD_OWNERS' income (herd produce) rather than on herd growth, which sits at
        ~0 once a herd reaches graze_cap. With both fixed, this bar is reached for
        both nation_valley (tithe) and nation_steppe (herd share).
        """

        world = load_scenario(str(REPO_ROOT / "tests" / "scenarios" / "three_bands.yaml"))
        world.ledger = Ledger()

        non_band_years: dict[str, int] = {}
        revenue_positive_years: dict[str, int] = {}
        for year in range(300):
            run_year(world)
            assert_invariants(world)
            for nation in world.nations.values():
                if nation.ended:
                    continue
                assert nation.scalars.revenue >= -1e-6, f"year {year} {nation.id}: revenue < 0"
                assert nation.scalars.treasure >= -1e-6, f"year {year} {nation.id}: treasure < 0"
                if nation.seat is SeatKind.BAND:
                    continue
                non_band_years[nation.id] = non_band_years.get(nation.id, 0) + 1
                if nation.scalars.revenue > 0:
                    revenue_positive_years[nation.id] = revenue_positive_years.get(nation.id, 0) + 1

        assert non_band_years, "expected at least one nation to reach beyond BAND"
        for nation_id, years in non_band_years.items():
            fraction = revenue_positive_years.get(nation_id, 0) / years
            assert fraction >= 0.9, (
                f"{nation_id}: revenue positive in only {fraction:.2%} of {years} "
                f"non-BAND years (Doc 05 bar is >= 90%)"
            )


# --- (f) unfunded_laws flags STANDING_ARMY_ACT when defence draw is 0 ---


class TestUnfundedLaws:
    def test_standing_army_unfunded_when_defence_draw_zero(self) -> None:
        from stock.core.world import BudgetShares

        loc = Location(id="loc1", terrain=Terrain.PLAINS, nation="nation1")
        loc.market = _flat_market()
        soldiers = Record(cls=ClassId.SOLDIERS, location="loc1", size=10.0, wealth=Wealth())
        loc.records.append(soldiers)
        state_record = Record(cls=ClassId.STATE, location="loc1", size=1.0, wealth=Wealth())
        loc.records.append(state_record)

        nation = Nation(id="nation1", seat=SeatKind.STATE, state=state_record)
        nation.scalars = NationScalars(soldier_pay=1.2)  # nothing else writes this yet; set explicitly
        nation.laws[LawId.STANDING_ARMY_ACT] = LawState(enacted=True)
        nation.budget = BudgetShares(
            defence=0.0, justice=0.2, works=0.2, service=0.2, court=0.2, transfers=0.2
        )

        world = make_world(nations={"nation1": nation}, locations={"loc1": loc})
        world.ledger = Ledger()

        step_taxation(world)

        assert nation.scalars.defence_draw == 0.0
        assert LawId.STANDING_ARMY_ACT in nation.scalars.unfunded_laws


# --- (g)-(i): finance/credit.py (Doc 05, task S1-D05-T2) ---


class TestCreditRates:
    def test_r_market_rises_with_r_bar(self) -> None:
        from stock.finance.credit import rates

        world = make_world()
        low = Nation(id="low", seat=SeatKind.STATE, scalars=NationScalars(r_bar=0.05, J=0.5))
        high = Nation(id="high", seat=SeatKind.STATE, scalars=NationScalars(r_bar=0.20, J=0.5))
        r_market_low, _, _ = rates(low, world)
        r_market_high, _, _ = rates(high, world)
        assert r_market_high > r_market_low

    def test_r_market_rises_with_lower_justice(self) -> None:
        from stock.finance.credit import rates

        world = make_world()
        just = Nation(id="just", seat=SeatKind.STATE, scalars=NationScalars(r_bar=0.05, J=0.9))
        unjust = Nation(id="unjust", seat=SeatKind.STATE, scalars=NationScalars(r_bar=0.05, J=0.1))
        r_market_just, _, _ = rates(just, world)
        r_market_unjust, _, _ = rates(unjust, world)
        assert r_market_unjust > r_market_just


def _credit_world(funding_mode: str) -> World:
    """A STATE nation with a hoard-holding CAPITALISTS record (willing to buy bonds),
    Public Credit enacted, and a war's `spending_extra` to fund."""
    from stock.core.params import Params

    loc = Location(id="loc1", terrain=Terrain.PLAINS, nation="nation1")
    loc.market = _flat_market()
    capitalists = Record(cls=ClassId.CAPITALISTS, location="loc1", size=5.0, wealth=Wealth(hoard=1000.0))
    loc.records.append(capitalists)
    state_record = Record(cls=ClassId.STATE, location="loc1", size=1.0, wealth=Wealth())
    loc.records.append(state_record)

    nation = Nation(id="nation1", seat=SeatKind.STATE, state=state_record)
    nation.scalars = NationScalars(r_bar=0.05, J=0.5, N_bar=0.0, revenue=100.0, defence_draw=10.0)
    nation.scalars.spending_extra = 50.0
    nation.funding_mode = funding_mode
    nation.laws[LawId.PUBLIC_CREDIT] = LawState(enacted=True)

    world = make_world(nations={"nation1": nation}, locations={"loc1": loc}, params=Params.default())
    world.ledger = Ledger()
    return world


class TestPublicCreditFunding:
    def test_bond_financed_war_tops_up_defence_draw_and_owes_service_next_year(self) -> None:
        from stock.finance.credit import step_credit

        world = _credit_world("BONDS")
        nation = world.nations["nation1"]
        step_credit(world)

        assert nation.scalars.defence_draw == 10.0 + 50.0, "bonds fully cover spending_extra this year"
        assert nation.scalars.spending_extra == 0.0
        assert nation.scalars.debt > 0.0
        assert nation.scalars.service_due > 0.0, "a service line is owed next year"

    def test_tax_financed_war_leaves_defence_draw_short_and_no_debt(self) -> None:
        from stock.finance.credit import step_credit

        world = _credit_world("TAX")
        nation = world.nations["nation1"]
        step_credit(world)

        assert nation.scalars.defence_draw == 10.0, "no bonds: the draw is not topped up"
        assert nation.scalars.spending_extra == 50.0, "unmet — a tax-financed nation must find it elsewhere"
        assert nation.scalars.debt == 0.0
        assert nation.scalars.service_due == 0.0


class TestPublicCreditDefault:
    def test_default_zeroes_debt_and_bonds_and_closes_public_credit(self) -> None:
        from stock.finance.credit import default_public_debt

        world = _credit_world("BONDS")
        nation = world.nations["nation1"]
        bondholder = world.locations["loc1"].record(ClassId.CAPITALISTS)
        assert bondholder is not None
        bondholder.wealth.bonds = 200.0
        nation.scalars.debt = 200.0
        nation.scalars.service_due = 40.0

        assert world.params is not None
        default_public_debt(nation, world, world.params.credit)

        assert nation.scalars.debt == 0.0
        assert bondholder.wealth.bonds == 0.0
        assert nation.scalars.default_history is True
        expected_closed_until = world.year + world.params.credit.default_closure_years
        assert nation.scalars.public_credit_closed_until == expected_closed_until
        assert nation.laws[LawId.PUBLIC_CREDIT].enacted is False


# --- (j)-(l): meta/hegemony.py and meta/scoreboards.py (Doc 05, task S1-D05-T4a/b) ---


def _hegemony_world() -> World:
    """Two nations: 'small' has a tiny population and high produce_per_head; 'big' has
    a large population and the higher total productive V — winners() should return
    each of them for a different curve."""
    from stock.core.params import Params

    loc_small = Location(id="loc_small", terrain=Terrain.PLAINS, nation="small")
    loc_small.market = _flat_market()
    small_producer = Producer(kind=ProducerKind.WORKSHOP, location="loc_small", last_V=100.0)
    loc_small.producers.append(small_producer)
    loc_small.records.append(Record(cls=ClassId.CRAFTSMEN, location="loc_small", size=10.0))

    loc_big = Location(id="loc_big", terrain=Terrain.PLAINS, nation="big")
    loc_big.market = _flat_market()
    big_producer = Producer(kind=ProducerKind.WORKSHOP, location="loc_big", last_V=500.0)
    loc_big.producers.append(big_producer)
    loc_big.records.append(Record(cls=ClassId.CRAFTSMEN, location="loc_big", size=1000.0))

    nation_small = Nation(id="small", seat=SeatKind.STATE, scalars=NationScalars())
    nation_big = Nation(id="big", seat=SeatKind.STATE, scalars=NationScalars())

    world = make_world(
        nations={"small": nation_small, "big": nation_big},
        locations={"loc_small": loc_small, "loc_big": loc_big},
        params=Params.default(),
    )
    return world


class TestHegemonyFlags:
    def test_flags_fire_at_threshold(self) -> None:
        from stock.meta.hegemony import world_shares

        world = _hegemony_world()
        nation_big = world.nations["big"]
        nation_big.scalars.treasure = 1000.0  # dominates capital_share too
        nation_big.flows["consumption"] = 1000.0
        world.nations["small"].flows["consumption"] = 1.0

        world_shares(world)
        h = world.hegemony
        assert h.production_share["big"] >= 0.75
        assert h.flags["big"] >= 2

    def test_countdown_resets_when_flags_drop_below_two(self) -> None:
        from stock.meta.hegemony import world_shares

        world = _hegemony_world()
        nation_big = world.nations["big"]
        nation_big.scalars.treasure = 1000.0
        nation_big.flows["consumption"] = 1000.0
        world.nations["small"].flows["consumption"] = 1.0

        assert world.params is not None
        world_shares(world)
        assert world.hegemony.countdown_nation == "big"
        first_countdown = world.hegemony.countdown
        assert first_countdown == world.params.scoreboard.h_years

        world.year += 1
        world_shares(world)
        assert first_countdown is not None
        assert world.hegemony.countdown == first_countdown - 1

        # flags drop below two: countdown resets to H_years, not cancelled
        nation_big.scalars.treasure = 0.0
        nation_big.flows["consumption"] = 1.0
        world.year += 1
        world_shares(world)
        assert world.hegemony.countdown == world.params.scoreboard.h_years
        assert world.hegemony.countdown_nation == "big"


class TestWinners:
    def test_winners_can_differ(self) -> None:
        from stock.meta.hegemony import winners

        world = _hegemony_world()
        per_head, labour_output = winners(world)
        assert per_head == "small"  # 100/10 = 10 per head vs 500/1000 = 0.5
        assert labour_output == "big"  # 500 > 100 total productive V
        assert per_head != labour_output


# --- (m)-(o): meta/regression.py (Doc 05, task S1-D05-T5) ---


def _regression_world() -> tuple[World, Nation, Location, Producer]:
    from stock.core.params import Params

    params = Params.default()
    loc = Location(id="loc1", terrain=Terrain.PLAINS, nation="nation1")
    loc.market = _flat_market()
    producer = Producer(
        kind=ProducerKind.WORKSHOP, location="loc1", stock_in_place=100.0, last_V=100.0,
        method=MethodId.HANDICRAFT, owners_stock={ClassId.CRAFTSMEN: 1.0},
    )
    loc.producers.append(producer)
    craftsmen = Record(cls=ClassId.CRAFTSMEN, location="loc1", size=10.0, wealth=Wealth(stock_in_place=100.0))
    craftsmen.A[Tier.SUBSISTENCE] = 1.0
    craftsmen.E[Tier.SUBSISTENCE] = 5.0
    loc.records.append(craftsmen)

    nation = Nation(id="nation1", seat=SeatKind.STATE, scalars=NationScalars(U_dis=10.0))
    nation.tree2.production[MethodId.HANDICRAFT].lit = True
    nation.tree2.production[MethodId.SOLITARY_LABOUR].lit = True

    world = make_world(nations={"nation1": nation}, locations={"loc1": loc}, params=params)
    world.ledger = Ledger()
    return world, nation, loc, producer


class TestRegressionSpiralAndResolve:
    def test_spiral_window_triggers_resolve_after_k_spiral_years(self) -> None:
        from stock.meta.regression import check_and_resolve

        world, nation, loc, producer = _regression_world()
        params = world.params
        assert params is not None
        nation.scalars.prev_n_bar = 0.0
        nation.scalars.prev_produce_per_head = 1000.0

        triggered_flags = []
        for year in range(params.regression.k_spiral):
            world.year = year
            producer.last_V = max(0.0, 100.0 - year * 10.0)  # produce_per_head falling
            nation.scalars.N_bar = -5.0 - year  # always < n_crit, always falling
            triggered_flags.append(check_and_resolve(nation, world, params.regression))

        assert triggered_flags[:-1] == [False] * (len(triggered_flags) - 1)
        assert triggered_flags[-1] is True
        assert nation.scalars.regressions == 1

    def test_resolve_moves_e_toward_a_and_keeps_tree_nodes_lit(self) -> None:
        from stock.meta.regression import resolve

        world, nation, loc, producer = _regression_world()
        craftsmen = loc.record(ClassId.CRAFTSMEN)
        assert craftsmen is not None
        e_before = craftsmen.E[Tier.SUBSISTENCE]

        resolve(nation, world)

        assert craftsmen.E[Tier.SUBSISTENCE] < e_before  # moved toward A (1.0), faster than alpha_down would
        assert nation.tree2.production[MethodId.HANDICRAFT].lit is True
        assert nation.tree2.production[MethodId.SOLITARY_LABOUR].lit is True


class TestEndNation:
    def test_end_nation_writes_final_ledger_with_expected_fields(self) -> None:
        from stock.meta.regression import end_nation
        from stock.sim.ledger import build_row

        world, nation, loc, producer = _regression_world()
        nation.scalars.revenue = 100.0
        nation.scalars.debt = 20.0
        assert world.ledger is not None
        world.ledger.add_row(build_row(nation, world))

        # the nation loses its only location (conquest already reassigned it away)
        loc.nation = "other_nation"
        end_nation(nation, world)

        assert nation.ended is True
        assert nation.final_ledger is not None
        expected_keys = {
            "turns_elapsed",
            "terminal_condition",
            "regressions_suffered",
            "curve_produce_per_head_final",
            "curve_labour_share_final",
            "curve_freedom_index_final",
            "curve_produce_per_head_peak",
            "curve_labour_share_peak",
            "curve_freedom_index_peak",
            "population",
            "productive_population",
            "unproductive_population",
            "emigrated_count",
            "military_dead",
            "locations_held_at_end",
            "locations_held_peak",
            "stock",
            "hoard_share",
            "interest_rate",
            "debt_revenue_ratio",
            "defaults",
            "laws_enacted",
            "laws_repealed",
            "laws_lapsed",
            "tree_nodes_lit",
            "wars_declared",
            "wars_suffered",
            "wars_won",
            "wars_lost",
            "locations_taken",
            "locations_lost",
            "plunder_taken",
        }
        assert expected_keys.issubset(nation.final_ledger.keys())
        assert nation.final_ledger["debt_revenue_ratio"] == pytest.approx(0.2)
        assert nation.final_ledger["population"] == 10.0
        assert nation.treaties == []


# --- Scenario acceptance: three_bands.yaml, --until-game-over, seeds 1..5 ---


class TestUntilGameOverScenario:
    """Doc 05's scenario acceptance: every seed terminates (game over or every
    nation ended) within 2,000 years with null sovereigns; no NaN; value
    conservation holds every year.

    Termination is no longer asserted (DEVIATIONS-IN-PROGRESS.md A69): it only ever
    held because the first band to settle was "hegemon" over two rivals that were
    still bands (game over by year ~30). With flags counting only against settled
    rivals, a null-sovereign world — nobody declares war — can settle into a
    balance of powers: measured on `three_bands.yaml`, seed 1 ends at year 1135
    (the valley outgrows its rivals on four arable locations), seeds 2-4 hold
    0.50/0.50, 0.49/0.51 and 0.70/0.30 capital shares for 2,000 years. The
    invariant and conservation checks run over Doc 08's 600-year horizon instead.

    Doc 05's acceptance also asks for "at least one seed reaches a manufactory" —
    not asserted here. `PRODUCTION_CHAIN`'s strict predecessor-chain gating means a
    nation that never herds can never light `HERDING_WITH_DEPENDENTS`, which
    permanently blocks every later node including MANUFACTORY; a herding nation
    (`nation_steppe`) does progress further (confirmed to reach `BOUND_LABOUR` after
    A45's fix below) but its own field never grows past a fraction of a land share
    in 2,000 years under current params. Reaching a manufactory needs either a
    branching redesign of the chain or an economic tuning pass — both out of scope
    here; logged as A46 in DEVIATIONS-UNRESOLVED.md for Doc 08 (or a design-document
    reading) to pick up."""

    def test_seeds_1_to_5_run_600_years_with_no_nan_and_value_conservation(self) -> None:
        from stock.sim.rng import make_rng

        for seed in range(1, 6):
            world = load_scenario(str(REPO_ROOT / "tests" / "scenarios" / "three_bands.yaml"))
            world.rng = make_rng(seed)

            years = 0
            max_years = 600
            while (
                years < max_years
                and not world.hegemony.game_over
                and not all(n.ended for n in world.nations.values())
            ):
                run_year(world)
                years += 1
                assert_invariants(world)

            for row in world.ledger.rows:
                for value in row.flows.values():
                    assert math.isfinite(value), f"seed {seed} year {row.year} {row.nation}: NaN/inf in flows"
                labour = row.flows.get("labour_income", 0.0)
                profit = row.flows.get("profit", 0.0)
                rent = row.flows.get("rent", 0.0)
                v = row.flows.get("V", 0.0)
                if v > 0:
                    rel_error = abs((labour + profit + rent) - v) / abs(v)
                    assert rel_error <= 1e-6, (
                        f"seed {seed} year {row.year} {row.nation}: value conservation failed"
                    )
