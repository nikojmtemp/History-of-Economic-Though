"""Balance sweep (design doc §20): AI-only games over many seeds, measured against the
balance targets. Prints one line per target with the measured value and PASS/MISS.

    python -m tools.sweep --seeds 20
"""

from __future__ import annotations

import argparse
import statistics
import time

from stock.game import rules, turn
from stock.game.worldgen import generate


def run(seed: int) -> dict[str, object]:
    w = generate(seed=seed)
    for n in w.nations.values():
        n.player = False
    first_left, all_left, manufactory = None, None, None
    for t in range(1, rules.LAST_TURN + 1):
        turn.end_turn(w)
        left = [n.mode != "hunting" for n in w.nations.values() if n.alive]
        if first_left is None and any(left):
            first_left = t
        if all_left is None and all(left):
            all_left = t
        if manufactory is None and any("manufactory" in nd.works for nd in w.nodes.values()):
            manufactory = t
    wars = sum(1 for e in w.log if e.kind == "war" and e.text.startswith("We declare"))
    agri = min((n.counters.get("mode_agriculture_turn", 999.0) for n in w.nations.values()), default=999.0)
    comm = [n.counters.get("mode_commerce_turn") for n in w.nations.values()]
    return {
        "first_left": first_left,
        "all_left": all_left,
        "agriculture": agri,
        "commerce": min((c for c in comm if c), default=None),
        "manufactory": manufactory,
        "winner": (w.winner or {}).get("kind"),
        "wars": wars,
        "routes_end": len(w.routes),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--start", type=int, default=1)
    args = ap.parse_args()
    t0 = time.time()
    rows = [run(s) for s in range(args.start, args.start + args.seeds)]
    n = len(rows)

    def share(pred: object) -> float:
        return sum(1 for r in rows if pred(r)) / n  # type: ignore[operator]

    targets = [
        (
            "first people leaves Hunting, turns 12-25",
            share(lambda r: r["first_left"] and 12 <= r["first_left"] <= 25),
            0.8,
        ),
        ("all peoples leave Hunting by turn 45", share(lambda r: r["all_left"] and r["all_left"] <= 45), 0.9),
        ("someone farms by turn 90", share(lambda r: r["agriculture"] <= 90), 0.9),
        ("a manufactory by turn 180", share(lambda r: r["manufactory"] and r["manufactory"] <= 180), 0.9),
        ("at least 1 war per 25 turns (10 a game)", share(lambda r: r["wars"] >= 10), 0.5),
    ]
    hegemony = share(lambda r: r["winner"] == "hegemony")
    print(f"{n} seeds in {time.time() - t0:.1f}s")
    for name, got, want in targets:
        print(f"{'PASS' if got >= want else 'MISS'}  {name}: {got:.0%} (target {want:.0%})")
    ok = 0.3 <= hegemony <= 0.6
    print(f"{'PASS' if ok else 'MISS'}  hegemony in 30-60% of games: {hegemony:.0%}")
    firsts = [r["first_left"] for r in rows if r["first_left"]]
    if firsts:
        print(f"median first leave: turn {statistics.median(firsts)}")  # type: ignore[type-var]
    print(f"wars per game: median {statistics.median(r['wars'] for r in rows)}")  # type: ignore[type-var]
    comms = [r["commerce"] for r in rows if r["commerce"]]
    print(
        f"Commerce reached in {len(comms)}/{n} games"
        + (f", first at median turn {statistics.median(comms)}" if comms else "")
    )  # type: ignore[type-var]


if __name__ == "__main__":
    main()
