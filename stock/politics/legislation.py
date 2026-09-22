"""The political pipeline: self-enactment, passing, veto, enforcement, and law
effects — year step 12c, and the legislative half of step 14 (DD §7.4-7.5; MM §13).
"""

from __future__ import annotations

from typing import Any

from stock.core.actions import Action, ActionKind, register_cost_fn
from stock.core.laws import LAW_TABLE, TRADE_LAW_TABLE, LawId, LawSpec
from stock.core.params import Params
from stock.core.records import ClassId, InterestId
from stock.core.world import InterestState, LawState, Nation, World
from stock.engine.mobility import vertical_flow
from stock.politics.interests import DEMANDS, Repeal, radicalism_update
from stock.sim.ledger import EventRecord


def _law_spec(law: LawId | str) -> LawSpec | None:
    return LAW_TABLE.get(law) if isinstance(law, LawId) else TRADE_LAW_TABLE.get(law)


def _authority(nation: Nation, interests: frozenset[InterestId]) -> float:
    return sum(nation.interests.get(i, InterestState()).authority for i in interests)


def _radicalism(nation: Nation, interests: frozenset[InterestId]) -> float:
    return sum(nation.interests.get(i, InterestState()).radicalism for i in interests)


def _passing_threshold(opp_authority: float, opp_radicalism: float, params: Params) -> float:
    """The right-hand side of `support+spend >= theta*opposition*(1+Sum opposing
    radicalism*w_r)` (MM §13)."""

    p = params.politics
    return p.theta * opp_authority * (1.0 + opp_radicalism * p.radicalism_weight_w_r)


def bar(law: LawId | str, nation: Nation, params: Params) -> tuple[float, float]:
    """`(support, opposition_term)` (MM §13): `opposition_term` is the full
    right-hand side of `passes`, so `cost = max(0, opposition_term - support)`."""

    spec = _law_spec(law)
    if spec is None:
        return 0.0, 0.0
    support = _authority(nation, spec.support)
    opp_authority = _authority(nation, spec.opposition)
    opp_radicalism = _radicalism(nation, spec.opposition)
    return support, _passing_threshold(opp_authority, opp_radicalism, params)


def _repeal_bar(law: LawId | str, nation: Nation, params: Params) -> tuple[float, float]:
    """Repealing a law must overcome those who *support* it — DD/MM give no separate
    repeal formula, so this is `bar` with support and opposition swapped; see
    DEVIATIONS.md."""

    spec = _law_spec(law)
    if spec is None:
        return 0.0, 0.0
    support = _authority(nation, spec.opposition)
    opp_authority = _authority(nation, spec.support)
    opp_radicalism = _radicalism(nation, spec.support)
    return support, _passing_threshold(opp_authority, opp_radicalism, params)


def passes(nation: Nation, law: LawId | str, spend: float, params: Params) -> bool:
    support, threshold = bar(law, nation, params)
    return support + spend >= threshold


def enforcement(law: LawId | str, nation: Nation, world: World) -> float:
    """`enf_law = J*A_S/(A_S+opposition_of_that_law)` (MM §13), floored above 0 (DD
    §7.5: "never zero") — the literal formula hits exactly 0 whenever `A_S=0` and
    opposition is positive, so a small epsilon floor is applied; see
    DEVIATIONS.md."""

    spec = _law_spec(law)
    if spec is None:
        return 0.0
    opposition = _authority(nation, spec.opposition)
    a_s = nation.scalars.A_S
    denom = a_s + opposition
    raw = (nation.scalars.J * a_s / denom) if denom > 0 else 0.0
    return float(max(raw, world.params.politics.enforcement_epsilon))


def _self_enactment_gap(
    nation: Nation, interest_state: InterestState, opposing_authority: float, params: Params
) -> float:
    lhs = interest_state.authority * (1.0 + interest_state.radicalism)
    rhs = params.politics.theta_prime * (nation.scalars.A_S + opposing_authority)
    return max(0.0, lhs - rhs)


