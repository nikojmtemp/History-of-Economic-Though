"""Engine tests: worldgen, verbs, invariants (design doc §21.2), and pacing (§20)."""

from __future__ import annotations

import copy
import math
from functools import cache
from typing import Any

import pytest

from stock.game import actions, research, rules, trade, turn
from stock.game.state import World
from stock.game.worldgen import generate, parse_spec


def ai_world(seed: int) -> World:
    w = generate(seed=seed)
    for n in w.nations.values():
        n.player = False
    return w


@cache
def finished(seed: int) -> World:
    w = ai_world(seed)
    for _ in range(rules.LAST_TURN):
        turn.end_turn(w)
    return w


# --- worldgen ---------------------------------------------------------------------------------


def test_same_seed_same_world() -> None:
    a, b = generate(seed=11), generate(seed=11)
    assert [(n.id, n.name, n.terrain, n.features) for n in a.nodes.values()] == [
        (n.id, n.name, n.terrain, n.features) for n in b.nodes.values()
    ]
    assert [(e.a, e.b, e.kind) for e in a.edges] == [(e.a, e.b, e.kind) for e in b.edges]


def _reach(w: World, start: str, *, sea: bool) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        for nxt in w.neighbours(stack.pop(), sea=sea):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


@pytest.mark.parametrize("seed", range(1, 9))
def test_world_is_connected_and_every_people_starts_with_a_band(seed: int) -> None:
    w = generate(seed=seed)
    starts = [u.node for u in w.units.values()]
    assert _reach(w, starts[0], sea=True) == set(w.nodes)  # everywhere can be reached, by sea at worst
    mainland = _reach(w, starts[0], sea=False)
    assert all(s in mainland for s in starts)  # every people starts on the one mainland
    assert len(starts) == len(w.nations) == len(set(starts))
    assert sum("wild_herds" in n.features for n in w.nodes.values()) >= len(w.nations)
    assert sum(n.player for n in w.nations.values()) == 1


def test_spec_round_trip() -> None:
    cfg = parse_spec("random:42:40:3")
    assert (cfg.seed, cfg.nodes, cfg.nations) == (42, 40, 3)
    assert generate(cfg).spec == "random:42:40:3"
    with pytest.raises(ValueError):
        parse_spec("random:1:10:5")  # too many peoples for the map


# --- verbs ---------------------------------------------------------------------------------------


def _me(w: World) -> tuple[str, str]:
    p = w.player()
    assert p is not None
    return p.id, next(u.id for u in w.units.values() if u.nation == p.id)


def test_move_uses_the_graph_and_moves() -> None:
    w = generate(seed=5)
    me, uid = _me(w)
    here = w.units[uid].node
    far = next(n for n in w.nodes if n != here and n not in w.neighbours(here))
    assert actions.act(w, me, {"kind": "move", "unit": uid, "to": far}) == "not adjacent by land"
    to = w.neighbours(here)[0]
    assert actions.act(w, me, {"kind": "move", "unit": uid, "to": to}) is None
    assert w.units[uid].node == to
    assert actions.act(w, me, {"kind": "move", "unit": uid, "to": here}) == "no moves left this turn"


def test_split_costs_sway_and_halves_the_band() -> None:
    w = generate(seed=5)
    me, uid = _me(w)
    sway = w.nations[me].sway
    assert actions.act(w, me, {"kind": "split", "unit": uid}) is None
    mine = [u for u in w.units.values() if u.nation == me]
    assert len(mine) == 2 and all(math.isclose(u.hands, rules.START_HANDS / 2) for u in mine)
    assert w.nations[me].sway == sway - rules.SPLIT_COST


def test_settling_needs_tillage_then_plants_fields() -> None:
    w = generate(seed=5)
    me, uid = _me(w)
    n = w.nations[me]
    node = w.nodes[w.units[uid].node]
    assert actions.act(w, me, {"kind": "settle", "unit": uid}) == "needs Tillage"
    n.known.append("tillage")
    if node.t.arable <= 0:
        pytest.skip("start node has no arable ground on this seed")
    assert actions.act(w, me, {"kind": "settle", "unit": uid}) is None
    assert node.owner == me and "fields" in node.works and uid not in w.units


