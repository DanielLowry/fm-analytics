"""Generate an explicit example league for the capture-driven comparison pages.

All teams and observations are synthetic; this never reads the game process.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from fm_analytics.analytics import MVP_CATALOGUE
from fm_analytics.cli import load_fixture
from fm_analytics.domain import AttributeObservation, Club, Squad, Visibility
from fm_analytics.domain.leagues import LeagueCapture, LeagueRoster
from fm_analytics.domain.matches import Competition

FIXTURE = Path(__file__).resolve().parents[1] / "src/fm_analytics/fixtures/sample-game.json"


def build_demo_capture():
    game, owned = load_fixture(FIXTURE)
    slots = MVP_CATALOGUE.tactics["balanced_442"].slots
    template = owned.players[0]
    required = {a.name for role in MVP_CATALOGUE.roles.values() for a in role.attributes}
    rosters = []
    for index, (name, value, complete) in enumerate(((game.controlled_club.name, 8, True),
                                                   ("Strong club", 18, True),
                                                   ("Unscouted club", None, True),
                                                   ("Partial club", 12, False))):
        club = game.controlled_club if index == 0 else Club(f"rival-{index}", name)
        attributes = {key: AttributeObservation(Visibility.KNOWN, value=value) if value is not None
                      else AttributeObservation(Visibility.UNKNOWN) for key in required}
        players = tuple(replace(template, id=f"{club.id}-player-{i}", name=f"{name} player {i}",
                                club_id=club.id, positions=(slot.position,), attributes=attributes,
                                injured=False, suspended=False, availability="available",
                                condition_percent=100, match_fitness_percent=100,
                                position_familiarity={slot.position: 20} if index == 0 else {})
                        for i, slot in enumerate(slots))
        rosters.append(LeagueRoster(Squad(club, game.game_date, players), complete, True,
                                    "Synthetic first-team observation"))
    season_start = game.game_date.year - (game.game_date.month < 7)
    return LeagueCapture("league-demo-save", game, f"{season_start}/{str(season_start + 1)[-2:]}", Competition("league-1", "Example league"),
                         True, "Synthetic full participant list", "fixture", tuple(rosters))



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/league-demo"))
    args = parser.parse_args(argv)
    capture = build_demo_capture()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    league_path, squad_path = args.output_dir / "league.json", args.output_dir / "squad.json"
    league_path.write_text(json.dumps(capture.to_document(), indent=2) + "\n", encoding="utf-8")
    squad_path.write_text(json.dumps({"game": capture.game.to_dict(), "squad": capture.teams[0].squad.to_dict()}, indent=2) + "\n", encoding="utf-8")
    print(f"Synthetic league: {league_path}\nMatching own squad: {squad_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