def _veto_gap(nation: Nation, interest_id: InterestId, law: LawId | str, params: Params) -> float:
    spec = _law_spec(law)
    if spec is None:
        return 0.0
    interest_state = nation.interests.get(interest_id, InterestState())
    return _self_enactment_gap(nation, interest_state, _authority(nation, spec.opposition), params)


def enact(nation: Nation, law: LawId | str, spend: float, world: World) -> bool:
    if not passes(nation, law, spend, world.params):
        return False
    nation.scalars.A_S = max(0.0, nation.scalars.A_S - spend)
    state = nation.laws.setdefault(law, LawState())
    state.enacted = True
    state.enacted_year = world.year
    state.enforcement = enforcement(law, nation, world)
    return True


def repeal(nation: Nation, law: LawId | str, spend: float, world: World) -> bool:
    state = nation.laws.get(law)
    if state is None or not state.enacted:
        return False
    support, threshold = _repeal_bar(law, nation, world.params)
    if support + spend < threshold:
        return False
    nation.scalars.A_S = max(0.0, nation.scalars.A_S - spend)
    state.enacted = False
    return True


def veto(nation: Nation, interest_id: InterestId, law: LawId | str, world: World) -> bool:
    """Vetoes an Interest's self-enactment of `law` (MM §13): `cost = gap*premium`,
    and that demand goes on a `k_veto`-year cooldown (DD §7.5)."""

    cost = _veto_gap(nation, interest_id, law, world.params) * world.params.politics.veto_premium
    if cost > nation.scalars.A_S:
        return False
    nation.scalars.A_S -= cost
    state = nation.laws.setdefault(law, LawState())
    state.veto_cooldown_until = world.year + world.params.politics.k_veto
    return True


#: Customary law (DD §6.3's first property nodes; `PoliticsParams.custom_*_pop`):
#: `(law, name of the population-threshold param, needs a seat past BAND)`. Order is
#: the order they come to be: the kill before sharing before inheritance.
CUSTOMARY_LAWS: tuple[tuple[LawId, str, bool], ...] = (
    (LawId.KILL_TO_KILLER, "custom_kill_to_killer_pop", False),
    (LawId.SHARED_BY_CUSTOM, "custom_shared_by_custom_pop", False),
    (LawId.HERDS_HERITABLE, "custom_herds_heritable_pop", True),
)


def enact_by_custom(nation: Nation, world: World) -> list[EventRecord]:
    """The first laws are nobody's legislation: they settle in as custom once there
    are enough people for the question to come up. Each `CUSTOMARY_LAWS` entry
    enacts itself, at no `A_S` cost and past no bar, the first year the nation's
    population reaches its threshold (and the seat is past BAND where the law
    presupposes property — Herds heritable needs herds). Enforcement is computed
    as for any law. Emits `law_by_custom` with the population and threshold."""

    from stock.core.world import SeatKind

    events: list[EventRecord] = []
    population = nation.population(world)
    p = world.params.politics
    for law, param_name, needs_property in CUSTOMARY_LAWS:
        threshold = float(getattr(p, param_name))
        if threshold < 0:
            continue
        state = nation.laws.get(law)
        if state is not None and state.enacted:
            continue
        if needs_property and nation.seat is SeatKind.BAND:
            continue
        if population < threshold:
            continue
        state = nation.laws.setdefault(law, LawState())
        state.enacted = True
        state.enacted_year = world.year
        state.enforcement = enforcement(law, nation, world)
        events.append(
            EventRecord(
                year=world.year,
                nation=nation.id,
                kind="law_by_custom",
                numbers={"population": population, "threshold": threshold, "law": float(law.value)},
            )
        )
    if world.ledger is not None:
        for e in events:
            world.ledger.add_event(e)
    return events


