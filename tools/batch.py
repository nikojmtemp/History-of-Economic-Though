"""Batch runner (Doc 08): many seeds of one scenario, headless.

    python -m tools.batch --scenario tests/scenarios/three_bands_ai.yaml --seeds 1..20 \\
        --years 1000 --ai all --out runs/

Writes one ledger JSON per run plus `summary.csv` (one row per run): years to
herds/field/manufactory, hegemony year and winners, regression count, which
nations ended, and each living nation's final curve values. Seeds run in parallel
with `multiprocessing`.
"""

from __future__ import annotations

import argparse
import copy
import csv
import multiprocessing
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from stock.core.params import Params, ParamsError
from stock.core.world import World
from stock.sim.rng import make_rng
from stock.sim.scenario import ScenarioError, load_scenario
from stock.sim.year import run_year
from tools.metrics import field_settled_year, herds_tamed_year, manufactory_year


@dataclass
class RunResult:
    scenario: str
    seed: int
    years_run: int
    ended_early: bool
    game_over: bool
    game_over_year: int | None
    winner_per_head: str | None
    winner_labour_output: str | None
    ended_nations: list[str]
    regressions_total: int
    per_nation: dict[str, dict[str, Any]] = field(default_factory=dict)
    ledger_path: str | None = None


def _parse_seeds(spec: str) -> list[int]:
    """`"1..20"` or `"1,2,7"` or a single `"3"`."""

    seeds: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if ".." in part:
            lo, hi = part.split("..", 1)
            seeds.extend(range(int(lo), int(hi) + 1))
        elif part:
            seeds.append(int(part))
    return seeds


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_world(
    scenario_path: str, seed: int, *, ai_mode: str = "none", params_override_path: str | None = None
) -> World:
    """Load `scenario_path`, then apply `--ai`/`--params` on top (Doc 08's own
    knobs; the scenario file itself is untouched)."""

    raw = yaml.safe_load(Path(scenario_path).read_text(encoding="utf-8")) or {}
    world = load_scenario(scenario_path)
    world.rng = make_rng(seed)

    if params_override_path is not None:
        extra = yaml.safe_load(Path(params_override_path).read_text(encoding="utf-8")) or {}
        merged = _deep_merge(raw.get("params_override", {}) or {}, extra)
        try:
            world.params = Params.from_dict(merged)
        except ParamsError as exc:
            raise ScenarioError(f"--params {params_override_path}: {exc}") from exc

    if ai_mode == "all":
        for nation in world.nations.values():
            nation.ai = "scripted"
    elif ai_mode == "none":
        for nation in world.nations.values():
            nation.ai = None
    # ai_mode == "scenario": leave the scenario file's own `ai:` fields as loaded.

    return world


def run_one(
    scenario_path: str,
    seed: int,
    years: int,
    *,
    ai_mode: str = "none",
    params_override_path: str | None = None,
    out_dir: str | None = None,
) -> RunResult:
    world = build_world(scenario_path, seed, ai_mode=ai_mode, params_override_path=params_override_path)

    years_run = 0
    for _ in range(years):
        if world.hegemony.game_over or all(n.ended for n in world.nations.values()):
            break
        run_year(world)
        years_run += 1

    ledger = world.ledger
    assert ledger is not None
    per_nation: dict[str, dict[str, Any]] = {}
    regressions_total = 0
    for nid, nation in world.nations.items():
        regressions = sum(1 for e in ledger.events if e.nation == nid and e.kind == "regression")
        regressions_total += regressions
        per_nation[nid] = {
            "ended": nation.ended,
            "seat": nation.seat.name,
            "herds_tamed_year": herds_tamed_year(ledger, nid),
            "field_settled_year": field_settled_year(ledger, nid),
            "manufactory_year": manufactory_year(ledger, nid),
            "regressions": regressions,
            "final_curves": dict(nation.curves),
        }

    game_over_year = None
    if world.hegemony.game_over:
        # the last year any row was written is when the loop stopped, i.e. game over
        game_over_year = world.year - 1

    ledger_path = None
    if out_dir is not None:
        stem = Path(scenario_path).stem
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        ledger_path = str(out / f"{stem}_seed{seed}.json")
        ledger.to_json(ledger_path)

    return RunResult(
        scenario=scenario_path,
        seed=seed,
        years_run=years_run,
        ended_early=years_run < years,
        game_over=world.hegemony.game_over,
        game_over_year=game_over_year,
        winner_per_head=world.hegemony.winner_per_head,
        winner_labour_output=world.hegemony.winner_labour_output,
        ended_nations=[nid for nid, n in world.nations.items() if n.ended],
        regressions_total=regressions_total,
        per_nation=per_nation,
        ledger_path=ledger_path,
    )


