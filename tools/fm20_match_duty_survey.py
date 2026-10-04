#!/usr/bin/env python3
"""Read archived duty candidates for the managed first team's past matches.

Research only: no candidate is assigned to a player or consumed by FMBridge.
Use ``fm20_research.py run match-duty-archive-survey`` for build preflight,
timeout, state checks and an immutable evidence envelope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "src"))

from tools import fm20_linux_probe as probe
from tools import fm20_match_archive as archive
from tools.fm20_linux_probe_runtime import snapshot_marker
from tools.fm20_match_probe import (
    Clubs, Memory, default_temporary_folder, first_team_address, played_results, temporary_folder,
)
from tools.fm20_match_tactics import DUTY_LABELS, Slot, TacticDecodeError, candidate_prefixes


MAX_ARCHIVE_BYTES = 128 << 20
MAX_MATCH_BYTES = 32 << 20
MAX_ARRAYS_PER_MATCH = 128


def _fingerprint(path: Path) -> str:
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise TacticDecodeError("archive exceeds the research size limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def slot_report(slot: Slot) -> dict[str, Any]:
    return {
        "positionCode": hex(slot.position),
        "roleAndDutyCode": hex(slot.role_and_duty),
        "roleCode": hex(slot.role),
        "dutyCode": hex(slot.duty),
        "duty": DUTY_LABELS.get(slot.duty),
    }


def unique_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reject repeated fixture candidates and chunks fitting multiple fixtures."""
    fixture_keys = [(row["date"], row["home"]["id"], row["away"]["id"]) for row in matches]
    chunk_keys = [(row["archive"], row["chunkIndex"]) for row in matches]
    fixtures, chunks = Counter(fixture_keys), Counter(chunk_keys)
    return [row for row, fixture, chunk in zip(matches, fixture_keys, chunk_keys)
            if fixtures[fixture] == 1 and chunks[chunk] == 1]


def survey(memory: Memory, temporary: Path) -> dict[str, Any]:
    managed_team = first_team_address(memory)
    clubs = Clubs(memory)
    wanted = []
    for row in played_results(memory).values():
        if managed_team not in (row["home_team"], row["away_team"]):
            continue
        home, away = clubs(row["home_team"]), clubs(row["away_team"])
        if not home or not away:
            continue
        wanted.append({
            "date": row["date"].isoformat(), "home": home, "away": away,
            "homeGoals": row["home_goals"], "awayGoals": row["away_goals"],
        })
    files = archive.archive_files(temporary)
    before = {path: _fingerprint(path) for path in files}
    matches = []
    for path in files:
        for index, chunk in enumerate(archive.chunks(path)):
            if len(chunk) > MAX_MATCH_BYTES:
                raise TacticDecodeError("match exceeds the research size limit")
            fixtures = [row for row in wanted if archive.involves(
                chunk, int(row["home"]["id"]), int(row["away"]["id"]))]
            for fixture in fixtures:
                detail, problems = archive.decode_match(chunk, fixture["homeGoals"], fixture["awayGoals"])
                if detail is None:
                    continue
                candidates = candidate_prefixes(chunk)
                if len(candidates) > MAX_ARRAYS_PER_MATCH:
                    raise TacticDecodeError("match exceeds the research candidate limit")
                matches.append({
                    **fixture, "archive": path.name, "chunkIndex": index,
                    "chunkSha256": hashlib.sha256(chunk).hexdigest(),
                    "statsValidated": not problems,
                    "players": [{
                        "shortId": player["short_id"], "side": player["side"],
                        "started": player["started"], "played": player["played"],
                        "roleCode": hex(player["role_code"]),
                        "startPositionCode": hex(struct.unpack_from(
                            "<I", chunk, player["at"] + archive.START_POSITION)[0]),
                    } for player in detail["players"]],
                    "candidates": [{
                        "offset": candidate.offset, "prefixEnd": candidate.prefix_end,
                        "name": candidate.name,
                        "slots": [slot_report(slot) for slot in candidate.slots],
                        "playerOverrides": [{
                            "shortId": player_id, "slots": [slot_report(slot) for slot in entries],
                        } for player_id, entries in candidate.overrides],
                    } for candidate in candidates],
                })
    after = {path: _fingerprint(path) for path in archive.archive_files(temporary)}
    unambiguous = unique_matches(matches)
    return {
        "researchOnly": True, "appearancesLinked": False, "labelsUiVerified": False,
        "stable": before == after, "matchesRead": len(unambiguous),
        "arraysFound": sum(len(row["candidates"]) for row in unambiguous),
        "ambiguousFixtureCandidates": len(matches) - len(unambiguous),
        "archives": [{"name": path.name, "sha256": digest} for path, digest in before.items()],
        "matches": sorted(unambiguous, key=lambda match: match["date"]),
    }


def capture_survey(pid: int) -> dict[str, Any]:
    before = snapshot_marker(pid)
    with closing(Memory(pid)) as memory:
        temporary = temporary_folder(pid) or default_temporary_folder(memory.executable)
        if temporary is None:
            raise TacticDecodeError("FM's Temporary folder is unavailable")
        report = survey(memory, temporary)
    after = snapshot_marker(pid)
    report["stable"] = report["stable"] and before == after
    report.update({
        "status": "complete" if report["stable"] else "changed_during_read",
        "capturedAt": datetime.now(timezone.utc).isoformat(), "gameDate": before.game_date,
        "managerId": before.manager_id, "managedClubId": before.club_id,
        "limitations": [
            "Decoded tactic arrays have no proven team/time/player association.",
            "Names and catalogue similarity must not select a candidate.",
            "Only Defend, Support and Attack have grounded labels; other duty masks stay raw.",
            "No match capture, history database or production inference is modified.",
        ],
    })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists():
        parser.error("report already exists; research evidence is immutable")
    try:
        report = capture_survey(args.pid)
    except (OSError, probe.ProbeError, TacticDecodeError) as error:
        report = {"researchOnly": True, "status": "error", "error": str(error)}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report.get(key) for key in ("status", "matchesRead", "arraysFound", "stable")}))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
