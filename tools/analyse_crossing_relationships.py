"""Explore actual-match crossing relationships; never write either match database.

Run: .venv/bin/python -m tools.analyse_crossing_relationships
Requires NumPy/SciPy in the research environment, not in the application.
Reuses the audited snapshot and rejects a changed source capture.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr, spearmanr

from fm_analytics.analytics.chance_value import classify_shots
from fm_analytics.analytics.goal_descriptions import describe_goal
from fm_analytics.analytics.match_breakdowns import counted_split, match_clock
from fm_analytics.analytics.match_timeline import goal_shots
from fm_analytics.domain.matches import MatchCapture
from fm_analytics.reporting import build_match_review, build_season_trends
from tools.audit_hampton_season import goal_rows, load_history, tally_json
from tools.audit_season_crossing import discrepancies

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/exports/season-crossing-audit-2026-10-11.json"
OUTCOMES = ("their_ccc", "their_shots", "their_sot", "their_goals", "points")
PREDICTORS = ("their_cross_attempts", "their_cross_completions", "their_cross_pct",
              "their_corners", "our_possession_pct", "our_pass_pct",
              "our_header_pct", "our_tackle_pct")


def ratio(part, whole):
    return 100 * part / whole if whole else None


def association(rows, x, y):
    pairs = [(r[x], r[y]) for r in rows if r[x] is not None and r[y] is not None]
    a, b = np.asarray(pairs, dtype=float).T
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return {"n": len(pairs), "pearson": None, "spearman": None}
    result = pearsonr(a, b)
    interval = result.confidence_interval()
    omitted = [pearsonr(np.delete(a, i), np.delete(b, i)).statistic for i in range(len(a))]
    return {"n": len(pairs), "pearson": float(result.statistic),
            "pearson_95ci": [float(interval.low), float(interval.high)],
            "spearman": float(spearmanr(a, b).statistic),
            "leave_one_out_pearson_range": [float(min(omitted)), float(max(omitted))]}


def partial(rows, x, y, controls):
    selected = [r for r in rows if all(r[k] is not None for k in (x, y, *controls))]
    design = np.asarray([[1, *(r[k] for k in controls)] for r in selected], dtype=float)
    residuals = []
    for name in (x, y):
        values = np.asarray([r[name] for r in selected], dtype=float)
        residuals.append(values - design @ np.linalg.lstsq(design, values, rcond=None)[0])
    return {"n": len(selected), "controls": list(controls),
            "partial_pearson": float(pearsonr(*residuals).statistic)}


def grouped(rows):
    n = len(rows)
    result = {"n": n, "wdl": dict(Counter(r["result"] for r in rows)),
              "goals_for": sum(r["our_goals"] for r in rows),
              "goals_against": sum(r["their_goals"] for r in rows)}
    for key in (*OUTCOMES, "our_ccc", "our_shots", "our_sot", "our_cross_completions",
                "their_cross_completions", "ahead_fraction"):
        values = [r[key] for r in rows if r[key] is not None]
        result[key + "_mean"] = float(np.mean(values)) if values else None
    return result


def goal_analysis(matches, club):
    rows = []
    for match in matches:
        side = match.side_of(club)
        clock = match_clock(match, side)
        for goal in goal_rows([match], club):
            at = goal["minute"] + goal["added_time"] - 0.5
            rows.append({**goal, "opponent": match.team("away" if side == "home" else "home").name,
                         "date": str(match.date), "state_before": clock.state(at) if clock else None,
                         "late": goal["minute"] >= 76})
    return {"goals": rows, "kind": dict(Counter(r["kind"] for r in rows)),
            "while_ahead_kind": dict(Counter(r["kind"] for r in rows if r["state_before"] == "ahead")),
            "late_kind": dict(Counter(r["kind"] for r in rows if r["late"]))}


def conversion(matches, club):
    counts = {who: Counter() for who in ("us", "them")}
    valid = 0
    unmatched_ccc = Counter()
    conceded_types = Counter()
    for match in matches:
        shots = classify_shots(match)
        if shots is None:
            continue
        valid += 1
        side = match.side_of(club)
        for index, event in goal_shots(match).items():
            if event.side == side:
                continue
            descriptor = describe_goal(event.descriptor)
            kind = (event.kind if event.kind == "penalty" else
                    descriptor.how if descriptor and descriptor.how else "other_or_unclassified")
            conceded_types[(kind, shots[index].kind)] += 1
        for who, selected in (("us", side), ("them", "away" if side == "home" else "home")):
            selected_shots = [s for s in shots if s.side == selected]
            for shot in selected_shots:
                counts[who][shot.kind + "_shots"] += 1
                counts[who][shot.kind + "_on_goal"] += shot.on_goal
                counts[who][shot.kind + "_goals"] += shot.goal
            # Penalty shots take precedence over their CCC label.
            unmatched_ccc[who] += (match.detail.team(selected)["clear_cut_chances"]
                                   - sum(s.kind in ("clear_cut", "penalty") for s in selected_shots))
    return {"classified_matches": valid, "counts": counts,
            "conceded_goal_types": [{"delivery": delivery, "chance_kind": kind, "goals": goals}
                                    for (delivery, kind), goals in conceded_types.items()],
            "ccc_minus_clearcut_and_scored_penalty_shots": unmatched_ccc,
            "caveat": "App time/player matching is approximate; scored penalties take precedence over CCC labels. On-goal shot geometry includes some blocked efforts and differs from FM shots on target."}


def analyse(matches, history):
    review = build_match_review(replace(history, matches=tuple(matches)))
    rows = []
    for summary in review.matches:
        match, side = summary.match, summary.side
        other = "away" if side == "home" else "home"
        ours, theirs = match.detail.team(side), match.detail.team(other)
        split, reason = counted_split(match, side)
        position = summary.strength.opponent
        ranks_valid = position is not None and position.played >= 3
        row = {"key": match.key, "date": str(match.date), "season": match.season,
               "opponent": summary.opponent.name, "venue": summary.venue,
               "home": int(side == "home"), "result": summary.result,
               "points": {"W": 3, "D": 1, "L": 0}[summary.result],
               "tactic": summary.tactic_key, "opponent_band": summary.band.label,
               "opponent_rank": position.position if ranks_valid else None,
               "opponent_rank_fraction": position.position / position.teams if ranks_valid else None,
               "clock_excluded": reason,
               "ahead_fraction": (split.by_state["ahead"].minutes /
                                  sum(t.minutes for t in split.by_state.values())) if split else None,
               "our_possession_pct": ratio(ours["possession_time"], ours["possession_time"] + theirs["possession_time"]),
               "our_pass_pct": ratio(ours["passes_completed"], ours["passes_attempted"]),
               "our_header_pct": ratio(ours["headers_won"], ours["headers_attempted"]),
               "our_tackle_pct": ratio(ours["tackles_won"], ours["tackles_attempted"])}
        for prefix, team in (("our", ours), ("their", theirs)):
            for name, key in (("cross_attempts", "crosses_attempted"), ("cross_completions", "crosses_completed"),
                              ("ccc", "clear_cut_chances"), ("shots", "shots"), ("sot", "shots_on_target"),
                              ("goals", "goals"), ("corners", "corners")):
                row[f"{prefix}_{name}"] = team[key]
            row[f"{prefix}_cross_pct"] = ratio(team["crosses_completed"], team["crosses_attempted"])
        rows.append(row)
    cutoff = float(np.median([r["their_cross_completions"] for r in rows]))
    trends = build_season_trends(review)
    trend = trends.windows[0]
    return {
        "n": len(rows), "rows": rows,
        "correlations": {x: {y: association(rows, x, y) for y in OUTCOMES} for x in PREDICTORS},
        "our_crossing_correlations": {x: {y: association(rows, x, y) for y in ("our_ccc", "our_shots", "our_sot", "our_goals", "points")}
                                      for x in ("our_cross_completions", "our_cross_pct")},
        "crossing_vs_ahead": association(rows, "their_cross_completions", "ahead_fraction"),
        "partial_correlations": {y: {
            "pre_match_controls": partial(rows, "their_cross_completions", y, ("season", "home", "opponent_rank_fraction")),
            "plus_lead_exposure": partial(rows, "their_cross_completions", y, ("season", "home", "opponent_rank_fraction", "ahead_fraction")),
            "shot_count_only": partial(rows, "their_cross_completions", y, ("their_shots",)),
        } for y in ("their_ccc", "their_goals", "points")},
        "median_split": {"cutoff": cutoff, "at_or_below": grouped([r for r in rows if r["their_cross_completions"] <= cutoff]),
                         "above": grouped([r for r in rows if r["their_cross_completions"] > cutoff])},
        "result_groups": {name: grouped([r for r in rows if r["result"] == name]) for name in ("W", "D", "L")},
        "trends": {"matches": trend.matches, "timed": trend.timed, "split_matches": trend.split_matches,
                   "led": trend.led, "led_won": trend.led_won, "dropped": trend.dropped,
                   "late_goals": trend.late_goals, "late_won": trend.late_won, "late_lost": trend.late_lost,
                   "by_state": {key: tally_json(value) for key, value in trend.by_state.items()},
                   "late": tally_json(trend.late)},
        "match_trends": [{"key": m.key, "opponent": m.opponent, "dropped": m.dropped,
                          "at75": m.score_after_75, "late_points": m.late_points} for m in trends.matches],
        "conceded": goal_analysis(matches, history.club.id),
        "shot_conversion": conversion(matches, history.club.id),
    }


def main():
    baseline = json.loads(SNAPSHOT.read_text())
    raw = (ROOT / baseline["source"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != baseline["source_sha256"]:
        raise ValueError("Capture changed: rerun the crossing audit before analysing relationships.")
    capture = MatchCapture.from_document(json.loads(raw))
    history, _ = load_history()
    stored = {m.key: m for m in history.matches}
    accepted = [m for m in capture.matches if m.detail is not None and m.key in stored
                and not discrepancies(m, stored[m.key]) and not m.competition.is_friendly]
    league = [m for m in accepted if m.competition.label == "Vanarama South"]
    year = max(m.season for m in league)
    report = {"source_sha256": baseline["source_sha256"], "source": baseline["source"],
              "method": "Exploratory match-level Pearson/Fisher CI and Spearman correlations; median bins, leave-one-out sensitivity; public app score/period helpers.",
              "limitations": ["Observational associations, not estimates of instruction effects.",
                              "Multiple exploratory comparisons; no selected p-value presented as confirmatory evidence.",
                              "Confidence intervals assume independent matches; same club and repeated opponents weaken this assumption.",
                              "Partial correlations are linear sensitivities; lead exposure is an outcome, not a pretreatment control.",
                              "CCC are sparse and do not identify every dangerous chance; shot origins remain unmeasured.",
                              "Time-split on_goal uses goal-plane geometry, including some blocked shots, not the team shots-on-target stat used by whole-match correlations.",
                              "Whole-match crosses cannot be timed or directly linked to shots; some cross goals may be set pieces."],
              "windows": {name: analyse(matches, history) for name, matches in (
                  ("current_league", [m for m in league if m.season == year]),
                  ("previous_league", [m for m in league if m.season == year - 1]),
                  ("all_league", league), ("competitive", accepted))}}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
