"""How each variant in a group of stored matches played, and whether the differences are real.

The manager labels each stored match with the variant it tried, so a group's
matches are compared label by label. FM's match engine is random: one replay can end 3-0 and the next 0-1 with
nothing changed. So variants are compared on what moves least from one replay
to the next: the balance of chances, what our shots were worth less what
theirs were (`chance_value`, the same values a match page uses), with shots,
shots on goal, clear-cut chances, goals and points beside it. A difference
counts as clear only when it is more than twice its standard error (about 19
times in 20 it is not chance); otherwise the report says how many runs of each
would settle a difference that size, from how much the runs so far vary.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt
from statistics import mean, stdev
from typing import Mapping, Sequence

from fm_analytics.analytics.chance_value import ChanceRates, chance_rates, classify_shots
from fm_analytics.analytics.match_breakdowns import ScoreSplit, score_split
from fm_analytics.domain.matches import MatchRecord
from fm_analytics.domain.experiments import StoredMatch

MIN_RUNS = 3  # runs of each variant before a comparison is judged at all
# 95% two-sided and 80% power: how many runs of each settle a difference.
_POWER = (1.96 + 0.84) ** 2


@dataclass(frozen=True)
class RunFigures:
    """One stored match from the managed club's point of view."""

    run_id: int  # the stored match's ID
    variant: str
    recorded_at: str
    opponent: str
    note: str
    tags: Mapping[str, str]
    tactic_key: str | None
    saved_tactic: str | None  # FM's name for the tactic it saved with the match
    result: str  # W, D or L
    goals: tuple[int, int]  # ours, theirs
    shots: tuple[int, int]
    on_goal: tuple[int, int]
    clear_cut_chances: tuple[int, int]
    worth: tuple[float, float]  # what each side's shots were worth, in goals
    possession: int | None
    second_half_shots: tuple[int, int]
    by_score: ScoreSplit | None
    match: MatchRecord

    @property
    def balance(self) -> float:
        return self.worth[0] - self.worth[1]

    @property
    def points(self) -> int:
        return {"W": 3, "D": 1, "L": 0}[self.result]


@dataclass(frozen=True)
class VariantFigures:
    variant: str
    runs: tuple[RunFigures, ...]

    def _mean(self, values) -> float:
        return round(mean(values), 2)

    @property
    def count(self) -> int:
        return len(self.runs)

    @property
    def record(self) -> tuple[int, int, int]:
        return tuple(sum(run.result == result for run in self.runs) for result in "WDL")  # type: ignore[return-value]

    @property
    def points_per_game(self) -> float:
        return self._mean(run.points for run in self.runs)

    def average(self, name: str) -> tuple[float, float]:
        """Ours and theirs, averaged over the runs: goals, shots, on_goal, clear_cut_chances, worth, second_half_shots."""
        return (self._mean(getattr(run, name)[0] for run in self.runs),
                self._mean(getattr(run, name)[1] for run in self.runs))

    @property
    def possession(self) -> float | None:
        values = [run.possession for run in self.runs if run.possession is not None]
        return round(mean(values), 1) if values else None

    @property
    def balance(self) -> float:
        return self._mean(run.balance for run in self.runs)

    @property
    def balance_spread(self) -> float | None:
        """How much the balance varies from one run to the next (standard deviation)."""
        return round(stdev(run.balance for run in self.runs), 2) if self.count >= 2 else None

    @property
    def standard_error(self) -> float | None:
        spread = self.balance_spread
        return round(spread / sqrt(self.count), 2) if spread is not None else None


@dataclass(frozen=True)
class Comparison:
    variant: str
    against: str  # the variant with the best balance
    difference: float  # its balance less the best's (0 or below)
    margin: float | None  # twice the standard error of the difference
    verdict: str  # "clear", "not clear yet" or "too few runs"
    runs_needed: int | None  # runs of each that would settle a difference this size


@dataclass(frozen=True)
class ExperimentReport:
    name: str  # the group's, or "All stored matches"
    note: str
    runs: tuple[RunFigures, ...]  # oldest first, withdrawn ones left out
    variants: tuple[VariantFigures, ...]  # best balance first
    comparisons: tuple[Comparison, ...]  # each variant against the best
    rates_from: int  # matches the chance values were counted from
    withdrawn: int


