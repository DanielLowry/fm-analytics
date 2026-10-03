"""Measure cold and cached league reports with seeded mixed scouting knowledge.

Each squad guarantees the eleven balanced-442 positions, with two to four
observed positions per player. This is an explicit synthetic workload, never
a live capture or a timing assertion suitable for CI.
"""
from __future__ import annotations

import argparse
import random
from dataclasses import replace
from time import perf_counter

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.domain import AttributeObservation, Club, Squad, Visibility
from fm_analytics.domain.leagues import LeagueCapture, LeagueRoster
from fm_analytics.web.league_state import LeagueState
from tools.benchmark_tactic_ranking import synthetic_players
from tools.league_demo import build_demo_capture


def synthetic_league(clubs=22, players=22, seed=7):
    demo = build_demo_capture()
    template = demo.teams[0].squad.players[0]
    slots = MVP_CATALOGUE.tactics["balanced_442"].slots
    rosters = []
    for index in range(clubs):
        club = demo.game.controlled_club if index == 0 else Club(f"synthetic-{index}", f"Synthetic club {index}")
        rng = random.Random(seed + index)
        roster = []
        for number, candidate in enumerate(synthetic_players(players, seed + index)):
            positions = tuple(dict.fromkeys((slots[number].position, *candidate.positions))) if number < 11 else candidate.positions
            positions = positions[:4]
            attributes = {}
            for name, observation in candidate.attributes.items():
                visibility = rng.random()
                if visibility < .4:
                    attributes[name] = observation
                elif visibility < .7:
                    attributes[name] = AttributeObservation(Visibility.RANGE, minimum=max(1, observation.value-3),
                                                           maximum=min(20, observation.value+3))
                elif visibility < .9:
                    attributes[name] = AttributeObservation(Visibility.UNKNOWN)
            roster.append(replace(template, id=f"{club.id}-{number}", name=f"Player {index}-{number}",
                                  club_id=club.id, positions=positions, attributes=attributes,
                                  condition_percent=100, match_fitness_percent=100,
                                  injured=False, suspended=False, availability="available",
                                  position_familiarity={p:20 for p in positions} if index == 0 else {}))
        rosters.append(LeagueRoster(Squad(club, demo.game.game_date, tuple(roster)), True, True,
                                    "Synthetic complete first team"))
    return replace(demo, teams=tuple(rosters))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clubs", type=int, default=22)
    parser.add_argument("--players", type=int, default=22)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--tactic", choices=tuple(MVP_CATALOGUE.tactics))
    args = parser.parse_args(argv)
    if args.clubs < 1 or args.players < 11:
        parser.error("at least one club and eleven players per club are required")
    capture = synthetic_league(args.clubs, args.players, args.seed)
    state = LeagueState()
    state.read = lambda: (capture.game, capture.teams[0].squad)
    state.setup_league(lambda: capture)
    started = perf_counter()
    report = state.league_report(args.tactic)
    cold = perf_counter()-started
    started = perf_counter()
    cached = state.league_report(args.tactic)
    warm = perf_counter()-started
    assert cached is report, "unchanged capture should reuse its completed report"
    tactics = 1 if args.tactic else len(MVP_CATALOGUE.tactics)
    print(f"Synthetic: {args.clubs} clubs × {args.players} players; 2–4 positions; seed {args.seed}")
    print(f"Knowledge: 40% exact, 30% ranged, 20% unknown, 10% uncaptured; {tactics} tactics; three scenarios")
    print(f"Cold: {cold:.3f}s; cached: {warm:.4f}s; comparable: {report.comparable_count}/{args.clubs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
