"""The season as one JSON document, for reading or handing to another tool.

`reporting.build_season_export` is the one way to build it; `fm-matches
export` and the web server's `/api/export` both call that. This module only
shapes what has already been computed: the match reviews
(`reporting.build_match_review`), each league's table, and, when a squad was
read, the recommendation bundle. Nothing here scores or judges.

Every detail level has the same sections; a higher level adds depth to them:

* ``basic``: records, league table, the review's splits, goals and roles,
  one line per player and per match. Needs only the match history.
* ``standard``: adds per-player totals and per-90s, each match's panel
  summary and our line-up, and (with a squad) fitness, best roles and the
  app's tactic ranking and XI.
* ``verbose``: adds every player's stat line in every match, both teams'
  full panels, goal timelines, every visible attribute, and the whole
  tactic ranking with depth and recruitment briefs.

`match_document` is one match on its own, for the match page's copy button
(`reporting.build_match_export`): its verbose entry, with more besides.
`matches_document` is every match the Matches page has selected, each as
`match_document` has it (`reporting.build_matches_export`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from fm_analytics.analytics.appearance_context import appearance_roles
from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.in_transition import in_transition_selected_instructions
from fm_analytics.analytics.in_possession import in_possession_instruction_strings
from fm_analytics.analytics.out_of_possession import out_of_possession_selected_instructions
from fm_analytics.analytics.match_analysis import (
    COMPETITION_SCOPE_LABELS, METRICS, MIN_GROUP_MATCHES, NO_TACTIC, GroupSummary, MatchReport, MatchReview,
    MatchSummary, season_label,
)
from fm_analytics.analytics.match_diagnostics import MatchDiagnostics
from fm_analytics.analytics.match_interventions import InterventionEvaluation
from fm_analytics.analytics.match_players import PlayerSeason
from fm_analytics.analytics.match_roles import RoleCodes
from fm_analytics.analytics.match_timeline import build_timeline
from fm_analytics.analytics.match_breakdowns import PERIODS, Breakdowns, PlayerEvents, Tally, breakdowns
from fm_analytics.analytics.penalty_record import conceded_penalties
from fm_analytics.analytics.match_strength import TablePosition, league_seasons, league_table
from fm_analytics.domain import AttributeObservation, Player
from fm_analytics.domain.matches import PLAYER_STAT_KEYS, PlayerMatchStats

if TYPE_CHECKING:
    from fm_analytics.persistence.match_history import MatchHistory
    from fm_analytics.reporting import RecommendationBundle

EXPORT_FORMAT = "fm-analytics/season-export"
EXPORT_FORMAT_VERSION = 2
DETAIL_LEVELS = ("basic", "standard", "verbose")
STANDARD_TACTIC_RANKING = 10
SUMMARY_STATS = ("goals", "assists", "shots", "shots_on_target", "key_passes")


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def _percent(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _metrics(values: Mapping[str, float | None] | None) -> dict[str, float | None] | None:
    return {key: _round(values.get(key)) for key, _label, _pct in METRICS} if values else None


def _group(group: GroupSummary) -> dict[str, Any]:
    return {
        "label": group.label,
        "played": group.matches, "won": group.wins, "drawn": group.draws, "lost": group.losses,
        "goals_for": group.goals_for, "goals_against": group.goals_against,
        "points": group.points, "points_per_game": _round(group.points_per_game),
        "enough_to_read": group.enough,
        "matches_with_full_stats": group.detailed,
        "avg_for": _metrics(group.averages_for) if group.detailed else None,
        "avg_against": _metrics(group.averages_against) if group.detailed else None,
    }


def _record(summaries: Iterable[MatchSummary]) -> dict[str, Any]:
    summaries = tuple(summaries)
    results = [summary.result for summary in summaries]
    goals_for = sum(summary.goals_for for summary in summaries)
    goals_against = sum(summary.goals_against for summary in summaries)
    points = 3 * results.count("W") + results.count("D")
    return {
        "played": len(summaries), "won": results.count("W"), "drawn": results.count("D"),
        "lost": results.count("L"), "goals_for": goals_for, "goals_against": goals_against,
        "goal_difference": goals_for - goals_against, "points": points,
        "points_per_game": _round(points / len(summaries)) if summaries else None,
        "clean_sheets": sum(1 for summary in summaries if summary.goals_against == 0),
        "failed_to_score": sum(1 for summary in summaries if summary.goals_for == 0),
    }


# -- the league ---------------------------------------------------------------


def _table(results, before: date, club_id: str) -> list[dict[str, Any]]:
    return [
        {
            "pos": position, "team": row.name, "team_id": row.team_id, "us": row.team_id == club_id,
            "played": row.played, "won": row.won, "drawn": row.drawn, "lost": row.lost,
            "goals_for": row.goals_for, "goals_against": row.goals_against,
            "goal_difference": row.goal_difference, "points": row.points,
        }
        for position, row in enumerate(league_table(results, before), start=1)
    ]


def _season(history: MatchHistory, everything: MatchReview, competitive: MatchReview,
            league: MatchReview, as_of: date | None) -> dict[str, Any]:
    competitive_keys = {summary.match.key for summary in competitive.matches}
    league_keys = {summary.match.key for summary in league.matches}
    section: dict[str, Any] = {
        "competitive": _record(competitive.matches),
        "league": _record(league.matches),
        "cups": _record(s for s in competitive.matches if s.match.key not in league_keys),
        "friendlies": _record(s for s in everything.matches if s.match.key not in competitive_keys),
        "league_form_last6": "".join(summary.result for summary in league.matches[-6:]),
    }
    # One season's table at a time: FM files every season of a league under one competition.
    seasons = {
        (season.competition.id, season.season): season
        for season in league_seasons(history.league_results) if history.club.id in season.teams
    }
    if not seasons or as_of is None:
        return section
    current = max(seasons.values(), key=lambda season: season.starts)
    table = _table(current.results, as_of + timedelta(days=1), history.club.id)
    trajectory = []
    for summary in league.matches:
        strength = summary.strength
        played_in = seasons.get((strength.league.id, strength.season)) if strength.league else None
        if played_in is None:
            continue
        after = _table(played_in.results, summary.match.date + timedelta(days=1), history.club.id)
        row = next(row for row in after if row["us"])
        trajectory.append({
            "date": summary.match.date.isoformat(), "season": played_in.season,
            "opponent": summary.opponent.name, "venue": summary.venue,
            "result": f"{summary.result} {summary.goals_for}-{summary.goals_against}",
            "position_after": row["pos"], "points_after": row["points"],
        })
    section.update({
        "league_name": current.competition.name,
        "league_season": current.season,
        "league_position_now": next((row["pos"] for row in table if row["us"]), None),
        "league_table_now": table,
        "league_position_trajectory": trajectory,
    })
    return section


# -- players and matches ------------------------------------------------------


def player_json(season: PlayerSeason, detail: str, events: PlayerEvents | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": season.name, "player_id": season.player_id,
        "apps": season.appearances, "starts": season.starts, "sub_apps": season.substitute_appearances,
        "minutes": season.minutes, "avg_rating": season.average_rating,
        "goals": season.stat("goals"), "assists": season.stat("assists"),
        "main_role": season.roles[0][0] if season.roles else None,
    }
    if detail == "basic":
        return row
    stat = season.stat
    row.update({
        "roles_played": dict(season.roles),
        "shots": stat("shots"), "shots_on_target": stat("shots_on_target"),
        "shot_accuracy_pct": _percent(stat("shots_on_target"), stat("shots")),
        "conversion_pct": _percent(stat("goals"), stat("shots")),
        "clear_cut_chances": stat("clear_cut_chances"), "chances_created": stat("chances_created"),
        "key_passes": stat("key_passes"), "dribbles": stat("dribbles"),
        "pass_completion_pct": _percent(stat("passes_completed"), stat("passes_attempted")),
        "tackles_won_pct": _percent(stat("tackles_won"), stat("tackles_attempted")),
        "headers_won_pct": _percent(stat("headers_won"), stat("headers_attempted")),
        "fouls": stat("fouls"),
        "per90": {
            key: _round(season.per_90(stat(key)))
            for key in ("goals", "assists", "shots", "shots_on_target", "key_passes",
                        "chances_created", "dribbles", "tackles_won", "headers_won")
        } | {"distance_km": _round(season.per_90(season.distance_m / 1000))},
    })
    if events is not None:
        row.update({
            "yellow_cards": events.yellow_cards, "sent_off": events.sent_off,
            "shots_on_goal": events.shots_on_goal, "shots_wide": events.shots_wide, "shots_over": events.shots_over,
            "clear_cut_chances_had": events.clear_cut_chances,
            "clear_cut_chances_scored": events.clear_cut_chances_scored,
            "goals_headed": events.headers, "goals_volleyed": events.volleys, "penalties_scored": events.penalties,
            "goals_from_outside_the_area": events.from_outside_the_area,
        })
    ratings = season.ratings if detail == "verbose" else season.ratings[-5:]
    row["ratings" if detail == "verbose" else "last5_ratings"] = [
        {"date": item.date.isoformat(), "opponent": item.opponent, "rating": item.rating} for item in ratings
    ]
    if detail == "verbose":
        row["totals"] = dict(season.stats)
        row["distance_km"] = _round(season.distance_m / 1000, 1)
    return row


def _team_panel(team: Mapping[str, int], players: Iterable[PlayerMatchStats]) -> dict[str, Any]:
    players = tuple(players)
    return dict(team) | {
        "pass_completion_pct": _percent(team.get("passes_completed", 0), team.get("passes_attempted", 0)),
        "tackles_won_pct": _percent(team.get("tackles_won", 0), team.get("tackles_attempted", 0)),
        "headers_won_pct": _percent(team.get("headers_won", 0), team.get("headers_attempted", 0)),
        "key_passes": sum(p.stat("key_passes") for p in players),
        "chances_created": sum(p.stat("chances_created") for p in players),
        "dribbles": sum(p.stat("dribbles") for p in players),
        "distance_km": _round(sum(p.distance_m for p in players) / 1000, 1),
    }


def _line(player: PlayerMatchStats, role: str, *, full: bool) -> dict[str, Any]:
    line: dict[str, Any] = {
        "name": player.label, "role": role, "position": player.position,
        "started": player.started, "minutes": player.minutes, "rating": player.rating,
    }
    if full:
        line.update({
            "player_id": player.player_id, "shirt": player.shirt,
            "start_position": player.start_position, "start_centre_side": player.start_centre_side,
            "came_on": player.came_on, "went_off": player.went_off,
            "distance_km": _round(player.distance_m / 1000),
            # Zeros are left out to keep a season's lines readable; a missing key is 0.
            "stats": {key: player.stat(key) for key in PLAYER_STAT_KEYS if player.stat(key)},
        })
    else:
        line.update({key: player.stat(key) for key in SUMMARY_STATS if player.stat(key)})
    return line


def _match(summary: MatchSummary, kind: str, codes: RoleCodes, catalogue: FootballCatalogue,
           detail: str, roles: Mapping[tuple[str, str, int], str],
           given_away: Mapping[tuple[int, int], str] = {}) -> dict[str, Any]:
    match = summary.match
    strength = summary.strength

    def role(player: PlayerMatchStats) -> str:
        return roles.get((match.key, player.side, player.short_id)) or codes.label(player.role_code, player.position)

    row: dict[str, Any] = {
        "key": match.key, "date": match.date.isoformat(), "competition": match.competition.label,
        "type": kind, "venue": summary.venue, "opponent": summary.opponent.name,
        "result": summary.result, "score": f"{summary.goals_for}-{summary.goals_against}",
        "opponent_league_pos_at_kickoff": strength.opponent.position if strength.opponent else None,
        "our_league_pos_at_kickoff": strength.ours.position if strength.ours else None,
        "opponent_band": strength.band("table").label,
        "opponent_relative": strength.band("relative").label,
        "tactic": catalogue.tactics[summary.tactic_key].name if summary.tactic_key in catalogue.tactics else None,
        "tactic_inferred_from_lineup": summary.tactic_inferred,
        "full_stats": match.detail is not None,
    }
    if summary.note:
        row["note"] = summary.note

    def ours_first(score: tuple[int, int]) -> str:
        home, away = score
        return f"{home}-{away}" if summary.side == "home" else f"{away}-{home}"

    if match.after_extra_time:
        row["after_extra_time"] = True
        row["score_at_90"] = ours_first(match.score_at_90)
    if match.penalties:
        row["penalties"] = ours_first(match.penalties)
    goals = [incident for incident in match.incidents if incident.is_goal]
    if goals:
        row["goals"] = [
            {"minute": goal.clock, "team": "us" if goal.side == summary.side else "them", "scorer": goal.player}
            | ({"penalty": True} if goal.kind == "penalty" else {})
            | ({"own_goal": True} if goal.kind == "own_goal" else {})
            | ({"given_away_by": given_away[(goal.minute, goal.added_time)], "given_away_by_source": "your record"}
               if goal.kind == "penalty" and (goal.minute, goal.added_time) in given_away else {})
            for goal in goals
        ]
    sent_off = [incident for incident in match.incidents if incident.kind == "sent_off"]
    if sent_off:
        row["sent_off"] = [
            {"minute": item.clock, "team": "us" if item.side == summary.side else "them", "player": item.player}
            for item in sent_off
        ]
    if detail == "basic" or match.detail is None:
        return row
    side = summary.side
    other = "away" if side == "home" else "home"
    ours = [player for player in match.detail.players_for(side) if player.played]
    row.update({
        "attendance": match.attendance,
        "summary_for": _metrics(summary.ours),
        "summary_against": _metrics(summary.theirs),
        "our_players": [_line(player, role(player), full=detail != "standard") for player in ours],
    })
    if detail in ("verbose", "match"):
        theirs = [player for player in match.detail.players_for(other) if player.played]
        row.update({
            "team_stats_for": _team_panel(match.detail.team(side), match.detail.players_for(side)),
            "team_stats_against": _team_panel(match.detail.team(other), match.detail.players_for(other)),
            "their_players": [_line(player, role(player), full=detail == "match") for player in theirs],
        })
        row.update(_timeline(match, side, shots=detail == "match"))
    return row


def _timeline(match, side: str, *, shots: bool) -> dict[str, Any]:
    """The timeline (and, for one match, every shot) as `build_match_report` gives the match page."""
    timeline = build_timeline(match, side)
    found: dict[str, Any] = {}
    if timeline is None:
        return found
    if timeline.opponent_formation:
        found["opponent_formation"] = timeline.opponent_formation
    if timeline.entries:
        found["timeline"] = [
            {"minute": entry.minute, "team": "us" if entry.ours else "them", "event": entry.kind}
            | ({"added_time": entry.added_time} if entry.added_time else {})
            | ({"player": entry.player} if entry.player else {})
            | ({"assist": entry.assisted_by} if entry.assisted_by else {})
            | ({"from_clear_cut_chance": True} if entry.from_clear_cut_chance else {})
            | ({"how": {key: value for key, value in (("strike", entry.how.strike), ("area", entry.how.area),
                                                       ("from", entry.how.how)) if value}} if entry.how else {})
            | ({"possibly_from_a_corner": "guess: assisted by a corner taker"} if entry.possibly_from_a_corner else {})
            for entry in timeline.entries
        ]
    if timeline.ours is not None:
        found["shot_directions"] = {
            team: {"shots": totals.shots, "on_goal": totals.on_goal, "wide": totals.wide, "over": totals.over,
                   "first_half": totals.first_half, "second_half": totals.second_half}
            for team, totals in (("us", timeline.ours), ("them", timeline.theirs))
        }
        if shots:
            found["shots"] = [
                {"minute": shot.clock, "match_clock": shot.match_clock, "team": "us" if shot.ours else "them",
                 "player": shot.player, "outcome": shot.outcome,
                 "goal_line_m": {"across": shot.across, "up": shot.up}}
                for shot in timeline.shots
            ]
    if timeline.by_score is not None:
        found["by_score"] = {state: _tally(tally) for state, tally in timeline.by_score.by_state.items() if tally.minutes >= 1}
    if shots and timeline.unidentified:
        found["unidentified_fm_events"] = [
            {"minute": clock, "team": "us" if ours else "them", "fm_code": f"0x{code:02x}"} for clock, ours, code in timeline.unidentified
        ]
    return found


def _tally(tally: Tally) -> dict[str, Any]:
    """Us, then them."""
    return {
        "minutes": round(tally.minutes), "shots": list(tally.shots), "on_goal": list(tally.on_goal),
        "clear_cut_chances": list(tally.clear_cut_chances), "goals": list(tally.goals),
    }


def breakdowns_json(found: Breakdowns) -> dict[str, Any]:
    """`reporting.build_match_breakdowns` as JSON: each pair is [us, them]."""
    return {
        "matches_in_score_and_period": found.split_matches,
        "left_out_of_score_and_period": dict(found.left_out),
        "by_score": {
            state: _tally(tally) | {"per_90": {key: list(tally.per_90(getattr(tally, key)))
                                               for key in ("shots", "on_goal", "clear_cut_chances", "goals")}}
            for state, tally in found.by_state.items() if tally.minutes >= 1
        },
        "by_period": [{"minutes": label} | _tally(found.by_period[label]) for label, _start, _end in PERIODS],
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


# -- the squad and the app's recommendation -----------------------------------


def _attribute(observation: AttributeObservation) -> int | list[int | None] | None:
    if observation.value is not None:
        return observation.value
    if observation.minimum is not None or observation.maximum is not None:
        return [observation.minimum, observation.maximum]
    return None


def _squad_player(player: Player, bundle: RecommendationBundle, season: PlayerSeason | None,
                  detail: str) -> dict[str, Any]:
    profile = bundle.role_matrix.player_profiles.get(player.id)
    fits = sorted(profile.fits, key=lambda fit: -fit.role_score.score.central) if profile else []
    row: dict[str, Any] = {
        "name": player.name, "player_id": player.id, "age": player.age, "positions": list(player.positions),
        "condition_pct": player.condition_percent, "match_fitness_pct": player.match_fitness_percent,
        "availability": player.availability, "injured": player.injured, "suspended": player.suspended,
        "best_role_fits": [
            {"role": fit.role_name, "score": _round(fit.role_score.score.central, 1)}
            for fit in fits[: 5 if detail == "verbose" else 3]
        ],
        "season": (
            {"apps": season.appearances, "starts": season.starts, "minutes": season.minutes,
             "avg_rating": season.average_rating, "goals": season.stat("goals"), "assists": season.stat("assists")}
            if season else None
        ),
    }
    if detail == "verbose":
        contract = player.contract
        row.update({
            "preferred_foot": player.preferred_foot,
            "position_familiarity": dict(player.position_familiarity),
            "squad_status": contract.squad_status if contract else None,
            "contract_end": contract.end_date.isoformat() if contract and contract.end_date else None,
            "attributes": {name: _attribute(obs) for name, obs in sorted(player.attributes.items())},
        })
    return row


def _evaluation(evaluation) -> dict[str, Any]:
    return {
        "tactic_key": evaluation.tactic.key, "tactic": evaluation.tactic.name,
        "formation": evaluation.tactic.formation, "fit": _round(evaluation.score.central, 1),
        "mean_player_score": _round(evaluation.mean_score.central, 1),
        "weakest_slot_score": _round(evaluation.weakest_score.central, 1),
        "weakest_slots": list(evaluation.weakest_slot_keys), "legal_xi": evaluation.has_legal_xi,
    }


def _recommendation(bundle: RecommendationBundle, detail: str) -> dict[str, Any]:
    pinned = bundle.policy.pinned_tactics
    ranked = [
        (rank, evaluation) for rank, evaluation in enumerate(bundle.recommendation.evaluations, start=1)
        if detail == "verbose" or rank <= STANDARD_TACTIC_RANKING or evaluation.tactic.key in pinned
    ]
    primary = bundle.primary
    section: dict[str, Any] = {
        "opponent": "neutral (none set)" if bundle.policy.opponent.is_neutral else "set by you",
        "pinned_tactics": list(pinned),
        "tactic_ranking": [{"rank": rank, **_evaluation(evaluation)} for rank, evaluation in ranked],
        "primary": _evaluation(primary) | {
            "mentality": primary.tactic.mentality,
            "instructions": list(
                primary.tactic.instructions
                + in_possession_instruction_strings(primary.tactic.in_possession)
                + in_transition_selected_instructions(primary.tactic.in_transition)
                + out_of_possession_selected_instructions(primary.tactic.out_of_possession)
            ),
            "xi": [
                {
                    "slot": assignment.slot.key, "player": assignment.player_name,
                    "role": assignment.intrinsic_role_score.role_name,
                    "role_score": _round(assignment.intrinsic_role_score.score.central, 1),
                    "selection_score": _round(assignment.selection_score.central, 1),
                    "warnings": list(assignment.readiness_warnings + assignment.familiarity_warnings),
                }
                for assignment in primary.assignments
            ],
            "bench": [
                {
                    "player": entry.player_name, "primary_slot": entry.primary_assignment.slot.key,
                    "role": entry.primary_assignment.intrinsic_role_score.role_name,
                    "selection_score": _round(entry.primary_assignment.selection_score.central, 1),
                    "covers": list(entry.covered_slots),
                    "credible_covers": list(entry.credible_slots),
                }
                for entry in bundle.bench.entries
            ],
            "bench_coverage": {
                "credible_cover_ratio": bundle.bench.credible_cover_ratio,
                "credible": list(bundle.bench.credible_covered_slots),
                "below_threshold": list(bundle.bench.weakly_covered_slots),
                "uncovered": list(bundle.bench.uncovered_slots),
            },
        },
        "weak_points": [
            {"kind": weakness.kind.value, "message": weakness.message}
            for weakness in bundle.weakness_report.weaknesses
        ],
    }
    if detail == "verbose":
        depth = bundle.planning_depth
        section["depth"] = {
            "persistent_weaknesses": [item.position for item in depth.persistent_weaknesses],
            "occasional_weaknesses": [item.position for item in depth.occasional_weaknesses],
        }
        section["recruitment_briefs"] = [
            {"need": brief.need, "position": brief.position, "role": brief.role_key,
             "target_score": _round(brief.minimum_role_score, 1), "reason": brief.reason}
            for brief in bundle.briefs
        ]
    return section


# -- the document -------------------------------------------------------------


def _caveats(everything: MatchReview, competitive: MatchReview, bundle, as_of: date | None) -> list[str]:
    detailed = sum(1 for summary in everything.matches if summary.match.detail is not None)
    caveats = [
        f"Groups under {MIN_GROUP_MATCHES} matches are marked enough_to_read: false; most splits are small.",
        "Averages are per match over the matches with full stats only (matches_with_full_stats).",
        "A match's tactic is your note if you added one, else inferred from the starting roles.",
        "Opponent bands use that season's league table on the morning of each match (a friendly uses the "
        "latest season under way); 'Early season' means the opponent had played fewer than 3 league games.",
        "FM20's match panel has no xG; clear-cut chances are the nearest measure of chance quality.",
    ]
    if len(everything.matches) > detailed:
        caveats.append(f"{len(everything.matches) - detailed} match(es) have the result only, no stats.")
    if any(summary.match.after_extra_time for summary in competitive.matches):
        caveats.append(
            "A score is the final one, after extra time where it was played (after_extra_time, score_at_90); "
            "a penalty shootout is shown beside it and not counted as a win or a loss. Extra-time goals "
            "count in the 90+ period."
        )
    if competitive.goals.timed_matches < len(competitive.matches):
        caveats.append(
            f"Goal minutes exist for {competitive.goals.timed_matches} of {len(competitive.matches)} "
            "competitive matches; goals.by_period covers just those. Run `fm-matches capture` to fill them in."
        )
    if everything.unconfirmed_roles:
        caveats.append(
            f"{len(everything.unconfirmed_roles)} FM role code(s) are not mapped to a catalogue role and show as "
            "'Unconfirmed role'; confirm them with `fm-matches role-code`."
        )
    if bundle is not None and as_of is not None and bundle.game.game_date != as_of:
        caveats.append(
            f"The squad was read at {bundle.game.game_date.isoformat()} but matches were last captured at "
            f"{as_of.isoformat()}; run `fm-matches capture` to line them up."
        )
    return caveats


def _goals(review: MatchReview) -> dict[str, Any]:
    goals = review.goals
    return {
        "our_goals_by_scorer_role": dict(goals.scorers),
        "our_goals_by_assister_role": dict(goals.assisters),
        "goals_conceded_by_opponent_role": dict(goals.conceded_to),
        "goals_for_with_player_stats": f"{goals.goals_for_covered} of {goals.goals_for_total}",
        "goals_against_with_player_stats": f"{goals.goals_against_covered} of {goals.goals_against_total}",
        "by_period": {
            "matches_with_goal_minutes": goals.timed_matches,
            "periods": list(goals.periods), "scored": list(goals.scored), "conceded": list(goals.conceded),
        },
        "penalties": {"for": goals.penalties_for, "against": goals.penalties_against},
        "own_goals": {"for": goals.own_goals_for, "against": goals.own_goals_against},
        "sent_off": {"ours": goals.sent_off_ours, "theirs": goals.sent_off_theirs},
    }


def _roles(review: MatchReview) -> list[dict[str, Any]]:
    return [
        {
            "role": role.label, "confirmed": role.confirmed, "appearances": role.appearances,
            "starts": role.starts, "minutes": role.minutes, "avg_rating": role.average_rating,
            "goals": role.goals, "assists": role.assists, "shots": role.shots,
            "shots_on_target": role.shots_on_target,
            "share_of_team_shots_pct": _round(100 * role.shot_share, 1) if role.shot_share is not None else None,
            "clear_cut_chances": role.clear_cut_chances, "key_passes": role.key_passes,
            "chances_created": role.chances_created, "dribbles": role.dribbles,
            "per90": {
                key: _round(role.per_90(getattr(role, key)))
                for key in ("goals", "assists", "shots", "key_passes", "chances_created")
            },
        }
        for role in review.roles
    ]


def export_document(
    history: MatchHistory,
    *,
    everything: MatchReview,
    competitive: MatchReview,
    relative: MatchReview,
    league: MatchReview,
    diagnostics: MatchDiagnostics,
    intervention: InterventionEvaluation | None,
    catalogue: FootballCatalogue,
    detail: str = "standard",
    bundle: RecommendationBundle | None = None,
    squad_note: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Shape the reviews (and the bundle, if a squad was read) into the export document."""
    if detail not in DETAIL_LEVELS:
        raise ValueError(f"detail must be one of {', '.join(DETAIL_LEVELS)}")
    as_of = history.last_game_date
    codes = RoleCodes.build(catalogue, history.role_codes)
    season_breakdowns = breakdowns((summary.match for summary in competitive.matches), history.club.id)
    # Each player's role in each match, with the duty his slot settles (FM's code has none).
    roles = appearance_roles(
        history.matches, history.club.id, notes=history.notes, codes=codes, usual_roles=history.usual_roles
    )
    competitive_keys = {summary.match.key for summary in competitive.matches}
    league_keys = {summary.match.key for summary in league.matches}
    document: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "formatVersion": EXPORT_FORMAT_VERSION,
        "meta": {
            "club": history.club.name, "club_id": history.club.id, "save_key": history.save_key,
            "detail": detail,
            "game_date": as_of.isoformat() if as_of else None,
            "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "coverage": {
                "matches": len(everything.matches),
                "with_full_stats": sum(1 for summary in everything.matches if summary.match.detail is not None),
                "competitive": len(competitive.matches),
                "league": len(league.matches),
                "with_goal_times": competitive.goals.timed_matches,
            },
            "squad": (
                "left out (basic)" if detail == "basic"
                else f"read at game date {bundle.game.game_date.isoformat()}" if bundle is not None
                else squad_note or "not included"
            ),
            "caveats": _caveats(everything, competitive, bundle if detail != "basic" else None, as_of),
        },
        "season": _season(history, everything, competitive, league, as_of),
        "review": {
            "scope": "League and cups; friendlies are left out.",
            "overall": _group(competitive.overall),
            "league_only": _group(league.overall),
            "by_opponent_table_third": [_group(group) for group in competitive.groups],
            "by_opponent_above_or_below_us": [_group(group) for group in relative.groups],
            "by_venue": [_group(group) for group in competitive.venues],
            "by_tactic": [{"tactic": row.label, **_group(row.overall)} for row in competitive.tactics],
        },
        "diagnostics": diagnostics.to_document() | {
            "active_intervention": intervention.to_document() if intervention else None,
            "intervention_history": [item.to_document() for item in history.interventions],
        },
        "goals": _goals(competitive),
        "breakdowns": breakdowns_json(season_breakdowns),
        "roles": _roles(competitive),
        "players": [player_json(season, detail, season_breakdowns.players.get(season.player_id or season.name))
                    for season in competitive.players],
        "matches": [
            _match(
                summary,
                "league" if summary.match.key in league_keys
                else "cup" if summary.match.key in competitive_keys else "friendly",
                codes, catalogue, detail, roles, _given_away(history, summary.match),
            )
            for summary in everything.matches
        ],
    }
    if bundle is not None and detail != "basic":
        seasons = {season.player_id: season for season in competitive.players if season.player_id}
        squad = [_squad_player(player, bundle, seasons.get(player.id), detail) for player in bundle.squad.players]
        squad.sort(key=lambda row: (-(row["season"] or {}).get("minutes", 0), row["name"]))
        document["squad"] = squad
        document["recommendation"] = _recommendation(bundle, detail)
    return document


