"""Events (design doc §18): each card's choices do what they say."""

from __future__ import annotations

import pytest

from stock.game import actions, events, rules, turn
from stock.game.state import Decision, Nation, Node, World
from stock.game.worldgen import generate


def town(seed: int = 5) -> tuple[World, Nation, Node]:
    w = generate(seed=seed)
    n = w.nations["p0"]
    nd = next(x for x in w.nodes.values() if x.t.arable > 0 and x.t.grazing > 0 and not x.coast)
    nd.owner, nd.hands, nd.works = n.id, 20.0, ["fields", "fields", "workshop"]
    n.seat, n.treasury, n.stock = "civil", 100.0, 100.0
    n.last.update({"made": {"food": 40.0, "wares": 5.0, "luxuries": 0.0}, "produce": 60.0})
    w.turn = 30
    return w, n, nd


def card(n: Nation, event: str) -> Decision:
    return next(d for d in n.decisions if d.kind == "event" and d.data["event"] == event)


def decide(w: World, n: Nation, event: str, choice: str) -> None:
    assert actions.act(w, n.id, {"kind": "decide", "id": card(n, event).id, "choice": choice}) is None


def test_a_failed_harvest_can_be_made_good_by_imports() -> None:
    w, n, _ = town()
    n.store["food"] = 20.0
    assert events._harvest(w, n, 0.0)
    assert n.store["food"] == pytest.approx(20.0 - 12.0)
    decide(w, n, "harvest", "import")
    assert n.store["food"] == pytest.approx(20.0) and n.treasury == pytest.approx(
        100.0 - 12.0 * n.prices["food"] * 1.5
    )


def test_a_price_cap_pleases_labour_and_angers_growers() -> None:
    w, n, _ = town()
    n.prices["food"] = 2.0
    labour, props = n.orders["labour"].contentment, n.orders["proprietors"].contentment
    events._harvest(w, n, 0.0)
    decide(w, n, "harvest", "cap")
    assert n.prices["food"] == rules.BASE_PRICE["food"]
    assert n.orders["labour"].contentment == labour + 5 and n.orders["proprietors"].contentment == props - 10


def test_plague_takes_a_share_of_the_people() -> None:
    w, n, nd = town()
    assert events._plague(w, n, 0.0)
    assert 20.0 * 0.75 <= nd.hands <= 20.0 * 0.9


def test_a_patent_raises_that_town_s_output() -> None:
    w, n, nd = town()
    from stock.game import economy

    before = {r[0]: r[2] for r in economy._work_jobs(w, n, nd, 1.0)}["workshop"]["wares"]
    assert events._workman(w, n, 0.0)
    decide(w, n, "workman", "patent")
    after = {r[0]: r[2] for r in economy._work_jobs(w, n, nd, 1.0)}["workshop"]["wares"]
    assert after == pytest.approx(before * rules.PATENT_BOOST)


def test_enclosure_turns_fields_to_pasture() -> None:
    w, n, nd = town()
    n.institutions["property"] = "alienable"
    n.known.append("taming")
    assert events._enclosure(w, n, 0.0)
    decide(w, n, "enclosure", "enclose")
    assert nd.works.count("fields") == 1 and "pasture" in nd.works and nd.herds > 0


def test_colonists_can_take_ship() -> None:
    w, n, _ = town()
    port = next(x for x in w.nodes.values() if x.coast and any(e.kind == "sea" for e in w.adjacency()[x.id]))
    port.owner, port.works, port.hands = n.id, ["port"], 10.0
    n.known += ["navigation", "sail"]
    n.orders["labour"].contentment = 20.0
    assert events._colonists(w, n, 0.0)
    decide(w, n, "colonists", "charter")
    band = next(u for u in w.units_of(n.id) if u.node == port.id)
    over_sea = next(e.other(port.id) for e in w.adjacency()[port.id] if e.kind == "sea")
    assert actions.move_cost(w, band, over_sea) == 1


def test_wild_herds_wander() -> None:
    w, _, _ = town()
    w.rng.random = lambda: 0.0  # type: ignore[method-assign]
    before = {x.id for x in w.nodes.values() if "wild_herds" in x.features}
    events.world_events(w)
    after = {x.id for x in w.nodes.values() if "wild_herds" in x.features}
    assert len(before) == len(after) and before != after


def test_the_ai_answers_its_cards() -> None:
    w = generate(seed=3)
    for n in w.nations.values():
        n.player = False
    seen = 0
    for _ in range(120):
        turn.end_turn(w)
        seen += sum(1 for n in w.nations.values() for d in n.decisions if d.kind == "event")
    open_cards = sum(1 for n in w.nations.values() for d in n.decisions if d.kind == "event")
    assert seen > 0 and open_cards <= len(w.nations)  # each is answered the next turn
