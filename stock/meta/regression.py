"""Regression: the spiral, discrete triggers, resolve, and end_nation (step 13c; Doc 05).

`resolve()` never reads a "stage" — it queries `meta/trees.carrying_configuration`
directly, per this doc's own instruction ("a manufactory economy can fall to
putting-out, a settled nation back to herding if the fields are lost and the herds
are not"). Producer-kind-level substitution (a MANUFACTORY's workers becoming a
PUTTING_OUT producer's workers) is not modelled explicitly: instead, a producer whose
current method drops out of the carrying configuration loses that method (reverts to
`MethodId.NONE`) and a share of its stock; the class occupying it is unchanged (Doc
02's `JOB_CLASS` already maps MANUFACTORY/PUTTING_OUT/MINE to the same LABOURERS
class, so no class flow is needed there), and the normal production step re-fills
jobs from whatever producers/methods remain viable next year. Logged as A39.

`end_nation`'s final ledger is built from the nation's *last flushed ledger row*, not
live world state — by the time "no location and no herd" is true, `nation.locations
(world)` is already empty (the last location's records dissolved to the conqueror via
`security.war.transfer_location`, or starved out via `engine.population`), so nothing
is left to query directly. Several of this doc's named fields (peak values, emigrated
count, military dead, plunder taken, hoard share, wars suffered) have no tracking
field anywhere else in the codebase; they are approximated from the ledger's event
history where possible and otherwise recorded as 0.0. Logged as A40.
"""

from __future__ import annotations

import math

from stock.core.params import RegressionParams
from stock.core.producers import MethodId
from stock.core.records import ClassId
from stock.core.world import Nation, World
from stock.meta.scoreboards import produce_per_head
from stock.meta.trees import carrying_configuration
from stock.politics.unrest import expected_needs_update
from stock.security.military import strength
from stock.sim.ledger import EventRecord

#: Classes whose maintenance is property income spent, not labour income or output
#: (Doc 05's scoreboards module note) — excluded from "productive population".
UNPRODUCTIVE_CLASSES: frozenset[ClassId] = frozenset(
    {ClassId.SOLDIERS, ClassId.RETAINERS, ClassId.SERVANTS, ClassId.COLLECTORS, ClassId.STATE, ClassId.CLERGY}
)


def _stock_total(nation: Nation, world: World) -> float:
    return sum(
        r.wealth.stock_in_place + r.wealth.herd for loc in nation.locations(world) for r in loc.records
    )


def _events_for(world: World, nation_id: str, year: int | None = None) -> list[EventRecord]:
    if world.ledger is None:
        return []
    events = world.ledger.events_in_year(year) if year is not None else world.ledger.events
    return [e for e in events if e.nation == nation_id]


# --- Spiral ---


def spiral_window(nation: Nation, world: World, params: RegressionParams) -> bool:
    """A spiral triggers when, for `k_spiral` consecutive years, `N_bar < N_crit` and
    falling, `U_dis > U_crit`, `Sigma to_reinvest ~= 0`, and produce per head is
    falling. Tracks the run in `nation.scalars.spiral_years` (reset the first year any
    condition fails); `nation.scalars.regression_warning` reflects how full the
    window is while it fills, for the UI."""

    s = nation.scalars
    ppc = produce_per_head(nation, world)
    reinvest = nation.flows.get("to_reinvest", 0.0)

    met = (
        s.N_bar < params.n_crit
        and s.N_bar < s.prev_n_bar
        and s.U_dis > params.u_crit
        and abs(reinvest) < params.reinvest_zero_epsilon
        and ppc < s.prev_produce_per_head
    )
    s.spiral_years = s.spiral_years + 1 if met else 0
    s.prev_n_bar = s.N_bar
    s.prev_produce_per_head = ppc
    s.regression_warning = 0 < s.spiral_years < params.k_spiral
    return s.spiral_years >= params.k_spiral


