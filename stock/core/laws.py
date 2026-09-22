"""Laws — Tree III / SHARE (DD §6.3), tax instruments (DD §12.1), and Focus (DD §6.4).

Effects are declarative: `EffectSpec(kind, params)` tags read by the owning engine
module rather than executable code, so a law's mechanical effect lives in one place
(`LAW_TABLE`) and is applied by whichever module owns that mechanism (Doc 00's "one
place per formula", extended to law effects). Most laws have no effects populated yet
because the mechanics they'd tag into don't exist until Docs 02-05; see DEVIATIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from stock.core.goods import Good
from stock.core.records import InterestId


class LawBranch(Enum):
    PROPERTY = auto()
    LABOUR = auto()
    COMMERCE = auto()
    REVENUE = auto()
    CREDIT = auto()
    DEFENCE = auto()
    JUSTICE = auto()
    RELIEF = auto()


class LawId(Enum):
    # Property (DD §6.3)
    KILL_TO_KILLER = auto()
    SHARED_BY_CUSTOM = auto()
    TAMED_ANIMAL_TO_TAMER = auto()
    PROTECTION_OF_PROPERTY = auto()
    HERDS_HERITABLE = auto()
    LAND_OWNABLE = auto()
    PRIMOGENITURE = auto()
    ALIENABLE = auto()
    STOCK_SEPARABLE = auto()
    # Labour
    SERFDOM = auto()
    COMMUTATION = auto()
    ENCLOSURE = auto()
    SETTLEMENT_LAW = auto()
    APPRENTICESHIP = auto()  # covers the Statute of Artificers (DD §6.3 note)
    GUILD_CHARTER = auto()
    COMBINATION_ACT = auto()
    # Commerce
    FREE_TRADE = auto()
    NAVIGATION_ACT = auto()
    CHARTERED_COMPANY = auto()
    # Revenue / taxation (DD §12.1)
    LAND_TAX = auto()
    TITHE = auto()
    CAPITATION = auto()
    WAGE_TAX = auto()
    PROFIT_TAX = auto()
    EXCISE_PROVISIONS = auto()
    EXCISE_WARES = auto()
    EXCISE_LUXURIES = auto()
    CUSTOMS = auto()
    TOLLS = auto()
    TAX_FARMING = auto()
    SALE_OF_CROWN_LANDS = auto()
    SINGLE_TAX_ON_RENT = auto()
    # Credit
    USURY_PROHIBITION = auto()
    USURY_CAP = auto()
    PUBLIC_CREDIT = auto()
    SINKING_FUND = auto()  # v2 (DD §16.1)
    # Defence
    STANDING_ARMY_ACT = auto()
    MILITIA_ACT = auto()
    # Justice
    ADMINISTRATION_OF_JUSTICE = auto()
    # Relief
    POOR_RATE = auto()
    PRICE_CONTROL_ON_GRAIN = auto()


def tariff_law(good: Good) -> str:
    """Tariff laws are per good class (DD §6.3 "(per class)"); named dynamically since
    LawId can't hold a payload. Registered into LawId-like string keys in TARIFF_LAWS."""

    return f"TARIFF_{good.name}"


def bounty_law(good: Good) -> str:
    return f"BOUNTY_{good.name}"


def prohibition_law(good: Good) -> str:
    return f"PROHIBITION_{good.name}"


#: Tradeable goods a Tariff/Bounty/Prohibition can target (DD §6.3; Attendance is not
#: traded across borders — see DD §10.1's route goods).
TARIFFABLE_GOODS: tuple[Good, ...] = (
    Good.PROVISIONS,
    Good.MATERIALS,
    Good.WARES,
    Good.LUXURIES,
    Good.ARMS,
    Good.SHIPS,
)


class FocusKind(Enum):
    """The sovereign's Focus (DD §6.4): spends revenue to lower one node's gate in one
    location. Not a law — no support/opposition, no enactment bar, only upkeep."""

    PUBLIC_WORKS = auto()
    PATENT = auto()
    EDUCATION = auto()


