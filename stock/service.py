"""The game as a service: every request the UI makes, answered in one place.

The desktop server (stock/server.py) puts this behind HTTP; the browser build
(stock/browser.py, in Pyodide) calls it directly from the page. Both speak the same
routes and the same JSON, so the one UI serves both.

    GET  /state            the player's snapshot
    GET  /scenario         the world spec (seed:nodes:nations) that regenerates this world
    GET  /alive            the page's heartbeat
    POST /action           one action: {"kind": ..., ...}; answers {ok, why, state}
    POST /forecast         one action, previewed one turn ahead (§19.5)
    POST /turn             end the turn
    POST /regent           let the AI rule our people for {"turns": N} turns (it takes every decision)
    POST /new              a new world: {"spec": "random:SEED:NODES:NATIONS"} or {} for a fresh seed
    GET  /saves            the saved games, newest first
    POST /save             save the game as {"name": ...} (a default name if none)
    POST /load             load {"file": ...}
    POST /delete_save      delete {"file": ...}

With no world spec given, the game continues the autosave if there is one. Everything
that changes the game is autosaved (stock/saves.py), so closing it loses nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from stock import saves
from stock.game import actions, ai, turn, view
from stock.game.state import World
from stock.game.worldgen import generate, parse_spec


class ApiError(Exception):
    """A request refused: an HTTP status and the reason, for the player."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


class Game:
    def __init__(self, spec: str | None = None) -> None:
        self.lock = threading.Lock()
        self.note: str | None = None  # said once, on the first look at the game
        world: World | None = None
        if spec is None and saves.exists(saves.AUTOSAVE):
            try:
                world = saves.load(saves.AUTOSAVE)
                self.note = f"Welcome back: your game goes on from turn {world.turn}."
            except Exception:  # noqa: BLE001 - a spoiled autosave must not stop the game starting
                self.note = "Your last game could not be read, so a new world begins."
        self.world: World = world or generate(parse_spec(spec))
        self.routes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "/state": self.state,
            "/scenario": self.scenario,
            "/alive": self.alive,
            "/action": self.action,
            "/forecast": self.forecast,
            "/turn": self.end_turn,
            "/regent": self.regent,
            "/new": self.new,
            "/saves": self.list_saves,
            "/save": self.save,
            "/load": self.load,
            "/delete_save": self.delete_save,
        }

    def call(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Answer one request, as the UI makes it: a route and its JSON body."""

        route = self.routes.get(path)
        if route is None:
            raise ApiError(404, f"No such request: {path}")
        with self.lock:
            return route(body or {})

    def autosave(self) -> None:
        try:
            saves.save(self.world, saves.AUTOSAVE)
        except OSError:
            pass  # a full or locked disk costs the autosave, never the game

    def player_id(self) -> str:
        p = self.world.player()
        assert p is not None
        return p.id

    # --- the routes ------------------------------------------------------------------------

    def state(self, _body: dict[str, Any]) -> dict[str, Any]:
        snap = view.snapshot(self.world)
        if self.note:
            snap["note"], self.note = self.note, None
        return snap

    def scenario(self, _body: dict[str, Any]) -> dict[str, Any]:
        return {"spec": self.world.spec, "seed": self.world.seed}

    def alive(self, _body: dict[str, Any]) -> dict[str, Any]:
        """The page's heartbeat; also how a second launch knows Stock is already running."""

        return {"app": "stock", "turn": self.world.turn}

    def action(self, body: dict[str, Any]) -> dict[str, Any]:
        why = actions.act(self.world, self.player_id(), body)
        if why is None:
            self.autosave()
        return {"ok": why is None, "why": why, "state": view.snapshot(self.world)}

    def forecast(self, body: dict[str, Any]) -> dict[str, Any]:
        why = actions.check(self.world, self.world.nations[self.player_id()], body)
        if why:
            return {"ok": False, "why": why}
        return {"ok": True, "delta": turn.forecast(self.world, self.player_id(), body)}

    def end_turn(self, _body: dict[str, Any]) -> dict[str, Any]:
        if self.world.nations[self.player_id()].decisions:
            raise ApiError(409, "Answer the waiting decision first.")
        turn.end_turn(self.world)
        self.autosave()
        return view.snapshot(self.world)

    def regent(self, body: dict[str, Any]) -> dict[str, Any]:
        """A regent rules for a while: the same AI as the rivals, playing our people."""

        me = self.world.nations[self.player_id()]
        for _ in range(max(1, min(int(body.get("turns", 1)), 50))):
            if self.world.winner is not None and not body.get("past_end"):
                break
            ai.take_turn(self.world, me)
            turn.end_turn(self.world)
        self.autosave()
        return view.snapshot(self.world)

    def new(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            self.world = generate(parse_spec(body.get("spec")))
        except (ValueError, TypeError) as exc:
            raise ApiError(422, str(exc)) from exc
        self.autosave()
        return view.snapshot(self.world)

    def list_saves(self, _body: dict[str, Any]) -> dict[str, Any]:
        return {"saves": saves.list_saves(), "folder": saves.where()}

    def save(self, body: dict[str, Any]) -> dict[str, Any]:
        meta = saves.meta_of(self.world)
        name = str(body.get("name") or f"{meta['people']} - turn {meta['turn']}").strip()
        if name == saves.AUTOSAVE:
            raise ApiError(422, "That name is kept for the autosave.")
        try:
            saves.save(self.world, name)
        except ValueError as exc:
            raise ApiError(422, str(exc)) from exc
        except OSError as exc:
            raise ApiError(507, f"The game could not be saved: {exc}") from exc
        return {"saves": saves.list_saves(), "saved": name}

    def load(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            self.world = saves.load(str(body.get("file", "")))
        except FileNotFoundError as exc:
            raise ApiError(404, "No such save.") from exc
        except Exception as exc:  # noqa: BLE001 - a spoiled file is the player's news, not a crash
            raise ApiError(422, f"That save could not be read: {exc}") from exc
        self.autosave()
        return view.snapshot(self.world)

    def delete_save(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            saves.delete(str(body.get("file", "")))
        except ValueError as exc:
            raise ApiError(422, str(exc)) from exc
        return {"saves": saves.list_saves()}
