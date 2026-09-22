"""Doc 07 additions: the procedural name register and the plain-English label table.

Names: unique within a world, deterministic across loads of the same map, terrain-
appropriate, and never a raw id. Labels: every enum member the screen can show has
one, and no label or name carries a forbidden token (the in-game text rule)."""

from __future__ import annotations

import pytest

from stock.core.world import Terrain
from stock.sim.scenario import load_scenario
from stock.ui import labels as L
from stock.ui.names import NATION_NAMES, RIVER_NAMES, TERRITORY_NAMES, NameRegister, names_for
from stock.ui.strings import check_forbidden

SCENARIO = "tests/scenarios/three_bands_ai.yaml"


def test_names_are_unique_and_never_ids() -> None:
    world = load_scenario(SCENARIO)
    reg = NameRegister(world)
    all_names = list(reg.locations.values()) + list(reg.nations.values())
    assert len(all_names) == len(set(all_names))
    for lid, name in reg.locations.items():
        assert name != lid and name
    for nid, name in reg.nations.items():
        assert name != nid and name


def test_names_are_deterministic_for_the_same_map() -> None:
    a = NameRegister(load_scenario(SCENARIO))
    b = NameRegister(load_scenario("tests/scenarios/late_start.yaml"))  # same ids, other seed
    assert a.locations == b.locations
    assert a.nations == b.nations


def test_territory_names_come_from_their_terrain_pool() -> None:
    world = load_scenario(SCENARIO)
    reg = NameRegister(world)
    for lid, loc in world.locations.items():
        name = reg.locations[lid]
        pool = set(TERRITORY_NAMES[loc.terrain.name])
        if loc.river and not loc.coast:
            pool |= set(RIVER_NAMES)
        assert name in pool, (lid, name)


def test_authored_scenario_names_win() -> None:
    world = load_scenario(SCENARIO)
    world.locations["valley_1"].name = "Home Field"
    world.nations["nation_valley"].name = "The Test Realm"
    reg = NameRegister(world)
    assert reg.locations["valley_1"] == "Home Field"
    assert reg.nations["nation_valley"] == "The Test Realm"


def test_register_serves_maps_larger_than_the_pools() -> None:
    from stock.core.world import Location, Nation, World
    from stock.sim.ledger import Ledger
    from stock.sim.rng import make_rng

    locations = {f"steppe_{i}": Location(id=f"steppe_{i}", terrain=Terrain.STEPPE) for i in range(60)}
    nations = {f"n{i}": Nation(id=f"n{i}") for i in range(60)}
    world = World(
        year=0, nations=nations, locations=locations, hostility={}, ledger=Ledger(), rng=make_rng(0)
    )
    reg = NameRegister(world)
    assert len(set(reg.locations.values())) == 60
    assert len(set(reg.nations.values())) == 60
    assert len(NATION_NAMES) < 60  # the compositional fallback was exercised


def test_names_for_caches_per_world_and_sees_authored_names() -> None:
    world = load_scenario(SCENARIO)
    assert names_for(world) is names_for(world)
    world.locations["valley_1"].name = "Home Field"
    assert names_for(world).location("valley_1") == "Home Field"


@pytest.mark.parametrize("group,enum", sorted(L.LABELLED_ENUMS.items()))
def test_every_enum_member_has_a_label(group: str, enum: type) -> None:
    table = L.LABELS[group.split(":")[0]]
    for member in enum:  # type: ignore[attr-defined]
        assert member.name in table, f"{group}.{member.name} has no label"


def test_no_label_or_name_carries_a_forbidden_token() -> None:
    for table in L.LABELS.values():
        for text in table.values():
            check_forbidden(text)
    for text in NATION_NAMES + RIVER_NAMES:
        check_forbidden(text)
    for pool in TERRITORY_NAMES.values():
        for text in pool:
            check_forbidden(text)
    from stock.ui.names import _ENDINGS, _NATION_ENDINGS, _STEMS

    for text in _STEMS + _NATION_ENDINGS + tuple(e for ends in _ENDINGS.values() for e in ends):
        check_forbidden(text)


def test_law_label_names_dynamic_trade_laws() -> None:
    assert L.law_label("TARIFF_WARES") == "Tariff on wares"
    assert L.law_label("BOUNTY_SHIPS") == "Bounty on ships"
    assert L.law_label("PROHIBITION_LUXURIES") == "Prohibition of luxuries"
    assert L.label("class", "HERD_OWNERS") == "Herd owners"
    assert L.label("symbol", "A_S") == "State authority"
    assert L.humanize("SOME_NEW_THING") == "Some new thing"


def test_describe_action_uses_display_names() -> None:
    world = load_scenario(SCENARIO)
    reg = NameRegister(world)
    text = L.describe_action("BAND_MOVE", {"to": "valley_2"}, reg)
    assert text == f"Move to {reg.locations['valley_2']}"
    text = L.describe_action("DECLARE_WAR", {"target": "nation_steppe"}, reg)
    assert text == f"Declare war · {reg.nations['nation_steppe']}"
    assert L.describe_action("ENACT", {"law": "ENCLOSURE"}, reg) == "Enact Enclosure"


# --- tooltips (stock/ui/help.py) ---------------------------------------------------


def test_help_covers_every_law_action_and_enum_it_names() -> None:
    from stock.core.actions import ActionKind
    from stock.core.laws import FocusKind, LawId
    from stock.security.military import Doctrine
    from stock.trade.treaties import TermKind
    from stock.ui.help import help_tables

    tables = help_tables()
    for law in LawId:
        assert tables["law"][law.name], law.name
    assert tables["law"]["SERFDOM"].endswith("interest.")  # the politics sentence is appended
    for kind in ActionKind:
        assert tables["action"][kind.name], kind.name
    assert set(tables["focus"]) == {f.name for f in FocusKind}
    assert set(tables["term"]) == {t.name for t in TermKind}
    assert set(tables["doctrine"]) == {d.name for d in Doctrine}
    assert set(tables["seat"]) == {"BAND", "CHIEF", "STATE"}
    assert set(tables["budget"]) == set(L.LABELS["budget"])
    assert set(tables["debt_policy"]) == set(L.LABELS["debt_policy"])
    assert set(tables["funding_mode"]) == set(L.LABELS["funding_mode"])


def test_help_text_obeys_the_in_game_text_rule() -> None:
    from stock.ui.help import help_tables, law_help

    for table in help_tables().values():
        for text in table.values():
            check_forbidden(text)
    assert law_help("TARIFF_WARES").startswith("A duty")
    assert law_help("NOT_A_LAW") == ""