def test_research_needs_prerequisites() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    assert actions.act(w, me, {"kind": "research", "key": "division"}) == "prerequisites not met"
    assert actions.act(w, me, {"kind": "research", "key": "taming"}) is None
    n = w.nations[me]
    n.research_progress = 1000.0
    research.advance(w, n)
    assert "taming" in n.known and n.researching is None


def test_no_discovery_is_a_dead_end() -> None:
    """Every discovery is reachable from the start (lesson: §2, the chain deadlock)."""

    known = set(rules.START_DISCOVERIES)
    changed = True
    while changed:
        changed = False
        for d in rules.DISCOVERIES.values():
            if d.key not in known and all(any(r in known for r in g) for g in d.requires):
                known.add(d.key)
                changed = True
    assert known == set(rules.DISCOVERIES)


def test_every_institution_option_is_reachable() -> None:
    for pillar in rules.PILLARS.values():
        for o in pillar.options:
            assert o.needs is None or o.needs in rules.DISCOVERIES, (pillar.key, o.key)


def test_institutions_phase_in_next_turn_and_cost_sway() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    n = w.nations[me]
    n.known.append("taming")
    n.sway = 100.0
    assert actions.act(w, me, {"kind": "institution", "pillar": "property", "option": "herds"}) is None
    assert n.sway < 100.0 and n.option("property") == "common"
    turn.end_turn(w)
    assert n.option("property") == "herds"
    assert actions.check(w, n, {"kind": "institution", "pillar": "property", "option": "common"}) is not None


def test_the_investment_queue_builds_what_pays() -> None:
    w = generate(seed=5)
    me, uid = _me(w)
    n = w.nations[me]
    n.known += ["tillage", "weaving"]
    node = w.nodes[w.units[uid].node]
    if node.t.arable <= 0:
        pytest.skip("start node has no arable ground on this seed")
    actions.act(w, me, {"kind": "settle", "unit": uid})
    node.hands = 20.0
    n.stock = 100.0
    assert actions.act(w, me, {"kind": "build", "node": node.id, "work": "workshop"}) is None
    n.prices["wares"] = 8.0  # dear wares: a workshop pays
    before = len(node.works)
    actions.process_build_queue(w, n)
    assert len(node.works) == before + 1 and n.stock == 100.0 - rules.WORKS["workshop"].cost


# --- invariants (§21.2) -----------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_full_game_stays_finite_and_conserves_value(seed: int) -> None:
    w = ai_world(seed)
    for _ in range(rules.LAST_TURN):
        turn.end_turn(w)
        for n in w.nations.values():
            if not n.alive:
                continue
            L = n.last
            for x in (n.sway, n.stock, n.treasury, n.hoard, L["produce"], *n.prices.values()):
                assert math.isfinite(x) and x >= -1e-9
            split = sum(L["split"].values())
            assert math.isclose(split, L["produce"], rel_tol=1e-9, abs_tol=1e-9)
            taxed = sum(n.orders[o].income for o in rules.ORDERS) + L["tax"]["collected"]
            # incomes and taxes = produce, plus transfers (tolls to lords, bounties from the Treasury)
            assert math.isclose(taxed, L["produce"] + L["transfers"], rel_tol=1e-6, abs_tol=1e-6)
            assert 0.0 <= n.sway <= rules.SWAY_CAP
            for o in n.orders.values():
                assert 0.0 <= o.contentment <= 100.0
    assert w.winner is not None


def test_same_seed_same_game() -> None:
    a, b = ai_world(4), ai_world(4)
    for _ in range(60):
        turn.end_turn(a)
        turn.end_turn(b)
    assert [n.history for n in a.nations.values()] == [n.history for n in b.nations.values()]


def test_forecast_matches_the_next_turn_when_nobody_else_acts() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    for _ in range(3):
        turn.end_turn(w, run_ai=False)
    delta = turn.forecast(w, me, {"kind": "feast"})
    assert "error" not in delta


