"""The desktop web server: the page, and the game's service (stock/service.py) over HTTP.

GET  /                 the UI
GET  /static/...       its scripts, styles and icon
...                    every route of stock/service.py, as GET or POST with a JSON body

The browser build (scripts/build_web.py) serves the same page from static hosting and calls
the service in the page itself, through Pyodide, instead of over HTTP.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from stock.service import ApiError, Game

__all__ = ["Game", "create_app"]

WEB = Path(__file__).resolve().parent / "web"
GETS = ("/state", "/scenario", "/alive", "/saves")


def create_app(spec: str | None = None) -> FastAPI:
    app = FastAPI(title="Stock")
    game = Game(spec)
    app.state.game = game
    app.state.last_seen = time.monotonic()  # the launcher quits when no page has called for a while

    @app.middleware("http")
    async def seen(request: Any, call_next: Any) -> Any:
        app.state.last_seen = time.monotonic()
        return await call_next(request)

    @app.get("/")
    def index() -> HTMLResponse:
        """The page, with each script and stylesheet stamped by its modification time so
        a browser never runs yesterday's code against today's server."""

        html = (WEB / "index.html").read_text(encoding="utf-8")
        for asset in ("app.js", "app.css", "tokens.css"):
            stamp = int((WEB / asset).stat().st_mtime)
            html = html.replace(f"/static/{asset}", f"/static/{asset}?v={stamp}")
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    def answer(path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return game.call(path, body)
        except ApiError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    def getter(path: str) -> Any:
        def get() -> dict[str, Any]:
            return answer(path, None)

        return get

    def poster(path: str) -> Any:
        def post(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # noqa: B008
            return answer(path, body)

        return post

    for path in game.routes:
        if path in GETS:
            app.add_api_route(path, getter(path), methods=["GET"])
        else:
            app.add_api_route(path, poster(path), methods=["POST"])

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app


app = create_app()
