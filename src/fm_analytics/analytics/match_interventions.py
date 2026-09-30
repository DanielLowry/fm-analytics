"""A controlled match intervention and its automatic five-exposure review.

Starting a test freezes the diagnostic hypothesis and a five-match baseline.
The persisted record is deliberately manager-authored: the app never assumes
that a suggested change was made.  Once the manager starts it, subsequent
eligible matches are compared with that baseline.  The result remains a
diagnostic verdict, not an instruction and never a write to Football Manager.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import mean
from typing import Any, Mapping, Sequence

from fm_analytics.analytics.match_analysis import MatchReview, MatchSummary
from fm_analytics.analytics.match_diagnostics import (
    DiagnosticFinding,
    MatchDiagnostics,
    diagnostic_window,
    eligible_team_summaries,
)

INTERVENTION_OUTCOMES = ("adopted", "not_supported", "stopped")
MAX_INTERVENTION_NOTE = 500


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


@dataclass(frozen=True)
class InterventionSnapshot:
    matches: int
    points_per_game: float | None
    conversion_pct: float | None
    shots_for: float | None
    clear_cut_chances_for: float | None
    shots_against: float | None
    clear_cut_chances_against: float | None
    adjusted_shots_for: float | None
    adjusted_clear_cut_chances_for: float | None
    adjusted_clear_cut_chances_against: float | None
    role_average_rating: float | None = None
    role_chances_created_per90: float | None = None
    role_contributions_per90: float | None = None
    led_matches: int = 0
    led_not_won: int = 0
    late_scored: int = 0
    late_conceded: int = 0

    def to_document(self) -> dict[str, Any]:
        return {
            "matches": self.matches,
            "points_per_game": _round(self.points_per_game),
            "conversion_pct": _round(self.conversion_pct, 1),
            "shots_for": _round(self.shots_for),
            "clear_cut_chances_for": _round(self.clear_cut_chances_for),
            "shots_against": _round(self.shots_against),
            "clear_cut_chances_against": _round(self.clear_cut_chances_against),
            "adjusted_shots_for": _round(self.adjusted_shots_for),
            "adjusted_clear_cut_chances_for": _round(self.adjusted_clear_cut_chances_for),
            "adjusted_clear_cut_chances_against": _round(self.adjusted_clear_cut_chances_against),
            "role_average_rating": _round(self.role_average_rating),
            "role_chances_created_per90": _round(self.role_chances_created_per90),
            "role_contributions_per90": _round(self.role_contributions_per90),
            "led_matches": self.led_matches,
            "led_not_won": self.led_not_won,
            "late_scored": self.late_scored,
            "late_conceded": self.late_conceded,
        }

    @classmethod
    def from_document(cls, raw: Mapping[str, Any]) -> InterventionSnapshot:
        def optional(key: str) -> float | None:
            value = raw.get(key)
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        def count(key: str) -> int:
            value = raw.get(key, 0)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

        return cls(
            matches=count("matches"),
            points_per_game=optional("points_per_game"),
            conversion_pct=optional("conversion_pct"),
            shots_for=optional("shots_for"),
            clear_cut_chances_for=optional("clear_cut_chances_for"),
            shots_against=optional("shots_against"),
            clear_cut_chances_against=optional("clear_cut_chances_against"),
            adjusted_shots_for=optional("adjusted_shots_for"),
            adjusted_clear_cut_chances_for=optional("adjusted_clear_cut_chances_for"),
            adjusted_clear_cut_chances_against=optional("adjusted_clear_cut_chances_against"),
            role_average_rating=optional("role_average_rating"),
            role_chances_created_per90=optional("role_chances_created_per90"),
            role_contributions_per90=optional("role_contributions_per90"),
            led_matches=count("led_matches"),
            led_not_won=count("led_not_won"),
            late_scored=count("late_scored"),
            late_conceded=count("late_conceded"),
        )


@dataclass(frozen=True)
class InterventionProposal:
    finding_key: str
    problem_class: str
    title: str
    hypothesis: str
    controlled_intervention: str
    expected_benefit: str
    success_condition: str
    stop_condition: str
    target_matches: int
    started_after_date: date
    started_after_match_key: str
    baseline: InterventionSnapshot
    manager_note: str = ""


@dataclass(frozen=True)
class StoredIntervention:
    id: int
    proposal: InterventionProposal
    started_at: str
    ended_at: str | None = None
    outcome: str | None = None
    outcome_note: str = ""

    @property
    def active(self) -> bool:
        return self.ended_at is None

    def to_document(self) -> dict[str, Any]:
        proposal = self.proposal
        return {
            "id": self.id,
            "finding_key": proposal.finding_key,
            "problem_class": proposal.problem_class,
            "title": proposal.title,
            "hypothesis": proposal.hypothesis,
            "controlled_intervention": proposal.controlled_intervention,
            "expected_benefit": proposal.expected_benefit,
            "success_condition": proposal.success_condition,
            "stop_condition": proposal.stop_condition,
            "target_matches": proposal.target_matches,
            "started_at": self.started_at,
            "started_after_date": proposal.started_after_date.isoformat(),
            "started_after_match_key": proposal.started_after_match_key,
            "baseline": proposal.baseline.to_document(),
            "manager_note": proposal.manager_note,
            "active": self.active,
            "ended_at": self.ended_at,
            "outcome": self.outcome,
            "outcome_note": self.outcome_note,
        }


@dataclass(frozen=True)
class InterventionEvaluation:
    intervention: StoredIntervention
    status: str
    status_label: str
    exposures: int
    target_matches: int
    summary: str
    evidence: tuple[str, ...]
    current: InterventionSnapshot | None

    @property
    def review_due(self) -> bool:
        return self.exposures >= self.target_matches

    def to_document(self) -> dict[str, Any]:
        return self.intervention.to_document() | {
            "evaluation": {
                "status": self.status,
                "status_label": self.status_label,
                "exposures": self.exposures,
                "target_matches": self.target_matches,
                "review_due": self.review_due,
                "summary": self.summary,
                "evidence": list(self.evidence),
                "current": self.current.to_document() if self.current else None,
            }
        }


def validate_intervention_note(note: str) -> str:
    if not isinstance(note, str):
        raise ValueError("an intervention note must be text")
    note = note.strip()
    if len(note) > MAX_INTERVENTION_NOTE:
        raise ValueError(f"an intervention note is limited to {MAX_INTERVENTION_NOTE} characters")
    return note


def _role_key(finding_key: str) -> str | None:
    return finding_key.split(":", 1)[1] if finding_key.startswith("role_output:") else None


def _relevant_rows(
    review: MatchReview,
    finding_key: str,
    *,
    after: tuple[date, str] | None = None,
) -> tuple[MatchSummary, ...]:
    rows = list(eligible_team_summaries(review))
    if after is not None:
        rows = [row for row in rows if (row.match.date, row.match.key) > after]
    if finding_key == "away_performance":
        rows = [row for row in rows if row.side == "away"]
    elif finding_key.startswith("opposition:"):
        band = finding_key.split(":", 1)[1]
        rows = [row for row in rows if row.strength.band("table").key == band]
    role_key = _role_key(finding_key)
    if role_key is not None:
        codes = {role.code for role in review.roles if role.role_key == role_key}
        rows = [
            row for row in rows
            if row.match.detail is not None
            and any(
                player.started and player.played and player.role_code in codes
                for player in row.match.detail.players_for(row.side)
            )
        ]
    if finding_key == "game_state_protection":
        rows = [row for row in rows if _goal_sequence(row) is not None and not any(
            incident.kind == "sent_off" for incident in row.match.incidents
        )]
    return tuple(rows)


def _goal_sequence(row: MatchSummary) -> tuple[tuple[int, str], ...] | None:
    goals = [incident for incident in row.match.incidents if incident.is_goal]
    total = row.goals_for + row.goals_against
    if len(goals) == total:
        return tuple((goal.minute, goal.side) for goal in goals)
    if row.match.detail is not None:
        events = [event for event in row.match.detail.events if event.kind == "goal"]
        if len(events) == total:
            return tuple((event.minute, event.side) for event in events)
    return None


def _state_metrics(rows: Sequence[MatchSummary]) -> tuple[int, int, int, int]:
    led_matches = led_not_won = late_scored = late_conceded = 0
    for row in rows:
        sequence = _goal_sequence(row)
        if sequence is None:
            continue
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
        led_matches += int(led)
        led_not_won += int(led and row.result != "W")
    return led_matches, led_not_won, late_scored, late_conceded


def _snapshot(
    review: MatchReview,
    rows: Sequence[MatchSummary],
    season: Sequence[MatchSummary],
    finding_key: str,
) -> InterventionSnapshot:
    window = diagnostic_window("intervention", "Intervention window", rows, season)
    role_rating = role_chances = role_contributions = None
    role_key = _role_key(finding_key)
    if role_key is not None:
        codes = {role.code for role in review.roles if role.role_key == role_key}
        players = [
            player
            for row in rows if row.match.detail is not None
            for player in row.match.detail.players_for(row.side)
            if player.played and player.role_code in codes
        ]
        ratings = [player.rating for player in players if player.rating is not None]
        minutes = sum(player.minutes for player in players)
        role_rating = mean(ratings) if ratings else None
        if minutes:
            role_chances = 90 * sum(player.stat("chances_created") for player in players) / minutes
            role_contributions = 90 * sum(
                player.stat("goals") + player.stat("assists") for player in players
            ) / minutes
    led, lost, late_for, late_against = _state_metrics(rows)
    return InterventionSnapshot(
        matches=len(rows),
        points_per_game=window.points_per_game,
        conversion_pct=window.conversion_pct,
        shots_for=window.averages_for.get("shots"),
        clear_cut_chances_for=window.averages_for.get("clear_cut_chances"),
        shots_against=window.averages_against.get("shots"),
        clear_cut_chances_against=window.averages_against.get("clear_cut_chances"),
        adjusted_shots_for=window.opponent_adjusted_for.get("shots"),
        adjusted_clear_cut_chances_for=window.opponent_adjusted_for.get("clear_cut_chances"),
        adjusted_clear_cut_chances_against=window.opponent_adjusted_against.get("clear_cut_chances"),
        role_average_rating=role_rating,
        role_chances_created_per90=role_chances,
        role_contributions_per90=role_contributions,
        led_matches=led,
        led_not_won=lost,
        late_scored=late_for,
        late_conceded=late_against,
    )


def propose_intervention(
    review: MatchReview,
    diagnostics: MatchDiagnostics,
    finding_key: str,
    *,
    manager_note: str = "",
) -> InterventionProposal:
    finding = next((item for item in diagnostics.opportunities if item.key == finding_key), None)
    if finding is None:
        raise ValueError("that opportunity is no longer current; refresh the Matches page")
    if not review.matches:
        raise ValueError("an intervention needs at least one recorded match")
    relevant = _relevant_rows(review, finding.key)
    if len(relevant) < finding.evaluation_matches:
        raise ValueError("that opportunity does not have a complete baseline window")
    season = eligible_team_summaries(review)
    latest = max(review.matches, key=lambda row: (row.match.date, row.match.key))
    return InterventionProposal(
        finding_key=finding.key,
        problem_class=finding.problem_class,
        title=finding.title,
        hypothesis=finding.hypothesis,
        controlled_intervention=finding.intervention,
        expected_benefit=finding.expected_benefit,
        success_condition=finding.success_condition,
        stop_condition=finding.stop_condition,
        target_matches=finding.evaluation_matches,
        started_after_date=latest.match.date,
        started_after_match_key=latest.match.key,
        baseline=_snapshot(review, relevant[-finding.evaluation_matches:], season, finding.key),
        manager_note=validate_intervention_note(manager_note),
    )


def _change(current: float | None, baseline: float | None) -> float | None:
    return current - baseline if current is not None and baseline is not None else None


def _number(value: float | None, places: int = 1) -> str:
    return "unknown" if value is None else f"{value:.{places}f}"


def _team_evidence(baseline: InterventionSnapshot, current: InterventionSnapshot) -> tuple[str, ...]:
    return (
        f"Shots: {_number(baseline.shots_for)} → {_number(current.shots_for)} per match; clear-cut chances: "
        f"{_number(baseline.clear_cut_chances_for, 2)} → {_number(current.clear_cut_chances_for, 2)}.",
        f"Clear-cut chances conceded: {_number(baseline.clear_cut_chances_against, 2)} → "
        f"{_number(current.clear_cut_chances_against, 2)} per match.",
    )


def _verdict(
    intervention: StoredIntervention,
    current: InterventionSnapshot,
) -> tuple[str, str, str, tuple[str, ...]]:
    baseline = intervention.proposal.baseline
    key = intervention.proposal.finding_key
    shots = _change(current.adjusted_shots_for, baseline.adjusted_shots_for)
    creation = _change(
        current.adjusted_clear_cut_chances_for,
        baseline.adjusted_clear_cut_chances_for,
    )
    prevention = _change(
        current.adjusted_clear_cut_chances_against,
        baseline.adjusted_clear_cut_chances_against,
    )
    guardrail_failed = (shots is not None and shots <= -1.25) or (creation is not None and creation <= -0.30)

    if key == "finishing_recent":
        conversion = _change(current.conversion_pct, baseline.conversion_pct)
        evidence = (
            f"Goals per shot: {_number(baseline.conversion_pct)}% → {_number(current.conversion_pct)}%.",
            *_team_evidence(baseline, current),
        )
        if guardrail_failed:
            return "stop", "Stop condition reached", "Conversion cannot justify a material fall in chance supply.", evidence
        if conversion is not None and conversion >= 2.0:
            return "supported", "Promising", "Conversion improved while the chance-supply guardrail held.", evidence
        return "not_supported", "Not supported yet", "Five matches did not produce a meaningful conversion improvement.", evidence

    if key == "chance_creation_recent" or key == "away_performance" or key.startswith("opposition:"):
        evidence = _team_evidence(baseline, current)
        if prevention is not None and prevention >= 0.30:
            return "stop", "Stop condition reached", "Chance creation was bought with too large a rise in chances conceded.", evidence
        if (shots is not None and shots >= 1.0) or (creation is not None and creation >= 0.25):
            return "supported", "Promising", "Opponent-adjusted chance creation improved and the defensive guardrail held.", evidence
        return "not_supported", "Not supported yet", "Five eligible matches did not materially improve chance creation.", evidence

    if key == "chance_prevention_recent":
        evidence = _team_evidence(baseline, current)
        if guardrail_failed:
            return "stop", "Stop condition reached", "The defensive test materially weakened chance creation.", evidence
        if prevention is not None and prevention <= -0.25:
            return "supported", "Promising", "Opponent-adjusted clear-cut chances conceded improved.", evidence
        return "not_supported", "Not supported yet", "Five matches did not materially improve chance prevention.", evidence

    if key.startswith("role_output:"):
        rating = _change(current.role_average_rating, baseline.role_average_rating)
        chances = _change(current.role_chances_created_per90, baseline.role_chances_created_per90)
        contributions = _change(current.role_contributions_per90, baseline.role_contributions_per90)
        evidence = (
            f"Role rating: {_number(baseline.role_average_rating, 2)} → {_number(current.role_average_rating, 2)}; "
            f"chances created/90: {_number(baseline.role_chances_created_per90, 2)} → "
            f"{_number(current.role_chances_created_per90, 2)}.",
            f"Goals plus assists/90: {_number(baseline.role_contributions_per90, 2)} → "
            f"{_number(current.role_contributions_per90, 2)}.",
            *_team_evidence(baseline, current),
        )
        if guardrail_failed:
            return "stop", "Stop condition reached", "The role-unit test materially weakened team chance creation.", evidence
        if any(value is not None and value >= 0.15 for value in (rating, chances, contributions)):
            return "supported", "Promising", "The role unit improved on at least one pre-declared output measure.", evidence
        return "not_supported", "Not supported yet", "Five eligible starts did not materially improve the role unit.", evidence

    if key == "game_state_protection":
        evidence = (
            f"Led but did not win: {baseline.led_not_won} of {baseline.led_matches} baseline lead matches; "
            f"{current.led_not_won} of {current.led_matches} during the test.",
            f"Late goals scored/conceded: {baseline.late_scored}/{baseline.late_conceded} → "
            f"{current.late_scored}/{current.late_conceded}.",
        )
        if current.led_matches < 2:
            return "inconclusive", "Not enough game-state exposure", "Five matches passed, but fewer than two contained a lead to protect.", evidence
        base_rate = baseline.led_not_won / baseline.led_matches if baseline.led_matches else 0
        current_rate = current.led_not_won / current.led_matches
        if current_rate <= base_rate - 0.20:
            return "supported", "Promising", "A smaller share of leads was lost during the test.", evidence
        if current.late_conceded > baseline.late_conceded:
            return "stop", "Stop condition reached", "Late concessions increased during the test.", evidence
        return "not_supported", "Not supported yet", "Lead protection did not materially improve across the test window.", evidence

    return "inconclusive", "Manual review needed", "The stored test has no automatic evaluator in this version.", ()


def evaluate_intervention(review: MatchReview, intervention: StoredIntervention) -> InterventionEvaluation:
    proposal = intervention.proposal
    rows = _relevant_rows(
        review,
        proposal.finding_key,
        after=(proposal.started_after_date, proposal.started_after_match_key),
    )
    exposures = len(rows)
    if not intervention.active:
        return InterventionEvaluation(
            intervention, "closed", "Closed", exposures, proposal.target_matches,
            f"The manager closed this test as {intervention.outcome or 'complete'}.", (), None,
        )
    if exposures < proposal.target_matches:
        remaining = proposal.target_matches - exposures
        return InterventionEvaluation(
            intervention, "collecting", "Collecting evidence", exposures, proposal.target_matches,
            f"{remaining} more eligible match{'es' if remaining != 1 else ''} before automatic review.",
            (f"{exposures} of {proposal.target_matches} eligible post-start exposures recorded.",),
            None,
        )
    season = eligible_team_summaries(review)
    current = _snapshot(review, rows[:proposal.target_matches], season, proposal.finding_key)
    status, label, summary, evidence = _verdict(intervention, current)
    return InterventionEvaluation(
        intervention, status, label, exposures, proposal.target_matches, summary, evidence, current,
    )
