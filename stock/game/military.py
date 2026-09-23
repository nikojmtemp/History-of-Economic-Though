"""War (design doc §15): units, strength, battles, sieges, capture, raids, supply,
war and peace, tribute, rebels, exile.

Units carry hands: raising an army takes people out of work, which is the central
cost of war. A unit's strength scales with the hands it carries and its cohesion.
"""

from __future__ import annotations

import math
from typing import Any

from stock.game import rules
from stock.game.economy import clamp
from stock.game.state import Decision, Nation, Node, Unit, World

# --- strength ---------------------------------------------------------------------------------


def unit_strength(world: World, u: Unit) -> float:
    """Fighting strength before matchups and terrain."""

    t = rules.UNITS[u.kind]
    scale = u.hands / t.hands
    base = t.strength
    if u.rebel_of is None:
        n = world.nations[u.nation]
        if u.kind == "warband" and n.knows("ambush"):
            base += 1.0
        if t.military and n.knows("metalworking"):
            base += 1.0
        if u.kind in ("regiment", "musketeers"):
            base += min(3.0, u.age // rules.DRILL_TURNS)
        if u.kind == "militia" and n.mode == "commerce":
            dol = float(n.last.get("dol", 1.0))
            base *= 1.0 - max(0.0, dol - 2.0) * 0.1 * (1.0 - n.budget.get("instruction", 0) / 3.0)
        if u.kind == "horde" and n.option("defence") == "nation_in_arms":
            base *= 1.5
    coh = u.cohesion / 100.0
    if u.cohesion < rules.BROKEN_COHESION:
        coh *= 0.5
    return base * scale * coh


def military_strength(world: World, nation_id: str) -> float:
    return sum(unit_strength(world, u) for u in world.units_of(nation_id) if u.military)


def _matchup(att: Unit, defender_kind: str, nd: Node) -> float:
    m = rules.MATCHUP.get(att.kind, {}).get(defender_kind, 1.0)
    if att.kind == "riders":
        if nd.t.rough or nd.terrain in ("HILLS", "FOREST") or "fort" in nd.works:
            m *= rules.RIDERS_ROUGH
        elif nd.terrain == "GRASSLAND":
            m *= rules.RIDERS_OPEN
    return m


def defenders(world: World, attacker: str, nd: Node, victim: str | None = None) -> list[Unit]:
    """Units at `nd` that fight a unit of `attacker` entering it: enemies at war, or,
    in a raid, everyone of the raided people."""

    if victim is not None:
        return [u for u in world.units_at(nd.id) if u.nation == victim and u.rebel_of is None]
    return [u for u in world.units_at(nd.id) if world.hostile(u, attacker)]


def _levy(world: World, attacker: str, nd: Node, victim: str | None) -> bool:
    """A settlement's people turn out to defend it, unless it was lately conquered."""

    if nd.conquered > 0:
        return False
    return nd.owner is not None and (nd.owner == victim or world.hostile_owner(attacker, nd))


def _defence_power(
    world: World, attacker: Unit, nd: Node, units: list[Unit], victim: str | None = None
) -> tuple[float, str]:
    """Defending power at `nd` and the kind the attacker's matchup is read against."""

    power = sum(unit_strength(world, u) for u in units)
    levy = 0.0
    if _levy(world, attacker.nation, nd, victim):
        levy = rules.SETTLED_LEVY * nd.hands
    power += levy
    primary = max(units, key=lambda u: unit_strength(world, u)).kind if units else "band"
    mult = nd.t.defence * (1.0 + rules.FORT_BONUS * nd.works.count("fort"))
    return power * mult, primary


def odds(world: World, att: Unit, nd: Node, victim: str | None = None) -> float:
    """The share of the field the attacker can expect, before luck (0..1)."""

    return float(odds_breakdown(world, att, nd, victim)["share"])


def odds_breakdown(world: World, att: Unit, nd: Node, victim: str | None = None) -> dict[str, Any]:
    """Every term of `odds`, for the attack tooltip: the same sums battle() makes."""

    units = defenders(world, att.nation, nd, victim)
    fleet = att.kind == "fleet"
    if fleet:  # as in battle(): ships fight ships, nothing else
        units = [u for u in units if u.kind == "fleet"]
    listed: list[dict[str, Any]] = [
        {
            "name": rules.UNITS[u.kind].name,
            "nation": u.nation,
            "hands": u.hands,
            "strength": unit_strength(world, u),
        }
        for u in units
    ]
    levy_hands = 0.0
    no_levy = None
    if not fleet and nd.owner is not None:
        if _levy(world, att.nation, nd, victim):
            levy_hands = nd.hands
        elif nd.conquered > 0:
            no_levy = "lately conquered: its people will not turn out"
    terrain = 1.0 if fleet else nd.t.defence
    forts = 0 if fleet else nd.works.count("fort")
    fort_mult = 1.0 + rules.FORT_BONUS * forts
    if fleet:
        d_power, primary = sum(unit_strength(world, u) for u in units), "fleet"
    else:
        d_power, primary = _defence_power(world, att, nd, units, victim)
    a_strength = unit_strength(world, att)
    matchup = _matchup(att, primary, nd)
    a_power = a_strength * matchup
    share = a_power / (a_power + d_power) if a_power + d_power > 0 else 1.0
    return {
        "attacker": {
            "name": rules.UNITS[att.kind].name,
            "hands": att.hands,
            "strength": a_strength,
            "cohesion": att.cohesion,
        },
        "matchup": matchup,
        "against": rules.UNITS[primary].name if primary in rules.UNITS else primary,
        "a_power": a_power,
        "defenders": listed,
        "levy_hands": levy_hands,
        "levy": rules.SETTLED_LEVY * levy_hands,
        "no_levy": no_levy,
        "terrain": terrain,
        "terrain_name": "open water" if fleet else nd.t.name,
        "forts": forts,
        "fort_mult": fort_mult,
        "d_power": d_power,
        "share": share,
        "siege_turns": rules.SIEGE_TURNS_PER_FORT * forts
        if forts and nd.owner is not None and victim is None
        else 0,
        "luck": rules.BATTLE_LUCK,
    }


# --- war state --------------------------------------------------------------------------------


def at_war(world: World, a: str, b: str) -> bool:
    return world.war_between(a, b) is not None


def declare_war(world: World, n: Nation, target: Nation, *, called: bool = False) -> None:
    from stock.game import trade  # trade does not import military; this keeps it that way

    free = target.id in n.casus_belli or called
    broken = trade.break_treaties(world, n, target)
    world.wars.append({"a": n.id, "b": target.id, "since": world.turn, "score": {n.id: 0.0, target.id: 0.0}})
    n.relations[target.id] = min(n.relations.get(target.id, 0.0), 0.0) - 50.0
    target.relations[n.id] = min(target.relations.get(n.id, 0.0), 0.0) - 50.0
    n.casus_belli.pop(target.id, None)
    for rid, r in list(world.routes.items()):
        if {r.a, r.b} == {n.id, target.id}:
            del world.routes[rid]
    why = (
        "honouring an alliance"
        if called
        else "with a just cause"
        if free
        else "without a cause, at a cost in Sway"
    )
    world.emit(n.id, "war", f"We declare war on {target.name}, {why}.")
    faith = f", breaking their {' and '.join(broken)} with us" if broken else ""
    world.emit(target.id, "war", f"{n.name} declares war on us{faith}.")
    if not called:  # the defender's allies come to its aid
        for ally_id in trade.allies_of(world, target.id):
            ally = world.nations[ally_id]
            if ally.alive and ally_id != n.id and not at_war(world, ally_id, n.id) and n.id in ally.contacts:
                declare_war(world, ally, n, called=True)


def make_peace(world: World, a: Nation, b: Nation, tribute_from: str | None) -> None:
    w = world.war_between(a.id, b.id)
    if w is None:
        return
    world.wars.remove(w)
    for x, y in ((a, b), (b, a)):
        x.relations[y.id] = x.relations.get(y.id, 0.0) + 20.0
        x.truce[y.id] = world.turn + rules.TRUCE_TURNS
        x.decisions = [d for d in x.decisions if not (d.kind == "peace" and d.data.get("from") == y.id)]
    text = "Peace with {}."
    if tribute_from is not None:
        payer = world.nations[tribute_from]
        to = b.id if tribute_from == a.id else a.id
        payer.tributes.append({"to": to, "turns": rules.TRIBUTE_TURNS, "share": rules.TRIBUTE_SHARE})
        text += f" {payer.name} pays tribute for {rules.TRIBUTE_TURNS} turns."
    world.emit(a.id, "peace", text.format(b.name))
    world.emit(b.id, "peace", text.format(a.name))


def war_score(world: World, n: Nation, other: str) -> float:
    w = world.war_between(n.id, other)
    return 0.0 if w is None else float(w["score"].get(n.id, 0.0) - w["score"].get(other, 0.0))


def _score(world: World, winner: str, loser: str | None, points: float) -> None:
    if loser is None:
        return
    w = world.war_between(winner, loser)
    if w is not None:
        w["score"][winner] = w["score"].get(winner, 0.0) + points


def offer_peace(world: World, n: Nation, other: Nation, terms: str) -> bool:
    """`terms`: "white", "tribute" (they pay us) or "submit" (we pay them).
    The AI answers at once; a player receives a decision. Returns True if peace is made."""

    payer = {"white": None, "tribute": other.id, "submit": n.id}[terms]
    if other.player:
        desc = {
            "white": "an end to the war, as things stand",
            "tribute": f"peace, if we pay them tribute for {rules.TRIBUTE_TURNS} turns",
            "submit": f"peace, with tribute paid to us for {rules.TRIBUTE_TURNS} turns",
        }[terms]
        other.decisions.append(
            Decision(
                id=world.new_id("d"),
                kind="peace",
                title=f"{n.name} offer peace",
                text=f"{n.name} propose {desc}.",
                choices=[
                    {"key": "accept", "label": "Accept", "effect": "The war ends."},
                    {"key": "refuse", "label": "Refuse", "effect": "The war goes on."},
                ],
                data={"from": n.id, "payer": payer},
            )
        )
        return False
    score = war_score(world, other, n.id)  # from the answering side
    w = world.war_between(n.id, other.id)
    length = world.turn - int(w["since"]) if w else 0
    weary = other.war_weariness > 15 or length >= 12
    accept = (
        (terms == "white" and (score <= 1 or weary))
        or (terms == "tribute" and score <= -3)
        or (terms == "submit")
    )
    if accept:
        make_peace(world, n, other, payer)
    return accept


# --- raising and disbanding -------------------------------------------------------------------


def raise_blocker(world: World, n: Nation, source: Node | Unit, kind: str) -> str | None:
    t = rules.UNITS.get(kind)
    if t is None or not t.raisable:
        return "no such unit"
    if t.defence is not None and n.option("defence") != t.defence:
        opt = rules.PILLARS["defence"].option(t.defence)
        return f"needs the {opt.name} institution"
    if not n.knows(t.needs):
        return f"needs {rules.DISCOVERIES[t.needs].name}" if t.needs else "locked"
    if kind == "musketeers" and not any("foundry" in nd.works for nd in world.nodes_of(n.id)):
        return "needs a Foundry"
    if kind == "fleet" and (not isinstance(source, Node) or "port" not in source.works):
        return "built at a Port"
    if kind == "host":
        if n.retainers < t.hands:
            return f"needs {t.hands:.0f} retainers"
        if n.orders["proprietors"].contentment < 35:
            return "the lords refuse to muster"
        if not isinstance(source, Node):
            return "raised at a settlement"
    else:
        have = source.hands
        spare = have - (1.0 if isinstance(source, Node) else 0.0)
        if spare < t.hands:
            return f"needs {t.hands:.0f} spare hands here"
    if t.herds and (source.herds if isinstance(source, Unit) else source.herds) < t.herds:
        return f"needs {t.herds:.0f} head of herds here"
    if n.store["wares"] < t.wares:
        return f"needs {t.wares:.0f} wares in store"
    if t.treasury and (n.seat != "civil" or n.treasury < t.treasury):
        return f"needs {t.treasury:.0f} Treasury"
    if isinstance(source, Node) and source.siege is not None:
        return "under siege"
    return None


def raise_unit(world: World, n: Nation, source: Node | Unit, kind: str) -> Unit:
    t = rules.UNITS[kind]
    if kind == "host":
        n.retainers -= t.hands
    else:
        source.hands -= t.hands
    if t.herds:
        source.herds -= t.herds
    n.store["wares"] -= t.wares
    n.treasury -= t.treasury
    node = source.id if isinstance(source, Node) else source.node
    uid = world.new_id("u")
    u = Unit(uid, n.id, kind, node, t.hands, moves_left=0)
    world.units[uid] = u
    if isinstance(source, Unit) and source.hands < 0.5:
        del world.units[source.id]
    return u


def disband(world: World, u: Unit) -> None:
    """Hands go home: into a settlement of theirs here, else into a band."""

    nd = world.nodes[u.node]
    if nd.owner == u.nation:
        nd.hands += u.hands
    else:
        band = next((x for x in world.units_of(u.nation) if x.node == u.node and not x.military), None)
        if band is not None:
            band.hands += u.hands
        else:
            uid = world.new_id("u")
            world.units[uid] = Unit(uid, u.nation, "band", u.node, u.hands, moves_left=0)
    del world.units[u.id]


def upgrade_blocker(world: World, n: Nation, u: Unit) -> str | None:
    if u.kind != "regiment":
        return "only regiments take firearms"
    why = raise_blocker(world, n, world.nodes[u.node], "musketeers")
    if why and "spare hands" not in why:
        return why
    return None


# --- battle ---------------------------------------------------------------------------------------


def _casualties(world: World, u: Unit, share: float) -> float:
    lost = u.hands * share
    u.hands -= lost
    u.cohesion = clamp(u.cohesion - rules.COHESION_LOSS * share / rules.CASUALTY_RATE, 0.0, 100.0)
    return lost


def _retreat(world: World, u: Unit) -> bool:
    """Fall back to an adjacent node held by the unit's people, else be destroyed."""

    for x in world.neighbours(u.node):
        nd = world.nodes[x]
        if nd.owner == u.nation or (
            nd.owner is None and not any(world.hostile(e, u.nation) for e in world.units_at(x))
        ):
            u.node = x
            u.moves_left = 0
            return True
    del world.units[u.id]
    return False


def battle(world: World, att: Unit, nd: Node, victim: str | None = None) -> bool:
    """Resolve `att` attacking `nd`. Returns True if the attacker holds the field.
    Fleets fight only fleets, on open water: no walls, no levy."""

    units = defenders(world, att.nation, nd, victim)
    if att.kind == "fleet":
        units = [u for u in units if u.kind == "fleet"]
        d_power, primary = sum(unit_strength(world, u) for u in units), "fleet"
    else:
        d_power, primary = _defence_power(world, att, nd, units, victim)
    a_power = unit_strength(world, att) * _matchup(att, primary, nd)
    a = a_power * (1.0 + world.rng.uniform(-rules.BATTLE_LUCK, rules.BATTLE_LUCK))
    d = d_power * (1.0 + world.rng.uniform(-rules.BATTLE_LUCK, rules.BATTLE_LUCK))
    share = a / (a + d) if a + d > 0 else 1.0
    win = share > 0.5
    a_lost = _casualties(world, att, rules.CASUALTY_RATE * (1.0 - share))
    d_lost = 0.0
    for u in units:
        d_lost += _casualties(world, u, rules.CASUALTY_RATE * share)
    if att.kind != "fleet" and _levy(world, att.nation, nd, victim):
        levy_loss = nd.hands * rules.CASUALTY_RATE * share * 0.3
        nd.hands = max(1.0, nd.hands - levy_loss)
        d_lost += levy_loss
    n = world.nations[att.nation]
    other = victim or (units[0].nation if units else nd.owner)
    enemy = world.nations.get(other) if other else None
    for u in list(units):
        if u.id in world.units and (u.hands < 0.3 or (win and u.military)):
            if u.hands < 0.3:
                del world.units[u.id]
            else:
                _retreat(world, u)
        elif win and u.id in world.units and not u.military:
            _retreat(world, u)
    if att.hands < 0.3:
        del world.units[att.id]
        win = False
    where = nd.name
    if win:
        n.counters["skirmishes_won"] = n.counters.get("skirmishes_won", 0.0) + 1
        _score(world, n.id, enemy.id if enemy else None, 1.0)
    elif enemy is not None:
        _score(world, enemy.id, n.id, 1.0)
    text = (
        f"Battle at {where}: {'victory' if win else 'defeat'} ({share:.0%} of the field). "
        f"We lost {a_lost:.1f} hands, they lost {d_lost:.1f}."
    )
    world.emit(n.id, "battle", text, nd.id)
    if enemy is not None and enemy.id != n.id:
        world.emit(
            enemy.id,
            "battle",
            f"Battle at {where}: {n.name} {'won' if win else 'were repulsed'}. "
            f"We lost {d_lost:.1f} hands, they lost {a_lost:.1f}.",
            nd.id,
        )
        enemy.war_weariness += d_lost
    n.war_weariness += a_lost
    return win


def advance(world: World, att: Unit, to: str) -> str:
    """A unit moves into `to`: fight whoever holds it, then besiege or capture.
    Returns a short outcome: "moved", "won", "lost", "siege", "captured"."""

    nd = world.nodes[to]
    if att.kind == "fleet":  # at sea: fight enemy fleets, then lie off the port (a blockade)
        if any(u.kind == "fleet" and world.hostile(u, att.nation) for u in world.units_at(to)):
            won = battle(world, att, nd)
            if att.id not in world.units or not won:
                return "lost"
            att.moves_left = 0
        att.node = to
        return "moved"
    hostile_units = any(world.hostile(u, att.nation) for u in world.units_at(to))
    hostile_node = nd.owner is not None and world.hostile_owner(att.nation, nd)
    if not hostile_units and not hostile_node:
        att.node = to
        return "moved"
    if not att.military:
        return "lost"
    if hostile_units or (hostile_node and nd.hands > 0):
        won = battle(world, att, nd)
        if att.id not in world.units:
            return "lost"
        att.moves_left = 0
        if not won:
            return "lost"
        if any(world.hostile(u, att.nation) for u in world.units_at(to)):
            return "won"
    att.node = to
    att.moves_left = 0
    if hostile_node:
        forts = nd.works.count("fort")
        if forts:
            if nd.siege is None or nd.siege["by"] != att.nation:
                nd.siege = {"by": att.nation, "turns": rules.SIEGE_TURNS_PER_FORT * forts}
                owner = world.nations[nd.owner] if nd.owner else None
                if owner is not None:
                    owner.counters["besieged"] = owner.counters.get("besieged", 0.0) + 1
                    world.emit(owner.id, "siege", f"{world.nations[att.nation].name} besiege {nd.name}.", to)
                world.emit(att.nation, "siege", f"We besiege {nd.name}: {nd.siege['turns']} turns.", to)
            return "siege"
        capture(world, att.nation, nd)
        return "captured"
    return "won"


# --- capture, exile -------------------------------------------------------------------------------


def capture(world: World, taker: str, nd: Node) -> None:
    loser_id = nd.owner
    n = world.nations[taker]
    nd.owner = taker
    nd.siege = None
    nd.conquered = 10
    nd.taken_from = loser_id
    nd.unrest = max(nd.unrest, rules.CONQUEST_UNREST)
    if loser_id is not None:
        loser = world.nations[loser_id]
        loser.build_queue = [q for q in loser.build_queue if q["node"] != nd.id]
        _score(world, taker, loser_id, 2.0)
        world.emit(loser_id, "captured", f"{nd.name} falls to {n.name}.", nd.id)
        loser.war_weariness += 5.0
        if not world.nodes_of(loser_id):
            exile(world, loser, nd)
    world.emit(taker, "captured", f"We take {nd.name}.", nd.id)
    choices = [
        {
            "key": "occupy",
            "label": "Occupy",
            "effect": "Keep it, its people and its works. Unrest +30 for a while.",
        },
        {
            "key": "plunder",
            "label": "Plunder",
            "effect": "Take its share of their stock and herds; wreck a work. Unrest +50.",
        },
    ]
    if nd.hands <= rules.RAZE_MAX_HANDS:
        choices.append({"key": "raze", "label": "Raze", "effect": "Burn it and leave it empty."})
    if not n.player:
        if n.mode == "pasturage":  # khans plunder; everyone else keeps what they take
            resolve_capture(world, n, nd.id, "plunder", loser_id)
        return
    if n.player:
        n.decisions.append(
            Decision(
                id=world.new_id("d"),
                kind="capture",
                title=f"{nd.name} is ours",
                text=f"{nd.name} ({nd.hands:.1f} hands, {len(nd.works)} works) has fallen. "
                "What becomes of it?",
                choices=choices,
                data={"node": nd.id, "from": loser_id},
            )
        )


def resolve_capture(world: World, n: Nation, node_id: str, choice: str, loser_id: str | None) -> None:
    nd = world.nodes[node_id]
    if nd.owner != n.id or choice == "occupy":
        return
    if choice == "plunder":
        loser = world.nations.get(loser_id) if loser_id else None
        if loser is not None:
            share = nd.hands / max(world.hands_of(loser.id) + nd.hands, 1.0)
            take = min(loser.stock, loser.stock * share + loser.hoard * 0.5 * share)
            loser.stock -= min(loser.stock, loser.stock * share)
            loser.hoard -= min(loser.hoard, loser.hoard * 0.5 * share)
            n.stock += take
        n.store["food"] += nd.herds * 0.5
        nd.herds *= 0.5
        if nd.works:
            nd.works.pop(world.rng.randrange(len(nd.works)))
        nd.unrest = max(nd.unrest, rules.PLUNDER_UNREST)
        world.emit(n.id, "plunder", f"{nd.name} is plundered.", nd.id)
    elif choice == "raze" and nd.hands <= rules.RAZE_MAX_HANDS:
        nd.owner, nd.works, nd.hands, nd.herds, nd.unrest = None, [], 0.0, 0.0, 0.0
        world.emit(n.id, "raze", f"{nd.name} is burned and left empty.", nd.id)


def exile(world: World, loser: Nation, lost: Node) -> None:
    """The last settlement is gone: the survivors take to the road (§7.3)."""

    if any(u.kind in ("band", "horde") for u in world.units_of(loser.id)):
        world.emit(loser.id, "exile", "Our last settlement is lost. Our people on the move carry on.")
    else:
        # the refugees: whoever can leave the fallen town, and those who were out in the fields
        take = min(rules.EXILE_HANDS, max(0.0, lost.hands - 1.0))
        lost.hands -= take
        size = max(take, rules.EXILE_MIN_HANDS)
        spot = next((x for x in world.neighbours(lost.id) if world.nodes[x].owner is None), lost.id)
        uid = world.new_id("u")
        world.units[uid] = Unit(uid, loser.id, "band", spot, size, moves_left=0)
        world.emit(
            loser.id,
            "exile",
            f"Our last settlement is lost. {size:.1f} hands flee as a band to {world.nodes[spot].name}.",
            spot,
        )
    loser.seat = "council"
    loser.institutions["revenue"] = "plunder"


# --- raids ------------------------------------------------------------------------------------------


def raid_blocker(world: World, n: Nation, u: Unit, to: str) -> str | None:
    if u.kind not in ("warband", "riders", "horde"):
        return "only warbands, riders and hordes raid"
    if u.moves_left <= 0:
        return "no moves left this turn"
    if world.edge_between(u.node, to) is None:
        return "not adjacent"
    nd = world.nodes[to]
    victims = {x.nation for x in world.units_at(to) if x.nation != n.id and x.rebel_of is None}
    if nd.owner is not None and nd.owner != n.id:
        victims.add(nd.owner)
    if not victims:
        return "nobody to raid there"
    return None


def raid(world: World, n: Nation, u: Unit, to: str) -> None:
    nd = world.nodes[to]
    victim_id = (
        nd.owner
        if nd.owner not in (None, n.id)
        else next(x.nation for x in world.units_at(to) if x.nation != n.id and x.rebel_of is None)
    )
    victim = world.nations[victim_id]
    guards = [x for x in world.units_at(to) if x.nation == victim_id and x.military]
    u.moves_left = 0
    if guards or (nd.owner == victim_id and nd.hands > 2):
        if not battle(world, u, nd, victim=victim_id):  # the raiders fight from where they stand
            return
    food = victim.store["food"] * 0.3
    victim.store["food"] -= food
    n.store["food"] += food
    herds = 0.0
    for x in world.units_at(to):
        if x.nation == victim_id and x.herds > 0:
            h = x.herds * 0.2
            x.herds -= h
            herds += h
    if nd.owner == victim_id:
        h = nd.herds * 0.2
        nd.herds -= h
        herds += h
    loot = victim.hoard * 0.1
    victim.hoard -= loot
    n.stock += loot
    if u.id in world.units and u.kind in ("horde", "riders"):
        u.herds += herds
    else:
        n.store["food"] += herds * rules.HERD_VALUE
    n.counters["raids_won"] = n.counters.get("raids_won", 0.0) + 1
    victim.casus_belli[n.id] = rules.CASUS_BELLI_TURNS
    victim.relations[n.id] = victim.relations.get(n.id, 0.0) - 30.0
    n.relations[victim_id] = n.relations.get(victim_id, 0.0) - 10.0
    world.emit(
        n.id, "raid", f"Raid on {nd.name}: {food:.1f} food, {herds:.0f} head of herds, {loot:.1f} stock.", to
    )
    world.emit(
        victim_id,
        "raid",
        f"{n.name} raid {nd.name}: we lose {food:.1f} food and {herds:.0f} head. "
        "We have a just cause for war.",
        to,
    )


# --- each turn --------------------------------------------------------------------------------------


def supplied(world: World, u: Unit) -> bool:
    """Within reach of a friendly settlement, or grazing for riders and hordes."""

    if u.rebel_of is not None:
        return True
    if u.kind in ("riders", "horde") and world.nodes[u.node].t.grazing >= 0.6:
        return True
    if u.kind == "fleet":  # victualled from any of our ports
        return any("port" in nd.works for nd in world.nodes_of(u.nation))
    frontier, seen = {u.node}, {u.node}
    for _ in range(rules.SUPPLY_RANGE + 1):
        if any(world.nodes[x].owner == u.nation for x in frontier):
            return True
        frontier = {y for x in frontier for y in world.neighbours(x)} - seen
        seen |= frontier
    return not u.military  # bands live off the land


def tick(world: World) -> None:
    """Upkeep, supply, sieges, the host's season, rebels, tribute, war weariness."""

    for u in list(world.units.values()):
        if u.id not in world.units:
            continue
        u.age += 1
        t = rules.UNITS[u.kind]
        if u.rebel_of is not None:
            _rebels(world, u)
            continue
        n = world.nations[u.nation]
        if u.kind == "host" and u.age >= rules.HOST_SEASON:
            world.emit(n.id, "host", "The feudal host goes home for the harvest.", u.node)
            n.retainers += u.hands
            del world.units[u.id]
            continue
        paid = True
        if t.upkeep:
            if n.treasury >= t.upkeep and n.seat == "civil":
                n.treasury -= t.upkeep
            else:
                paid = False
        crowd = sum(1 for x in world.units_at(u.node) if x.nation == u.nation and x.military)
        home = world.nodes[u.node]
        capacity = 2 + (home.hands / 3.0 if home.owner == u.nation else 0.0)
        if not u.military:
            continue
        if not paid:
            u.cohesion -= 20.0
            if u.cohesion <= 0:
                world.emit(n.id, "mutiny", f"Unpaid, a {t.name.lower()} deserts.", u.node)
                disband(world, u)
                continue
        if supplied(world, u) and crowd <= capacity:
            u.cohesion = min(100.0, u.cohesion + rules.COHESION_RECOVERY)
        else:
            u.cohesion -= rules.SUPPLY_LOSS
            if u.cohesion <= 0:
                world.emit(n.id, "attrition", f"A {t.name.lower()} starves and scatters.", u.node)
                disband(world, u)
    for nd in world.nodes.values():
        if nd.siege is None:
            continue
        besiegers = [u for u in world.units_at(nd.id) if u.nation == nd.siege["by"] and u.military]
        if not besiegers or nd.owner is None or not world.hostile_owner(nd.siege["by"], nd):
            nd.siege = None
            continue
        for u in besiegers:
            u.cohesion -= rules.SIEGE_ATTRITION
        nd.siege["turns"] -= 1
        if nd.siege["turns"] <= 0:
            capture(world, nd.siege["by"], nd)
    for n in world.nations.values():
        if not n.alive:
            continue
        for k in list(n.casus_belli):
            n.casus_belli[k] -= 1
            if n.casus_belli[k] <= 0:
                del n.casus_belli[k]
        warring = any(n.id in (w["a"], w["b"]) for w in world.wars)
        n.war_weariness = n.war_weariness + 1.0 if warring else n.war_weariness * 0.8
        for nd in world.nodes_of(n.id):
            nd.conquered = max(0, nd.conquered - 1)
        _pay_tribute(world, n)
        _pay_protection(world, n)
        if not world.nodes_of(n.id):
            n.exile_turns += 1
        else:
            n.exile_turns = 0


def _pay_tribute(world: World, n: Nation) -> None:
    for tr in list(n.tributes):
        to = world.nations.get(tr["to"])
        if to is None or not to.alive:
            n.tributes.remove(tr)
            continue
        amount = tr["share"] * float(n.last.get("produce", 0.0))
        pool = "treasury" if n.seat == "civil" else "stock"
        paid = min(amount, getattr(n, pool))
        setattr(n, pool, getattr(n, pool) - paid)
        if paid < amount:
            food = min(n.store["food"], amount - paid)
            n.store["food"] -= food
            paid += food
        if to.seat == "civil":
            to.treasury += paid
        else:
            to.stock += paid
        tr["paid"] = round(paid, 2)
        tr["turns"] -= 1
        if tr["turns"] <= 0:
            n.tributes.remove(tr)
            world.emit(n.id, "tribute", f"Our tribute to {to.name} is paid off.")


def _pay_protection(world: World, n: Nation) -> None:
    """A protected people pays its protector a share of its produce each turn."""

    for t in world.treaties:
        if t["kind"] != "protection" or t["b"] != n.id:
            continue
        to = world.nations[t["a"]]
        amount = rules.PROTECTION_SHARE * float(n.last.get("produce", 0.0))
        pool = "treasury" if n.seat == "civil" else "stock"
        paid = min(amount, max(0.0, getattr(n, pool)))
        setattr(n, pool, getattr(n, pool) - paid)
        if to.seat == "civil":
            to.treasury += paid
        else:
            to.stock += paid
        t["paid"] = round(paid, 2)


def _rebels(world: World, u: Unit) -> None:
    nd = world.nodes[u.node]
    loyal = [x for x in world.units_at(nd.id) if x.nation == u.rebel_of and x.military and x.rebel_of is None]
    if loyal or nd.owner != u.rebel_of:
        u.hold = 0
        return
    u.hold += 1
    if u.hold >= rules.REBEL_HOLD_TURNS:
        owner = world.nations[u.rebel_of] if u.rebel_of else None
        nd.owner = None
        nd.hands += u.hands
        nd.unrest = 20.0
        nd.siege = None
        del world.units[u.id]
        if owner is not None:
            world.emit(
                owner.id,
                "revolt",
                f"{nd.name} breaks away: the rebels have held it {rules.REBEL_HOLD_TURNS} turns.",
                nd.id,
            )
            owner.build_queue = [q for q in owner.build_queue if q["node"] != nd.id]


def check_revolts(world: World, n: Nation) -> None:
    hands = world.hands_of(n.id)
    for nd in world.nodes_of(n.id):
        if nd.unrest > rules.REVOLT_UNREST:
            nd.revolt_turns += 1
        else:
            nd.revolt_turns = 0
        big = nd.hands >= rules.UNREST_EVENT_MIN_HANDS and nd.hands >= rules.UNREST_EVENT_MIN_SHARE * hands
        already = any(x.rebel_of == n.id and x.node == nd.id for x in world.units.values())
        if nd.revolt_turns >= 2 and big and not already:
            size = max(1.0, nd.hands / 3.0)
            nd.hands -= size
            uid = world.new_id("u")
            world.units[uid] = Unit(uid, n.id, "rebels", nd.id, size, moves_left=0, rebel_of=n.id)
            nd.revolt_turns = 0
            world.emit(
                n.id,
                "revolt",
                f"Revolt in {nd.name}: {size:.1f} hands take up arms. Put it down, meet their "
                f"demands, or lose the node in {rules.REBEL_HOLD_TURNS} turns.",
                nd.id,
            )


def defence_ratio(world: World, n: Nation) -> float:
    """Our strength against the strongest hostile neighbour's (§9.7)."""

    ours = military_strength(world, n.id) + 0.2 * world.hands_of(n.id)
    threats = [
        military_strength(world, o) + 0.2 * world.hands_of(o)
        for o in n.contacts
        if world.nations[o].alive and (at_war(world, n.id, o) or n.relations.get(o, 0.0) < -20)
    ]
    if not threats:
        return 0.75
    return clamp(ours / max(max(threats), 1e-9) * 0.5, 0.0, 1.0)


def expected_power(world: World, n: Nation) -> float:
    return military_strength(world, n.id) + 0.1 * math.sqrt(max(world.hands_of(n.id), 0.0))


def summary(world: World, n: Nation) -> dict[str, Any]:
    return {
        "wars": [
            {
                "with": (w["b"] if w["a"] == n.id else w["a"]),
                "since": w["since"],
                "score": war_score(world, n, w["b"] if w["a"] == n.id else w["a"]),
            }
            for w in world.wars
            if n.id in (w["a"], w["b"])
        ],
        "strength": round(military_strength(world, n.id), 1),
        "weariness": round(n.war_weariness, 1),
        "casus_belli": dict(n.casus_belli),
        "tributes": list(n.tributes),
        "tribute_in": [
            {"from": o.id, **t} for o in world.nations.values() for t in o.tributes if t["to"] == n.id
        ],
    }
