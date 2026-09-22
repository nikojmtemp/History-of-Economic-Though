"""The growth clamp, the one-person minimum, customary laws, population-gated
taming, and procedural world generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from stock.api.layout import compute_layout, count_crossings, graph_edges, min_edge_node_clearance
from stock.core.laws import LawId
from stock.core.params import Params
from stock.core.records import ClassId, Record, Wealth, quantise_move
from stock.core.world import (
    Capacity,
    HegemonyState,
    Location,
    Market,
    Nation,
    PrevSnapshot,
    Resources,
    SeatKind,
    Terrain,
    World,
)
from stock.engine.band import tame_gate_met, tame_herd
from stock.engine.mobility import vertical_flow
from stock.engine.population import population_update, reap_extinct_records
from stock.politics.legislation import enact_by_custom
from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from stock.sim.worldgen import WorldGenConfig, generate_scenario, parse_random_spec, write_scenario
from tests._harness import assert_invariants, run_year


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


# --- growth clamp ------------------------------------------------------------------


def test_growth_never_exceeds_max_growth() -> None:
    params = Params.default()
    record = Record(cls=ClassId.LABOURERS, location="x", size=100.0)
    record.A.subsistence = 1000.0  # absurd surplus
    population_update(record, params)
    assert record.size == pytest.approx(100.0 * (1.0 + params.population.max_growth))


def test_max_growth_is_reachable_through_the_subsistence_cap() -> None:
    """`a_subs_cap` and `beta` are sized so the 10% ceiling actually binds."""

    p = Params.default()
    assert p.population.beta * (p.consumption.a_subs_cap - 1.0) >= p.population.max_growth
    assert p.population.max_growth == pytest.approx(0.10)


# --- the one-person minimum ---------------------------------------------------------


def test_quantise_move_rounds_to_whole_people() -> None:
    assert quantise_move(100.0, 0.3, 1.0) == 0.0  # under a person: nobody goes
    assert quantise_move(100.0, 5.0, 1.0) == 5.0
    assert quantise_move(100.0, 99.5, 1.0) == 100.0  # would leave half a person: everyone goes
    assert quantise_move(0.6, 0.1, 1.0) == 0.6  # a sub-person source moves entire
    assert quantise_move(100.0, 0.3, 0.0) == 0.3  # rule off
    assert quantise_move(100.0, -1.0, 1.0) == 0.0


def test_vertical_flow_never_creates_a_sub_person_record() -> None:
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())
    src = Record(cls=ClassId.LABOURERS, location="x", size=50.0)
    loc.records.append(src)
    moved = vertical_flow(loc, ClassId.LABOURERS, ClassId.CRAFTSMEN, 0.001, 1.0)
    assert moved == 0.0
    craftsmen = loc.record(ClassId.CRAFTSMEN)
    assert craftsmen is None or craftsmen.size == 0.0
    moved = vertical_flow(loc, ClassId.LABOURERS, ClassId.CRAFTSMEN, 0.1, 1.0)
    assert moved == pytest.approx(5.0)
    assert loc.record(ClassId.CRAFTSMEN).size == pytest.approx(5.0)


def test_reap_folds_last_people_into_vertical_down_neighbour() -> None:
    loc = Location(id="x", terrain=Terrain.PLAINS, nation="n", market=Market())
    craftsmen = Record(cls=ClassId.CRAFTSMEN, location="x", size=0.4, wealth=Wealth(hoard=3.0))
    labourers = Record(cls=ClassId.LABOURERS, location="x", size=20.0)
    loc.records = [craftsmen, labourers]
    nation = Nation(id="n", seat=SeatKind.STATE)
    world = make_world(locations={"x": loc}, nations={"n": nation})
    reap_extinct_records(loc, world, nation)
    assert craftsmen.size == 0.0
    assert craftsmen.wealth.hoard == 0.0
    assert labourers.size == pytest.approx(20.4)
    assert labourers.wealth.hoard == pytest.approx(3.0)
    assert nation.flows.get("reaped") == pytest.approx(0.4)


def test_no_working_record_under_one_person_over_a_long_run() -> None:
    world = load_scenario("tests/scenarios/three_bands_ai.yaml")
    for nation in world.nations.values():
        nation.ai = "scripted"
    for _ in range(120):
        run_year(world)
        for loc in world.locations.values():
            for r in loc.records:
                assert not (0.0 < r.size < 1.0), f"year {world.year} {loc.id} {r.cls.name} size={r.size}"
    assert_invariants(world)


# --- customary laws and population-gated taming ---------------------------------


def _band(size: float, *, grazing: bool = True) -> tuple[Location, Nation, World]:
    loc = Location(
        id="x",
        terrain=Terrain.STEPPE,
        nation="n",
        market=Market(),
        resources=Resources(game=True, game_yield=3.5, grazing=grazing),
        capacity=Capacity(game_cap=1200.0, graze_cap=1500.0),
    )
    loc.records.append(Record(cls=ClassId.HUNTERS, location="x", size=size, walk_away=1.0))
    nation = Nation(id="n", seat=SeatKind.BAND)
    world = make_world(locations={"x": loc}, nations={"n": nation})
    return loc, nation, world


def test_customary_laws_settle_in_by_population_without_authority() -> None:
    loc, nation, world = _band(50.0)
    nation.scalars.A_S = 0.0
    events = enact_by_custom(nation, world)
    assert [e.numbers["law"] for e in events] == [float(LawId.KILL_TO_KILLER.value)]
    assert nation.laws[LawId.KILL_TO_KILLER].enacted
    assert LawId.SHARED_BY_CUSTOM not in nation.laws  # 50 < 60
    assert nation.scalars.A_S == 0.0  # cost nothing

    loc.record(ClassId.HUNTERS).size = 200.0
    enact_by_custom(nation, world)
    assert nation.laws[LawId.SHARED_BY_CUSTOM].enacted
    assert LawId.HERDS_HERITABLE not in nation.laws  # needs herds (a seat past BAND)

    nation.seat = SeatKind.CHIEF
    enact_by_custom(nation, world)
    assert nation.laws[LawId.HERDS_HERITABLE].enacted
    assert not enact_by_custom(nation, world)  # idempotent


def test_customary_law_threshold_below_zero_disables_it() -> None:
    params = Params.from_dict({"politics": {"custom_kill_to_killer_pop": -1.0}})
    loc, nation, world = _band(500.0)
    world.params = params
    enact_by_custom(nation, world)
    assert LawId.KILL_TO_KILLER not in nation.laws
    assert nation.laws[LawId.SHARED_BY_CUSTOM].enacted


def test_large_band_tames_herds_without_contact() -> None:
    loc, nation, world = _band(world_size := 400.0)
    assert loc.contact.get("n", 0.0) == 0.0
    assert tame_gate_met(loc, nation, world)
    assert tame_herd(loc, nation, world)
    assert loc.record(ClassId.HERD_OWNERS).size >= 1.0
    assert loc.record(ClassId.HERDSMEN).size >= 1.0
    assert loc.record(ClassId.HUNTERS).size == pytest.approx(
        world_size * (1.0 - world.params.band.tame_conversion_share)
    )


def test_small_band_still_waits_on_contact() -> None:
    loc, nation, world = _band(100.0)
    assert not tame_gate_met(loc, nation, world)
    # ...and so does a band the size a generated world starts with (A78)
    loc, nation, world = _band(240.0)
    assert not tame_gate_met(loc, nation, world)
    loc.contact["n"] = world.params.tree.contact_threshold
    assert tame_gate_met(loc, nation, world)


def test_no_grazing_no_taming_whatever_the_size() -> None:
    loc, nation, world = _band(1000.0, grazing=False)
    assert not tame_gate_met(loc, nation, world)


def test_contact_scales_with_band_size() -> None:
    from stock.engine.band import band_follow_herds

    small, _, world = _band(100.0)
    big, _, _ = _band(200.0)
    band_follow_herds(small, "n", world.params)
    band_follow_herds(big, "n", world.params)
    assert big.contact["n"] == pytest.approx(2.0 * small.contact["n"])


# --- procedural world generation --------------------------------------------------


def test_generation_is_deterministic_per_seed() -> None:
    a = generate_scenario(WorldGenConfig(seed=11))
    b = generate_scenario(WorldGenConfig(seed=11))
    c = generate_scenario(WorldGenConfig(seed=12))
    assert a == b
    assert a != c


@pytest.mark.parametrize("seed", range(8))
def test_generated_maps_are_planar_connected_and_stocked(seed: int) -> None:
    world = load_scenario(f"random:{seed}:28:3")
    assert len(world.locations) == 28
    assert len(world.nations) == 3
    edges = graph_edges(world)
    layout = compute_layout(world)
    assert count_crossings(layout, edges) == 0
    assert min_edge_node_clearance(layout, edges) >= 30.0

    # connected
    seen = {next(iter(world.locations))}
    frontier = list(seen)
    while frontier:
        loc = world.locations[frontier.pop()]
        for nb in loc.neighbours:
            if nb not in seen:
                seen.add(nb)
                frontier.append(nb)
    assert seen == set(world.locations)

    # symmetric distances
    for loc in world.locations.values():
        for nb_id, d in loc.neighbours.items():
            assert world.locations[nb_id].neighbours[loc.id] == d

    resources = [loc.resources for loc in world.locations.values()]
    assert sum(r.rare for r in resources) == 1
    assert any(r.ore for r in resources)
    assert any(r.coal for r in resources)
    assert any(r.arable for r in resources)
    assert any(loc.river for loc in world.locations.values())
    assert any(loc.coast for loc in world.locations.values())
    for r in resources:
        for key in ("game", "arable", "timber", "ore", "coal", "fishing"):
            assert getattr(r, key) == (getattr(r, f"{key}_yield") > 0)
        # grazing has no yield, only a graze_cap
    for loc in world.locations.values():
        if loc.resources.grazing:
            assert loc.capacity.graze_cap > 0

    # every band starts on a hunt that can feed it, and the first seat is the player's
    for k, nation in enumerate(world.nations.values()):
        home = nation.locations(world)
        assert len(home) == 1
        assert home[0].resources.game and home[0].resources.game_yield >= 3.5
        assert home[0].terrain is not Terrain.MOUNTAIN
        assert (nation.ai is None) == (k == 0)


def test_generated_world_runs() -> None:
    world = load_scenario("random:5")
    for nation in world.nations.values():
        nation.ai = "scripted"
    for _ in range(60):
        run_year(world)
    assert_invariants(world)


def test_parse_random_spec() -> None:
    assert parse_random_spec("tests/scenarios/three_bands.yaml") is None
    assert parse_random_spec("random") == WorldGenConfig()
    assert parse_random_spec("random:7") == WorldGenConfig(seed=7)
    assert parse_random_spec("random:7:40:5") == WorldGenConfig(seed=7, locations=40, nations=5)
    with pytest.raises(ValueError):
        parse_random_spec("random:1:8:5")  # too many nations for the map


def test_written_scenario_loads_identically(tmp_path: Path) -> None:
    cfg = WorldGenConfig(seed=3, locations=20, nations=2)
    out = write_scenario(cfg, tmp_path / "gen.yaml")
    from_file = load_scenario(out)
    in_memory = load_scenario("random:3:20:2")
    assert set(from_file.locations) == set(in_memory.locations)
    assert {n.id for n in from_file.nations.values()} == {n.id for n in in_memory.nations.values()}
    for loc_id, loc in from_file.locations.items():
        assert loc.neighbours == in_memory.locations[loc_id].neighbours
