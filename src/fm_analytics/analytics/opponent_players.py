"""Their players over the opponent report's matches: who started where, who finishes, who supplies.

From each match's player records and timeline, as FM's match reports show
them; a player's attributes only as FM shows them (`seen_attributes`), from the
latest league read. See `opponent_report`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Sequence

from fm_analytics.analytics.match_timeline import GoalMoment, goal_moments
from fm_analytics.domain.matches import MatchRecord, PlayerMatchStats
from fm_analytics.domain.models import AttributeObservation, Player, Visibility

RECENT = 5  # "the last five": the likely XI, and form
LIKELY_STARTS = 2  # starts of the last five that make a player likely to play
MIN_RATE_MINUTES = 270  # per-90 figures need at least three full matches

FM_POSITION_ORDER = ("GK", "SW", "DR", "DC", "DL", "WBR", "DM", "WBL", "MR", "MC", "ML", "AMR", "AMC", "AML", "ST")
LEFT = frozenset({"DL", "WBL", "ML", "AML"})
RIGHT = frozenset({"DR", "WBR", "MR", "AMR"})
WIDE = LEFT | RIGHT
LINES = (
    ("centre_backs", "Centre-backs", frozenset({"DC", "SW"})),
    ("full_backs", "Full-backs and wing-backs", frozenset({"DR", "DL", "WBR", "WBL"})),
    ("central_midfield", "Central midfielders", frozenset({"DM", "MC"})),
    ("wide", "Wide midfielders and wingers", frozenset({"MR", "ML", "AMR", "AML"})),
    ("attacking_midfield", "Attacking midfielders", frozenset({"AMC"})),
    ("strikers", "Strikers", frozenset({"ST"})),
    ("goalkeeper", "Goalkeeper", frozenset({"GK"})),
)


@dataclass(frozen=True)
class PlayerLine:
    """One of their players over the window."""

    short_id: int
    player_id: str | None  # FM's unique ID
    name: str
    position: str | None  # where he most often started (or came on), FM's name
    side: str  # "left", "right" or "centre"
    appearances: int
    starts: int
    recent_starts: int  # of the last five
    started_last: bool
    minutes: int
    goals: int  # penalties included
    penalties: int
    headed_goals: int
    goals_from_crosses: int
    assists: int
    assists_from_crosses: int
    shots: int
    shots_on_target: int
    clear_cut_chances: int
    chances_created: int
    key_passes: int
    dribbles: int
    headers_won: int
    headers_attempted: int
    yellow_cards: int
    red_cards: int
    average_rating: float | None
    last_played: date | None
    # Assists from crosses that may have been his corners (match_timeline.CORNER_GUESS).
    assists_possibly_corners: int = 0
    foot: str | None = None  # preferred foot, when FM shows it
    seen_attributes: Mapping[str, AttributeObservation] = field(default_factory=dict)

    def per90(self, value: int) -> float | None:
        return round(90 * value / self.minutes, 2) if self.minutes >= MIN_RATE_MINUTES else None

    @property
    def likely(self) -> bool:
        """Likely to play: he started at least two of their last five."""
        return self.recent_starts >= LIKELY_STARTS


@dataclass(frozen=True)
class Partnership:
    supplier: str
    scorer: str
    goals: int
    from_crosses: int


def pitch_side(position: str | None, centre_side: str | None) -> str:
    if position in LEFT:
        return "left"
    if position in RIGHT:
        return "right"
    return centre_side or "centre"


def line_of(position: str | None) -> str | None:
    return next((key for key, _label, members in LINES if position in members), None)


def where(player: PlayerMatchStats) -> tuple[str | None, str]:
    """Where he played, and on which side: the starting position's centre side counts only if he stayed there."""
    position = player.position or player.start_position
    centre = player.start_centre_side if position == player.start_position else None
    return position, pitch_side(position, centre)


@dataclass
class _Tally:
    short_id: int
    player_id: str | None = None
    name: str = ""
    positions: Counter = field(default_factory=Counter)
    sides: Counter = field(default_factory=Counter)
    appearances: int = 0
    starts: int = 0
    recent_starts: int = 0
    started_last: bool = False
    minutes: int = 0
    stats: Counter = field(default_factory=Counter)
    goals: int = 0
    penalties: int = 0
    headed_goals: int = 0
    goals_from_crosses: int = 0
    assists: int = 0
    assists_from_crosses: int = 0
    assists_possibly_corners: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    ratings: list = field(default_factory=list)
    last_played: date | None = None


def timeline_goals(match: MatchRecord) -> tuple[GoalMoment, ...] | None:
    """The match's goals from its timeline, or None when the timeline does not name them."""
    moments = goal_moments(match)
    if sum(1 for moment in moments if moment.counts_for == "home") != match.home_goals:
        return None
    if sum(1 for moment in moments if moment.counts_for == "away") != match.away_goals:
        return None
    return moments


