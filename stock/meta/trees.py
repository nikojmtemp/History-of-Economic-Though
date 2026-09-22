"""Tree gate evaluation — year step 10 (DD §6; Doc 05 task T3).

`evaluate_gates(world)` is the per-year walk that lights Tree I nodes per location
and Tree II nodes (production, defence, credit) per nation, for every living
nation. Nodes light and stay lit through regression (DD §13 step 4); a Tree II node
can go `idle` (lit but not currently in use) without ever un-lighting. The
Sovereign's Focus (`politics.focus.gate_reduction`) lowers the one gate it targets
— never opens a boolean gate (a law, a resource) — per DD §6.4's "lower the gate,
never open it".

`core.trees` owns node identities and the pure Tree I predicate (`tree1_gate_met`);
this module supplies the keyword context that predicate needs and owns every Tree
II predicate outright (DD §6.2 has no separate pure-predicate module for Tree II).

Event encoding (`node_lit`, numbers only — DD §14, Doc 00's "no prose" rule):
    {"tree": 1.0 | 2.0,
     "branch": 0.0 (Tree I; or Tree II production) | 1.0 (defence) | 2.0 (credit),
     "node": <enum member>.value,
     "location": <index of the location id in sorted(world.locations)>}  # Tree I only
`branch` is needed because `MethodId`, `DefenceNode`, and `CreditNode` are separate
enums whose `.value`s collide (e.g. `MethodId.SOLITARY_LABOUR.value ==
DefenceNode.NATION_IN_ARMS.value == CreditNode.BANK.value == 2`) — see
DEVIATIONS.md.
"""

from __future__ import annotations

from collections.abc import Callable

from stock.core.goods import TIER, Good
from stock.core.laws import FocusKind, LawId
from stock.core.params import TreeParams
from stock.core.producers import MethodId, ProducerKind
from stock.core.records import ClassId
from stock.core.trees import (
    CREDIT_CHAIN,
    DEFENCE_CHAIN,
    PRODUCTION_CHAIN,
    CreditNode,
    DefenceNode,
    NodeState,
    TreeINode,
    tree1_gate_met,
)
from stock.core.world import Location, Nation, SeatKind, World
from stock.engine.market import reachable_within
from stock.engine.production import herd_total
from stock.politics.focus import FocusEffect, gate_reduction
from stock.security.military import Doctrine, active_doctrine
from stock.sim.ledger import EventRecord

# ---------------------------------------------------------------------------
# Shared context helpers (nation-wide aggregates Tree I/II predicates both read)
# ---------------------------------------------------------------------------


def _has_producer_kind(nation: Nation, world: World, kind: ProducerKind) -> bool:
    return any(p.kind is kind for loc in nation.locations(world) for p in loc.producers)


def _record_total(nation: Nation, world: World, cls: ClassId) -> float:
    return sum(r.size for loc in nation.locations(world) for r in loc.records if r.cls is cls)


def _herd_total_nation(nation: Nation, world: World) -> float:
    return sum(herd_total(loc) for loc in nation.locations(world))


def _law_enacted(nation: Nation, law: LawId) -> bool:
    state = nation.laws.get(law)
    return state is not None and state.enacted


def _stock_total(nation: Nation, world: World) -> float:
    return sum(p.stock_in_place for loc in nation.locations(world) for p in loc.producers)


def _good_reachable(good: Good, location: Location, world: World, c_max: float) -> bool:
    """`good` is produced in `location`, reachable from it within `c_max` carriage
    cost (MM §9's extent of market — reused here as the Tree I "available" gate), or
    arrives on a route touching `location` with positive volume last year."""

    if any(p.outputs.get(good, 0.0) > 0 for p in location.producers):
        return True
    for loc_id in reachable_within(world, location, c_max):
        if loc_id == location.id:
            continue
        other = world.locations.get(loc_id)
        if other is not None and any(p.outputs.get(good, 0.0) > 0 for p in other.producers):
            return True
    for route in world.routes.values():
        if route.a != location.id and route.b != location.id:
            continue
        if route.last_volume_by_good.get(good, 0.0) > 0:
            return True
    return False


def _route_reaches_luxuries(location: Location, world: World) -> bool:
    """DD §6.1's second Luxuries door: "a route to a market that has them"."""

    for route in world.routes.values():
        if route.a != location.id and route.b != location.id:
            continue
        other_id = route.b if route.a == location.id else route.a
        other = world.locations.get(other_id)
        if other is None:
            continue
        if other.tree1.nodes[TreeINode.LUXURIES].lit:
            return True
        if (
            other.market.last_supply.get(Good.LUXURIES, 0.0) > 0
            or other.market.inventory.get(Good.LUXURIES, 0.0) > 0
        ):
            return True
    return False


