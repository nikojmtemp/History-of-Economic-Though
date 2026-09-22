"""End of turn (design doc §4.1, §21.1): the AI moves, then the world resolves in a
fixed order."""

from __future__ import annotations

import copy
from typing import Any

from stock.game import actions, ai, economy, military, politics, research, rules, trade, victory
from stock.game.state import Nation, World


def end_turn(world: World, *, run_ai: bool = True) -> None:
    living = [n for n in world.nations.values() if n.alive]
    if run_ai:
        for n in living:
            if not n.player:
                ai.take_turn(world, n)

    # 1. policy phases in; queued works are built if Stock covers them
    for n in living:
        politics.apply_pending_institutions(world, n)
        actions.process_build_queue(world, n)

    # observation counters from this turn's choices
    for n in living:
        for u in world.units_of(n.id):
            if u.followed and "wild_herds" in world.nodes[u.node].features:
                n.counters["followed_herds"] = n.counters.get("followed_herds", 0.0) + 1

    # 2–7. production (hunting is shared across nations), then each nation's year
    plans = {n.id: economy.plan_labour(world, n) for n in living}
    economy.resolve_hunting(world, plans)
    for n in living:
        figures = economy.run_nation(world, n, plans[n.id])
        spent = economy.spend_budget(world, n)
        if n.seat == "civil" and figures["tax"]["collected"] < sum(spent.values()):
            n.counters["deficit"] = 1.0
        figures["spent"] = spent
        n.last.update(figures)

    # armies: upkeep, supply, sieges, the host's season, rebels, tribute
    military.tick(world)

    # 8. politics
    trade.update_contacts(world)
    trade.update_routes(world)
    for n in living:
        extent = economy.extent_of(world, n)
        n.last["extent"] = extent
        n.last["dol"] = rules.division_of_labour(extent, n.mode == "commerce")
        politics.update_clout(n)
        parts = politics.sway_income(world, n)
        n.last["sway_parts"] = parts
        n.sway = economy.clamp(n.sway + sum(parts.values()), 0.0, rules.SWAY_CAP)
        politics.update_seat(world, n)
        politics.update_unrest(world, n)
        military.check_revolts(world, n)
        politics.maybe_demand(world, n)
        n.feast_ready = max(0, n.feast_ready - 1)

    # 9. research
    for n in living:
        n.last["ingenuity"] = research.ingenuity(world, n)
        research.advance(world, n)

    # 10. world: modes, fog, victory
    for n in living:
        victory.update_mode(world, n)
        trade.update_fog(world, n)
    shares = victory.world_shares(world)
    for n in living:
        hands = world.hands_of(n.id)
        produce = float(n.last.get("produce", 0.0))
        labour_income = float(n.last.get("split", {}).get("wages", 0.0))
        n.history.append(
            {
                "turn": world.turn,
                "produce": round(produce, 2),
                "hands": round(hands, 2),
                "per_head": round(produce / hands, 3) if hands else 0.0,
                "labour_share": round(labour_income / produce, 3) if produce else 1.0,
                "freedom": _freedom(n),
                "share": round(shares.get(n.id, 0.0), 3),
                "stock": round(n.stock, 1),
                "mode": rules.MODES.index(n.mode),
            }
        )
    victory.check_elimination(world)
    victory.check_victory(world)
    if world.winner is not None and not world.winner.get("announced"):
        world.winner["announced"] = True
        world.emit(None, "victory", world.winner["text"])

    world.turn += 1
    for u in world.units.values():
        u.moves_left = u.max_moves(set(world.nations[u.nation].known))
        u.followed = False
        u.road_used = False


def _freedom(n: Nation) -> float:
    """Share of hands free to leave their employment (§17.5, the third curve)."""

    labour = n.option("labour")
    if labour == "serfdom":
        return 0.0
    if labour in rules.FREE_LABOUR or n.orders["proprietors"].size == 0:
        return 1.0
    return 0.6  # custom and guilds: free in law, bound by custom


def forecast(world: World, nation_id: str, action: dict[str, Any] | None) -> dict[str, Any]:
    """The action's effect, measured on copies of the world run with and without it (§19.5).

    Rivals do not act in either branch, so the difference is the action's alone. An
    institution comes into force at the next turn's start, so both branches run two
    turns for one and a single turn for anything else."""

    turns = 2 if action is not None and action.get("kind") == "institution" else 1

    def run(with_action: bool) -> dict[str, float] | None:
        w = copy.deepcopy(world)
        if with_action and action is not None and actions.act(w, nation_id, dict(action)):
            return None
        for _ in range(turns):
            end_turn(w, run_ai=False)
        n = w.nations[nation_id]
        out = {
            "food": float(n.last["made"]["food"]) - float(n.last["consumed"]["food"]),
            "stock": float(n.last["to_stock"]),
            "treasury": float(n.last["tax"]["collected"]) - sum(n.last.get("spent", {}).values()),
            "sway": sum(n.last.get("sway_parts", {}).values()),
            "produce": float(n.last["produce"]),
        }
        for o in rules.ORDERS:
            out[f"{o}_contentment"] = n.orders[o].contentment
        return out

    base, after = run(False), run(True)
    if base is None or after is None:
        return {"error": "not possible now"}
    return {k: round(after[k] - base[k], 2) for k in after}
