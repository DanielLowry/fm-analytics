"""Who gave each penalty away, as the manager read it off FM's replay.

FM's match record names who scored a penalty, never who gave it away
(docs/match-replay-extraction.md), so the manager records it on the match
page or with `fm-matches penalty`. It is kept apart from what is read from FM
(`MatchHistoryStore.record_penalty_foul`), and no read of FM touches it.
This puts the two together: each penalty scored against us, who could have
given it away (our players on the pitch at that minute), who the manager says
did, and the tally the Matches page and `fm-matches review` show.

Only penalties that were scored are known: FM's record of a result lists its
goals, and a saved or missed penalty is not among them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from fm_analytics.domain.matches import MatchRecord

# (match key, minute, added time): one penalty, as FM's result records it.
PenaltyKey = tuple[str, int, int]


@dataclass(frozen=True)
class ConcededPenalty:
    match_key: str
    date: date
    opponent: str
    minute: int
    added_time: int
    taker: str | None
    # Our players on the pitch at that minute, (short ID, name); empty when
    # the match's line-ups were not read, and then nobody can be recorded.
    on_pitch: tuple[tuple[int, str], ...]
    given_away_by: str | None = None  # the manager's record; None until made
    given_away_by_id: int | None = None

    @property
    def clock(self) -> str:
        return f"{self.minute}+{self.added_time}" if self.added_time else str(self.minute)

    @property
    def key(self) -> PenaltyKey:
        return (self.match_key, self.minute, self.added_time)


@dataclass(frozen=True)
class PenaltyRecord:
    penalties: tuple[ConcededPenalty, ...]  # oldest first

    @property
    def by_player(self) -> tuple[tuple[str, int], ...]:
        """Who gave the recorded ones away, most first."""
        counts = Counter(penalty.given_away_by for penalty in self.penalties if penalty.given_away_by)
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    @property
    def unrecorded(self) -> tuple[ConcededPenalty, ...]:
        return tuple(penalty for penalty in self.penalties if penalty.given_away_by is None)


def _on_pitch(match: MatchRecord, side: str, minute: int) -> tuple[tuple[int, str], ...]:
    if match.detail is None:
        return ()
    return tuple(
        (player.short_id, player.label)
        for player in match.detail.players_for(side)
        if player.played and (player.came_on or 0) <= minute and (player.went_off is None or player.went_off >= minute)
    )


def conceded_penalties(
    match: MatchRecord, club_id: str, given_away: Mapping[PenaltyKey, int | None] = {}
) -> tuple[ConcededPenalty, ...]:
    """The penalties scored against the club in one match, each with the manager's record of who gave it away."""
    ours = match.side_of(club_id)
    found = []
    for incident in match.incidents:
        if incident.kind != "penalty" or incident.side == ours:
            continue
        on_pitch = _on_pitch(match, ours, incident.minute)
        recorded = given_away.get((match.key, incident.minute, incident.added_time))
        name = dict(on_pitch).get(recorded) if recorded is not None else None
        found.append(ConcededPenalty(
            match_key=match.key,
            date=match.date,
            opponent=match.team("away" if ours == "home" else "home").name,
            minute=incident.minute,
            added_time=incident.added_time,
            taker=incident.player,
            on_pitch=on_pitch,
            given_away_by=name,
            given_away_by_id=recorded if name else None,
        ))
    return tuple(found)


def penalty_record(
    matches: Iterable[MatchRecord], club_id: str, given_away: Mapping[PenaltyKey, int | None] = {}
) -> PenaltyRecord:
    return PenaltyRecord(tuple(
        penalty
        for match in sorted(matches, key=lambda match: match.date)
        for penalty in conceded_penalties(match, club_id, given_away)
    ))