def _worth(match: MatchRecord, side: str, rates: ChanceRates) -> float:
    shots = classify_shots(match)
    if shots is not None:
        return round(sum(rates.value(shot.kind) for shot in shots if shot.side == side), 2)
    team = match.detail.team(side)
    clear_cut = team.get("clear_cut_chances", 0)
    return round(clear_cut * rates.value("clear_cut") + max(team.get("shots", 0) - clear_cut, 0) * rates.value("other"), 2)


def run_figures(run: StoredMatch, rates: ChanceRates) -> RunFigures:
    match = run.match
    side = run.side
    other = "away" if side == "home" else "home"
    detail = match.detail
    pair = lambda key: (detail.team(side).get(key, 0), detail.team(other).get(key, 0))  # noqa: E731
    ours, theirs = match.goals(side), match.goals(other)
    saved = detail.saved_tactics.get(side)
    return RunFigures(
        run_id=run.id, variant=run.label.variant, recorded_at=run.stored_at, opponent=run.opponent,
        note=run.label.note,
        tags=run.label.tags, tactic_key=run.label.tactic_key, saved_tactic=saved.name if saved else None,
        result="W" if ours > theirs else "L" if ours < theirs else "D",
        goals=(ours, theirs), shots=pair("shots"), on_goal=(
            sum(shot.side == side and shot.heading == "on_goal" for shot in detail.shots),
            sum(shot.side == other and shot.heading == "on_goal" for shot in detail.shots),
        ) if detail.shots else pair("shots_on_target"),
        clear_cut_chances=pair("clear_cut_chances"),
        worth=(_worth(match, side, rates), _worth(match, other, rates)),
        possession=detail.possession_percent(side),
        second_half_shots=(sum(shot.side == side and shot.minute >= 45 for shot in detail.shots),
                           sum(shot.side == other and shot.minute >= 45 for shot in detail.shots)),
        by_score=score_split(match, side),
        match=match,
    )


def _compare(variant: VariantFigures, best: VariantFigures) -> Comparison:
    difference = round(variant.balance - best.balance, 2)
    if variant.count < MIN_RUNS or best.count < MIN_RUNS or variant.standard_error is None or best.standard_error is None:
        return Comparison(variant.variant, best.variant, difference, None, "too few runs", None)
    margin = round(2 * sqrt(variant.standard_error ** 2 + best.standard_error ** 2), 2)
    spread = sqrt((variant.balance_spread ** 2 + best.balance_spread ** 2) / 2)
    needed = ceil(2 * _POWER * spread ** 2 / difference ** 2) if difference else None
    return Comparison(variant.variant, best.variant, difference, margin,
                      "clear" if abs(difference) > margin else "not clear yet", needed)


def experiment_report(
    name: str, stored: Sequence[StoredMatch], rates: ChanceRates, *, note: str = ""
) -> ExperimentReport:
    """`stored` compared label by label; withdrawn matches are counted but left out."""
    runs = tuple(run_figures(run, rates) for run in stored if not run.withdrawn)
    groups: dict[str, list[RunFigures]] = {}
    for run in runs:
        groups.setdefault(run.variant, []).append(run)
    variants = tuple(sorted(
        (VariantFigures(name, tuple(items)) for name, items in groups.items()),
        key=lambda variant: (-variant.balance, variant.variant),
    ))
    best = variants[0] if variants else None
    return ExperimentReport(
        name=name,
        note=note,
        runs=runs,
        variants=variants,
        comparisons=tuple(_compare(variant, best) for variant in variants[1:]) if best else (),
        rates_from=rates.matches,
        withdrawn=sum(run.withdrawn for run in stored),
    )


def rates_for(history_matches: Sequence[MatchRecord], stored: Sequence[StoredMatch]) -> ChanceRates:
    """What each kind of shot is worth: from the save's competitive matches, or the stored matches without any."""
    counted = [shots for match in history_matches if not match.competition.is_friendly
               and (shots := classify_shots(match)) is not None]
    if not counted:
        counted = [shots for run in stored if (shots := classify_shots(run.match)) is not None]
    return chance_rates(counted)
