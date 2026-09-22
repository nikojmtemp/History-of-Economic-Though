"""Trade and diplomacy (design doc §11, §16): flows, policy, blockade, embargo,
traders, treaties, fleets."""

from __future__ import annotations

import pytest

from stock.game import actions, military, rules, trade, turn
from stock.game.state import Node, Route, Unit, World
from stock.game.worldgen import generate


def partners(seed: int = 5) -> tuple[World, str, str, Node, Node]:
    """Two peoples on adjacent settled nodes, in contact, with a caravan route between them."""

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
        nd.owner, nd.hands, nd.works = owner, 12.0, ["fields", "market"]
    for x, y in ((me, them), (them, me)):
        n = w.nations[x]
        n.contacts.append(y)
        n.relations[y] = 0.0
        n.sway = 60.0
        n.known += ["barter", "fairs", "gifts", "sail", "coinage"]
        n.seat = "civil"
    return w, me, them, a, b


def route(w: World, me: str, them: str, a: Node, b: Node, kind: str = "caravan") -> Route:
    r = Route(w.new_id("r"), kind, me, them, rules.ROUTE_CAPACITY[kind], a_node=a.id, b_node=b.id, hops=1)
    w.routes[r.id] = r
    return r


def dear_wares_abroad(w: World, me: str, them: str) -> None:
    """We make cheap wares; they want them dear."""

    mine, theirs = w.nations[me], w.nations[them]
    mine.prices["wares"], theirs.prices["wares"] = 1.0, 3.0
    mine.store["wares"] = 40.0
    theirs.demand = {"food": 10.0, "wares": 20.0, "luxuries": 0.0}
    mine.demand = {"food": 10.0, "wares": 5.0, "luxuries": 0.0}


def test_goods_flow_from_cheap_to_dear_and_merchants_keep_the_gap() -> None:
    w, me, them, a, b = partners()
    r = route(w, me, them, a, b)
    dear_wares_abroad(w, me, them)
    trade.resolve_flows(w)
    sold = w.nations[me].trade["exports"]["wares"]
    assert sold > 0 and w.nations[them].trade["imports"]["wares"] == pytest.approx(sold)
    assert r.flows["wares"] == pytest.approx(sold)  # positive: from the opener to the partner
    assert w.nations[me].trade["profit"] == pytest.approx(r.profit) and r.profit > 0
    assert w.nations[them].trade["profit"] == 0.0  # the opener's merchants take the margin


def test_no_trade_when_the_gap_does_not_cover_carriage() -> None:
    w, me, them, a, b = partners()
    route(w, me, them, a, b)
    dear_wares_abroad(w, me, them)
    w.nations[them].prices["wares"] = 1.05  # 5% dearer; carriage is 10% a step
    trade.resolve_flows(w)
    assert w.nations[me].trade["exports"]["wares"] == 0.0


def test_imports_are_shared_across_routes() -> None:
    w, me, them, a, b = partners()
    for _ in range(4):
        route(w, me, them, a, b)
    dear_wares_abroad(w, me, them)
    w.nations[me].store["wares"] = 400.0
    trade.resolve_flows(w)
    assert w.nations[them].trade["imports"]["wares"] <= rules.IMPORT_SHARE * 20.0 + 1e-9


def test_mercantile_tariff_and_navigation_act() -> None:
    w, me, them, a, b = partners()
    route(w, me, them, a, b)
    dear_wares_abroad(w, me, them)
    w.nations[them].institutions["commerce"] = "mercantile"
    trade.resolve_flows(w)
    assert w.nations[them].trade["tariff"] > 0
    w.nations[them].prices["wares"] = 1.3  # covers carriage, not carriage and the tariff
    trade.resolve_flows(w)
    assert w.nations[me].trade["exports"]["wares"] == 0.0
    b.works.append("port")
    ship = Unit(w.new_id("u"), me, "merchantman", b.id, 0.0, home=a.id)
    w.units[ship.id] = ship
    assert "Navigation" in (trade.trader_blocker(w, w.nations[me], ship) or "")


