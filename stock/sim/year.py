"""The assembled year loop: all 14 steps, in order (Doc 05, task S1-D05-T6).

Promotes `tests/_harness.py`'s scoped runner (steps 1-9, 11-13a/b, built up doc by
doc) to the real, complete loop, adding steps 3 (was already there), 6, 10's Focus
half, 13b's events/regression/hegemony, and 14.
"""

from __future__ import annotations

from typing import Any

from stock.ai.sovereign import NullSovereign, ScriptedSovereign
from stock.ai.view import build_view
from stock.core.actions import Action, ActionKind, enqueue, validate
from stock.core.world import Nation, PrevSnapshot, World
from stock.engine.band import band_barter, band_follow_herds, band_move, band_raid, settle, step_band
from stock.engine.capital import placement, step_hoards
from stock.engine.consumption import step_consumption
from stock.engine.market import step_market
from stock.engine.mobility import step_mobility
from stock.engine.population import step_population, sweep_dust
from stock.engine.production import step_production
from stock.engine.wages import step_wages
from stock.finance import credit as credit_module
from stock.finance import taxation as taxation_module
from stock.meta.events import step_events
from stock.meta.hegemony import step_hegemony
from stock.meta.regression import check_and_resolve, end_nation
from stock.meta.scoreboards import step_scoreboards
from stock.meta.trees import evaluate_gates
from stock.politics import legislation as legislation_module
from stock.politics.authority import step_authority
from stock.politics.focus import advance_focus
from stock.politics.legislation import step_legislation
from stock.politics.state import step_state
from stock.politics.unrest import step_unrest
from stock.security import war as war_module
from stock.security.military import step_army_purchase, step_security
from stock.security.war import step_war
from stock.sim.ledger import build_row
from stock.trade.routes import step_routes
from stock.trade.treaties import negotiate, step_treaties

#: Kinds dispatched to a module's own `apply_action(world, action)` (Doc 03/04/05).
_MODULE_HANDLERS: dict[ActionKind, Any] = {
    ActionKind.ENACT: legislation_module.apply_action,
    ActionKind.REPEAL: legislation_module.apply_action,
    ActionKind.VETO: legislation_module.apply_action,
    ActionKind.SET_FOCUS: legislation_module.apply_action,
    ActionKind.CLEAR_FOCUS: legislation_module.apply_action,
    ActionKind.SET_TAX_RATE: taxation_module.apply_action,
    ActionKind.SET_BUDGET: taxation_module.apply_action,
    ActionKind.SET_DEBT_POLICY: credit_module.apply_action,
    ActionKind.SET_FUNDING_MODE: credit_module.apply_action,
    ActionKind.DECLARE_RAID: war_module.apply_action,
    ActionKind.DECLARE_WAR: war_module.apply_action,
    ActionKind.BESIEGE: war_module.apply_action,
    ActionKind.OFFER_PEACE: war_module.apply_action,
    ActionKind.ACCEPT_PEACE: war_module.apply_action,
    ActionKind.REPRESS: war_module.apply_action,
}


def _apply_band_action(world: World, action: Action) -> None:
    nation = world.nations.get(action.nation)
    if nation is None:
        return
    home = nation.locations(world)
    location = home[0] if home else None
    if action.kind is ActionKind.BAND_MOVE and location is not None:
        band_move(world, nation, location, action.payload.get("to", ""), world.params)
    elif action.kind is ActionKind.BAND_FOLLOW_HERDS and location is not None:
        assert world.params is not None
        band_follow_herds(location, nation.id, world.params)
    elif action.kind is ActionKind.BAND_SETTLE and location is not None:
        if settle(location, nation, world):
            # The same handover step_band performs for an automatic settling (DD
            # §3/§7.3, DEVIATIONS A27) — a queued settle used to leave the seat at
            # BAND for good. See DEVIATIONS-IN-PROGRESS.md A68.
            from stock.politics.state import on_settled

            on_settled(nation, world)
    elif action.kind is ActionKind.BAND_RAID:
        target = world.locations.get(action.payload.get("location", ""))
        assert world.params is not None
        if target is not None:
            band_raid(world, nation, target, world.params)
    elif action.kind is ActionKind.BAND_BARTER and location is not None:
        other = world.locations.get(action.payload.get("with", ""))
        if other is not None:
            band_barter(location, other, world)


def _apply_treaty_action(world: World, action: Action) -> None:
    """PROPOSE_TREATY queues a proposal on `world.treaty_proposals`; ACCEPT_TREATY
    finds a matching one addressed to this nation and calls `negotiate`. No
    acceptance test exercises this (a null sovereign never queues one) — best-effort
    pending Doc 06/07's real use of it; see DEVIATIONS-RESOLVED.md A42."""

    nation = world.nations.get(action.nation)
    if nation is None:
        return
    if action.kind is ActionKind.PROPOSE_TREATY:
        # One open proposal per (initiator, target): a new one replaces the old
        # (a proposer that repeated itself used to get the same pact signed once
        # per pending copy, A76).
        target = action.payload.get("target")
        world.treaty_proposals = [
            p
            for p in world.treaty_proposals
            if not (p.get("initiator") == nation.id and p.get("target") == target)
        ]
        world.treaty_proposals.append(
            {
                "initiator": nation.id,
                "target": action.payload.get("target"),
                "terms": action.payload.get("terms", []),
            }
        )
    elif action.kind is ActionKind.ACCEPT_TREATY:
        wanted = action.payload.get("initiator")  # Doc 07's UI names the proposer; None = first
        for proposal in list(world.treaty_proposals):
            addressed = proposal.get("target") == nation.id
            if addressed and (wanted is None or proposal.get("initiator") == wanted):
                negotiate(world, proposal["initiator"], nation.id, proposal.get("terms", []))
                world.treaty_proposals.remove(proposal)
                break


