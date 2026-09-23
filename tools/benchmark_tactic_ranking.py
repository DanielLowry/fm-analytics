"""Measure exact sequential and process-parallel full tactic rankings.

This is deliberately a benchmark, not a test with a timing threshold: laptop
CPU frequency and background load make absolute seconds unsuitable for CI. It
does assert the complete returned recommendations are equal, so a faster path
cannot quietly change a tie, an assignment, or an explanatory score band.
"""

from __future__ import annotations

import argparse
import random
from time import perf_counter

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    PlayerSelectionInput,
    TacticRankingExecutor,
    recommend_tactic_effective_and_potential,
)
from fm_analytics.domain import AttributeObservation, Visibility


def synthetic_players(count: int, seed: int) -> tuple[PlayerSelectionInput, ...]:
    """Return the deterministic, positionally broad stress input from the investigation."""
    rng = random.Random(seed)
    positions = tuple(
        sorted(
            {
                position
                for role in MVP_CATALOGUE.roles.values()
                for position in role.eligible_positions
            }
        )
    )
    attributes = tuple(
        sorted(
            {
                attribute.name
                for role in MVP_CATALOGUE.roles.values()
                for attribute in role.attributes
            }
        )
    )
    return tuple(
        PlayerSelectionInput(
            id=str(index),
            name=f"Synthetic Player {index:02}",
            positions=tuple(rng.sample(positions, rng.randint(2, 4))),
            attributes={
                name: AttributeObservation(Visibility.KNOWN, value=rng.randint(6, 18))
                for name in attributes
            },
            availability="available",
            injured=False,
            suspended=False,
            condition_percent=100,
            match_fitness_percent=100,
            position_familiarity={position: 20 for position in positions},
        )
        for index in range(1, count + 1)
    )


def _timed(call):
    started = perf_counter()
    result = call()
    return result, perf_counter() - started


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--players", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    if args.players < 1:
        parser.error("--players must be at least 1")
    if args.workers < 1:
        parser.error("--workers must be at least 1")

    players = synthetic_players(args.players, args.seed)
    sequential, sequential_seconds = _timed(
        lambda: recommend_tactic_effective_and_potential(players, MVP_CATALOGUE)
    )
    executor = TacticRankingExecutor(workers=args.workers)
    try:
        # Startup is intentionally outside the timing: the web server retains
        # this executor, and `warm` happens before it begins handling requests.
        executor.warm()
        parallel, parallel_seconds = _timed(
            lambda: recommend_tactic_effective_and_potential(
                players, MVP_CATALOGUE, ranking_executor=executor
            )
        )
    finally:
        executor.shutdown()

    if parallel != sequential:
        raise AssertionError("parallel ranking changed the sequential result")
    speedup = sequential_seconds / parallel_seconds if parallel_seconds else float("inf")
    print(
        f"{args.players} players, seed {args.seed}, {len(MVP_CATALOGUE.tactics)} tactics\n"
        f"sequential: {sequential_seconds:.3f}s\n"
        f"parallel ({args.workers} workers, warmed): {parallel_seconds:.3f}s\n"
        f"speed-up: {speedup:.2f}x\n"
        "exact result: yes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