def _market_size_with_c_max(good: Good, location: Location, world: World, c_max: float) -> float:
    """`engine.market.market_size`'s extent-of-market sum, re-derived with a
    caller-supplied `c_max` (for the Public Works Focus's carriage-cost cut, DD
    §6.4). `market_size` itself hardcodes `params.prices.c_max`, and
    `engine/market.py` is outside this task's file allowlist, so this stays a local
    read-only duplicate of that one loop rather than a change to its signature."""

    tier = TIER.get(good)
    if tier is None:
        return 0.0
    total = 0.0
    for loc_id in reachable_within(world, location, c_max):
        loc = world.locations[loc_id]
        for record in loc.records:
            total += record.last_spend_by_good.get(good, 0.0)
    return total


# ---------------------------------------------------------------------------
# Focus (DD §6.4): "lower the gate, never open it"
# ---------------------------------------------------------------------------


def _public_works_c_max(
    effect: FocusEffect | None, location_id: str, node_name: str, base_c_max: float
) -> float:
    """Public Works cuts carriage cost on the chosen edges — modelled here as
    stretching the `c_max` cutoff used by the reachability gates it targets
    (materials/wares availability, market_size), only for the node/location the
    Focus names."""

    if (
        effect is not None
        and effect.kind is FocusKind.PUBLIC_WORKS
        and effect.node == node_name
        and (effect.location is None or effect.location == location_id)
    ):
        return base_c_max / max(1e-6, 1.0 - effect.magnitude)
    return base_c_max


def _patent_threshold(effect: FocusEffect | None, node_name: str, base: float) -> float:
    """Patent lowers the targeted production node's numeric threshold."""

    if effect is not None and effect.kind is FocusKind.PATENT and effect.node == node_name:
        return base * (1.0 - effect.magnitude)
    return base


def _education_threshold(effect: FocusEffect | None, node_name: str, base: float) -> float:
    """Education lowers `dol_market_size_threshold` specifically (DD §6.4's
    "reduces the skill penalty of division of labour")."""

    if effect is not None and effect.kind is FocusKind.EDUCATION and effect.node == node_name:
        return base * (1.0 - effect.magnitude)
    return base


# ---------------------------------------------------------------------------
# Tree II — production (DD §6.2)
# ---------------------------------------------------------------------------


def _production_gate_met(
    method: MethodId, nation: Nation, world: World, effect: FocusEffect | None
) -> bool:
    p: TreeParams = world.params.tree

    if method is MethodId.SOLITARY_LABOUR:
        return nation.seat is SeatKind.BAND or _has_producer_kind(nation, world, ProducerKind.HUNTING)

    if method is MethodId.HERDING_WITH_DEPENDENTS:
        return (
            _has_producer_kind(nation, world, ProducerKind.HERDING)
            and _herd_total_nation(nation, world) > 0
        )

    if method is MethodId.BOUND_LABOUR:
        return _law_enacted(nation, LawId.LAND_OWNABLE) and _law_enacted(nation, LawId.SERFDOM)

    if method is MethodId.THREE_FIELD_ROTATION:
        threshold = _patent_threshold(effect, "THREE_FIELD_ROTATION", p.rotation_land_threshold)
        total_land = sum(
            pr.land_shares
            for loc in nation.locations(world)
            for pr in loc.producers
            if pr.kind is ProducerKind.FIELD
        )
        return total_land >= threshold

    if method is MethodId.HANDICRAFT:
        return any(loc.is_town() for loc in nation.locations(world))

    if method is MethodId.PUTTING_OUT:
        threshold = _patent_threshold(effect, "PUTTING_OUT", p.putting_out_stock_threshold)
        merchants_stock = sum(
            r.wealth.stock_in_place + r.wealth.hoard
            for loc in nation.locations(world)
            for r in loc.records
            if r.cls is ClassId.MERCHANTS
        )
        materials_in_town = False
        for loc in nation.locations(world):
            if not loc.is_town():
                continue
            c_max = _public_works_c_max(effect, loc.id, "PUTTING_OUT", world.params.prices.c_max)
            if _good_reachable(Good.MATERIALS, loc, world, c_max):
                materials_in_town = True
                break
        return merchants_stock >= threshold and materials_in_town

    if method is MethodId.MONEY_RENT:
        return _law_enacted(nation, LawId.COMMUTATION)

    if method is MethodId.MANUFACTORY:
        return (
            _law_enacted(nation, LawId.STOCK_SEPARABLE)
            and _record_total(nation, world, ClassId.LABOURERS) > 0
        )

    if method is MethodId.DIVISION_OF_LABOUR:
        threshold = _education_threshold(effect, "DIVISION_OF_LABOUR", p.dol_market_size_threshold)
        for loc in nation.locations(world):
            c_max = _public_works_c_max(effect, loc.id, "DIVISION_OF_LABOUR", world.params.prices.c_max)
            if _market_size_with_c_max(Good.WARES, loc, world, c_max) >= threshold:
                return True
        return False

    if method is MethodId.MACHINE_PRODUCTION:
        if not nation.tree2.production[MethodId.DIVISION_OF_LABOUR].lit:
            return False
        wares_threshold = _patent_threshold(effect, "MACHINE_PRODUCTION", p.machine_wares_threshold)
        capital_threshold = _patent_threshold(effect, "MACHINE_PRODUCTION", p.machine_capital_threshold)
        wares_q = sum(
            pr.last_Q * pr.outputs.get(Good.WARES, 0.0)
            for loc in nation.locations(world)
            for pr in loc.producers
        )
        has_ore = any(loc.resources.ore for loc in nation.locations(world))
        capital = _stock_total(nation, world)
        return wares_q >= wares_threshold and has_ore and capital >= capital_threshold

    if method is MethodId.MACHINERY_STEAM:
        # MACHINE_PRODUCTION + coal + "the Watt event" (DD §6.2). "watt" is a
        # world-level flag (meta/events.py, Doc 05 task T4c) — the invention exists
        # once discovered, but each nation still needs its own coal and
        # MACHINE_PRODUCTION prerequisites met to benefit from it.
        if not nation.tree2.production[MethodId.MACHINE_PRODUCTION].lit:
            return False
        has_coal = any(loc.resources.coal for loc in nation.locations(world))
        return has_coal and "watt" in world.flags

    raise AssertionError(f"unhandled MethodId {method}")


