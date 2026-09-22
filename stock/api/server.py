"""The FastAPI server (Doc 07): serves the static frontend, the REST endpoints, and a
`/ws` snapshot stream. The game proceeds turn by turn: `POST /turn` runs exactly one
year and broadcasts the snapshot (DEVIATIONS-IN-PROGRESS.md A73).

`GameSession.advance_one_year()` is the test/UI-injectable seam the spec's own acceptance
needs ("a WebSocket client receives one Snapshot per year"): `/turn` and a test both
call it directly, one simulated year at a time.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from stock.api.schemas import ActionRequest, ActionResult, NewWorldRequest, ScenarioInfo, Snapshot
from stock.api.snapshot import build_snapshot
from stock.core.actions import Action, ActionKind, enqueue
from stock.core.goods import Good
from stock.core.laws import FocusKind, LawId
from stock.core.records import InterestId
from stock.core.world import World
from stock.sim.ledger import EventRecord
from stock.sim.scenario import load_scenario
from stock.sim.worldgen import new_world_spec, parse_random_spec
from stock.sim.year import run_year
from stock.trade.treaties import Term, TermKind
from stock.ui.labels import describe_action
from stock.ui.names import names_for

STATIC_DIR = Path(__file__).resolve().parent.parent / "ui" / "static"
# The game is played on a procedurally generated world (`sim/worldgen`): with no
# scenario given, `create_app` draws a fresh seed. The authored maps live under
# `tests/scenarios/` and are test fixtures only (A78).


class _RevalidatingStaticFiles(StaticFiles):
    """The front end is plain ES modules edited in place; without this the browser
    keeps a stale `main.js` (and its imports) across server restarts."""

    async def get_response(self, path: str, scope: Any) -> Any:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _pick_player_nation(world: World) -> str:
    candidates = sorted(nid for nid, n in world.nations.items() if n.ai is None)
    if candidates:
        return candidates[0]
    return sorted(world.nations)[0]


def _decode_law(value: Any) -> Any:
    if isinstance(value, str) and value in LawId.__members__:
        return LawId[value]
    return value


def _decode_terms(raw: Any, *, bound: str, beneficiary: str) -> list[Term]:
    """Treaty terms arrive as `{"kind": "NON_AGGRESSION", ...}` dicts (or bare kind
    names); the engine wants `trade.treaties.Term` objects binding the target for the
    proposer's benefit."""

    terms: list[Term] = []
    for item in raw or []:
        if isinstance(item, Term):
            terms.append(item)
            continue
        spec = {"kind": item} if isinstance(item, str) else dict(item)
        kind_name = str(spec.get("kind", ""))
        if kind_name not in TermKind.__members__:
            raise ValueError(f"unknown treaty term {kind_name!r}")
        goods = tuple(Good[g] for g in spec.get("goods", []) if g in Good.__members__)
        terms.append(
            Term(
                kind=TermKind[kind_name],
                bound=str(spec.get("bound", bound)),
                beneficiary=str(spec.get("beneficiary", beneficiary)),
                goods=goods,
                rate=float(spec.get("rate", 0.0)),
                route_id=spec.get("route_id"),
                location=spec.get("location"),
                amount=float(spec.get("amount", 0.0)),
                years=int(spec.get("years", 0)),
            )
        )
    return terms


