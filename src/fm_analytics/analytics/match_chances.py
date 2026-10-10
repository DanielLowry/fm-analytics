"""Result against the chances: how well one match was played, and whether the score was fair to it.

Each side's chances are valued by `chance_value`, from your other competitive
matches, both sides' shots counted alike. From those values come how often
chances like these win, draw or lose, and so whether the result was about what
the chances deserved or luck. Where a side's goals and its chances part
company, two steps say why: how many of its shots were on goal against how
many usually are for chances like these (the shooting), and how many of those
went in against how many usually do (the keeper, the blocks and luck). Over
your other matches the same comparison says whether a bad day in front of goal
is a pattern: the team's and each player's goals against what their chances
were worth, and how often luck alone leaves a gap that large.

Like the rest of a match's Diagnosis it is a description and changes no score.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import stdev
from typing import Mapping, Sequence

from fm_analytics.analytics.chance_value import (
    PENALTY_VALUE,
    ChanceRates,
    ClassifiedShot,
    chance_rates,
    classify_shots,
    goal_chances,
    luck_odds,
    one_in,
    outcomes,
    own_goals_for,
)
from fm_analytics.analytics.match_analysis import MatchReview, MatchSummary
from fm_analytics.analytics.match_diagnostics import MIN_BASELINE_MATCHES, eligible_team_summaries, expected_value

# P(win) - P(loss) from the chances at which one side had the better of them.
BETTER_CHANCES = 0.25
# A finishing gap is a pattern when luck alone leaves one this large less often than this.
PATTERN_ODDS = 0.05
# Goals this far from what a side's (or a player's) chances were worth are worth explaining.
NOTABLE_GAP = 0.5
MAX_FINISHERS = 3
_VERDICTS = {
    ("better", "W"): ("Deserved win", "good"),
    ("better", "D"): ("Should have won", "unlucky"),
    ("better", "L"): ("Unlucky defeat", "unlucky"),
    ("even", "W"): ("Won a close one", "even"),
    ("even", "D"): ("Fair draw", "even"),
    ("even", "L"): ("Lost a close one", "even"),
    ("worse", "W"): ("Lucky win", "lucky"),
    ("worse", "D"): ("Lucky draw", "lucky"),
    ("worse", "L"): ("Deserved defeat", "bad"),
}
HEADING_WORDS = {"on_goal": "saved or blocked", "wide": "wide", "over": "over"}


@dataclass(frozen=True)
class MissedChance:
    player: str | None
    clock: str
    heading: str  # "on_goal" (saved or blocked), "wide" or "over"

    @property
    def outcome(self) -> str:
        return HEADING_WORDS[self.heading]


@dataclass(frozen=True)
class SideChances:
    """One side's chances in the match, what they were worth, and where its goals parted from them."""

    shots: int
    clear_cut: int  # penalties included, as FM counts them
    penalties: int  # scored: FM keeps no other
    worth: float  # what its chances were worth in goals
    goals: int  # from its own shots
    own_goals: int  # put into the other net by the other side, counting for this one
    on_goal: int  # shots on goal, penalties left out
    usual_on_goal: float  # what chances like these usually put on goal
    scored_on_goal: int  # goals from those shots on goal
    usual_scored_on_goal: float  # what that many shots on goal, of those kinds, usually score
    missed_clear_cut: tuple[MissedChance, ...] = ()

    @property
    def score(self) -> int:
        return self.goals + self.own_goals

    @property
    def shooting(self) -> float:
        """Goals the shooting gained (or, below 0, cost): shots on goal against what these chances usually put there."""
        return self.usual_scored_on_goal - (self.worth - self.penalties * PENALTY_VALUE)

    @property
    def beating_the_keeper(self) -> float:
        """Goals gained (or cost) once on goal: how many went in against how many usually do."""
        return self.scored_on_goal - self.usual_scored_on_goal


@dataclass(frozen=True)
class UsualWorth:
    """One side's chances against what they are usually worth for that opponent third and venue.

    The usual is the season diagnosis's own expectation from the other
    matches, and the range is one standard deviation either side of it.
    """

    side: str  # "ours" or "theirs"
    actual: float
    usual: float
    low: float
    high: float

    @property
    def standing(self) -> str:
        if self.actual < self.low:
            return "below"
        return "above" if self.actual > self.high else "usual"

    @property
    def favourable(self) -> bool | None:
        if self.standing == "usual":
            return None
        return (self.standing == "above") == (self.side == "ours")


