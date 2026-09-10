#!/usr/bin/env python3
"""Capture and compare compact Phase 00 observations from FMBridge."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


class ValidationError(RuntimeError):
    """An observation could not be captured or did not meet expectations."""


def read_json(
    base_url: str,
    resource: str,
    *,
    accept_http_error: bool = False,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{resource}"
    try:
        with urlopen(url, timeout=15) as response:  # noqa: S310
            payload = json.load(response)
    except HTTPError as exc:
        if not accept_http_error:
            raise ValidationError(f"could not read {url}: {exc}") from exc
        try:
            payload = json.load(exc)
        except (json.JSONDecodeError, UnicodeError) as decode_error:
            raise ValidationError(f"could not read {url}: {exc}") from decode_error
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValidationError(f"could not read {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"expected an object from {url}")
    return payload


def capture(base_url: str) -> dict[str, Any]:
    health = read_json(base_url, "health", accept_http_error=True)
    if health.get("status") != "ready":
        raise ValidationError(str(health.get("detail") or health.get("status")))
    game = read_json(base_url, "game")
    squad = read_json(base_url, "squad")
    players = squad.get("players")
    if not isinstance(players, list):
        raise ValidationError("squad response omitted players")
    player_ids = [str(player["id"]) for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise ValidationError("squad response contains duplicate player IDs")
    club = game.get("controlledClub")
    return {
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "source": health.get("source"),
        "gameDate": game["gameDate"],
        "managerId": str(game["humanManager"]["id"]),
        "clubId": str(club["id"]) if club else None,
        "playerCount": len(player_ids),
        "playerIds": sorted(player_ids),
    }


def compare(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    expect_date_change: bool,
    expect_squad_change: bool,
    expect_date_stable: bool = False,
    expect_squad_stable: bool = False,
) -> list[str]:
    failures: list[str] = []
    for field in ("managerId", "clubId"):
        if before.get(field) != after.get(field):
            failures.append(f"{field} changed")
    date_changed = before.get("gameDate") != after.get("gameDate")
    squad_changed = before.get("playerIds") != after.get("playerIds")
    if expect_date_change and not date_changed:
        failures.append("gameDate did not change")
    if expect_date_stable and date_changed:
        failures.append("gameDate changed")
    if expect_squad_change and not squad_changed:
        failures.append("first-team membership did not change")
    if expect_squad_stable and squad_changed:
        failures.append("first-team membership changed")
    return failures


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5072")
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("output", type=Path)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("baseline", type=Path)
    date_expectation = compare_parser.add_mutually_exclusive_group()
    date_expectation.add_argument("--expect-date-change", action="store_true")
    date_expectation.add_argument("--expect-date-stable", action="store_true")
    squad_expectation = compare_parser.add_mutually_exclusive_group()
    squad_expectation.add_argument("--expect-squad-change", action="store_true")
    squad_expectation.add_argument("--expect-squad-stable", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        observation = capture(args.base_url)
        if args.command == "capture":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(observation, indent=2) + "\n")
            print(f"Captured {observation['playerCount']} players to {args.output}")
            return 0

        baseline = json.loads(args.baseline.read_text())
        failures = compare(
            baseline,
            observation,
            expect_date_change=args.expect_date_change,
            expect_squad_change=args.expect_squad_change,
            expect_date_stable=args.expect_date_stable,
            expect_squad_stable=args.expect_squad_stable,
        )
        if failures:
            raise ValidationError("; ".join(failures))
        checks = ["manager/club stability"]
        if args.expect_date_change:
            checks.append("date change")
        if args.expect_date_stable:
            checks.append("date stability")
        if args.expect_squad_change:
            checks.append("squad change")
        if args.expect_squad_stable:
            checks.append("squad stability")
        print(
            f"Validated {', '.join(checks)} with "
            f"{observation['playerCount']} players on {observation['gameDate']}"
        )
        return 0
    except (OSError, KeyError, TypeError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
