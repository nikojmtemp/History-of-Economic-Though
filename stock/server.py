"""The web server: one game in memory, the player's snapshot over plain JSON.

GET  /                 the UI
GET  /state            the player's snapshot
GET  /scenario         the world spec (seed:nodes:nations) that regenerates this world
POST /action           one action: {"kind": ..., ...}; answers {ok, why, state}
POST /forecast         one action, previewed one turn ahead (§19.5)
POST /turn             end the turn
POST /regent           let the AI rule our people for {"turns": N} turns (it takes every decision)
POST /new              a new world: {"spec": "random:SEED:NODES:NATIONS"} or {} for a fresh seed
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from stock.game import actions, ai, turn, view
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
    app.state.last_seen = time.monotonic()  # the launcher quits when no page has called for a while

    @app.middleware("http")
    async def seen(request: Any, call_next: Any) -> Any:
        app.state.last_seen = time.monotonic()
        return await call_next(request)

    @app.get("/alive")
    def alive() -> dict[str, Any]:
        """The page's heartbeat; also how a second launch knows Stock is already running."""

        return {"app": "stock", "turn": game.world.turn}

    @app.get("/")
    def index() -> HTMLResponse:
        """The page, with each script and stylesheet stamped by its modification time so
        a browser never runs yesterday's code against today's server."""

        html = (WEB / "index.html").read_text(encoding="utf-8")
        for asset in ("app.js", "app.css", "tokens.css"):
            stamp = int((WEB / asset).stat().st_mtime)
            html = html.replace(f"/static/{asset}", f"/static/{asset}?v={stamp}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

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

    @app.post("/regent")
    def regent(body: dict[str, Any]) -> dict[str, Any]:
        """A regent rules for a while: the same AI as the rivals, playing our people."""

        with game.lock:
            me = game.world.nations[game.player_id()]
            for _ in range(max(1, min(int(body.get("turns", 1)), 50))):
                if game.world.winner is not None and not body.get("past_end"):
                    break
                ai.take_turn(game.world, me)
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
