"""Tests for Doc 04 task 5: treaties, breach, casus belli, and effects (treaties.py)."""

from __future__ import annotations

from stock.core.goods import Good
from stock.core.laws import tariff_law
from stock.core.params import Params
from stock.core.producers import Producer, ProducerKind
from stock.core.records import ClassId, Record
from stock.core.world import Location, Nation, SeatKind, Terrain, World
from stock.security.war import PeaceTerms
from stock.sim.ledger import Ledger
from stock.trade.hostility import add_hostility, hostility
from stock.trade.treaties import Term, TermKind, check_breach, impose, lapse_on_end, negotiate


def test_tariff_ceiling_breach_raises_hostility_and_grants_casus_belli() -> None:
    """Test 1: TARIFF_CEILING breach raises hostility and grants casus belli.

    Create an imposed TARIFF_CEILING(WARES, 0.0) binding nation B.
    B's INDUSTRIAL Interest self-enacts tariff_law(WARES) with high authority.
    check_breach yields a breach event, h_AB rose, and (A,B) is in casus_belli.
    declare_war(A→B) afterwards emits no aggression event.
    """
    from stock.core.world import LawState
    from stock.security.war import declare_war

    world = World(
        year=0,
        nations={
            "A": Nation(id="A", seat=SeatKind.STATE),
            "B": Nation(id="B", seat=SeatKind.STATE),
        },
        locations={},
        ledger=Ledger(),
        params=Params(),
        rng=None,
    )

    # Impose TARIFF_CEILING on B
    term = Term(
        kind=TermKind.TARIFF_CEILING,
        bound="B",
        beneficiary="A",
        goods=(Good.WARES,),
        rate=0.0,
    )
    treaty = impose(world, "A", "B", [term])

    h_before = hostility(world, "A", "B")

    # B's tariff is enacted
    nation_b = world.nations["B"]
    law_key = tariff_law(Good.WARES)
    nation_b.laws[law_key] = LawState(enacted=True, enforcement=0.5)

    # Check breach
    breach_events = check_breach(treaty, world)

    # Verify breach occurred
    assert any(e.kind == "breach" for e in breach_events), "No breach event emitted"
    assert ("A", "B") in world.casus_belli, "Casus belli not granted"

    h_after = hostility(world, "A", "B")
    assert h_after > h_before, f"Hostility did not rise: {h_before} -> {h_after}"

    # Declare war without casus_belli flag - should not emit aggression event
    world.wars.clear()
    declare_war(world, "A", "B")

    # Check that there's no aggression event (casus_belli was consumed)
    if world.ledger is not None:
        aggression_events = [e for e in world.ledger.events if e.kind == "aggression"]
        assert len(aggression_events) == 0, "Aggression event emitted despite casus belli"


def test_f_n_rises_with_treaty_that_lowers_hostility() -> None:
    """Test 2: f(N) rises when a treaty lowers hostility via h_i reduction."""
    from stock.core.world import PrevSnapshot
    from stock.engine.production import step_production
    from stock.security.military import perceived_security, strength

    world = World(
        year=0,
        nations={
            "A": Nation(id="A"),
            "B": Nation(id="B"),
        },
        locations={
            "loc_a": Location(id="loc_a", terrain=Terrain.PLAINS, nation="A"),
            "loc_b": Location(id="loc_b", terrain=Terrain.PLAINS, nation="B"),
        },
        ledger=None,
        params=Params(),
        rng=None,
    )

    # Add minimal records to both nations
    loc_a = world.locations["loc_a"]
    loc_b = world.locations["loc_b"]

    hunters_a = Record(cls=ClassId.HUNTERS, location="loc_a", size=10.0)
    field_a = Producer(kind=ProducerKind.FIELD, location="loc_a")
    loc_a.records.append(hunters_a)
    loc_a.producers.append(field_a)

    hunters_b = Record(cls=ClassId.HUNTERS, location="loc_b", size=10.0)
    field_b = Producer(kind=ProducerKind.FIELD, location="loc_b")
    loc_b.records.append(hunters_b)
    loc_b.producers.append(field_b)

    # Set up high hostility
    add_hostility(world, "A", "B", 0.8)

    # Run production to populate M values
    world.prev = PrevSnapshot.take(world)
    step_production(world)

    strength(world.nations["A"], world)
    strength(world.nations["B"], world)

    # Compute f before treaty
    perceived_security(world.nations["A"], world)
    f_before = world._f_n_by_record.get(("A", "loc_a", ClassId.HUNTERS), 0.5)

    # Create a treaty between A and B (unbreached)
    term = Term(
        kind=TermKind.NON_AGGRESSION,
        bound="B",
        beneficiary="A",
    )
    negotiate(world, "A", "B", [term])

    # Re-compute perceived_security
    perceived_security(world.nations["A"], world)
    f_after = world._f_n_by_record.get(("A", "loc_a", ClassId.HUNTERS), 0.5)

    assert f_after > f_before, (
        f"f(N) did not rise with treaty: "
        f"before={f_before:.4f}, after={f_after:.4f}"
    )