# ---------------------------------------------------------------------------
# Tree II — defence (DD §6.2)
# ---------------------------------------------------------------------------

#: Which doctrine each defence node corresponds to, for idle marking only
#: (`active_doctrine` is never read for gating — Doc 05's brief is explicit about
#: that split). FIREARMS/NAVY aren't doctrines; they fall through to the gate check.
_DEFENCE_DOCTRINE: dict[DefenceNode, Doctrine] = {
    DefenceNode.EVERY_MAN_A_WARRIOR: Doctrine.EVERY_MAN,
    DefenceNode.NATION_IN_ARMS: Doctrine.NATION_IN_ARMS,
    DefenceNode.FEUDAL_HOST: Doctrine.FEUDAL_HOST,
    DefenceNode.MILITIA: Doctrine.MILITIA,
    DefenceNode.STANDING_ARMY: Doctrine.STANDING_ARMY,
}


def _defence_gate_met(node: DefenceNode, nation: Nation, world: World) -> bool:
    p: TreeParams = world.params.tree

    if node is DefenceNode.EVERY_MAN_A_WARRIOR:
        return True

    if node is DefenceNode.NATION_IN_ARMS:
        return _herd_total_nation(nation, world) > 0

    if node is DefenceNode.FEUDAL_HOST:
        has_field = _has_producer_kind(nation, world, ProducerKind.FIELD)
        return has_field and _record_total(nation, world, ClassId.RETAINERS) > 0

    if node is DefenceNode.MILITIA:
        return _law_enacted(nation, LawId.MILITIA_ACT)

    if node is DefenceNode.STANDING_ARMY:
        return (
            _law_enacted(nation, LawId.STANDING_ARMY_ACT)
            and nation.scalars.defence_draw > 0
            and _record_total(nation, world, ClassId.LABOURERS) > 0
        )

    if node is DefenceNode.FIREARMS:
        return nation.scalars.arms_stock >= p.firearms_arms_threshold

    if node is DefenceNode.NAVY:
        has_port = _has_producer_kind(nation, world, ProducerKind.PORT)
        ships_supply = any(
            loc.market.last_supply.get(Good.SHIPS, 0.0) > 0 for loc in nation.locations(world)
        )
        return has_port and ships_supply

    raise AssertionError(f"unhandled DefenceNode {node}")


def _defence_in_use(node: DefenceNode, nation: Nation, world: World) -> bool:
    doctrine = _DEFENCE_DOCTRINE.get(node)
    if doctrine is not None:
        return active_doctrine(nation, world) is doctrine
    return _defence_gate_met(node, nation, world)


