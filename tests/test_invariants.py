"""Doc 08 invariants tests: value conservation, determinism, lag rule, etc.

Runs the three_bands.yaml scenario for 400 years and validates invariants on the ledger.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from stock.sim.scenario import load_scenario
from tests._harness import run_year

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO = REPO_ROOT / "tests" / "scenarios" / "three_bands.yaml"


@pytest.fixture(scope="module")
def ledger_400_years_and_observations() -> tuple[Any, dict[str, list[str]]]:
    """Run three_bands.yaml for 400 years, collecting invariant observations.

    Returns (ledger, observations) where observations is a dict mapping invariant names
    to lists of violation messages (empty lists mean all checks passed).
    """
    from stock.core.goods import Good
    from stock.core.records import ClassId
    from stock.engine.consumption import RETAINER_BUYING_CLASSES, SERVANT_BUYING_CLASSES

    world = load_scenario(SCENARIO)
    observations: dict[str, list[str]] = {
        "price_violations": [],
        "share_violations": [],
        "derived_size_violations": [],
        "validate_errors": [],
    }

    for year in range(400):
        run_year(world)

        # Invariant 4: prices finite and > 0
        for location in world.locations.values():
            for good in Good:
                price = location.market.price.get(good, 1.0)
                if not math.isfinite(price) or price <= 0:
                    if len(observations["price_violations"]) < 5:
                        observations["price_violations"].append(
                            f"Year {year} {location.id}: price[{good.name}]={price}, "
                            f"expected finite and > 0"
                        )

        # Invariant 4: ownership shares in [0,1], sum to 1 where non-empty (with tolerance for FP error)
        for location in world.locations.values():
            for producer in location.producers:
                for cls_id, share in producer.owners_stock.items():
                    if not (-1e-6 <= share <= 1 + 1e-6):  # Allow small FP tolerance
                        if len(observations["share_violations"]) < 5:
                            observations["share_violations"].append(
                                f"Year {year} {location.id}: producer {producer.kind.name} "
                                f"owners_stock[{cls_id.name}]={share}, expected [0,1]"
                            )
                total_stock = sum(producer.owners_stock.values())
                if producer.owners_stock and abs(total_stock - 1.0) > 1e-5:  # Relax tolerance for sums
                    if len(observations["share_violations"]) < 5:
                        observations["share_violations"].append(
                            f"Year {year} {location.id}: producer {producer.kind.name} "
                            f"owners_stock sum={total_stock}, expected 1.0"
                        )
                for cls_id, share in producer.owners_land.items():
                    if not (-1e-6 <= share <= 1 + 1e-6):  # Allow small FP tolerance
                        if len(observations["share_violations"]) < 5:
                            observations["share_violations"].append(
                                f"Year {year} {location.id}: producer {producer.kind.name} "
                                f"owners_land[{cls_id.name}]={share}, expected [0,1]"
                            )
                total_land = sum(producer.owners_land.values())
                if producer.owners_land and abs(total_land - 1.0) > 1e-5:  # Relax tolerance for sums
                    if len(observations["share_violations"]) < 5:
                        observations["share_violations"].append(
                            f"Year {year} {location.id}: producer {producer.kind.name} "
                            f"owners_land sum={total_land}, expected 1.0"
                        )

        # Invariant 6: derived sizes match Attendance purchases
        for location in world.locations.values():
            # Retainers: sum of last_spend_by_good[ATTENDANCE] from RETAINER_BUYING_CLASSES
            retainer_spend = sum(
                r.last_spend_by_good.get(Good.ATTENDANCE, 0.0)
                for r in location.records
                if r.cls in RETAINER_BUYING_CLASSES
            )
            retainers = location.record(ClassId.RETAINERS)
            retainer_size = retainers.size if retainers is not None else 0.0
            # A purchase that would keep less than one person keeps nobody
            # (`PopulationParams.extinct_size_epsilon`; engine.consumption).
            min_size = world.params.population.extinct_size_epsilon
            if retainer_spend < min_size:
                retainer_spend = 0.0
            if abs(retainer_size - retainer_spend) > 1e-6:
                if len(observations["derived_size_violations"]) < 5:
                    observations["derived_size_violations"].append(
                        f"Year {year} {location.id}: RETAINERS size={retainer_size}, "
                        f"Attendance spend={retainer_spend}, mismatch"
                    )

            # Servants: sum of last_spend_by_good[ATTENDANCE] from SERVANT_BUYING_CLASSES
            servant_spend = sum(
                r.last_spend_by_good.get(Good.ATTENDANCE, 0.0)
                for r in location.records
                if r.cls in SERVANT_BUYING_CLASSES
            )
            servants = location.record(ClassId.SERVANTS)
            servant_size = servants.size if servants is not None else 0.0
            if servant_spend < min_size:
                servant_spend = 0.0
            if abs(servant_size - servant_spend) > 1e-6:
                if len(observations["derived_size_violations"]) < 5:
                    observations["derived_size_violations"].append(
                        f"Year {year} {location.id}: SERVANTS size={servant_size}, "
                        f"Attendance spend={servant_spend}, mismatch"
                    )

        # Invariant 5: World.validate() every 50 years (includes hostility symmetry)
        if year % 50 == 0:
            try:
                world.validate()
            except Exception as e:
                if len(observations["validate_errors"]) < 5:
                    observations["validate_errors"].append(
                        f"Year {year}: {type(e).__name__}: {str(e)}"
                    )

    return world.ledger, observations


# --- Invariant checks: per nation per year from ledger rows ---


def test_value_conservation(ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]]) -> None:
    """MM §5: labour_income + profit + rent == V."""
    ledger_400_years, _ = ledger_400_years_and_observations
    tolerance = 1e-6
    for row in ledger_400_years.rows:
        labour = row.flows.get("labour_income", 0.0)
        profit = row.flows.get("profit", 0.0)
        rent = row.flows.get("rent", 0.0)
        v = row.flows.get("V", 0.0)
        total = labour + profit + rent
        if v > 0:
            rel_error = abs(total - v) / abs(v)
            assert rel_error <= tolerance, (
                f"Value conservation failed at {row.nation} year {row.year}: "
                f"labour_income({labour:.2f}) + profit({profit:.2f}) + rent({rent:.2f}) "
                f"= {total:.2f}, expected V={v:.2f}, rel_error={rel_error:.2e}"
            )


def test_income_conservation(ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]]) -> None:
    """gross_income == consumption + saved."""
    ledger_400_years, _ = ledger_400_years_and_observations
    tolerance = 1e-6
    for row in ledger_400_years.rows:
        gross_income = row.flows.get("gross_income", 0.0)
        consumption = row.flows.get("consumption", 0.0)
        saved = row.flows.get("saved", 0.0)
        total = consumption + saved
        if gross_income > 0:
            rel_error = abs(total - gross_income) / abs(gross_income)
            assert rel_error <= tolerance, (
                f"Income conservation failed at {row.nation} year {row.year}: "
                f"consumption({consumption:.2f}) + saved({saved:.2f}) "
                f"= {total:.2f}, expected gross_income={gross_income:.2f}, "
                f"rel_error={rel_error:.2e}"
            )


def test_hoard_conservation(ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]]) -> None:
    """to_hoard + to_reinvest == saved."""
    ledger_400_years, _ = ledger_400_years_and_observations
    tolerance = 1e-6
    for row in ledger_400_years.rows:
        to_hoard = row.flows.get("to_hoard", 0.0)
        to_reinvest = row.flows.get("to_reinvest", 0.0)
        saved = row.flows.get("saved", 0.0)
        total = to_hoard + to_reinvest
        if saved > 0:
            rel_error = abs(total - saved) / abs(saved)
            assert rel_error <= tolerance, (
                f"Hoard conservation failed at {row.nation} year {row.year}: "
                f"to_hoard({to_hoard:.2f}) + to_reinvest({to_reinvest:.2f}) "
                f"= {total:.2f}, expected saved={saved:.2f}, rel_error={rel_error:.2e}"
            )


def test_ledger_rows_written_every_year(
    ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]],
) -> None:
    """Ledger rows count matches 400 years × number of nations."""
    ledger_400_years, _ = ledger_400_years_and_observations
    rows = ledger_400_years.rows
    # Extract unique nation ids
    nations = set(r.nation for r in rows)
    expected_count = len(nations) * 400
    assert len(rows) == expected_count, (
        f"Ledger rows: {len(rows)}, expected {expected_count} "
        f"({len(nations)} nations × 400 years)"
    )


def test_no_nan_values(ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]]) -> None:
    """No NaN in any row value."""
    ledger_400_years, _ = ledger_400_years_and_observations
    for row in ledger_400_years.rows:
        for key, value in row.flatten().items():
            if isinstance(value, float):
                assert math.isfinite(value), (
                    f"NaN/Inf found at {row.nation} year {row.year}, field {key}: {value}"
                )


def test_no_negative_wealth_or_size(
    ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]],
) -> None:
    """No negative wealth or size on any record."""
    ledger_400_years, _ = ledger_400_years_and_observations
    for row in ledger_400_years.rows:
        # Check class sizes
        for cls_name, size in row.class_sizes.items():
            assert size >= -1e-6, (
                f"Negative size at {row.nation} year {row.year}, class {cls_name}: {size}"
            )
        # Check class wealth
        for cls_name, wealth in row.class_wealth.items():
            assert wealth >= -1e-6, (
                f"Negative wealth at {row.nation} year {row.year}, class {cls_name}: {wealth}"
            )


def test_prices_finite_positive(
    ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]],
) -> None:
    """Every price is finite and > 0; checked live during the 400-year run."""
    _, observations = ledger_400_years_and_observations
    price_violations = observations["price_violations"]
    assert not price_violations, (
        "Price violations found:\n" + "\n".join(price_violations[:5])
    )


def test_ownership_shares_valid(
    ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]],
) -> None:
    """Ownership shares in [0,1], sum to 1 where non-empty."""
    _, observations = ledger_400_years_and_observations
    share_violations = observations["share_violations"]
    assert not share_violations, (
        "Share violations found:\n" + "\n".join(share_violations[:5])
    )


def test_world_validate_passes(
    ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]],
) -> None:
    """World.validate() passes every 50 years (includes hostility symmetry)."""
    _, observations = ledger_400_years_and_observations
    validate_errors = observations["validate_errors"]
    assert not validate_errors, (
        "World.validate() errors found:\n" + "\n".join(validate_errors[:5])
    )


def test_derived_sizes_match_attendance(
    ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]],
) -> None:
    """RETAINERS/SERVANTS size == Σ last_spend_by_good[ATTENDANCE] of buyer classes."""
    _, observations = ledger_400_years_and_observations
    derived_violations = observations["derived_size_violations"]
    assert not derived_violations, (
        "Derived size violations found:\n" + "\n".join(derived_violations[:5])
    )


def test_enforcement_in_valid_range(
    ledger_400_years_and_observations: tuple[Any, dict[str, list[str]]],
) -> None:
    """Enforcement of every enacted law in (0,1) (strictly)."""
    ledger_400_years, _ = ledger_400_years_and_observations
    for row in ledger_400_years.rows:
        for law_name, law_state in row.law_states.items():
            if law_state.get("enacted", 0.0) > 0.5:  # enacted
                enforcement = law_state.get("enforcement", 0.0)
                assert 0 < enforcement < 1, (
                    f"Invalid enforcement at {row.nation} year {row.year}, law {law_name}: "
                    f"enforcement={enforcement}, must be in (0, 1)"
                )


def test_determinism_200_years() -> None:
    """Two fresh runs with the same scenario produce identical Ledger.hash()."""
    hash1 = _run_and_hash(200)
    hash2 = _run_and_hash(200)
    assert hash1 == hash2, (
        f"Determinism check failed: two runs produced different hashes. "
        f"hash1={hash1}, hash2={hash2}"
    )


# --- Lag-rule static check ---


def test_lag_rule_static_check() -> None:
    """Assert no forbidden attribute reads in step functions (lag rule validation).

    Forbidden reads = substrings that must not appear in source except in assignment targets
    (left-hand side of = or +=). Uses simple heuristic: exclude lines starting with the pattern.
    """

    FORBIDDEN_READS: dict[str, list[str]] = {
        "stock/engine/production.py": [
            "nation.scalars.r_bar",
            "location.market.price",
            "market.price[",
        ],
        "stock/engine/capital.py": [
            "world._f_n_by_record",
        ],
        "stock/engine/wages.py": [
            # Check if step_wages reads nation.scalars.r_bar; if only via prev, remove this entry
        ],
    }

    for module_path, patterns in FORBIDDEN_READS.items():
        full_path = REPO_ROOT / module_path
        if not full_path.exists():
            continue
        source = full_path.read_text(encoding="utf-8")

        # Find the step_* function
        for node in (line for line in source.split("\n")):
            if node.strip().startswith("def step_"):
                func_name = node.split("(")[0].replace("def ", "")
                # Extract function body (simple approach: lines until next def)
                lines = source.split("\n")
                start_idx = None
                end_idx = None
                for i, line in enumerate(lines):
                    if f"def {func_name}" in line:
                        start_idx = i
                    elif (
                        start_idx is not None
                        and line.strip()
                        and not line.startswith(" ")
                        and line.startswith("def")
                    ):
                        end_idx = i
                        break

                if start_idx is not None:
                    end_idx = end_idx or len(lines)
                    func_source = "\n".join(lines[start_idx:end_idx])

                    for pattern in patterns:
                        if not pattern:  # Skip empty patterns
                            continue
                        # Find lines containing the pattern that are NOT assignment targets
                        for line in func_source.split("\n"):
                            stripped = line.strip()
                            if pattern in line:
                                # Skip if assignment target (pattern on left of =)
                                if f"{pattern} =" in line or f"{pattern} +=" in line:
                                    continue
                                # Found a forbidden read
                                raise AssertionError(
                                    f"Lag rule violation in {module_path}::{func_name}: "
                                    f"forbidden read '{pattern}' in: {stripped}"
                                )
                break


# --- f(N) in the open unit interval (MM §14's investment sigmoid) ---


def test_f_n_strictly_in_open_unit_interval() -> None:
    """`world._f_n_by_record` (written by `security.military.perceived_security`,
    read lagged by `engine.capital.hoard_update`) stays strictly in `(0, 1)` for
    every record, every year — checked live during the run since it's transient
    per-year state, not part of the ledger."""

    world = load_scenario(SCENARIO)
    for _year in range(200):
        run_year(world)
        for key, f_n in world._f_n_by_record.items():
            assert 0.0 < f_n < 1.0, f"f(N) out of (0,1) for {key}: {f_n}"


# --- Bonds bought == bonds issued (world) ---


def test_bonds_bought_equals_bonds_issued() -> None:
    """`finance.credit.issue_bonds` distributes exactly `issued` baskets across
    lenders' `wealth.bonds` (`lent = amount * (issued / total_offered)`, summed back
    to `issued` by construction) — pinned directly against the function rather than
    against a full year's ledger, since other steps (mobility, extinction, service,
    default) also touch `wealth.bonds` in the same year and would make a ledger-level
    before/after comparison test the net of several mechanisms, not just issuance."""

    from stock.core.laws import LawId
    from stock.core.params import Params
    from stock.core.records import ClassId, Record, Wealth
    from stock.core.world import (
        HegemonyState,
        LawState,
        Location,
        Market,
        Nation,
        NationScalars,
        PrevSnapshot,
        Terrain,
        World,
    )
    from stock.finance.credit import issue_bonds

    lenders = [
        Record(cls=ClassId.MERCHANTS, location="loc1", size=10.0, wealth=Wealth(hoard=100.0)),
        Record(cls=ClassId.CAPITALISTS, location="loc1", size=5.0, wealth=Wealth(hoard=50.0)),
        Record(cls=ClassId.LANDLORDS, location="loc1", size=5.0, wealth=Wealth(hoard=20.0)),
    ]
    loc = Location(id="loc1", terrain=Terrain.PLAINS, nation="n1", market=Market(), records=list(lenders))
    nation = Nation(id="n1", scalars=NationScalars(r_bar=0.05, spending_extra=50.0), funding_mode="BONDS")
    nation.laws[LawId.PUBLIC_CREDIT] = LawState(enacted=True)

    world = World(
        year=0,
        nations={"n1": nation},
        locations={"loc1": loc},
        hostility={},
        hegemony=HegemonyState(),
        prev=PrevSnapshot(),
        ledger=None,
        rng=None,
        params=Params.default(),
    )

    issued = issue_bonds(nation, world, r_sovereign=0.08, params=world.params.credit)

    assert issued > 0, "fixture should have produced a positive issuance"
    total_bonds_bought = sum(r.wealth.bonds for r in lenders)
    assert total_bonds_bought == pytest.approx(issued, rel=1e-9)
    assert issued <= 50.0 + 1e-9  # never exceeds `needed`


# --- Helpers ---


def _run_and_hash(years: int) -> str:
    """Run a fresh scenario for N years and return the ledger hash."""
    world = load_scenario(SCENARIO)
    for _ in range(years):
        run_year(world)
    hash_val = world.ledger.hash()
    return str(hash_val)


# --- Markers for xfail tests (if any engine invariants are violated) ---
# If an invariant fails, mark it with @pytest.mark.xfail(strict=True, reason="...") here.
# The test stays in place for the orchestrator to track as a real finding.
