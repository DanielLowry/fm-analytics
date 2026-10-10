"""What the match pages show beyond the match record, as JSON: a match's Diagnosis and Result vs
chances, for its entry in every copy and export, and the Matches page's penalty record.

Serialisation only: `single_match_diagnosis.diagnose_one_match` and
`penalty_record` work them out, and the pages show the same figures. Pairs and "team" read as the page does:
"us" is the managed club.
"""

from __future__ import annotations

from typing import Any

from fm_analytics.analytics.match_chances import FinishingRecord, ResultVsChances, SideChances
from fm_analytics.analytics.penalty_record import PenaltyRecord
from fm_analytics.analytics.single_match_diagnosis import OneMatchDiagnosis


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def _team(side: str) -> str:
    return "us" if side == "ours" else "them"


def _finishing(record: FinishingRecord) -> dict[str, Any]:
    row = {
        "name": record.name, "matches": record.matches, "shots": record.shots, "worth": _round(record.worth),
        "goals": record.goals, "clear_cut_chances": record.clear_cut, "clear_cut_chances_scored": record.clear_cut_scored,
        "luck_odds": _round(record.luck_odds, 3), "standing": record.standing,
    }
    if record.today_worth is not None:
        row |= {"today_worth": _round(record.today_worth), "today_goals": record.today_goals}
    return row


def _side(side: SideChances) -> dict[str, Any]:
    return {
        "shots": side.shots, "clear_cut_chances": side.clear_cut, "penalties_scored": side.penalties,
        "worth": _round(side.worth), "goals": side.goals, "own_goals_for": side.own_goals, "score": side.score,
        "on_goal": side.on_goal, "usual_on_goal": _round(side.usual_on_goal),
        "scored_on_goal": side.scored_on_goal, "usual_scored_on_goal": _round(side.usual_scored_on_goal),
        "goals_gained_by_shooting": _round(side.shooting),
        "goals_gained_beating_the_keeper": _round(side.beating_the_keeper),
        "missed_clear_cut_chances": [
            {"player": chance.player, "minute": chance.clock, "outcome": chance.outcome}
            for chance in side.missed_clear_cut
        ],
    }


def chances_json(chances: ResultVsChances) -> dict[str, Any]:
    """The match page's Result vs chances."""
    return {
        "us": _side(chances.ours),
        "them": _side(chances.theirs),
        "chances_of_result": {"win": _round(chances.win, 3), "draw": _round(chances.draw, 3),
                              "loss": _round(chances.loss, 3)},
        "points": chances.points,
        "expected_points": _round(chances.expected_points),
        "better_chances": chances.played,
        "verdict": chances.verdict,
        "tone": chances.tone,
        "summary": chances.summary,
        "why_the_score_and_chances_differ": list(chances.explanations),
        "takeaway": chances.takeaway,
        "team_finishing": _finishing(chances.team_finishing),
        "finishers_below_their_chances": [_finishing(record) for record in chances.finishers],
        "against_your_usual": [
            {"team": _team(item.side), "worth": _round(item.actual), "usual": _round(item.usual),
             "usual_low": _round(item.low), "usual_high": _round(item.high), "standing": item.standing,
             "favourable": item.favourable}
            for item in chances.usual
        ],
        "method": chances.method,
    }


def diagnosis_json(diagnosis: OneMatchDiagnosis) -> dict[str, Any]:
    """The match page's Diagnosis, its Result vs chances included."""
    return {
        "compared_with": diagnosis.compared_with,
        "baseline_matches": diagnosis.baseline_matches,
        "not_compared": diagnosis.not_compared,
        "headline": diagnosis.headline,
        "usual_ranges": [
            {"stat": check.label, "team": _team(check.side), "actual": check.actual,
             "expected": _round(check.expected), "usual_low": check.usual_low, "usual_high": check.usual_high,
             "standing": check.standing, "favourable": check.favourable}
            for check in diagnosis.checks
        ],
        "how_it_played_out": list(diagnosis.game_state),
        "players_above_their_usual": [
            {"name": item.name, "role": item.role, "rating": item.rating, "usual": _round(item.usual),
             "matches": item.matches}
            for item in diagnosis.above_usual
        ],
        "players_below_their_usual": [
            {"name": item.name, "role": item.role, "rating": item.rating, "usual": _round(item.usual),
             "matches": item.matches}
            for item in diagnosis.below_usual
        ],
        "result_vs_chances": chances_json(diagnosis.chances) if diagnosis.chances is not None else None,
        "result_vs_chances_not_judged": diagnosis.chances_not_judged,
    }


def penalties_json(record: PenaltyRecord) -> dict[str, Any]:
    """The Matches page's "Penalties you gave away": who you recorded giving each away (FM doesn't say)."""
    return {
        "penalties": [
            {"date": penalty.date.isoformat(), "opponent": penalty.opponent, "minute": penalty.clock,
             "taker": penalty.taker, "given_away_by": penalty.given_away_by}
            for penalty in record.penalties
        ],
        "by_player": [{"name": name, "penalties": count} for name, count in record.by_player],
        "not_recorded": len(record.unrecorded),
    }
