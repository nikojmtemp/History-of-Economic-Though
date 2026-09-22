"""The opening and the game's length (DEVIATIONS-IN-PROGRESS.md A68-A70).

Measured before these guards: the valley band settled at step 13 of year 0, the
hegemony countdown started in year 2 against two rivals that were still bands, the
game was over by year 33, and `nation_valley` regressed 25 times in those 33 years
(a one-person record's yearly revolt is a discrete trigger). These tests pin the
guards that changed that: an unsteered band settles only once its ground gives out
and a player's band never on its own; flags count only with two settled nations;
a regression has a cooldown and a crowd floor; the herding script does not settle
on an arable *neighbour*, does not flip between near-equal locations, and a move
onto the band's own location is refused.
"""

from __future__ import annotations

from pathlib import Path

from stock.ai.scripts import HERDING_SCRIPT, _better_ground, _seek_ground, _should_settle
from stock.ai.view import LocationSummary, NationView
from stock.core.actions import Action, ActionKind, validate
from stock.core.goods import Tier
from stock.core.records import ClassId, Record
from stock.core.world import (
    HegemonyState,
    Location,
    Nation,
    NationScalars,
    PrevSnapshot,
    SeatKind,
    Terrain,
    World,
)
from stock.engine.band import band_move, move_cost
from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from stock.sim.year import run_year

SCENARIOS = Path(__file__).resolve().parent / "scenarios"


def _world(**kw: object) -> World:
    from stock.core.params import Params

    return World(
        year=int(kw.pop("year", 0)),
        nations=kw.pop("nations", {}),  # type: ignore[arg-type]
        locations=kw.pop("locations", {}),  # type: ignore[arg-type]
        hostility={},
        hegemony=HegemonyState(),
        prev=PrevSnapshot(),
        ledger=Ledger(),
        rng=make_rng(1),
        params=Params.default(),
    )


# --- the band stage ---------------------------------------------------------------


def test_unsteered_band_settles_once_the_hunt_falls_short_not_in_year_zero() -> None:
    world = load_scenario(SCENARIOS / "three_bands_ai.yaml")
    world.rng = make_rng(1)
    valley = world.nations["nation_valley"]
    assert valley.ai is None  # a null sovereign: the engine's heuristics steer it
    run_year(world)
    assert valley.seat is SeatKind.BAND, "settled in year 0"
    settled_year = None
    for _ in range(40):
        run_year(world)
        if valley.seat is not SeatKind.BAND:
            settled_year = world.year - 1
            break
    assert settled_year is not None
    assert settled_year >= world.params.band.settle_pressed_years
    assert world.locations["valley_1"].fields > 0


def test_player_band_is_never_settled_or_moved_by_the_heuristics() -> None:
    world = load_scenario(SCENARIOS / "three_bands_ai.yaml")
    world.rng = make_rng(1)
    valley = world.nations["nation_valley"]
    valley.ai = "player"
    for _ in range(60):
        run_year(world)
    assert valley.seat is SeatKind.BAND
    assert [loc.id for loc in valley.locations(world)] == ["valley_1"]
    assert world.locations["valley_1"].fields == 0


def test_queued_settle_hands_the_seat_over_like_the_automatic_one() -> None:
    world = load_scenario(SCENARIOS / "three_bands_ai.yaml")
    valley = world.nations["nation_valley"]
    valley.ai = "player"
    valley.queue.append(Action(kind=ActionKind.BAND_SETTLE, nation=valley.id, payload={}))
    run_year(world)
    assert valley.seat is not SeatKind.BAND
    assert world.locations["valley_1"].fields > 0


def test_band_move_quotes_its_consensus_cost_and_refuses_its_own_location() -> None:
    world = load_scenario(SCENARIOS / "three_bands_ai.yaml")
    forest = world.nations["nation_forest"]
    home = world.locations["forest_1"]
    quote = validate(world, Action(kind=ActionKind.BAND_MOVE, nation=forest.id, payload={"to": "forest_2"}))
    assert quote.ok and quote.cost == move_cost(world.params) > 0
    people = sum(r.size for r in home.records)
    assert not band_move(world, forest, home, "forest_1", world.params)
    assert home.nation == forest.id and sum(r.size for r in home.records) == people


def test_every_rival_leaves_the_band_stage_on_the_shipped_map() -> None:
    # `forest_2` is a clearing with wild herds (A62): the forest band has somewhere to go.
    for seed in (1, 2, 3):
        world = load_scenario(SCENARIOS / "three_bands_ai.yaml")
        world.rng = make_rng(seed)
        for _ in range(40):
            run_year(world)
        for nid in ("nation_steppe", "nation_forest"):
            nation = world.nations[nid]
            assert nation.seat is not SeatKind.BAND, f"seed {seed}: {nid} still a band at year 40"
            assert nation.locations(world), f"seed {seed}: {nid} lost its location"


# --- the herding script -----------------------------------------------------------


def _loc(
    id_: str, *, game: float = 0.0, grazing: bool = False, arable: bool = False, nation: str | None = None
) -> LocationSummary:
    return LocationSummary(
        id=id_,
        nation=nation,
        game_yield=game,
        grazing=grazing,
        depletion=0.0,
        arable=arable,
        is_town=False,
        fields=0.0,
    )