def _decode_payload(kind: ActionKind, nation: str, payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if "law" in out:
        out["law"] = _decode_law(out["law"])
    if "interest" in out and isinstance(out["interest"], str):
        out["interest"] = InterestId[out["interest"]]
    if kind in (ActionKind.SET_FOCUS,) and isinstance(out.get("kind"), str):
        out["kind"] = FocusKind[out["kind"]]
    if kind is ActionKind.PROPOSE_TREATY:
        target = str(out.get("target", ""))
        out["terms"] = _decode_terms(out.get("terms"), bound=target, beneficiary=nation)
    if kind is ActionKind.OFFER_PEACE:
        target = str(out.get("target", ""))
        out["treaty_terms"] = _decode_terms(out.get("treaty_terms"), bound=target, beneficiary=nation)
        out["cession"] = [str(x) for x in out.get("cession", [])]
        out["tribute_amount"] = float(out.get("tribute_amount", 0.0))
        out["tribute_years"] = int(out.get("tribute_years", 0))
    return out


@dataclass
class ResolvedEvent(EventRecord):
    """A ledger-shaped record for a queued action resolving at the boundary, plus
    the one-line description its chip carried — the engine never emits one for a
    player's own action (see `stock/ui/strings.py`), so the API synthesises it."""

    detail: str = ""


def _jsonable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k.startswith("_"):
            continue
        out[k] = v.name if hasattr(v, "name") and not isinstance(v, str) else v
    return out


class GameSession:
    """One running world plus the UI-facing bookkeeping the pure engine has no
    business holding: queued-action tracking (for the Now column's chips and for
    synthesising a feed entry when the engine itself emits none — see
    `stock/ui/strings.py`'s module docstring) and connected WebSocket clients."""

    def __init__(self, world: World, player_nation: str) -> None:
        self.world = world
        self.player_nation = player_nation
        # The engine's null-sovereign heuristics (band auto-move/settle, automatic
        # peace acceptance) step aside for a nation the player steers.
        world.nations[player_nation].ai = "player"
        self.pending: dict[str, dict[str, Any]] = {}
        self.synthetic_events: list[EventRecord] = []
        self.websockets: set[WebSocket] = set()
    def enqueue_action(self, action: Action) -> ActionResult:
        ui_id = uuid.uuid4().hex
        action.payload = {**action.payload, "_ui_id": ui_id}
        if action.kind in (ActionKind.ENACT, ActionKind.REPEAL) and "spend" not in action.payload:
            # The handler spends `payload["spend"]` to pass the bar (see api/offers.py);
            # a bare request spends whatever the bar costs at the boundary.
            action.payload["spend"] = "bar"
        result = enqueue(self.world, action)
        if not result.ok:
            numbers = dict(result.numbers)
            if result.reason == "insufficient A_S":
                numbers["shortfall"] = numbers.get("cost", 0.0) - numbers.get("available", 0.0)
            return ActionResult(ok=False, cost=result.cost, reason=result.reason, numbers=numbers)
        self.pending[ui_id] = {
            "nation": action.nation,
            "kind": action.kind,
            "action": action,  # the queued object itself: step 14 marks `_rejected` on its payload
            "cost": result.cost,
            "applies_year": self.world.year + 1,
            "label": describe_action(
                action.kind.name, _jsonable_payload(action.payload), names_for(self.world)
            ),
        }
        return ActionResult(ok=True, cost=result.cost, numbers=result.numbers, queued_id=ui_id)

    def withdraw_action(self, ui_id: str) -> bool:
        info = self.pending.get(ui_id)
        if info is None:
            return False
        nation = self.world.nations.get(info["nation"])
        if nation is None:
            return False
        for a in list(nation.queue):
            if a.payload.get("_ui_id") == ui_id:
                nation.queue.remove(a)
                del self.pending[ui_id]
                return True
        return False

    def queued_for(self, nation_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": uid,
                "kind": info["kind"].name,
                "label": info.get("label") or info["kind"].name.replace("_", " ").title(),
                "cost": info["cost"],
                "applies_year": info["applies_year"],
            }
            for uid, info in self.pending.items()
            if info["nation"] == nation_id
        ]

    def advance_one_year(self) -> None:
        """Run exactly one simulated year. The seam both the real-time driver and
        `tests/test_api.py` use, so a websocket test never races a real sleep."""

        before_ids: dict[str, set[str]] = {
            nid: {a.payload.get("_ui_id") for a in n.queue if "_ui_id" in a.payload}
            for nid, n in self.world.nations.items()
        }
        run_year(self.world)
        resolved_year = self.world.year - 1
        for nid, ids in before_ids.items():
            for uid in ids:
                info = self.pending.pop(uid, None)
                if info is None:
                    continue
                queued_action = info.get("action")
                payload = queued_action.payload if queued_action is not None else {}
                rejected = "_rejected" in payload
                spent = float(payload.get("_spent", info["cost"]))
                self.synthetic_events.append(
                    ResolvedEvent(
                        year=resolved_year,
                        nation=nid,
                        kind=f"{'rejected' if rejected else 'resolved'}_{info['kind'].name.lower()}",
                        numbers={} if rejected else {"cost": spent},
                        detail=str(info.get("label", "")),
                    )
                )
        self.synthetic_events = self.synthetic_events[-300:]
    def snapshot(self, nation_id: str | None = None) -> Snapshot:
        nid = nation_id or self.player_nation
        return build_snapshot(
            self.world,
            nid,
            queued=self.queued_for(nid),
            synthetic_events=self.synthetic_events,
        )