@dataclass(frozen=True)
class EffectSpec:
    """A declarative effect tag (see module docstring)."""

    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LawSpec:
    branch: LawBranch
    support: frozenset[InterestId]
    opposition: frozenset[InterestId]
    binds: InterestId | None  # the Interest whose enforcement gates this law (MM §13)
    weight: float  # weight in State authority's sum over enacted laws (MM §12, a3)
    effects: tuple[EffectSpec, ...] = ()


_I = InterestId

LAW_TABLE: dict[LawId, LawSpec] = {
    LawId.KILL_TO_KILLER: LawSpec(LawBranch.PROPERTY, frozenset(), frozenset(), None, 0.1),
    LawId.SHARED_BY_CUSTOM: LawSpec(LawBranch.PROPERTY, frozenset(), frozenset(), None, 0.1),
    LawId.TAMED_ANIMAL_TO_TAMER: LawSpec(
        LawBranch.PROPERTY,
        frozenset({_I.LANDED}),
        frozenset(),
        None,
        0.5,
        effects=(EffectSpec("handover_tamed_animal"),),
    ),
    LawId.PROTECTION_OF_PROPERTY: LawSpec(
        LawBranch.PROPERTY,
        frozenset({_I.LANDED}),
        frozenset({_I.LABOUR}),
        _I.LANDED,
        1.0,
        effects=(EffectSpec("handover_protection_of_property"), EffectSpec("tax_on_all")),
    ),
    LawId.HERDS_HERITABLE: LawSpec(
        LawBranch.PROPERTY,
        frozenset({_I.LANDED}),
        frozenset(),
        _I.LANDED,
        0.3,
        effects=(EffectSpec("concentration", {"good": "herd"}),),
    ),
    LawId.LAND_OWNABLE: LawSpec(
        LawBranch.PROPERTY,
        frozenset({_I.LANDED}),
        frozenset({_I.LABOUR}),
        _I.LANDED,
        0.8,
        effects=(EffectSpec("unlocks_land_shares"),),
    ),
    LawId.PRIMOGENITURE: LawSpec(
        LawBranch.PROPERTY,
        frozenset({_I.LANDED}),
        frozenset({_I.MERCHANT, _I.INDUSTRIAL}),
        _I.LANDED,
        0.3,
        effects=(EffectSpec("concentration", {"good": "land_shares"}), EffectSpec("default_pledges_rent")),
    ),
    LawId.ALIENABLE: LawSpec(
        LawBranch.PROPERTY,
        frozenset({_I.MERCHANT, _I.INDUSTRIAL}),
        frozenset({_I.LANDED}),
        _I.LANDED,
        0.3,
        effects=(EffectSpec("fragmentation", {"good": "land_shares"}), EffectSpec("default_transfers_land")),
    ),
    LawId.STOCK_SEPARABLE: LawSpec(
        LawBranch.PROPERTY,
        frozenset({_I.INDUSTRIAL, _I.MERCHANT}),
        frozenset({_I.LANDED}),
        _I.INDUSTRIAL,
        0.6,
        effects=(EffectSpec("unlocks", {"nodes": ("MANUFACTORY",)}),),
    ),
    LawId.SERFDOM: LawSpec(
        LawBranch.LABOUR,
        frozenset({_I.LANDED}),
        frozenset({_I.LABOUR}),
        _I.LANDED,
        0.5,
        effects=(EffectSpec("walk_away_multiplier", {"cls": "SERFS", "base": 0.0}),),
    ),
    LawId.COMMUTATION: LawSpec(
        LawBranch.LABOUR,
        frozenset({_I.LABOUR, _I.MERCHANT}),
        frozenset({_I.LANDED}),
        _I.LANDED,
        0.4,
        effects=(EffectSpec("vertical_flow", {"from": "SERFS", "to": "TENANTS"}),),
    ),
    LawId.ENCLOSURE: LawSpec(
        LawBranch.LABOUR,
        frozenset({_I.LANDED}),
        frozenset({_I.LABOUR}),
        _I.LANDED,
        0.4,
        effects=(
            EffectSpec("commons_to_land_shares"),
            EffectSpec("vertical_flow", {"from": "SERFS", "to": "LABOURERS", "forced": True}),
            EffectSpec("vertical_flow", {"from": "TENANTS", "to": "LABOURERS", "forced": True}),
        ),
    ),
    LawId.SETTLEMENT_LAW: LawSpec(
        LawBranch.LABOUR,
        frozenset({_I.LANDED}),
        frozenset({_I.INDUSTRIAL, _I.LABOUR}),
        _I.LANDED,
        0.3,
        effects=(EffectSpec("friction", {"edge": "free_labour_cross_location", "x": 0.6}),),
    ),
    LawId.APPRENTICESHIP: LawSpec(
        LawBranch.LABOUR,
        frozenset({_I.INDUSTRIAL}),
        frozenset({_I.LABOUR}),
        _I.INDUSTRIAL,
        0.3,
        effects=(EffectSpec("friction", {"edge": "producer", "x": 0.4}), EffectSpec("state_wage_ceiling")),
    ),
    LawId.GUILD_CHARTER: LawSpec(
        LawBranch.LABOUR,
        frozenset({_I.INDUSTRIAL}),
        frozenset({_I.INDUSTRIAL, _I.MERCHANT}),
        _I.INDUSTRIAL,
        0.3,
        effects=(EffectSpec("craftsmen_cap"), EffectSpec("blocks", {"nodes": ("MANUFACTORY",)})),
    ),
    LawId.COMBINATION_ACT: LawSpec(
        LawBranch.LABOUR,
        frozenset({_I.INDUSTRIAL}),
        frozenset({_I.LABOUR}),
        _I.INDUSTRIAL,
        0.4,
        effects=(EffectSpec("enforcement_in_wage"),),
    ),
    LawId.FREE_TRADE: LawSpec(
        LawBranch.COMMERCE,
        frozenset({_I.MERCHANT}),
        frozenset({_I.INDUSTRIAL}),
        None,
        0.2,
        effects=(EffectSpec("routes_open_to_all"),),
    ),
    LawId.NAVIGATION_ACT: LawSpec(
        LawBranch.COMMERCE,
        frozenset({_I.MERCHANT}),
        frozenset({_I.MERCHANT, _I.INDUSTRIAL}),
        _I.MERCHANT,
        0.3,
        effects=(EffectSpec("domestic_ships_only"), EffectSpec("navy_base")),
    ),
    LawId.CHARTERED_COMPANY: LawSpec(
        LawBranch.COMMERCE,
        frozenset({_I.MERCHANT}),
        frozenset({_I.INDUSTRIAL, _I.LABOUR}),
        _I.MERCHANT,
        0.3,
        effects=(EffectSpec("route_monopoly"),),
    ),
    LawId.LAND_TAX: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.LANDED}), _I.LANDED, 0.3),
    LawId.TITHE: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.LANDED}), _I.LANDED, 0.1),
    LawId.CAPITATION: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.LABOUR}), None, 0.2),
    LawId.WAGE_TAX: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.LABOUR}), _I.INDUSTRIAL, 0.2),
    LawId.PROFIT_TAX: LawSpec(
        LawBranch.REVENUE, frozenset(), frozenset({_I.INDUSTRIAL, _I.MERCHANT}), _I.INDUSTRIAL, 0.2
    ),
    LawId.EXCISE_PROVISIONS: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.LABOUR}), None, 0.2),
    LawId.EXCISE_WARES: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.LABOUR}), None, 0.2),
    LawId.EXCISE_LUXURIES: LawSpec(
        LawBranch.REVENUE, frozenset(), frozenset({_I.LANDED, _I.MERCHANT}), None, 0.1
    ),
    LawId.CUSTOMS: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.MERCHANT}), _I.MERCHANT, 0.2),
    LawId.TOLLS: LawSpec(LawBranch.REVENUE, frozenset(), frozenset(), None, 0.1),
    LawId.TAX_FARMING: LawSpec(LawBranch.REVENUE, frozenset(), frozenset({_I.LABOUR}), None, 0.2),
    LawId.SALE_OF_CROWN_LANDS: LawSpec(LawBranch.REVENUE, frozenset(), frozenset(), None, 0.1),
    LawId.SINGLE_TAX_ON_RENT: LawSpec(
        LawBranch.REVENUE, frozenset(), frozenset({_I.LANDED}), _I.LANDED, 0.3
    ),
    LawId.USURY_PROHIBITION: LawSpec(
        LawBranch.CREDIT, frozenset({_I.LANDED}), frozenset({_I.MERCHANT}), None, 0.2
    ),
    LawId.USURY_CAP: LawSpec(LawBranch.CREDIT, frozenset(), frozenset({_I.MONEYED}), None, 0.2),
    LawId.PUBLIC_CREDIT: LawSpec(
        LawBranch.CREDIT,
        frozenset({_I.MONEYED, _I.MERCHANT, _I.INDUSTRIAL}),
        frozenset({_I.LANDED}),
        None,
        0.3,
        effects=(EffectSpec("unlocks_bonds"),),
    ),
    LawId.SINKING_FUND: LawSpec(LawBranch.CREDIT, frozenset({_I.MONEYED}), frozenset(), None, 0.2),
    LawId.STANDING_ARMY_ACT: LawSpec(
        LawBranch.DEFENCE,
        frozenset({_I.MERCHANT, _I.INDUSTRIAL}),
        frozenset({_I.LANDED}),
        None,
        0.4,
        effects=(EffectSpec("creates_soldiers_record"), EffectSpec("doctrine", {"value": "STANDING_ARMY"})),
    ),
    LawId.MILITIA_ACT: LawSpec(
        LawBranch.DEFENCE,
        frozenset({_I.LANDED}),
        frozenset({_I.INDUSTRIAL}),
        None,
        0.3,
        effects=(EffectSpec("doctrine", {"value": "MILITIA"}),),
    ),
    LawId.ADMINISTRATION_OF_JUSTICE: LawSpec(
        LawBranch.JUSTICE,
        frozenset({_I.MERCHANT, _I.INDUSTRIAL}),
        frozenset({_I.LANDED}),
        None,
        0.3,
        effects=(EffectSpec("justice_draw_raises_j"),),
    ),
    LawId.POOR_RATE: LawSpec(
        LawBranch.RELIEF,
        frozenset({_I.LABOUR, _I.INDUSTRIAL}),
        frozenset({_I.LANDED}),
        _I.LANDED,
        0.2,
        effects=(EffectSpec("transfer_funded_on_rent"),),
    ),
    LawId.PRICE_CONTROL_ON_GRAIN: LawSpec(
        LawBranch.RELIEF,
        frozenset({_I.LABOUR}),
        frozenset({_I.LANDED}),
        _I.LANDED,
        0.2,
        effects=(EffectSpec("price_cap", {"good": "PROVISIONS"}),),
    ),
}