def test_an_enemy_army_at_either_end_blockades_the_route() -> None:
    w, me, them, a, b = partners()
    r = route(w, me, them, a, b)
    dear_wares_abroad(w, me, them)
    third = "p2"
    w.wars.append({"a": third, "b": them, "since": w.turn, "score": {third: 0.0, them: 0.0}})
    w.units["x"] = Unit("x", third, "warband", b.id, 3.0)
    trade.resolve_flows(w)
    assert not r.active and w.nations[me].trade["exports"]["wares"] == 0.0


def test_embargo_closes_routes_and_gives_a_cause() -> None:
    w, me, them, a, b = partners()
    route(w, me, them, a, b)
    assert actions.act(w, me, {"kind": "embargo", "nation": them}) is None
    assert not trade.routes_of(w, me) and me in w.nations[them].casus_belli
    assert actions.check(w, w.nations[me], {"kind": "barter", "nation": them}) == "under embargo"


def test_a_caravan_walks_to_a_foreign_town_and_opens_a_route() -> None:
    w, me, them, a, b = partners()
    n = w.nations[me]
    n.stock = 50.0
    assert actions.act(w, me, {"kind": "send_trader", "node": a.id, "trader": "caravan"}) is None
    u = next(x for x in w.units_of(me) if x.kind == "caravan")
    assert n.stock == 50.0 - rules.TRADER_COST["caravan"]
    assert actions.check(w, n, {"kind": "open_route", "unit": u.id}) == "walk it to a foreign town"
    u.moves_left = 2
    assert (
        actions.act(w, me, {"kind": "move", "unit": u.id, "to": b.id}) is None
    )  # peaceful merchants may enter
    assert actions.act(w, me, {"kind": "open_route", "unit": u.id}) is None
    r = trade.routes_of(w, me)[0]
    assert (r.kind, r.a, r.b, r.a_node, r.b_node) == ("caravan", me, them, a.id, b.id)
    assert u.id not in w.units


def test_a_trade_pact_widens_routes() -> None:
    w, me, them, a, b = partners()
    r = route(w, me, them, a, b)
    before = trade.capacity_of(w, r)
    w.nations[them].relations[me] = 20.0
    assert actions.act(w, me, {"kind": "propose_treaty", "nation": them, "treaty": "trade_pact"}) is None
    assert trade.capacity_of(w, r) == pytest.approx(before * rules.PACT_CAPACITY)


def test_allies_join_a_defensive_war_and_breaking_faith_costs_standing() -> None:
    w, me, them, _, _ = partners()
    ally = w.nations["p2"]
    trade.sign(w, w.nations[them], ally, "alliance")
    trade.sign(w, w.nations[me], w.nations[them], "non_aggression")
    ally.contacts.append(me)
    w.nations[me].contacts.append(ally.id)
    before = w.nations["p3"].relations.get(me, 0.0)
    military.declare_war(w, w.nations[me], w.nations[them])
    assert military.at_war(w, ally.id, me)  # the ally came in
    assert w.treaty("non_aggression", me, them) is None
    assert w.nations["p3"].relations[me] == before - rules.BREAK_FAITH_RELATIONS


def test_fleets_fight_only_fleets() -> None:
    w, me, them, a, b = partners()
    military.declare_war(w, w.nations[me], w.nations[them])
    mine = Unit("f1", me, "fleet", a.id, 2.0)
    theirs = Unit("f2", them, "fleet", b.id, 2.0)
    w.units.update({"f1": mine, "f2": theirs})
    b.hands = 50.0  # a big town does not fight ships
    assert military.odds(w, mine, b) == pytest.approx(0.5)  # an even fight between equal fleets
    military.battle(w, mine, b)
    assert b.hands == 50.0
    assert w.nations[them].seat == "civil" and b.owner == them  # fleets never take towns


def test_the_ai_trades() -> None:
    routes = 0
    for seed in (2, 3):
        w = generate(seed=seed)
        for n in w.nations.values():
            n.player = False
        for _ in range(110):
            turn.end_turn(w)
        routes += sum(1 for r in w.routes.values() if r.kind in ("caravan", "sea"))
    assert routes >= 4
