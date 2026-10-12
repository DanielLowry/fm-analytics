"""Reproduce the Hampton/season advice audit without changing either database.

Run from the repository root: PYTHONPATH=src python3 tools/audit_hampton_season.py
The JSON printed to stdout uses the app's public match analysis functions.
Group names supply experiment identities: the stored tactic label alone merges
four different mentalities. No mentality or delegation metadata is invented.
"""

from __future__ import annotations

import json
import hashlib
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from statistics import mean, stdev

from fm_analytics.analytics.chance_value import classify_shots, goal_chances, outcomes
from fm_analytics.analytics.experiments import rates_for, run_figures
from fm_analytics.analytics.match_analysis import ReviewFilters
from fm_analytics.analytics.match_breakdowns import Tally, breakdowns, counted_split, match_clock
from fm_analytics.analytics.match_timeline import goal_moments
from fm_analytics.analytics.opponent_players import where
from fm_analytics.analytics.season_chances import season_chances
from fm_analytics.domain.experiments import MatchLabel, StoredMatch
from fm_analytics.domain.matches import Competition, LeagueResult, MatchRecord, TeamRef
from fm_analytics.domain.mentality import MentalityPlan
from fm_analytics.persistence.match_history import MatchHistory
from fm_analytics.reporting import build_match_review, build_season_trends


ROOT = Path(__file__).resolve().parents[1]


def connect(name):
    connection = sqlite3.connect((ROOT / "data" / name).as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_history():
    with connect("match-history.sqlite3") as connection:
        save = connection.execute("SELECT * FROM saves ORDER BY id DESC LIMIT 1").fetchone()
        documents = connection.execute(
            "SELECT v.document FROM match_versions v WHERE v.save_id = ? AND v.id = "
            "(SELECT w.id FROM match_versions w WHERE w.save_id=v.save_id AND w.match_key=v.match_key "
            "ORDER BY w.has_detail DESC,w.id DESC LIMIT 1) ORDER BY v.match_date,v.match_key", (save["id"],)
        )
        matches = tuple(MatchRecord.from_document(json.loads(row[0])) for row in documents)
        leagues = {}
        for row in connection.execute("SELECT * FROM league_results WHERE save_id=? ORDER BY result_date", (save["id"],)):
            competition = Competition(row["competition_id"], row["competition_name"], row["competition_short_name"])
            leagues.setdefault(competition.id, (competition, []))[1].append(LeagueResult(
                date.fromisoformat(row["result_date"]), TeamRef(row["home_id"], row["home_name"]),
                TeamRef(row["away_id"], row["away_name"]), row["home_goals"], row["away_goals"], row["season"]))
        codes = dict(connection.execute("SELECT code,role_key FROM role_codes ORDER BY id"))
        usual = {(row[0], row[1]): row[2] for row in connection.execute(
            "SELECT tactic_key,slot_key,role_key FROM usual_roles ORDER BY id")}
        plans = {row[0]: json.loads(row[1]) if row[1] else None for row in connection.execute(
            "SELECT match_key,plan FROM match_mentalities WHERE save_id=? ORDER BY id", (save["id"],))}
        coverage = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                    for table in ("club_match_versions", "capture_fixtures", "match_mentalities", "penalty_fouls")}
    return MatchHistory(save["key"], TeamRef(save["club_id"], save["club_name"]), matches,
                        tuple((comp, tuple(rows)) for comp, rows in leagues.values()), {}, codes,
                        max(match.date for match in matches), usual_roles=usual,
                        mentalities={key: MentalityPlan.from_document(plan) for key, plan in plans.items() if plan}), coverage


