"""Modes, moments, orbits and the two victories (design doc §8, §17)."""

from __future__ import annotations

from typing import Any

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


def levers(world: World) -> dict[str, dict[str, dict[str, Any]]]:
    """For each living people B: {A: {"kind", "strength", "detail"}} for every people A
    holding a lever over B (§17.2). Strength 1.0 is the threshold; only the strongest
    of A's levers over B is kept."""

    from stock.game import finance  # finance imports economy; victory stays light

    out: dict[str, dict[str, dict[str, Any]]] = {}
    living = [n for n in world.nations.values() if n.alive]
    for b in living:
        held: dict[str, dict[str, Any]] = {}

        def offer(
            a: str,
            kind: str,
            strength: float,
            detail: str,
            held: dict[str, dict[str, Any]] = held,
            b_id: str = b.id,
        ) -> None:
            _offer(world, held, b_id, a, kind, strength, detail)

        # trade: a partner supplies a quarter of one good, or a sixth of all we consume (smoothed)
        for a, (strength, detail) in b.last.get("trade_levers", {}).items():
            offer(a, "trade", strength, detail)
        # credit: they owe more than five turns of their revenue
        for a, strength in finance.credit_levers(world, b).items():
            offer(a, "credit", strength, f"holds {finance.debt(b, a):.0f} of their debt")
        # force: tribute, protection, or towns held in a war still being fought
        for tr in b.tributes:
            offer(tr["to"], "force", rules.TRIBUTE_LEVER, f"takes tribute for {tr['turns']} more turns")
        for t in world.treaties:
            if t["kind"] == "protection" and t["b"] == b.id:
                offer(t["a"], "force", rules.TRIBUTE_LEVER, "protects them, for 5% of their produce")
        taken: dict[str, int] = {}
        for nd in world.nodes.values():
            if nd.taken_from == b.id and nd.owner and nd.owner != b.id and world.war_between(nd.owner, b.id):
                taken[nd.owner] = taken.get(nd.owner, 0) + 1
        home = len(world.nodes_of(b.id))
        for a, count in taken.items():
            share = count / max(home + count, 1)
            offer(a, "force", share / rules.OCCUPATION_LEVER, f"occupies {count} of their towns")
        out[b.id] = held
    return out


def _offer(
    world: World, held: dict[str, dict[str, Any]], b_id: str, a: str, kind: str, strength: float, detail: str
) -> None:
    """Keep A's strongest lever over B, if it reaches the threshold."""

    if a == b_id or strength < 1.0 or not world.nations[a].alive:
        return
    if a not in held or strength > held[a]["strength"]:
        held[a] = {"kind": kind, "strength": round(strength, 2), "detail": detail}


def orbits(world: World, held: dict[str, dict[str, dict[str, Any]]] | None = None) -> dict[str, str]:
    """B -> the people whose orbit it is in: the holder of the strongest lever over it."""

    held = held if held is not None else levers(world)
    out: dict[str, str] = {}
    for b, by in held.items():
        # a people cannot be in the orbit of one it holds a stronger lever over (no mutual orbits)
        pulls = {
            a: x["strength"]
            for a, x in by.items()
            if x["strength"] > held.get(a, {}).get(b, {}).get("strength", 0.0)
        }
        if pulls:
            out[b] = max(pulls, key=lambda a: pulls[a])
    return out


def update_trade_levers(world: World, b: Nation) -> None:
    """This turn's trade dependence, folded into a running average so that a lever
    reflects years of dependence rather than one turn's flows."""

    eaten = b.last.get("consumed", {})
    old = b.last.get("trade_levers", {})
    raw: dict[str, tuple[float, str]] = {}
    for a, goods in b.trade.get("from", {}).items():
        total = float(b.last.get("dependence", {}).get(a, 0.0))
        good, share = max(
            ((g, q / float(eaten.get(g, 0.0))) for g, q in goods.items() if float(eaten.get(g, 0.0)) > 0),
            key=lambda t: t[1],
            default=("", 0.0),
        )
        by_good = share / rules.TRADE_LEVER_GOOD
        by_total = total / rules.TRADE_LEVER_TOTAL
        detail = (
            f"supplies {share:.0%} of their {good}"
            if by_good >= by_total
            else f"supplies {total:.0%} of all they consume"
        )
        raw[a] = (max(by_good, by_total), detail)
    new: dict[str, tuple[float, str]] = {}
    for a in set(old) | set(raw):
        s_old = old.get(a, (0.0, ""))[0]
        s_new, detail = raw.get(a, (0.0, old.get(a, (0.0, ""))[1]))
        smoothed = (1 - rules.LEVER_SMOOTHING) * s_old + rules.LEVER_SMOOTHING * s_new
        if smoothed >= 0.05:
            new[a] = (round(smoothed, 3), detail)
    b.last["trade_levers"] = new


def sphere(orb: dict[str, str], centre: str) -> list[str]:
    """Everyone in `centre`'s orbit, directly or through its satellites."""

    out: list[str] = []
    frontier = [centre]
    while frontier:
        nxt = [b for b, a in orb.items() if a in frontier and b != centre and b not in out]
        out += nxt
        frontier = nxt
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
        members = [b for b in sphere(orb, n.id) if world.nations[b].alive]
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
            _coalition(world, world.nations[candidate])
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
        if not eligible:  # everyone is in someone's orbit: the richest of the large still wins
            eligible = [n for n in living if world.hands_of(n.id) >= rules.OPULENCE_POP_FLOOR * avg]
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


def _coalition(world: World, leader: Nation) -> None:
    """The balance of power (§17.4): the others gain a cause against the leader, and each other."""

    others = [n for n in world.nations.values() if n.alive and n.id != leader.id]
    for n in others:
        n.casus_belli[leader.id] = rules.HEGEMONY_COUNTDOWN + 5
        for m in others:
            if m.id != n.id and m.id in n.contacts:
                n.relations[m.id] = min(100.0, n.relations.get(m.id, 0.0) + rules.COALITION_RELATIONS)
    world.emit(
        None,
        "coalition",
        f"The other peoples draw together against {leader.name}: each has a just cause for war against them.",
    )


def summary(world: World) -> dict[str, Any]:
    """Levers, orbits and the race, for the screen."""

    held = levers(world)
    orb = orbits(world, held)
    shares = world_shares(world)
    return {
        "levers": held,
        "orbits": orb,
        "shares": shares,
        "members": {a: sphere(orb, a) for a in shares},
    }
