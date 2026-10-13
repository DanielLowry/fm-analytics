"""The control scorecard: how far our matches show each kind of control, beside the league's top third.

docs/control-tactics-plan.md section 5.2. Three kinds of control, each read from
the match stats FM shows, for us and for the side we played:

- **Possession control:** our possession and our pass completion.
- **Territorial control:** the crosses we attempted, the corner margin, and the
  opponent's pass completion (lower means they were kept under pressure).
- **Chance control:** the shots-on-target and clear-cut-chance margins.

Rows are split by the opponent's third of the table at kickoff, as the Matches
page's default grouping places it: all the selected matches with full stats,
the same split by the game plan of the tactic we played (`analytics.game_plan`;
a tactic with two plans counts in both), and the **benchmark**: every archived
league match between two other clubs in which one of them was in the top third
at kickoff, from that club's side. That is what a promotion-chasing side in our
league gets against opponents of the same strength.

Like the rest of the match review this describes; it does not judge. Rows under
`MIN_GROUP_MATCHES` are flagged as too small to read, and the benchmark is
league matches only, while our rows follow the page's filters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from fm_analytics.analytics.catalogue import FootballCatalogue
from fm_analytics.analytics.game_plan import GAME_PLANS, game_plan_keys
from fm_analytics.analytics.match_analysis import MIN_GROUP_MATCHES, MatchReview, side_metrics
from fm_analytics.analytics.match_strength import BANDS, EARLY_SEASON_GAMES, StrengthCalculator, TablePosition
from fm_analytics.domain.matches import Competition, LeagueResult, MatchRecord


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    kind: str  # "possession", "territorial" or "chance"
    percent: bool
    higher_is_better: bool


MEASURES: tuple[Measure, ...] = (
    Measure("possession", "Possession", "possession", True, True),
    Measure("pass_completion", "Passes completed", "possession", True, True),
    Measure("crosses", "Crosses attempted", "territorial", False, True),
    Measure("corner_margin", "Corner margin", "territorial", False, True),
    Measure("opponent_pass_completion", "Their passes completed", "territorial", True, False),
    Measure("sot_margin", "On-target margin", "chance", False, True),
    Measure("ccc_margin", "Clear-cut-chance margin", "chance", False, True),
)
KINDS: tuple[tuple[str, str], ...] = (
    ("possession", "Possession control"),
    ("territorial", "Territorial control"),
    ("chance", "Chance control"),
)
# The opponent thirds the benchmark can be compared in; "early" and "outside"
# have no table position to match.
THIRDS = tuple(band for band in BANDS["table"] if band.key in ("top", "middle", "bottom"))
BENCHMARK_LABEL = "League top third"
NO_TACTIC_PLAN = "unknown"


@dataclass(frozen=True)
class ControlRow:
    key: str
    label: str
    matches: int  # with full stats
    values: Mapping[str, float | None]

    @property
    def enough(self) -> bool:
        return self.matches >= MIN_GROUP_MATCHES


@dataclass(frozen=True)
class ControlBand:
    key: str
    label: str
    ours: ControlRow
    plans: tuple[ControlRow, ...]  # only the plans with a match in this third
    benchmark: ControlRow


@dataclass(frozen=True)
class ControlScorecard:
    bands: tuple[ControlBand, ...]
    season: int | None  # the season the benchmark was limited to, as the page's filter
    benchmark_matches: int  # club-sides counted across every third

    @property
    def has_benchmark(self) -> bool:
        return self.benchmark_matches > 0


def match_measures(
    ours: Mapping[str, float | None] | None, theirs: Mapping[str, float | None] | None
) -> dict[str, float | None] | None:
    """One match's figures for every measure, from each side's `side_metrics`; None without stats."""
    if ours is None or theirs is None:
        return None

    def margin(metric: str) -> float | None:
        mine, other = ours.get(metric), theirs.get(metric)
        return None if mine is None or other is None else mine - other

    return {
        "possession": ours.get("possession"),
        "pass_completion": ours.get("pass_completion"),
        "crosses": ours.get("crosses_attempted"),
        "corner_margin": margin("corners"),
        "opponent_pass_completion": theirs.get("pass_completion"),
        "sot_margin": margin("shots_on_target"),
        "ccc_margin": margin("clear_cut_chances"),
    }


def summarise(key: str, label: str, rows: Iterable[Mapping[str, float | None]]) -> ControlRow:
    rows = list(rows)
    values: dict[str, float | None] = {}
    for measure in MEASURES:
        present = [row[measure.key] for row in rows if row.get(measure.key) is not None]
        values[measure.key] = sum(present) / len(present) if present else None
    return ControlRow(key, label, len(rows), values)


def _third(position: TablePosition | None) -> str | None:
    if position is None or position.played < EARLY_SEASON_GAMES:
        return None
    third = round(position.teams / 3)
    if position.position <= third:
        return "top"
    if position.position > position.teams - third:
        return "bottom"
    return "middle"


def benchmark_rows(
    club_matches: Iterable[MatchRecord],
    leagues: Sequence[tuple[Competition, Sequence[LeagueResult]]],
    club_id: str,
    *,
    season: int | None = None,
) -> dict[str, list[dict[str, float | None]]]:
    """Each opponent third's figures for the league's top-third sides, one entry per club-side.

    Only league matches between two other clubs of our league, with full
    stats, placed in the season (and on the day) the Matches page would place
    one of ours. `season` limits them to one season, as the page's filter does.
    """
    league_ids = {competition.id for competition, _results in leagues}
    calculator = StrengthCalculator(leagues, club_id)
    rows: dict[str, list[dict[str, float | None]]] = {band.key: [] for band in THIRDS}
    for match in club_matches:
        if match.detail is None or match.competition.id not in league_ids:
            continue
        if season is not None and match.season != season:
            continue
        for side, other in (("home", "away"), ("away", "home")):
            table = calculator.table_at(match, match.team(side).id)
            if table is None or _third(table.get(match.team(side).id)) != "top":
                continue
            opponent_third = _third(table.get(match.team(other).id))
            measures = match_measures(side_metrics(match, side), side_metrics(match, other))
            if opponent_third is not None and measures is not None:
                rows[opponent_third].append(measures)
    return rows


def control_scorecard(
    review: MatchReview,
    club_matches: Iterable[MatchRecord],
    leagues: Sequence[tuple[Competition, Sequence[LeagueResult]]],
    catalogue: FootballCatalogue,
) -> ControlScorecard:
    """The selected matches by opponent third and game plan, beside the league's top third."""
    plan_keys = {
        key: game_plan_keys(catalogue.tactics[key], catalogue)
        for key in {summary.tactic_key for summary in review.matches}
        if key in catalogue.tactics
    }
    benchmark = benchmark_rows(club_matches, leagues, review.club.id, season=review.filters.season)
    bands = []
    for band in THIRDS:
        ours = [
            (summary, measures)
            for summary in review.matches
            if summary.strength.band("table").key == band.key
            and (measures := match_measures(summary.ours, summary.theirs)) is not None
        ]
        plans = []
        for plan in GAME_PLANS:
            matching = [m for summary, m in ours if plan.key in plan_keys.get(summary.tactic_key, ())]
            if matching:
                plans.append(summarise(plan.key, plan.label, matching))
        unknown = [m for summary, m in ours if summary.tactic_key not in plan_keys]
        if unknown:
            plans.append(summarise(NO_TACTIC_PLAN, "Tactic not known", unknown))
        bands.append(ControlBand(
            band.key, band.label,
            summarise("ours", "All our matches", (m for _summary, m in ours)),
            tuple(plans),
            summarise("benchmark", BENCHMARK_LABEL, benchmark[band.key]),
        ))
    return ControlScorecard(tuple(bands), review.filters.season, sum(len(rows) for rows in benchmark.values()))