@dataclass(frozen=True)
class FinishingRecord:
    """Goals against what the chances were worth over your other matches: the team's, or one player's."""

    name: str
    matches: int
    shots: int
    worth: float
    goals: int
    clear_cut: int
    clear_cut_scored: int
    luck_odds: float  # how often luck alone leaves a gap at least this large, this way
    today_worth: float | None = None  # a player's chances in this match
    today_goals: int | None = None

    @property
    def standing(self) -> str:
        """"below" or "above" when the gap is larger than luck usually leaves, else "usual"."""
        if self.luck_odds >= PATTERN_ODDS or not self.shots:
            return "usual"
        return "below" if self.goals < self.worth else "above"


@dataclass(frozen=True)
class ResultVsChances:
    ours: SideChances
    theirs: SideChances
    win: float
    draw: float
    loss: float
    points: int
    expected_points: float
    played: str  # "better", "even" or "worse": who had the better chances
    verdict: str
    tone: str  # "good", "unlucky", "even", "lucky" or "bad"
    summary: str
    explanations: tuple[str, ...]  # why goals and chances parted, side by side
    takeaway: str
    team_finishing: FinishingRecord
    finishers: tuple[FinishingRecord, ...]  # ours who scored well below their chances today
    usual: tuple[UsualWorth, ...]  # empty when the match isn't compared with your usual
    rates: ChanceRates

    @property
    def method(self) -> str:
        rates = self.rates
        return (
            f"Each shot is worth how often shots of its kind were scored in your other {rates.matches} competitive "
            f"matches, both sides counted: {rates.value('clear_cut'):.0%} of clear-cut chances "
            f"({rates.clear_cut.goals} of {rates.clear_cut.shots}) and {rates.value('other'):.0%} of other shots "
            f"({rates.other.goals} of {rates.other.shots}). A penalty is worth {PENALTY_VALUE:g} of a goal, "
            "football's usual rate: FM records only the penalties that were scored, so your history can't measure it. "
            "FM20 shows no expected goals; this uses only what its match screens show."
        )


def _side_chances(
    shots: Sequence[ClassifiedShot], rates: ChanceRates, own_goals: int, names: Mapping[int, str]
) -> SideChances:
    kicks = [shot for shot in shots if shot.kind != "penalty"]
    on_goal = [shot for shot in kicks if shot.on_goal]
    return SideChances(
        shots=len(shots),
        clear_cut=sum(shot.kind != "other" for shot in shots),
        penalties=len(shots) - len(kicks),
        worth=sum(rates.value(shot.kind) for shot in shots),
        goals=sum(shot.goal for shot in shots),
        own_goals=own_goals,
        on_goal=len(on_goal),
        usual_on_goal=sum(rates.on_goal_rate(shot.kind) for shot in kicks),
        scored_on_goal=sum(shot.goal for shot in on_goal),
        usual_scored_on_goal=sum(rates.on_goal_value(shot.kind) for shot in on_goal),
        missed_clear_cut=tuple(
            MissedChance(names.get(shot.player_short_id), shot.clock, shot.heading)
            for shot in shots if shot.kind == "clear_cut" and not shot.goal
        ),
    )


def _explanation(side: SideChances, who: str, keeper: str) -> str | None:
    """Why one side's goals parted from what its chances were worth, when they did by much."""
    gap = side.goals - side.worth
    if abs(gap) < NOTABLE_GAP:
        return None
    shots = side.shots - side.penalties
    text = (
        f"{who} scored {side.goals} from chances worth {side.worth:.1f}. "
        f"{side.on_goal} of {shots} shots{' (penalties aside)' if side.penalties else ''} were on goal, where "
        f"chances like these usually put {side.usual_on_goal:.1f} there, and {side.scored_on_goal} of those went "
        f"in, where {side.usual_scored_on_goal:.1f} usually would. "
    )
    shooting, kept_out = side.shooting, side.beating_the_keeper
    # Split when both parts pull the same way and the smaller is at least half the larger.
    if shooting * kept_out > 0 and min(abs(shooting), abs(kept_out)) >= max(abs(shooting), abs(kept_out)) / 2:
        return text + (
            f"The shortfall was split between shots off target and shots on goal that {keeper} kept out."
            if gap < 0 else "It was split between more shots on target and more of them going in than usual."
        )
    if gap < 0:
        return text + (
            "Most of the shortfall was shots off target." if abs(shooting) >= abs(kept_out)
            else f"Most of the shortfall was shots on goal that {keeper} kept out."
        )
    return text + (
        "Most of it was more shots on target than usual." if abs(shooting) >= abs(kept_out)
        else "Most of it was shots on goal going in more often than usual."
    )