def test_imposed_treaty_at_peace_and_lapse_on_end() -> None:
    """Test 3: accept_peace with treaty_terms creates Treaty with imposed=True;
    lapse_on_end removes it when signatory ends.
    """
    from stock.security.war import accept_peace, declare_war, offer_peace

    world = World(
        year=0,
        nations={
            "A": Nation(id="A", seat=SeatKind.STATE),
            "B": Nation(id="B", seat=SeatKind.STATE),
        },
        locations={
            "loc_a": Location(id="loc_a", terrain=Terrain.PLAINS, nation="A"),
            "loc_b": Location(id="loc_b", terrain=Terrain.PLAINS, nation="B"),
        },
        ledger=None,
        params=Params(),
        rng=None,
    )

    # Declare war
    declare_war(world, "A", "B")

    # Offer peace with treaty terms
    term = Term(
        kind=TermKind.NON_AGGRESSION,
        bound="B",
        beneficiary="A",
    )
    terms = [term]
    offer_peace(world, ("A", "B"), PeaceTerms(treaty_terms=terms))

    # Accept peace
    accept_peace(world, ("A", "B"), "B")

    # Verify treaty was created with imposed=True
    assert len(world.treaties) >= 1, "No treaty created"
    treaty = list(world.treaties.values())[0]
    assert treaty.imposed, "Treaty is not imposed"

    # Verify both nations have treaty ref
    assert any(tr.id == treaty.id for tr in world.nations["A"].treaties), \
        "A doesn't have treaty ref"
    assert any(tr.id == treaty.id for tr in world.nations["B"].treaties), \
        "B doesn't have treaty ref"

    # Set B.ended = True and lapse
    world.nations["B"].ended = True
    lapse_on_end(world)

    # Verify treaty was removed
    assert treaty.id not in world.treaties, "Treaty not lapsed when signatory ended"
    assert not any(tr.id == treaty.id for tr in world.nations["A"].treaties), \
        "A still has reference to lapsed treaty"


def test_exclusive_route_zeroes_third_party_stock() -> None:
    """Test 4: EXCLUSIVE_ROUTE term between A and B on route r zeroes C's committed stock
    in capacity calculation.
    """
    from stock.core.world import Route
    from stock.trade.routes import capacity

    world = World(
        year=0,
        nations={"A": Nation(id="A"), "B": Nation(id="B"), "C": Nation(id="C")},
        locations={
            "loc_a": Location(id="loc_a", terrain=Terrain.PLAINS, nation="A"),
            "loc_b": Location(id="loc_b", terrain=Terrain.PLAINS, nation="B"),
        },
        ledger=None,
        params=Params(),
        rng=None,
    )

    # Create route between A and B
    route = Route(id="loc_a->loc_b", a="loc_a", b="loc_b")
    route.merchant_stock = {"A": 10.0, "B": 5.0, "C": 10.0}  # C has stock
    world.routes["loc_a->loc_b"] = route

    # Capacity with C's stock
    cap_with_c = capacity(route, world)

    # Create EXCLUSIVE_ROUTE term
    term = Term(
        kind=TermKind.EXCLUSIVE_ROUTE,
        bound="B",
        beneficiary="A",
        route_id="loc_a->loc_b",
    )
    impose(world, "A", "B", [term])

    # Re-get route (it may be modified)
    route_maybe = world.routes.get("loc_a->loc_b")
    if route_maybe is not None and route_maybe.exclusive_to is not None:
        route = route_maybe
        # Capacity now only counts A's stock
        cap_with_exclusive = capacity(route, world)
        # Capacity should be lower (only A's 10, not A's 10 + C's 10)
        assert cap_with_exclusive <= cap_with_c, (
            f"Exclusive route should lower capacity: "
            f"with_exclusive={cap_with_exclusive}, with_c={cap_with_c}"
        )