# -- one match ----------------------------------------------------------------

MATCH_EXPORT_FORMAT = "fm-analytics/match-export"
MATCH_EXPORT_FORMAT_VERSION = 1
MATCH_CAVEATS = (
    "summary_for and summary_against are FM's match panel; possession, pass_completion, tackles_won and "
    "headers_won are percentages. FM20 has no xG: clear-cut chances are the nearest measure of chance quality.",
    "A player's stats leave out zeros: a missing key is 0.",
    "Our roles carry the duty our tactic's slot settles; theirs are as FM's role code names them.",
    "opponent_band uses that season's league table on the morning of the match (a friendly uses the latest "
    "season under way); 'Early season' means the opponent had played fewer than 3 league games.",
)
_RATING_CAVEAT = (
    "your_pre_match_rating is how strong you judged them before kickoff: -2 much weaker than us, "
    "0 about the same, +2 much stronger than us."
)
DUTY_CAVEAT = "A saved-tactic duty of null is one FM's code does not yet name (see docs/match-duty-extraction.md)."


def _standing(position: TablePosition | None) -> dict[str, int] | None:
    return {"position": position.position, "played": position.played, "points": position.points} if position else None


def match_document(
    history: MatchHistory,
    report: MatchReport,
    *,
    catalogue: FootballCatalogue,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """One match with everything recorded about it, for the match page's copy button.

    Its `match` is the match's entry in the verbose season export, with full
    stat lines for their players as well as ours, plus what only one match
    has room for: the league table at kickoff, the unused substitutes, your
    pre-match rating of the opponent and the tactic FM saved for each side.
    """
    summary = report.summary
    match = summary.match
    codes = RoleCodes.build(catalogue, history.role_codes)
    roles = {(match.key, side, short_id): role for (side, short_id), role in report.role_labels.items()}
    row = _full_match(history, summary, codes, catalogue, roles)
    caveats = list(MATCH_CAVEATS)
    if summary.tactic_inferred:
        caveats.append("The tactic is inferred from the starting roles; you did not record one.")
    if summary.strength.rating is not None:
        caveats.append(_RATING_CAVEAT)
    if match.detail is None:
        caveats.append("Only the result was found: FM's archive had no stats for this match that added up.")
    elif has_null_duty(row):
        caveats.append(DUTY_CAVEAT)
    return {
        "format": MATCH_EXPORT_FORMAT,
        "formatVersion": MATCH_EXPORT_FORMAT_VERSION,
        "meta": _match_meta(history, generated_at) | {"caveats": caveats},
        "match": row,
    }


def _match_meta(history: MatchHistory, generated_at: datetime | None) -> dict[str, Any]:
    return {
        "club": history.club.name, "club_id": history.club.id, "save_key": history.save_key,
        "last_captured_game_date": history.last_game_date.isoformat() if history.last_game_date else None,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
    }


def has_null_duty(row: Mapping[str, Any]) -> bool:
    return any(slot["duty"] is None for tactic in row.get("fm_saved_tactics", {}).values() for slot in tactic["slots"])


def _given_away(history: MatchHistory, match) -> dict[tuple[int, int], str]:
    """Who you recorded giving away each penalty scored against you in `match`."""
    return {
        (penalty.minute, penalty.added_time): penalty.given_away_by
        for penalty in conceded_penalties(match, history.club.id, history.penalty_fouls) if penalty.given_away_by
    }


def _full_match(history: MatchHistory, summary: MatchSummary, codes: RoleCodes, catalogue: FootballCatalogue,
                roles: Mapping[tuple[str, str, int], str]) -> dict[str, Any]:
    return full_match_entry(
        summary, codes, catalogue, roles,
        league_ids={competition.id for competition, _results in history.league_results},
        given_away=_given_away(history, summary.match),
    )


def full_match_entry(
    summary: MatchSummary, codes: RoleCodes, catalogue: FootballCatalogue, roles: Mapping[tuple[str, str, int], str],
    *, league_ids: set[str] | None, given_away: Mapping[tuple[int, int], str],
) -> dict[str, Any]:
    """One match's verbose season-export entry, plus what only one match has room for: a match page's copy.

    `league_ids` are the club's leagues; without them (None) a match is only
    competitive or a friendly. `given_away` is who you recorded giving away
    each penalty scored against you.
    """
    match = summary.match
    kind = (
        "friendly" if match.competition.is_friendly
        else "competitive" if league_ids is None
        else "league" if match.competition.id in league_ids else "cup"
    )
    row = _match(summary, kind, codes, catalogue, "match", roles, given_away)
    row.setdefault("attendance", match.attendance)
    strength = summary.strength
    row["league_at_kickoff"] = (
        {"league": strength.league.name, "season": strength.season, "teams": strength.ours.teams,
         "us": _standing(strength.ours), "them": _standing(strength.opponent)}
        if strength.league is not None and strength.ours is not None else None
    )
    row["your_pre_match_rating"] = strength.rating
    if match.detail is not None:
        sides = (("us", summary.side), ("them", "away" if summary.side == "home" else "home"))
        row["unused_substitutes"] = {
            who: [player.label for player in match.detail.players_for(side) if not player.played]
            for who, side in sides
        }
        row["fm_saved_tactics"] = {
            who: {
                "name": tactic.name,
                "slots": [
                    {"position": slot.position, "centre_side": slot.centre_side,
                     "role": codes.label(slot.role_code, slot.position), "duty": slot.duty}
                    for slot in tactic.slots
                ],
            }
            for who, side in sides
            if (tactic := match.detail.saved_tactics.get(side)) is not None
        }
    return row


# -- the matches a review selected --------------------------------------------

MATCHES_EXPORT_FORMAT = "fm-analytics/matches-export"
MATCHES_EXPORT_FORMAT_VERSION = 1


def matches_document(
    history: MatchHistory,
    review: MatchReview,
    *,
    catalogue: FootballCatalogue,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Every match a review selected, with everything recorded about each, for the Matches page's copy button.

    `selection` names the filters; `review`, `goals`, `roles` and `players`
    are the review's figures for just these matches, as the page shows them.
    Each entry in `matches` is that match's `match` in `match_document`, the
    match page's own copy.
    """
    filters = review.filters
    codes = RoleCodes.build(catalogue, history.role_codes)
    rows = [_full_match(history, summary, codes, catalogue, review.appearance_roles) for summary in review.matches]
    selected = breakdowns((summary.match for summary in review.matches), history.club.id)
    tactic = (
        "Any tactic" if filters.tactic is None
        else "Tactic not known" if filters.tactic == NO_TACTIC
        else catalogue.tactics[filters.tactic].name if filters.tactic in catalogue.tactics
        else filters.tactic
    )
    caveats = list(MATCH_CAVEATS)
    if filters.season is not None:
        caveats.append("FM files no season for a friendly; one counts in the season of the next competitive match.")
    if any(summary.tactic_inferred for summary in review.matches):
        caveats.append("tactic_inferred_from_lineup: true means the tactic is inferred from the starting roles; "
                       "you did not record one.")
    if any(summary.strength.rating is not None for summary in review.matches):
        caveats.append(_RATING_CAVEAT)
    result_only = sum(1 for summary in review.matches if summary.match.detail is None)
    if result_only:
        caveats.append(f"{result_only} match(es) have the result only: FM's archive had no stats for them that added up.")
    if any(has_null_duty(row) for row in rows):
        caveats.append(DUTY_CAVEAT)
    return {
        "format": MATCHES_EXPORT_FORMAT,
        "formatVersion": MATCHES_EXPORT_FORMAT_VERSION,
        "meta": _match_meta(history, generated_at) | {"caveats": caveats},
        "selection": {
            "season": season_label(filters.season) if filters.season is not None else "All seasons",
            "competitions": COMPETITION_SCOPE_LABELS[filters.competitions],
            "venue": {"home": "Home", "away": "Away"}.get(filters.venue or "", "Home and away"),
            "tactic": tactic,
            "opponents_grouped_by": review.grouping_label,
            "matches": len(review.matches),
            "with_full_stats": len(review.matches) - result_only,
        },
        "review": {
            "overall": _group(review.overall),
            "by_opponent": [_group(group) for group in review.groups],
            "by_venue": [_group(group) for group in review.venues],
            "by_tactic": [{"tactic": row.label, **_group(row.overall)} for row in review.tactics],
        },
        "goals": _goals(review),
        "breakdowns": breakdowns_json(selected),
        "roles": _roles(review),
        "players": [player_json(season, "verbose", selected.players.get(season.player_id or season.name))
                    for season in review.players],
        "matches": rows,
    }
