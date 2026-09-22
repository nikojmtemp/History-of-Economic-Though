"""Doc 07 acceptance: `/state` returns a valid Snapshot; posting an unaffordable
ENACT returns 422 with the three numbers; a WebSocket client receives one Snapshot
per year and the event list.

Years are advanced via `GameSession.advance_one_year()`, the injectable seam
`stock/api/server.py` documents on that method.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock.api.schemas import Snapshot
from stock.api.server import GameSession, create_app
from stock.core.actions import Action, ActionKind
from stock.core.world import SeatKind

SCENARIO = "tests/scenarios/three_bands_ai.yaml"


def _session(app: FastAPI) -> GameSession:
    session: GameSession = app.state.session
    return session


@pytest.fixture()
def app() -> FastAPI:
    return create_app(SCENARIO)


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_state_returns_a_valid_snapshot(client: TestClient) -> None:
    r = client.get("/state")
    assert r.status_code == 200
    snapshot = Snapshot.model_validate(r.json())
    assert snapshot.header.year == 0
    assert snapshot.player_nation
    assert len(snapshot.map.nodes) > 0


def test_state_rejects_unknown_nation(client: TestClient) -> None:
    r = client.get("/state", params={"nation": "does_not_exist"})
    assert r.status_code == 404


def _advance_to_state_seat(app: FastAPI, max_years: int = 400) -> str:
    # The player's band never settles on its own (engine/band.py): settle it the way
    # a player would, then let the seat progress.
    session = _session(app)
    session.enqueue_action(Action(kind=ActionKind.BAND_SETTLE, nation=session.player_nation, payload={}))
    for _ in range(max_years):
        if session.world.nations[session.player_nation].seat is SeatKind.STATE:
            break
        session.advance_one_year()
    return session.player_nation


def test_unaffordable_enact_returns_422_with_three_numbers(app: FastAPI, client: TestClient) -> None:
    nation = _advance_to_state_seat(app)
    session = _session(app)
    assert session.world.nations[nation].seat is SeatKind.STATE, "fixture never reached STATE seat"
    # Force the shortfall deterministically rather than hoping a scenario nation is poor.
    session.world.nations[nation].scalars.A_S = 1.0

    r = client.post("/action", json={"nation": nation, "kind": "ENACT", "payload": {"law": "LAND_TAX"}})

    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "insufficient A_S"
    assert set(body["numbers"]) == {"cost", "available", "shortfall"}
    assert body["numbers"]["available"] == pytest.approx(1.0)
    assert body["numbers"]["shortfall"] == pytest.approx(body["numbers"]["cost"] - 1.0)


def test_affordable_enact_queues_and_resolves_next_year(app: FastAPI, client: TestClient) -> None:
    nation = _advance_to_state_seat(app)
    session = _session(app)
    session.world.nations[nation].scalars.A_S = 1_000_000.0

    r = client.post("/action", json={"nation": nation, "kind": "ENACT", "payload": {"law": "LAND_TAX"}})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["queued_id"]

    snap = Snapshot.model_validate(client.get("/state").json())
    assert any(q.id == body["queued_id"] for q in snap.now.queued)

    session.advance_one_year()
    snap_after = Snapshot.model_validate(client.get("/state").json())
    assert not any(q.id == body["queued_id"] for q in snap_after.now.queued)
    assert any(e.kind == "resolved_enact" for e in snap_after.now.events)
    # ... and the law is actually in force: the quoted cost was spent to pass its bar.
    from stock.core.laws import LawId

    state = session.world.nations[nation].laws.get(LawId.LAND_TAX)
    assert state is not None and state.enacted


def test_unknown_action_kind_returns_422(client: TestClient) -> None:
    r = client.post("/action", json={"nation": "nation_valley", "kind": "NOT_A_KIND", "payload": {}})
    assert r.status_code == 422


def test_turn_runs_one_year_and_answers_with_the_snapshot(app: FastAPI, client: TestClient) -> None:
    session = _session(app)
    r = client.post("/turn")
    assert r.status_code == 200
    snap = Snapshot.model_validate(r.json())
    assert snap.header.year == 1 and session.world.year == 1
    assert client.post("/turn", params={"nation": "nobody"}).status_code == 404
    assert session.world.year == 1


def test_turn_broadcasts_to_websocket_clients(app: FastAPI) -> None:
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        assert json.loads(ws.receive_text())["header"]["year"] == 0
        assert client.post("/turn").status_code == 200
        assert json.loads(ws.receive_text())["header"]["year"] == 1


def test_websocket_receives_one_snapshot_per_year(app: FastAPI) -> None:
    session = _session(app)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        initial = json.loads(ws.receive_text())
        assert initial["header"]["year"] == 0

        session.advance_one_year()
        # `/turn` broadcasts on its own; this exercises the seam directly.
        asyncio.run(_broadcast_now(app))
        msg = json.loads(ws.receive_text())
        assert msg["header"]["year"] == 1


async def _broadcast_now(app: FastAPI) -> None:
    from stock.api.server import _broadcast

    await _broadcast(app.state.session)


def test_ledger_endpoint_returns_rows_for_nation(app: FastAPI, client: TestClient) -> None:
    session = _session(app)
    session.advance_one_year()
    r = client.get(f"/ledger/{session.player_nation}")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["nation"] == session.player_nation

    r2 = client.get("/ledger/no_such_nation")
    assert r2.status_code == 404


# --- Doc 07 "Actions — draft, cost, boundary": every action drafted server-side ---


def _offers(client: TestClient, kind: str) -> list[dict]:
    snap = client.get("/state").json()
    return [o for o in snap["actions"] if o["kind"] == kind]


def test_band_offers_move_to_unclaimed_neighbours_with_ground_numbers(client: TestClient) -> None:
    snap = Snapshot.model_validate(client.get("/state").json())
    assert snap.player is not None and snap.player.seat == "BAND"
    moves = [o for o in snap.actions if o.kind == "BAND_MOVE"]
    assert moves, "a band at year 0 has unclaimed neighbours to move to"
    by_id = {n.id: n for n in snap.map.nodes}
    for o in moves:
        node = by_id[o.payload["to"]]
        assert node.nation is None and node.adjacent_to_player
        assert o.location == node.id and o.affordable
        assert o.label == f"Move to {node.name}"
    home = by_id[snap.player.home or ""]
    assert home.is_player and home.ground_quality >= 0.0


def test_player_band_is_not_settled_for_them(app: FastAPI, client: TestClient) -> None:
    # The opening is the player's: with nothing queued the valley band is still a
    # band on its start location years later (the null-sovereign heuristic would have
    # settled it), and the move offers keep coming with the move's consensus cost.
    session = _session(app)
    for _ in range(12):
        session.advance_one_year()
    snap = Snapshot.model_validate(client.get("/state").json())
    assert snap.player is not None and snap.player.seat == "BAND" and snap.player.home == "valley_1"
    moves = _offers(client, "BAND_MOVE")
    assert moves and all(o["cost"] > 0 for o in moves)


def test_band_move_pre_empted_by_settling_is_not_applied(app: FastAPI, client: TestClient) -> None:
    # Settle and move queued the same year: the settle applies first and hands the
    # seat over, so the move is illegal by the time step 14 reaches it — the feed
    # must say "not applied", never "moved".
    session = _session(app)
    offer = _offers(client, "BAND_MOVE")[0]
    for kind, payload in (("BAND_SETTLE", {}), ("BAND_MOVE", offer["payload"])):
        r = client.post("/action", json={"nation": session.player_nation, "kind": kind, "payload": payload})
        assert r.status_code == 200, r.text
    session.advance_one_year()
    snap = Snapshot.model_validate(client.get("/state").json())
    assert snap.player is not None and snap.player.home == "valley_1" and snap.player.seat != "BAND"
    kinds = {e.kind for e in snap.now.events}
    assert "rejected_band_move" in kinds and "resolved_band_move" not in kinds
    entry = next(e for e in snap.now.events if e.kind == "rejected_band_move")
    assert entry.text == f"{offer['label']} · Not applied"


def test_posting_a_drafted_band_move_relocates_the_band() -> None:
    # The forest band starts on game+timber only: it can neither settle nor tame
    # where it stands, so it is still a band when the queued move applies at step 14.
    app = create_app(SCENARIO, player_nation="nation_forest")
    client = TestClient(app)
    session = _session(app)
    offer = _offers(client, "BAND_MOVE")[0]
    body = {"nation": "nation_forest", "kind": "BAND_MOVE", "payload": offer["payload"]}
    r = client.post("/action", json=body)
    assert r.status_code == 200, r.text
    snap = client.get("/state").json()
    assert any(q["label"] == offer["label"] for q in snap["now"]["queued"])
    session.advance_one_year()
    snap_after = Snapshot.model_validate(client.get("/state").json())
    assert snap_after.player is not None and snap_after.player.home == offer["payload"]["to"]
    assert any(e.kind == "resolved_band_move" and offer["label"] in e.text for e in snap_after.now.events)


def test_sovereign_offers_carry_cost_and_shortfall(app: FastAPI, client: TestClient) -> None:
    nation = _advance_to_state_seat(app)
    session = _session(app)
    session.world.nations[nation].scalars.A_S = 0.0
    snap = Snapshot.model_validate(client.get("/state").json())
    kinds = {o.kind for o in snap.actions}
    assert {"DECLARE_WAR", "PROPOSE_TREATY", "REPRESS", "SET_BUDGET", "SET_DEBT_POLICY"} <= kinds
    war = next(o for o in snap.actions if o.kind == "DECLARE_WAR")
    assert war.confirm and not war.affordable
    assert war.shortfall == pytest.approx(war.cost)
    assert war.label.startswith("Declare war · ")
    debt = [o for o in snap.actions if o.kind == "SET_DEBT_POLICY"]
    default = next(o for o in debt if o.payload["policy"] == "DEFAULT")
    assert default.confirm
    enacts = [law for law in snap.panels.politics.laws if law.enact is not None]
    assert enacts and all(law.label and law.enact is not None and law.enact.kind == "ENACT" for law in enacts)
    assert snap.panels.politics.set_focus is not None
    assert snap.panels.politics.focus_options


def test_treaty_proposal_terms_are_decoded_for_the_engine(app: FastAPI, client: TestClient) -> None:
    from stock.trade.treaties import Term

    nation = _advance_to_state_seat(app)
    session = _session(app)
    session.world.nations[nation].scalars.A_S = 1_000_000.0
    target = next(n for n in session.world.nations if n != nation)
    r = client.post(
        "/action",
        json={
            "nation": nation,
            "kind": "PROPOSE_TREATY",
            "payload": {
                "target": target,
                "terms": [{"kind": "NON_AGGRESSION"}, {"kind": "TARIFF_CEILING", "rate": 0.05}],
            },
        },
    )
    assert r.status_code == 200, r.text
    queued = session.world.nations[nation].queue[-1]
    assert all(isinstance(t, Term) for t in queued.payload["terms"])
    assert queued.payload["terms"][1].rate == pytest.approx(0.05)
    bad_payload = {"target": target, "terms": [{"kind": "NOPE"}]}
    bad = client.post("/action", json={"nation": nation, "kind": "PROPOSE_TREATY", "payload": bad_payload})
    assert bad.status_code == 422


def test_snapshot_carries_names_and_labels(client: TestClient) -> None:
    snap = Snapshot.model_validate(client.get("/state").json())
    assert set(snap.names.locations) == {n.id for n in snap.map.nodes}
    assert all(n.name == snap.names.locations[n.id] for n in snap.map.nodes)
    assert snap.labels["symbol"]["A_S"] == "State authority"
    assert snap.labels["class"]["HERD_OWNERS"] == "Herd owners"
    assert all(n.name for n in snap.nations)


def test_trees_panel_lists_every_node_in_chain_order(client: TestClient) -> None:
    from stock.core.trees import CREDIT_CHAIN, DEFENCE_CHAIN, PRODUCTION_CHAIN, TreeINode

    snap = Snapshot.model_validate(client.get("/state").json())
    trees = snap.panels.trees
    assert [c.id for c in trees.tree2] == ["production", "defence", "credit"]
    assert [n.id for n in trees.tree2[0].nodes] == [m.name for m in PRODUCTION_CHAIN]
    assert [n.id for n in trees.tree2[1].nodes] == [m.name for m in DEFENCE_CHAIN]
    assert [n.id for n in trees.tree2[2].nodes] == [m.name for m in CREDIT_CHAIN]
    assert trees.tree1
    assert all([n.id for n in c.nodes] == [m.name for m in TreeINode] for c in trees.tree1)
    assert all(c.label == snap.names.locations[c.location or ""] for c in trees.tree1)


def test_ledger_and_capital_rows_show_the_production_to_consumption_link(
    app: FastAPI, client: TestClient
) -> None:
    # Doc 07 (A75): each record says where its income came from and what it bought;
    # each producer says what it made, who worked it, who owns it and who was paid.
    nation = _advance_to_state_seat(app)
    session = _session(app)
    for _ in range(3):
        session.advance_one_year()
    snap = Snapshot.model_validate(client.get("/state").json())
    panels = snap.panels
    home = session.world.nations[nation].locations(session.world)[0].id
    tenants = next(r for r in panels.ledger if r.location == home and r.cls == "TENANTS")
    assert tenants.income > 0 and tenants.works_at.get("FIELD", 0) > 0
    field_source = next(s for s in tenants.sources if s.producer == "FIELD")
    # what the field paid, less what taxation took before consumption, is the income
    assert field_source.wages + field_source.profit + field_source.rent >= tenants.income * (1 - 1e-6)
    assert tenants.paid == pytest.approx(sum(s.wages + s.profit + s.rent for s in tenants.sources))
    assert tenants.taxed == pytest.approx(max(0.0, tenants.paid - tenants.income))
    assert sum(tenants.spend_by_good.values()) + tenants.saved == pytest.approx(tenants.income, rel=1e-6)

    field = next(r for r in panels.capital if r.location == home and r.kind == "FIELD")
    assert field.makes.get("PROVISIONS", 0) > 0
    assert field.worked_by == {"TENANTS": pytest.approx(field.jobs_filled)}
    assert sum(field.owned_by.values()) == pytest.approx(1.0)
    paid = sum(field.wages_to.values()) + sum(field.profit_to.values()) + sum(field.rent_to.values())
    assert paid == pytest.approx(field.V, rel=1e-6)

    # an occupation pays no wage: its whole output is its workers' own labour
    hunting = next((r for r in panels.capital if r.kind == "HUNTING"), None)
    if hunting is not None and hunting.V > 0:
        assert sum(hunting.wages_to.values()) == pytest.approx(hunting.V)

    flow = next(t for t in panels.territories if t.location == home)
    assert flow.made_value > 0 and flow.spent_total > 0
    assert flow.income_total == pytest.approx(sum(r.income for r in panels.ledger if r.location == home))


def test_the_game_starts_on_a_fresh_generated_world_and_can_start_over() -> None:
    # A78: no scenario given -> a random world with a seed nobody chose, named so it
    # can be played again; /new regenerates (named or fresh) for the same clients.
    from stock.sim.worldgen import parse_random_spec

    c = TestClient(create_app())
    first = c.get("/scenario").json()["name"]
    cfg = parse_random_spec(first)
    assert cfg is not None and cfg.seed >= 1 and cfg.locations == 24 and cfg.nations == 3
    assert TestClient(create_app()).get("/scenario").json()["name"] != first  # a fresh seed each start

    r = c.post("/new", json={"scenario": "random:42:30:4"})
    assert r.status_code == 200
    snap = Snapshot.model_validate(r.json())
    assert snap.header.year == 0 and len(snap.map.nodes) == 30 and len(snap.nations) == 4
    assert c.get("/scenario").json()["name"] == "random:42:30:4"
    assert c.post("/new", json={"scenario": "random:1:8:5"}).status_code == 422  # too many nations
    assert c.post("/new", json={"scenario": "no/such/file.yaml"}).status_code == 422

    # the authored map is still loadable by path, as a test fixture
    r = c.post("/new", json={"scenario": SCENARIO})
    assert r.status_code == 200 and c.get("/scenario").json()["name"] == "three_bands_ai"