def _names(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _takeaway(played: str, result: str, team: FinishingRecord, finishers: Sequence[FinishingRecord]) -> str:
    """What the verdict means for whether to change anything."""
    if played == "worse":
        if result == "L":
            return "They had the better chances, so this wasn't bad luck: worth a look at the tactic and the selection."
        return (
            "They had the better chances, so the result flattered you: worth a look at how the tactic held up, "
            "even with the points."
        )
    if result == "W":
        return (
            "You made the better chances and took them." if played == "better"
            else "There was little between the sides on chances, so it could have gone either way."
        )
    opening = (
        "The chances were there" if played == "better"
        else "There was little between the sides on chances, so it could have gone either way"
    )
    if team.standing == "below":
        return (
            f"{opening}, but this fits a pattern: over your other {team.matches} matches you've scored "
            f"{team.goals} from chances worth {team.worth:.1f}, a shortfall luck alone leaves "
            f"{one_in(team.luck_odds)}. The finishing, more than the tactic, is what to look at."
        )
    poor = [record.name for record in finishers if record.standing == "below"]
    if poor:
        return (
            f"{opening}. Over your other matches {_names(poor)} {'has' if len(poor) == 1 else 'have'} scored fewer "
            "than their chances were worth, by more than luck usually leaves, so the finishing may matter more "
            "than the tactic."
        )
    if played == "even":
        return f"{opening}."
    return (
        f"{opening}, and over your other {team.matches} matches your goals have been about what your chances "
        "were worth, so this looks like one of those days rather than a reason to change the tactic."
    )


def _finishing_record(
    name: str, shots: Sequence[ClassifiedShot], matches: int, rates: ChanceRates, **today: float | int | None
) -> FinishingRecord:
    return FinishingRecord(
        name=name,
        matches=matches,
        shots=len(shots),
        worth=sum(rates.value(shot.kind) for shot in shots),
        goals=sum(shot.goal for shot in shots),
        clear_cut=sum(shot.kind != "other" for shot in shots),
        clear_cut_scored=sum(shot.kind != "other" and shot.goal for shot in shots),
        luck_odds=luck_odds(shots, rates) if shots else 1.0,
        **today,
    )


def _identities(summary: MatchSummary) -> dict[int, str]:
    """Our players in a match by short ID: FM's unique ID when known, else the name, as the rating checks key them."""
    return {
        player.short_id: player.player_id or player.label
        for player in summary.match.detail.players_for(summary.side)
    }


def _finishers(
    summary: MatchSummary,
    shots: Sequence[ClassifiedShot],
    baseline: Sequence[tuple[MatchSummary, tuple[ClassifiedShot, ...]]],
    rates: ChanceRates,
) -> tuple[FinishingRecord, ...]:
    """Our players who scored well below their chances today (or missed a clear-cut one), with their record."""
    names = {player.short_id: player.label for player in summary.match.detail.players_for(summary.side)}
    identities = _identities(summary)
    today: dict[int, list[ClassifiedShot]] = {}
    for shot in shots:
        if shot.side == summary.side:
            today.setdefault(shot.player_short_id, []).append(shot)
    wanted: list[tuple[float, int]] = []
    for short_id, own in today.items():
        shortfall = sum(rates.value(shot.kind) for shot in own) - sum(shot.goal for shot in own)
        if shortfall >= NOTABLE_GAP or any(shot.kind == "clear_cut" and not shot.goal for shot in own):
            wanted.append((shortfall, short_id))
    wanted.sort(reverse=True)
    records = []
    for _shortfall, short_id in wanted[:MAX_FINISHERS]:
        identity = identities.get(short_id)
        history: list[ClassifiedShot] = []
        matches = 0
        for row, row_shots in baseline:
            players = {
                player.short_id: player for player in row.match.detail.players_for(row.side)
                if (player.player_id or player.label) == identity
            }
            if not any(player.played for player in players.values()):
                continue
            matches += 1
            history += [shot for shot in row_shots if shot.side == row.side and shot.player_short_id in players]
        own = today[short_id]
        records.append(_finishing_record(
            names.get(short_id) or f"Player {short_id}", history, matches, rates,
            today_worth=sum(rates.value(shot.kind) for shot in own), today_goals=sum(shot.goal for shot in own),
        ))
    return tuple(records)


def _usual(
    summary: MatchSummary,
    worth: Mapping[str, float],
    baseline: Sequence[MatchSummary],
    worth_by_match: Mapping[str, Mapping[str, float]],
) -> tuple[UsualWorth, ...]:
    checks = []
    for side in ("ours", "theirs"):
        def value(row: MatchSummary, side: str = side) -> float:
            return worth_by_match[row.match.key][side]

        spread = stdev(value(row) - expected_value(row, baseline, value) for row in baseline)
        centre = expected_value(summary, baseline, value)
        checks.append(UsualWorth(side, worth[side], centre, max(centre - spread, 0.0), centre + spread))
    return tuple(checks)


def judge_chances(
    review: MatchReview, summary: MatchSummary, *, compare_usual: bool
) -> tuple[ResultVsChances | None, str | None]:
    """The match's result against its chances, or None with the reason it can't be judged.

    `review` is the competitive selection the season diagnosis reads; the
    match itself is left out of everything it is judged against. With
    `compare_usual`, its chances are also set against your usual for that
    opponent third and venue.
    """
    match = summary.match
    if match.detail is None:
        return None, "Only the result was found, so there are no shots to judge."
    if match.after_extra_time:
        return None, "It went to extra time, so its chances cover 120 minutes and aren't judged."
    shots = classify_shots(match)
    if shots is None:
        return None, "FM's list of shots for this match is missing or doesn't add up to its stats."
    baseline = []
    for row in eligible_team_summaries(review):
        if row.match.key != match.key:
            row_shots = classify_shots(row.match)
            if row_shots is not None:
                baseline.append((row, row_shots))
    if len(baseline) < MIN_BASELINE_MATCHES:
        return None, (
            f"Judging chances needs {MIN_BASELINE_MATCHES} other competitive matches with every shot recorded; "
            f"there are {len(baseline)}."
        )
    rates = chance_rates([row_shots for _row, row_shots in baseline])
    other = "away" if summary.side == "home" else "home"
    players = match.detail.players
    names = {side: {p.short_id: p.label for p in players if p.side == side} for side in (summary.side, other)}
    ours_shots = [shot for shot in shots if shot.side == summary.side]
    theirs_shots = [shot for shot in shots if shot.side == other]
    ours = _side_chances(ours_shots, rates, own_goals_for(match, summary.side), names[summary.side])
    theirs = _side_chances(theirs_shots, rates, own_goals_for(match, other), names[other])
    win, draw, loss = outcomes(goal_chances(ours_shots, rates), goal_chances(theirs_shots, rates))
    edge = win - loss
    played = "better" if edge >= BETTER_CHANCES else "worse" if edge <= -BETTER_CHANCES else "even"
    verdict, tone = _VERDICTS[(played, summary.result)]
    summary_line = {
        "better": f"You had the better chances, worth {ours.worth:.1f} goals to their {theirs.worth:.1f}.",
        "even": f"Little between the sides: chances worth {ours.worth:.1f} goals to their {theirs.worth:.1f}.",
        "worse": f"They had the better chances, worth {theirs.worth:.1f} goals to your {ours.worth:.1f}.",
    }[played] + f" Chances like these win {win:.0%}, draw {draw:.0%} and lose {loss:.0%} of the time."
    explanations = [
        line for line in (
            _explanation(ours, "You", "their keeper and defenders"),
            _explanation(theirs, "They", "your keeper and defenders"),
        ) if line
    ]
    for side, who in ((ours, "You"), (theirs, "They")):
        if side.own_goals:
            explanations.append(
                f"{who} also had {side.own_goals} own goal{'s' if side.own_goals > 1 else ''}, which no chance accounts for."
            )
    team = _finishing_record(
        "You", [shot for row, row_shots in baseline for shot in row_shots if shot.side == row.side],
        len(baseline), rates,
    )
    finishers = _finishers(summary, shots, baseline, rates)
    usual: tuple[UsualWorth, ...] = ()
    if compare_usual:
        worth_by_match = {
            row.match.key: {
                "ours": sum(rates.value(shot.kind) for shot in row_shots if shot.side == row.side),
                "theirs": sum(rates.value(shot.kind) for shot in row_shots if shot.side != row.side),
            }
            for row, row_shots in baseline
        }
        usual = _usual(
            summary, {"ours": ours.worth, "theirs": theirs.worth}, [row for row, _shots in baseline], worth_by_match
        )
    points = {"W": 3, "D": 1, "L": 0}[summary.result]
    return ResultVsChances(
        ours=ours,
        theirs=theirs,
        win=win,
        draw=draw,
        loss=loss,
        points=points,
        expected_points=3 * win + draw,
        played=played,
        verdict=verdict,
        tone=tone,
        summary=summary_line,
        explanations=tuple(explanations),
        takeaway=_takeaway(played, summary.result, team, finishers),
        team_finishing=team,
        finishers=finishers,
        usual=usual,
        rates=rates,
    ), None
