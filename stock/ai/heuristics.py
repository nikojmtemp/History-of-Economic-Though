"""Small estimators scripts lean on (Doc 06): best neighbour, raid/war odds, treaty
value. Each is a thin read over `NationView`'s public numbers — no access to
another nation's private state.
"""

from __future__ import annotations

from stock.ai.view import NationView


def best_raid_target(view: NationView) -> str | None:
    """The rival with the highest hostility-adjusted weakness: lowest `M` among
    those we're not already at peace-committed to avoid, among rivals we aren't
    already at war with."""

    candidates = [o for o in view.others.values() if not o.ended and not o.at_war]
    if not candidates:
        return None
    weakest = min(candidates, key=lambda o: o.m)
    our_m = view.scalars.get("M", 0.0)
    if our_m <= 0 or weakest.m / our_m > 0.8:
        return None
    return weakest.id


def strongest_rival(view: NationView) -> str | None:
    candidates = [o for o in view.others.values() if not o.ended]
    if not candidates:
        return None
    return max(candidates, key=lambda o: o.m).id


def war_odds(view: NationView, target_id: str) -> float:
    """A simple `M_us / (M_us + M_them)` win-odds estimate (public numbers only)."""

    other = view.others.get(target_id)
    if other is None:
        return 0.0
    our_m = view.scalars.get("M", 0.0)
    total = our_m + other.m
    if total <= 0:
        return 0.5
    return our_m / total


def conquest_allowed(view: NationView, target_id: str) -> bool:
    """Smallest reading: our strength is meaningfully ahead of theirs (the doc names
    a `conquest_allowed`-style odds check; the precise Doc 04 predicate needs a
    `World`, which `decide()` doesn't have — see this module's docstring)."""

    return war_odds(view, target_id) > 0.6


def treaty_value(view: NationView, target_id: str) -> float:
    """Estimated value of a treaty with `target_id`: how much it would lower our
    external threat (`PTV_ext`, proxied by their hostility toward us) against how
    much market access it costs us (proxied by their production share, a rough
    stand-in for how much we'd forgo by conceding route terms)."""

    other = view.others.get(target_id)
    if other is None:
        return 0.0
    threat_relief = other.hostility
    market_cost = other.production_share * 0.5
    return threat_relief - market_cost


def dominant_border_good_price(view: NationView) -> tuple[str, float] | None:
    """The highest-priced good visible across any of our routes' far endpoints —
    used by the commercial script's charter-worthiness check."""

    best: tuple[str, float] | None = None
    for goods in view.route_prices.values():
        for good, price in goods.items():
            if best is None or price > best[1]:
                best = (good, price)
    return best