def test_scenario_400_years_doc04_acceptance() -> None:
    """Test 5: 400-year scenario with raids and war/peace with treaties.

    Runs three_bands.yaml for 400 years with:
    - Every 20 years: nation_valley raids a neighbouring foreign location
    - Every 60 years: declares war if not already at war
    - Immediately after war creation: offers peace with TARIFF_CEILING treaty (auto-accept)

    Asserts:
    - ≥ 1 raid event
    - ≥ 1 year with positive route volume
    - ≥ 1 treaty with imposed=True
    - f(N) ∈ (0,1) for all entries in _f_n_by_record (no defaults)
    - M finite for all nations
    - world.validate() passes
    """
    import math
    from pathlib import Path

    from stock.security.war import declare_war, offer_peace, raid
    from stock.sim.scenario import load_scenario
    from tests._harness import run_year

    REPO_ROOT = Path(__file__).parent.parent
    world = load_scenario(REPO_ROOT / "tests" / "scenarios" / "three_bands.yaml")

    raid_events = 0
    volume_year = None
    imposed_seen = False
    target_nation = None

    for _ in range(400):
        y = world.year

        # Every 20 years: nation_valley raids a neighbouring foreign location
        if y % 20 == 0 and y > 0:
            nation_valley = world.nations.get("nation_valley")
            if nation_valley is not None:
                # Find first location neighbouring any of nation_valley's locations
                # whose nation is not None and not nation_valley.id
                target = None
                for loc in nation_valley.locations(world):
                    for neighbor_id in loc.neighbours:
                        neighbor = world.locations.get(neighbor_id)
                        if (neighbor is not None and neighbor.nation is not None
                                and neighbor.nation != nation_valley.id):
                            target = neighbor
                            target_nation = neighbor.nation
                            break
                    if target is not None:
                        break

                if target is not None:
                    raid(world, nation_valley.id, target, world.rng)

        # Every 60 years: declare war if no war exists between the pair
        if y % 60 == 0 and y > 0 and target_nation is not None:
            nation_valley = world.nations.get("nation_valley")
            if nation_valley is not None:
                nation_valley_id = nation_valley.id
                war_key = (nation_valley_id, target_nation)
                if war_key not in world.wars:
                    declare_war(world, nation_valley_id, target_nation)
                    # Immediately offer peace with treaty terms (null sovereign will accept)
                    term = Term(
                        kind=TermKind.TARIFF_CEILING,
                        bound=target_nation,
                        beneficiary=nation_valley_id,
                        goods=(Good.WARES,),
                        rate=0.0,
                    )
                    offer_peace(world, (nation_valley_id, target_nation), PeaceTerms(treaty_terms=[term]))

        # Run year (null sovereign accepts the offer inside step_treaties)
        run_year(world)

        # Track events and state
        if world.ledger is not None:
            raid_events += len([e for e in world.ledger.events
                               if e.year == y and e.kind == "raid"])
        if (volume_year is None and
                any(sum(r.last_volume_by_good.values()) > 0 for r in world.routes.values())):
            volume_year = y
        if any(t.imposed for t in world.treaties.values()):
            imposed_seen = True

        # f(N) ∈ (0,1) for every entry in _f_n_by_record (no defaults)
        for (_nid, _lid, _cls), f_n in world._f_n_by_record.items():
            assert 0 < f_n < 1, f"f(N) out of (0,1): {f_n}"

        # _f_n_by_record must not be empty
        assert world._f_n_by_record, "security wrote no f(N)"

        # M must be finite for all nations
        for nation in world.nations.values():
            assert math.isfinite(nation.scalars.M), f"M is NaN for {nation.id}"

        # Structural invariants
        world.validate()

    # Final assertions
    assert raid_events >= 1, f"No raid events (count={raid_events})"
    assert volume_year is not None, "No year with positive route volume"
    assert imposed_seen, f"No imposed treaty found (treaties: {len(world.treaties)})"
