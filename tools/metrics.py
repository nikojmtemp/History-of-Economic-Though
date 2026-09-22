"""Design-goal metrics (Doc 08 "Deliverables — Design-goal metrics").

Every function here reads a `Ledger` (or a list of them, one per seed) that
`tools.batch` already produced by calling the engine's own public API
(`sim.scenario.load_scenario` / `sim.year.run_year`) — nothing here runs a
simulation. `tools/batch.py` and `tools/sweep.py` are the callers; `tests/
test_scenarios.py` calls the same functions directly against a short in-test run
for the scenario tests that need one of these numbers rather than a hand-rolled
check.

Node-lit decoding follows `meta/trees.py`'s own documented encoding (its module
docstring): `tree` 1.0 = Tree I (per location), 2.0 = Tree II; `branch` 0.0/1.0/2.0
= production/defence/credit (Tree II only); `node` is the enum member's `.value`
within that tree/branch.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock.sim.ledger import Ledger

TREE_I = 1.0
TREE_II = 2.0
BRANCH_PRODUCTION = 0.0

NODE_DOMESTICATED_HERDS = 2.0  # TreeINode.DOMESTICATED_HERDS
NODE_GRAIN = 3.0  # TreeINode.GRAIN
NODE_MANUFACTORY = 9.0  # MethodId.MANUFACTORY, Tree II production branch


# ---------------------------------------------------------------------------
# Emergence
# ---------------------------------------------------------------------------


def node_lit_year(
    ledger: Ledger, nation: str, *, tree: float, node: float, branch: float | None = None
) -> int | None:
    """The first year `nation` lights the given Tree I/II node, or `None`."""

    for e in ledger.events:
        if e.nation != nation or e.kind != "node_lit":
            continue
        if e.numbers.get("tree") != tree or e.numbers.get("node") != node:
            continue
        if branch is not None and e.numbers.get("branch") != branch:
            continue
        return e.year
    return None


def herds_tamed_year(ledger: Ledger, nation: str) -> int | None:
    """Unreliable for a band's *automatic* taming: `engine/band.py`'s `tame_herd`
    sets `location.tree1.nodes[DOMESTICATED_HERDS].lit` directly rather than through
    `meta/trees.evaluate_gates`, so no `node_lit` event is emitted on that path and
    this returns `None` even when the herd was in fact tamed (confirmed empirically —
    see `build/DEVIATIONS-IN-PROGRESS.md`). Prefer checking `nation.seat`/`A_S` and a
    `HERD_OWNERS` record directly (as `tests/test_scenarios.py`'s herds-become-
    property test does) over this function for that case. `manufactory_year` below
    doesn't share this gap: Tree II nodes are only ever lit through `evaluate_gates`."""

    return node_lit_year(ledger, nation, tree=TREE_I, node=NODE_DOMESTICATED_HERDS)


def field_settled_year(ledger: Ledger, nation: str) -> int | None:
    return node_lit_year(ledger, nation, tree=TREE_I, node=NODE_GRAIN)


def manufactory_year(ledger: Ledger, nation: str) -> int | None:
    return node_lit_year(ledger, nation, tree=TREE_II, branch=BRANCH_PRODUCTION, node=NODE_MANUFACTORY)


def class_size_series(ledger: Ledger, nation: str, class_name: str) -> list[tuple[int, float]]:
    return [(r.year, r.class_sizes.get(class_name, 0.0)) for r in ledger.rows if r.nation == nation]


def dismissal_within(
    ledger: Ledger,
    nation: str,
    *,
    class_name: str = "RETAINERS",
    trigger_year: int,
    within_years: int,
    drop_ratio: float = 0.5,
) -> bool:
    """True if `class_name`'s size falls to `<= (1 - drop_ratio)` of its size at
    `trigger_year`, by `trigger_year + within_years`."""

    series = class_size_series(ledger, nation, class_name)
    at_trigger = next((size for year, size in series if year == trigger_year), None)
    if at_trigger is None or at_trigger <= 0:
        return False
    threshold = at_trigger * (1.0 - drop_ratio)
    deadline = trigger_year + within_years
    return any(trigger_year <= year <= deadline and size <= threshold for year, size in series)


def emergence_share(
    ledgers: Sequence[Ledger],
    nation: str,
    detector: Callable[[Ledger, str], int | bool | None],
    *,
    within_years: int | None = None,
) -> float:
    """Share of `ledgers` (one per seed) where `detector` finds the behaviour —
    `within_years` filters a year-returning detector; a bool-returning detector
    (e.g. `dismissal_within`) is used as-is."""

    if not ledgers:
        return 0.0
    hits = 0
    for ledger in ledgers:
        result = detector(ledger, nation)
        if isinstance(result, bool):
            hits += 1 if result else 0
        elif result is not None and (within_years is None or result <= within_years):
            hits += 1
    return hits / len(ledgers)


# ---------------------------------------------------------------------------
# Divergence of the curves
# ---------------------------------------------------------------------------


