"""Record scouting captures into the player-knowledge database.

`persistence.player_knowledge` knows how to store observations; this module knows
where they come from. It reads the same manager-visible capture file the
Scouting page uses, through the same `ScoutingCandidate` parser, so the database
can never hold something the page would have rejected or a differently
normalised copy of it.

    uv run fm-knowledge ingest data/scouting-capture-enriched.json
    uv run fm-knowledge status
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from fm_analytics.analytics.scouting import ScoutingCandidate
from fm_analytics.persistence.player_knowledge import (
    KnowledgeCapture,
    KnowledgeStoreError,
    PlayerKnowledge,
    PlayerKnowledgeStore,
    RecordResult,
    TimelineError,
)

DEFAULT_DATABASE = Path(__file__).resolve().parents[2] / "data" / "player-knowledge.sqlite3"


def default_save_key(document: Mapping[str, Any]) -> str:
    club = (document.get("source") or {}).get("managedClub") or {}
    club_id = club.get("id")
    if not club_id:
        raise ValueError(
            "the capture does not say which club is managed, so it cannot name the save; "
            "pass an explicit save key"
        )
    return f"club:{club_id}"


def capture_from_document(
    document: Mapping[str, Any], *, save_key: str | None = None
) -> KnowledgeCapture:
    """Turn a scouting-capture document into a recordable capture."""
    game_date = document.get("gameDate")
    if not isinstance(game_date, str):
        raise ValueError("the capture has no gameDate, so its observations cannot be dated")
    rows = document.get("players")
    if not isinstance(rows, list):
        raise ValueError("a scouting capture must be an object with a players list")
    club = (document.get("source") or {}).get("managedClub") or {}
    return KnowledgeCapture(
        save_key=save_key or default_save_key(document),
        game_date=game_date,
        captured_at=str(document.get("capturedAt") or ""),
        club_id=club.get("id"),
        club_name=club.get("name"),
        players=tuple(
            _player_knowledge(ScoutingCandidate.from_dict({**row, "capturedGameDate": game_date}))
            for row in rows
        ),
    )


def _player_knowledge(candidate: ScoutingCandidate) -> PlayerKnowledge:
    return PlayerKnowledge(
        player_id=candidate.id,
        name=candidate.name,
        profile={
            "age": candidate.age,
            "club": candidate.club,
            "contract_type": candidate.contract_type,
            "contract_end": candidate.contract_end,
            "has_contract": candidate.has_contract,
            "transfer_status": candidate.transfer_status,
            "value": candidate.value,
            "scouting_knowledge": candidate.scouting_knowledge,
            "matched_active_search": candidate.matched_active_search,
            "dropped_from_scout_reports": candidate.dropped_from_scout_reports,
            "footedness": candidate.footedness,
            "nationality": candidate.nationality,
            "positions": candidate.positions,
            "raw_positions": candidate.raw_positions,
            "raw_position_familiarity": candidate.raw_position_familiarity,
            "facts": candidate.facts,
        },
        attributes=candidate.attributes,
        attributes_observed_on=candidate.attributes_observed_at,
        last_known_attributes=candidate.last_known_attributes or {},
        last_known_observed_on=candidate.last_known_attributes_observed_at,
    )


def record_capture_file(
    store: PlayerKnowledgeStore,
    path: str | Path,
    *,
    save_key: str | None = None,
    allow_rewind: bool = False,
) -> RecordResult:
    """Read one capture file and append what it shows to `store`."""
    with Path(path).open(encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError(f"{path} is not a scouting capture object")
    return store.record(
        capture_from_document(document, save_key=save_key), allow_rewind=allow_rewind
    )


def _capture_order(path: Path) -> tuple[str, str]:
    with path.open(encoding="utf-8") as stream:
        document = json.load(stream)
    return str(document.get("gameDate") or ""), str(document.get("capturedAt") or "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fm-knowledge", description="The manager's own record of scouted players"
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DATABASE,
        help="player-knowledge database (default: %(default)s)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser(
        "ingest", help="record one or more scouting captures, oldest game date first"
    )
    ingest.add_argument("captures", type=Path, nargs="+")
    ingest.add_argument(
        "--save", help="name of this playthrough (default: the managed club's id)"
    )
    ingest.add_argument(
        "--allow-rewind", action="store_true",
        help="record a capture dated before what the save already holds "
             "(you reloaded an earlier point of the same save)",
    )
    commands.add_parser("status", help="show what has been recorded")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = PlayerKnowledgeStore(args.db)
    try:
        if args.command == "status":
            saves = store.saves()
            if not saves:
                print(f"No saves recorded in {args.db} yet.")
            for save in saves:
                print(
                    f"{save.key} ({save.club_name or 'unnamed club'}): {save.players} players, "
                    f"{save.ingests} recordings from {save.first_game_date} to "
                    f"{save.last_game_date}, {save.profile_rows} profile and "
                    f"{save.attribute_rows} attribute observations"
                )
            return 0
        for path in sorted(args.captures, key=_capture_order):
            result = record_capture_file(
                store, path, save_key=args.save, allow_rewind=args.allow_rewind
            )
            print(f"{path.name}: {result.summary()}")
    except (KnowledgeStoreError, TimelineError, OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