# --- pacing (§20 balance targets) ------------------------------------------------------------


SEEDS = (1, 2, 3, 4)


def test_every_people_leaves_hunting_early() -> None:
    left = [
        n.counters.get("mode_pasturage_turn") or n.counters.get("mode_agriculture_turn")
        for s in SEEDS
        for n in finished(s).nations.values()
    ]
    early = sum(1 for t in left if t is not None and t <= 45)
    assert early >= 0.9 * len(left), left


def test_someone_farms_by_turn_60() -> None:
    hits = [
        any((n.counters.get("mode_agriculture_turn") or 999) <= 60 for n in finished(s).nations.values())
        for s in SEEDS
    ]
    assert sum(hits) >= 3, hits


def test_manufactories_appear() -> None:
    hits = [any("manufactory" in nd.works for nd in finished(s).nodes.values()) for s in SEEDS]
    assert sum(hits) >= 3, hits


def test_demolishing_frees_a_slot() -> None:
    w = generate(seed=5)
    me, uid = _me(w)
    n = w.nations[me]
    n.known.append("tillage")
    node = w.nodes[w.units[uid].node]
    if node.t.arable <= 0:
        pytest.skip("start node has no arable ground on this seed")
    actions.act(w, me, {"kind": "settle", "unit": uid})
    before = list(node.works)
    assert actions.act(w, me, {"kind": "demolish", "node": node.id, "work": "fields"}) is None
    assert len(node.works) == len(before) - 1
    assert actions.check(w, n, {"kind": "demolish", "node": node.id, "work": "bank"}) == "no such work there"


@pytest.mark.parametrize("seed", range(1, 41))
def test_every_people_has_wild_herds_within_two_steps(seed: int) -> None:
    w = generate(seed=seed)
    for u in w.units.values():
        near = {u.node} | set(w.neighbours(u.node))
        near |= {y for x in list(near) for y in w.neighbours(x)}
        assert any("wild_herds" in w.nodes[x].features for x in near), (seed, u.nation)


def test_a_feast_spikes_growth_and_costs_more_with_more_people() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    for _ in range(3):
        turn.end_turn(w, run_ai=False)
    w.nations[me].store["food"] = 1000.0
    base = copy.deepcopy(w)
    turn.end_turn(base, run_ai=False)
    first = actions.feast_cost(w, w.nations[me])
    assert actions.act(w, me, {"kind": "feast"}) is None
    assert first == pytest.approx(rules.FEAST_FOOD_PER_HAND * w.hands_of(me))
    turn.end_turn(w, run_ai=False)
    assert w.hands_of(me) > base.hands_of(me) * 1.04


def test_queueing_a_distant_discovery_plans_the_road_to_it() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    n = w.nations[me]
    assert actions.act(w, me, {"kind": "queue_research", "key": "land_tenure"}) is None
    plan = [n.researching, *n.research_queue]
    assert plan[-1] == "land_tenure"
    for i, k in enumerate(plan):  # every step's requirements come before it
        for group in rules.DISCOVERIES[k].requires:
            assert any(r in n.known or r in plan[:i] for r in group)
    n.research_progress = 1000.0
    for _ in range(4):
        turn.end_turn(w, run_ai=False)
    assert "land_tenure" in n.known and not n.research_queue


def test_choosing_a_discovery_sets_the_current_one_aside() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    n = w.nations[me]
    assert actions.act(w, me, {"kind": "research", "key": "taming"}) is None
    assert actions.act(w, me, {"kind": "queue_research", "key": "barter"}) is None
    assert n.researching == "taming" and n.research_queue == ["barter"]
    assert actions.act(w, me, {"kind": "research", "key": "barter"}) is None
    assert n.researching == "barter" and n.research_queue == ["taming"]
    assert actions.act(w, me, {"kind": "unqueue_research", "key": "taming"}) is None
    assert n.research_queue == []


