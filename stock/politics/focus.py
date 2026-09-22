"""The sovereign's Focus — year step 10 support (DD §6.4).

`FocusState` (node, location, progress, upkeep) already lives on `Nation` (Doc 01).
Gate evaluation itself — actually lowering a Tree I/II node's gate by the Focus's
accumulated effect — is Doc 05's `meta/trees.py` (`evaluate_gates`, not built yet);
this module tracks progress and reports the effect magnitude Doc 05 will consume.
"""

from __future__ import annotations

from dataclasses import dataclass

from stock.core.laws import FocusKind
from stock.core.params import Params
from stock.core.world import FocusState, Nation


def set_focus(nation: Nation, kind: FocusKind, node: str, location: str | None = None) -> None:
    """Sets a new Focus, forfeiting any progress on the previous one (DD §6.4:
    "switching forfeits progress")."""

    nation.focus = FocusState(kind=kind, node=node, location=location)


def clear_focus(nation: Nation) -> None:
    nation.focus = None


@dataclass(frozen=True)
class FocusEffect:
    """The Focus's current gate-reduction, read out for Doc 05's `meta/trees.py`
    (DD §6.4): which node/location it targets, and the magnitude in `[0,1]` this
    year's accumulated progress buys. `evaluate_gates` decides *how* `magnitude`
    lowers that node's gate (a carriage-cost cut, a threshold cut, ...) — this
    module only tracks progress and reports the number."""

    kind: FocusKind
    node: str
    location: str | None
    magnitude: float


def gate_reduction(nation: Nation, params: Params) -> FocusEffect | None:
    """Reads the nation's Focus (if any) into a `FocusEffect` — a pure function of
    `nation.focus.progress`, not a mutator; `advance_focus` is the sole writer of
    `progress`/`upkeep`. Returns `None` with no Focus or no progress yet."""

    focus = nation.focus
    if focus is None or focus.progress <= 0:
        return None
    p = params.politics
    rate = p.focus_gate_rate_education if focus.kind is FocusKind.EDUCATION else p.focus_gate_rate
    magnitude = min(1.0, focus.progress * rate)
    return FocusEffect(kind=focus.kind, node=focus.node, location=focus.location, magnitude=magnitude)


def advance_focus(nation: Nation, works_draw: float, params: Params) -> float:
    """Advances the nation's Focus by this year's spend (`works_draw`; 0 until Doc
    05's budget exists) and returns the gate-reduction magnitude this year's
    progress buys (DD §6.4): Public Works — carriage factor on chosen edges; Patent
    — exclusive method N years with expiry; Education — skill-penalty reduction.
    All three reduce, from here, to "a gate lowered by an amount proportional to
    accumulated progress", computed by `gate_reduction` once progress is recorded;
    which specific gate field each writes is `meta/trees.py`'s `evaluate_gates`."""

    focus = nation.focus
    if focus is None or works_draw <= 0:
        return 0.0
    focus.progress += works_draw
    focus.upkeep = works_draw
    effect = gate_reduction(nation, params)
    return effect.magnitude if effect is not None else 0.0
