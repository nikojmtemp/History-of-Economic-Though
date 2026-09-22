"""The web server: one game in memory, the player's snapshot over plain JSON.

GET  /                 the UI
GET  /state            the player's snapshot
GET  /scenario         the world spec (seed:nodes:nations) that regenerates this world
POST /action           one action: {"kind": ..., ...}; answers {ok, why, state}
POST /forecast         one action, previewed one turn ahead (§19.5)
POST /turn             end the turn
POST /new              a new world: {"spec": "random:SEED:NODES:NATIONS"} or {} for a fresh seed
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from stock.game import actions, turn, view
from stock.game.state import World
from stock.game.worldgen import generate, parse_spec

WEB = Path(__file__).resolve().parent / "web"


class Game:
    def __init__(self, spec: str | None = None) -> None:
        self.lock = threading.Lock()
        self.world: World = generate(parse_spec(spec))

    def player_id(self) -> str:
        p = self.world.player()
        assert p is not None
        return p.id


def create_app(spec: str | None = None) -> FastAPI:
    app = FastAPI(title="Stock")
    game = Game(spec)
    app.state.game = game

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/state")
    def state() -> dict[str, Any]:
        with game.lock:
            return view.snapshot(game.world)

    @app.get("/scenario")
    def scenario() -> dict[str, Any]:
        return {"spec": game.world.spec, "seed": game.world.seed}

    @app.post("/action")
    def action(body: dict[str, Any]) -> dict[str, Any]:
        with game.lock:
            why = actions.act(game.world, game.player_id(), body)
            return {"ok": why is None, "why": why, "state": view.snapshot(game.world)}

    @app.post("/forecast")
    def forecast(body: dict[str, Any]) -> dict[str, Any]:
        with game.lock:
            why = actions.check(game.world, game.world.nations[game.player_id()], body)
            if why:
                return {"ok": False, "why": why}
            return {"ok": True, "delta": turn.forecast(game.world, game.player_id(), body)}

    @app.post("/turn")
    def end_turn() -> dict[str, Any]:
        with game.lock:
            me = game.world.nations[game.player_id()]
            if me.decisions:
                raise HTTPException(409, "Answer the waiting decision first.")
            turn.end_turn(game.world)
            return view.snapshot(game.world)

    @app.post("/new")
    def new(body: dict[str, Any]) -> dict[str, Any]:
        with game.lock:
            try:
                game.world = generate(parse_spec(body.get("spec")))
            except (ValueError, TypeError) as exc:
                raise HTTPException(422, str(exc)) from exc
            return view.snapshot(game.world)

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()
