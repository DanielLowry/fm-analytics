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
    if detail is None:
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


def _window(
    key: str,
    label: str,
    rows: Sequence[MatchSummary],
    season: Sequence[MatchSummary],
) -> DiagnosticWindow:
    metrics = ("shots", "shots_on_target", "clear_cut_chances")
    if not rows:
        empty = {metric: None for metric in metrics}
        return DiagnosticWindow(key, label, 0, None, None, None, empty, empty, None, empty, empty)
    averages_for = {metric: _average(rows, "ours", metric) for metric in metrics}
    averages_against = {metric: _average(rows, "theirs", metric) for metric in metrics}
    adjusted_for = {
        metric: mean(
            float(row.ours[metric]) - _expected(row, season, "ours", metric) for row in rows
        )
        for metric in metrics
    }
    adjusted_against = {
        metric: mean(
            float(row.theirs[metric]) - _expected(row, season, "theirs", metric) for row in rows
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
        if player.played and player.role_code == role.code
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
        key=f"role_output:{role.role_key}",
        problem_class="individual-role output",
        title=f"{role.label} output merits a controlled player test",
        hypothesis=(
            f"The current {role.label} unit may be underperforming, but this does not yet show "
            "that the role itself is wrong."
        ),
        confidence="medium" if role.starts >= 10 else "low",
        evidence=(
            f"{role.starts} starts and {role.minutes} minutes in a manager-confirmed role.",
            f"Average rating {role.average_rating:.2f}; {chance_rate:.2f} chances created and "
            f"{contribution_rate:.2f} goals plus assists per 90.",
        ),
        expected_benefit="Separate a player-selection issue from a role or system issue.",
        intervention=(
            f"Keep the {role.label} role and surrounding tactic fixed; give one alternative player "
            f"{EVALUATION_MATCHES} starts in it."
        ),
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Role-unit rating or chance/contribution output improves without weakening team creation.",
        stop_condition=(
            "Stop or reverse if team chance creation falls, or if the replacement shows no useful "
            "improvement after five eligible starts."
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
        title="Recent chance creation is below its opponent-adjusted baseline",
        hypothesis="The attack may be reaching fewer useful shooting positions, rather than merely finishing poorly.",
        confidence="medium" if recent.matches >= 10 else "low",
        evidence=(
            f"Last {recent.matches}: {shots:.1f} shots and {ccc:.2f} clear-cut chances per match.",
            f"After opponent and venue adjustment: {shots_delta:+.1f} shots and {ccc_delta:+.2f} "
            "clear-cut chances versus expectation.",
        ),
        expected_benefit="Restore shot volume and clear-cut chances without trading away chance prevention.",
        intervention="Change one creative role or duty only; keep mentality, shape and the other roles fixed.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Opponent-adjusted shots or clear-cut chances return to the season baseline.",
        stop_condition="Reverse if creation remains flat after five eligible matches or clear-cut chances conceded rise.",
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
        title="Finishing has fallen while chance supply remains adequate",
        hypothesis=(
            "The recent scoring shortfall may be conversion variance or forward selection, rather "
            "than a reason to make the whole tactic more attacking."
        ),
        confidence="medium" if recent.matches >= 10 else "low",
        evidence=(
            f"Goals per shot: {recent.conversion_pct:.1f}% over the last {recent.matches}, versus "
            f"{season.conversion_pct:.1f}% across the eligible season.",
            f"Opponent-adjusted creation remains {shots_delta:+.1f} shots and {ccc_delta:+.2f} "
            "clear-cut chances versus expectation.",
        ),
        expected_benefit="Recover goals without destabilising a chance-creation process that is still working.",
        intervention="Keep the team tactic fixed and test one forward-selection change for five starts.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Conversion improves while opponent-adjusted shots and clear-cut chances stay at baseline.",
        stop_condition="Stop if chance supply falls, or if conversion does not improve after five eligible matches.",
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
        title="Opponents are getting more high-quality chances than expected",
        hypothesis="The recent defensive issue may be chance quality allowed, not simply unlucky scorelines.",
        confidence="medium" if recent.matches >= 10 else "low",
        evidence=(
            f"Last {recent.matches}: {shots:.1f} shots and {ccc:.2f} clear-cut chances conceded per match.",
            f"Clear-cut chances conceded are {ccc_delta:+.2f} per match above the opponent/venue expectation.",
        ),
        expected_benefit="Reduce clear-cut chances conceded while preserving the existing attacking process.",
        intervention="Change one defensive-transition responsibility only; keep the block, mentality and attack fixed.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Opponent-adjusted clear-cut chances conceded return to baseline with creation unchanged.",
        stop_condition="Reverse if chance prevention does not improve after five matches or attacking creation drops materially.",
        priority=82 + ccc_delta * 20,
    )


def _game_state_opportunity(state: _GameState) -> DiagnosticFinding | None:
    if state.matches < MIN_TEAM_MATCHES or (state.led_not_won < 2 and state.late_conceded <= state.late_scored + 2):
        return None
    return DiagnosticFinding(
        key="game_state_protection",
        problem_class="game-state management",
        title="Protecting leads is a repeatable review point",
        hypothesis=(
            "A small late-game control issue may be costing results; it should be tested separately "
            "from the starting tactic."
        ),
        confidence="medium" if state.matches >= 10 and state.led_not_won >= 3 else "low",
        evidence=(
            f"Led but did not win in {state.led_not_won} of {state.matches} matches with complete goal timing.",
            f"From 76 minutes onward: {state.late_conceded} conceded and {state.late_scored} scored."
            + (f" {state.red_card_matches_excluded} red-card match(es) were excluded." if state.red_card_matches_excluded else ""),
        ),
        expected_benefit="Turn more existing leads into wins without weakening the starting approach.",
        intervention="At the next lead after 70 minutes, test one pre-defined lower-risk game-state change only.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Fewer leads are lost and late clear-cut chances conceded do not worsen.",
        stop_condition="Abandon the change if it suppresses your outlet and increases sustained late pressure over five eligible uses.",
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
        title="Away chance creation trails the home process",
        hypothesis="The away drop may reflect one overly cautious responsibility rather than a need for a separate tactic.",
        confidence="low" if min(home.matches, away.matches) < 10 else "medium",
        evidence=(
            f"Points per game: {away.points_per_game:.2f} away versus {home.points_per_game:.2f} at home.",
            f"Away opponent-adjusted creation: {away_shots:+.1f} shots and {away_ccc:+.2f} clear-cut chances.",
        ),
        expected_benefit="Close the away creation gap without changing the full tactical identity.",
        intervention="In away matches only, test one less-cautious supporting duty while leaving every other setting fixed.",
        evaluation_matches=EVALUATION_MATCHES,
        success_condition="Away opponent-adjusted creation improves without a material increase in clear-cut chances conceded.",
        stop_condition="Reverse after five eligible away matches if creation is unchanged or chance prevention worsens.",
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
            f"Against the next {description} opponents, change one creative support duty only."
            if creation_problem else
            f"Against the next {description} opponents, change one defensive-transition responsibility only."
        )
        candidates.append(DiagnosticFinding(
            key=f"opposition:{key}",
            problem_class="opposition strength",
            title=f"The {description} split shows a process weakness, not just poorer results",
            hypothesis=f"Performance against {description} opponents may have a specific {process} problem.",
            confidence="low" if split.matches < 10 else "medium",
            evidence=(
                f"{split.matches} matches at {split.points_per_game:.2f} points per game, versus "
                f"{season_ppg:.2f} across the eligible season.",
                f"Relative to the season: {shots_gap:+.1f} shots, {ccc_gap:+.2f} clear-cut chances "
                f"created and {prevention_gap:+.2f} clear-cut chances conceded per match.",
            ),
            expected_benefit=f"Improve {process} in this opponent band without changing the base tactic elsewhere.",
            intervention=intervention,
            evaluation_matches=EVALUATION_MATCHES,
            success_condition=f"The {process} gap to the season baseline narrows across five eligible exposures.",
            stop_condition="Stop if the targeted process does not improve or the opposite side of the ball worsens materially.",
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
            "Overall chance creation is adequate; no evidence to make the team more attacking",
            (
                f"Last {recent.matches}: {recent.averages_for['shots']:.1f} shots and "
                f"{recent.averages_for['clear_cut_chances']:.2f} clear-cut chances per match.",
                f"Opponent-adjusted deltas are {adjusted_shots:+.1f} shots and {adjusted_ccc:+.2f} clear-cut chances.",
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
            "The attacking approach against bottom-third opponents is producing chances",
            (
                f"Across {bottom.matches} matches: {bottom.averages_for['shots']:.1f} shots and "
                f"{bottom.averages_for['clear_cut_chances']:.2f} clear-cut chances per match.",
                f"Only {bottom.averages_against['clear_cut_chances']:.2f} clear-cut chances conceded per match.",
            ),
        ))
    af = next(
        (role for role in review.roles if role.confirmed and role.role_key == "af_attack" and role.starts >= MIN_ROLE_STARTS),
        None,
    )
    if af is not None and ((af.per_90(af.goals) or 0) >= 0.35 or (af.average_rating or 0) >= 7.0):
        items.append(DiagnosticAssurance(
            "advanced_forward",
            f"{af.label} is producing; no evidence to change it",
            (
                f"{af.starts} starts, {af.minutes} minutes and {af.goals} goals.",
                f"{(af.per_90(af.goals) or 0):.2f} goals per 90; average rating "
                f"{af.average_rating:.2f}." if af.average_rating is not None else f"{(af.per_90(af.goals) or 0):.2f} goals per 90.",
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
            "Chance prevention is sound; no evidence for a broader defensive change",
            (
                f"Eligible-season clear-cut chances conceded: {season.averages_against['clear_cut_chances']:.2f} per match.",
                f"The recent opponent-adjusted delta is {recent_ccc:+.2f} per match.",
            ),
        ))
    return tuple(items[:4])


def diagnose_matches(review: MatchReview) -> MatchDiagnostics:
    """Build explainable, evidence-gated diagnostics for one selected review."""
    full = [summary for summary in review.matches if summary.match.detail is not None]
    eligible = sorted((summary for summary in review.matches if _valid_team_stats(summary)), key=lambda row: row.match.date)
    unconfirmed = sum(item.appearances for item in review.unconfirmed_roles)
    issues: list[DiagnosticIssue] = []
    if len(eligible) < MIN_TEAM_MATCHES:
        issues.append(DiagnosticIssue(
            "team_sample_too_small",
            f"Only {len(eligible)} eligible full-stat matches; team findings need {MIN_TEAM_MATCHES}.",
            ("team findings",),
        ))
    if len(full) != len(eligible):
        issues.append(DiagnosticIssue(
            "invalid_or_incomplete_team_stats",
            f"{len(full) - len(eligible)} full-stat match(es) lack a valid shots/on-target/clear-cut-chances panel.",
            ("those matches",),
        ))
    if len(eligible) < MIN_BASELINE_MATCHES:
        issues.append(DiagnosticIssue(
            "baseline_sample_weak",
            f"Fewer than {MIN_BASELINE_MATCHES} eligible matches; any trend is weak evidence.",
        ))
    if unconfirmed:
        issues.append(DiagnosticIssue(
            "unconfirmed_role_mapping",
            f"{unconfirmed} player appearance(s) use an unconfirmed FM role code; those roles cannot be recommended.",
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
    if eligible:
        season = _window("season", "Eligible season", eligible, eligible)
        last_ten = _window("last10", "Last 10", eligible[-10:], eligible)
        last_five = _window("last5", "Last 5", eligible[-5:], eligible)
        windows = (season, last_ten, last_five)
        split_rows = {
            key: [summary for summary in eligible if _band_key(summary) == key]
            for key in _TABLE_BAND_LABELS
        }
        opponent_splits = tuple(
            _window(f"opponent:{key}", _TABLE_BAND_LABELS[key], rows, eligible)
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
            _window("home", "Home", home_rows, eligible) if home_rows else None,
            _window("away", "Away", away_rows, eligible) if away_rows else None,
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
            "Set-piece diagnosis",
            "FM corners and penalties are captured, but goal situation (open play, corner, free kick) is not; "
            "that is insufficient evidence for a set-piece recommendation.",
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