def _run_one_star(args: tuple[Any, ...]) -> RunResult:
    return run_one(*args[:3], ai_mode=args[3], params_override_path=args[4], out_dir=args[5])


def run_batch(
    scenario_path: str,
    seeds: list[int],
    years: int,
    *,
    ai_mode: str = "none",
    params_override_path: str | None = None,
    out_dir: str | None = None,
    processes: int | None = None,
) -> list[RunResult]:
    tasks = [(scenario_path, seed, years, ai_mode, params_override_path, out_dir) for seed in seeds]
    if len(tasks) == 1 or processes == 1:
        return [_run_one_star(t) for t in tasks]
    with multiprocessing.Pool(processes=processes) as pool:
        return pool.map(_run_one_star, tasks)


def write_summary_csv(results: list[RunResult], path: str) -> None:
    fieldnames = [
        "scenario",
        "seed",
        "years_run",
        "ended_early",
        "game_over",
        "game_over_year",
        "winner_per_head",
        "winner_labour_output",
        "ended_nations",
        "regressions_total",
        "nation",
        "seat",
        "herds_tamed_year",
        "field_settled_year",
        "manufactory_year",
        "regressions",
        "produce_per_head",
        "labour_share",
        "freedom_index",
        "N_bar",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            for nid, info in r.per_nation.items():
                curves = info["final_curves"]
                writer.writerow(
                    {
                        "scenario": r.scenario,
                        "seed": r.seed,
                        "years_run": r.years_run,
                        "ended_early": r.ended_early,
                        "game_over": r.game_over,
                        "game_over_year": r.game_over_year,
                        "winner_per_head": r.winner_per_head,
                        "winner_labour_output": r.winner_labour_output,
                        "ended_nations": "|".join(r.ended_nations),
                        "regressions_total": r.regressions_total,
                        "nation": nid,
                        "seat": info["seat"],
                        "herds_tamed_year": info["herds_tamed_year"],
                        "field_settled_year": info["field_settled_year"],
                        "manufactory_year": info["manufactory_year"],
                        "regressions": info["regressions"],
                        "produce_per_head": curves.get("produce_per_head"),
                        "labour_share": curves.get("labour_share"),
                        "freedom_index": curves.get("freedom_index"),
                        "N_bar": curves.get("N_bar"),
                    }
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--seeds", required=True, help='e.g. "1..20" or "1,2,7"')
    parser.add_argument("--years", type=int, required=True)
    parser.add_argument("--ai", choices=["none", "all", "scenario"], default="scenario")
    parser.add_argument("--params", default=None, help="YAML fragment merged onto the scenario overrides")
    parser.add_argument("--out", default="runs")
    parser.add_argument("--processes", type=int, default=None)
    args = parser.parse_args(argv)

    seeds = _parse_seeds(args.seeds)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    results = run_batch(
        args.scenario,
        seeds,
        args.years,
        ai_mode=args.ai,
        params_override_path=args.params,
        out_dir=args.out,
        processes=args.processes,
    )
    summary_path = str(Path(args.out) / "summary.csv")
    write_summary_csv(results, summary_path)
    print(f"{len(results)} run(s) -> {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
