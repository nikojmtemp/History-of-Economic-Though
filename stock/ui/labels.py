"""Plain-English labels for everything the screen names (Doc 07).

Doc 00 keeps the model's symbols in code (`A_S`, `N_bar`, `r_bar`, `PSV`, ...) and
the engine's enums in SHOUTING_CASE (`HERD_OWNERS`, `KILL_TO_KILLER`). None of that
is fit to read, so this module is the one place a symbol or an enum member becomes
words: a `Snapshot` carries the whole table (`Snapshot.labels`) and the JS looks up
`labels[group][key]`, falling back to a humanised key. Labels are labels — a noun
phrase, never a sentence or a verdict — and `tests/test_labels.py` runs the
forbidden-token check over every entry and checks every enum the engine exposes has one.
"""

from __future__ import annotations

from typing import Any

from stock.core.goods import Good, Tier
from stock.core.laws import FocusKind, LawBranch, LawId
from stock.core.producers import MethodId, ProducerKind
from stock.core.records import ClassId, InterestId
from stock.core.trees import CreditNode, DefenceNode, TreeINode
from stock.core.world import SeatKind, Terrain

#: Model symbols and scalar keys -> what the number is.
SYMBOLS: dict[str, str] = {
    "A_S": "State authority",
    "consensus": "Consensus",
    "N_bar": "Perceived security",
    "N_r": "Net security",
    "PSV": "Felt protection",
    "PTV_ext": "Foreign threat",
    "PTV_int": "Internal threat",
    "M": "Military strength",
    "M_state": "State's own strength",
    "r_bar": "Average profit rate",
    "r_market": "Market interest",
    "r_legal": "Legal interest cap",
    "r_sovereign": "Sovereign's borrowing rate",
    "J": "Justice",
    "V": "Output value",
    "U": "Unrest",
    "U_dis": "Disorder",
    "O": "Order signal",
    "hoard": "Hoard",
    "walk_away": "Walk-away",
    "authority": "Authority",
    "radicalism": "Radicalism",
    "size": "People",
    "wealth": "Wealth",
    "stock": "Stock in place",
    "jobs": "Jobs",
    "produce_per_head": "Produce per head",
    "labour_share": "Labour share",
    "freedom_index": "Freedom index",
    "capital_share": "Share of world capital",
    "consumption_share": "Share of world consumption",
    "production_share": "Share of world output",
    "treasure": "Treasury",
    "debt": "Public debt",
    "revenue": "Revenue",
    "enforcement": "Enforcement",
    "support": "Support",
    "opposition": "Opposition",
    "cost": "Cost",
    "available": "Available",
    "shortfall": "Shortfall",
    "ground_quality": "Ground",
    "population": "Population",
    "depletion": "Depletion",
    "hostility": "Hostility",
    "distance": "Distance",
    "capacity": "Capacity",
    "volume": "Volume",
    "customs": "Customs",
    "gap": "Price gap",
    "collected": "Collected",
    "draw": "Draw",
    "rate": "Rate",
    "progress": "Progress",
    "upkeep": "Upkeep",
}

CLASSES: dict[str, str] = {
    "HUNTERS": "Hunters",
    "HERD_OWNERS": "Herd owners",
    "HERDSMEN": "Herdsmen",
    "LANDLORDS": "Landlords",
    "CLERGY": "Clergy",
    "SERFS": "Serfs",
    "RETAINERS": "Retainers",
    "CRAFTSMEN": "Craftsmen",
    "TENANTS": "Tenant farmers",
    "MERCHANTS": "Merchants",
    "CAPITALISTS": "Capitalists",
    "LABOURERS": "Labourers",
    "SERVANTS": "Servants",
    "SOLDIERS": "Soldiers",
    "COLLECTORS": "Tax collectors",
    "STATE": "The State",
}

INTERESTS: dict[str, str] = {
    "LANDED": "Landed interest",
    "INDUSTRIAL": "Industrial interest",
    "MERCHANT": "Merchant interest",
    "MONEYED": "Moneyed interest",
    "LABOUR": "Labour interest",
}

