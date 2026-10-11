"""`reporting.build_match_breakdowns`, a match's own split and `reporting.build_season_trends` as JSON:
each pair is [us, them].

Serialisation only, shared by the season, matches, match and experiment
exports. The mentality figures appear where you recorded a mentality.
"""

from __future__ import annotations

from typing import Any

from fm_analytics.analytics.match_breakdowns import PERIODS, Breakdowns, ScoreSplit, Tally
from fm_analytics.analytics.season_trends import CHANGE_WINDOW, ChangeGroup, SeasonTrends, TrendWindow

_PER_90 = ("shots", "on_goal", "clear_cut_chances", "goals")


def tally_json(tally: Tally, *, per_90: bool = False) -> dict[str, Any]:
    """Us, then them."""
    row = {
        "minutes": round(tally.minutes), "shots": list(tally.shots), "on_goal": list(tally.on_goal),
        "clear_cut_chances": list(tally.clear_cut_chances), "goals": list(tally.goals),
    }
    if per_90:
        row["per_90"] = {key: list(tally.per_90(getattr(tally, key))) for key in _PER_90}
    return row


def mentality_json(found: Breakdowns | ScoreSplit, *, per_90: bool = True) -> dict[str, Any]:
    """By the mentality in use, and by mentality and the score together; empty without a recorded mentality."""
    return {
        "by_mentality": {
            name: tally_json(tally, per_90=per_90) for name, tally in found.by_mentality.items() if tally.minutes >= 1
        },
        "by_mentality_and_score": [
            {"mentality": name, "score": state} | tally_json(tally, per_90=per_90)
            for (name, state), tally in found.by_mentality_state.items() if tally.minutes >= 1
        ],
    }


def breakdowns_json(found: Breakdowns) -> dict[str, Any]:
    """`reporting.build_match_breakdowns` as JSON."""
    return {
        "matches_in_score_and_period": found.split_matches,
        "left_out_of_score_and_period": dict(found.left_out),
        "by_score": {state: tally_json(tally, per_90=True) for state, tally in found.by_state.items() if tally.minutes >= 1},
        "by_period": [{"minutes": label} | tally_json(found.by_period[label]) for label, _start, _end in PERIODS],
        "matches_with_mentality": found.mentality_matches,
        **mentality_json(found),
        "goals_scored": {key: dict(counts) for key, counts in found.goals_for.items()},
        "goals_conceded": {key: dict(counts) for key, counts in found.goals_against.items()},
        "by_formation_faced": [
            {"formation": record.formation, "played": record.played, "won": record.won, "drawn": record.drawn,
             "lost": record.lost, "goals": [record.goals_for, record.goals_against],
             "shots": list(record.shots), "clear_cut_chances": list(record.clear_cut_chances),
             "matches_with_stats": record.with_stats}
            for record in found.formations
        ],
    }


def _trend_window_json(window: TrendWindow) -> dict[str, Any]:
    return {
        "window": window.label, "matches": window.matches,
        "matches_with_goal_times": window.timed,
        "led": window.led, "led_won": window.led_won, "led_drawn": window.led_drawn, "led_lost": window.led_lost,
        "points_dropped_from_winning_positions": window.dropped,
        "usual_share_of_leads_won": None if window.usual_hold is None else round(window.usual_hold, 3),
        "after_75": {"goals": list(window.late_goals), "points_won": window.late_won, "points_lost": window.late_lost},
        "matches_in_chance_figures": window.split_matches,
        "by_score": {state: tally_json(tally, per_90=True) for state, tally in window.by_state.items()
                     if tally.minutes >= 1},
        "after_75_chances": tally_json(window.late, per_90=True),
    }


def _change_group_json(group: ChangeGroup) -> dict[str, Any]:
    return {"changes": group.label, "count": group.changes,
            "before": tally_json(group.before, per_90=True), "after": tally_json(group.after, per_90=True)}


def season_trends_json(trends: SeasonTrends) -> dict[str, Any]:
    """`reporting.build_season_trends` as JSON: by window, the matches where a lead was not won, and the changes."""
    return {
        "windows": [_trend_window_json(window) for window in trends.windows],
        "left_out_of_chance_figures": dict(trends.left_out),
        "points_dropped_from_winning_positions": [
            {"key": match.key, "date": match.date.isoformat(), "opponent": match.opponent, "venue": match.venue,
             "result": match.result, "score": [match.goals_for, match.goals_against],
             "points_dropped": match.dropped, "goals": [list(goal) for goal in match.goals]}
            for match in trends.dropped_matches
        ],
        "change_window_minutes": CHANGE_WINDOW,
        "changes": [_change_group_json(group) for group in trends.change_groups],
        "each_change": [
            {"key": change.match_key, "date": change.date.isoformat(), "opponent": change.opponent,
             "minute": change.minute, "by": "us" if change.ours else "them", "kind": change.kind, "what": change.what,
             "score": list(change.score), "before": tally_json(change.before), "after": tally_json(change.after)}
            for change in trends.changes
        ],
    }
