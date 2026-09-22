"""Parameter sweeps (Doc 08): a grid (or Latin-hypercube) over named `Params` fields,
each point run through `tools.batch`, summarized into a table of design-goal metrics
vs. parameters plus a short `report.md`.

    python -m tools.sweep --scenario tests/scenarios/three_bands_ai.yaml --seeds 1..8 \\
        --years 400 --ai all --grid politics.enforcement_floor_enf_min=0.03,0.06,0.1 \\
        --grid politics.k_lapse=3,5,8 --out sweeps/enf_floor/

Named fields use the same dotted `section.field` path as `core/params.SYMBOL_MAP`'s
values (e.g. `politics.k_lapse`, not the MM symbol `k_lapse` — this tool takes the
field path directly so it isn't limited to symbols that happen to have one).
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
from pathlib import Path
from typing import Any

import yaml

from tools.batch import RunResult, _parse_seeds, run_batch, write_summary_csv
from tools.metrics import (
    emergence_share,
    field_settled_year,
    herds_tamed_year,
    manufactory_year,
    regression_frequency,
)


def _parse_grid_arg(spec: str) -> tuple[str, list[float]]:
    """`"politics.k_lapse=3,5,8"` -> `("politics.k_lapse", [3.0, 5.0, 8.0])`."""

    path, _, values = spec.partition("=")
    parsed = [float(v) if "." in v or "e" in v.lower() else int(v) for v in values.split(",")]
    return path.strip(), parsed


def _set_path(d: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    """Nest `value` at dotted `path` inside a fresh copy of `d`."""

    out = dict(d)
    parts = path.split(".")
    cursor = out
    for part in parts[:-1]:
        cursor[part] = dict(cursor.get(part, {}))
        cursor = cursor[part]
    cursor[parts[-1]] = value
    return out


def grid_points(grids: list[tuple[str, list[float]]]) -> list[dict[str, Any]]:
    """The full Cartesian product of every named field's candidate values, each as
    a params-override fragment ready for `Params.from_dict`."""

    paths = [g[0] for g in grids]
    value_lists = [g[1] for g in grids]
    points = []
    for combo in itertools.product(*value_lists):
        override: dict[str, Any] = {}
        for path, value in zip(paths, combo, strict=True):
            override = _set_path(override, path, value)
        points.append(override)
    return points


def latin_hypercube_points(
    grids: list[tuple[str, tuple[float, float]]], n_samples: int, seed: int = 0
) -> list[dict[str, Any]]:
    """One Latin-hypercube sample per point, `n_samples` points, over `(low, high)`
    ranges (unlike `grid_points`'s discrete candidate lists)."""

    rng = random.Random(seed)
    paths = [g[0] for g in grids]
    ranges = [g[1] for g in grids]
    columns: list[list[float]] = []
    for low, high in ranges:
        edges = [low + (high - low) * i / n_samples for i in range(n_samples + 1)]
        cell_samples = [rng.uniform(edges[i], edges[i + 1]) for i in range(n_samples)]
        rng.shuffle(cell_samples)
        columns.append(cell_samples)
    points = []
    for row in range(n_samples):
        override: dict[str, Any] = {}
        for path, column in zip(paths, columns, strict=True):
            override = _set_path(override, path, column[row])
        points.append(override)
    return points


def run_sweep(
    scenario_path: str,
    points: list[dict[str, Any]],
    seeds: list[int],
    years: int,
    *,
    ai_mode: str,
    out_dir: str,
    processes: int | None = None,
) -> list[dict[str, Any]]:
    """Runs `tools.batch.run_batch` once per point; returns one summary dict per
    point with the design-goal metrics averaged across seeds."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for i, override in enumerate(points):
        point_dir = out / f"point_{i:03d}"
        point_dir.mkdir(exist_ok=True)
        override_path = point_dir / "params_override.yaml"
        override_path.write_text(yaml.safe_dump(override), encoding="utf-8")

        results: list[RunResult] = run_batch(
            scenario_path,
            seeds,
            years,
            ai_mode=ai_mode,
            params_override_path=str(override_path),
            out_dir=str(point_dir),
            processes=processes,
        )
        write_summary_csv(results, str(point_dir / "summary.csv"))

        ledgers = []
        for r in results:
            assert r.ledger_path is not None
            from stock.sim.ledger import Ledger

            ledgers.append(Ledger.load_json(r.ledger_path))

        nations = sorted({nid for r in results for nid in r.per_nation})
        row: dict[str, Any] = {"point": i, "override": override}
        for nation in nations:
            herds = emergence_share(ledgers, nation, herds_tamed_year)
            fields = emergence_share(ledgers, nation, field_settled_year)
            manu = emergence_share(ledgers, nation, manufactory_year)
            regress = regression_frequency(ledgers, nation, years)
            row[f"{nation}.herds_share"] = herds
            row[f"{nation}.fields_share"] = fields
            row[f"{nation}.manufactory_share"] = manu
            row[f"{nation}.regressions_per_100y"] = regress.per_100_years
        row["hegemony_share"] = sum(1 for r in results if r.game_over) / len(results)
        rows.append(row)

    return rows


def write_report(rows: list[dict[str, Any]], path: str) -> None:
    lines = ["# Parameter sweep report", ""]
    if not rows:
        lines.append("No points swept.")
    else:
        metric_keys = [k for k in rows[0] if k not in ("point", "override")]
        lines.append("| point | override | " + " | ".join(metric_keys) + " |")
        lines.append("|---|---|" + "---|" * len(metric_keys))
        for row in rows:
            override_str = json.dumps(row["override"])
            cells = (f"{row[k]:.3f}" if isinstance(row[k], float) else str(row[k]) for k in metric_keys)
            values = " | ".join(cells)
            lines.append(f"| {row['point']} | `{override_str}` | {values} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--years", type=int, required=True)
    parser.add_argument("--ai", choices=["none", "all", "scenario"], default="scenario")
    parser.add_argument("--grid", action="append", default=[], help='"section.field=v1,v2,v3", repeatable')
    parser.add_argument("--out", required=True)
    parser.add_argument("--processes", type=int, default=None)
    args = parser.parse_args(argv)

    grids = [_parse_grid_arg(g) for g in args.grid]
    points = grid_points(grids) if grids else [{}]
    seeds = _parse_seeds(args.seeds)

    rows = run_sweep(
        args.scenario, points, seeds, args.years, ai_mode=args.ai, out_dir=args.out, processes=args.processes
    )
    report_path = str(Path(args.out) / "report.md")
    write_report(rows, report_path)
    print(f"{len(rows)} point(s) -> {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
