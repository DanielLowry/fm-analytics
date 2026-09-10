from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from fm_analytics.api import BridgeClient, BridgeError
from fm_analytics.domain import GameState, Player, Squad


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect the current FM squad")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--base-url",
        default="http://localhost:5072",
        help="FM bridge base URL (default: %(default)s)",
    )
    source.add_argument(
        "--fixture",
        type=Path,
        help="read a combined game/squad fixture without running the bridge",
    )
    return parser


def load_fixture(path: Path) -> tuple[GameState, Squad]:
    with path.open(encoding="utf-8") as fixture_file:
        payload = json.load(fixture_file)
    return GameState.from_dict(payload["game"]), Squad.from_dict(payload["squad"])


def render(game: GameState, squad: Squad) -> str:
    club_name = squad.club.name if squad.club else "No controlled club"
    lines = [
        f"Game date: {game.game_date.strftime('%d %B %Y')}",
        f"Manager: {game.human_manager.name}",
        f"Club: {club_name}",
        "",
        "Players",
        "-------",
    ]
    for player in squad.players:
        positions = ", ".join(player.positions)
        age = str(player.age) if player.age is not None else "?"
        condition = _percent(player.condition_percent)
        fitness = _percent(player.match_fitness_percent)
        contract = _contract_summary(player, squad)
        lines.append(
            f"{player.name:<28} age {age:<2}  {positions:<12} "
            f"condition {condition:<4} fitness {fitness:<4} "
            f"{player.availability}{contract}"
        )
    return "\n".join(lines)


def _percent(value: int | None) -> str:
    return f"{value}%" if value is not None else "?"


def _contract_summary(player: Player, squad: Squad) -> str:
    contract = player.contract
    contracted_club = contract.contracted_club if contract else None
    if contracted_club and squad.club and contracted_club.id != squad.club.id:
        return f" · loan from {contracted_club.name}"
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.fixture:
            game, squad = load_fixture(args.fixture)
        else:
            client = BridgeClient(args.base_url)
            game, squad = client.get_game(), client.get_squad()
    except (BridgeError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    print(render(game, squad))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
