"""Scenario loading: map + nations + params override + seed -> a `World` (Doc 01)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from stock.core.params import Params, ParamsError
from stock.core.records import ClassId, Record, Wealth
from stock.core.world import (
    Capacity,
    HegemonyState,
    Location,
    Market,
    Nation,
    NationScalars,
    Resources,
    SeatKind,
    Terrain,
    World,
)
from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng


class ScenarioError(ValueError):
    pass


def _location_from_dict(data: dict[str, Any]) -> Location:
    known = {
        "id",
        "terrain",
        "resources",
        "capacity",
        "neighbours",
        "river",
        "coast",
        "roads",
        "x",
        "y",
        "name",
    }
    unknown = set(data) - known
    if unknown:
        raise ScenarioError(f"location {data.get('id')!r}: unknown key(s) {sorted(unknown)}")

    try:
        terrain = Terrain[data.get("terrain", "PLAINS").upper()]
    except KeyError as exc:
        raise ScenarioError(f"location {data.get('id')!r}: unknown terrain {data.get('terrain')!r}") from exc

    resources_data = dict(data.get("resources", {}))
    resources = Resources(**resources_data)
    capacity = Capacity(**dict(data.get("capacity", {})))

    return Location(
        id=data["id"],
        terrain=terrain,
        resources=resources,
        capacity=capacity,
        neighbours=dict(data.get("neighbours", {})),
        river=bool(data.get("river", False)),
        coast=bool(data.get("coast", False)),
        roads=dict(data.get("roads", {})),
        market=Market(),
        x=None if data.get("x") is None else float(data["x"]),
        y=None if data.get("y") is None else float(data["y"]),
        name=None if data.get("name") is None else str(data["name"]),
    )


def _nation_from_dict(data: dict[str, Any], locations: dict[str, Location]) -> Nation:
    known = {"id", "start_location", "start_size", "ai", "name"}
    unknown = set(data) - known
    if unknown:
        raise ScenarioError(f"nation {data.get('id')!r}: unknown key(s) {sorted(unknown)}")

    nation_id = data["id"]
    start_location = data["start_location"]
    if start_location not in locations:
        raise ScenarioError(f"nation {nation_id!r}: unknown start_location {start_location!r}")

    nation = Nation(
        id=nation_id,
        seat=SeatKind.BAND,
        scalars=NationScalars(A_S=1.0),  # band consensus C0 default (DD §7.3 handover)
        ai=data.get("ai"),
        name=None if data.get("name") is None else str(data["name"]),
    )
    start_size = float(data.get("start_size", 20.0))
    band = Record(
        cls=ClassId.HUNTERS,
        location=start_location,
        size=start_size,
        wealth=Wealth(),
        walk_away=1.0,
    )
    loc = locations[start_location]
    if loc.nation is not None:
        raise ScenarioError(
            f"location {start_location!r} claimed by both {loc.nation!r} and {nation_id!r}"
        )
    loc.nation = nation_id
    loc.records.append(band)
    return nation


def load_scenario(path: str | Path) -> World:
    """A scenario YAML file -> `World`; or, for `random[:seed[:locations[:nations]]]`,
    a procedurally generated one (`sim.worldgen`)."""

    from stock.sim.worldgen import generate_scenario, parse_random_spec

    if isinstance(path, str):
        config = parse_random_spec(path)
        if config is not None:
            return world_from_dict(generate_scenario(config))
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return world_from_dict(raw)


def world_from_dict(raw: dict[str, Any]) -> World:
    """The scenario mapping (a YAML file's contents, or `worldgen.generate_scenario`'s
    output) -> a validated `World`."""

    known_top = {"seed", "params_override", "locations", "nations"}
    unknown_top = set(raw) - known_top
    if unknown_top:
        raise ScenarioError(f"unknown top-level key(s) {sorted(unknown_top)}")

    seed = int(raw.get("seed", 0))
    try:
        params = Params.from_dict(raw.get("params_override", {}) or {})
    except ParamsError as exc:
        raise ScenarioError(f"params_override: {exc}") from exc

    locations: dict[str, Location] = {}
    for loc_data in raw.get("locations", []):
        loc = _location_from_dict(loc_data)
        if loc.id in locations:
            raise ScenarioError(f"duplicate location id {loc.id!r}")
        locations[loc.id] = loc

    for loc in locations.values():
        for neighbour_id in loc.neighbours:
            if neighbour_id not in locations:
                raise ScenarioError(f"location {loc.id!r}: unknown neighbour {neighbour_id!r}")

    nations: dict[str, Nation] = {}
    for nation_data in raw.get("nations", []):
        nation = _nation_from_dict(nation_data, locations)
        if nation.id in nations:
            raise ScenarioError(f"duplicate nation id {nation.id!r}")
        nations[nation.id] = nation

    world = World(
        year=0,
        nations=nations,
        locations=locations,
        hostility={},
        hegemony=HegemonyState(),
        ledger=Ledger(),
        rng=make_rng(seed),
        params=params,
    )
    world.validate()
    return world
