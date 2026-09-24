"""Saved games (design doc §19.10): an autosave after everything the player does, named saves,
and the last game continued on launch.

A save is one gzip file, `<name>.stock`, in the player's saves folder (on the web, the
browser's own storage: stock/browser.py):

    STOCKSAVE <format>\\n  {json: people, turn, year, age, spec, saved}\\n  <the pickled World>

The JSON line lets the saves list be read without unpickling every world. A save from an
older build is upgraded on load: any field it lacks takes its default, so adding state to
the game never strands a saved game.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import os
import pickle
import re
import sys
import time
from pathlib import Path
from typing import Any, Protocol

from stock.game import rules
from stock.game.state import World

FORMAT = 1
MAGIC = b"STOCKSAVE"
SUFFIX = ".stock"
AUTOSAVE = "autosave"
_NAME = re.compile(r"^[\w .,'()-]{1,60}$")


def saves_dir() -> Path:
    """Where saves live: `STOCK_SAVES` if set (tests), else the usual per-user place."""

    if os.environ.get("STOCK_SAVES"):
        folder = Path(os.environ["STOCK_SAVES"])
    elif sys.platform == "win32":
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Stock" / "saves"
    elif sys.platform == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "Stock" / "saves"
    else:
        folder = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "stock" / "saves"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def check_name(name: str) -> str:
    """The save's name as stored, or ValueError: names never reach outside the saves."""

    if not _NAME.match(name) or name.strip(" .") != name.strip():
        raise ValueError("a save's name uses letters, digits, spaces and - _ . , ' ( ) only")
    return name.strip()


class Store(Protocol):
    """Where save files are kept: a folder on the desktop, the browser's storage on the web."""

    def names(self) -> list[str]: ...
    def read(self, name: str) -> bytes: ...  # FileNotFoundError when there is none
    def write(self, name: str, data: bytes) -> None: ...
    def delete(self, name: str) -> None: ...
    def where(self) -> str: ...


class FileStore:
    def _path(self, name: str) -> Path:
        return saves_dir() / f"{name}{SUFFIX}"

    def names(self) -> list[str]:
        return [p.stem for p in saves_dir().glob(f"*{SUFFIX}")]

    def read(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    def write(self, name: str, data: bytes) -> None:
        path = self._path(name)
        tmp = path.with_suffix(".tmp")  # written aside, then swapped in: a crash never spoils a save
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def where(self) -> str:
        return str(saves_dir())


STORE: Store = FileStore()  # the browser build puts its own in place (stock/browser.py)


def where() -> str:
    return STORE.where()


def meta_of(world: World) -> dict[str, Any]:
    p = world.player()
    return {
        "people": p.name if p else "?",
        "turn": world.turn,
        "year": rules.year_of(world.turn),
        "age": rules.MODE_NAMES.get(p.mode, "") if p else "",
        "spec": world.spec,
        "over": bool(world.winner),
        "saved": time.time(),
    }


def save(world: World, name: str) -> dict[str, Any]:
    """Write `world` as `name`; returns its listing entry."""

    stem = check_name(name)
    meta = meta_of(world)
    body = MAGIC + b" " + str(FORMAT).encode() + b"\n" + json.dumps(meta).encode() + b"\n"
    body += pickle.dumps(world, protocol=pickle.HIGHEST_PROTOCOL)
    STORE.write(stem, gzip.compress(body, 6))
    return {"file": stem, **meta}


def _read(name: str) -> tuple[dict[str, Any], bytes]:
    raw = gzip.decompress(STORE.read(name))
    head, meta_line, blob = raw.split(b"\n", 2)
    if not head.startswith(MAGIC):
        raise ValueError(f"{name} is not a Stock save")
    return json.loads(meta_line), blob


def list_saves() -> list[dict[str, Any]]:
    """Every save, the newest first; the autosave flagged."""

    out = []
    for name in STORE.names():
        try:
            meta, _ = _read(name)
        except (OSError, ValueError, EOFError):
            continue
        out.append({"file": name, "auto": name == AUTOSAVE, **meta})
    return sorted(out, key=lambda m: -float(m.get("saved", 0)))


def load(name: str) -> World:
    _meta, blob = _read(check_name(name))
    world = pickle.loads(blob)  # noqa: S301 - the player's own saves, from their own storage
    if not isinstance(world, World):
        raise ValueError(f"{name} holds no world")
    upgrade(world)
    return world


def delete(name: str) -> None:
    STORE.delete(check_name(name))


def exists(name: str) -> bool:
    try:
        return check_name(name) in STORE.names()
    except ValueError:
        return False


def upgrade(obj: Any, seen: set[int] | None = None) -> None:
    """Give every dataclass in a loaded world the fields it lacks (a save from an older build)."""

    seen = seen if seen is not None else set()
    if id(obj) in seen:
        return
    seen.add(id(obj))
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        for f in dataclasses.fields(obj):
            if f.name not in vars(obj):
                if f.default is not dataclasses.MISSING:
                    setattr(obj, f.name, f.default)
                elif f.default_factory is not dataclasses.MISSING:
                    setattr(obj, f.name, f.default_factory())
            upgrade(getattr(obj, f.name, None), seen)
    elif isinstance(obj, dict):
        for v in obj.values():
            upgrade(v, seen)
    elif isinstance(obj, list):
        for v in obj:
            upgrade(v, seen)