def self_enact(nation: Nation, world: World) -> list[EventRecord]:
    """For each Interest, walk its demand table (`politics.interests.DEMANDS`); if
    the self-enactment condition holds (MM §13) and the demand isn't on a veto
    cooldown, enact (or repeal) it and emit `law_self_enacted` with the three
    numbers. At most one self-enactment per Interest per year."""

    events: list[EventRecord] = []
    for interest_id, demands in DEMANDS.items():
        interest_state = nation.interests.get(interest_id)
        if interest_state is None:
            continue
        for demand in demands:
            is_repeal = isinstance(demand, Repeal)
            law = demand.law if isinstance(demand, Repeal) else demand
            spec = _law_spec(law)
            if spec is None:
                continue
            state = nation.laws.get(law)
            currently_enacted = state is not None and state.enacted
            if is_repeal and not currently_enacted:
                continue
            if not is_repeal and currently_enacted:
                continue
            cooldown = state.veto_cooldown_until if state is not None else None
            if cooldown is not None and world.year < cooldown:
                continue

            opposing_authority = _authority(nation, spec.opposition)
            gap = _self_enactment_gap(nation, interest_state, opposing_authority, world.params)
            if gap <= 0.0:
                continue

            if is_repeal:
                assert state is not None
                state.enacted = False
            else:
                new_state = nation.laws.setdefault(law, LawState())
                new_state.enacted = True
                new_state.enacted_year = world.year
                new_state.enforcement = enforcement(law, nation, world)

            interest_state.radicalism = radicalism_update(
                interest_state.radicalism, 0.0, met=True, params=world.params
            )
            numbers = {
                "authority_I": interest_state.authority,
                "A_S": nation.scalars.A_S,
                "opposition": opposing_authority,
            }
            events.append(
                EventRecord(
                    year=world.year,
                    nation=nation.id,
                    kind="law_self_enacted",
                    numbers=numbers,
                )
            )
            break  # one self-enactment per Interest per year

    if world.ledger is not None:
        for e in events:
            world.ledger.add_event(e)
    return events


#: `vertical_flow` share applied per year while the law is enacted: a "forced" edge
#: (Enclosure) converts fast, scaled directly by enforcement; an unforced one
#: (Commutation) trickles at the law-free promotion rate, also enforcement-scaled
#: (DD §2.4's edges "gated by a law" — MM gives no separate rate for law-gated vs.
#: law-free edges, so the law-free rate is reused as the "gradual" case; see
#: DEVIATIONS.md).
def _apply_continuous_law_effects(nation: Nation, world: World) -> None:
    for law, state in nation.laws.items():
        if not state.enacted:
            continue
        spec = _law_spec(law)
        if spec is None:
            continue
        for effect in spec.effects:
            if effect.kind == "walk_away_multiplier":
                _apply_walk_away_multiplier(nation, world, effect.params, state.enforcement)
            elif effect.kind == "vertical_flow":
                _apply_vertical_flow_effect(nation, world, effect.params, state.enforcement)


def _apply_walk_away_multiplier(
    nation: Nation, world: World, effect_params: dict[str, Any], enf: float
) -> None:
    cls = ClassId[effect_params["cls"]]
    base = float(effect_params.get("base", 0.0))
    walk_away = base + (1.0 - base) * (1.0 - enf)
    for location in nation.locations(world):
        record = location.record(cls)
        if record is not None:
            record.walk_away = walk_away


def _apply_vertical_flow_effect(
    nation: Nation, world: World, effect_params: dict[str, Any], enf: float
) -> None:
    from_cls = ClassId[effect_params["from"]]
    to_cls = ClassId[effect_params["to"]]
    forced = bool(effect_params.get("forced", False))
    share = enf if forced else world.params.mobility.rate_v_base * enf
    for location in nation.locations(world):
        vertical_flow(location, from_cls, to_cls, share, world.params.population.extinct_size_epsilon)