def discrete_triggers(nation: Nation, world: World, params: RegressionParams) -> bool:
    """Mutiny; capital loss exceeding `kappa_loss*stock` in a war, or a Port taken
    (approximated here as any location lost this year — see A40); a revolt the army
    fails to contain (any `revolt` event, since `army_inside` already suppresses the
    event when the army *does* contain it); a Provisions route or grain guarantee
    broken for more than `k_food` years; a default exceeding `kappa_def*stock`."""

    events = _events_for(world, nation.id, world.year)
    kinds = {e.kind for e in events}
    if "mutiny" in kinds or "revolt" in kinds or "location_lost" in kinds:
        return True

    stock = _stock_total(nation, world)
    for e in events:
        if e.kind in ("default", "private_credit_default") and stock > 0:
            written_off = e.numbers.get("debt_written_off", e.numbers.get("written_off", 0.0))
            if written_off > params.kappa_def * stock:
                return True
        if e.kind == "breach" and e.numbers.get("years_breached", 0.0) >= params.k_food:
            return True
    return False


# --- Resolve ---


def resolve(nation: Nation, world: World) -> None:
    """A regression, in order: (1)+(2) the carrying configuration and each producer's
    fallback; (3) unenforceable-law lapsing (already handled by the ordinary step 12,
    which ran earlier this year — nothing further here); (4) Tree I/II nodes stay lit
    but idle; (5) `E := A` at rate `alpha_collapse`; (6) `PSV := a*ln(1+M_surviving)`."""

    params = world.params
    if params is None:
        return

    carrying = carrying_configuration(nation, world)
    loss = params.regression.collapse_stock_loss
    for loc in nation.locations(world):
        for producer in loc.producers:
            if producer.method is not MethodId.NONE and producer.method not in carrying:
                producer.stock_in_place = max(0.0, producer.stock_in_place * (1.0 - loss))
                producer.method = MethodId.NONE

    for method, state in nation.tree2.production.items():
        if state.lit:
            state.idle = method not in carrying

    for loc in nation.locations(world):
        for r in loc.records:
            expected_needs_update(r, params.unrest.alpha_up, params.unrest.alpha_collapse)

    m_surviving, _ = strength(nation, world)
    nation.scalars.PSV = params.security.security_scale_a * math.log(1.0 + max(0.0, m_surviving))

    nation.scalars.regressions += 1
    nation.scalars.spiral_years = 0
    nation.scalars.regression_warning = False

    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(
                year=world.year,
                nation=nation.id,
                kind="regression",
                numbers={"regressions": float(nation.scalars.regressions), "M_surviving": m_surviving},
            )
        )


def check_and_resolve(nation: Nation, world: World, params: RegressionParams) -> bool:
    """Step 13c: runs `spiral_window` and `discrete_triggers`; calls `resolve` if
    either fires. Returns whether a regression happened this year."""

    spiral = spiral_window(nation, world, params)  # always runs: it keeps the window's counters
    last = nation.scalars.last_regression_year
    if last is not None and 0 <= world.year - last < params.cooldown_years:
        # A regression is a configuration change, not a yearly tax (measured: 25
        # regressions in 33 years before this). See DEVIATIONS-IN-PROGRESS.md A70.
        return False
    triggered = spiral or discrete_triggers(nation, world, params)
    if triggered:
        resolve(nation, world)
        nation.scalars.last_regression_year = world.year
    return triggered


# --- End of a nation ---


def _top_rivals(world: World, nation_id: str, n: int = 3) -> list[tuple[str, float]]:
    scored = [
        (other, h)
        for (a, b), h in world.hostility.items()
        for other in ([b] if a == nation_id else [a] if b == nation_id else [])
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:n]


def _law_event_counts(world: World, nation_id: str) -> tuple[float, float, float]:
    enacted = repealed = lapsed = 0.0
    for e in _events_for(world, nation_id):
        if e.kind == "law_enacted":
            enacted += 1
        elif e.kind == "law_repealed":
            repealed += 1
        elif e.kind == "law_lapsed":
            lapsed += 1
    return enacted, repealed, lapsed