def make_trade_law_table() -> dict[str, LawSpec]:
    """Per-good Tariff/Bounty/Prohibition laws (DD §6.3 "(per class)"), keyed by the
    string names from `tariff_law`/`bounty_law`/`prohibition_law` since LawId can't
    carry a payload. Merged into scenario/nation law-state dicts by string key."""

    table: dict[str, LawSpec] = {}
    for good in TARIFFABLE_GOODS:
        table[tariff_law(good)] = LawSpec(
            LawBranch.COMMERCE,
            frozenset(),  # support is "the producer" of `good` — resolved at apply time
            frozenset({_I.MERCHANT, _I.LABOUR}),
            _I.MERCHANT,
            0.2,
            effects=(EffectSpec("import_price_up", {"good": good.name}),),
        )
        table[bounty_law(good)] = LawSpec(
            LawBranch.COMMERCE,
            frozenset(),
            frozenset(),  # opposition is "whoever pays" — resolved at apply time
            None,
            0.2,
            effects=(EffectSpec("export_price_above_natural", {"good": good.name}),),
        )
        table[prohibition_law(good)] = LawSpec(
            LawBranch.COMMERCE,
            frozenset(),
            frozenset({_I.MERCHANT, _I.LABOUR}),
            _I.MERCHANT,
            0.3,
            effects=(EffectSpec("route_closed", {"good": good.name}),),
        )
    return table


#: Per-good trade laws, merged for convenience where callers want one lookup table.
TRADE_LAW_TABLE: dict[str, LawSpec] = make_trade_law_table()