LAWS: dict[str, str] = {
    "KILL_TO_KILLER": "The kill to the killer",
    "SHARED_BY_CUSTOM": "Sharing by custom",
    "TAMED_ANIMAL_TO_TAMER": "The tamed animal to the tamer",
    "PROTECTION_OF_PROPERTY": "Protection of property",
    "HERDS_HERITABLE": "Heritable herds",
    "LAND_OWNABLE": "Land as property",
    "PRIMOGENITURE": "Primogeniture",
    "ALIENABLE": "Land freely sold",
    "STOCK_SEPARABLE": "Stock separate from land",
    "SERFDOM": "Serfdom",
    "COMMUTATION": "Commutation of services",
    "ENCLOSURE": "Enclosure",
    "SETTLEMENT_LAW": "Law of settlement",
    "APPRENTICESHIP": "Statute of apprentices",
    "GUILD_CHARTER": "Guild charter",
    "COMBINATION_ACT": "Combination act",
    "FREE_TRADE": "Free trade",
    "NAVIGATION_ACT": "Navigation act",
    "CHARTERED_COMPANY": "Chartered company",
    "LAND_TAX": "Land tax",
    "TITHE": "Tithe",
    "CAPITATION": "Poll tax",
    "WAGE_TAX": "Tax on wages",
    "PROFIT_TAX": "Tax on profit",
    "EXCISE_PROVISIONS": "Excise on provisions",
    "EXCISE_WARES": "Excise on wares",
    "EXCISE_LUXURIES": "Excise on luxuries",
    "CUSTOMS": "Customs duties",
    "TOLLS": "Tolls",
    "TAX_FARMING": "Tax farming",
    "SALE_OF_CROWN_LANDS": "Sale of crown lands",
    "SINGLE_TAX_ON_RENT": "Single tax on rent",
    "USURY_PROHIBITION": "Usury forbidden",
    "USURY_CAP": "Interest capped",
    "PUBLIC_CREDIT": "Public credit",
    "SINKING_FUND": "Sinking fund",
    "STANDING_ARMY_ACT": "Standing army",
    "MILITIA_ACT": "Militia",
    "ADMINISTRATION_OF_JUSTICE": "Courts of justice",
    "POOR_RATE": "Poor rate",
    "PRICE_CONTROL_ON_GRAIN": "Grain price ceiling",
}

BRANCHES: dict[str, str] = {
    "PROPERTY": "Property",
    "LABOUR": "Labour",
    "COMMERCE": "Commerce",
    "REVENUE": "Revenue",
    "CREDIT": "Credit",
    "DEFENCE": "Defence",
    "JUSTICE": "Justice",
    "RELIEF": "Relief",
}

GOODS: dict[str, str] = {
    "PROVISIONS": "Provisions",
    "MATERIALS": "Materials",
    "WARES": "Wares",
    "LUXURIES": "Luxuries",
    "ARMS": "Arms",
    "SHIPS": "Ships",
    "ATTENDANCE": "Attendance",
}

TERRAIN: dict[str, str] = {
    "PLAINS": "Plains",
    "HILLS": "Hills",
    "FOREST": "Forest",
    "MOUNTAIN": "Mountains",
    "STEPPE": "Steppe",
    "WETLAND": "Wetland",
    "COASTAL_PLAIN": "Coast",
}

RESOURCES: dict[str, str] = {
    "game": "Game",
    "grazing": "Grazing",
    "arable": "Arable land",
    "timber": "Timber",
    "ore": "Ore",
    "coal": "Coal",
    "fishing": "Fishing",
    "rare": "Rare goods",
}

PRODUCERS: dict[str, str] = {
    "HUNTING": "Hunting",
    "HERDING": "Herding",
    "FIELD": "Fields",
    "WORKSHOP": "Workshop",
    "PUTTING_OUT": "Putting-out",
    "MANUFACTORY": "Manufactory",
    "MINE": "Mine",
    "PORT": "Port",
    "STATE": "State works",
}

METHODS: dict[str, str] = {
    "NONE": "—",
    "SOLITARY_LABOUR": "Solitary labour",
    "HERDING_WITH_DEPENDENTS": "Herding with dependents",
    "BOUND_LABOUR": "Bound labour",
    "THREE_FIELD_ROTATION": "Three-field rotation",
    "HANDICRAFT": "Handicraft",
    "PUTTING_OUT": "Putting-out",
    "MONEY_RENT": "Money rent",
    "MANUFACTORY": "Manufactory",
    "DIVISION_OF_LABOUR": "Division of labour",
    "MACHINE_PRODUCTION": "Machine production",
    "MACHINERY_STEAM": "Steam machinery",
}