def curve_correlation(ledger: Ledger, nation: str, curve_a: str, curve_b: str) -> float | None:
    """Pearson correlation of two `nation.curves` series over the run, or `None`
    if there isn't enough variance to define one (a constant series, < 2 points)."""

    a = [r.curves.get(curve_a, 0.0) for r in ledger.rows if r.nation == nation]
    b = [r.curves.get(curve_b, 0.0) for r in ledger.rows if r.nation == nation]
    if len(a) < 2 or statistics.pvariance(a) == 0 or statistics.pvariance(b) == 0:
        return None
    return statistics.correlation(a, b)


# ---------------------------------------------------------------------------
# Regression frequency
# ---------------------------------------------------------------------------


@dataclass
class RegressionFrequency:
    per_100_years: float
    share_with_any: float


def regression_frequency(ledgers: Sequence[Ledger], nation: str, years_per_run: int) -> RegressionFrequency:
    if not ledgers or years_per_run <= 0:
        return RegressionFrequency(0.0, 0.0)
    counts = [
        sum(1 for e in ledger.events if e.nation == nation and e.kind == "regression") for ledger in ledgers
    ]
    total_regressions = sum(counts)
    total_years = years_per_run * len(ledgers)
    share_with_any = sum(1 for c in counts if c > 0) / len(ledgers)
    per_100 = total_regressions / total_years * 100
    return RegressionFrequency(per_100_years=per_100, share_with_any=share_with_any)


# ---------------------------------------------------------------------------
# Competitiveness
# ---------------------------------------------------------------------------


def world_share_dispersion(ledger: Ledger, year: int, *, share_kind: str = "capital") -> float | None:
    """Population stdev of `world_shares[share_kind]` across nations at `year`."""

    values = [r.world_shares.get(share_kind, 0.0) for r in ledger.rows if r.year == year]
    if len(values) < 2:
        return None
    return statistics.pstdev(values)


def winner_agreement_rate(winner_pairs: Sequence[tuple[str | None, str | None]]) -> float:
    """Share of runs where the per-head winner and the labour-output winner are the
    *same* nation (both present) — "agreement" as in one nation sweeping both."""

    decided = [(a, b) for a, b in winner_pairs if a is not None and b is not None]
    if not decided:
        return 0.0
    return sum(1 for a, b in decided if a == b) / len(decided)


def hegemony_share_by_year(game_over_years: Sequence[int | None], year: int) -> float:
    if not game_over_years:
        return 0.0
    return sum(1 for y in game_over_years if y is not None and y <= year) / len(game_over_years)


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------

#: Doc 08 names "law self-enacted, siege, breach, regression warning". No event
#: kind literally named "siege" is ever emitted (`security/war.py` emits
#: `war_declared`/`location_lost`/`location_taken` around a siege, never a
#: `"siege"` kind of its own — see `build/DEVIATIONS-IN-PROGRESS.md`); `war_declared`
#: substitutes as the nearest emitted proxy for "a siege-class event happened".
PACING_EVENT_KINDS: frozenset[str] = frozenset({"law_self_enacted", "war_declared", "breach"})


def _regression_warning_onsets(ledger: Ledger, nation: str) -> list[int]:
    """Years `regression_warning` turns on (a rising edge), from `NationScalars.
    regression_warning` via `LedgerRow.scalars` — not an emitted event."""

    onsets = []
    prev = False
    for r in sorted((r for r in ledger.rows if r.nation == nation), key=lambda r: r.year):
        on = r.scalars.get("regression_warning", 0.0) > 0.5
        if on and not prev:
            onsets.append(r.year)
        prev = on
    return onsets


def pacing_mean_years_between(ledger: Ledger, nation: str) -> float | None:
    years = sorted(
        {e.year for e in ledger.events if e.nation == nation and e.kind in PACING_EVENT_KINDS}
        | set(_regression_warning_onsets(ledger, nation))
    )
    if len(years) < 2:
        return None
    gaps = [b - a for a, b in zip(years, years[1:], strict=False)]
    return statistics.mean(gaps)


# ---------------------------------------------------------------------------
# Stability (price oscillation) — needs a live price trace, not the ledger
# (`LedgerRow` carries no per-location market prices; see
# `build/DEVIATIONS-IN-PROGRESS.md`). `tools/batch.py`'s `--trace-prices` mode
# supplies the series this function checks.
# ---------------------------------------------------------------------------


def has_period2_oscillation(series: Sequence[float], *, min_years: int, rel_amplitude: float = 0.05) -> bool:
    """True if `series` alternates up/down (period-2) for at least `min_years`
    consecutive steps with a relative amplitude above `rel_amplitude` (a genuine
    cobweb, not float noise around a converged price)."""

    if len(series) < min_years + 1:
        return False
    run = 0
    best = 0
    for i in range(1, len(series)):
        prev, cur = series[i - 1], series[i]
        mid = (prev + cur) / 2 or 1e-9
        amplitude = abs(cur - prev) / abs(mid)
        alternating = i < 2 or (cur - prev) * (series[i - 1] - series[i - 2]) < 0
        if alternating and amplitude >= rel_amplitude:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best >= min_years
