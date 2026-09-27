"""A player as the manager last knew him, assembled from the knowledge history.

`PlayerKnowledgeStore.best_known_profile` and `best_known_profiles` read
through here. For one save and one in-game date they take the newest profile
row, the newest non-unknown reading of each attribute, and the newest recorded
state beside it even when that state is unknown, so a caller can say the
knowledge has faded. Nothing dated after that day, or from another save, is
read.

Observation rows are change-only, so a row's date is when a state began. Every
day a player is seen is also kept as a sighting, and each reading here carries
the last day it was still seen: Pace 14 seen every week is a week old, not as
old as the week it first appeared. The result reports ages and leaves "out of
date" to whoever asked for it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from fm_analytics.domain import AttributeObservation, Visibility
from fm_analytics.persistence.player_knowledge import PROFILE_FIELDS, _decoded_profile


@dataclass(frozen=True)
class SelectedAttribute:
    """One attribute reading picked out of the history, with when it was seen.

    `observed_on` is the row's date: when the store first recorded this state.
    An unchanged reading adds no row, so `last_seen_on` is the latest day at or
    before `as_of` that a sheet still showed it, and the date its age runs
    from. The two are equal when it was not seen again, or was seen again only
    before sightings were kept.
    """

    observation: AttributeObservation
    observed_on: str
    last_seen_on: str
    source: str  # 'current' or 'last_known', as recorded


@dataclass(frozen=True)
class AttributeKnowledge:
    """One attribute of a best-known profile: the value to show, and the newest state.

    `best_known` is None when every reading at or before the date is unknown:
    captured, but never learned. An attribute missing from the profile's
    `attributes` mapping was never captured at all, which is a different state
    and is not invented as an unknown here.
    """

    attribute: str
    best_known: SelectedAttribute | None
    latest: SelectedAttribute


@dataclass(frozen=True)
class BestKnownProfile:
    """A player assembled from what one save recorded at or before one game date.

    * `profile` is the latest profile observation at or before `as_of`, in the
      same shape `profile_history` returns (including `observed_on`), or None
      when no profile row is that early. Profile rows are written only when a
      fact changed, so its `observed_on` is "when a fact last changed";
      `profile_last_seen_on` is the last day at or before `as_of` he was seen
      with those facts.
    * `attributes` holds every attribute recorded at or before `as_of`. Each
      entry carries the best-known (never unknown) reading and, separately, the
      newest recorded state even when that state is unknown, so a caller can
      say the knowledge has faded. Attribute rows are never read past `as_of`.
    * `oldest_seen_on` / `latest_seen_on` bound the last-seen dates of
      everything this result draws on, so `oldest_seen_on` is the age of its
      stalest reading: an age, not a verdict. Whether that age is "out of date"
      is the caller's threshold to apply, never this store's.
    * `name` is the save's most recently recorded name: the history dates
      profile facts and attributes, not names, and identity is the player id.
    """

    save_key: str
    player_id: str
    name: str
    as_of: str
    profile: Mapping[str, Any] | None
    profile_last_seen_on: str | None
    attributes: Mapping[str, AttributeKnowledge]
    oldest_seen_on: str
    latest_seen_on: str


def read_best_known(
    connection: sqlite3.Connection, save_key: str, as_of: str, player_id: str | None
) -> dict[str, BestKnownProfile]:
    """Assemble best-known profiles; `player_id` narrows the same queries to one.

    `connection` is one of the store's own (rows readable by name), and `as_of`
    must already be a checked YYYY-MM-DD date, because it is compared as text.
    """
    save = connection.execute("SELECT id FROM saves WHERE key = ?", (save_key,)).fetchone()
    if save is None:
        return {}
    wanted = "" if player_id is None else " AND player_id = :player_id"
    args = {"save_id": int(save[0]), "as_of": as_of, "player_id": player_id}
    names = {
        row["player_id"]: row["name"]
        for row in connection.execute(
            f"SELECT player_id, name FROM players WHERE save_id = :save_id{wanted}", args
        )
    }
    # The newest profile row is the state at `as_of`, so every profile
    # sighting since its date saw it.
    profile_rows: dict[str, dict[str, Any]] = {}
    profile_seen: dict[str, str] = {}
    for row in connection.execute(
        f"SELECT player_id, observed_on, {', '.join(PROFILE_FIELDS)}, "
        "  (SELECT MAX(s.observed_on) FROM sightings s "
        "   WHERE s.save_id = r.save_id AND s.player_id = r.player_id "
        "     AND s.kind = 'profile' AND s.attribute = '' "
        "     AND s.observed_on BETWEEN r.observed_on AND :as_of) AS seen_until "
        "FROM ("
        "  SELECT *, ROW_NUMBER() OVER (PARTITION BY player_id "
        "    ORDER BY observed_on DESC, id DESC) AS rn "
        "  FROM profile_observations "
        f"  WHERE save_id = :save_id AND observed_on <= :as_of{wanted}"
        ") r WHERE rn = 1",
        args,
    ):
        profile_rows[row["player_id"]] = _decoded_profile(row)
        profile_seen[row["player_id"]] = row["seen_until"] or row["observed_on"]
    # One pass yields both selections: the newest row overall (the latest
    # state, unknown or not) and the newest row that carries a value (the
    # best-known one). Ties on the in-game date are broken by row id, newest
    # first -- the same order `attribute_history` reports, so a same-day
    # re-record and a re-read cannot disagree. A reading was last seen on the
    # newest sighting between its own row and the next change (`next_on`). The
    # latest state has no next change, so the player's newest sheet (or the
    # attribute's newest last-known sighting) is enough; only a reading that
    # has since changed, such as a faded best-known value, needs the range
    # looked up.
    latest: dict[tuple[str, str], SelectedAttribute] = {}
    best_known: dict[tuple[str, str], SelectedAttribute] = {}
    for row in connection.execute(
        "SELECT r.player_id, r.attribute, r.observed_on, r.source, r.visibility, "
        "r.value, r.minimum, r.maximum, r.rn_latest, r.rn_best, "
        "  CASE WHEN r.next_on IS NULL "
        "    THEN MAX(r.observed_on, COALESCE(sheet.seen, ''), COALESCE(last_known.seen, '')) "
        "    ELSE COALESCE((SELECT MAX(s.observed_on) FROM sightings s "
        "      WHERE s.save_id = r.save_id AND s.player_id = r.player_id "
        "        AND s.kind IN ('current', 'last_known') "
        "        AND s.attribute IN ('', r.attribute) "
        "        AND s.observed_on >= r.observed_on AND s.observed_on < r.next_on), "
        "      r.observed_on) "
        "  END AS last_seen_on "
        "FROM ("
        "  SELECT *, "
        "    ROW_NUMBER() OVER (PARTITION BY player_id, attribute "
        "      ORDER BY observed_on DESC, id DESC) AS rn_latest, "
        "    ROW_NUMBER() OVER (PARTITION BY player_id, attribute "
        "      ORDER BY CASE WHEN visibility = 'unknown' THEN 1 ELSE 0 END, "
        "               observed_on DESC, id DESC) AS rn_best, "
        # The row before in newest-first order is the next change; LAG over
        # rn_latest's own order shares its sort.
        "    LAG(observed_on) OVER (PARTITION BY player_id, attribute "
        "      ORDER BY observed_on DESC, id DESC) AS next_on "
        "  FROM attribute_observations "
        f"  WHERE save_id = :save_id AND observed_on <= :as_of{wanted}"
        ") r "
        "LEFT JOIN ("
        "  SELECT player_id, MAX(observed_on) AS seen FROM sightings "
        "  WHERE save_id = :save_id AND kind = 'current' AND observed_on <= :as_of"
        f"{wanted} GROUP BY player_id"
        ") sheet ON sheet.player_id = r.player_id "
        "LEFT JOIN ("
        "  SELECT player_id, attribute, MAX(observed_on) AS seen FROM sightings "
        "  WHERE save_id = :save_id AND kind = 'last_known' AND observed_on <= :as_of"
        f"{wanted} GROUP BY player_id, attribute"
        ") last_known ON last_known.player_id = r.player_id "
        "  AND last_known.attribute = r.attribute "
        "WHERE r.rn_latest = 1 OR r.rn_best = 1 "
        "ORDER BY r.player_id, r.attribute",
        args,
    ):
        selected = SelectedAttribute(
            observation=AttributeObservation(
                Visibility(row["visibility"]), value=row["value"],
                minimum=row["minimum"], maximum=row["maximum"],
            ),
            observed_on=row["observed_on"],
            last_seen_on=row["last_seen_on"],
            source=row["source"],
        )
        key = (row["player_id"], row["attribute"])
        if row["rn_latest"] == 1:
            latest[key] = selected
        # The best candidate can still be an unknown row: then the save has
        # nothing but unknowns for this attribute, and there is no best-known
        # value to offer.
        if row["rn_best"] == 1 and row["visibility"] != Visibility.UNKNOWN.value:
            best_known[key] = selected

    grouped: dict[str, dict[str, AttributeKnowledge]] = {}
    for (pid, attribute), selected in latest.items():
        grouped.setdefault(pid, {})[attribute] = AttributeKnowledge(
            attribute=attribute, best_known=best_known.get((pid, attribute)), latest=selected
        )
    dates: dict[str, set[str]] = {pid: {seen} for pid, seen in profile_seen.items()}
    for pid, attributes in grouped.items():
        used = dates.setdefault(pid, set())
        for knowledge in attributes.values():
            used.add(knowledge.latest.last_seen_on)
            if knowledge.best_known is not None:
                used.add(knowledge.best_known.last_seen_on)
    profiles: dict[str, BestKnownProfile] = {}
    # Only players with a row dated at or before `as_of` qualify; the foreign
    # key means such a player always has a name to go with him.
    for pid in sorted(dates):
        if pid not in names:
            continue
        profiles[pid] = BestKnownProfile(
            save_key=save_key, player_id=pid, name=names[pid], as_of=as_of,
            profile=profile_rows.get(pid), profile_last_seen_on=profile_seen.get(pid),
            attributes=grouped.get(pid, {}),
            oldest_seen_on=min(dates[pid]), latest_seen_on=max(dates[pid]),
        )
    return profiles