def _view(home: LocationSummary, *neighbours: LocationSummary, pressed_years: float = 0.0) -> NationView:
    return NationView(
        nation_id="n",
        year=10,
        seat="BAND",
        scalars={"pressed_years": pressed_years},
        curves={"produce_per_head": 0.9},
        flows={},
        class_sizes={},
        law_states={},
        interests={},
        dominant_interest=None,
        own_treaties=(),
        others={},
        breaches_against_us=(),
        own_locations={home.id: home},
        neighbour_locations={n.id: n for n in neighbours},
    )


def test_script_does_not_settle_for_an_arable_neighbour() -> None:
    view = _view(_loc("home", game=5.0), _loc("field", arable=True))
    assert not _should_settle(view)


def test_script_settles_its_own_arable_ground_once_pressed_for_years() -> None:
    assert not _should_settle(_view(_loc("home", game=3.0, arable=True), pressed_years=2))
    assert _should_settle(_view(_loc("home", game=3.0, arable=True), pressed_years=5))


def test_script_seeks_ground_that_feeds_the_band_now() -> None:
    fields_only = _loc("fields_only", arable=True)
    view = _view(_loc("home", game=5.6), fields_only, _loc("clearing", game=4.5, grazing=True))
    action = _seek_ground(view, None)
    assert action is not None and action.payload["to"] == "clearing"


def test_script_needs_clearly_better_ground_before_moving() -> None:
    # 5.6 against 4.5 + herds: within the margin, so the band stays put (it used to
    # flip between the two every year).
    assert _better_ground(_view(_loc("home", game=5.6), _loc("clearing", game=4.5, grazing=True))) is None
    better = _better_ground(_view(_loc("home", game=2.0), _loc("clearing", game=4.5, grazing=True)))
    assert better is not None and better.id == "clearing"


def test_herding_script_rules_keep_their_order() -> None:
    assert [name for name, _, _ in HERDING_SCRIPT][:2] == ["seek_ground", "move_to_better_ground"]


# --- hegemony flags need two settled nations ------------------------------------


def test_flags_do_not_count_against_bands() -> None:
    from stock.meta.hegemony import world_shares

    loc = Location(id="a", terrain=Terrain.PLAINS, nation="a")
    loc.records.append(Record(cls=ClassId.TENANTS, location="a", size=100.0))
    loc.records[0].wealth.stock_in_place = 1000.0
    band_loc = Location(id="b", terrain=Terrain.PLAINS, nation="b")
    band_loc.records.append(Record(cls=ClassId.HUNTERS, location="b", size=100.0))
    a = Nation(id="a", seat=SeatKind.STATE, scalars=NationScalars(), flows={"consumption": 100.0})
    b = Nation(id="b", seat=SeatKind.BAND, scalars=NationScalars(), flows={"consumption": 1.0})
    world = _world(nations={"a": a, "b": b}, locations={"a": loc, "b": band_loc})

    world_shares(world)
    assert world.hegemony.capital_share["a"] > world.params.scoreboard.h_share
    assert world.hegemony.flags == {"a": 0, "b": 0} and world.hegemony.countdown is None

    b.seat = SeatKind.CHIEF
    world_shares(world)
    assert world.hegemony.flags["a"] >= 2 and world.hegemony.countdown_nation == "a"


# --- regression cooldown and the crowd floor -------------------------------------


def _revolting_nation() -> tuple[World, Nation]:
    loc = Location(id="l", terrain=Terrain.PLAINS, nation="n")
    loc.records.append(Record(cls=ClassId.TENANTS, location="l", size=100.0))
    nation = Nation(id="n", seat=SeatKind.STATE, scalars=NationScalars())
    world = _world(nations={"n": nation}, locations={"l": loc})
    return world, nation


def test_regression_does_not_refire_within_its_cooldown() -> None:
    from stock.meta.regression import check_and_resolve
    from stock.sim.ledger import EventRecord

    world, nation = _revolting_nation()
    params = world.params.regression
    assert world.ledger is not None
    world.ledger.add_event(EventRecord(year=0, nation="n", kind="revolt", numbers={"size": 100.0}))
    assert check_and_resolve(nation, world, params)
    assert nation.scalars.last_regression_year == 0
    world.year = params.cooldown_years - 1
    world.ledger.add_event(EventRecord(year=world.year, nation="n", kind="revolt", numbers={"size": 100.0}))
    assert not check_and_resolve(nation, world, params)
    world.year = params.cooldown_years
    world.ledger.add_event(EventRecord(year=world.year, nation="n", kind="revolt", numbers={"size": 100.0}))
    assert check_and_resolve(nation, world, params)
    assert nation.scalars.regressions == 2


def test_a_record_too_small_to_be_a_crowd_fires_no_event() -> None:
    from stock.politics.unrest import step_unrest

    world, nation = _revolting_nation()
    loc = nation.locations(world)[0]
    crowd = loc.records[0]
    crowd.A[Tier.SUBSISTENCE] = 0.0
    crowd.E[Tier.SUBSISTENCE] = 10.0
    speck = Record(cls=ClassId.COLLECTORS, location="l", size=1.0)
    speck.A[Tier.SUBSISTENCE] = 0.0
    speck.E[Tier.SUBSISTENCE] = 10.0
    loc.records.append(speck)
    step_unrest(world)
    assert world.ledger is not None
    events = [e for e in world.ledger.events_in_year(0) if e.kind in ("strike", "riot", "revolt")]
    assert events, "the crowd itself should still fire"
    assert all(e.numbers["size"] >= world.params.unrest.event_min_share * 101.0 for e in events)
    assert nation.scalars.U_dis > 0
    # The speck is still classified — its strike years keep counting (engine/wages.py reads them).
    assert speck.strike_years == 1 and crowd.strike_years == 1
