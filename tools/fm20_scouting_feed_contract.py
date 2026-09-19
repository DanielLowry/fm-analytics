#!/usr/bin/env python3
"""The stable JSON contract for scouting captures: build it, then read it back.

Split out of ``fm20_scouting_feed.py`` on 18 September 2026 to keep that
module under this project's line cap -- this is a genuinely separate
responsibility from *how* a capture goes and gets its data (live-memory
reads, Frida hydration, pool rebuilds), which stays there. Nothing here
touches FM's process; it only shapes and reshapes the JSON both the CLI and
the web view read and write.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, NamedTuple


SCHEMA_VERSION = 1


class ScoutingFeedError(RuntimeError):
    """A scouting feed could not be captured without crossing a safety boundary."""


class PoolNotBuiltError(ScoutingFeedError):
    """FM has not built this manager's Player Search pool in this process yet.

    Separate from its base class because it is the one failure a caller can
    offer a choice about: open Player Search in FM (no native call), or
    approve asking FM to build the pool.  Everything else is fail-closed.
    """


def feed_document(
    player_ids: Iterable[int],
    names: dict[int, str],
    *,
    game_date: str,
    managed_club: dict[str, str],
    source_count: int,
    excluded_own_ids: Iterable[int],
    attributes_by_id: dict[int, dict[str, Any]] | None = None,
    attributes_observed_at: dict[int, str] | None = None,
    footedness_by_id: dict[int, str] | None = None,
    footedness_observed_at: dict[int, str] | None = None,
    raw_positions_by_id: dict[int, tuple[str, ...]] | None = None,
    identity_facts_by_id: Mapping[int, dict[str, Any]] | None = None,
    position_familiarity_by_id: Mapping[int, Mapping[str, int]] | None = None,
    scouting_knowledge_by_id: Mapping[int, int] | None = None,
    dropped_from_scout_reports_ids: Iterable[int] = (),
    active_search_match_ids: Iterable[int] | None = None,
    hydrated_count: int = 0,
    pool_available: bool = True,
    rebuilt: bool = False,
) -> dict[str, Any]:
    """Build the stable JSON contract consumed by ``fm-web --scouting-json``.

    ``gameDate`` is always the date this capture actually read live, even when
    most players' facts were carried forward from an earlier capture rather
    than re-observed today -- the file's own date always advances. Each
    carried-forward attribute/footedness observation keeps the date it was
    actually seen on in ``attributesObservedAt``/``footednessObservedAt``, so
    a stale-looking value is visible as stale rather than silently relabelled
    as current. A player hydrated in this run gets ``game_date`` for both.
    """
    ids = tuple(sorted(set(player_ids)))
    missing_names = [player_id for player_id in ids if not names.get(player_id)]
    if missing_names:
        raise ScoutingFeedError(
            f"identity lookup failed for {len(missing_names)} discovered player(s)"
        )
    excluded = tuple(sorted(set(excluded_own_ids)))
    attributes_by_id = attributes_by_id or {}
    attributes_observed_at = attributes_observed_at or {}
    footedness_by_id = footedness_by_id or {}
    footedness_observed_at = footedness_observed_at or {}
    raw_positions_by_id = raw_positions_by_id or {}
    identity_facts_by_id = identity_facts_by_id or {}
    position_familiarity_by_id = position_familiarity_by_id or {}
    scouting_knowledge_by_id = scouting_knowledge_by_id or {}
    dropped_from_scout_reports = set(dropped_from_scout_reports_ids)
    # None means no search was on screen, which is different from a search
    # that matched nobody -- the first cannot answer the question at all.
    search_matches = None if active_search_match_ids is None else set(active_search_match_ids)
    with_age = sum(1 for player_id in ids if "age" in identity_facts_by_id.get(player_id, {}))
    with_club = sum(1 for player_id in ids if "club" in identity_facts_by_id.get(player_id, {}))
    scouted_count = sum(
        1 for player_id in ids
        if player_id in scouting_knowledge_by_id and player_id not in dropped_from_scout_reports
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "capturedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "gameDate": game_date,
        "source": {
            "kind": "manager-rooted-player-search-pool",
            "transport": "windows-frida-server" if rebuilt else "read-only-process-memory",
            "poolRebuiltByCapture": rebuilt,
            "poolAvailable": pool_available,
            "sourceCount": source_count,
            "excludedOwnContractedCount": len(excluded),
            # Which players FM's own on-screen Player Search matched when this
            # capture ran. The criteria are not readable, only the result, so
            # nothing here may claim to know what was filtered on.
            "activeSearchMatchCount": None if search_matches is None else len(search_matches),
            "managedClub": managed_club,
            "fieldCoverage": {
                "identity": (
                    "manager-search-pool plus read-only identity lookup "
                    f"(age {with_age}/{len(ids)}, club/transfer status {with_club}/{len(ids)}); "
                    "availability is not captured yet -- its read is unreliable for some pool "
                    "records (see resolve_source_identity_facts)"
                ),
                "positions": (
                    "raw external position data accepted under the documented short-term "
                    f"visibility gap for {len(raw_positions_by_id)}/{len(ids)} candidates"
                    + (
                        f"; individual position ratings for {len(position_familiarity_by_id)}/{len(ids)}"
                        if position_familiarity_by_id else ""
                    )
                    if raw_positions_by_id else "not yet externally visibility-verified"
                ),
                "attributes": (
                    (
                        f"{scouted_count}/{len(ids)} from the manager's own scouting knowledge "
                        "(read-only, FM's own visibility formula and the scout's report -- "
                        "see tools.fm20_scouted_attributes)"
                        + (
                            f"; {hydrated_count}/{len(ids)} additionally confirmed via a "
                            "manager-visible native-builder hydration this run"
                            if hydrated_count else ""
                        )
                    )
                    if attributes_by_id or scouted_count
                    else "not yet externally visibility-verified"
                ),
                "footedness": (
                    f"manager-visible property getter for {len(footedness_by_id)}/{len(ids)} candidates"
                    if footedness_by_id else "not yet externally visibility-verified"
                ),
            },
        },
        "players": [
            {
                "id": str(player_id),
                "name": names[player_id],
                "positions": [],
                **identity_facts_by_id.get(player_id, {}),
                **(
                    {"scoutingKnowledge": scouting_knowledge_by_id[player_id]}
                    if player_id in scouting_knowledge_by_id else {}
                ),
                **(
                    {"matchedActiveSearch": player_id in search_matches}
                    if search_matches is not None else {}
                ),
                **(
                    {"droppedFromScoutReports": True}
                    if player_id in dropped_from_scout_reports else {}
                ),
                **({"rawPositions": list(raw_positions_by_id[player_id])}
                   if player_id in raw_positions_by_id else {}),
                **({"rawPositionFamiliarity": dict(position_familiarity_by_id[player_id])}
                   if player_id in position_familiarity_by_id else {}),
                "attributes": attributes_by_id.get(player_id, {}),
                **(
                    {"attributesObservedAt": attributes_observed_at.get(player_id, game_date)}
                    if player_id in attributes_by_id else {}
                ),
                **({"footedness": footedness_by_id[player_id]} if player_id in footedness_by_id else {}),
                **(
                    {"footednessObservedAt": footedness_observed_at.get(player_id, game_date)}
                    if player_id in footedness_by_id else {}
                ),
            }
            for player_id in ids
        ],
    }


class PriorVisibility(NamedTuple):
    """Everything reusable from an earlier capture, dated per field.

    ``game_date`` is that capture's own top-level date, kept only so a caller
    can log how far it has drifted from today's live read -- it is no longer
    used to refuse a refresh. Each attribute/footedness map's *_observed_at
    counterpart records when that specific fact was actually seen, which for
    a file written before this field existed falls back to the whole prior
    capture's date (the best available answer at migration time).
    """

    game_date: str
    attributes: dict[int, dict[str, Any]]
    attributes_observed_at: dict[int, str]
    footedness: dict[int, str]
    footedness_observed_at: dict[int, str]
    raw_positions: dict[int, tuple[str, ...]]
    scouting_knowledge: dict[int, int]
    names: dict[int, str]


def load_prior_visibility(path: Path) -> PriorVisibility:
    """Load prior captured fields, including explicitly accepted raw positions."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        game_date = raw["gameDate"]
        rows = raw["players"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ScoutingFeedError(f"cannot read prior scouting feed {path}: {error}") from error
    if not isinstance(game_date, str) or not isinstance(rows, list):
        raise ScoutingFeedError("prior scouting feed has an invalid game date or player list")
    attributes: dict[int, dict[str, Any]] = {}
    attributes_observed_at: dict[int, str] = {}
    footedness: dict[int, str] = {}
    footedness_observed_at: dict[int, str] = {}
    raw_positions: dict[int, tuple[str, ...]] = {}
    scouting_knowledge: dict[int, int] = {}
    names: dict[int, str] = {}

    def observed_at(row: Mapping[str, Any], field: str) -> str:
        value = row.get(field)
        if value is None:
            return game_date  # pre-dating field: the whole capture's date is all we have
        if not isinstance(value, str):
            raise ScoutingFeedError(f"prior scouting feed has an invalid {field}")
        return value

    for row in rows:
        if not isinstance(row, Mapping):
            raise ScoutingFeedError("prior scouting feed contains an invalid player")
        try:
            player_id = int(row["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ScoutingFeedError("prior scouting feed contains an invalid player ID") from error
        prior_name = row.get("name")
        if prior_name is not None:
            if not isinstance(prior_name, str) or not prior_name:
                raise ScoutingFeedError("prior scouting feed contains an invalid player name")
            names[player_id] = prior_name
        observed_attributes = row.get("attributes", {})
        if not isinstance(observed_attributes, Mapping):
            raise ScoutingFeedError("prior scouting feed contains an invalid attribute map")
        if observed_attributes:
            attributes[player_id] = dict(observed_attributes)
            attributes_observed_at[player_id] = observed_at(row, "attributesObservedAt")
        observed_foot = row.get("footedness")
        if observed_foot is not None:
            if not isinstance(observed_foot, str):
                raise ScoutingFeedError("prior scouting feed contains an invalid footedness value")
            footedness[player_id] = observed_foot
            footedness_observed_at[player_id] = observed_at(row, "footednessObservedAt")
        observed_raw_positions = row.get("rawPositions")
        if observed_raw_positions is not None:
            if not (
                isinstance(observed_raw_positions, list)
                and all(isinstance(position, str) and position for position in observed_raw_positions)
            ):
                raise ScoutingFeedError(
                    "prior scouting feed contains an invalid raw position list"
                )
            raw_positions[player_id] = tuple(observed_raw_positions)
        observed_knowledge = row.get("scoutingKnowledge")
        if observed_knowledge is not None:
            if not isinstance(observed_knowledge, int) or isinstance(observed_knowledge, bool):
                raise ScoutingFeedError("prior scouting feed contains an invalid scoutingKnowledge value")
            scouting_knowledge[player_id] = observed_knowledge
    return PriorVisibility(
        game_date, attributes, attributes_observed_at, footedness, footedness_observed_at,
        raw_positions, scouting_knowledge, names,
    )
