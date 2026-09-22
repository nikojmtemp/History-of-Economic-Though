"""The three trees (DD §6). Node identities and gate predicates live here (pure,
declarative); Doc 05's `meta/trees.py` owns `evaluate_gates`, the per-year walk that
lights nodes and keeps them lit through regression (DD §6, §13).

Tree II's production branch reuses `core.producers.MethodId` one-to-one (a method
being lit *is* the node being lit) rather than duplicating eleven names in a second
enum — see DEVIATIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from stock.core.producers import MethodId


class TreeINode(Enum):
    """Tree I — WHAT (DD §6.1): good classes a location can make."""

    GAME_AND_GATHERING = auto()
    DOMESTICATED_HERDS = auto()
    GRAIN = auto()
    WARES = auto()
    LUXURIES = auto()
    SHIPS = auto()
    ARMS = auto()


class DefenceNode(Enum):
    """Tree II — defence branch (DD §6.2)."""

    EVERY_MAN_A_WARRIOR = auto()
    NATION_IN_ARMS = auto()
    FEUDAL_HOST = auto()
    MILITIA = auto()
    STANDING_ARMY = auto()
    FIREARMS = auto()
    NAVY = auto()


class CreditNode(Enum):
    """Tree II — credit branch (DD §6.2)."""

    BILLS_OF_EXCHANGE = auto()
    BANK = auto()  # v2 (DD §16.1)


#: Tree II production branch node order (DD §6.2), as MethodId members — the order
#: matters for "the first build" defaults and for balance-run summaries.
PRODUCTION_CHAIN: tuple[MethodId, ...] = (
    MethodId.SOLITARY_LABOUR,
    MethodId.HERDING_WITH_DEPENDENTS,
    MethodId.BOUND_LABOUR,
    MethodId.THREE_FIELD_ROTATION,
    MethodId.HANDICRAFT,
    MethodId.PUTTING_OUT,
    MethodId.MONEY_RENT,
    MethodId.MANUFACTORY,
    MethodId.DIVISION_OF_LABOUR,
    MethodId.MACHINE_PRODUCTION,
    MethodId.MACHINERY_STEAM,
)

DEFENCE_CHAIN: tuple[DefenceNode, ...] = (
    DefenceNode.EVERY_MAN_A_WARRIOR,
    DefenceNode.NATION_IN_ARMS,
    DefenceNode.FEUDAL_HOST,
    DefenceNode.MILITIA,
    DefenceNode.STANDING_ARMY,
    DefenceNode.FIREARMS,
    DefenceNode.NAVY,
)

CREDIT_CHAIN: tuple[CreditNode, ...] = (CreditNode.BILLS_OF_EXCHANGE, CreditNode.BANK)


@dataclass
class NodeState:
    """A tree node's state. Once `lit`, stays lit through regression (DD §13 step 4);
    `idle` means lit but the method/doctrine/credit form is not currently in use."""

    lit: bool = False
    lit_year: int | None = None
    idle: bool = False


@dataclass
class LocationTreeState:
    """Tree I is evaluated per location (DD §6.1)."""

    nodes: dict[TreeINode, NodeState] = field(
        default_factory=lambda: {n: NodeState() for n in TreeINode}
    )


@dataclass
class NationTreeState:
    """Tree II is evaluated per nation (DD §6.2)."""

    production: dict[MethodId, NodeState] = field(
        default_factory=lambda: {n: NodeState() for n in PRODUCTION_CHAIN}
    )
    defence: dict[DefenceNode, NodeState] = field(
        default_factory=lambda: {n: NodeState() for n in DEFENCE_CHAIN}
    )
    credit: dict[CreditNode, NodeState] = field(
        default_factory=lambda: {n: NodeState() for n in CREDIT_CHAIN}
    )


#: Tree I gates (DD §6.1 "Gate (in the location)" column). Parts of a gate that need a
#: subsystem not yet built (contact, extent-of-market reachability, a lit manufactory)
#: are supplied by the caller as keyword context rather than re-derived here, so this
#: stays a pure predicate; Doc 05's `evaluate_gates` computes that context and calls in.
def tree1_gate_met(
    node: TreeINode,
    *,
    has_game: bool = False,
    has_grazing: bool = False,
    has_arable: bool = False,
    has_rare: bool = False,
    has_ore: bool = False,
    has_coal: bool = False,
    is_coast: bool = False,
    contact: float = 0.0,
    contact_threshold: float = 1.0,
    settled: bool = False,
    is_town: bool = False,
    craftsmen_present: bool = False,
    materials_available: bool = False,
    wares_available: bool = False,
    route_reaches_luxuries: bool = False,
    manufactory_or_ironworks: bool = False,
) -> bool:
    if node is TreeINode.GAME_AND_GATHERING:
        return has_game
    if node is TreeINode.DOMESTICATED_HERDS:
        return has_grazing and contact >= contact_threshold
    if node is TreeINode.GRAIN:
        return has_arable and settled
    if node is TreeINode.WARES:
        return materials_available and craftsmen_present and is_town
    if node is TreeINode.LUXURIES:
        return (
            (has_rare and craftsmen_present)
            or route_reaches_luxuries
            or manufactory_or_ironworks
        )
    if node is TreeINode.SHIPS:
        return is_coast and materials_available and wares_available
    if node is TreeINode.ARMS:
        return has_ore and has_coal and manufactory_or_ironworks
    raise AssertionError(f"unhandled TreeINode {node}")
