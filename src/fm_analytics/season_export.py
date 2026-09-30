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
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.match_analysis import METRICS, MIN_GROUP_MATCHES, GroupSummary, MatchReview, MatchSummary
from fm_analytics.analytics.match_players import PlayerSeason
from fm_analytics.analytics.match_roles import RoleCodes
from fm_analytics.analytics.match_strength import league_table
from fm_analytics.domain import AttributeObservation, Player
from fm_analytics.domain.matches import PLAYER_STAT_KEYS, PlayerMatchStats

if TYPE_CHECKING:
    from fm_analytics.persistence.match_history import MatchHistory
    from fm_analytics.reporting import RecommendationBundle

EXPORT_FORMAT = "fm-analytics/season-export"
EXPORT_FORMAT_VERSION = 1
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
    ours = next(
        ((competition, results) for competition, results in history.league_results
         if any(history.club.id in (r.home.id, r.away.id) for r in results)),
        None,
    )
    if ours is None or as_of is None:
        return section
    competition, results = ours
    table = _table(results, as_of + timedelta(days=1), history.club.id)
    trajectory = []
    for summary in league.matches:
        after = _table(results, summary.match.date + timedelta(days=1), history.club.id)
        row = next(row for row in after if row["us"])
        trajectory.append({
            "date": summary.match.date.isoformat(), "opponent": summary.opponent.name, "venue": summary.venue,
            "result": f"{summary.result} {summary.goals_for}-{summary.goals_against}",
            "position_after": row["pos"], "points_after": row["points"],
        })
    section.update({
        "league_name": competition.name,
        "league_position_now": next((row["pos"] for row in table if row["us"]), None),
        "league_table_now": table,
        "league_position_trajectory": trajectory,
    })
    return section


# -- players and matches ------------------------------------------------------


def _player(season: PlayerSeason, detail: str) -> dict[str, Any]:
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


def _line(player: PlayerMatchStats, codes: RoleCodes, *, full: bool) -> dict[str, Any]:
    line: dict[str, Any] = {
        "name": player.label, "role": codes.label(player.role_code), "started": player.started,
        "minutes": player.minutes, "rating": player.rating,
    }
    if full:
        line.update({
            "player_id": player.player_id, "shirt": player.shirt,
            "came_on": player.came_on, "went_off": player.went_off,
            "distance_km": _round(player.distance_m / 1000),
            # Zeros are left out to keep a season's lines readable; a missing key is 0.
            "stats": {key: player.stat(key) for key in PLAYER_STAT_KEYS if player.stat(key)},
        })
    else:
        line.update({key: player.stat(key) for key in SUMMARY_STATS if player.stat(key)})
    return line


def _match(summary: MatchSummary, kind: str, codes: RoleCodes, catalogue: FootballCatalogue,
           detail: str) -> dict[str, Any]:
    match = summary.match
    strength = summary.strength
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
    goals = [incident for incident in match.incidents if incident.is_goal]
    if goals:
        row["goals"] = [
            {"minute": goal.clock, "team": "us" if goal.side == summary.side else "them", "scorer": goal.player}
            | ({"penalty": True} if goal.kind == "penalty" else {})
            | ({"own_goal": True} if goal.kind == "own_goal" else {})
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
        "our_players": [_line(player, codes, full=detail == "verbose") for player in ours],
    })
    if detail == "verbose":
        theirs = [player for player in match.detail.players_for(other) if player.played]
        row.update({
            "team_stats_for": _team_panel(match.detail.team(side), match.detail.players_for(side)),
            "team_stats_against": _team_panel(match.detail.team(other), match.detail.players_for(other)),
            "their_players": [_line(player, codes, full=False) for player in theirs],
        })
        if match.detail.events:
            row["timeline"] = [
                {"minute": event.minute, "team": "us" if event.side == side else "them", "event": event.kind}
                for event in match.detail.events if event.kind != "other"
            ]
    return row


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
            "instructions": list(primary.tactic.instructions),
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
                }
                for entry in bundle.bench.entries
            ],
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
        "Opponent bands use the league table on the morning of each match; 'Early season' means "
        "the opponent had played fewer than 3 league games.",
        "FM20's match panel has no xG; clear-cut chances are the nearest measure of chance quality.",
    ]
    if len(everything.matches) > detailed:
        caveats.append(f"{len(everything.matches) - detailed} match(es) have the result only, no stats.")
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


def export_document(
    history: MatchHistory,
    *,
    everything: MatchReview,
    competitive: MatchReview,
    relative: MatchReview,
    league: MatchReview,
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
    competitive_keys = {summary.match.key for summary in competitive.matches}
    league_keys = {summary.match.key for summary in league.matches}
    goals = competitive.goals
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
                "with_goal_times": goals.timed_matches,
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
        "goals": {
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
        },
        "roles": [
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
            for role in competitive.roles
        ],
        "players": [_player(season, detail) for season in competitive.players],
        "matches": [
            _match(
                summary,
                "league" if summary.match.key in league_keys
                else "cup" if summary.match.key in competitive_keys else "friendly",
                codes, catalogue, detail,
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
