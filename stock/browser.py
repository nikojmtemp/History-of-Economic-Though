"""The game in the browser (Pyodide): the service (stock/service.py) called straight from the
page, and saves kept in the browser's own storage instead of a folder.

The page's loader (stock/web/boot.js, in the web build only) unpacks the engine, calls
`start(window.localStorage)`, and then sends every request the UI makes to `call`.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from stock import saves
from stock.service import ApiError, Game

PREFIX = "stock-save:"


class BrowserStore:
    """Saves as base64 text in localStorage, one key each. A save is about 70 KB there, so the
    usual 5 MB allowance holds some seventy."""

    def __init__(self, storage: Any) -> None:
        self.storage = storage  # window.localStorage, through Pyodide

    def names(self) -> list[str]:
        keys = [self.storage.key(i) for i in range(int(self.storage.length))]
        return [k[len(PREFIX) :] for k in keys if k and str(k).startswith(PREFIX)]

    def read(self, name: str) -> bytes:
        text = self.storage.getItem(PREFIX + name)
        if text is None:
            raise FileNotFoundError(name)
        return base64.b64decode(str(text))

    def write(self, name: str, data: bytes) -> None:
        try:
            self.storage.setItem(PREFIX + name, base64.b64encode(data).decode("ascii"))
        except Exception as exc:  # the browser's QuotaExceededError, or storage turned off
            raise OSError("the browser's storage for this page is full or turned off") from exc

    def delete(self, name: str) -> None:
        self.storage.removeItem(PREFIX + name)

    def where(self) -> str:
        return "this browser's storage for this page (clearing the site's data deletes them)"


_game: Game | None = None


def start(storage: Any) -> None:
    """Saves go to `storage`; the game continues the autosave there, if any."""

    global _game
    saves.STORE = BrowserStore(storage)
    _game = Game()


def call(path: str, body_json: str | None = None) -> str:
    """One request from the page, answered as JSON text: {"ok", "data"} or {"ok", "status",
    "detail"}, as the desktop server would answer over HTTP."""

    assert _game is not None, "start() first"
    try:
        body = json.loads(body_json) if body_json else None
        return json.dumps({"ok": True, "data": _game.call(path, body)}, default=str)
    except ApiError as exc:
        return json.dumps({"ok": False, "status": exc.status, "detail": exc.detail})
    except Exception as exc:  # noqa: BLE001 - a crash is reported to the page, not swallowed
        return json.dumps({"ok": False, "status": 500, "detail": f"{type(exc).__name__}: {exc}"})
