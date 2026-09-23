"""The HTTP API the UI drives (stock/server.py)."""

from __future__ import annotations

import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from stock.server import create_app


def client() -> TestClient:
    return TestClient(create_app("random:7"))


def test_state_and_scenario() -> None:
    c = client()
    s = c.get("/state").json()
    assert s["turn"] == 1 and s["spec"] == "random:7:60:5"
    assert s["me"]["orders"]["labour"]["size"] > 0
    assert any(u["nation"] == s["me"]["id"] for u in s["units"])
    assert c.get("/scenario").json()["seed"] == 7
    assert c.get("/").status_code == 200


def test_actions_and_refusals() -> None:
    c = client()
    r = c.post("/action", json={"kind": "research", "key": "taming"}).json()
    assert r["ok"] and r["state"]["me"]["researching"] == "taming"
    r = c.post("/action", json={"kind": "research", "key": "division"}).json()
    assert not r["ok"] and r["why"] == "prerequisites not met"
    assert c.post("/action", json={"kind": "nonsense"}).json()["why"].startswith("unknown action")


def test_turns_advance_and_new_world() -> None:
    c = client()
    for _ in range(3):
        s = c.post("/turn", json={}).json()
    assert s["turn"] == 4
    s = c.post("/new", json={"spec": "random:9:40:3"}).json()
    assert s["turn"] == 1 and s["spec"] == "random:9:40:3" and len(s["nations"]) == 3
    assert c.post("/new", json={"spec": "nonsense"}).status_code == 422


def test_forecast() -> None:
    c = client()
    f = c.post("/forecast", json={"kind": "institution", "pillar": "property", "option": "herds"}).json()
    assert not f["ok"] and "Taming" in f["why"]


def test_a_regent_rules_for_a_while() -> None:
    c = client()
    s = c.post("/regent", json={"turns": 5}).json()
    assert s["turn"] == 6 and not s["me"]["decisions"]
    assert "routes" in s and "trade" in s["me"]
