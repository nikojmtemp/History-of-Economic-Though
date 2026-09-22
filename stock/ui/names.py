"""Display names for nations and territories (Doc 07, "legible and beautiful").

Scenario ids (`valley_1`, `nation_steppe`) are keys — they appear in `neighbours`,
route ids, `start_location`, war and treaty state, and every test — so they never
change. What the player reads instead is a *display name* drawn procedurally from the
pools below: a territory takes a name from its terrain's pool (a river or coast
biases the choice toward fords and havens), a nation takes a realm name, and both are
assigned deterministically per world — seeded from a digest of the scenario's ids, not
from `world.rng`, which stays reserved for the simulation — and without repetition, so
the same map always reads the same way and no two places share a name. An authored
`name:` in the scenario wins over the pool.

The pools are curated whole names first; when a pool runs dry the compositional
generator (`_coin`) joins a terrain-appropriate stem and ending, so any map size is
served. Names are labels, not prose: nothing here is a sentence, a verdict, or a
citation (the in-game text rule in Doc 00), and `tests/test_names.py` runs the
forbidden-token check over every pool.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable

from stock.core.world import World

#: Realm names for nations — a mix of peoples, houses, leagues and lands so that a
#: three-nation map never reads as three of the same thing.
NATION_NAMES: tuple[str, ...] = (
    "Ostrellin",
    "the Cairnfolk",
    "Vaelmark",
    "the Heron League",
    "Drossmere",
    "Karsholm",
    "the Fennish Host",
    "Isenvale",
    "the Marrowmen",
    "Quillon",
    "Sabrenne",
    "Tarrow",
    "the Ullswater Compact",
    "the Wend",
    "Ythe",
    "Brannock",
    "the Hollin Kin",
    "Morrowgate",
    "Sallowmark",
    "the Greywater Folk",
    "Aubrenne",
    "Cinderhold",
    "the Oxbow Clans",
    "Pellam",
    "Rooksmoor",
    "the Thorn Assembly",
    "Vantery",
    "Wexley",
    "the Halloran",
    "Ilmarrow",
    "Kestrelmark",
    "Lorne",
    "the Ninefold",
    "Orrinshaw",
    "the Pale Concord",
    "Ravensk",
    "Sundermere",
    "Tollivant",
    "Umberlin",
    "the Weald Compact",
    "Hadrell",
    "the Saltwise",
    "Corvenne",
    "Estmoor",
    "the Long Hundred",
    "Gallowmere",
    "Nithering",
    "the Ashfolk",
)

#: Territory names by terrain (keys are `Terrain` member names).
TERRITORY_NAMES: dict[str, tuple[str, ...]] = {
    "PLAINS": (
        "Aldmere",
        "Whitfold",
        "Oxenhale",
        "Barrowfield",
        "Cornhallow",
        "Lindley Flats",
        "Mereton",
        "Harrowgate",
        "Fallowmead",
        "Goldacre",
        "Wheatstead",
        "Hollowfield",
        "Thistlemere",
        "Kingsmead",
        "Elderwick",
        "Broadacre",
        "Sheafton",
        "Lammastide",
        "Threshingham",
        "Furlong Cross",
    ),
    "HILLS": (
        "Cairnside",
        "Hollin Rise",
        "Thornhowe",
        "Greyridge",
        "Wethercote",
        "Barrowdown",
        "Ellsworth Tor",
        "Ravenscar",
        "Highcombe",
        "Copperknoll",
        "Windcote",
        "Beacon Hill",
        "Stonecroft",
        "Harthill",
        "Wolds End",
        "Shepherd's Howe",
        "Longbarrow",
        "Foxcombe",
        "Bleakridge",
        "Tarnhow",
    ),
    "FOREST": (
        "Blackholt",
        "Thornwald",
        "Hazelhurst",
        "Ashenshaw",
        "Deepwood",
        "Wolfden",
        "Kingsholt",
        "Elmshaw",
        "Foxhollow",
        "Ravenwood",
        "Oakenhurst",
        "Mirkwold",
        "Boarsgrove",
        "Yewshade",
        "Bramblewick",
        "Hartswood",
        "Charcoal Reach",
        "Owlhurst",
        "Hollowbeech",
        "Wardenwood",
    ),
    "MOUNTAIN": (
        "Ironcrag",
        "Grimfell",
        "Coldspire",
        "Adamant Pass",
        "Skarrow Peak",
        "Hollow Tor",
        "Ormscar",
        "Frostgate",
        "Stonecleft",
        "Blackspur",
        "Kestrel Crag",
        "Duncairn",
        "Thunderfell",
        "Ravenspire",
        "Greyhorn",
        "Sablecrag",
        "the Anvil",
        "Nethercleft",
        "Wolfscar",
        "Hoarfell",
    ),
    "STEPPE": (
        "Windmoor",
        "Harrowheath",
        "Longgrass",
        "the Wide Marches",
        "Saltmoor",
        "Hoofmere",
        "Kessendale",
        "Ashplain",
        "Bittergrass",
        "Vastheath",
        "Tallowmoor",
        "Drumhollow",
        "Wildmark",
        "Foalsmoor",
        "Sunderreach",
        "Roansweep",
        "the Open Shires",
        "Dunmoor",
        "Skylark Downs",
        "Brackenheath",
    ),
    "WETLAND": (
        "Reedfen",
        "Eelmarsh",
        "Sallowcarr",
        "Mistmoor",
        "Blackfen",
        "Willowsedge",
        "Heronmere",
        "Tarnwater",
        "Fenmouth",
        "Bogholm",
        "Sedgewick",
        "Quagmere",
        "Rushford",
        "Marshgate",
        "Crakefen",
        "Otterholm",
        "the Sinks",
        "Mireside",
        "Duckling Fen",
        "Peatmoor",
    ),
    "COASTAL_PLAIN": (
        "Saltholm",
        "Gullhaven",
        "Whitesand",
        "Kelpmouth",
        "Fairharbour",
        "Nethercove",
        "Brinewick",
        "Seaford",
        "Tidemark",
        "Sternness",
        "Cockle Strand",
        "Wrackhaven",
        "Longstrand",
        "Shellmere",
        "Herringcove",
        "Greyshoal",
        "Dunwich Point",
        "Oysterhithe",
        "Lanternness",
        "Wavecombe",
    ),
}

#: A river biases a territory toward a crossing or a water name, whatever its terrain.
RIVER_NAMES: tuple[str, ...] = (
    "Sheafford",
    "Brightwater",
    "Sallowford",
    "Ashbridge",
    "Weirstead",
    "Millwater",
    "Eelbrook",
    "Otterford",
    "Reedham",
    "Kingsweir",
    "Longreach",
    "Silverbend",
    "Fordingham",
    "Stonebridge",
    "Ferryfold",
    "Oxbow Ford",
)

#: Compositional fallback: stems and terrain-appropriate endings, joined when a pool
#: is exhausted. Endings carry the terrain's flavour; stems are shared.
_STEMS: tuple[str, ...] = (
    "Ash",
    "Elder",
    "Grey",
    "Black",
    "White",
    "High",
    "Nether",
    "Wester",
    "Norther",
    "Cold",
    "Oaken",
    "Raven",
    "Wolf",
    "Hart",
    "Fox",
    "King's",
    "Salt",
    "Thorn",
    "Bright",
    "Hollow",
    "Broad",
    "Long",
    "Sunder",
    "Wind",
)
_ENDINGS: dict[str, tuple[str, ...]] = {
    "PLAINS": ("mead", "field", "acre", "stead", "ton", "wick", "mere"),
    "HILLS": ("howe", "down", "ridge", "combe", "knoll", "tor", "cote"),
    "FOREST": ("holt", "hurst", "wold", "shaw", "wood", "grove", "den"),
    "MOUNTAIN": ("crag", "fell", "spire", "scar", "cleft", "gate", "horn"),
    "STEPPE": ("moor", "heath", "mark", "reach", "sweep", "plain", "downs"),
    "WETLAND": ("fen", "marsh", "carr", "mere", "holm", "sedge", "mire"),
    "COASTAL_PLAIN": ("haven", "strand", "cove", "ness", "mouth", "hithe", "shoal"),
}
_NATION_ENDINGS: tuple[str, ...] = ("mark", "holm", "vale", "shire", "gate", "mere", "reach")


def _seed(parts: Iterable[str]) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _coin(rng: random.Random, stems: tuple[str, ...], endings: tuple[str, ...], taken: set[str]) -> str:
    """A fresh compositional name; tries a few hundred stem+ending pairs before
    numbering, so a very large map still gets unique names."""

    for _ in range(400):
        candidate = rng.choice(stems) + rng.choice(endings)
        if candidate not in taken:
            return candidate
    n = 2
    base = rng.choice(stems) + rng.choice(endings)
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


class NameRegister:
    """id -> display name for one world's locations and nations (see module docstring)."""

    def __init__(self, world: World) -> None:
        loc_ids = sorted(world.locations)
        nation_ids = sorted(world.nations)
        rng = random.Random(_seed(["names", *loc_ids, "#", *nation_ids]))
        taken: set[str] = set()

        pools: dict[str, list[str]] = {t: list(names) for t, names in TERRITORY_NAMES.items()}
        for names in pools.values():
            rng.shuffle(names)
        river_pool = list(RIVER_NAMES)
        rng.shuffle(river_pool)

        self.locations: dict[str, str] = {}
        for lid in loc_ids:
            loc = world.locations[lid]
            authored = loc.name
            if authored:
                name = authored
            else:
                terrain = loc.terrain.name
                candidate: str | None = None
                # A river crossing on a non-coastal plain reads as a ford; try that pool
                # first (roughly every other river location) so valleys aren't all -mead.
                if loc.river and not loc.coast and river_pool and rng.random() < 0.5:
                    candidate = river_pool.pop()
                pool = pools.setdefault(terrain, [])
                while candidate is None or candidate in taken:
                    candidate = pool.pop() if pool else None
                    if candidate is None:
                        candidate = _coin(rng, _STEMS, _ENDINGS.get(terrain, _ENDINGS["PLAINS"]), taken)
                name = candidate
            taken.add(name)
            self.locations[lid] = name

        realm_pool = list(NATION_NAMES)
        rng.shuffle(realm_pool)
        self.nations: dict[str, str] = {}
        for nid in nation_ids:
            realm: str | None = world.nations[nid].name or None
            while realm is None or realm in taken:
                realm = realm_pool.pop() if realm_pool else _coin(rng, _STEMS, _NATION_ENDINGS, taken)
            taken.add(realm)
            self.nations[nid] = realm

    def location(self, loc_id: str | None) -> str:
        if loc_id is None:
            return ""
        return self.locations.get(loc_id, loc_id)

    def nation(self, nation_id: str | None) -> str:
        if nation_id is None:
            return ""
        return self.nations.get(nation_id, nation_id)


_registers: dict[int, tuple[tuple[str, ...], NameRegister]] = {}


def _signature(world: World) -> tuple[str, ...]:
    return tuple(
        [f"{lid}={loc.name}" for lid, loc in sorted(world.locations.items())]
        + ["#"]
        + [f"{nid}={n.name}" for nid, n in sorted(world.nations.items())]
    )


def names_for(world: World) -> NameRegister:
    """The register for this world, built once per `World` object and rebuilt if its
    ids or authored names change (names never change during a run; a new scenario
    load gets its own)."""

    key = id(world)
    signature = _signature(world)
    cached = _registers.get(key)
    if cached is None or cached[0] != signature:
        reg = NameRegister(world)
        _registers.clear()
        _registers[key] = (signature, reg)
        return reg
    return cached[1]