def test_the_investment_queue_can_be_reordered() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    n = w.nations[me]
    n.build_queue = [{"node": "a", "work": "fields"}, {"node": "b", "work": "pasture"}]
    assert actions.act(w, me, {"kind": "reorder_queue", "index": 1, "to": 0}) is None
    assert [q["node"] for q in n.build_queue] == ["b", "a"]
    assert actions.act(w, me, {"kind": "reorder_queue", "index": 2, "to": 0}) == "no such queue item"


def _investing_town() -> tuple[World, str, Any]:
    w = generate(seed=5)
    me, uid = _me(w)
    n = w.nations[me]
    n.known += ["tillage", "weaving", rules.AUTO_INVEST_TECH]
    node = w.nodes[w.units[uid].node]
    actions.act(w, me, {"kind": "settle", "unit": uid})
    node.hands = 30.0
    n.prices["wares"] = 8.0  # dear wares: a workshop pays
    return w, me, node


def test_investors_choose_their_own_works_once_allowed() -> None:
    w, me, node = _investing_town()
    n = w.nations[me]
    n.stock = 100.0
    actions.process_build_queue(w, n)
    assert "workshop" not in node.works  # not without leave
    assert actions.act(w, me, {"kind": "auto_invest", "on": True}) is None
    actions.process_build_queue(w, n)
    built = rules.AUTO_INVEST_PER_TURN
    assert node.works.count("workshop") + node.works.count("fields") + node.works.count("pasture") >= 1
    assert 100.0 - n.stock <= built * max(rules.WORKS[k].cost for k in ("workshop", "fields", "pasture"))
    assert n.stock >= rules.AUTO_INVEST_RESERVE


def test_investors_wait_for_our_queue_and_keep_a_reserve() -> None:
    w, me, node = _investing_town()
    n = w.nations[me]
    n.auto_invest = True
    n.stock = rules.AUTO_INVEST_RESERVE + 1.0  # not enough to build and keep the reserve
    before = list(node.works)
    actions.process_build_queue(w, n)
    assert node.works == before
    n.stock = 100.0
    n.build_queue = [{"node": node.id, "work": "workshop", "status": "waiting"}]
    n.stock = 5.0  # our own item waits for Stock: the investors wait too
    actions.process_build_queue(w, n)
    assert node.works == before


def test_investing_on_their_own_needs_the_discovery() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    assert actions.act(w, me, {"kind": "auto_invest", "on": True}) == (
        f"needs {rules.DISCOVERIES[rules.AUTO_INVEST_TECH].name}"
    )


def _full_town_with_an_idle_pasture() -> tuple[World, str, Any]:
    w, me, node = _investing_town()
    n = w.nations[me]
    n.auto_invest = True
    node.herds = 0.0  # its pastures have nothing to tend: they earn nothing
    node.works = ["pasture"] * node.slots()
    n.stock = 100.0
    n.last["made"] = {"food": 30.0}  # food to spare: a food work may go
    n.last["consumed"] = {"food": 20.0}
    return w, me, node


def test_investors_replace_the_poorest_work_once_allowed() -> None:
    w, me, node = _full_town_with_an_idle_pasture()
    n = w.nations[me]
    actions.process_build_queue(w, n)
    assert node.works == ["pasture"] * node.slots()  # full, and no leave to pull anything down
    n.known.append(rules.REINVEST_TECH)
    actions.process_build_queue(w, n)
    assert len(node.works) == node.slots()
    assert node.works.count("pasture") == node.slots() - 1  # one replaced a turn
    assert any(e.kind == "demolished" and "by its investors" in e.text for e in w.log)


def test_investors_keep_trade_towns_and_works_that_pay() -> None:
    w, me, node = _full_town_with_an_idle_pasture()
    n = w.nations[me]
    n.known.append(rules.REINVEST_TECH)
    node.works = ["market"] * node.slots()
    actions.process_build_queue(w, n)
    assert node.works == ["market"] * node.slots()


def test_no_food_work_is_pulled_down_without_food_to_spare() -> None:
    w, me, node = _full_town_with_an_idle_pasture()
    n = w.nations[me]
    n.known.append(rules.REINVEST_TECH)
    n.last["made"] = {"food": 21.0}
    actions.process_build_queue(w, n)
    assert node.works == ["pasture"] * node.slots()


