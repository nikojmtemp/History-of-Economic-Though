"""Doc 05 task T3 acceptance tests: `meta/trees.py` gate evaluation (DD §6)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from stock.core.laws import FocusKind, LawId
from stock.core.params import Params
from stock.core.producers import MethodId, Producer, ProducerKind
from stock.core.records import ClassId, Record
from stock.core.trees import DefenceNode, TreeINode
from stock.core.world import (
    FocusState,
    HegemonyState,
    LawState,
    Location,
    Nation,
    PrevSnapshot,
    Resources,
    Route,
    Terrain,
    World,
)
from stock.engine.production import herd_total
from stock.meta.trees import carrying_configuration, evaluate_gates, evaluate_tree1, evaluate_tree2
from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from tests._harness import run_year

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


# --- (a) Tree I: Grain lights only with arable + a settled (FIELD) record -----


def test_grain_lights_only_with_arable_and_field() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]

    loc_no_field = Location(
        id="loc1", terrain=Terrain.PLAINS, nation="n", resources=Resources(arable=True)
    )
    world.locations["loc1"] = loc_no_field
    evaluate_tree1(loc_no_field, nation, world)
    assert not loc_no_field.tree1.nodes[TreeINode.GRAIN].lit

    loc_no_arable = Location(id="loc2", terrain=Terrain.PLAINS, nation="n")
    loc_no_arable.producers.append(
        Producer(kind=ProducerKind.FIELD, location="loc2", land_shares=5.0)
    )
    world.locations["loc2"] = loc_no_arable
    evaluate_tree1(loc_no_arable, nation, world)
    assert not loc_no_arable.tree1.nodes[TreeINode.GRAIN].lit

    loc_both = Location(
        id="loc3", terrain=Terrain.PLAINS, nation="n", resources=Resources(arable=True)
    )
    loc_both.producers.append(Producer(kind=ProducerKind.FIELD, location="loc3", land_shares=5.0))
    world.locations["loc3"] = loc_both
    evaluate_tree1(loc_both, nation, world)
    assert loc_both.tree1.nodes[TreeINode.GRAIN].lit
    assert loc_both.tree1.nodes[TreeINode.GRAIN].lit_year == world.year


# --- (b) Tree I: Luxuries' three doors -----------------------------------------


def test_luxuries_lights_via_rare_and_craftsmen() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n", resources=Resources(rare=True))
    loc.records.append(Record(cls=ClassId.CRAFTSMEN, location="a", size=5.0))
    world.locations["a"] = loc

    evaluate_tree1(loc, nation, world)
    assert loc.tree1.nodes[TreeINode.LUXURIES].lit


def test_luxuries_lights_via_route_to_a_market_that_has_them() -> None:
    world = make_world(nations={"n": Nation(id="n"), "m": Nation(id="m")})
    nation = world.nations["n"]
    loc_a = Location(id="a", terrain=Terrain.PLAINS, nation="n", neighbours={"b": 1.0})
    loc_b = Location(id="b", terrain=Terrain.PLAINS, nation="m", neighbours={"a": 1.0})
    loc_b.tree1.nodes[TreeINode.LUXURIES].lit = True
    world.locations["a"] = loc_a
    world.locations["b"] = loc_b
    world.routes["a->b"] = Route(id="a->b", a="a", b="b")

    evaluate_tree1(loc_a, nation, world)
    assert loc_a.tree1.nodes[TreeINode.LUXURIES].lit


def test_luxuries_lights_via_manufactory_in_the_nation() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]
    loc_with_manufactory = Location(id="a", terrain=Terrain.PLAINS, nation="n")
    loc_with_manufactory.producers.append(
        Producer(kind=ProducerKind.MANUFACTORY, location="a", stock_in_place=10.0)
    )
    loc_other = Location(id="b", terrain=Terrain.PLAINS, nation="n")
    world.locations["a"] = loc_with_manufactory
    world.locations["b"] = loc_other

    evaluate_tree1(loc_other, nation, world)
    assert loc_other.tree1.nodes[TreeINode.LUXURIES].lit


# --- (c) Tree II: Manufactory lights only after Stock Separable + labourers, ---
# --- stays lit and goes idle when the law is later un-enacted -----------------


def _light_predecessors(nation: Nation, up_to: MethodId) -> None:
    from stock.core.trees import PRODUCTION_CHAIN

    for method in PRODUCTION_CHAIN:
        if method is up_to:
            return
        nation.tree2.production[method].lit = True


def test_manufactory_lights_only_after_gate_and_stays_lit_when_law_repealed() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n")
    world.locations["a"] = loc
    _light_predecessors(nation, MethodId.MANUFACTORY)

    evaluate_tree2(nation, world)
    assert not nation.tree2.production[MethodId.MANUFACTORY].lit

    nation.laws[LawId.STOCK_SEPARABLE] = LawState(enacted=True)
    loc.records.append(Record(cls=ClassId.LABOURERS, location="a", size=5.0))
    evaluate_tree2(nation, world)
    assert nation.tree2.production[MethodId.MANUFACTORY].lit
    assert nation.tree2.production[MethodId.MANUFACTORY].idle is False

    nation.laws[LawId.STOCK_SEPARABLE].enacted = False
    evaluate_tree2(nation, world)
    assert nation.tree2.production[MethodId.MANUFACTORY].lit, "a lit node never un-lights"
    assert nation.tree2.production[MethodId.MANUFACTORY].idle is True


# --- (d) Focus: Patent lowers a numeric threshold; Education never opens a ----
# --- boolean (law) gate ---------------------------------------------------


def test_patent_focus_lights_a_below_threshold_numeric_node() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n")
    loc.producers.append(Producer(kind=ProducerKind.FIELD, location="a", land_shares=10.0))
    world.locations["a"] = loc
    _light_predecessors(nation, MethodId.THREE_FIELD_ROTATION)

    threshold = world.params.tree.rotation_land_threshold
    assert 10.0 < threshold, "fixture must start below the threshold"

    evaluate_tree2(nation, world)
    assert not nation.tree2.production[MethodId.THREE_FIELD_ROTATION].lit

    nation.focus = FocusState(kind=FocusKind.PATENT, node="THREE_FIELD_ROTATION", progress=20.0)
    evaluate_tree2(nation, world)
    assert nation.tree2.production[MethodId.THREE_FIELD_ROTATION].lit


def test_education_focus_does_not_light_a_law_gated_node() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n")
    world.locations["a"] = loc
    _light_predecessors(nation, MethodId.MONEY_RENT)
    # COMMUTATION is deliberately left un-enacted: MONEY_RENT's gate is a bare law
    # check, which Education (dol_market_size_threshold only) must not touch.

    nation.focus = FocusState(kind=FocusKind.EDUCATION, node="MONEY_RENT", progress=100.0)
    evaluate_tree2(nation, world)
    assert not nation.tree2.production[MethodId.MONEY_RENT].lit


# --- carrying_configuration: pure, matches the lit set it would produce -------


def test_carrying_configuration_matches_gate_state_with_no_focus() -> None:
    from stock.core.world import SeatKind

    world = make_world(nations={"n": Nation(id="n", seat=SeatKind.STATE)})
    nation = world.nations["n"]
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n")
    world.locations["a"] = loc

    config_before = carrying_configuration(nation, world)
    assert MethodId.SOLITARY_LABOUR not in config_before  # not BAND-seat, no HUNTING producer

    loc.producers.append(Producer(kind=ProducerKind.HUNTING, location="a"))
    config_after = carrying_configuration(nation, world)
    assert MethodId.SOLITARY_LABOUR in config_after
    # Pure: nothing on the nation's actual tree state was mutated by the call.
    assert nation.tree2.production[MethodId.SOLITARY_LABOUR].lit is False
    assert nation.tree2.production[MethodId.HERDING_WITH_DEPENDENTS].lit is False


# --- (e) Scenario: three_bands.yaml, 300 years -------------------------------


def test_three_bands_300_years_game_and_herds_lit_no_nan() -> None:
    world = load_scenario(str(SCENARIO))
    for _ in range(300):
        run_year(world)
        evaluate_gates(world)

    saw_game_location = False
    for nation in world.nations.values():
        if nation.ended:
            continue
        for loc in nation.locations(world):
            if loc.resources.game:
                saw_game_location = True
                assert loc.tree1.nodes[TreeINode.GAME_AND_GATHERING].lit, (
                    f"{loc.id} has game and is occupied by {nation.id} but "
                    "GAME_AND_GATHERING is unlit"
                )
    assert saw_game_location, "fixture sanity: scenario should have at least one game location"

    # Not "wherever herd currently sits" -- `engine.mobility`'s stock edges can
    # carry herd wealth to a location that was never itself the site of taming, so
    # herd presence there says nothing about that location's own gate. Check
    # instead that taming happened *somewhere* (DOMESTICATED_HERDS lit there) and
    # that herd exists in the world at all.
    domesticated_herds_lit_somewhere = any(
        loc.tree1.nodes[TreeINode.DOMESTICATED_HERDS].lit for loc in world.locations.values()
    )
    assert domesticated_herds_lit_somewhere, (
        "expected at least one location to have tamed a herd in 300 years"
    )
    # A `> 1e-6` floor, not `> 0`: a pre-existing, unrelated mobility bug (not
    # touched by this task; see Blockers) leaks near-zero (~1e-75) herd noise into
    # records that were never actually tamed.
    total_herd = sum(herd_total(loc) for loc in world.locations.values())
    assert total_herd > 1e-6, "fixture sanity: some herd should exist in the world after 300 years"

    for nation in world.nations.values():
        for loc in nation.locations(world):
            for tree1_state in loc.tree1.nodes.values():
                assert tree1_state.lit_year is None or math.isfinite(tree1_state.lit_year)
        for production_state in nation.tree2.production.values():
            assert production_state.lit_year is None or math.isfinite(production_state.lit_year)
        for defence_state in nation.tree2.defence.values():
            assert defence_state.lit_year is None or math.isfinite(defence_state.lit_year)
        for credit_state in nation.tree2.credit.values():
            assert credit_state.lit_year is None or math.isfinite(credit_state.lit_year)


# --- (f) Determinism -----------------------------------------------------------


def _lit_year_map(world: World) -> dict[tuple[str, str, int], int | None]:
    result: dict[tuple[str, str, int], int | None] = {}
    for loc_id, loc in world.locations.items():
        for tree1_node, tree1_state in loc.tree1.nodes.items():
            result[("tree1", loc_id, tree1_node.value)] = tree1_state.lit_year
    for nation_id, nation in world.nations.items():
        for method, production_state in nation.tree2.production.items():
            result[("prod", nation_id, method.value)] = production_state.lit_year
        for defence_node, defence_state in nation.tree2.defence.items():
            result[("defence", nation_id, defence_node.value)] = defence_state.lit_year
        for credit_node, credit_state in nation.tree2.credit.items():
            result[("credit", nation_id, credit_node.value)] = credit_state.lit_year
    return result


def test_determinism_two_runs_give_identical_lit_year_maps() -> None:
    def run(years: int) -> dict[tuple[str, str, int], int | None]:
        world = load_scenario(str(SCENARIO))
        for _ in range(years):
            run_year(world)
            evaluate_gates(world)
        return _lit_year_map(world)

    result_a = run(100)
    result_b = run(100)
    assert result_a == result_b
    assert any(v is not None for v in result_a.values()), "fixture sanity: something should light"


# --- misc: DefenceNode idle marking uses active_doctrine, not gating ----------


def test_every_man_a_warrior_lights_unconditionally() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n")
    world.locations["a"] = loc

    evaluate_tree2(nation, world)
    assert nation.tree2.defence[DefenceNode.EVERY_MAN_A_WARRIOR].lit


def test_bank_credit_node_stays_dark() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    nation = world.nations["n"]
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n")
    world.locations["a"] = loc

    from stock.core.trees import CreditNode

    nation.tree2.credit[CreditNode.BILLS_OF_EXCHANGE].lit = True
    evaluate_tree2(nation, world)
    assert not nation.tree2.credit[CreditNode.BANK].lit


def test_node_lit_event_encoding_is_numbers_only() -> None:
    world = make_world(nations={"n": Nation(id="n")})
    loc = Location(id="a", terrain=Terrain.PLAINS, nation="n", resources=Resources(game=True))
    world.locations["a"] = loc

    evaluate_gates(world)
    events = [e for e in world.ledger.events if e.kind == "node_lit"]
    assert events, "expected at least one node_lit event (Game and gathering)"
    for event in events:
        for value in event.numbers.values():
            assert isinstance(value, float)
        assert set(event.numbers) <= {"tree", "branch", "node", "location"}
