"""`python -m stock.sim run scenario.yaml [--years N] [--seed S] [--out ledger.json]
[--until-game-over]`; `summary` of a saved ledger (Doc 05); `gen --seed S [--locations N]
[--nations K] --out world.yaml` writes a procedurally generated scenario (`sim.worldgen`).
`run` also takes `random[:seed[:locations[:nations]]]` in place of a scenario path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stock.sim.ledger import Ledger
from stock.sim.rng import make_rng
from stock.sim.scenario import load_scenario
from stock.sim.year import run_year

#: A hard cap so `--until-game-over` can't hang forever on a fixture that never ends.
_MAX_YEARS_UNTIL_GAME_OVER = 5000


def _all_ended(world: object) -> bool:
    from stock.core.world import World

    assert isinstance(world, World)
    return all(n.ended for n in world.nations.values())


def _write_ledger(ledger: Ledger, out: str) -> None:
    path = Path(out)
    if path.suffix == ".csv":
        ledger.to_csv(path)
        return
    if path.suffix not in (".json", ".parquet"):
        print(f"note: unrecognised --out suffix {path.suffix!r}; writing JSON", file=sys.stderr)
    if path.suffix == ".parquet":
        print(
            "note: no parquet writer is available in this environment; writing JSON to "
            f"{path.with_suffix('.json')} instead",
            file=sys.stderr,
        )
        path = path.with_suffix(".json")
    ledger.to_json(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stock.sim")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a scenario")
    run_p.add_argument("scenario", help="a scenario YAML file, or random[:seed[:locations[:nations]]]")
    run_p.add_argument("--years", type=int, default=0, help="years to run (0: just load and summarise)")
    run_p.add_argument("--seed", type=int, default=None, help="override the scenario's seed")
    run_p.add_argument("--out", type=str, default=None, help="write the ledger to this path")
    run_p.add_argument(
        "--until-game-over",
        action="store_true",
        help="run until hegemony's game_over or every nation has ended",
    )
    run_p.add_argument(
        "--ai", choices=["all"], default=None, help="put a ScriptedSovereign in every seat (balance runs)"
    )

    summary_p = sub.add_parser("summary", help="summarise a saved ledger")
    summary_p.add_argument("ledger", help="path to a ledger JSON file")

    gen_p = sub.add_parser("gen", help="write a procedurally generated scenario")
    gen_p.add_argument("--seed", type=int, default=0, help="world seed (default 0)")
    gen_p.add_argument("--locations", type=int, default=24, help="locations on the map (default 24)")
    gen_p.add_argument("--nations", type=int, default=3, help="bands at the start (default 3)")
    gen_p.add_argument("--rivers", type=int, default=1, help="rivers to carve (default 1)")
    gen_p.add_argument(
        "--no-ai", action="store_true", help="leave every seat unscripted (default: all but the first are AI)"
    )
    gen_p.add_argument("--out", type=str, required=True, help="write the scenario YAML here")

    args = parser.parse_args(argv)

    if args.command == "gen":
        from stock.sim.worldgen import WorldGenConfig, write_scenario

        config = WorldGenConfig(
            seed=args.seed,
            locations=args.locations,
            nations=args.nations,
            rivers=args.rivers,
            other_ai=None if args.no_ai else "scripted",
        )
        out = write_scenario(config, args.out)
        world = load_scenario(out)
        print(f"wrote {out}")
        print(world.summary())
        return 0

    if args.command == "run":
        world = load_scenario(args.scenario)
        if args.seed is not None:
            world.rng = make_rng(args.seed)
        if args.ai == "all":
            for nation in world.nations.values():
                nation.ai = "scripted"
        if world.ledger is None:
            world.ledger = Ledger()

        if args.until_game_over:
            elapsed = 0
            while (
                elapsed < _MAX_YEARS_UNTIL_GAME_OVER
                and not world.hegemony.game_over
                and not _all_ended(world)
            ):
                run_year(world)
                elapsed += 1
        else:
            for _ in range(args.years):
                run_year(world)

        if args.out:
            _write_ledger(world.ledger, args.out)
        print(world.summary())
        return 0

    if args.command == "summary":
        import json

        data = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
        rows = data.get("rows", [])
        events = data.get("events", [])
        years = {r["year"] for r in rows}
        nations = {r["nation"] for r in rows}
        print(f"{len(rows)} rows, {len(events)} events, {len(years)} years, {len(nations)} nations")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
