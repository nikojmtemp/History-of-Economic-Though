"""Shared test harness: a year runner and a long-run invariant check.

`run_year` now just delegates to `stock.sim.year.run_year`, the real, complete
14-step loop (Doc 05, task S1-D05-T6). Kept here (rather than importing
`stock.sim.year.run_year` directly in every test) so existing test files that import
`run_year` from this module don't need touching.
"""

from __future__ import annotations

import math

from stock.core.world import World
from stock.sim.year import run_year as run_year

__all__ = ["assert_invariants", "run_year"]


def assert_invariants(world: World, *, r_bar_bound: float = 10.0) -> None:
    """No NaN, no negative wealth/size/price, `r_bar` bounded. Doc 02's own
    acceptance bar ("no NaN; value conservation holds") plus the advisor's
    recommendation to check this doesn't silently drift into nonsense as later docs
    add steps."""

    for location in world.locations.values():
        for record in location.records:
            for field_name, value in record.wealth.as_dict().items():
                assert math.isfinite(value), f"{location.id}/{record.cls}: wealth.{field_name}={value}"
                assert value >= -1e-6, f"{location.id}/{record.cls}: wealth.{field_name}={value} < 0"
            assert math.isfinite(record.size), f"{location.id}/{record.cls}: size={record.size}"
            assert record.size >= -1e-6, f"{location.id}/{record.cls}: size={record.size} < 0"
        for good, price in location.market.price.items():
            assert math.isfinite(price) and price >= 0, f"{location.id}: price[{good}]={price}"

    for nation_id, nation in world.nations.items():
        r_bar = nation.scalars.r_bar
        assert math.isfinite(r_bar), f"{nation_id}: r_bar={r_bar}"
        assert -r_bar_bound <= r_bar <= r_bar_bound, f"{nation_id}: r_bar={r_bar} out of bound"
