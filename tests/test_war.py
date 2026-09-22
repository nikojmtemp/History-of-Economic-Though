"""War (design doc §15): raising, battle, capture, siege, raids, peace, rebels, supply."""

from __future__ import annotations

import pytest

from stock.game import actions, military, rules, turn
from stock.game.state import Node, Unit, World
from stock.game.worldgen import generate


def frontier(seed: int = 5) -> tuple[World, str, str, Node, Node]:
    """Two peoples on adjacent settled nodes, in contact."""

    w = generate(seed=seed)
    me, them = "p0", "p1"
    for u in list(w.units.values()):
        del w.units[u.id]
    a = next(
        n
        for n in w.nodes.values()
        if not n.t.rough and any(not w.nodes[x].t.rough for x in w.neighbours(n.id))
    )
    b = w.nodes[next(x for x in w.neighbours(a.id) if not w.nodes[x].t.rough)]
    for nd, owner in ((a, me), (b, them)):
        nd.owner, nd.hands, nd.works = owner, 12.0, ["fields"]
    for x, y in ((me, them), (them, me)):
        w.nations[x].contacts.append(y)
        w.nations[x].relations[y] = 0.0
        w.nations[x].sway = 60.0
    return w, me, them, a, b


def raise_at(w: World, nation: str, node: Node, kind: str = "warband", hands: float = 1.0) -> Unit:
    u = military.raise_unit(w, w.nations[nation], node, kind)
    u.hands = hands
    u.moves_left = 1
    return u


def test_raising_takes_hands_and_disbanding_returns_them() -> None:
    w, me, _, a, _ = frontier()
    before = w.hands_of(me)
    assert actions.act(w, me, {"kind": "raise_unit", "node": a.id, "unit_kind": "warband"}) is None
    u = next(u for u in w.units_of(me) if u.military)
    assert a.hands == 11.0 and w.hands_of(me) == before
    assert actions.act(w, me, {"kind": "raise_unit", "node": a.id, "unit_kind": "regiment"}) is not None
    assert actions.act(w, me, {"kind": "disband", "unit": u.id}) is None
    assert a.hands == 12.0


def test_war_costs_sway_without_a_cause_and_truce_follows_peace() -> None:
    w, me, them, _, _ = frontier()
    n = w.nations[me]
    assert actions.act(w, me, {"kind": "declare_war", "nation": them}) is None
    assert n.sway == 60.0 - rules.WAR_COST and military.at_war(w, me, them)
    w.turn += rules.PEACE_MIN_TURNS
    military.make_peace(w, n, w.nations[them], None)
    assert not military.at_war(w, me, them)
    assert "truce" in (actions.check(w, n, {"kind": "declare_war", "nation": them}) or "")


def test_a_strong_army_takes_an_undefended_town() -> None:
    w, me, them, a, b = frontier()
    military.declare_war(w, w.nations[me], w.nations[them])
    u = raise_at(w, me, a, "warband", hands=8.0)
    assert military.odds(w, u, b) > 0.6
    assert actions.act(w, me, {"kind": "move", "unit": u.id, "to": b.id}) is None
    assert b.owner == me and u.node == b.id and b.conquered > 0


def test_peaceful_units_cannot_enter_foreign_towns() -> None:
    w, me, _, a, b = frontier()
    u = raise_at(w, me, a)
    assert "at peace" in (actions.check(w, w.nations[me], {"kind": "move", "unit": u.id, "to": b.id}) or "")


def test_losing_the_last_town_sends_the_people_into_exile() -> None:
    w, me, them, a, b = frontier()
    military.declare_war(w, w.nations[me], w.nations[them])
    military.capture(w, me, b)
    exiles = w.units_of(them)
    assert b.owner == me and len(exiles) == 1 and exiles[0].kind == "band"
    assert w.nations[them].alive and w.nations[them].seat == "council"


def test_walls_must_be_besieged() -> None:
    w, me, them, a, b = frontier()
    b.works.append("fort")
    b.hands = 1.0
    military.declare_war(w, w.nations[me], w.nations[them])
    u = raise_at(w, me, a, "warband", hands=8.0)
    actions.act(w, me, {"kind": "move", "unit": u.id, "to": b.id})
    assert b.owner == them and b.siege is not None and b.siege["turns"] == rules.SIEGE_TURNS_PER_FORT
    for _ in range(rules.SIEGE_TURNS_PER_FORT):
        military.tick(w)
    assert b.owner == me and b.siege is None


def test_a_raid_takes_food_and_gives_a_cause() -> None:
    w, me, them, a, b = frontier()
    w.nations[them].store["food"] = 20.0
    b.hands = 2.0  # too few to turn out against raiders
    u = raise_at(w, me, a, "warband", hands=3.0)
    assert actions.act(w, me, {"kind": "raid", "unit": u.id, "to": b.id}) is None
    assert w.nations[them].store["food"] < 20.0 and me in w.nations[them].casus_belli
    assert u.node == a.id and not military.at_war(w, me, them)
    assert actions.check(w, w.nations[them], {"kind": "declare_war", "nation": me}) is None
    w.nations[them].sway = 0.0
    assert actions.check(w, w.nations[them], {"kind": "declare_war", "nation": me}) is None  # a cause is free


def test_tribute_flows_after_peace() -> None:
    w, me, them, _, _ = frontier()
    military.declare_war(w, w.nations[me], w.nations[them])
    military.make_peace(w, w.nations[me], w.nations[them], tribute_from=them)
    payer, payee = w.nations[them], w.nations[me]
    payer.last["produce"] = 50.0
    payer.stock = 100.0
    military.tick(w)
    assert payee.stock == pytest.approx(rules.TRIBUTE_SHARE * 50.0)
    assert payer.tributes[0]["turns"] == rules.TRIBUTE_TURNS - 1


def test_rebels_rise_and_a_node_breaks_away() -> None:
    w, me, _, a, _ = frontier()
    a.unrest = 95.0
    a.revolt_turns = 1
    military.check_revolts(w, w.nations[me])
    rebels = [u for u in w.units.values() if u.rebel_of == me]
    assert len(rebels) == 1 and rebels[0] not in w.units_of(me)
    for _ in range(rules.REBEL_HOLD_TURNS):
        military.tick(w)
    assert a.owner is None


def test_armies_out_of_supply_lose_cohesion() -> None:
    w, me, _, a, _ = frontier()
    u = raise_at(w, me, a, "warband")
    far = max(w.nodes, key=lambda x: (w.nodes[x].x - a.x) ** 2 + (w.nodes[x].y - a.y) ** 2)
    u.node = far
    military.tick(w)
    assert u.cohesion == 100.0 - rules.SUPPLY_LOSS


def test_the_ai_goes_to_war() -> None:
    wars = 0
    for seed in (1, 2, 3, 4):
        w = generate(seed=seed)
        for n in w.nations.values():
            n.player = False
        for _ in range(rules.LAST_TURN):
            turn.end_turn(w)
        wars += sum(1 for e in w.log if e.kind == "war" and e.text.startswith("We declare"))
        assert not w.wars or all(x["a"] in w.nations for x in w.wars)
    assert wars >= 4


@pytest.mark.parametrize("nodes", [29, 61])
def test_maps_have_30_to_60_nodes(nodes: int) -> None:
    with pytest.raises(ValueError):
        generate(seed=1, nodes=nodes)
    assert len(generate(seed=1, nodes=30).nodes) == 30
    assert len(generate(seed=1, nodes=60).nodes) == 60