def load_experiments():
    with connect("experiments.sqlite3") as connection:
        names = dict(connection.execute("SELECT id,name FROM match_groups"))
        membership = {}
        for row in connection.execute("SELECT group_id,stored_match_id,member FROM group_memberships ORDER BY id"):
            membership[(row[0], row[1])] = row[2]
        groups = defaultdict(list)
        for (group_id, match_id), member in membership.items():
            if member:
                groups[match_id].append(names[group_id])
        stored = []
        for row in connection.execute("SELECT * FROM stored_matches ORDER BY id"):
            label = connection.execute("SELECT * FROM match_labels WHERE stored_match_id=? ORDER BY id DESC LIMIT 1",
                                       (row["id"],)).fetchone()
            stored.append(StoredMatch(row["id"], row["stored_at"], TeamRef(row["club_id"], row["club_name"]),
                          MatchRecord.from_document(json.loads(row["document"])),
                          MatchLabel(label["variant"], label["tactic_key"], label["note"], json.loads(label["tags"]),
                                     MentalityPlan.from_document(json.loads(label["mentality"])) if label["mentality"] else None),
                          bool(label["withdrawn"]), tuple(groups[row["id"]])))
        metadata = {"recorded_mentalities": connection.execute(
            "SELECT count(*) FROM match_labels WHERE mentality IS NOT NULL").fetchone()[0],
            "nonempty_notes": connection.execute("SELECT count(*) FROM match_labels WHERE note!=''").fetchone()[0],
            "nonempty_tags": connection.execute("SELECT count(*) FROM match_labels WHERE tags!='{}'").fetchone()[0]}
    return stored, metadata


def wilson(success, count):
    z = 1.96
    p = success / count
    divisor = 1 + z*z/count
    centre = (p + z*z/(2*count)) / divisor
    half = z * math.sqrt(p*(1-p)/count + z*z/(4*count*count)) / divisor
    return [round(centre-half, 3), round(centre+half, 3)]


def goal_rows(matches, club_id, conceded=True):
    rows = []
    for match in matches:
        side = match.side_of(club_id)
        for moment in goal_moments(match):
            if (moment.counts_for != side) != conceded:
                continue
            event = moment.event
            players = {p.short_id: p for p in match.detail.players_for(event.side)}
            scorer = players.get(event.player_short_id)
            supplier = players.get(moment.assist.player_short_id) if moment.assist else None
            scorer_position, scorer_flank = where(scorer) if scorer else (None, None)
            supplier_position, supplier_flank = where(supplier) if supplier else (None, None)
            how = moment.how
            kind = (event.kind if event.kind in ("penalty", "own_goal") else
                    how.how if how and how.how else "other_or_unclassified")
            rows.append({"match": match.key, "minute": event.minute, "added_time": event.added_time,
                         "scorer": scorer.label if scorer else None, "scorer_position": scorer_position,
                         "scorer_flank": scorer_flank, "supplier": supplier.label if supplier else None,
                         "supplier_position": supplier_position, "supplier_flank": supplier_flank,
                         "kind": kind, "strike": how.strike if how else None,
                         "area": how.area if how else None, "possibly_corner": moment.possibly_from_a_corner,
                         "opposite_flanks_guess": kind == "cross" and not moment.possibly_from_a_corner
                         and supplier_position in ("DL", "DR", "WBL", "WBR", "ML", "MR", "AML", "AMR")
                         and {scorer_flank, supplier_flank} == {"left", "right"}})
    return rows


def goal_summary(rows):
    return {"total": len(rows), "kind": dict(Counter(r["kind"] for r in rows)),
            "possible_corners": sum(r["possibly_corner"] for r in rows),
            "cross_strikes": dict(Counter(r["strike"] for r in rows if r["kind"] == "cross")),
            "wide_player_cross_headers": sum(r["kind"] == "cross" and r["strike"] == "header"
                                            and r["scorer_position"] in ("ML", "MR", "AML", "AMR") for r in rows),
            "cross_scorers": dict(Counter(r["scorer"] for r in rows if r["kind"] == "cross")),
            "cross_suppliers": dict(Counter(r["supplier"] for r in rows if r["kind"] == "cross")),
            "cross_scorer_positions": dict(Counter(r["scorer_position"] for r in rows if r["kind"] == "cross")),
            "opposite_flanks_guesses": sum(r["opposite_flanks_guess"] for r in rows)}


