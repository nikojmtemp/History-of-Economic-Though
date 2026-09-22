"""Sovereigns (Doc 05's null stub; Doc 06 adds ScriptedSovereign)."""

from __future__ import annotations

from typing import Any, Protocol

from stock.ai.scripts import SCRIPTS, Script, select_mode
from stock.ai.view import NationView
from stock.core.actions import Action


class Sovereign(Protocol):
    def decide(self, view: NationView, rng: Any) -> list[Action]: ...


class NullSovereign:
    """Enqueues nothing."""

    def decide(self, view: NationView, rng: Any) -> list[Action]:
        return []


class ScriptedSovereign:
    """Picks a script by the nation's dominant Interest and fires every rule whose
    condition holds, in order, up to `max_actions` (None: every rule that holds —
    `sim/year._act` then enqueues the first ones that validate, so a rule whose
    action cannot pass its bar this year does not use up the year's actions, A76).
    Peace, treaty answers and breach responses come before the script."""

    def __init__(self, scripts: dict[Any, Script] | None = None, max_actions: int | None = 2) -> None:
        self.scripts = scripts if scripts is not None else SCRIPTS
        self.max_actions = max_actions

    def decide(self, view: NationView, rng: Any) -> list[Action]:
        from stock.ai.scripts import answer_proposals, make_peace, respond_to_breach

        actions: list[Action] = []
        for common in (make_peace, answer_proposals, respond_to_breach):
            action = common(view)
            if action is not None:
                actions.append(action)

        mode = select_mode(view)
        script = self.scripts.get(mode, [])
        for _name, condition, factory in script:
            if self.max_actions is not None and len(actions) >= self.max_actions:
                break
            if not condition(view):
                continue
            action = factory(view, rng)
            if action is not None:
                actions.append(action)
        return actions if self.max_actions is None else actions[: self.max_actions]
