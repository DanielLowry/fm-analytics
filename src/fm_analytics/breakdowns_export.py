"""`reporting.build_match_breakdowns` and a match's own split as JSON: each pair is [us, them].

Serialisation only, shared by the season, matches, match and experiment
exports. The mentality figures appear where you recorded a mentality.
"""

from __future__ import annotations

from typing import Any

from fm_analytics.analytics.match_breakdowns import PERIODS, Breakdowns, ScoreSplit, Tally

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