def tally_json(tally):
    return {**asdict(tally), "shots_per90": tally.per_90(tally.shots),
            "ccc_per90": tally.per_90(tally.clear_cut_chances)}


def model_points(summary, rates):
    shots = classify_shots(summary.match)
    if shots is None:
        return None
    own = goal_chances([shot for shot in shots if shot.side == summary.side], rates)
    other = goal_chances([shot for shot in shots if shot.side != summary.side], rates)
    win, draw, _loss = outcomes(own, other)
    return 3 * win + draw


def periods_by_score(summaries):
    """Cross the time split with the score; minutes use the app's estimated clock."""
    tallies = {(period, state): Tally() for period in ("before76", "76plus")
               for state in ("level", "ahead", "behind")}
    for summary in summaries:
        split, _reason = counted_split(summary.match, summary.side)
        if split is None:
            continue
        clock = match_clock(summary.match, summary.side)
        bounds = sorted({0, 75, clock.end, *(minute for minute, _change in clock.score_changes)})
        for start, stop in zip(bounds, bounds[1:]):
            tallies[("76plus" if start >= 75 else "before76", clock.state((start+stop)/2))].minutes += stop-start
        for moment in clock.moments:
            moment.add_to(tallies[("76plus" if moment.minute >= 76 else "before76", clock.state(moment.clock))])
    return {period: {state: tally_json(tallies[(period, state)]) for state in ("level", "ahead", "behind")}
            for period in ("before76", "76plus")}


def management_figures(runs, club_id):
    """Observed substitutions and time splits; talks/mentality are not inferred."""
    before = Tally()
    after = Tally()
    substitutions = []
    for run in runs:
        side = run.match.side_of(club_id)
        players = run.match.detail.players_for(side)
        changes = [{"player": p.label, "minute": p.came_on, "position": p.position}
                   for p in players if p.played and p.came_on is not None]
        substitutions.append({"run_id": run.run_id, "changes": changes,
                              "first_substitution": min((row["minute"] for row in changes), default=None)})
        clock = match_clock(run.match, side)
        if clock is not None:
            before.add(clock.tally(0, 60))
            after.add(clock.tally(60, clock.end))
    return {"substitutions": substitutions, "before60": tally_json(before), "from60": tally_json(after)}


def opponent_player_figures(runs, club_id):
    """Visible player stats for the named Hampton threats, preserving each run."""
    targets = {"Sam Chaney", "Ryan Hill", "Tyrone Lewthwaite", "Conor Carty",
               "Ruaridh Donaldson", "Kiernan Hughes-Mason", "Joe Wilson",
               "Tyrell Miller-Rodney"}
    stats = ("shots", "shots_on_target", "clear_cut_chances", "goals", "assists",
             "dribbles", "passes_attempted", "passes_completed", "key_passes",
             "chances_created", "crosses_attempted", "crosses_completed")
    rows = defaultdict(list)
    for run in runs:
        side = run.match.side_of(club_id)
        other = "away" if side == "home" else "home"
        for player in run.match.detail.players_for(other):
            if player.label in targets:
                rows[player.label].append({
                    "run_id": run.run_id, "started": player.started,
                    "minutes": player.minutes, "position": player.position,
                    "stats": {key: player.stats.get(key) for key in stats},
                })
    result = {}
    for name, appearances in rows.items():
        available = {key: [row["stats"][key] for row in appearances
                           if row["stats"][key] is not None] for key in stats}
        stat_figures = {}
        for key, values in available.items():
            minutes = sum(row["minutes"] for row in appearances if row["stats"][key] is not None)
            stat_figures[key] = {
                "observations": len(values), "total": sum(values),
                "mean_per_appearance": mean(values) if values else None,
                "minutes_observed": minutes,
                "per90": sum(values) * 90 / minutes if minutes else None,
            }
        result[name] = {
            "appearances": appearances,
            "minutes_total": sum(row["minutes"] for row in appearances),
            "stats": stat_figures,
        }
    return result