def _apply_price_control(world: World, action: Action) -> None:
    """No module owns a direct price-setting handler yet — sets a location's
    Provisions price ceiling directly (best-effort; see A42)."""

    nation = world.nations.get(action.nation)
    if nation is None:
        return
    location_id = action.payload.get("location")
    price = action.payload.get("price")
    if location_id is None or price is None:
        return
    location = world.locations.get(location_id)
    if location is None:
        return
    from stock.core.goods import Good

    location.market.price[Good.PROVISIONS] = min(location.market.price.get(Good.PROVISIONS, price), price)


def apply_actions(nation: Any, world: World) -> None:
    """Step 14: drains the action queue through `actions.validate` and the owning
    module's handler. An action the year's earlier steps made illegal (a band that
    settled before its queued move) or one its handler declined is marked on its own
    payload (`_rejected`) so a caller holding the `Action` — Doc 07's API, for the feed
    — can tell "applied" from "skipped"; the engine itself reads nothing from it."""

    queue = list(nation.queue)
    nation.queue = []
    for action in queue:
        result = validate(world, action)
        if not result.ok:
            action.payload["_rejected"] = result.reason or "rejected"
            continue
        if action.payload.get("spend") == "bar":
            # ENACT/REPEAL spend `payload["spend"]` to pass their bar. A sovereign that
            # queued during the year saw a quote from before steps 1-13 moved the
            # authorities; "bar" means "what it costs now", i.e. `validate`'s cost.
            action.payload["spend"] = result.cost + 1e-9
            action.payload["_spent"] = result.cost
        handler = _MODULE_HANDLERS.get(action.kind)
        if handler is not None:
            if handler(world, action) is False:
                action.payload["_rejected"] = "not applied"
        elif action.kind in (ActionKind.PROPOSE_TREATY, ActionKind.ACCEPT_TREATY):
            _apply_treaty_action(world, action)
        elif action.kind is ActionKind.PRICE_CONTROL:
            _apply_price_control(world, action)
        elif action.kind.name.startswith("BAND_"):
            _apply_band_action(world, action)


def _sovereign_for(nation: Nation, world: World) -> NullSovereign | ScriptedSovereign:
    if nation.ai == "scripted":
        return ScriptedSovereign(max_actions=None)  # `_act` caps what is enqueued, not what is proposed
    return NullSovereign()


def _act(nation: Nation, world: World) -> None:
    """A sovereign decides once per year (Doc 06); each proposed action still goes
    through `actions.validate`/`enqueue` here, with a reserve `Params.ai.reserve`
    share of A_S never spent (a stricter bar than `validate`'s own, which allows
    spending A_S to zero)."""

    sovereign = _sovereign_for(nation, world)
    view = build_view(nation, world)
    reserve_fraction = world.params.ai.reserve if world.params is not None else 0.2
    max_actions = world.params.ai.max_actions_per_year if world.params is not None else 2
    enqueued = 0
    for action in sovereign.decide(view, world.rng):
        if enqueued >= max_actions:
            break
        reserve = reserve_fraction * nation.scalars.A_S
        result = validate(world, action)
        if not result.ok or result.cost > nation.scalars.A_S - reserve:
            continue
        enqueue(world, action)
        enqueued += 1


def run_year(world: World) -> None:
    """The 14 steps, every nation, in order (Doc 05)."""

    for nation in world.nations.values():
        if nation.ended:
            continue
        nation.flows = {}
        nation.scalars.army_inside = False
        if not nation.queue:
            _act(nation, world)

    world.prev = PrevSnapshot.take(world)

    step_production(world)  # 1
    step_wages(world)  # 2
    taxation_module.step_taxation(world)  # 3
    step_market(world)  # 4
    step_routes(world)  # 4 (cross-border)
    step_consumption(world)  # 5
    step_army_purchase(world)  # 5a (defence spending, reads step 3's draw)
    credit_module.step_credit(world)  # 6
    step_hoards(world)  # 7
    step_population(world)  # 8
    step_mobility(world)  # 8
    for nation in world.nations.values():
        if not nation.ended:
            placement(nation, world)  # 9

    evaluate_gates(world)  # 10
    for nation in world.nations.values():
        if nation.ended:
            continue
        assert world.params is not None
        advance_focus(nation, nation.scalars.works_draw, world.params)  # 10 (Focus)

    step_unrest(world)  # 11
    step_authority(world)  # 12a
    step_state(world)  # 12b
    step_legislation(world)  # 12c

    step_security(world)  # 13 (military)
    step_war(world)  # 13
    step_treaties(world)  # 13
    step_band(world)  # 13 (band-stage heuristics; a real sovereign's BAND_* actions
    # at step 14 can act instead)
    step_events(world)  # 13b
    sweep_dust(world)  # 13b (fold sub-person records left by casualties/plague/dismissal)
    for nation in world.nations.values():
        if not nation.ended:
            assert world.params is not None
            check_and_resolve(nation, world, world.params.regression)  # 13c
    step_scoreboards(world)  # curves, before hegemony reads world state
    step_hegemony(world)  # 13d
    for nation in list(world.nations.values()):
        if not nation.ended:
            end_nation(nation, world)

    for nation in world.nations.values():
        if not nation.ended:
            apply_actions(nation, world)  # 14

    if world.ledger is not None:
        for nation in world.nations.values():
            world.ledger.add_row(build_row(nation, world))

    world.year += 1