async def _broadcast(session: GameSession) -> None:
    if not session.websockets:
        return
    payload = session.snapshot().model_dump_json()
    dead = []
    for ws in session.websockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        session.websockets.discard(ws)


def _new_session(scenario_path: str | Path | None, player_nation: str | None) -> tuple[GameSession, str]:
    """A session on `scenario_path` (a file or a `random:...` spec; None = a fresh
    seed), and the spec or path that names its world."""

    resolved = str(scenario_path) if scenario_path is not None else new_world_spec()
    world = load_scenario(resolved)
    nation = player_nation or _pick_player_nation(world)
    return GameSession(world, nation), resolved


def create_app(scenario_path: str | Path | None = None, *, player_nation: str | None = None) -> FastAPI:
    session, resolved = _new_session(scenario_path, player_nation)

    app = FastAPI(title="Stock")
    app.state.session = session
    app.state.scenario = resolved

    @app.get("/state", response_model=Snapshot)
    def get_state(nation: str | None = None) -> Snapshot:
        s: GameSession = app.state.session
        if nation is not None and nation not in s.world.nations:
            raise HTTPException(404, f"no such nation {nation!r}")
        return s.snapshot(nation)

    @app.get("/ledger/{nation}")
    def get_ledger(nation: str) -> list[dict[str, Any]]:
        s: GameSession = app.state.session
        if nation not in s.world.nations:
            raise HTTPException(404, f"no such nation {nation!r}")
        rows = s.world.ledger.rows_for(nation) if s.world.ledger else []
        return [asdict(r) for r in rows]

    @app.get("/scenario", response_model=ScenarioInfo)
    def get_scenario() -> ScenarioInfo:
        current: str = app.state.scenario
        if parse_random_spec(current) is not None:
            return ScenarioInfo(name=current, path=current)  # a generated world, no file
        return ScenarioInfo(name=Path(current).stem, path=current)

    @app.post("/new", response_model=Snapshot)
    async def post_new(req: NewWorldRequest) -> Snapshot:
        """Start over: a new world (a fresh seed unless one is named), the same
        connected clients, year 0."""

        old: GameSession = app.state.session
        try:
            session, resolved = _new_session(req.scenario, req.player_nation)
        except (OSError, ValueError, KeyError) as exc:
            raise HTTPException(422, f"cannot start that world: {exc}") from exc
        session.websockets = old.websockets
        app.state.session = session
        app.state.scenario = resolved
        await _broadcast(session)
        return session.snapshot()

    @app.post("/turn", response_model=Snapshot)
    async def post_turn(nation: str | None = None) -> Snapshot:
        """End the turn: run one year, tell every connected client, and answer with
        the new snapshot (the same one the socket carries)."""

        s: GameSession = app.state.session
        if nation is not None and nation not in s.world.nations:
            raise HTTPException(404, f"no such nation {nation!r}")
        s.advance_one_year()
        await _broadcast(s)
        return s.snapshot(nation)

    @app.post("/action", response_model=ActionResult)
    def post_action(req: ActionRequest) -> JSONResponse:
        s: GameSession = app.state.session
        if req.nation not in s.world.nations:
            raise HTTPException(422, f"no such nation {req.nation!r}")
        try:
            kind = ActionKind[req.kind.upper()]
        except KeyError as exc:
            raise HTTPException(422, f"unknown action kind {req.kind!r}") from exc
        try:
            payload = _decode_payload(kind, req.nation, req.payload)
        except (KeyError, ValueError) as exc:
            raise HTTPException(422, f"bad payload: {exc}") from exc
        action = Action(kind=kind, nation=req.nation, payload=payload)
        result = s.enqueue_action(action)
        status = 200 if result.ok else 422
        return JSONResponse(status_code=status, content=result.model_dump())

    @app.post("/action/{queued_id}/withdraw")
    def withdraw_action(queued_id: str) -> dict[str, Any]:
        s: GameSession = app.state.session
        ok = s.withdraw_action(queued_id)
        if not ok:
            raise HTTPException(404, "no such queued action")
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        s: GameSession = app.state.session
        await websocket.accept()
        s.websockets.add(websocket)
        try:
            await websocket.send_text(s.snapshot().model_dump_json())
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            s.websockets.discard(websocket)

    if STATIC_DIR.exists():
        app.mount("/", _RevalidatingStaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
