"""The action queue (DD §7.2): the player and the AI share one API. Actions are queued
during the year and applied at step 14 (the year boundary), where cost is deducted.

Cost formulas are mostly owned by later docs (politics for laws/vetoes/Focus; security
for war/raids/repression; finance for tax/budget) — this module provides the generic
plumbing (`Action`, `validate`, `enqueue`) and a small registry so those modules can
plug in a cost function per `ActionKind` without this module depending on them. An
unregistered action kind costs 0 until its owning doc registers a real formula.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stock.core.world import World


class ActionKind(Enum):
    ENACT = auto()
    REPEAL = auto()
    VETO = auto()
    SET_FOCUS = auto()
    CLEAR_FOCUS = auto()
    SET_TAX_RATE = auto()
    SET_BUDGET = auto()
    SET_DEBT_POLICY = auto()
    SET_FUNDING_MODE = auto()
    DECLARE_RAID = auto()
    DECLARE_WAR = auto()
    BESIEGE = auto()
    OFFER_PEACE = auto()
    ACCEPT_PEACE = auto()
    PROPOSE_TREATY = auto()
    ACCEPT_TREATY = auto()
    REPRESS = auto()
    PRICE_CONTROL = auto()
    BAND_MOVE = auto()
    BAND_FOLLOW_HERDS = auto()
    BAND_SETTLE = auto()
    BAND_RAID = auto()
    BAND_BARTER = auto()


#: Actions only a band (seat == BAND) may take (DD §3).
BAND_ONLY_ACTIONS: frozenset[ActionKind] = frozenset(
    {
        ActionKind.BAND_MOVE,
        ActionKind.BAND_FOLLOW_HERDS,
        ActionKind.BAND_SETTLE,
        ActionKind.BAND_RAID,
        ActionKind.BAND_BARTER,
    }
)

#: Actions that require a seat beyond BAND — a sovereign currency to spend (DD §7.2).
SOVEREIGN_ACTIONS: frozenset[ActionKind] = frozenset(
    {
        ActionKind.ENACT,
        ActionKind.REPEAL,
        ActionKind.VETO,
        ActionKind.SET_FOCUS,
        ActionKind.CLEAR_FOCUS,
        ActionKind.SET_TAX_RATE,
        ActionKind.SET_BUDGET,
        ActionKind.SET_DEBT_POLICY,
        ActionKind.SET_FUNDING_MODE,
        ActionKind.DECLARE_RAID,
        ActionKind.DECLARE_WAR,
        ActionKind.BESIEGE,
        ActionKind.OFFER_PEACE,
        ActionKind.ACCEPT_PEACE,
        ActionKind.PROPOSE_TREATY,
        ActionKind.ACCEPT_TREATY,
        ActionKind.REPRESS,
        ActionKind.PRICE_CONTROL,
    }
)


@dataclass
class Action:
    kind: ActionKind
    nation: str
    payload: dict[str, Any] = field(default_factory=dict)
    cost: float | None = None  # filled by validate()/enqueue()


@dataclass
class ValidationResult:
    ok: bool
    cost: float = 0.0
    reason: str | None = None
    numbers: dict[str, float] = field(default_factory=dict)


CostFn = Callable[["World", Action], float]

_COST_FUNCTIONS: dict[ActionKind, CostFn] = {}


def register_cost_fn(kind: ActionKind, fn: CostFn) -> None:
    """Register a real cost formula for an action kind (called by politics/security/
    finance modules as they're built). Overwrites any previous registration."""

    _COST_FUNCTIONS[kind] = fn


def _cost_of(world: World, action: Action) -> float:
    fn = _COST_FUNCTIONS.get(action.kind)
    return fn(world, action) if fn is not None else 0.0


def validate(world: World, action: Action) -> ValidationResult:
    """Legality plus cost (DD §7.2). Generic seat legality lives here; the numeric cost
    formula for most kinds is filled in by 03/04/05 via `register_cost_fn`."""

    nation = world.nations.get(action.nation)
    if nation is None:
        return ValidationResult(ok=False, reason=f"no such nation {action.nation!r}")

    from stock.core.world import SeatKind  # local import: avoids a cycle with world.py

    if action.kind in BAND_ONLY_ACTIONS and nation.seat != SeatKind.BAND:
        return ValidationResult(ok=False, reason=f"{action.kind.name} requires seat BAND")
    if action.kind in SOVEREIGN_ACTIONS and nation.seat == SeatKind.BAND:
        return ValidationResult(ok=False, reason=f"{action.kind.name} requires a seat beyond BAND")

    cost = _cost_of(world, action)
    if action.kind in SOVEREIGN_ACTIONS and cost > nation.scalars.A_S:
        return ValidationResult(
            ok=False,
            cost=cost,
            reason="insufficient A_S",
            numbers={"cost": cost, "available": nation.scalars.A_S},
        )
    return ValidationResult(ok=True, cost=cost)


def enqueue(world: World, action: Action) -> ValidationResult:
    """Validate and, if legal, append to the nation's queue (applied at step 14)."""

    result = validate(world, action)
    if result.ok:
        action.cost = result.cost
        world.nations[action.nation].queue.append(action)
    return result
