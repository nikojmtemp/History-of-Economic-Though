"""Public credit, levers, orbits and hegemony (design doc §14.4, §17)."""

from __future__ import annotations

import pytest

from stock.game import actions, finance, military, rules, trade, victory
from stock.game.state import World
from stock.game.worldgen import generate


def peoples(seed: int = 5) -> World:
    w = generate(seed=seed)
    for n in w.nations.values():
        n.seat = "civil"
        n.known += ["public_credit", "tribute", "gifts", "barter"]
        n.stock = 200.0
        n.sway = 60.0
        n.contacts = [o for o in w.nations if o != n.id]
        n.relations = {o: 20.0 for o in w.nations if o != n.id}
        n.last.update(
            {
                "produce": 50.0,
                "tax": {"collected": 4.0},
                "consumed": {"food": 40.0, "wares": 10.0, "luxuries": 1.0},
            }
        )
    return w


def test_borrowing_at_home_crowds_out_stock_and_interest_is_paid() -> None:
    w = peoples()
    n = w.nations["p0"]
    assert actions.act(w, "p0", {"kind": "borrow", "source": "domestic", "amount": 20.0}) is None
    assert n.stock == 180.0 and n.treasury == 20.0 and finance.debt(n) == 20.0
    finance.service(w, n)
    assert n.treasury == pytest.approx(20.0 - 20.0 * rules.INTEREST_BASE)
    assert n.stock == pytest.approx(180.0 + 20.0 * rules.INTEREST_BASE)  # interest goes to our own savers


def test_a_foreign_loan_gives_the_lender_a_credit_lever() -> None:
    w = peoples()
    b, a = w.nations["p0"], w.nations["p1"]
    assert actions.act(w, "p0", {"kind": "borrow", "source": "p1", "amount": 20.0}) is None
    assert a.stock == 180.0 and finance.debt(b, "p1") == 20.0
    b.debts[0]["principal"] = 25.0  # past five turns of revenue (4 x 5 = 20)
    held = victory.levers(w)["p0"]
    assert held["p1"]["kind"] == "credit" and held["p1"]["strength"] >= 1.0
    assert victory.orbits(w)["p0"] == "p1"


def test_default_wipes_the_debt_and_closes_credit() -> None:
    w = peoples()
    b = w.nations["p0"]
    actions.act(w, "p0", {"kind": "borrow", "source": "p1", "amount": 20.0})
    before = w.nations["p1"].relations["p0"]
    assert actions.act(w, "p0", {"kind": "default"}) is None
    assert not b.debts and b.credit_closed > w.turn
    assert w.nations["p1"].relations["p0"] == before - rules.DEFAULT_RELATIONS
    assert "no one will lend" in (finance.borrow_blocker(w, b, "domestic", 10.0) or "")


def test_unpayable_interest_forces_a_default() -> None:
    w = peoples()
    b = w.nations["p0"]
    b.debts = [{"lender": "p1", "principal": 500.0, "rate": 0.1, "since": 1}]
    b.treasury = 0.0
    finance.service(w, b)
    assert not b.debts and b.credit_closed > w.turn


def test_trade_dependence_is_a_lever_once_it_lasts() -> None:
    w = peoples()
    b = w.nations["p0"]
    b.trade = {"from": {"p2": {"food": 20.0}}, "tolls": 0.0}
    b.last["dependence"] = {"p2": 0.2}
    victory.update_trade_levers(w, b)
    assert "p2" not in victory.levers(w)["p0"]  # one turn is not yet a dependence
    for _ in range(8):
        victory.update_trade_levers(w, b)
    lever = victory.levers(w)["p0"]["p2"]
    assert lever["kind"] == "trade" and "food" in lever["detail"]


def test_protection_puts_the_protected_in_orbit_and_pays() -> None:
    w = peoples()
    strong, weak = w.nations["p0"], w.nations["p1"]
    for u in list(w.units.values()):
        del w.units[u.id]
    nd = next(n for n in w.nodes.values() if not n.t.rough)
    nd.owner, nd.hands = "p0", 20.0
    military.raise_unit(w, strong, nd, "warband").hands = 10.0
    w.wars.append({"a": "p2", "b": "p1", "since": 1, "score": {"p2": 0.0, "p1": 0.0}})
    assert actions.act(w, "p0", {"kind": "propose_treaty", "nation": "p1", "treaty": "protection"}) is None
    assert victory.orbits(w)["p1"] == "p0"
    weak.treasury = 10.0
    military.tick(w)
    assert strong.treasury == pytest.approx(rules.PROTECTION_SHARE * 50.0)
    assert "p0" in trade.allies_of(w, "p1")  # the protector comes to their aid


def test_equal_levers_both_ways_cancel() -> None:
    w = peoples()
    w.nations["p1"].tributes.append({"to": "p0", "turns": 5, "share": 0.1})
    w.nations["p0"].tributes.append({"to": "p1", "turns": 5, "share": 0.1})
    orb = victory.orbits(w)
    assert "p0" not in orb and "p1" not in orb


def test_a_satellites_satellites_are_in_the_sphere() -> None:
    w = peoples()
    w.nations["p1"].tributes.append({"to": "p0", "turns": 5, "share": 0.1})
    w.nations["p2"].tributes.append({"to": "p1", "turns": 5, "share": 0.1})
    orb = victory.orbits(w)
    assert orb == {"p1": "p0", "p2": "p1"}
    assert sorted(victory.sphere(orb, "p0")) == ["p1", "p2"]


def test_ascendancy_counts_down_and_rallies_a_coalition() -> None:
    w = peoples()
    w.turn = rules.HEGEMONY_EARLIEST
    leader = w.nations["p0"]
    for n in w.nations.values():
        n.last["produce"] = 10.0
    leader.last["produce"] = 100.0
    for other in ("p1", "p2", "p3"):
        w.nations[other].tributes.append({"to": "p0", "turns": 20, "share": 0.1})
    victory.check_victory(w)
    assert w.hegemony["leader"] == "p0" and w.hegemony["countdown"] == rules.HEGEMONY_COUNTDOWN
    assert all("p0" in w.nations[x].casus_belli for x in ("p1", "p2", "p3", "p4"))
    for _ in range(rules.HEGEMONY_COUNTDOWN):
        w.turn += 1
        victory.check_victory(w)
    assert w.winner is not None and w.winner["nation"] == "p0" and w.winner["kind"] == "hegemony"


def test_opulence_still_names_a_winner_when_everyone_is_in_an_orbit() -> None:
    w = peoples()
    w.turn = rules.LAST_TURN
    for n in w.nations.values():
        n.last["produce"] = 10.0
    for a, b in (("p0", "p1"), ("p1", "p2"), ("p2", "p3"), ("p3", "p4"), ("p4", "p0")):
        w.nations[a].tributes.append({"to": b, "turns": 5, "share": 0.1})
    victory.check_victory(w)
    assert w.winner is not None and w.winner["kind"] == "opulence"
