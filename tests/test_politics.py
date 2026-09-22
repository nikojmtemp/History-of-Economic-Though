"""Doc 03 acceptance tests (politics and unrest)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from stock.core.actions import Action, ActionKind, validate
from stock.core.goods import Good, basket_cost
from stock.core.laws import LawId, tariff_law
from stock.core.params import Params
from stock.core.records import ClassId, InterestId, Record, Wealth
from stock.core.world import (
    HegemonyState,
    InterestState,
    LawState,
    Location,
    Market,
    Nation,
    PrevSnapshot,
    SeatKind,
    Terrain,
    World,
)
from stock.politics import legislation
from stock.politics.authority import dependents_of, interest_authority, record_authority
from stock.politics.interests import DEMANDS
from stock.politics.justice import convert_disorder, legibility_update
from stock.politics.legislation import enforcement, self_enact, veto
from stock.politics.state import on_tamed_animal
from stock.politics.unrest import step_unrest
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
        year=overrides.pop("year", 0),
        nations=nations,
        locations=locations,
        hostility={},
        hegemony=HegemonyState(),
        prev=PrevSnapshot(),
        ledger=Ledger(),
        rng=make_rng(1),
        params=overrides.pop("params", Params.default()),
    )


# --- self-enactment, passing, veto -----------------------------------------------


def test_self_enacts_first_demand_and_event_carries_three_numbers() -> None:
    nation = Nation(id="n")
    nation.scalars.A_S = 1.0
    nation.interests[InterestId.LANDED] = InterestState(authority=1000.0)
    world = make_world(nations={"n": nation})

    law = DEMANDS[InterestId.LANDED][0]  # the corn tariff (DD §7.4)
    assert law == tariff_law(Good.PROVISIONS)

    events = self_enact(nation, world)
    matching = [e for e in events if e.kind == "law_self_enacted"]
    assert matching, events
    e = matching[0]
    assert set(e.numbers) == {"authority_I", "A_S", "opposition"}
    assert e.numbers["authority_I"] == pytest.approx(1000.0)
    assert nation.laws[law].enacted


def test_insufficient_a_s_cannot_push_a_law_and_reports_three_numbers() -> None:
    nation = Nation(id="n", seat=SeatKind.CHIEF)
    nation.scalars.A_S = 0.1
    nation.interests[InterestId.MERCHANT] = InterestState(authority=1000.0)  # opposes the tariff
    world = make_world(nations={"n": nation})

    law = tariff_law(Good.PROVISIONS)
    action = Action(kind=ActionKind.ENACT, nation="n", payload={"law": law})
    result = validate(world, action)

    assert not result.ok
    assert set(result.numbers) == {"cost", "available"}
    assert result.numbers["available"] == pytest.approx(0.1)
    assert result.numbers["cost"] > result.numbers["available"]


def test_veto_sets_cooldown_and_interest_does_not_reenact_within_it() -> None:
    nation = Nation(id="n")
    nation.scalars.A_S = 10.0
    nation.interests[InterestId.LANDED] = InterestState(authority=18.0)
    world = make_world(nations={"n": nation}, year=5)

    law = tariff_law(Good.PROVISIONS)  # LANDED's first demand
    assert veto(nation, InterestId.LANDED, law, world)
    assert nation.laws[law].veto_cooldown_until == 5 + world.params.politics.k_veto

    self_enact(nation, world)  # same year: still within cooldown
    assert not nation.laws[law].enacted


# --- enforcement -------------------------------------------------------------------


def test_enforcement_matches_formula_and_is_never_zero() -> None:
    nation = Nation(id="n")
    nation.scalars.A_S = 10.0
    nation.scalars.J = 0.5
    nation.interests[InterestId.LABOUR] = InterestState(authority=5.0)  # opposes Serfdom
    world = make_world(nations={"n": nation})

    enf = enforcement(LawId.SERFDOM, nation, world)
    assert enf == pytest.approx(0.5 * 10.0 / 15.0)

    starved = Nation(id="n2")
    starved.scalars.A_S = 0.0
    starved.scalars.J = 0.5
    starved.interests[InterestId.LABOUR] = InterestState(authority=5.0)
    world2 = make_world(nations={"n2": starved})

    enf2 = enforcement(LawId.SERFDOM, starved, world2)
    assert enf2 > 0.0
    assert enf2 == pytest.approx(world2.params.politics.enforcement_epsilon)


# --- continuous law effects (walk_away_multiplier, vertical_flow) ------------------


def test_serfdom_walk_away_multiplier_scales_with_enforcement() -> None:
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())
    serfs = Record(cls=ClassId.SERFS, location="x", size=10.0, walk_away=1.0)
    loc.records = [serfs]
    nation = Nation(id="n")
    nation.laws[LawId.SERFDOM] = LawState(enacted=True, enforcement=0.4)
    world = make_world(locations={"x": loc}, nations={"n": nation})

    legislation._apply_continuous_law_effects(nation, world)

    assert serfs.walk_away == pytest.approx(1.0 - 0.4)


def test_commutation_vertical_flow_moves_serfs_to_tenants() -> None:
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())
    serfs = Record(cls=ClassId.SERFS, location="x", size=100.0, wealth=Wealth(stock_in_place=50.0))
    loc.records = [serfs]
    nation = Nation(id="n")
    nation.laws[LawId.COMMUTATION] = LawState(enacted=True, enforcement=0.5)
    world = make_world(locations={"x": loc}, nations={"n": nation})
    expected_share = world.params.mobility.rate_v_base * 0.5

    legislation._apply_continuous_law_effects(nation, world)

    tenants = loc.record(ClassId.TENANTS)
    assert tenants is not None and tenants.size > 0.0
    assert tenants.size == pytest.approx(100.0 * expected_share)
    assert serfs.size == pytest.approx(100.0 * (1.0 - expected_share))
    assert tenants.wealth.stock_in_place == pytest.approx(50.0 * expected_share)


def test_enclosure_forced_vertical_flow_moves_faster_than_commutation() -> None:
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())
    serfs = Record(cls=ClassId.SERFS, location="x", size=100.0)
    loc.records = [serfs]
    nation = Nation(id="n")
    nation.laws[LawId.ENCLOSURE] = LawState(enacted=True, enforcement=0.5)
    world = make_world(locations={"x": loc}, nations={"n": nation})

    legislation._apply_continuous_law_effects(nation, world)

    labourers = loc.record(ClassId.LABOURERS)
    assert labourers is not None
    # forced=True -> share == enforcement itself, not enforcement*rate_v_base
    assert labourers.size == pytest.approx(100.0 * 0.5)


# --- unrest: disorder vs. political demand ------------------------------------------


def test_disorder_riots_while_high_authority_lobbies_on_the_same_shortfall() -> None:
    params = Params.from_dict({"unrest": {"alpha_up": 0.0, "alpha_down": 0.0}})
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())

    poor = Record(cls=ClassId.LABOURERS, location="x", size=100.0, authority=10.0)  # ratio 0.1 < a_split
    poor.A.subsistence = 0.7
    poor.E.subsistence = 1.0

    landlord = Record(
        cls=ClassId.LANDLORDS, location="x", size=10.0, authority=50.0, wealth=Wealth(land_shares=100.0)
    )  # ratio 5.0 >= a_split
    landlord.A.subsistence = 0.7
    landlord.E.subsistence = 1.0

    loc.records = [poor, landlord]
    nation = Nation(id="n")
    world = make_world(locations={"x": loc}, nations={"n": nation}, params=params)

    step_unrest(world)

    riot_events = [e for e in world.ledger.events if e.kind == "riot"]
    assert riot_events, world.ledger.events
    assert nation.scalars.U_dis > 0.0

    landed = nation.interests.get(InterestId.LANDED)
    assert landed is not None and landed.radicalism > 0.0

    # the landlord's own shortfall never turns into a disorder event
    disorder_kinds = {"strike", "riot", "revolt", "desertion", "mutiny"}
    assert not any(e.kind in disorder_kinds and e.numbers.get("size") == 10.0 for e in world.ledger.events)


# --- legibility ----------------------------------------------------------------------


def test_legibility_rises_only_when_justice_and_converted_disorder_are_both_positive() -> None:
    params = Params.default()
    decay_only = 0.5 * (1.0 - params.authority.delta_ell)

    zero_justice = Nation(id="n1")
    zero_justice.scalars.ell = 0.5
    zero_justice.scalars.U_dis = 10.0
    converted = convert_disorder(zero_justice, j=0.0)
    assert converted == 0.0
    assert legibility_update(zero_justice, 0.0, converted, params) == pytest.approx(decay_only)

    no_disorder = Nation(id="n2")
    no_disorder.scalars.ell = 0.5
    no_disorder.scalars.U_dis = 0.0
    converted = convert_disorder(no_disorder, j=0.5)
    assert converted == 0.0
    assert legibility_update(no_disorder, 0.5, converted, params) == pytest.approx(decay_only)

    both_positive = Nation(id="n3")
    both_positive.scalars.ell = 0.5
    both_positive.scalars.U_dis = 10.0
    converted = convert_disorder(both_positive, j=0.5)
    assert converted > 0.0
    assert legibility_update(both_positive, 0.5, converted, params) > 0.5


# --- handovers and apportionment ------------------------------------------------------


def test_tamed_animal_handover_sets_a_s_to_largest_herd_owners_authority() -> None:
    loc_a = Location(id="a", terrain=Terrain.PLAINS, nation="n", market=Market())
    loc_b = Location(id="b", terrain=Terrain.PLAINS, nation="n", market=Market())
    small = Record(cls=ClassId.HERD_OWNERS, location="a", size=5.0, wealth=Wealth(herd=10.0))
    big = Record(cls=ClassId.HERD_OWNERS, location="b", size=20.0, wealth=Wealth(herd=200.0))
    loc_a.records = [small]
    loc_b.records = [big]
    nation = Nation(id="n", seat=SeatKind.BAND)
    world = make_world(locations={"a": loc_a, "b": loc_b}, nations={"n": nation})

    on_tamed_animal(nation, world)

    expected = record_authority(
        big, nation.scalars.ell, basket_cost(loc_b.market.price), world.params, dependents_of(big, loc_b)
    )
    assert nation.scalars.A_S == pytest.approx(expected)
    assert nation.seat is SeatKind.CHIEF
    smaller = record_authority(
        small, nation.scalars.ell, basket_cost(loc_a.market.price), world.params, dependents_of(small, loc_a)
    )
    assert expected > smaller


def test_interest_authority_identical_when_recomputed_twice_in_a_year() -> None:
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())
    landlord = Record(cls=ClassId.LANDLORDS, location="x", size=10.0, wealth=Wealth(land_shares=50.0))
    labourer = Record(cls=ClassId.LABOURERS, location="x", size=40.0)
    loc.records = [landlord, labourer]
    nation = Nation(id="n")
    nation.scalars.ell = 0.4
    world = make_world(locations={"x": loc}, nations={"n": nation})

    totals_1 = interest_authority(nation, world)
    totals_2 = interest_authority(nation, world)

    for interest_id in totals_1:
        assert totals_1[interest_id] == pytest.approx(totals_2[interest_id])


# --- scenario ------------------------------------------------------------------------


def test_scenario_300_years_reaches_state_and_self_enacts_without_zero_enforcement() -> None:
    world = load_scenario(SCENARIO)
    for _ in range(300):
        run_year(world)
        assert_invariants(world)

    assert any(n.seat is SeatKind.STATE for n in world.nations.values()), {
        nid: n.seat.name for nid, n in world.nations.items()
    }
    assert any(e.kind == "law_self_enacted" for e in world.ledger.events)

    for nation in world.nations.values():
        for law, state in nation.laws.items():
            if state.enacted:
                assert state.enforcement > 0.0, (nation.id, law)