def _final_ledger(nation: Nation, world: World) -> dict[str, float]:
    rows = world.ledger.rows_for(nation.id) if world.ledger is not None else []
    last = rows[-1] if rows else None
    scalars = last.scalars if last is not None else {}
    curves = last.curves if last is not None else {}
    class_sizes = last.class_sizes if last is not None else {}

    population = sum(class_sizes.values())
    productive_pop = sum(v for k, v in class_sizes.items() if k not in {c.name for c in UNPRODUCTIVE_CLASSES})
    unproductive_pop = population - productive_pop

    lifetime_events = _events_for(world, nation.id)
    wars_declared = sum(1 for e in lifetime_events if e.kind == "war_declared")
    wars_won = sum(1 for e in lifetime_events if e.kind == "victory")
    wars_lost = sum(1 for e in lifetime_events if e.kind == "defeat")
    locations_taken = sum(1 for e in lifetime_events if e.kind == "location_taken")
    locations_lost = sum(1 for e in lifetime_events if e.kind == "location_lost")
    recent_conquest = any(
        e.kind == "location_lost" for e in _events_for(world, nation.id, world.year)
    ) or any(e.kind == "location_lost" for e in _events_for(world, nation.id, world.year - 1))
    laws_enacted, laws_repealed, laws_lapsed = _law_event_counts(world, nation.id)

    result: dict[str, float] = {
        "turns_elapsed": float(last.year if last is not None else world.year),
        "terminal_condition": 1.0 if recent_conquest else 0.0,  # 1 = conquered, 0 = internal collapse
        "regressions_suffered": scalars.get("regressions", 0.0),
        "curve_produce_per_head_final": curves.get("produce_per_head", 0.0),
        "curve_labour_share_final": curves.get("labour_share", 0.0),
        "curve_freedom_index_final": curves.get("freedom_index", 0.0),
        # Peaks are not tracked anywhere else in the codebase; the final value stands
        # in for the peak (A40) pending dedicated peak-tracking infrastructure.
        "curve_produce_per_head_peak": curves.get("produce_per_head", 0.0),
        "curve_labour_share_peak": curves.get("labour_share", 0.0),
        "curve_freedom_index_peak": curves.get("freedom_index", 0.0),
        "population": population,
        "productive_population": productive_pop,
        "unproductive_population": unproductive_pop,
        "emigrated_count": 0.0,  # not tracked elsewhere (A40)
        "military_dead": 0.0,  # not tracked elsewhere (A40)
        "locations_held_at_end": 0.0,  # locations are already gone by end_nation (A40)
        "locations_held_peak": 0.0,  # not tracked elsewhere (A40)
        "stock": sum(last.class_wealth.values()) if last is not None else 0.0,
        "hoard_share": 0.0,  # hoard is not broken out of class_wealth in the ledger row (A40)
        "interest_rate": scalars.get("r_sovereign", 0.0),
        "debt_revenue_ratio": (
            scalars.get("debt", 0.0) / scalars["revenue"] if scalars.get("revenue", 0.0) > 0 else 0.0
        ),
        "defaults": 1.0 if scalars.get("default_history", 0.0) else 0.0,
        "laws_enacted": laws_enacted,
        "laws_repealed": laws_repealed,
        "laws_lapsed": laws_lapsed,
        "tree_nodes_lit": float(sum(1 for s in nation.tree2.production.values() if s.lit)),
        "wars_declared": float(wars_declared),
        "wars_suffered": 0.0,  # no defender-id field on war_declared events to count from (A40)
        "wars_won": float(wars_won),
        "wars_lost": float(wars_lost),
        "locations_taken": float(locations_taken),
        "locations_lost": float(locations_lost),
        "plunder_taken": 0.0,  # not tracked elsewhere (A40)
    }
    for i, (rival_id, hostility) in enumerate(_top_rivals(world, nation.id), start=1):
        result[f"rival{i}_hostility"] = hostility
        result[f"rival{i}_strength"] = world.prev.M.get(rival_id, 0.0)
        result[f"rival{i}_trade_volume"] = world.trade_volume.get(
            (nation.id, rival_id), 0.0
        ) or world.trade_volume.get((rival_id, nation.id), 0.0)
        result[f"rival{i}_treaties"] = world.kept_treaties_count.get(
            (nation.id, rival_id), 0.0
        ) or world.kept_treaties_count.get((rival_id, nation.id), 0.0)
    return result


def end_nation(nation: Nation, world: World) -> None:
    """A nation ends when it holds no location (and, inseparably, no herd — nothing
    is left to hold one once locations are gone). Records already dissolved to the
    conqueror or vanished by the time this fires (`security.war.transfer_location` /
    `engine.population`'s extinction handling); this function's own job is the
    treaty lapse and the final-ledger snapshot."""

    if nation.locations(world):
        return

    nation.final_ledger = _final_ledger(nation, world)
    nation.treaties = []
    nation.ended = True

    if world.ledger is not None:
        world.ledger.add_event(
            EventRecord(year=world.year, nation=nation.id, kind="nation_ended", numbers={})
        )
