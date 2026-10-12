"""The League page's hidden view as JSON: its "Copy everything as JSON" button. HIDDEN DATA.

Serialisation only: `analytics.hidden_strength` works everything out, and the
page shows the same figures. Every score is the team model's XI score (0-100)
from the real values FM keeps for every player, shown to the manager or not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fm_analytics.analytics.hidden_strength import MATCHUPS, HiddenStrength, XiStrength

FORMAT = "fm-analytics/hidden-strength"
FORMAT_VERSION = 1

WARNING = (
    "Uses hidden attributes: the real value of every attribute and position rating FM keeps for each player, "
    "including what FM does not show you. Nothing here feeds the recommendations or any other page."
)


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def _xi(xi: XiStrength | None) -> dict[str, Any] | None:
    if xi is None:
        return None
    document: dict[str, Any] = {"score": xi.score, "shape": xi.shape, "scored_in": xi.tactic_name}
    if not xi.exact_shape:
        document["nearest_shape_we_have"] = True
    if xi.out_of_position:
        document["players_out_of_position"] = True
    if xi.missing:
        document["not_scored_because"] = list(xi.missing)
    if xi.units:
        document["units"] = xi.units
    if xi.players:
        document["players"] = [{"name": player.name, "position": player.position, "role": player.role_name,
                                "score": player.score} for player in xi.players]
    return document


def hidden_document(report: HiddenStrength, *, generated_at: datetime | None = None) -> dict[str, Any]:
    capture, model, verdict = report.capture, report.model, report.verdict
    catalogue_names = report.tactic_names
    used = dict(report.our_tactics)
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "warning": WARNING,
        "club": capture.club.name,
        "competition": capture.competition.name,
        "season": report.season,
        "attributes_read_at_game_date": capture.game_date.isoformat(),
        "method": {
            "xi_score": "The team model's XI score (0-100), as on the League page, but from true attributes and "
                        "position ratings, with every player fully fit and a neutral opponent.",
            "fielded_xi": "Each starter where he started, in our catalogue's best tactic of that shape; without that "
                          "shape, the nearest one stands in.",
            "attributes_as_of": "Every XI uses its players' attributes as at the read date, not the match date.",
            "expected": "Each side's goals are Poisson, with log mean moving linearly with the XI-score gap, "
                        "fitted on every league match this season with both XIs scored.",
        },
        "model": None if model is None else {
            "matches": model.matches,
            "log_goals_per_point_of_gap": _round(model.slope, 4),
            "standard_error": _round(model.slope_error, 4),
            "goals_per_match_per_point_of_gap": _round(model.goals_per_point(), 3),
            "home_goals_at_equal_strength": _round(model.outcome(0, 0).home_goals),
            "away_goals_at_equal_strength": _round(model.outcome(0, 0).away_goals),
        },
        "league_matches": report.league_matches,
        "league_matches_scored": report.league_scored,
        "verdict": None if verdict is None else {
            "played": verdict.played, "points": verdict.points,
            "expected_points": _round(verdict.expected_points, 1),
            "points_above_expected": _round(verdict.points_gap, 1),
            "last_matches": verdict.recent_played, "last_points": verdict.recent_points,
            "last_expected_points": _round(verdict.recent_expected, 1),
            "clubs": verdict.clubs, "points_rank": verdict.points_rank,
            "fielded_xi_rank": verdict.fielded_rank, "best_xi_rank": verdict.best_rank,
            "best_xi_rank_tactic": catalogue_names.get(verdict.best_tactic),
            "fielded_unit_ranks": dict(verdict.fielded_unit_ranks),
            "best_xi_unit_ranks": dict(verdict.best_unit_ranks),
        },
        "our_league_totals": None if report.our_totals is None else {
            "matches": report.our_totals.matches, "points": report.our_totals.points,
            "expected_points": _round(report.our_totals.expected_points, 1),
            "average_our_xi": _round(report.our_totals.our_xi), "average_their_xi": _round(report.our_totals.their_xi),
            "average_unit_gaps": {key: _round(value) for key, value in report.our_totals.unit_gaps.items()},
            "average_matchups": {key: _round(value) for key, value in report.our_totals.matchups.items()},
        },
        "our_matches": [{
            "date": row.match.date.isoformat(),
            "competition": row.match.competition.label,
            "opponent": row.opponent.name,
            "venue": "home" if row.side == "home" else "away",
            "score": f"{row.goals_for}-{row.goals_against}",
            "points": row.points,
            "our_formation": row.our_formation,
            "their_formation": row.their_formation,
            "our_xi": row.ours.score,
            "their_xi": row.theirs.score,
            "gap": _round(row.gap),
            "expected_points": _round(row.expected_points),
            "expected_goals_for": _round(row.expected_for),
            "expected_goals_against": _round(row.expected_against),
            "unit_gaps": {key: row.unit_gap(key) for key in row.ours.units if key in row.theirs.units},
            "matchups": {key: row.matchups[key] for key, _mine, _theirs in MATCHUPS},
            "our_line_up": _xi(row.ours),
            "their_line_up": _xi(row.theirs),
        } for row in report.our_matches],
        "best_xi_in_our_tactics": {
            "tactics": [{"key": key, "name": catalogue_names.get(key, key), "our_matches": used.get(key, 0)}
                        for key in report.compared_tactics],
            "clubs": [{"club": row.club.name, "ours": row.ours, "squad": row.squad_size,
                       "xis": {key: _xi(row.xis[key]) for key in report.compared_tactics},
                       "unit_ranks_in_main_tactic": dict(report.best_unit_ranks.get(row.club.id, {}))}
                      for row in report.by_tactic],
        },
        "best_xi_in_their_formations": [{
            "club": row.club.name, "ours": row.ours,
            "formations": [{"name": use.name, "matches": use.matches, "in_our_catalogue": use.exact}
                           for use in row.formations],
            "best_formation": row.best_formation,
            "best_xi": _xi(row.best),
        } for row in report.by_formation],
        "expected_against_actual": [{
            "club": row.club.name, "ours": row.ours, "played": row.played, "points": row.points,
            "expected_points": _round(row.expected_points, 1), "points_above_expected": _round(row.points_gap, 1),
            "goals_for": row.goals_for, "goals_against": row.goals_against,
            "expected_goals_for": _round(row.expected_for, 1), "expected_goals_against": _round(row.expected_against, 1),
            "average_xi": _round(row.average_xi), "average_opposition_xi": _round(row.average_opponent_xi),
            "average_units": {key: _round(value) for key, value in row.average_units.items()},
            "unit_ranks": dict(report.fielded_unit_ranks.get(row.club.id, {})),
        } for row in report.clubs],
        "notes": list(capture.notes),
    }
