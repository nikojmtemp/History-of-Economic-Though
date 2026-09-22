"""Display names for nodes and nations (design doc §19): drawn from curated pools by
terrain, then coined from stems and endings when a pool runs dry. Deterministic per
world seed, never repeated within a world, and seeded apart from the simulation RNG."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable
from dataclasses import dataclass, field

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


#: New terrain keys -> the name pools above.
_POOL_FOR = {
    "FOREST": "FOREST",
    "GRASSLAND": "STEPPE",
    "VALLEY": "PLAINS",
    "HILLS": "HILLS",
    "COAST": "COASTAL_PLAIN",
    "MARSH": "WETLAND",
    "MOUNTAIN": "MOUNTAIN",
}


@dataclass
class Names:
    nodes: dict[str, str] = field(default_factory=dict)
    nations: list[str] = field(default_factory=list)


def assign_names(seed: int, nodes: list[tuple[str, str, bool]], nations: int) -> Names:
    """`nodes` is (id, terrain, on_river) per node."""

    rng = random.Random(_seed(["names", str(seed), *(n[0] for n in nodes)]))
    taken: set[str] = set()
    pools: dict[str, list[str]] = {t: list(names) for t, names in TERRITORY_NAMES.items()}
    for names in pools.values():
        rng.shuffle(names)
    river_pool = list(RIVER_NAMES)
    rng.shuffle(river_pool)
    out = Names()
    for node_id, terrain, river in nodes:
        key = _POOL_FOR.get(terrain, "PLAINS")
        candidate: str | None = None
        if river and terrain != "COAST" and river_pool and rng.random() < 0.5:
            candidate = river_pool.pop()
        pool = pools.setdefault(key, [])
        while candidate is None or candidate in taken:
            candidate = pool.pop() if pool else None
            if candidate is None:
                candidate = _coin(rng, _STEMS, _ENDINGS.get(key, _ENDINGS["PLAINS"]), taken)
        taken.add(candidate)
        out.nodes[node_id] = candidate
    realms = list(NATION_NAMES)
    rng.shuffle(realms)
    for _ in range(nations):
        realm: str | None = None
        while realm is None or realm in taken:
            realm = realms.pop() if realms else _coin(rng, _STEMS, _NATION_ENDINGS, taken)
        taken.add(realm)
        out.nations.append(realm)
    return out
