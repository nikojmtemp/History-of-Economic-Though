"""Hostility between nations — increments from war/routes/treaties, decrements from trade/treaties/tribute
(DD §10; MM §16-17, last line)."""

from __future__ import annotations

from stock.core.world import World


def hostility(world: World, i: str, j: str) -> float:
    """Symmetric read of hostility between nations i and j. Returns 0 if absent or if i==j.
    Symmetric: hostility(world, i, j) == hostility(world, j, i)."""

    if i == j:
        return 0.0
    # Normalise to canonical form: min,max so we always store in one direction
    if i < j:
        canonical: tuple[str, str] = (i, j)
    else:
        canonical = (j, i)
    return world.hostility.get(canonical, 0.0)


def add_hostility(world: World, i: str, j: str, delta: float) -> None:
    """Add hostility between nations i and j. Writes both (i,j) and (j,i) with same value,
    clamped to [0, 1]."""

    if i == j:
        return
    # Normalise to canonical form
    if i < j:
        canonical: tuple[str, str] = (i, j)
    else:
        canonical = (j, i)
    current = world.hostility.get(canonical, 0.0)
    new_value = max(0.0, min(1.0, current + delta))
    world.hostility[canonical] = new_value


def hostility_update(world: World) -> None:
    """MM §16 last line: per-year decrements for every unordered pair of living nations.
    h ← h − Δtrade·(trade volume) − Δtreaty_kept·(kept treaties count) − Δtribute·(1 if tribute flows).

    Iterates unordered pairs to avoid double-decrementing. Clamps to [0, 1]."""

    params = world.params
    p = params.trade

    # Collect all living nation IDs
    living_nations = [nid for nid, n in world.nations.items() if not n.ended]

    # Iterate unordered pairs
    for i_idx, i in enumerate(living_nations):
        for j in living_nations[i_idx + 1 :]:
            # Compute total decrement
            decrement = 0.0

            # Trade volume decrement
            trade_vol = world.trade_volume.get((i, j), 0.0) + world.trade_volume.get((j, i), 0.0)
            decrement += p.h_trade_volume_rate * trade_vol

            # Kept treaties decrement
            kept_treaties = world.kept_treaties_count.get((i, j), 0.0)
            decrement += p.h_treaty_kept * kept_treaties

            # Tribute decrement (1 if flows either way)
            if (i, j) in world.tribute_pairs or (j, i) in world.tribute_pairs:
                decrement += p.h_tribute

            # Apply decrement
            if decrement > 0:
                current = hostility(world, i, j)
                new_value = max(0.0, current - decrement)
                if i < j:
                    canonical: tuple[str, str] = (i, j)
                else:
                    canonical = (j, i)
                world.hostility[canonical] = new_value