def window(history, filters, fixed_rates):
    review = build_match_review(history, filters=filters)
    trends = build_season_trends(review)
    trend = trends.windows[0]
    chances = season_chances(review.matches, minimum=1)
    matches = [row.match for row in review.matches]
    fixed_points = [points for summary in review.matches if (points := model_points(summary, fixed_rates)) is not None]
    return {"matches": len(matches), "match_keys": [m.key for m in matches],
            "goals": [sum(m.goals(m.side_of(history.club.id)) for m in matches),
                      sum(m.goals('away' if m.side_of(history.club.id)=='home' else 'home') for m in matches)],
            "chances": chances.to_document() if chances else None,
            "expected_ppg_fixed_pre_fixture_rates": mean(fixed_points),
            "split_matches": trend.split_matches, "split_excluded": trends.left_out,
            "periods_by_score": periods_by_score(review.matches),
            "by_state": {k: tally_json(v) for k, v in trend.by_state.items()},
            "late": tally_json(trend.late), "late_goals_all_timed": trend.late_goals,
            "dropped_points": trend.dropped, "led": trend.led, "led_won": trend.led_won,
            "late_points_won": trend.late_won, "late_points_lost": trend.late_lost,
            "conceded": goal_summary(goal_rows(matches, history.club.id)),
            "by_tactic": {name: {"matches": len(rows), "expected_points_per_game": mean(
                row.expected_points for row in rows)} for name, rows in group_chances(review, chances).items()}}


def group_chances(review, chances):
    by_key = {row.key: row for row in chances.matches} if chances else {}
    groups = defaultdict(list)
    for summary in review.matches:
        if summary.match.key in by_key:
            groups[summary.tactic_key].append(by_key[summary.match.key])
    return groups


def run_row(run):
    return {"id": run.run_id, "result": run.result,
            **{key: getattr(run, key) for key in
               ("goals", "shots", "on_goal", "clear_cut_chances", "worth", "balance")},
            "shot_classification_valid": classify_shots(run.match) is not None}


