"""World shares, the hegemony countdown, and winners (MM §23; Doc 05, step 13d)."""

from __future__ import annotations

from stock.core.params import ScoreboardParams
from stock.core.world import HegemonyState, Nation, SeatKind, World
from stock.meta.scoreboards import produce_per_head, productive_v


def _capital(nation: Nation, world: World) -> float:
    """Stock in place + herds + hoards + treasure (DD §1.4)."""
    total = nation.scalars.treasure
    for loc in nation.locations(world):
        for r in loc.records:
            total += r.wealth.stock_in_place + r.wealth.herd + r.wealth.hoard
    return total


def _share(values: dict[str, float]) -> dict[str, float]:
    total = sum(values.values())
    if total <= 0:
        return dict.fromkeys(values, 0.0)
    return {k: v / total for k, v in values.items()}


def world_shares(world: World) -> None:
    """`capital_share`, `consumption_share`, `production_share` of the world total,
    and `flags_n = #{k : share_k,n >= H_share}`. Writes to `world.hegemony` and
    advances the countdown."""

    params = world.params.scoreboard if world.params else ScoreboardParams()
    living = [n for n in world.nations.values() if not n.ended]

    capital = {n.id: _capital(n, world) for n in living}
    consumption = {n.id: n.flows.get("consumption", 0.0) for n in living}
    production = {n.id: productive_v(n, world) for n in living}

    cap_share = _share(capital)
    cons_share = _share(consumption)
    prod_share = _share(production)

    # A band has no capital and next to no consumption or production, so shares
    # against a world of bands are trivially ≥ H_share (measured: 0.97 capital share
    # the year the first band settled). Flags count only once `h_min_settled` living
    # nations hold a seat beyond BAND; until then the countdown never starts (and
    # resets if it had). See DEVIATIONS-IN-PROGRESS.md A69.
    settled = sum(1 for n in living if n.seat is not SeatKind.BAND)
    counting = settled >= params.h_min_settled

    flags = {}
    for n in living:
        count = 0
        if not counting:
            flags[n.id] = 0
            continue
        if cap_share.get(n.id, 0.0) >= params.h_share:
            count += 1
        if cons_share.get(n.id, 0.0) >= params.h_share:
            count += 1
        if prod_share.get(n.id, 0.0) >= params.h_share:
            count += 1
        flags[n.id] = count

    h = world.hegemony
    h.capital_share = cap_share
    h.consumption_share = cons_share
    h.production_share = prod_share
    h.flags = flags
    _update_countdown(h, flags, params)


def _update_countdown(h: HegemonyState, flags: dict[str, int], params: ScoreboardParams) -> None:
    """Set to `H_years` the first year `flags_n >= 2` holds for a nation, then
    decrements by 1 each further year it holds; reset to `H_years` (not cancelled)
    the moment `flags_n < 2` again."""

    if h.countdown_nation is not None and flags.get(h.countdown_nation, 0) >= 2:
        # first year it holds: set to H_years; each further year: decrement
        h.countdown = params.h_years if h.countdown is None else max(0, h.countdown - 1)
        if h.countdown == 0:
            h.game_over = True
        return

    if h.countdown_nation is not None:
        h.countdown = params.h_years  # reset, not cancelled — stays attached to this nation

    for nation_id in sorted(flags):
        if flags[nation_id] >= 2:
            h.countdown_nation = nation_id
            h.countdown = params.h_years
            return


def game_over(world: World) -> bool:
    return world.hegemony.game_over


def winners(world: World) -> tuple[str | None, str | None]:
    """`argmax` of `produce_per_head` and of `Σ productive V`, among living nations
    only — they may be different nations."""

    living = [n for n in world.nations.values() if not n.ended]
    if not living:
        return None, None
    per_head = max(living, key=lambda n: produce_per_head(n, world)).id
    labour_output = max(living, key=lambda n: productive_v(n, world)).id
    return per_head, labour_output


def step_hegemony(world: World) -> None:
    """Step 13d: world shares, the countdown, and the running winners."""

    world_shares(world)
    per_head, labour_output = winners(world)
    world.hegemony.winner_per_head = per_head
    world.hegemony.winner_labour_output = labour_output
