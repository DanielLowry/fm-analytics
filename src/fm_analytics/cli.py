from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from fm_analytics.api import BridgeClient, BridgeError
from fm_analytics.domain import GameState, Squad


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect the current FM squad")
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--base-url",
        default="http://localhost:5072",
        help="FMBridge base URL (default: %(default)s)",
    )
    source.add_argument(
        "--fixture",
        type=Path,
        help="read a combined game/squad fixture without running FMBridge",
    )
    return parser


def load_fixture(path: Path) -> tuple[GameState, Squad]:
    with path.open(encoding="utf-8") as fixture_file:
        payload = json.load(fixture_file)
    return GameState.from_dict(payload["game"]), Squad.from_dict(payload["squad"])


def render(game: GameState, squad: Squad) -> str:
    lines = [
        f"Game date: {game.game_date.strftime('%d %B %Y')}",
        f"Manager: {game.human_manager.name}",
        f"Club: {squad.club.name}",
        "",
        "Players",
        "-------",
    ]
    for player in squad.players:
        positions = ", ".join(player.positions)
        lines.append(f"{player.name:<28} {positions}")
    return "\n".join(lines)


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

