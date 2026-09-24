"""The web build (scripts/build_web.py) and the browser side of the game (stock/browser.py)."""

from __future__ import annotations

import ast
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from stock import browser, saves

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_web  # noqa: E402


class FakeStorage:
    """window.localStorage, as Pyodide shows it to Python."""

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    @property
    def length(self) -> int:
        return len(self.items)

    def key(self, i: int) -> str | None:
        return list(self.items)[i] if i < len(self.items) else None

    def getItem(self, k: str) -> str | None:  # noqa: N802 - the browser's own names
        return self.items.get(k)

    def setItem(self, k: str, v: str) -> None:  # noqa: N802
        self.items[k] = v

    def removeItem(self, k: str) -> None:  # noqa: N802
        self.items.pop(k, None)


@pytest.fixture
def storage() -> Any:
    before = saves.STORE
    yield FakeStorage()
    saves.STORE = before


def ask(path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(browser.call(path, json.dumps(body) if body is not None else None))
    return out


def test_the_browser_plays_and_saves_in_its_own_storage(storage: FakeStorage) -> None:
    browser.start(storage)
    first = ask("/state")
    assert first["ok"] and first["data"]["turn"] == 1
    assert ask("/turn", {})["data"]["turn"] == 2
    assert "stock-save:autosave" in storage.items  # every change is autosaved, in the page's storage
    assert ask("/save", {"name": "Early"})["data"]["saved"] == "Early"
    listed = ask("/saves")["data"]["saves"]
    assert {s["file"] for s in listed} == {"autosave", "Early"}
    browser.start(storage)  # the page opened again: the game continues
    again = ask("/state")["data"]
    assert again["turn"] == 2 and "Welcome back" in again["note"]


def test_the_browser_reports_refusals_as_the_server_would(storage: FakeStorage) -> None:
    browser.start(storage)
    r = ask("/load", {"file": "nothing"})
    assert not r["ok"] and r["status"] == 404
    assert ask("/nowhere")["status"] == 404


def test_a_full_browser_storage_costs_the_save_not_the_game(storage: FakeStorage) -> None:
    def full(k: str, v: str) -> None:
        raise RuntimeError("QuotaExceededError")

    browser.start(storage)
    storage.setItem = full  # type: ignore[method-assign]
    assert ask("/turn", {})["ok"]  # the autosave fails quietly
    r = ask("/save", {"name": "Too much"})
    assert not r["ok"] and r["status"] == 507


def test_the_web_build_holds_the_page_and_the_engine(tmp_path: Path) -> None:
    site = build_web.build(tmp_path / "site")
    names = {p.name for p in site.iterdir()}
    assert {"index.html", "app.js", "boot.js", "stock.zip", "icon.png", ".nojekyll"} <= names
    html = (site / "index.html").read_text(encoding="utf-8")
    assert "/static/" not in html  # relative paths: it works under any Pages sub-path
    assert html.index("pyodide.js") < html.index("boot.js") < html.index("app.js?v=")
    with zipfile.ZipFile(site / "stock.zip") as z:
        files = set(z.namelist())
    assert "stock/game/turn.py" in files and "stock/browser.py" in files
    assert "stock/server.py" not in files and "stock/launch.py" not in files


def test_the_engine_needs_nothing_pyodide_lacks() -> None:
    """Everything in the web zip imports only the standard library and stock itself."""

    allowed = set(sys.stdlib_module_names) | {"stock"}
    paths = [ROOT / "stock" / n for n in build_web.ENGINE] + list((ROOT / "stock" / "game").glob("*.py"))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            else:
                continue
            assert set(roots) <= allowed | {"__future__"}, f"{path.name} imports {roots}"
