"""The three curves (MM §22; Doc 05).

Computed per nation per year from this year's flows and records, and written to
`nation.curves` for `sim/year.py` to copy into the ledger row.
"""

from __future__ import annotations

from stock.core.params import ScoreboardParams
from stock.core.producers import ProducerKind
from stock.core.world import Nation, SeatKind, World

#: All producer kinds except STATE count as productive (DD §14.1: Attendance,
#: soldiers', and servants' maintenance is property income spent, and must never be
#: counted a second time as labour income or output).
PRODUCTIVE_KINDS: frozenset[ProducerKind] = frozenset(ProducerKind) - {ProducerKind.STATE}


def _population(nation: Nation, world: World) -> float:
    return sum(r.size for loc in nation.locations(world) for r in loc.records)


def productive_v(nation: Nation, world: World) -> float:
    """Sum of `last_V` over productive producers only (shared with meta/hegemony.py's
    production_share and winners())."""
    return sum(
        p.last_V for loc in nation.locations(world) for p in loc.producers if p.kind in PRODUCTIVE_KINDS
    )


def produce_per_head(nation: Nation, world: World) -> float:
    pop = _population(nation, world)
    if pop <= 0:
        return 0.0
    return productive_v(nation, world) / pop


def labour_share(nation: Nation) -> float:
    """Labour income of productive records / (labour income + profit + rent), those
    records only (`nation.flows` is already scoped this way — see
    `engine.production`/`engine.wages`). In a band, 1.0 by construction (no property
    income exists yet)."""

    if nation.seat is SeatKind.BAND:
        return 1.0
    labour = nation.flows.get("labour_income", 0.0)
    profit = nation.flows.get("profit", 0.0)
    rent = nation.flows.get("rent", 0.0)
    total = labour + profit + rent
    if total <= 0:
        return 0.0
    return labour / total


def freedom_index(nation: Nation, world: World, params: ScoreboardParams) -> float:
    pop = _population(nation, world)
    if pop <= 0:
        return 0.0
    free_size = sum(
        r.size
        for loc in nation.locations(world)
        for r in loc.records
        if r.walk_away > params.wa_free
    )
    return free_size / pop


def step_scoreboards(world: World) -> None:
    """The three curves per nation per year, plus the N_bar band alongside curve 1."""

    params = world.params.scoreboard if world.params else ScoreboardParams()
    for nation in world.nations.values():
        if nation.ended:
            continue
        nation.curves = {
            "produce_per_head": produce_per_head(nation, world),
            "labour_share": labour_share(nation),
            "freedom_index": freedom_index(nation, world, params),
            "N_bar": nation.scalars.N_bar,
        }