def main():
    history, coverage = load_history()
    stored, metadata = load_experiments()
    active = [run for run in stored if not run.withdrawn]
    fixture_date = min(run.match.date for run in active)
    pre = replace(history, matches=tuple(m for m in history.matches if m.date < fixture_date))
    rates = rates_for(pre.matches, active)  # avoid fitting to the fixture being tested
    grouped = defaultdict(list)
    for item in active:
        for group in item.groups:
            grouped[group].append(run_figures(item, rates))
    variants = {}
    for group, runs in sorted(grouped.items()):
        balances = [run.balance for run in runs]
        model_outcomes = []
        for run in runs:
            shots = classify_shots(run.match)
            if shots is not None:
                side = run.match.side_of(history.club.id)
                ours = [shot for shot in shots if shot.side == side]
                theirs = [shot for shot in shots if shot.side != side]
                model_outcomes.append(outcomes(goal_chances(ours, rates), goal_chances(theirs, rates)))
        variants[group] = {
            "ids": [r.run_id for r in runs], "n": len(runs),
            "record": {k: sum(r.result == k for r in runs) for k in "WDL"},
            "win_interval_wilson95": wilson(sum(r.result == "W" for r in runs), len(runs)),
            **{key: [mean(getattr(r, key)[side] for r in runs) for side in (0, 1)] for key in
               ("goals", "shots", "on_goal", "clear_cut_chances", "worth")},
            "balance": mean(balances), "balance_sd": stdev(balances) if len(balances) > 1 else None,
            "model_outcomes": [mean(row[i] for row in model_outcomes) for i in range(3)] if model_outcomes else None,
            "red_card_runs": [r.run_id for r in runs if any(e.kind == "sent_off" for e in r.match.detail.events)],
            "without_red_balance": mean(r.balance for r in runs if not any(
                e.kind == "sent_off" for e in r.match.detail.events)),
            "conceded": goal_summary(goal_rows([r.match for r in runs], history.club.id)),
            "breakdowns": {k: tally_json(v) for k, v in breakdowns([r.match for r in runs], history.club.id).by_state.items()},
            "management_figures": management_figures(runs, history.club.id),
            "opponent_player_figures": opponent_player_figures(runs, history.club.id),
            "per_run": [run_row(run) for run in runs],
            "starting_xis": dict(Counter(tuple(p.label for p in r.match.detail.players_for(
                r.match.side_of(history.club.id)) if p.started) for r in runs)),
        }
        variants[group]["starting_xis"] = [{"players": list(k), "count": v}
                                             for k, v in variants[group]["starting_xis"].items()]
    ungrouped = []
    for item in active:
        if item.groups:
            continue
        run = run_figures(item, rates)
        ungrouped.append({"id": item.id, "variant": item.label.variant,
                          "note": item.label.note, "match": item.match.to_document(),
                          "figures": run_row(run),
                          "opponent_player_figures": opponent_player_figures([run], history.club.id),
                          "management_figures": management_figures([run], history.club.id)})
    scopes = {"league_2020": ReviewFilters(competitions="league", season=2020),
              "competitive_2020": ReviewFilters(competitions="competitive", season=2020),
              "competitive_all": ReviewFilters(competitions="competitive")}
    result = {"fixture_date": str(fixture_date), "club": history.club.name, "coverage": coverage,
              "input_sha256": {name: hashlib.sha256((ROOT / "data" / name).read_bytes()).hexdigest()
                               for name in ("match-history.sqlite3", "experiments.sqlite3", "league-capture.json")},
              "history_matches_identical_to_replay": [{"match_key": m.key, "replay_id": r.id}
                    for m in history.matches for r in active if m.to_document() == r.match.to_document()],
              "experiment_metadata": metadata, "rate_matches_pre_fixture": rates.matches,
              "rates": {k: rates.value(k) for k in ("clear_cut", "other", "penalty")},
              "variants": variants, "ungrouped_runs": ungrouped,
              "replay_conceded": goal_summary(goal_rows([r.match for r in active], history.club.id)),
              "replay_goal_rows": [{"id": r.id, **row} for r in active for row in goal_rows([r.match], history.club.id)],
              "windows": {key: window(history, filt, rates) for key, filt in scopes.items()},
              "pre_fixture_windows": {key: window(pre, filt, rates) for key, filt in scopes.items()},
              "players": player_evidence()}
    print(json.dumps(result, indent=2))


def player_evidence():
    capture = json.loads((ROOT / "data/league-capture.json").read_text())
    names = {"Mikkel Fosu", "Lucas Odunston", "Jordan Lee", "Abdul Sankoh", "Terrance Saydee", "Ross Holden",
             "Harrison Ashby", "Ejiro Okosieme", "Jamie Bradley-Green", "Ben Jefford", "Conor Carty",
             "Sam Chaney", "Tyrone Lewthwaite", "Ryan Hill"}
    attributes = ("heading", "jumpingReach", "marking", "positioning", "anticipation", "concentration",
                  "stamina", "workRate", "teamwork", "pace", "acceleration", "vision", "dribbling",
                  "offTheBall", "strength", "corners")
    return [{"club_roster": team["squad"]["club"]["name"], "as_of": team["squad"]["asOfDate"],
             "name": player["name"], "attributes": {key: player["attributes"].get(key) for key in attributes},
             "familiarity": player.get("positionFamiliarity"), "contract": player.get("contract"),
             "condition": player.get("conditionPercent"), "match_fitness": player.get("matchFitnessPercent")}
            for team in capture["teams"] for player in team["squad"]["players"]
            if player["name"] in names]


if __name__ == "__main__":
    main()
