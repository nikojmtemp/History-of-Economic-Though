"""Content tables and starting numbers (design doc §5, §9, §12, §13, §20).

Everything a designer tunes lives here: terrain yields, works, discoveries,
institutions, and the constants of the model. Engine modules read these tables and
hold no literal numbers of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- turns and calendar (§4.1) -----------------------------------------------------------

LAST_TURN = 150
START_YEAR = -1500  # flavour only


def year_of(turn: int) -> int:
    """Calendar year at the start of `turn` (20 / 10 / 5 years per turn)."""

    year = START_YEAR
    for t in range(1, turn):
        year += 20 if t <= 40 else 10 if t <= 90 else 5
    return year


# --- terrain (§5.1) ------------------------------------------------------------------------


@dataclass(frozen=True)
class Terrain:
    name: str
    game: float
    grazing: float
    arable: float
    defence: float
    rough: bool = False
    fish: float = 0.0


TERRAIN: dict[str, Terrain] = {
    "FOREST": Terrain("Forest", game=1.3, grazing=0.3, arable=0.3, defence=1.2),
    "GRASSLAND": Terrain("Grassland", game=1.0, grazing=1.0, arable=0.45, defence=1.0),
    "VALLEY": Terrain("River valley", game=0.6, grazing=0.6, arable=1.25, defence=1.0),
    "HILLS": Terrain("Hills", game=0.9, grazing=0.7, arable=0.3, defence=1.3),
    "COAST": Terrain("Coast", game=0.5, grazing=0.3, arable=0.75, defence=1.0, fish=0.5),
    "MARSH": Terrain("Marsh", game=0.6, grazing=0.2, arable=0.0, defence=1.3, rough=True),
    "MOUNTAIN": Terrain("Mountain", game=0.4, grazing=0.2, arable=0.0, defence=1.5, rough=True),
}

FEATURES = ("wild_herds", "rare", "ore", "coal")

# --- goods and prices (§9.1, §9.8) ------------------------------------------------------

GOODS = ("food", "wares", "luxuries")
BASE_PRICE = {"food": 1.0, "wares": 2.0, "luxuries": 6.0}
PRICE_ELASTICITY = 0.7
PRICE_CLAMP = (0.25, 4.0)
STORE_DECAY = {"food": 0.3, "wares": 0.1, "luxuries": 0.1}

# --- the band, hunting, herds (§20) --------------------------------------------------------

START_HANDS = 5.0
START_FOOD = 10.0
START_SWAY = 20.0
HUNT_YIELD = 1.6
FISH_HANDS_CAP = 3.0  # hands per node that can fish
GAME_DEPLETION = 0.03  # per hunting hand, times the game level
GAME_REGEN = 0.08  # times (1 - game level)
FORAGE_YIELD = 0.5  # a hand with no work and no game
HERD_GROWTH = 0.12
HERD_CAP_PER_GRAZING = 60.0
HERDS_PER_FOOD = 5.0
HERDS_PER_HERDSMAN = 10.0
HERD_VALUE = 1.0  # baskets per head of herd, for produce and capital
TAME_HERDS = 10.0
BAND_MOVES = 1
HORDE_MOVES = 2
MIN_UNIT_HANDS = 2.0

# --- works (§9.2, §20) -----------------------------------------------------------------------


@dataclass(frozen=True)
class Work:
    key: str
    name: str
    needs: str | None  # discovery
    jobs: int
    cost: float
    makes: dict[str, float]  # good -> quantity per filled job, before multipliers
    paid: str  # "land" (wages/profit/rent) | "stock" (wages/profit) | "none"
    site: str | None = None  # node requirement: arable|grazing|rare|coast|ore|mine
    public: bool = False  # paid from the Treasury instead of Stock
    dol: float = 0.0  # exponent on the division-of-labour multiplier
    description: str = ""


WORKS: dict[str, Work] = {
    w.key: w
    for w in (
        Work(
            "pasture",
            "Pasture",
            "taming",
            2,
            5.0,
            {},
            "land",
            site="grazing",
            description="Keeps herds on settled ground. Each herdsman tends 10 head; 5 head feed one.",
        ),
        Work(
            "fields",
            "Fields",
            "tillage",
            3,
            10.0,
            {"food": 1.8},
            "land",
            site="arable",
            description="Three jobs growing food. Yield follows the ground's arable quality.",
        ),
        Work(
            "workshop",
            "Workshop",
            "weaving",
            2,
            15.0,
            {"wares": 0.8},
            "stock",
            dol=0.5,
            description="Two craftsmen making wares, or luxuries on a node with a rare resource.",
        ),
        Work(
            "market",
            "Market Town",
            "fairs",
            2,
            25.0,
            {"wares": 0.3},
            "stock",
            description="Extent +3, Ingenuity +2, one more trade route.",
        ),
        Work(
            "port",
            "Port",
            "sail",
            2,
            30.0,
            {"food": 1.0},
            "stock",
            site="coast",
            description="Fishing fleets and a harbour: opens sea lanes and two route slots.",
        ),
        Work(
            "mine",
            "Mine",
            "metalworking",
            2,
            25.0,
            {"wares": 0.9},
            "land",
            site="mine",
            description="Ore or coal dug for wares and, later, arms.",
        ),
        Work(
            "fort",
            "Fort",
            "masonry",
            0,
            20.0,
            {},
            "none",
            public=True,
            description="Walls. Each level adds two turns to a siege.",
        ),
        Work(
            "manufactory",
            "Manufactory",
            "division",
            4,
            60.0,
            {"wares": 1.0},
            "stock",
            dol=1.0,
            description="Four labourers dividing one trade into many operations: output scales with Extent.",
        ),
        Work(
            "foundry",
            "Foundry",
            "firearms",
            2,
            40.0,
            {"wares": 0.4},
            "stock",
            description="Casts arms for musket regiments.",
        ),
        Work(
            "academy",
            "Academy",
            "instruction",
            1,
            30.0,
            {},
            "none",
            public=True,
            description="Ingenuity +3, and it offsets the dulling effect of divided labour.",
        ),
        Work(
            "bank",
            "Bank",
            "banking",
            1,
            50.0,
            {},
            "stock",
            description="Circulating capital: Stock grows 10% more each turn.",
        ),
    )
}
FIELD_JOB_ARABLE = True  # fields yield x terrain arable
WORK_SLOTS_BASE = 2
WORK_SLOTS_PER_HANDS = 4.0
WORK_SLOTS_MAX = 8
RARE_LUXURY_YIELD = 0.3  # luxuries per workshop job on a rare node
SERF_PRODUCTIVITY = 0.75

# --- extent and division of labour (§9.4) --------------------------------------------------

EXTENT_PER_MARKET_TOWN = 3.0
ROUTE_EXTENT_SHARE = 0.5
ROUTE_EXTENT_PER_CAPACITY = 10.0


def division_of_labour(extent: float, commerce_mode: bool) -> float:
    import math

    eff = extent * (2.0 if commerce_mode else 1.0)
    return max(1.0, min(4.0, 1.0 + 0.6 * math.log2(max(eff, 1e-9) / 8.0)))


# --- distribution, consumption, accumulation (§10, §9.6) -----------------------------------

R0 = 0.12
R_CLAMP = (0.03, 0.25)
BARGAIN_CLAMP = (0.0, 1.5)
SAVE_RATE = {"stock": 0.6, "proprietors": 0.18, "labour": 0.05}
LABOUR_SAVE_ABOVE = 1.2  # labour saves only from income above this many baskets per head
COMFORT_NEED = {"labour": 0.5, "proprietors": 1.0, "stock": 1.0}
STOCK_LUXURY_NEED = 0.3
TIER_WEIGHTS = (8.0, 2.0, 0.5)
EXPECT_UP, EXPECT_DOWN = 0.3, 0.1
VANITY_MIN, VANITY_MAX, VANITY_TURNS = 0.6, 1.6, 10
RETAINER_CAP_SHARE = 0.3
RETAINER_ADJUST = 0.5
PROPRIETOR_OWNER_SHARE = 0.05  # owners per hand on privately held land works
STOCK_OWNERS_PER_WORK = 0.25

# --- population (§20) ---------------------------------------------------------------------

GROWTH_PER_SURPLUS = 0.05
GROWTH_CLAMP = (-0.10, 0.05)
HIGH_WAGE_BONUS = 0.01

# --- the seat and sway (§7) --------------------------------------------------------------

SWAY_CAP = 100.0
SPLIT_COST = 5.0
SPLIT_COST_ELDERS = 3.0
FOUND_GOVERNMENT_COST = 20.0
RESTORE_COST = 30.0
FEAST_FOOD_PER_HAND = 0.5
FEAST_SWAY = 5.0
FEAST_COOLDOWN = 3
INSTITUTION_COOLDOWN = 5

# --- unrest (§10.4) ------------------------------------------------------------------------

UNREST_EVENT_MIN_SHARE = 0.03
UNREST_EVENT_MIN_HANDS = 2.0

# --- research (§12) ----------------------------------------------------------------------

ERA_COST = {1: 30.0, 2: 45.0, 3: 100.0, 4: 180.0}
DIFFUSION_PER_CONTACT = 0.10
DIFFUSION_PER_ROUTE = 0.10
DIFFUSION_MAX = 0.60

# --- state purse (§14) --------------------------------------------------------------------

TAX_RATES = {"light": 0.05, "moderate": 0.10, "heavy": 0.18}
TAX_UNREST = {"light": 0.0, "moderate": 5.0, "heavy": 15.0}
BUDGET_LINES = ("justice", "instruction", "court")
JUSTICE_COST_PER_10_HANDS = 2.0
INSTRUCTION_COST_PER_10_HANDS = 1.0
COURT_COST = 3.0

# --- modes (§8) ------------------------------------------------------------------------------

MODES = ("hunting", "pasturage", "agriculture", "commerce")
MODE_NAMES = {
    "hunting": "Hunting",
    "pasturage": "Pasturage",
    "agriculture": "Agriculture",
    "commerce": "Commerce",
}
MODE_LEAD = 1.10
MODE_STREAK = 3

# --- victory (§17) -----------------------------------------------------------------------

HEGEMONY_SHARE = 0.40
HEGEMONY_EARLIEST = 50
HEGEMONY_COUNTDOWN = 10
HEGEMONY_RESET_AFTER = 3
OPULENCE_POP_FLOOR = 0.25

# --- discoveries (§12.4) -----------------------------------------------------------------


@dataclass(frozen=True)
class Discovery:
    key: str
    name: str
    era: int
    lane: str  # subsistence | exchange | force | order
    requires: tuple[tuple[str, ...], ...]  # AND of OR-groups
    observation: tuple[str, float] | None  # (metric, threshold) that halves the cost
    observation_text: str
    unlocks: str
    quote: str = ""


def _d(
    key: str,
    name: str,
    era: int,
    lane: str,
    requires: tuple[tuple[str, ...], ...],
    observation: tuple[str, float] | None,
    obs_text: str,
    unlocks: str,
    quote: str = "",
) -> Discovery:
    return Discovery(key, name, era, lane, requires, observation, obs_text, unlocks, quote)


SMITH = "Adam Smith, The Wealth of Nations"

DISCOVERIES: dict[str, Discovery] = {
    d.key: d
    for d in (
        _d("tracking", "Tracking", 1, "subsistence", (), None, "", "Hunt, Move"),
        _d("kin", "Kin & Custom", 1, "order", (), None, "", "Customs"),
        _d(
            "taming",
            "Taming",
            1,
            "subsistence",
            (("tracking",),),
            ("followed_herds", 3),
            "Follow wild herds for 3 turns",
            "Tame (band becomes a horde), Pasture, Herds to the Tamer",
            "The second period of society, that of shepherds, admits of very great inequalities of fortune.",
        ),
        _d(
            "barter",
            "Barter",
            1,
            "exchange",
            (("kin",),),
            ("contacts", 1),
            "Meet another people",
            "Barter routes, Gift",
        ),
        _d(
            "ambush",
            "Ambush",
            1,
            "force",
            (("tracking",),),
            ("skirmishes_won", 1),
            "Win a skirmish",
            "Warbands +1 strength",
        ),
        _d(
            "fishing",
            "Fishing",
            1,
            "subsistence",
            (("tracking",),),
            ("on_coast", 1),
            "Camp a band on the coast",
            "Coast fishing doubled",
        ),
        _d(
            "elders",
            "Elders' Council",
            1,
            "order",
            (("kin",),),
            ("bands", 3),
            "Lead 3 bands",
            "Feasts +1 Sway; splitting a band costs 3",
        ),
        _d(
            "horsemanship",
            "Horsemanship",
            2,
            "force",
            (("taming",),),
            ("herds", 20),
            "Own 20 head of herds",
            "Hordes move 3",
            "A nation of hunters can never be formidable to the civilized nations in "
            "their neighbourhood. A nation of shepherds may.",
        ),
        _d(
            "weaving",
            "Weaving",
            2,
            "subsistence",
            (("taming", "barter"),),
            ("pastures", 1),
            "Keep a pasture or a horde",
            "Workshop",
        ),
        _d(
            "tillage",
            "Tillage",
            2,
            "subsistence",
            (("taming", "fishing"),),
            ("camped_arable", 1),
            "Camp a band on a river valley or coast",
            "Fields, Settle",
        ),
        _d(
            "chieftainship",
            "Chieftainship",
            2,
            "order",
            (("taming", "elders"),),
            ("proprietors", 1),
            "Have herd-owners or landowners",
            "Chiefdom verbs",
        ),
        _d(
            "tribute",
            "Tribute",
            2,
            "force",
            (("ambush", "chieftainship"),),
            ("raids_won", 1),
            "Win a raid",
            "Tribute peace terms",
        ),
        _d(
            "metalworking",
            "Metalworking",
            2,
            "subsistence",
            (("ambush", "weaving"),),
            ("own_ore", 1),
            "Hold a node with ore",
            "Mine",
        ),
        _d(
            "gifts",
            "Gift & Hostage",
            2,
            "exchange",
            (("barter",),),
            ("best_relations", 50),
            "Relations above 50 with anyone",
            "Non-aggression pacts",
        ),
        _d(
            "rotation",
            "Rotation",
            3,
            "subsistence",
            (("tillage",),),
            ("fields", 3),
            "Keep 3 Fields",
            "Fields +50%",
        ),
        _d(
            "land_tenure",
            "Land Tenure",
            3,
            "order",
            (("tillage",),),
            ("field_nodes", 3),
            "Fields on 3 nodes",
            "Entailed Land, Serfdom",
            "As soon as the land of any country has all become private property, the landlords, like all "
            "other men, love to reap where they never sowed.",
        ),
        _d(
            "magistracy",
            "Magistracy",
            3,
            "order",
            (("land_tenure", "chieftainship"),),
            ("proprietor_clout", 0.4),
            "Proprietors hold 40% of clout",
            "Civil Government: Treasury, taxes, justice",
            "Civil government, so far as it is instituted for the security of property, is in reality "
            "instituted for the defence of the rich against the poor.",
        ),
        _d(
            "masonry",
            "Masonry",
            3,
            "force",
            (("tillage", "metalworking"),),
            ("besieged", 1),
            "Suffer a siege",
            "Fort",
        ),
        _d(
            "feudal",
            "Feudal Tenure",
            3,
            "force",
            (("land_tenure",),),
            ("retainers", 5),
            "Keep 5 retainers",
            "Feudal Host",
        ),
        _d(
            "coinage",
            "Coinage",
            3,
            "exchange",
            (("metalworking", "gifts"),),
            ("routes", 2),
            "Hold 2 routes",
            "Customs, Tax Farming",
        ),
        _d(
            "fairs",
            "Fairs & Markets",
            3,
            "exchange",
            (("coinage", "weaving"),),
            ("extent", 20),
            "Extent of 20",
            "Market Town, Caravan",
            "The division of labour is limited by the extent of the market.",
        ),
        _d(
            "sail",
            "Sail",
            3,
            "subsistence",
            (("fishing", "weaving"),),
            ("own_coast", 1),
            "Settle a coast node",
            "Port, sea lanes",
        ),
        _d(
            "guilds",
            "Guilds",
            3,
            "order",
            (("weaving",),),
            ("workshops", 3),
            "Keep 3 Workshops",
            "Guilds",
            "People of the same trade seldom meet together, even for merriment and diversion, but the "
            "conversation ends in a conspiracy against the publick.",
        ),
        _d(
            "commutation",
            "Commutation",
            3,
            "order",
            (("land_tenure",), ("coinage",)),
            ("rent_share", 0.3),
            "Rent is 30% of produce",
            "Alienable Land, Free Labour, Land Tax",
        ),
        _d(
            "militia",
            "Militia Drill",
            3,
            "force",
            (("magistracy", "masonry"),),
            ("stock_share", 0.15),
            "Stock-holders are 15% of the people",
            "Militia",
        ),
        _d(
            "mercantile",
            "Mercantile System",
            3,
            "exchange",
            (("coinage",), ("magistracy",)),
            ("importing", 1),
            "Import a good",
            "Mercantile commerce, bounties",
        ),
        _d(
            "bills",
            "Bills of Exchange",
            4,
            "exchange",
            (("fairs",),),
            ("routes", 4),
            "Hold 4 routes",
            "Route capacity +50%",
        ),
        _d(
            "division",
            "Division of Labour",
            4,
            "subsistence",
            (("fairs", "guilds"),),
            ("extent", 40),
            "Extent of 40",
            "Manufactory",
            "The greatest improvement in the productive powers of labour ... seem to have been the effects "
            "of the division of labour.",
        ),
        _d(
            "navigation",
            "Navigation",
            4,
            "exchange",
            (("sail",),),
            ("ports", 2),
            "Keep 2 Ports",
            "Ocean lanes, Colonists",
        ),
        _d(
            "standing_army",
            "Standing Army",
            4,
            "force",
            (("militia",), ("magistracy",)),
            ("treasury", 50),
            "Treasury of 50",
            "Standing Army, Regiments",
            "It is only by means of a standing army ... that the civilization of any country can be "
            "perpetuated.",
        ),
        _d(
            "firearms",
            "Firearms",
            4,
            "force",
            (("standing_army", "militia"),),
            ("mines", 1),
            "Keep a Mine",
            "Foundry, Musket regiments",
        ),
        _d(
            "banking",
            "Banking",
            4,
            "exchange",
            (("bills",),),
            ("stock", 200),
            "Stock of 200",
            "Bank",
            "A sort of waggon-way through the air.",
        ),
        _d(
            "public_credit",
            "Public Credit",
            4,
            "order",
            (("banking", "mercantile"),),
            ("deficit", 1),
            "Run a deficit",
            "Public borrowing",
        ),
        _d(
            "liberty",
            "Natural Liberty",
            4,
            "order",
            (("division",), ("commutation",)),
            ("free_labour", 1),
            "Enact Free Labour",
            "Free Trade; institution changes cost 25% less Sway",
            "Led by an invisible hand to promote an end which was no part of his intention.",
        ),
        _d(
            "machinery",
            "Machinery",
            4,
            "subsistence",
            (("division",),),
            ("manufactories", 2),
            "Keep 2 Manufactories",
            "Manufactory +50%",
        ),
        _d(
            "instruction",
            "Public Instruction",
            4,
            "order",
            (("division", "guilds"),),
            ("stupefaction", 1),
            "Suffer the dulling of divided labour",
            "Academy, Instruction budget",
        ),
    )
}
START_DISCOVERIES = ("tracking", "kin")
LANES = ("subsistence", "exchange", "force", "order")

# --- institutions (§13) ---------------------------------------------------------------------


@dataclass(frozen=True)
class Option:
    key: str
    name: str
    needs: str | None  # discovery
    effect: str
    supports: tuple[str, ...] = ()
    opposes: tuple[str, ...] = ()
    state_only: bool = False


@dataclass(frozen=True)
class Pillar:
    key: str
    name: str
    options: tuple[Option, ...] = field(default_factory=tuple)

    def option(self, key: str) -> Option:
        for o in self.options:
            if o.key == key:
                return o
        raise KeyError(key)


PILLARS: dict[str, Pillar] = {
    p.key: p
    for p in (
        Pillar(
            "property",
            "Property",
            (
                Option(
                    "common",
                    "Common Use",
                    None,
                    "All produce goes to those who work it. No proprietors.",
                    ("labour",),
                ),
                Option(
                    "killer",
                    "Kill to the Killer",
                    None,
                    "Hunting +10%. Taking herds as property later costs half.",
                    (),
                    ("labour",),
                ),
                Option(
                    "herds",
                    "Herds to the Tamer",
                    "taming",
                    "Herds become the owners' stock: herd-owners take the increase. Herd growth +20%.",
                    ("proprietors",),
                    ("labour",),
                ),
                Option(
                    "entailed",
                    "Entailed Land",
                    "land_tenure",
                    "Rent goes to landowners. Land cannot be sold.",
                    ("proprietors",),
                    ("stock",),
                ),
                Option(
                    "alienable",
                    "Alienable Land",
                    "commutation",
                    "Stock may buy estates; improving owners raise field yields up to +25%. Security +0.1.",
                    ("stock",),
                    ("proprietors",),
                ),
            ),
        ),
        Pillar(
            "labour",
            "Labour",
            (
                Option(
                    "custom", "Kin & Custom", None, "Hands fill the oldest works first. No wage bargaining."
                ),
                Option(
                    "serfdom",
                    "Serfdom",
                    "land_tenure",
                    "Bound labour at 75% productivity. No migration, no manufactories. Rent +20%.",
                    ("proprietors",),
                    ("labour",),
                ),
                Option(
                    "guilds",
                    "Guilds",
                    "guilds",
                    "Workshops +20%. Craftsmen bargain harder. Manufactories cost double.",
                    ("stock",),
                    ("labour",),
                ),
                Option(
                    "free",
                    "Free Labour",
                    "commutation",
                    "Hands move to the best-paying work on their own. Full productivity.",
                    ("stock",),
                    ("proprietors",),
                ),
                Option(
                    "poor_laws",
                    "Free Labour + Poor Laws",
                    "commutation",
                    "As Free Labour, with a wage floor paid from rent. Migration halved.",
                    ("labour",),
                    ("proprietors",),
                ),
            ),
        ),
        Pillar(
            "commerce",
            "Commerce",
            (
                Option("barter", "Barter", None, "Barter routes only."),
                Option(
                    "tolls",
                    "Staples & Tolls",
                    "coinage",
                    "Treasury takes 10% of route profit. Route capacity -20%.",
                    ("proprietors",),
                    ("stock",),
                ),
                Option(
                    "mercantile",
                    "Mercantile System",
                    "mercantile",
                    "Imported wares and luxuries +30% price; the Treasury pays export bounties.",
                    ("stock",),
                    ("labour",),
                ),
                Option(
                    "free_trade",
                    "Free Trade",
                    "liberty",
                    "No tariffs. Route capacity +30%, Extent from routes x1.5.",
                    ("stock", "labour"),
                    ("proprietors",),
                ),
            ),
        ),
        Pillar(
            "revenue",
            "Revenue",
            (
                Option("plunder", "Gifts & Plunder", None, "No taxes: tribute and raids only."),
                Option(
                    "feudal_dues",
                    "Feudal Dues",
                    "magistracy",
                    "A tax on rent, collected by the lords. Half of it reaches the Treasury.",
                    ("proprietors",),
                    ("labour",),
                    state_only=True,
                ),
                Option(
                    "tax_farming",
                    "Tax Farming",
                    "coinage",
                    "Taxes on all income, sold to farmers who keep 30%. Unrest +10, Security -0.1.",
                    ("stock",),
                    ("labour",),
                    state_only=True,
                ),
                Option(
                    "excise",
                    "Excise on Necessaries",
                    "magistracy",
                    "A tax on food and wares. Labour passes part of it on through wages.",
                    (),
                    ("labour",),
                    state_only=True,
                ),
                Option(
                    "land_tax",
                    "Land Tax",
                    "commutation",
                    "A tax on rent. It cannot be shifted. 85% reaches the Treasury.",
                    ("stock", "labour"),
                    ("proprietors",),
                    state_only=True,
                ),
                Option(
                    "customs",
                    "Customs",
                    "coinage",
                    "A tax on trade routes.",
                    ("proprietors",),
                    ("stock",),
                    state_only=True,
                ),
            ),
        ),
        Pillar(
            "defence",
            "Defence",
            (
                Option("warriors", "Every Man a Warrior", None, "Warbands from any hands."),
                Option(
                    "nation_in_arms",
                    "Nation in Arms",
                    "taming",
                    "Hordes fight as they graze.",
                    ("proprietors",),
                ),
                Option(
                    "feudal_host",
                    "Feudal Host",
                    "feudal",
                    "Levies raised from retainers, free to the state, if the lords agree.",
                    ("proprietors",),
                    ("stock",),
                ),
                Option(
                    "militia",
                    "Militia",
                    "militia",
                    "Cheap part-time units.",
                    ("labour", "stock"),
                    ("proprietors",),
                ),
                Option(
                    "standing",
                    "Standing Army",
                    "standing_army",
                    "Regiments paid by the Treasury, improving with drill.",
                    ("stock",),
                    ("proprietors",),
                    state_only=True,
                ),
            ),
        ),
    )
}
START_INSTITUTIONS = {
    "property": "common",
    "labour": "custom",
    "commerce": "barter",
    "revenue": "plunder",
    "defence": "warriors",
}
PRIVATE_LAND = ("entailed", "alienable")
PRIVATE_HERDS = ("herds", "entailed", "alienable")
FREE_LABOUR = ("free", "poor_laws")

ORDERS = ("labour", "proprietors", "stock")
ORDER_NAMES = {"labour": "Labour", "proprietors": "Proprietors", "stock": "Stock-holders"}

# --- nations -------------------------------------------------------------------------------

NATION_COLOURS = ("#3B5B8C", "#8C4A3B", "#5B7A3B", "#7A5B8C", "#8C7A3B", "#3B7A8C")

MOMENT_QUOTES = {
    "first_herd": "The second period of society, that of shepherds, admits of very great inequalities "
    "of fortune.",
    "first_field": "Among nations of hunters, as there is scarce any property, ... there is seldom any "
    "established magistrate or any regular administration of justice.",
    "retainers_dismissed": "For a pair of diamond buckles perhaps, or for something as frivolous and "
    "useless, they exchanged the maintenance ... of a thousand men for a year.",
    "first_manufactory": "The greatest improvement in the productive powers of labour ... seem to have "
    "been the effects of the division of labour.",
    "first_town": "The division of labour is limited by the extent of the market.",
    "civil_government": "Civil government, so far as it is instituted for the security of property, is in "
    "reality instituted for the defence of the rich against the poor.",
    "mode_commerce": "Consumption is the sole end and purpose of all production.",
    "regression": "Capitals are increased by parsimony, and diminished by prodigality and misconduct.",
}