def tally_players(matches: Sequence[MatchRecord], club_id: str, latest_five: set[str]) -> dict[int, _Tally]:
    tallies: dict[int, _Tally] = {}
    latest = matches[0].key if matches else None
    for match in matches:
        side = match.side_of(club_id)
        for player in match.detail.players_for(side):
            if not player.played:
                continue
            tally = tallies.setdefault(player.short_id, _Tally(player.short_id))
            tally.player_id = tally.player_id or player.player_id
            tally.name = tally.name or player.label
            position, pitch_side = where(player)
            if position:
                tally.positions[(player.start_position or position)] += 2 if player.started else 1
                tally.sides[pitch_side] += 1
            tally.appearances += 1
            tally.starts += player.started
            if player.started and match.key in latest_five:
                tally.recent_starts += 1
                tally.started_last = tally.started_last or match.key == latest
            tally.minutes += player.minutes
            tally.stats.update({key: value for key, value in player.stats.items()})
            if player.rating is not None:
                tally.ratings.append(player.rating)
            tally.last_played = max(filter(None, (tally.last_played, match.date)))
        events = match.detail.events
        for event in events:
            if event.side != side or event.player_short_id not in tallies:
                continue
            if event.kind == "yellow_card":
                tallies[event.player_short_id].yellow_cards += 1
            elif event.kind in ("second_yellow", "straight_red"):
                tallies[event.player_short_id].red_cards += 1
        moments = timeline_goals(match)
        if moments is None:
            # No timeline that names the goals: the result's own record still names each scorer.
            for incident in match.incidents:
                if incident.side == side and incident.kind in ("goal", "penalty") and incident.player_short_id in tallies:
                    tally = tallies[incident.player_short_id]
                    tally.goals += 1
                    tally.penalties += incident.kind == "penalty"
            continue
        for moment in moments:
            if moment.counts_for != side or moment.event.kind == "own_goal":
                continue
            scorer = tallies.get(moment.event.player_short_id)
            cross = bool(moment.how and moment.how.how == "cross")
            if scorer:
                scorer.goals += 1
                scorer.penalties += moment.event.kind == "penalty"
                scorer.headed_goals += bool(moment.how and moment.how.strike == "header")
                scorer.goals_from_crosses += cross
            supplier = tallies.get(moment.assist.player_short_id) if moment.assist else None
            if supplier:
                supplier.assists += 1
                supplier.assists_from_crosses += cross
                supplier.assists_possibly_corners += moment.possibly_from_a_corner
    return tallies


def _seen(player: Player | None) -> tuple[str | None, Mapping[str, AttributeObservation]]:
    if player is None:
        return None, {}
    seen = {key: value for key, value in player.attributes.items() if value.visibility is not Visibility.UNKNOWN}
    return player.preferred_foot, seen


def player_lines(
    tallies: Mapping[int, _Tally], roster: Mapping[str, Player] | None
) -> tuple[PlayerLine, ...]:
    lines = []
    for tally in tallies.values():
        # A league read's squad list can leave out a player FM still has at the
        # club (Oxford City's regular keeper on 20 October 2020), so it gives
        # attributes only and never says who has left.
        known = roster.get(tally.player_id) if roster is not None and tally.player_id else None
        foot, seen = _seen(known)
        position = tally.positions.most_common(1)[0][0] if tally.positions else None
        lines.append(PlayerLine(
            short_id=tally.short_id,
            player_id=tally.player_id,
            name=tally.name,
            position=position,
            side=tally.sides.most_common(1)[0][0] if tally.sides else "centre",
            appearances=tally.appearances,
            starts=tally.starts,
            recent_starts=tally.recent_starts,
            started_last=tally.started_last,
            minutes=tally.minutes,
            goals=tally.goals,
            penalties=tally.penalties,
            headed_goals=tally.headed_goals,
            goals_from_crosses=tally.goals_from_crosses,
            assists=tally.assists,
            assists_from_crosses=tally.assists_from_crosses,
            shots=tally.stats["shots"],
            shots_on_target=tally.stats["shots_on_target"],
            clear_cut_chances=tally.stats["clear_cut_chances"],
            chances_created=tally.stats["chances_created"],
            key_passes=tally.stats["key_passes"],
            dribbles=tally.stats["dribbles"],
            headers_won=tally.stats["headers_won"],
            headers_attempted=tally.stats["headers_attempted"],
            yellow_cards=tally.yellow_cards,
            red_cards=tally.red_cards,
            average_rating=round(sum(tally.ratings) / len(tally.ratings), 2) if tally.ratings else None,
            last_played=tally.last_played,
            assists_possibly_corners=tally.assists_possibly_corners,
            foot=foot,
            seen_attributes=seen,
        ))
    return tuple(sorted(lines, key=lambda line: (-line.minutes, line.name)))


def _position_order(line: PlayerLine) -> tuple[int, str]:
    position = line.position if line.position in FM_POSITION_ORDER else "ST"
    side_order = {"right": 0, "centre": 1, "left": 2}
    return FM_POSITION_ORDER.index(position) * 3 + side_order.get(line.side, 1), line.name


def likely_xi(players: Sequence[PlayerLine]) -> tuple[PlayerLine, ...]:
    """The eleven who started most of the last five (most recent starters first on a tie), in FM's position order."""
    ranked = sorted(
        (line for line in players if line.recent_starts),
        key=lambda line: (-line.recent_starts, not line.started_last, -line.starts, -line.minutes),
    )
    keepers = [line for line in ranked if line.position == "GK"][:1]
    outfield = [line for line in ranked if line.position != "GK"][:10]
    return tuple(sorted(keepers + outfield, key=_position_order))


def partnerships_in(matches: Sequence[MatchRecord], club_id: str, players: Sequence[PlayerLine]) -> tuple[Partnership, ...]:
    """Who set up whom for at least two of the club's goals, most first."""
    pairs: Counter = Counter()
    crossed: Counter = Counter()
    names = {line.short_id: line.name for line in players}
    for match in matches:
        side = match.side_of(club_id)
        for moment in timeline_goals(match) or ():
            if moment.counts_for == side and moment.assist and moment.event.kind != "own_goal":
                pair = (names.get(moment.assist.player_short_id, "?"), names.get(moment.event.player_short_id, "?"))
                pairs[pair] += 1
                crossed[pair] += bool(moment.how and moment.how.how == "cross")
    return tuple(
        Partnership(supplier, scorer, goals, crossed[(supplier, scorer)])
        for (supplier, scorer), goals in sorted(pairs.items(), key=lambda item: (-item[1], item[0]))
        if goals >= 2
    )[:5]