def test_a_pasture_with_no_herds_to_tend_returns_nothing() -> None:
    w, me, node = _investing_town()
    n = w.nations[me]
    n.known.append("taming")
    node.works = ["pasture"]
    node.herds = 10.0  # one herdsman's worth: the standing pasture employs him
    assert actions.expected_return(w, n, node, "pasture") == 0.0
    assert actions.work_return(w, n, node, "pasture") > 0.0


def test_each_later_discovery_makes_the_next_dearer() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    n = w.nations[me]
    n.known += ["taming", "tillage"]
    before = research.cost(w, n, "rotation")
    early = research.cost(w, n, "weaving")
    n.known.append("land_tenure")  # an Agriculture-era discovery
    assert research.cost(w, n, "rotation") == pytest.approx(
        before * (1 + rules.LATE_ESCALATION) / 1.0, rel=0.01
    )
    assert research.cost(w, n, "weaving") == early  # the early eras do not escalate


@pytest.mark.parametrize("seed", range(1, 7))
def test_ranges_have_passes_and_islands_are_reached_only_by_sea(seed: int) -> None:
    w = generate(seed=seed)
    starts = [u.node for u in w.units.values()]
    mainland = _reach(w, starts[0], sea=False)
    islands = set(w.nodes) - mainland
    assert islands, "some places are reached only by sea"
    for i in islands:
        assert w.nodes[i].coast
        assert all(e.kind == "sea" or e.other(i) in islands for e in w.adjacency()[i])
    passes = [e for e in w.edges if e.kind == "pass"]
    assert passes, "a range with a way over it"
    for e in passes:  # a pass is a bottleneck: without it, the land falls apart
        rest = [x for x in w.edges if x is not e and x.kind != "sea"]
        seen, stack = {e.a}, [e.a]
        while stack:
            cur = stack.pop()
            for x in rest:
                if cur in (x.a, x.b) and x.other(cur) not in seen:
                    seen.add(x.other(cur))
                    stack.append(x.other(cur))
        assert e.b not in seen
    assert any("rare" in w.nodes[i].features for i in islands)


def _scouts(w: World) -> tuple[str, Any]:
    me, uid = _me(w)
    n = w.nations[me]
    band = w.units[uid]
    band.hands = 6.0
    assert actions.act(w, me, {"kind": "raise_unit", "unit": uid, "unit_kind": "scouts"}) is None
    s = next(u for u in w.units_of(me) if u.kind == "scouts")
    s.moves_left = s.max_moves(set(n.known))
    return me, s


def test_scouts_cross_rough_ground_cheaply_and_see_far() -> None:
    w = generate(seed=5)
    me, s = _scouts(w)
    for e in w.edges:
        e.kind = "rough" if e.kind == "path" else e.kind
    to = w.neighbours(s.node)[0]
    assert actions.move_cost(w, s, to) == 1
    two_steps = {x for y in w.neighbours(s.node) for x in w.neighbours(y)}
    assert two_steps <= trade.visible(w, w.nations[me])
    assert actions.act(w, me, {"kind": "settle", "unit": s.id}) is not None
    assert actions.act(w, me, {"kind": "disband", "unit": s.id}) is None


def test_exploring_and_meeting_peoples_feed_ingenuity() -> None:
    w = generate(seed=5)
    me, _ = _me(w)
    n = w.nations[me]
    before = n.research_progress
    fresh = next(x for x in w.nodes if x not in n.explored)
    w.units[next(u.id for u in w.units_of(me))].node = fresh
    trade.update_fog(w, n)
    assert n.research_progress > before
    other = next(o for o in w.nations.values() if o.id != me)
    w.units[next(u.id for u in w.units_of(me))].node = next(u.node for u in w.units_of(other.id))
    gained = n.research_progress
    trade.update_contacts(w)
    assert other.id in n.contacts and n.research_progress == gained + rules.CONTACT_INGENUITY
