"""Modes, moments, orbits and the two victories (design doc §8, §17)."""

from __future__ import annotations

from stock.game import rules
from stock.game.state import Nation, World


def update_mode(world: World, n: Nation) -> None:
    sources: dict[str, float] = n.last.get("sources", {})
    if not sources or sum(sources.values()) <= 0:
        return
    leader = max(rules.MODES, key=lambda m: sources.get(m, 0.0))
    if leader == n.mode:
        n.mode_challenger, n.mode_streak = None, 0
        return
    if sources.get(leader, 0.0) < rules.MODE_LEAD * sources.get(n.mode, 0.0):
        n.mode_challenger, n.mode_streak = None, 0
        return
    if n.mode_challenger == leader:
        n.mode_streak += 1
    else:
        n.mode_challenger, n.mode_streak = leader, 1
    if n.mode_streak >= rules.MODE_STREAK:
        old = n.mode
        n.mode, n.mode_challenger, n.mode_streak = leader, None, 0
        backwards = rules.MODES.index(leader) < rules.MODES.index(old)
        if backwards:
            n.counters["regressions"] = n.counters.get("regressions", 0.0) + 1
            world.emit(
                n.id,
                "regression",
                f"{n.name} falls back from {rules.MODE_NAMES[old]} to "
                f"{rules.MODE_NAMES[leader]}: {rules.MODE_NAMES[leader].lower()} is again the largest "
                "source of produce.",
                quote=rules.MOMENT_QUOTES["regression"],
            )
        else:
            quote = rules.MOMENT_QUOTES["mode_commerce"] if leader == "commerce" else ""
            world.emit(
                n.id,
                "mode",
                f"{n.name} enters the age of {rules.MODE_NAMES[leader]}: "
                f"{rules.MODE_NAMES[leader].lower()} now yields the most produce.",
                quote=quote,
            )
        n.counters[f"mode_{leader}_turn"] = n.counters.get(f"mode_{leader}_turn", float(world.turn))


def world_shares(world: World) -> dict[str, float]:
    living = [n for n in world.nations.values() if n.alive]
    total = sum(float(n.last.get("produce", 0.0)) for n in living)
    return {n.id: (float(n.last.get("produce", 0.0)) / total if total > 0 else 0.0) for n in living}


def levers(world: World) -> dict[str, dict[str, str]]:
    """For each nation B, {A: lever} for every nation A holding a lever over B.

    Trade dependence, credit and force levers need goods flows, loans and tribute
    (M4–M6); until then nobody holds a lever and orbits are empty."""

    return {n.id: {} for n in world.nations.values()}


def orbits(world: World) -> dict[str, str]:
    """B -> the nation whose orbit it is in."""

    out: dict[str, str] = {}
    for b, held in levers(world).items():
        if held:
            out[b] = sorted(held)[0]
    return out


def produce_per_head(world: World, n: Nation) -> float:
    hands = world.hands_of(n.id)
    return float(n.last.get("produce", 0.0)) / hands if hands > 0 else 0.0


def check_victory(world: World) -> None:
    if world.winner is not None:
        return
    living = [n for n in world.nations.values() if n.alive]
    if len(living) == 1 and len(world.nations) > 1:
        world.winner = {"nation": living[0].id, "kind": "hegemony", "text": f"{living[0].name} stands alone."}
        return
    shares = world_shares(world)
    orb = orbits(world)
    heg = world.hegemony
    candidate = None
    for n in living:
        members = [b for b, a in orb.items() if a == n.id and world.nations[b].alive]
        others = len(living) - 1
        need = -(-others // 2)
        if (
            world.turn >= rules.HEGEMONY_EARLIEST
            and shares.get(n.id, 0) >= rules.HEGEMONY_SHARE
            and (len(members) >= need)
        ):
            candidate = n.id
    if candidate is not None:
        if heg["leader"] != candidate:
            heg.update(leader=candidate, countdown=rules.HEGEMONY_COUNTDOWN, failing=0)
            world.emit(
                None,
                "hegemony",
                f"{world.nations[candidate].name} holds Ascendancy: "
                f"{rules.HEGEMONY_COUNTDOWN} turns to hegemony.",
            )
        else:
            heg["countdown"] -= 1
            heg["failing"] = 0
        if heg["countdown"] <= 0:
            world.winner = {
                "nation": candidate,
                "kind": "hegemony",
                "text": f"{world.nations[candidate].name} achieves hegemony.",
            }
            return
    elif heg["leader"] is not None:
        heg["failing"] += 1
        if heg["failing"] >= rules.HEGEMONY_RESET_AFTER:
            heg.update(leader=None, countdown=None, failing=0)
    if world.turn >= rules.LAST_TURN:
        avg = sum(world.hands_of(n.id) for n in living) / len(living)
        eligible = [
            n for n in living if n.id not in orb and world.hands_of(n.id) >= rules.OPULENCE_POP_FLOOR * avg
        ]
        if eligible:
            best = max(eligible, key=lambda n: produce_per_head(world, n))
            world.winner = {
                "nation": best.id,
                "kind": "opulence",
                "text": f"{best.name} is the most opulent nation: "
                f"{produce_per_head(world, best):.2f} produce per head.",
            }


def check_elimination(world: World) -> None:
    for n in world.nations.values():
        if n.alive and world.hands_of(n.id) < 1.0:
            n.alive = False
            world.emit(None, "eliminated", f"{n.name} is no more.")
