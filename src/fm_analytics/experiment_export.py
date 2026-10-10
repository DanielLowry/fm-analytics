"""Stored matches as JSON, with everything recorded about each: a group page's copy button and `fm-experiments export`.

Built by `reporting.build_experiment_export`. Like the Matches page's "Copy all
match data", each entry in `matches` is the match as its own page's copy
holds it (`season_export.full_match_entry`), here from the stored match's own
report: replays of one fixture share a date and a match key, so nothing is
looked up by key across them. The comparison (`variants`, `comparisons`),
`breakdowns` and `players` (for the whole group, and for each label
under `variants`) count only the matches not withdrawn; withdrawn ones are
still listed, marked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.experiments import ExperimentReport, RunFigures
from fm_analytics.analytics.match_analysis import MatchReport
from fm_analytics.analytics.match_breakdowns import breakdowns
from fm_analytics.analytics.match_players import summarise_players
from fm_analytics.analytics.match_roles import RoleCodes
from fm_analytics.analytics.single_match_diagnosis import OneMatchDiagnosis
from fm_analytics.domain.experiments import StoredMatch
from fm_analytics.breakdowns_export import breakdowns_json
from fm_analytics.season_export import DUTY_CAVEAT, MATCH_CAVEATS, full_match_entry, has_null_duty, player_json

if TYPE_CHECKING:
    from fm_analytics.persistence.match_history import MatchHistory

EXPORT_FORMAT = "fm-analytics/experiment-export"
EXPORT_FORMAT_VERSION = 2

_CAVEATS = (
    "Pairs are [ours, theirs]. 'worth' is what each side's shots were worth in goals, valued as a match page "
    "values them; 'balance' is ours less theirs. FM20 shows no expected goals.",
    "A difference is 'clear' when it is more than twice its standard error; 'runs_needed' is how many matches "
    "of each would settle a difference that size, from how much these vary.",
    "Replays of one fixture share its date and key; stored_match_id tells them apart. Each match's 'match' is "
    "what its own page's copy holds.",
    "variants, comparisons, breakdowns and players count only matches not withdrawn; a withdrawn match is "
    "listed with withdrawn: true and no figures.",
)


def _figures(run: RunFigures) -> dict[str, Any]:
    return {
        "result": run.result, "goals": list(run.goals), "shots": list(run.shots), "on_goal": list(run.on_goal),
        "clear_cut_chances": list(run.clear_cut_chances), "worth": list(run.worth),
        "balance": round(run.balance, 2), "possession": run.possession,
        "second_half_shots": list(run.second_half_shots),
    }


def experiment_document(
    report: ExperimentReport,
    stored: Sequence[StoredMatch],
    reports: Mapping[int, MatchReport],
    history: MatchHistory | None,
    diagnoses: Mapping[int, OneMatchDiagnosis],
    *,
    catalogue: FootballCatalogue,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """`report`'s comparison, then every stored match in `stored` as its own page's copy holds it.

    `reports` are the stored matches' own reports (`reporting.build_stored_match_report`)
    by ID; `history` is the same club's match history or None, for the
    league table at kickoff, FM role codes you confirmed and which
    competitions are leagues; `diagnoses` each stored match's Diagnosis,
    against that history's competitive matches (none without one).
    """
    codes = RoleCodes.build(catalogue, history.role_codes if history else {})
    league_ids = {competition.id for competition, _results in history.league_results} if history else None
    figures = {run.run_id: run for run in report.runs}
    club_id = stored[0].club.id if stored else None
    # The breakdowns are one club's; a group mixing saves counts only the first match's club there.
    ours = {item.id for item in stored if item.club.id == club_id}

    def roles(item: StoredMatch) -> dict[tuple[str, str, int], str]:
        return {(item.match.key, side, short_id): role for (side, short_id), role in reports[item.id].role_labels.items()}

    def counted(runs: Sequence[RunFigures]) -> dict[str, Any]:
        """The Matches page's breakdowns and player lines, for just these matches."""
        counted_runs = [run for run in runs if run.run_id in ours]
        found = breakdowns((run.match for run in counted_runs), club_id,
                           plans=[reports[run.run_id].summary.mentality for run in counted_runs])
        lines = summarise_players(
            (player, summary.match.date, summary.opponent.name,
             reports[run.run_id].role_labels.get((player.side, player.short_id))
             or codes.label(player.role_code, player.position))
            for run in runs
            if (summary := reports[run.run_id].summary).match.detail is not None
            for player in summary.match.detail.players_for(summary.side)
        )
        return {
            "breakdowns": breakdowns_json(found),
            "players": [player_json(season, "verbose", found.players.get(season.player_id or season.name))
                        for season in lines],
        }

    rows = []
    for item in stored:
        run = figures.get(item.id)
        rows.append({
            "stored_match_id": item.id, "label": item.label.variant, "tactic_key": item.label.tactic_key,
            "note": item.label.note, "tags": dict(item.label.tags),
            "mentality": item.label.mentality.to_document() if item.label.mentality else None,
            "stored_at": item.stored_at,
            "groups": list(item.groups), "withdrawn": item.withdrawn,
            "figures": _figures(run) if run else None,
            "match": full_match_entry(reports[item.id].summary, codes, catalogue, roles(item),
                                      league_ids=league_ids, given_away={}, diagnosis=diagnoses.get(item.id)),
        })
    caveats = [*_CAVEATS, *MATCH_CAVEATS]
    if any(has_null_duty(row["match"]) for row in rows):
        caveats.append(DUTY_CAVEAT)
    return {
        "format": EXPORT_FORMAT,
        "formatVersion": EXPORT_FORMAT_VERSION,
        "meta": {
            "club": stored[0].club.name if stored else None, "club_id": club_id,
            "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "chance_values_from_matches": report.rates_from,
            "caveats": caveats,
        },
        "group": {"name": report.name, "note": report.note, "matches": len(stored), "compared": len(report.runs),
                  "withdrawn": report.withdrawn},
        "variants": [
            {
                "label": variant.variant, "matches": variant.count, "record": dict(zip("WDL", variant.record)),
                "points_per_game": variant.points_per_game, "balance": variant.balance,
                "balance_spread": variant.balance_spread, "standard_error": variant.standard_error,
                **{name: list(variant.average(name)) for name in
                   ("goals", "shots", "on_goal", "clear_cut_chances", "worth", "second_half_shots")},
                "possession": variant.possession,
                "stored_match_ids": [run.run_id for run in variant.runs],
                **counted(variant.runs),
            }
            for variant in report.variants
        ],
        "comparisons": [
            {"label": item.variant, "against": item.against, "difference": item.difference, "margin": item.margin,
             "verdict": item.verdict, "runs_needed": item.runs_needed}
            for item in report.comparisons
        ],
        **counted(report.runs),
        "matches": rows,
    }