def lapse_unenforceable(
    nation: Nation, world: World, *, unfunded: frozenset[Any] = frozenset()
) -> list[EventRecord]:
    """A law whose payer draw is unfunded (input from Doc 05, empty until then) or
    whose enforcement < `enf_min` for `k_lapse` years lapses, emitting `law_lapsed`
    (DD §7.4's "Lapse")."""

    events: list[EventRecord] = []
    for law, state in nation.laws.items():
        if not state.enacted:
            continue
        if state.enforcement < world.params.politics.enforcement_floor_enf_min or law in unfunded:
            state.years_below_enf_min += 1
        else:
            state.years_below_enf_min = 0
        if state.years_below_enf_min >= world.params.politics.k_lapse:
            state.enacted = False
            state.years_below_enf_min = 0
            events.append(
                EventRecord(
                    year=world.year,
                    nation=nation.id,
                    kind="law_lapsed",
                    numbers={"enforcement": state.enforcement},
                )
            )
    if world.ledger is not None:
        for e in events:
            world.ledger.add_event(e)
    return events


def step_legislation(world: World) -> None:
    """Year step 12c: self-enactment, fresh enforcement for every enacted law,
    law-gated continuous effects (using that fresh enforcement), then lapse checks."""

    from stock.core.world import SeatKind

    for nation in world.nations.values():
        if nation.ended:
            continue
        enact_by_custom(nation, world)  # custom needs no seat: bands have it too
        if nation.seat is SeatKind.BAND:
            continue
        self_enact(nation, world)
        for law, state in nation.laws.items():
            if state.enacted:
                state.enforcement = enforcement(law, nation, world)
        _apply_continuous_law_effects(nation, world)
        lapse_unenforceable(nation, world, unfunded=nation.scalars.unfunded_laws)


def apply_action(world: World, action: Action) -> bool:
    """Applies one legislative action queued at step 14 (`ENACT`/`REPEAL`/`VETO`) —
    a dispatcher Doc 05's step-14 loop (not built yet) will call. `SET_FOCUS`/
    `CLEAR_FOCUS` are handled by `politics.focus` directly (no bar to pass)."""

    from stock.politics.focus import clear_focus, set_focus

    nation = world.nations[action.nation]
    if action.kind is ActionKind.ENACT:
        return enact(nation, action.payload["law"], action.payload.get("spend", 0.0), world)
    if action.kind is ActionKind.REPEAL:
        return repeal(nation, action.payload["law"], action.payload.get("spend", 0.0), world)
    if action.kind is ActionKind.VETO:
        return veto(nation, action.payload["interest"], action.payload["law"], world)
    if action.kind is ActionKind.SET_FOCUS:
        set_focus(nation, action.payload["kind"], action.payload["node"], action.payload.get("location"))
        return True
    if action.kind is ActionKind.CLEAR_FOCUS:
        clear_focus(nation)
        return True
    return False


def _cost_enact(world: World, action: Action) -> float:
    nation = world.nations[action.nation]
    support, threshold = bar(action.payload["law"], nation, world.params)
    return max(0.0, threshold - support)


def _cost_repeal(world: World, action: Action) -> float:
    nation = world.nations[action.nation]
    support, threshold = _repeal_bar(action.payload["law"], nation, world.params)
    return max(0.0, threshold - support)


def _cost_veto(world: World, action: Action) -> float:
    nation = world.nations[action.nation]
    gap = _veto_gap(nation, action.payload["interest"], action.payload["law"], world.params)
    return float(gap * world.params.politics.veto_premium)


def _cost_focus(world: World, action: Action) -> float:
    return float(world.params.politics.focus_upkeep)


register_cost_fn(ActionKind.ENACT, _cost_enact)
register_cost_fn(ActionKind.REPEAL, _cost_repeal)
register_cost_fn(ActionKind.VETO, _cost_veto)
register_cost_fn(ActionKind.SET_FOCUS, _cost_focus)