TREE_NODES: dict[str, str] = {
    "GAME_AND_GATHERING": "Game and gathering",
    "DOMESTICATED_HERDS": "Domesticated herds",
    "GRAIN": "Grain",
    "WARES": "Wares",
    "LUXURIES": "Luxuries",
    "SHIPS": "Ships",
    "ARMS": "Arms",
    "EVERY_MAN_A_WARRIOR": "Every man a warrior",
    "NATION_IN_ARMS": "Nation in arms",
    "FEUDAL_HOST": "Feudal host",
    "MILITIA": "Militia",
    "STANDING_ARMY": "Standing army",
    "FIREARMS": "Firearms",
    "NAVY": "Navy",
    "BILLS_OF_EXCHANGE": "Bills of exchange",
    "BANK": "Bank",
    **METHODS,
}

DOCTRINES: dict[str, str] = {
    "EVERY_MAN": "Every man a warrior",
    "NATION_IN_ARMS": "Nation in arms",
    "FEUDAL_HOST": "Feudal host",
    "MILITIA": "Militia",
    "STANDING_ARMY": "Standing army",
}

FOCUS_KINDS: dict[str, str] = {
    "PUBLIC_WORKS": "Public works",
    "PATENT": "Patent",
    "EDUCATION": "Education",
}

TERMS: dict[str, str] = {
    "TARIFF_CEILING": "Tariff ceiling",
    "ROUTE_ACCESS": "Route access",
    "PORT_ACCESS": "Port access",
    "EXCLUSIVE_ROUTE": "Exclusive route",
    "MOST_FAVOURED": "Most favoured nation",
    "TRIBUTE": "Tribute",
    "CESSION": "Cession",
    "GRAIN_GUARANTEE": "Grain guarantee",
    "NON_AGGRESSION": "Non-aggression",
}

TIERS: dict[str, str] = {
    "subsistence": "Subsistence",
    "comfort": "Comfort",
    "standing": "Standing",
    "SUBSISTENCE": "Subsistence",
    "COMFORT": "Comfort",
    "STANDING": "Standing",
}

BUDGET: dict[str, str] = {
    "defence": "Defence",
    "justice": "Justice",
    "works": "Public works",
    "service": "Debt service",
    "court": "Court",
    "transfers": "Transfers",
}

DEBT_POLICIES: dict[str, str] = {
    "TAX": "Tax to pay",
    "ROLLOVER": "Roll over",
    "DEFAULT": "Default",
}

FUNDING_MODES: dict[str, str] = {
    "BONDS": "Borrow",
    "TAX": "Tax",
}

SEATS: dict[str, str] = {
    "BAND": "Band",
    "CHIEF": "Chiefdom",
    "STATE": "State",
}

ASSETS: dict[str, str] = {
    "herd": "Herds",
    "land_shares": "Land",
    "fixed_assets": "Buildings",
    "stock_in_place": "Stock in place",
    "hoard": "Hoard",
    "bonds": "Bonds",
    "tools": "Tools",
    "loans_out": "Loans out",
}

FACTORS: dict[str, str] = {
    "units": "Units",
    "equipment": "Equipment",
    "doctrine": "Doctrine",
    "supply": "Supply",
    "loyalty": "Loyalty",
}

ACTIONS: dict[str, str] = {
    "ENACT": "Enact",
    "REPEAL": "Repeal",
    "VETO": "Veto",
    "SET_FOCUS": "Set focus",
    "CLEAR_FOCUS": "Clear focus",
    "SET_TAX_RATE": "Set tax rate",
    "SET_BUDGET": "Set budget",
    "SET_DEBT_POLICY": "Debt policy",
    "SET_FUNDING_MODE": "Funding",
    "DECLARE_RAID": "Raid",
    "DECLARE_WAR": "Declare war",
    "BESIEGE": "Besiege",
    "OFFER_PEACE": "Offer peace",
    "ACCEPT_PEACE": "Accept peace",
    "PROPOSE_TREATY": "Propose treaty",
    "ACCEPT_TREATY": "Accept treaty",
    "REPRESS": "Send the army in",
    "PRICE_CONTROL": "Cap the price of provisions",
    "BAND_MOVE": "Move",
    "BAND_FOLLOW_HERDS": "Follow the herds",
    "BAND_SETTLE": "Settle",
    "BAND_RAID": "Raid",
    "BAND_BARTER": "Barter",
}

