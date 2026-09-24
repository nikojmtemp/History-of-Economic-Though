"""Saved games (stock/saves.py and the server's save routes)."""

from __future__ import annotations

import warnings

import pytest

from stock import saves
from stock.game import turn
from stock.game.worldgen import generate

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from stock.server import Game, create_app


@pytest.fixture(autouse=True)
def _clean_saves() -> None:
    for f in saves.saves_dir().glob("*"):
        f.unlink()


def test_a_saved_world_comes_back_the_same() -> None:
    w = generate(seed=5)
    for _ in range(12):
        turn.end_turn(w)
    entry = saves.save(w, "My people")
    assert entry["turn"] == w.turn and entry["file"] == "My people"
    back = saves.load("My people")
    assert back.turn == w.turn
    assert [n.hands for n in back.nodes.values()] == [n.hands for n in w.nodes.values()]
    turn.end_turn(w)
    turn.end_turn(back)  # the same seed of chance travels with it: the next turn matches
    assert [n.history for n in back.nations.values()] == [n.history for n in w.nations.values()]


def test_an_old_save_gains_the_fields_it_lacks() -> None:
    w = generate(seed=5)
    nd = next(iter(w.nodes.values()))
    del nd.__dict__["tier"], nd.__dict__["improved"]  # as a save from before settlements grew
    saves.upgrade(w)
    assert nd.tier == 0 and nd.improved == {}


def test_names_stay_inside_the_saves_folder() -> None:
    w = generate(seed=5)
    for bad in ("../escape", "a/b", "", "x" * 61):
        with pytest.raises(ValueError):
            saves.save(w, bad)


def test_the_saves_list_reads_without_loading() -> None:
    w = generate(seed=5)
    saves.save(w, "first")
    turn.end_turn(w)
    saves.save(w, "second")
    listed = saves.list_saves()
    assert [s["file"] for s in listed] == ["second", "first"]  # newest first
    assert listed[0]["turn"] == 2 and listed[0]["people"]


def test_the_server_autosaves_and_continues_the_last_game() -> None:
    c = TestClient(create_app())
    c.post("/new", json={"spec": "random:9:40:3"})
    c.post("/turn")
    assert saves.exists(saves.AUTOSAVE)
    again = Game()  # the app opened again
    assert again.world.turn == 2 and again.world.spec == "random:9:40:3"
    assert again.note and "turn 2" in again.note


def test_save_load_and_delete_through_the_server() -> None:
    c = TestClient(create_app("random:7"))
    r = c.post("/save", json={"name": "Before the war"}).json()
    assert r["saved"] == "Before the war" and any(s["file"] == "Before the war" for s in r["saves"])
    c.post("/turn")
    s = c.post("/load", json={"file": "Before the war"}).json()
    assert s["turn"] == 1
    assert c.post("/save", json={"name": "autosave"}).status_code == 422
    assert c.post("/load", json={"file": "nothing here"}).status_code == 404
    left = c.post("/delete_save", json={"file": "Before the war"}).json()["saves"]
    assert all(x["file"] != "Before the war" for x in left)


def test_a_spoiled_autosave_starts_a_new_world() -> None:
    (saves.saves_dir() / f"{saves.AUTOSAVE}{saves.SUFFIX}").write_bytes(b"not a save")
    g = Game()
    assert g.world.turn == 1 and g.note and "could not be read" in g.note
