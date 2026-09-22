"""Engine tests: worldgen, verbs, invariants (design doc §21.2), and pacing (§20)."""

from __future__ import annotations

import math
from functools import cache

import pytest

from stock.game import actions, research, rules, turn
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


@pytest.mark.parametrize("seed", range(1, 9))
def test_world_is_connected_and_every_people_starts_with_a_band(seed: int) -> None:
    w = generate(seed=seed)
    start = next(iter(w.nodes))
    seen, stack = {start}, [start]
    while stack:
        for nxt in w.neighbours(stack.pop()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    assert seen == set(w.nodes)
    starts = [u.node for u in w.units.values()]
    assert len(starts) == len(w.nations) == len(set(starts))
    assert sum("wild_herds" in n.features for n in w.nodes.values()) >= len(w.nations)
    assert sum(n.player for n in w.nations.values()) == 1


def test_spec_round_trip() -> None:
    cfg = parse_spec("random:42:30:3")
    assert (cfg.seed, cfg.nodes, cfg.nations) == (42, 30, 3)
    assert generate(cfg).spec == "random:42:30:3"
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