#: group name -> table, as shipped in `Snapshot.labels`.
LABELS: dict[str, dict[str, str]] = {
    "symbol": SYMBOLS,
    "class": CLASSES,
    "interest": INTERESTS,
    "law": LAWS,
    "branch": BRANCHES,
    "good": GOODS,
    "terrain": TERRAIN,
    "resource": RESOURCES,
    "producer": PRODUCERS,
    "method": METHODS,
    "node": TREE_NODES,
    "doctrine": DOCTRINES,
    "focus": FOCUS_KINDS,
    "term": TERMS,
    "tier": TIERS,
    "budget": BUDGET,
    "debt_policy": DEBT_POLICIES,
    "funding_mode": FUNDING_MODES,
    "seat": SEATS,
    "asset": ASSETS,
    "factor": FACTORS,
    "action": ACTIONS,
}

#: Enums whose every member must have a label (checked by `tests/test_labels.py`).
LABELLED_ENUMS: dict[str, type] = {
    "class": ClassId,
    "interest": InterestId,
    "law": LawId,
    "branch": LawBranch,
    "good": Good,
    "tier": Tier,
    "terrain": Terrain,
    "producer": ProducerKind,
    "method": MethodId,
    "focus": FocusKind,
    "seat": SeatKind,
}
for _enum in (TreeINode, DefenceNode, CreditNode):
    LABELLED_ENUMS[f"node:{_enum.__name__}"] = _enum


def humanize(key: str) -> str:
    """`SNAKE_CASE` / `snake_case` -> `Snake case`: the fallback for an unlabelled key."""

    text = str(key).replace("_", " ").strip()
    return text[:1].upper() + text[1:].lower() if text else ""


def label(group: str, key: Any) -> str:
    name = getattr(key, "name", key)
    table = LABELS.get(group, {})
    return table.get(str(name), humanize(str(name)))


def law_label(law: Any) -> str:
    """Laws include dynamically named trade laws (`TARIFF_WARES`, `BOUNTY_SHIPS`,
    `PROHIBITION_LUXURIES`) that no enum lists."""

    name = str(getattr(law, "name", law))
    if name in LAWS:
        return LAWS[name]
    trade_prefixes = (("TARIFF_", "Tariff on"), ("BOUNTY_", "Bounty on"), ("PROHIBITION_", "Prohibition of"))
    for prefix, word in trade_prefixes:
        if name.startswith(prefix):
            return f"{word} {label('good', name[len(prefix):]).lower()}"
    return humanize(name)


def describe_action(kind: str, payload: dict[str, Any], names: Any) -> str:
    """One-line label for a queued action chip / feed entry: the verb plus what it
    targets, by display name. `names` is a `NameRegister` (duck-typed to keep this
    module free of `ui.names`)."""

    verb = ACTIONS.get(kind, humanize(kind))
    p = payload

    def loc(key: str) -> str:
        v = p.get(key)
        return str(names.location(v)) if v is not None else ""

    def nation(key: str) -> str:
        v = p.get(key)
        return str(names.nation(v)) if v is not None else ""

    if kind in ("ENACT", "REPEAL", "VETO") and "law" in p:
        text = f"{verb} {law_label(p['law'])}"
        if kind == "VETO" and "interest" in p:
            text += f" · {label('interest', p['interest'])}"
        return text
    if kind == "SET_FOCUS":
        text = f"{verb} · {label('focus', p.get('kind', ''))} · {label('node', p.get('node', ''))}"
        if p.get("location"):
            text += f" · {loc('location')}"
        return text
    if kind == "SET_TAX_RATE":
        rate = float(p.get("rate", 0.0)) * 100
        return f"{law_label(p.get('instrument', ''))} · rate {rate:.1f}%"
    if kind == "SET_DEBT_POLICY":
        return f"{verb} · {label('debt_policy', p.get('policy', ''))}"
    if kind == "SET_FUNDING_MODE":
        return f"{verb} · {label('funding_mode', p.get('mode', ''))}"
    if kind in ("DECLARE_WAR", "OFFER_PEACE", "ACCEPT_PEACE", "PROPOSE_TREATY"):
        return f"{verb} · {nation('target')}" if p.get("target") else verb
    if kind == "ACCEPT_TREATY":
        return f"{verb} · {nation('initiator')}" if p.get("initiator") else verb
    if kind in ("DECLARE_RAID", "BAND_RAID", "BESIEGE", "PRICE_CONTROL"):
        return f"{verb} · {loc('location')}" if p.get("location") else verb
    if kind == "BAND_MOVE":
        return f"{verb} to {loc('to')}" if p.get("to") else verb
    if kind == "BAND_BARTER":
        return f"{verb} with {loc('with')}" if p.get("with") else verb
    return verb