# ---------------------------------------------------------------------------
# Tree II — credit (DD §6.2)
# ---------------------------------------------------------------------------


def _credit_gate_met(node: CreditNode, nation: Nation, world: World) -> bool:
    if node is CreditNode.BILLS_OF_EXCHANGE:
        has_port = _has_producer_kind(nation, world, ProducerKind.PORT)
        merchants_stock = sum(
            r.wealth.stock_in_place
            for loc in nation.locations(world)
            for r in loc.records
            if r.cls is ClassId.MERCHANTS
        )
        return has_port and merchants_stock > 0
    if node is CreditNode.BANK:
        return False  # v2 (DD §6.2); stays dark
    raise AssertionError(f"unhandled CreditNode {node}")


# ---------------------------------------------------------------------------
# Chain walk (shared by production/defence/credit)
# ---------------------------------------------------------------------------


def _walk_chain[Node](
    states: dict[Node, NodeState],
    chain: tuple[Node, ...],
    gate_met_fn: Callable[[Node], bool],
    in_use_fn: Callable[[Node], bool],
    year: int,
) -> list[Node]:
    """Walks a Tree II chain in DD §6.2 order. A node lights the first year its own
    gate is met *and* its predecessor is already lit (chain order); once lit it
    never un-lights. `idle` is recomputed every year from `in_use_fn` regardless of
    the lighting decision (DD §6: "a HOW node lit but idle"). Returns the nodes
    newly lit this call, in chain order, for event emission."""

    newly_lit: list[Node] = []
    prev_lit = True
    for node in chain:
        state = states[node]
        if not state.lit and prev_lit and gate_met_fn(node):
            state.lit = True
            state.lit_year = year
            newly_lit.append(node)
        state.idle = state.lit and not in_use_fn(node)
        prev_lit = state.lit
    return newly_lit


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def _emit_node_lit(
    world: World,
    nation_id: str,
    *,
    tree: int,
    branch: int,
    node_value: int,
    location_index: int | None = None,
) -> None:
    if world.ledger is None:
        return
    numbers: dict[str, float] = {
        "tree": float(tree),
        "branch": float(branch),
        "node": float(node_value),
    }
    if location_index is not None:
        numbers["location"] = float(location_index)
    world.ledger.add_event(
        EventRecord(year=world.year, nation=nation_id, kind="node_lit", numbers=numbers)
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def evaluate_tree1(
    location: Location, nation: Nation, world: World, effect: FocusEffect | None = None
) -> None:
    """Tree I (DD §6.1), one location: computes the keyword context
    `core.trees.tree1_gate_met` needs and lights whichever nodes newly qualify.
    `effect` may be precomputed by a caller looping many locations for one nation
    (`evaluate_gates`); computed fresh if omitted."""

    if effect is None:
        effect = gate_reduction(nation, world.params)

    tparams: TreeParams = world.params.tree
    base_c_max = world.params.prices.c_max

    craftsmen = location.record(ClassId.CRAFTSMEN)
    craftsmen_present = craftsmen is not None and craftsmen.size > 0
    settled = any(p.kind is ProducerKind.FIELD for p in location.producers)
    manufactory_or_ironworks = _has_producer_kind(nation, world, ProducerKind.MANUFACTORY)
    route_reaches_luxuries = _route_reaches_luxuries(location, world)
    location_index = sorted(world.locations).index(location.id)

    # `_good_reachable` runs a Dijkstra search (`engine.market.reachable_within`);
    # `_public_works_c_max` returns `base_c_max` unchanged unless a Public Works
    # Focus targets this exact node/location, so nearly every node below shares the
    # same `c_max` — compute it once per good and reuse it instead of once per node
    # (was up to 2 Dijkstra runs per *unlit* node, of which there are up to 8).
    materials_at_base = _good_reachable(Good.MATERIALS, location, world, base_c_max)
    wares_at_base = _good_reachable(Good.WARES, location, world, base_c_max)

    for node in TreeINode:
        state = location.tree1.nodes[node]
        if state.lit:
            continue
        if node is TreeINode.DOMESTICATED_HERDS:
            # Owned exclusively by `engine.band.tame_herd`'s event (DD §3, §7.3):
            # `tree1_gate_met`'s predicate is only this node's *precondition*
            # (grazing + contact) — the actual event converts hunters into
            # herd-owners/herdsmen and seeds the herd, which this generic
            # gate-only walk has no way to do (and `band.py` is outside this
            # task's file allowlist). Lighting it from the bare precondition here
            # would mark the node lit with no herd ever created, pre-empting
            # `tame_herd`'s own `if node.lit: return False` guard on every future
            # year. See DEVIATIONS.md.
            continue
        c_max = _public_works_c_max(effect, location.id, node.name, base_c_max)
        if c_max == base_c_max:
            materials_available = materials_at_base
            wares_available = wares_at_base
        else:
            materials_available = _good_reachable(Good.MATERIALS, location, world, c_max)
            wares_available = _good_reachable(Good.WARES, location, world, c_max)
        met = tree1_gate_met(
            node,
            has_game=location.resources.game,
            has_grazing=location.resources.grazing,
            has_arable=location.resources.arable,
            has_rare=location.resources.rare,
            has_ore=location.resources.ore,
            has_coal=location.resources.coal,
            is_coast=location.coast,
            contact=location.contact.get(nation.id, 0.0),
            contact_threshold=tparams.contact_threshold,
            settled=settled,
            is_town=location.is_town(),
            craftsmen_present=craftsmen_present,
            materials_available=materials_available,
            wares_available=wares_available,
            route_reaches_luxuries=route_reaches_luxuries,
            manufactory_or_ironworks=manufactory_or_ironworks,
        )
        if met:
            state.lit = True
            state.lit_year = world.year
            _emit_node_lit(
                world,
                nation.id,
                tree=1,
                branch=0,
                node_value=node.value,
                location_index=location_index,
            )


def evaluate_tree2(nation: Nation, world: World, effect: FocusEffect | None = None) -> None:
    """Tree II (DD §6.2), one nation: production, defence, and credit chains, each
    walked in DD order with the predecessor-lit chain rule."""

    if effect is None:
        effect = gate_reduction(nation, world.params)

    newly_lit_production = _walk_chain(
        nation.tree2.production,
        PRODUCTION_CHAIN,
        lambda m: _production_gate_met(m, nation, world, effect),
        lambda m: _production_gate_met(m, nation, world, effect),
        world.year,
    )
    for method in newly_lit_production:
        _emit_node_lit(world, nation.id, tree=2, branch=0, node_value=method.value)

    newly_lit_defence = _walk_chain(
        nation.tree2.defence,
        DEFENCE_CHAIN,
        lambda n: _defence_gate_met(n, nation, world),
        lambda n: _defence_in_use(n, nation, world),
        world.year,
    )
    for defence_node in newly_lit_defence:
        _emit_node_lit(world, nation.id, tree=2, branch=1, node_value=defence_node.value)

    newly_lit_credit = _walk_chain(
        nation.tree2.credit,
        CREDIT_CHAIN,
        lambda n: _credit_gate_met(n, nation, world),
        lambda n: _credit_gate_met(n, nation, world),
        world.year,
    )
    for node in newly_lit_credit:
        _emit_node_lit(world, nation.id, tree=2, branch=2, node_value=node.value)


def evaluate_gates(world: World) -> None:
    """Year step 10 (DD §6, §13): lights Tree I nodes per location and Tree II
    nodes per nation, for every living nation, once per year. Never un-lights a
    node; regression (Doc 05's `meta/regression.resolve`, a later task) keeps nodes
    lit and marks them idle instead (DD §13 step 4).

    Not wired into `sim/year.py` (that module isn't built by this task) nor into
    `tests/_harness.py::run_year` (outside this task's file allowlist) — see this
    task's Blockers for the exact call-site line to add."""

    for nation in world.nations.values():
        if nation.ended:
            continue
        effect = gate_reduction(nation, world.params)
        for location in nation.locations(world):
            evaluate_tree1(location, nation, world, effect)
        evaluate_tree2(nation, world, effect)


def carrying_configuration(nation: Nation, world: World) -> set[MethodId]:
    """The highest set of Tree II production nodes whose gates are met *right now*
    by surviving assets (DD §13: regression's "carrying configuration" uses this,
    not stage labels) — pure, no mutation, no event emission. For
    `meta/regression.resolve` (a later task) to size a nation's post-regression
    producers against. Chain order/predecessor rule mirrors `_walk_chain`'s gating
    pass, but nothing here is written to `nation.tree2` (that only ever grows via
    `evaluate_tree2`)."""

    effect = gate_reduction(nation, world.params)
    result: set[MethodId] = set()
    prev_met = True
    for method in PRODUCTION_CHAIN:
        met = prev_met and _production_gate_met(method, nation, world, effect)
        if met:
            result.add(method)
        prev_met = met
    return result
