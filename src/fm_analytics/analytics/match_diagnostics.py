"""Evidence-gated hypotheses from the match review.

The review describes what happened.  This module asks the narrower question
"where is the strongest evidence of an exploitable weakness?".  Its rules are
deliberately small and inspectable: no finding is emitted from fewer than five
valid full-stat matches, opponent adjustment uses only the table band known at
kickoff and venue, and an individual-role finding needs five starts in a role
whose FM code has been confirmed by the manager.

Findings are hypotheses, never instructions.  Each proposes one controlled
test and says how long to run it, what improvement would support it, and when
to stop.  Persisting and automatically evaluating those tests is a separate
workflow; the fields are part of the contract now so that workflow can be
added without changing the diagnostic output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Mapping, Sequence

from fm_analytics.analytics.match_analysis import MatchReview, MatchSummary
from fm_analytics.analytics.match_roles import RoleSummary

DIAGNOSTIC_VERSION = 1
MIN_TEAM_MATCHES = 5
MIN_BASELINE_MATCHES = 10
MIN_ROLE_STARTS = 5
MIN_ROLE_MINUTES = 450
EVALUATION_MATCHES = 5
CORE_TEAM_STATS = ("shots", "shots_on_target", "clear_cut_chances")
_ADJUSTMENT_SHRINKAGE = 3
_TABLE_BAND_LABELS = {
    "top": "Top third",
    "middle": "Middle third",
    "bottom": "Bottom third",
    "early": "Early season",
    "outside": "Not in our league",
}


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


@dataclass(frozen=True)
class DiagnosticIssue:
    code: str
    message: str
    blocks: tuple[str, ...] = ()

    def to_document(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "blocks": list(self.blocks)}


@dataclass(frozen=True)
class DiagnosticQuality:
    selected_matches: int
    full_stat_matches: int
    eligible_team_matches: int
    timed_goal_matches: int
    unconfirmed_role_appearances: int
    team_findings_allowed: bool
    issues: tuple[DiagnosticIssue, ...] = ()

    def to_document(self) -> dict[str, Any]:
        return {
            "selected_matches": self.selected_matches,
            "full_stat_matches": self.full_stat_matches,
            "eligible_team_matches": self.eligible_team_matches,
            "timed_goal_matches": self.timed_goal_matches,
            "unconfirmed_role_appearances": self.unconfirmed_role_appearances,
            "team_findings_allowed": self.team_findings_allowed,
            "issues": [issue.to_document() for issue in self.issues],
        }


@dataclass(frozen=True)
class DiagnosticWindow:
    key: str
    label: str
    matches: int
    points_per_game: float | None
    goals_for_per_match: float | None
    goals_against_per_match: float | None
    averages_for: Mapping[str, float | None]
    averages_against: Mapping[str, float | None]
    conversion_pct: float | None
    opponent_adjusted_for: Mapping[str, float | None] = field(default_factory=dict)
    opponent_adjusted_against: Mapping[str, float | None] = field(default_factory=dict)

    def to_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "matches": self.matches,
            "points_per_game": _round(self.points_per_game),
            "goals_for_per_match": _round(self.goals_for_per_match),
            "goals_against_per_match": _round(self.goals_against_per_match),
            "averages_for": {key: _round(value) for key, value in self.averages_for.items()},
            "averages_against": {key: _round(value) for key, value in self.averages_against.items()},
            "conversion_pct": _round(self.conversion_pct, 1),
            "opponent_adjusted_for": {
                key: _round(value) for key, value in self.opponent_adjusted_for.items()
            },
            "opponent_adjusted_against": {
                key: _round(value) for key, value in self.opponent_adjusted_against.items()
            },
        }


@dataclass(frozen=True)
class DiagnosticFinding:
    key: str
    problem_class: str
    title: str
    hypothesis: str
    confidence: str
    evidence: tuple[str, ...]
    expected_benefit: str
    intervention: str
    evaluation_matches: int
    success_condition: str
    stop_condition: str
    priority: float = field(repr=False, compare=False)

    def to_document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "problem_class": self.problem_class,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "expected_benefit": self.expected_benefit,
            "controlled_intervention": self.intervention,
            "evaluation_matches": self.evaluation_matches,
            "success_condition": self.success_condition,
            "stop_condition": self.stop_condition,
        }


@dataclass(frozen=True)
class DiagnosticAssurance:
    key: str
    title: str
    evidence: tuple[str, ...]

    def to_document(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class UnavailableDiagnostic:
    key: str
    title: str
    reason: str

    def to_document(self) -> dict[str, str]:
        return {"key": self.key, "title": self.title, "reason": self.reason}


@dataclass(frozen=True)
class MatchDiagnostics:
    quality: DiagnosticQuality
    windows: tuple[DiagnosticWindow, ...]
    opponent_splits: tuple[DiagnosticWindow, ...]
    opportunities: tuple[DiagnosticFinding, ...]
    do_not_change: tuple[DiagnosticAssurance, ...]
    unavailable: tuple[UnavailableDiagnostic, ...]
    version: int = DIAGNOSTIC_VERSION

    def to_document(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "quality": self.quality.to_document(),
            "windows": [window.to_document() for window in self.windows],
            "opponent_splits": [split.to_document() for split in self.opponent_splits],
            "top_opportunities": [finding.to_document() for finding in self.opportunities],
            "do_not_change": [item.to_document() for item in self.do_not_change],
            "unavailable": [item.to_document() for item in self.unavailable],
            "method": {
                "minimum_team_matches": MIN_TEAM_MATCHES,
                "minimum_role_starts": MIN_ROLE_STARTS,
                "evaluation_matches": EVALUATION_MATCHES,
                "opponent_adjustment": (
                    "Residual from the selected-season average after partially pooling the "
                    "opponent's table third at kickoff and venue toward that average."
                ),
            },
        }


def _valid_team_stats(summary: MatchSummary) -> bool:
    detail = summary.match.detail
    # FM's panel includes extra time in the totals.  Comparing that 120-minute
    # sample with ordinary 90-minute matches would manufacture an improvement.
    if detail is None or summary.match.after_extra_time:
        return False
    for side in (summary.side, "away" if summary.side == "home" else "home"):
        panel = detail.team(side)
        if any(key not in panel for key in CORE_TEAM_STATS):
            return False
        shots = panel["shots"]
        on_target = panel["shots_on_target"]
        clear_cut = panel["clear_cut_chances"]
        if min(shots, on_target, clear_cut) < 0 or on_target > shots or clear_cut > shots:
            return False
    return True


def eligible_team_summaries(review: MatchReview) -> tuple[MatchSummary, ...]:
    """Chronological matches whose core panels can safely support a finding."""
    return tuple(sorted(
        (summary for summary in review.matches if _valid_team_stats(summary)),
        key=lambda row: (row.match.date, row.match.key),
    ))


def _average(rows: Sequence[MatchSummary], side: str, metric: str) -> float | None:
    values = [getattr(row, side)[metric] for row in rows if getattr(row, side) is not None]
    values = [float(value) for value in values if value is not None]
    return mean(values) if values else None


def _points(summary: MatchSummary) -> int:
    return 3 if summary.result == "W" else 1 if summary.result == "D" else 0


def _band_key(summary: MatchSummary) -> str:
    return summary.strength.band("table").key


def _expected(
    row: MatchSummary,
    season: Sequence[MatchSummary],
    side: str,
    metric: str,
) -> float:
    values = [float(getattr(item, side)[metric]) for item in season]
    overall = mean(values)
    band_rows = [item for item in season if _band_key(item) == _band_key(row)]
    venue_rows = [item for item in season if item.side == row.side]

    def contribution(group: Sequence[MatchSummary]) -> float:
        weight = len(group) / (len(group) + _ADJUSTMENT_SHRINKAGE)
        group_mean = mean(float(getattr(item, side)[metric]) for item in group)
        return weight * (group_mean - overall)

    return overall + contribution(band_rows) + contribution(venue_rows)


class _Expectations:
    """`_expected` against one season, worked out once for each opposition band, venue, side and metric.

    A row's expectation depends on nothing else, and every window of a
    diagnosis asks it of the same season for each of its rows.
    """

    def __init__(self, season: Sequence[MatchSummary]):
        self.season = season
        self._known: dict[tuple[str, str, str, str], float] = {}

    def __call__(self, row: MatchSummary, side: str, metric: str) -> float:
        key = (_band_key(row), row.side, side, metric)
        if key not in self._known:
            self._known[key] = _expected(row, self.season, side, metric)
        return self._known[key]


def _window(
    key: str,
    label: str,
    rows: Sequence[MatchSummary],
    season: Sequence[MatchSummary],
    expected: _Expectations | None = None,
) -> DiagnosticWindow:
    metrics = ("shots", "shots_on_target", "clear_cut_chances")
    if not rows:
        empty = {metric: None for metric in metrics}
        return DiagnosticWindow(key, label, 0, None, None, None, empty, empty, None, empty, empty)
    expected = expected or _Expectations(season)
    averages_for = {metric: _average(rows, "ours", metric) for metric in metrics}
    averages_against = {metric: _average(rows, "theirs", metric) for metric in metrics}
    adjusted_for = {
        metric: mean(
            float(row.ours[metric]) - expected(row, "ours", metric) for row in rows
        )
        for metric in metrics
    }
    adjusted_against = {
        metric: mean(
            float(row.theirs[metric]) - expected(row, "theirs", metric) for row in rows
        )
        for metric in metrics
    }
    shots = sum(float(row.ours["shots"]) for row in rows)
    goals = sum(row.goals_for for row in rows)
    return DiagnosticWindow(
        key=key,
        label=label,
        matches=len(rows),
        points_per_game=mean(_points(row) for row in rows),
        goals_for_per_match=mean(row.goals_for for row in rows),
        goals_against_per_match=mean(row.goals_against for row in rows),
        averages_for=averages_for,
        averages_against=averages_against,
        conversion_pct=100 * goals / shots if shots else None,
        opponent_adjusted_for=adjusted_for,
        opponent_adjusted_against=adjusted_against,
    )


def diagnostic_window(
    key: str,
    label: str,
    rows: Sequence[MatchSummary],
    season: Sequence[MatchSummary],
) -> DiagnosticWindow:
    """Public window builder used when evaluating a controlled intervention."""
    return _window(key, label, rows, season)


def _complete_goal_sequence(summary: MatchSummary) -> tuple[tuple[int, str], ...] | None:
    match = summary.match
    goals = [incident for incident in match.incidents if incident.is_goal]
    total = summary.goals_for + summary.goals_against
    if len(goals) == total:
        return tuple((goal.minute, goal.side) for goal in goals)
    if match.detail is not None:
        events = [event for event in match.detail.events if event.kind == "goal"]
        if len(events) == total:
            return tuple((event.minute, event.side) for event in events)
    return None


@dataclass(frozen=True)
class _GameState:
    matches: int
    led_not_won: int
    late_scored: int
    late_conceded: int
    red_card_matches_excluded: int


def _game_state(rows: Sequence[MatchSummary]) -> _GameState:
    covered = led_not_won = late_scored = late_conceded = excluded = 0
    for row in rows:
        if row.match.after_extra_time:
            continue
        if any(incident.kind == "sent_off" for incident in row.match.incidents):
            excluded += 1
            continue
        sequence = _complete_goal_sequence(row)
        if sequence is None:
            continue
        covered += 1
        ours = theirs = 0
        led = False
        for minute, side in sequence:
            if side == row.side:
                ours += 1
                late_scored += int(minute >= 76)
            else:
                theirs += 1
                late_conceded += int(minute >= 76)
            led = led or ours > theirs
        led_not_won += int(led and row.result != "W")
    return _GameState(covered, led_not_won, late_scored, late_conceded, excluded)


def _role_stats_complete(review: MatchReview, role: RoleSummary) -> bool:
    required = {"goals", "assists", "shots", "key_passes", "chances_created"}
    appearances = [
        player
        for summary in review.matches
        if summary.match.detail is not None
        for player in summary.match.detail.players_for(summary.side)
        if player.played
        and review.appearance_roles.get((summary.match.key, player.side, player.short_id)) == role.label
    ]
    return bool(appearances) and all(required.issubset(player.stats) for player in appearances)


def _role_opportunity(review: MatchReview) -> DiagnosticFinding | None:
    candidates = [
        role for role in review.roles
        if role.confirmed
        and role.role_key != "gk_defend"
        and role.starts >= MIN_ROLE_STARTS
        and role.minutes >= MIN_ROLE_MINUTES
        and role.average_rating is not None
        and role.average_rating < 6.70
        and _role_stats_complete(review, role)
    ]
    if not candidates:
        return None
    role = min(candidates, key=lambda item: (item.average_rating or 10, -item.starts))
    chance_rate = role.per_90(role.chances_created) or 0
    contribution_rate = role.per_90(role.goals + role.assists) or 0
    return DiagnosticFinding(
        key=f"role_output:{role.role_key or role.label}",
        problem_class="individual-role output",
        title=f"{role.label} is under-producing",
        hypothesis="It may be the player rather than the role; another player in the same job tells you which.",
        confidence="medium" if role.starts >= 10 else "low",
        evidence=(
            f"Average rating {role.average_rating:.2f} over {role.starts} starts",
            f"Per 90: {chance_rate:.2f} chances created, {contribution_rate:.2f} goals + assists",
        ),
        expected_benefit="Tells a player problem apart from a role or system problem.",
        intervention=f"Give another player {EVALUATION_MATCHES} starts in this role; change nothing else.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="The role's rating or chances created go up, and the team creates no less.",
        stop_condition=(
            f"The team creates less, or nothing improves after {EVALUATION_MATCHES} starts."
        ),
        priority=70 + (6.70 - (role.average_rating or 6.70)) * 100,
    )


def _creation_opportunity(season: DiagnosticWindow, recent: DiagnosticWindow) -> DiagnosticFinding | None:
    shots_delta = recent.opponent_adjusted_for.get("shots")
    ccc_delta = recent.opponent_adjusted_for.get("clear_cut_chances")
    if recent.matches < MIN_TEAM_MATCHES or shots_delta is None or ccc_delta is None:
        return None
    shots = recent.averages_for["shots"] or 0
    ccc = recent.averages_for["clear_cut_chances"] or 0
    if not ((shots_delta <= -1.5 and ccc_delta <= -0.30) or (shots < 8 and ccc < 0.8)):
        return None
    return DiagnosticFinding(
        key="chance_creation_recent",
        problem_class="chance creation",
        title="Creating fewer chances lately",
        hypothesis="The attack may be reaching fewer good shooting positions, not just finishing badly.",
        confidence="medium" if recent.matches >= 10 else "low",
        evidence=(
            f"Last {recent.matches}: {shots:.1f} shots, {ccc:.2f} clear-cut chances a match",
            f"{shots_delta:+.1f} shots, {ccc_delta:+.2f} clear-cut chances vs expected",
        ),
        expected_benefit="More shots and clear-cut chances without conceding more.",
        intervention="Change one creative role or duty; keep mentality, shape and the other roles.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Shots or clear-cut chances get back to expected.",
        stop_condition=(
            f"Creation hasn't improved after {EVALUATION_MATCHES} matches, "
            "or you concede more clear-cut chances."
        ),
        priority=85 + max(-shots_delta - 1.5, 0) * 4 + max(-ccc_delta - 0.3, 0) * 15,
    )


def _finishing_opportunity(season: DiagnosticWindow, recent: DiagnosticWindow) -> DiagnosticFinding | None:
    if recent.matches < MIN_TEAM_MATCHES or season.conversion_pct is None or recent.conversion_pct is None:
        return None
    shots_delta = recent.opponent_adjusted_for.get("shots")
    ccc_delta = recent.opponent_adjusted_for.get("clear_cut_chances")
    if shots_delta is None or ccc_delta is None:
        return None
    drop = season.conversion_pct - recent.conversion_pct
    creation_adequate = shots_delta >= -1.0 and ccc_delta >= -0.25
    if drop < 2.5 or not creation_adequate:
        return None
    return DiagnosticFinding(
        key="finishing_recent",
        problem_class="finishing",
        title="Scoring less from the same chances",
        hypothesis=(
            "Could be bad luck or the forwards picked; not a reason to make the whole tactic more attacking."
        ),
        confidence="medium" if recent.matches >= 10 else "low",
        evidence=(
            f"Goals per shot: {recent.conversion_pct:.1f}% in the last {recent.matches}, "
            f"{season.conversion_pct:.1f}% overall",
            f"Chances still there: {shots_delta:+.1f} shots, {ccc_delta:+.2f} clear-cut chances vs expected",
        ),
        expected_benefit="More goals without disturbing chance creation that still works.",
        intervention=f"Keep the tactic; try one change of forward for {EVALUATION_MATCHES} starts.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Goals per shot go up while shots and clear-cut chances hold.",
        stop_condition=(
            f"Chances dry up, or goals per shot hasn't improved after {EVALUATION_MATCHES} matches."
        ),
        priority=80 + drop,
    )


def _prevention_opportunity(recent: DiagnosticWindow) -> DiagnosticFinding | None:
    ccc_delta = recent.opponent_adjusted_against.get("clear_cut_chances")
    if recent.matches < MIN_TEAM_MATCHES or ccc_delta is None:
        return None
    ccc = recent.averages_against["clear_cut_chances"] or 0
    shots = recent.averages_against["shots"] or 0
    if ccc < 1.25 or ccc_delta < 0.30:
        return None
    return DiagnosticFinding(
        key="chance_prevention_recent",
        problem_class="chance prevention",
        title="Conceding more clear-cut chances than expected",
        hypothesis="The problem is the quality of chances allowed, not just unlucky scorelines.",
        confidence="medium" if recent.matches >= 10 else "low",
        evidence=(
            f"Last {recent.matches}: {shots:.1f} shots, {ccc:.2f} clear-cut chances conceded a match",
            f"{ccc_delta:+.2f} clear-cut chances conceded a match vs expected",
        ),
        expected_benefit="Fewer clear-cut chances conceded, attack unchanged.",
        intervention="Change one player's job when the ball is lost; keep the block, mentality and attack.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Clear-cut chances conceded get back to expected, and creation holds.",
        stop_condition=(
            f"Nothing improves after {EVALUATION_MATCHES} matches, or you create clearly less."
        ),
        priority=82 + ccc_delta * 20,
    )


def _game_state_opportunity(state: _GameState) -> DiagnosticFinding | None:
    if state.matches < MIN_TEAM_MATCHES or (state.led_not_won < 2 and state.late_conceded <= state.late_scored + 2):
        return None
    return DiagnosticFinding(
        key="game_state_protection",
        problem_class="game-state management",
        title="Leads are slipping",
        hypothesis=(
            "Late-game control may be costing results; test it apart from the starting tactic. "
            f"Counts the {state.matches} matches whose goal times are known"
            + (f", leaving out {state.red_card_matches_excluded} with a red card." if state.red_card_matches_excluded else ".")
        ),
        confidence="medium" if state.matches >= 10 and state.led_not_won >= 3 else "low",
        evidence=(
            f"Led but didn't win {state.led_not_won} of {state.matches} matches",
            f"From 76′: {state.late_conceded} conceded, {state.late_scored} scored",
        ),
        expected_benefit="Turn more leads into wins without changing how you start.",
        intervention="Next time you lead after 70′, make one planned, lower-risk change.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Fewer leads lost, without conceding more late clear-cut chances.",
        stop_condition=(
            f"You lose your outlet and come under more late pressure over {EVALUATION_MATCHES} uses."
        ),
        priority=75 + state.led_not_won * 5 + max(state.late_conceded - state.late_scored, 0) * 2,
    )


def _venue_opportunity(
    home: DiagnosticWindow | None, away: DiagnosticWindow | None
) -> DiagnosticFinding | None:
    if home is None or away is None or min(home.matches, away.matches) < MIN_TEAM_MATCHES:
        return None
    if home.points_per_game is None or away.points_per_game is None:
        return None
    gap = home.points_per_game - away.points_per_game
    away_shots = away.opponent_adjusted_for.get("shots")
    away_ccc = away.opponent_adjusted_for.get("clear_cut_chances")
    if gap < 0.60 or away_shots is None or away_ccc is None or (away_shots > -1 and away_ccc > -0.25):
        return None
    return DiagnosticFinding(
        key="away_performance",
        problem_class="home/away",
        title="Creating less away than at home",
        hypothesis="One over-cautious job away may explain it; you may not need a separate away tactic.",
        confidence="low" if min(home.matches, away.matches) < 10 else "medium",
        evidence=(
            f"Points a game: {away.points_per_game:.2f} away, {home.points_per_game:.2f} at home",
            f"Away: {away_shots:+.1f} shots, {away_ccc:+.2f} clear-cut chances vs expected",
        ),
        expected_benefit="Close the away gap without changing the tactic.",
        intervention="Away only: make one supporting duty less cautious; change nothing else.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Away chances improve without conceding more clear-cut chances.",
        stop_condition=(
            f"Away creation hasn't improved after {EVALUATION_MATCHES} away matches, or you concede more."
        ),
        priority=65 + gap * 10,
    )


def _opposition_opportunity(
    season: DiagnosticWindow,
    splits: Mapping[str, DiagnosticWindow],
) -> DiagnosticFinding | None:
    """Surface a strength split only when the underlying chance process also moves.

    A poor record alone is not actionable.  This prevents five awkward results
    against a table third from becoming a recommendation when shots and chance
    quality are still normal.
    """
    candidates: list[DiagnosticFinding] = []
    season_ppg = season.points_per_game or 0
    for key, description in (("top", "top-third"), ("bottom", "bottom-third")):
        split = splits.get(key)
        if split is None or split.matches < MIN_TEAM_MATCHES or split.points_per_game is None:
            continue
        ppg_gap = season_ppg - split.points_per_game
        shots_gap = (split.averages_for["shots"] or 0) - (season.averages_for["shots"] or 0)
        ccc_gap = (
            (split.averages_for["clear_cut_chances"] or 0)
            - (season.averages_for["clear_cut_chances"] or 0)
        )
        prevention_gap = (
            (split.averages_against["clear_cut_chances"] or 0)
            - (season.averages_against["clear_cut_chances"] or 0)
        )
        creation_problem = shots_gap <= -1.25 and ccc_gap <= -0.25
        prevention_problem = prevention_gap >= 0.35
        if ppg_gap < 0.60 or not (creation_problem or prevention_problem):
            continue
        process = "chance creation" if creation_problem else "chance prevention"
        intervention = (
            f"Against the next {description} teams, change one creative support duty only."
            if creation_problem else
            f"Against the next {description} teams, change one player's job when the ball is lost."
        )
        candidates.append(DiagnosticFinding(
            key=f"opposition:{key}",
            problem_class="opposition strength",
            title=f"{process.capitalize()} drops against {description} teams",
            hypothesis=f"A specific {process} problem against these teams, not just worse results.",
            confidence="low" if split.matches < 10 else "medium",
            evidence=(
                f"{split.matches} matches at {split.points_per_game:.2f} points a game "
                f"({season_ppg:.2f} overall)",
                f"Vs your average: {shots_gap:+.1f} shots, {ccc_gap:+.2f} clear-cut chances created, "
                f"{prevention_gap:+.2f} conceded a match",
            ),
            expected_benefit=f"Better {process} against these teams, with the tactic unchanged elsewhere.",
            intervention=intervention,
            evaluation_matches=EVALUATION_MATCHES,
            success_condition=f"The {process} gap to your average narrows over {EVALUATION_MATCHES} matches.",
            stop_condition="It doesn't improve, or the other side of the game gets clearly worse.",
            priority=68 + ppg_gap * 8 + max(-ccc_gap, prevention_gap, 0) * 10,
        ))
    return max(candidates, key=lambda finding: finding.priority) if candidates else None


def _assurances(
    review: MatchReview,
    season: DiagnosticWindow,
    recent: DiagnosticWindow,
    splits: Mapping[str, DiagnosticWindow],
) -> tuple[DiagnosticAssurance, ...]:
    items: list[DiagnosticAssurance] = []
    adjusted_shots = recent.opponent_adjusted_for.get("shots")
    adjusted_ccc = recent.opponent_adjusted_for.get("clear_cut_chances")
    if (
        recent.matches >= MIN_TEAM_MATCHES
        and adjusted_shots is not None and adjusted_ccc is not None
        and adjusted_shots >= -1.0 and adjusted_ccc >= -0.25
    ):
        items.append(DiagnosticAssurance(
            "chance_creation",
            "Chance creation",
            (
                f"Last {recent.matches}: {recent.averages_for['shots']:.1f} shots, "
                f"{recent.averages_for['clear_cut_chances']:.2f} clear-cut chances a match",
                f"{adjusted_shots:+.1f} shots, {adjusted_ccc:+.2f} clear-cut vs expected",
            ),
        ))
    bottom = splits.get("bottom")
    if (
        bottom is not None and bottom.matches >= MIN_TEAM_MATCHES
        and (bottom.averages_for["shots"] or 0) >= (season.averages_for["shots"] or 0)
        and (bottom.averages_for["clear_cut_chances"] or 0) >= (season.averages_for["clear_cut_chances"] or 0)
    ):
        items.append(DiagnosticAssurance(
            "weaker_opposition_attack",
            "Attacking bottom-third teams",
            (
                f"{bottom.matches} matches: {bottom.averages_for['shots']:.1f} shots, "
                f"{bottom.averages_for['clear_cut_chances']:.2f} clear-cut chances a match",
                f"{bottom.averages_against['clear_cut_chances']:.2f} clear-cut conceded",
            ),
        ))
    af = next(
        (role for role in review.roles if role.confirmed and role.role_key == "af_attack" and role.starts >= MIN_ROLE_STARTS),
        None,
    )
    if af is not None and ((af.per_90(af.goals) or 0) >= 0.35 or (af.average_rating or 0) >= 7.0):
        items.append(DiagnosticAssurance(
            "advanced_forward",
            af.label,
            (
                f"{af.goals} goals in {af.starts} starts",
                f"{(af.per_90(af.goals) or 0):.2f} goals per 90"
                + (f", average rating {af.average_rating:.2f}" if af.average_rating is not None else ""),
            ),
        ))
    recent_ccc = recent.opponent_adjusted_against.get("clear_cut_chances")
    if (
        season.matches >= MIN_TEAM_MATCHES and recent.matches >= MIN_TEAM_MATCHES
        and (season.averages_against["clear_cut_chances"] or 0) <= 1.0
        and recent_ccc is not None and recent_ccc <= 0.20
    ):
        items.append(DiagnosticAssurance(
            "chance_prevention",
            "Chance prevention",
            (
                f"{season.averages_against['clear_cut_chances']:.2f} clear-cut chances conceded a match",
                f"last {recent.matches}: {recent_ccc:+.2f} vs expected",
            ),
        ))
    return tuple(items[:4])


def diagnose_matches(review: MatchReview) -> MatchDiagnostics:
    """Build explainable, evidence-gated diagnostics for one selected review."""
    full = [summary for summary in review.matches if summary.match.detail is not None]
    eligible = list(eligible_team_summaries(review))
    extra_time = sum(1 for summary in full if summary.match.after_extra_time)
    unconfirmed = sum(item.appearances for item in review.unconfirmed_roles)
    issues: list[DiagnosticIssue] = []
    if len(eligible) < MIN_TEAM_MATCHES:
        issues.append(DiagnosticIssue(
            "team_sample_too_small",
            f"Only {len(eligible)} usable matches; team findings need {MIN_TEAM_MATCHES}.",
            ("team findings",),
        ))
    invalid_panels = len(full) - len(eligible) - extra_time
    if invalid_panels:
        issues.append(DiagnosticIssue(
            "invalid_or_incomplete_team_stats",
            f"{invalid_panels} match(es) with full stats left out: shots or clear-cut chances missing or invalid.",
            ("those matches",),
        ))
    if extra_time:
        issues.append(DiagnosticIssue(
            "extra_time_not_comparable",
            f"{extra_time} extra-time match(es) left out: their stats cover 120 minutes.",
            ("team windows",),
        ))
    if len(eligible) < MIN_BASELINE_MATCHES:
        issues.append(DiagnosticIssue(
            "baseline_sample_weak",
            f"Fewer than {MIN_BASELINE_MATCHES} usable matches, so any trend is weak.",
        ))
    if unconfirmed:
        issues.append(DiagnosticIssue(
            "unconfirmed_role_mapping",
            f"{unconfirmed} appearance(s) have an unconfirmed FM role code, so those roles aren't judged.",
            ("affected role findings",),
        ))

    quality = DiagnosticQuality(
        selected_matches=len(review.matches),
        full_stat_matches=len(full),
        eligible_team_matches=len(eligible),
        timed_goal_matches=review.goals.timed_matches,
        unconfirmed_role_appearances=unconfirmed,
        team_findings_allowed=len(eligible) >= MIN_TEAM_MATCHES,
        issues=tuple(issues),
    )
    expected = _Expectations(eligible)
    if eligible:
        season = _window("season", "Eligible season", eligible, eligible, expected)
        last_ten = _window("last10", "Last 10", eligible[-10:], eligible, expected)
        last_five = _window("last5", "Last 5", eligible[-5:], eligible, expected)
        windows = (season, last_ten, last_five)
        split_rows = {
            key: [summary for summary in eligible if _band_key(summary) == key]
            for key in _TABLE_BAND_LABELS
        }
        opponent_splits = tuple(
            _window(f"opponent:{key}", _TABLE_BAND_LABELS[key], rows, eligible, expected)
            for key, rows in split_rows.items() if rows
        )
    else:
        season = _window("season", "Eligible season", (), ())
        last_ten = _window("last10", "Last 10", (), ())
        last_five = _window("last5", "Last 5", (), ())
        windows = (season, last_ten, last_five)
        opponent_splits = ()

    opportunities: list[DiagnosticFinding] = []
    split_map = {split.key.removeprefix("opponent:"): split for split in opponent_splits}
    if quality.team_findings_allowed:
        for finding in (
            _creation_opportunity(season, last_five),
            _finishing_opportunity(season, last_ten),
            _prevention_opportunity(last_five),
            _game_state_opportunity(_game_state(review.matches)),
            _opposition_opportunity(season, split_map),
        ):
            if finding is not None:
                opportunities.append(finding)
        home_rows = [row for row in eligible if row.side == "home"]
        away_rows = [row for row in eligible if row.side == "away"]
        venue = _venue_opportunity(
            _window("home", "Home", home_rows, eligible, expected) if home_rows else None,
            _window("away", "Away", away_rows, eligible, expected) if away_rows else None,
        )
        if venue is not None:
            opportunities.append(venue)
    role = _role_opportunity(review)
    if role is not None:
        opportunities.append(role)
    opportunities.sort(key=lambda finding: (-finding.priority, finding.key))

    do_not_change = (
        _assurances(review, season, last_five, split_map)
        if quality.team_findings_allowed else ()
    )
    unavailable = (
        UnavailableDiagnostic(
            "set_pieces",
            "Set pieces",
            "how each goal came (open play, corner, free kick) isn't read from FM yet, so there is no "
            "set-piece diagnosis.",
        ),
    )
    return MatchDiagnostics(
        quality=quality,
        windows=windows,
        opponent_splits=opponent_splits,
        opportunities=tuple(opportunities[:3]),
        do_not_change=do_not_change,
        unavailable=unavailable,
    )
