"""Which owned players to secure, renew or let go: contract risk crossed with value.

Two manager-visible readings per player. **How soon could he leave?** comes
from his contract (type, end date, and whether he is ours or on loan). **How
much would we lose?** comes from his competitive match ratings against the
rest of the squad, his best in-position role score against the recommended
XI, and how far that XI drops if his first cover replaces him. The two cross
into one verdict (see ``docs/contract-planning.md``), and a keep value orders
players within a verdict.

This module adds no scoring of its own. The position score is the Squad
page's in-position figure (``reporting.build_player_role_scores``) and
replaceability is the weakness report's own starter/first-cover comparison,
including its weak-backup rule, so a number here can never disagree with the
Squad or Depth pages. Nothing reads a hidden value: potential is not visible,
so age is the only development signal used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from statistics import median
from typing import Mapping, Sequence

from fm_analytics.analytics.match_players import PlayerSeason
from fm_analytics.analytics.weaknesses import WeaknessKind, WeaknessReport
from fm_analytics.analytics.xi_selection import PositionAdjustedRoleFit
from fm_analytics.domain import Player


class ContractRisk(StrEnum):
    """How soon a player could leave, read from his contract alone."""

    ANY_DAY = "any_day"  # non-contract: another club can offer terms at any time
    ENDS_SOON = "ends_soon"  # within the policy's short window (six months)
    NEXT_YEAR = "next_year"  # within the renewal window (eighteen months)
    SETTLED = "settled"
    ON_LOAN = "on_loan"  # contracted to another club
    UNKNOWN = "unknown"  # no contract read, or a dated type with no end date


RISK_LABELS = {
    ContractRisk.ANY_DAY: "Any day",
    ContractRisk.ENDS_SOON: "Within 6 months",
    ContractRisk.NEXT_YEAR: "In 6–18 months",
    ContractRisk.SETTLED: "Settled",
    ContractRisk.ON_LOAN: "On loan",
    ContractRisk.UNKNOWN: "Unknown",
}


class FormBand(StrEnum):
    STRONG = "strong"  # top third of the squad's rated players
    SOLID = "solid"
    POOR = "poor"  # bottom third
    NO_EVIDENCE = "no_evidence"  # under the policy's minimum minutes


class PositionLevel(StrEnum):
    STARTER = "starter"  # at or above the recommended XI's median starter
    SQUAD = "squad"  # at or above the Depth page's starter bar
    BELOW = "below"  # under that bar, or no eligible role at all


class Value(StrEnum):
    CORE = "core"
    USEFUL = "useful"
    UNPROVEN = "unproven"
    MARGINAL = "marginal"


class Verdict(StrEnum):
    SECURE_NOW = "secure_now"
    RENEW_EARLY = "renew_early"
    KEEP_IF_TERMS = "keep_if_terms"
    YOUR_CALL = "your_call"
    REPLACE_FIRST = "replace_first"
    LET_GO = "let_go"
    LET_RUN_DOWN = "let_run_down"
    REVIEW_LATER = "review_later"
    SURPLUS = "surplus"
    SETTLED = "settled"
    ON_LOAN = "on_loan"
    UNKNOWN = "unknown"


# Priority order: the action list and every table sort by this first.
VERDICT_ORDER = tuple(Verdict)

# Verdicts that ask the manager for a decision now or soon.
ACTION_VERDICTS = (
    Verdict.SECURE_NOW,
    Verdict.RENEW_EARLY,
    Verdict.KEEP_IF_TERMS,
    Verdict.YOUR_CALL,
    Verdict.REPLACE_FIRST,
)

VERDICT_LABELS = {
    Verdict.SECURE_NOW: "Secure now",
    Verdict.RENEW_EARLY: "Renew early",
    Verdict.KEEP_IF_TERMS: "Keep if the terms are right",
    Verdict.YOUR_CALL: "Your call",
    Verdict.REPLACE_FIRST: "Replace first",
    Verdict.LET_GO: "Let go",
    Verdict.LET_RUN_DOWN: "Let it run down",
    Verdict.REVIEW_LATER: "Review later",
    Verdict.SURPLUS: "Surplus",
    Verdict.SETTLED: "Settled",
    Verdict.ON_LOAN: "On loan",
    Verdict.UNKNOWN: "Contract unknown",
}

VERDICT_ADVICE = {
    Verdict.SECURE_NOW: "Offer a new contract before he can leave.",
    Verdict.RENEW_EARLY: "Open talks before he enters his final six months.",
    Verdict.KEEP_IF_TERMS: "Worth keeping, but not at any price.",
    Verdict.YOUR_CALL: "Too little match evidence to judge: give him minutes before deciding.",
    Verdict.REPLACE_FIRST: "Not worth keeping on his own merits, but he is the only cover somewhere: sign a replacement first.",
    Verdict.LET_GO: "Let him leave when his contract allows.",
    Verdict.LET_RUN_DOWN: "No renewal needed: let the contract run out.",
    Verdict.REVIEW_LATER: "Nothing to decide yet; look again when more evidence is in.",
    Verdict.SURPLUS: "Under contract but not needed; consider moving him on.",
    Verdict.SETTLED: "No contract action needed.",
    Verdict.ON_LOAN: "Not ours to renew: a permanent deal or a loan extension is a separate decision.",
    Verdict.UNKNOWN: "No usable contract was read; check it in FM.",
}

_URGENT = frozenset({ContractRisk.ANY_DAY, ContractRisk.ENDS_SOON})

_VERDICTS = {
    (Value.CORE, True): Verdict.SECURE_NOW,
    (Value.USEFUL, True): Verdict.KEEP_IF_TERMS,
    (Value.UNPROVEN, True): Verdict.YOUR_CALL,
    (Value.MARGINAL, True): Verdict.LET_GO,
    (Value.CORE, False): Verdict.RENEW_EARLY,
    (Value.USEFUL, False): Verdict.REVIEW_LATER,
    (Value.UNPROVEN, False): Verdict.REVIEW_LATER,
    (Value.MARGINAL, False): Verdict.LET_RUN_DOWN,
}

# Weakness kinds that make a starter hard to replace: exactly the Depth page's
# "no backup" and "cover drops off sharply" findings for his slot.
_HARD_TO_REPLACE_KINDS = frozenset({WeaknessKind.NO_BACKUP, WeaknessKind.WEAK_BACKUP})


@dataclass(frozen=True)
class ContractPolicy:
    """Every threshold the verdicts use, versioned and tunable in one place."""

    version: str = "contract-v1"
    # A rating needs this many competitive minutes before it counts as form.
    min_minutes: int = 450
    # A strong rating over fewer minutes than this is flagged as a small sample.
    small_sample_minutes: int = 900
    # Keep value treats a rating as if he had also played this many minutes at
    # the squad's median rating, so a short hot streak cannot top the list.
    prior_minutes: int = 900
    ends_soon_months: int = 6
    renewal_window_months: int = 18
    # Ratings come from competitive matches in this many days to the game date.
    rating_window_days: int = 365
    # Fewer rated players than this and form is not split into thirds.
    min_rated_players: int = 3
    form_weight: float = 0.4
    position_weight: float = 0.3
    replaceability_weight: float = 0.3
    # A drop this large from the starter to his first cover earns full marks.
    full_marks_drop: float = 0.30
    young_age: int = 21
    old_age: int = 32
    age_points: int = 5
    recent_join_days: int = 60
    sparkline_matches: int = 10


@dataclass(frozen=True)
class Reason:
    """One short, manager-facing reason behind a verdict."""

    label: str
    tone: str  # "good" | "neutral" | "warn" | "bad"


@dataclass(frozen=True)
class ContractAssessment:
    player_id: str
    player_name: str
    age: int | None
    positions: tuple[str, ...]
    first_team: bool
    # Contract, as FM shows it.
    contract_type: str | None
    end_date: date | None
    joined_date: date | None
    squad_status: str | None
    contracted_club: str | None
    months_left: int | None
    risk: ContractRisk
    # Form: competitive matches in the rating window.
    appearances: int
    starts: int
    minutes: int
    average_rating: float | None
    recent_ratings: tuple[float, ...]  # oldest first, for a sparkline
    form: FormBand
    form_rank: int | None  # 1 = best rating among the squad's rated players
    # Position score: the Squad page's in-position figure.
    position_score: float | None
    position_role: str | None
    position: str | None
    level: PositionLevel
    # Replaceability, from the recommended XI's weakness report.
    xi_slot: str | None
    starter_score: float | None
    cover_name: str | None
    cover_score: float | None
    replacement_drop: float  # 0..1; 1.0 when the slot has no available cover
    hard_to_replace: bool
    only_cover_for: tuple[str, ...]
    # The answer.
    value: Value
    verdict: Verdict
    keep_value: int
    reasons: tuple[Reason, ...]

    @property
    def in_xi(self) -> bool:
        return self.xi_slot is not None

    @property
    def risk_label(self) -> str:
        return RISK_LABELS[self.risk]

    @property
    def verdict_label(self) -> str:
        return VERDICT_LABELS[self.verdict]

    @property
    def advice(self) -> str:
        if self.verdict is Verdict.REPLACE_FIRST and self.only_cover_for:
            return (
                "Not worth keeping on his own merits, but he is the only cover at "
                + ", ".join(self.only_cover_for) + ": sign a replacement first."
            )
        return VERDICT_ADVICE[self.verdict]


@dataclass(frozen=True)
class ContractReview:
    game_date: date
    policy: ContractPolicy
    tactic_key: str
    tactic_name: str
    reference_score: float  # the XI's median starter: the starter-level bar
    squad_level_score: float  # the Depth page's starter bar
    rated_players: int
    strong_from: float | None  # a rating at or above this is strong form
    poor_below: float | None  # a rating below this is poor form
    history_note: str | None  # why ratings are missing or partial, if they are
    assessments: tuple[ContractAssessment, ...]  # priority order

    def with_verdict(self, verdict: Verdict) -> tuple[ContractAssessment, ...]:
        return tuple(item for item in self.assessments if item.verdict is verdict)

    def count(self, verdict: Verdict) -> int:
        return sum(1 for item in self.assessments if item.verdict is verdict)

    def for_player(self, player_id: str) -> ContractAssessment | None:
        return next((item for item in self.assessments if item.player_id == player_id), None)

    @property
    def xi(self) -> tuple[ContractAssessment, ...]:
        return tuple(item for item in self.assessments if item.in_xi)

    @property
    def xi_at_risk(self) -> tuple[ContractAssessment, ...]:
        """Recommended starters who could leave within the short window."""
        return tuple(item for item in self.xi if item.risk in _URGENT)


def add_months(day: date, months: int) -> date:
    """The same day of the month `months` later, clamped to the month's end."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    following = date(year + month // 12, month % 12 + 1, 1)
    last_day = (following - date.resolution).day
    return date(year, month, min(day.day, last_day))


def months_between(start: date, end: date) -> int:
    """Whole months from `start` to `end`; negative once `end` has passed."""
    months = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        months -= 1
    return months


def contract_risk(
    player: Player, game_date: date, club_id: str | None, policy: ContractPolicy = ContractPolicy()
) -> ContractRisk:
    contract = player.contract
    if contract is None:
        return ContractRisk.UNKNOWN
    owner = contract.contracted_club
    if owner is not None and club_id is not None and owner.id != club_id:
        return ContractRisk.ON_LOAN
    if contract.contract_type == "non_contract":
        return ContractRisk.ANY_DAY
    if contract.end_date is None:
        return ContractRisk.UNKNOWN
    if contract.end_date <= add_months(game_date, policy.ends_soon_months):
        return ContractRisk.ENDS_SOON
    if contract.end_date <= add_months(game_date, policy.renewal_window_months):
        return ContractRisk.NEXT_YEAR
    return ContractRisk.SETTLED


def assess_contracts(
    players: Sequence[Player],
    *,
    game_date: date,
    club_id: str | None,
    seasons: Mapping[str, PlayerSeason],
    position_fits: Mapping[str, PositionAdjustedRoleFit | None],
    weakness_report: WeaknessReport,
    tactic_name: str,
    other_players: Sequence[Player] = (),
    history_note: str | None = None,
    policy: ContractPolicy = ContractPolicy(),
) -> ContractReview:
    """Assess `players` (the first team) and, optionally, `other_players`.

    Form thirds, ranks and the keep value's squad ranks always come from the
    first team, so adding other club squads to the view never moves a
    first-team player's verdict. Only first-team players can be in the XI or
    be its cover; `weakness_report` is the recommended tactic's.
    """
    reference = weakness_report.reference_score
    squad_bar = reference * weakness_report.starter_ratio

    # Form: thirds and ranks among first-team players with enough minutes.
    def season_for(player: Player) -> PlayerSeason | None:
        return seasons.get(player.id)

    def rating(player: Player) -> tuple[int, float | None]:
        season = season_for(player)
        if season is None:
            return 0, None
        return season.minutes, season.average_rating

    rated = sorted(
        value for minutes, value in map(rating, players)
        if value is not None and minutes >= policy.min_minutes
    )
    if len(rated) >= policy.min_rated_players:
        poor_below, strong_from = rated[len(rated) // 3], rated[(2 * len(rated)) // 3]
    else:
        poor_below = strong_from = None
    median_rating = median(rated) if rated else None

    def adjusted(player: Player) -> float | None:
        minutes, value = rating(player)
        if median_rating is None:
            return None
        if value is None or minutes <= 0:
            return median_rating
        return (minutes * value + policy.prior_minutes * median_rating) / (minutes + policy.prior_minutes)

    first_team_adjusted = [value for value in map(adjusted, players) if value is not None]

    def fit_score(player_id: str) -> float:
        fit = position_fits.get(player_id)
        return fit.position_adjusted_score.central if fit is not None else 0.0

    first_team_fits = [fit_score(player.id) for player in players]

    # Replaceability: each starter's slot, score, first cover, and the
    # weakness report's own verdict on that cover.
    hard_slots = {
        slot_key
        for weakness in weakness_report.weaknesses
        if weakness.kind in _HARD_TO_REPLACE_KINDS
        for slot_key in weakness.slot_keys
    }
    starters: dict[str, tuple[str, float, str | None, float | None]] = {}
    only_cover: dict[str, list[str]] = {}
    for slot_depth in weakness_report.depth:
        backups = slot_depth.available_backups
        if slot_depth.starter is not None:
            cover = backups[0] if backups else None
            starters[slot_depth.starter.player_id] = (
                slot_depth.slot.key,
                slot_depth.starter.tapered_attribute_score.central,
                cover.player_name if cover else None,
                cover.role_score.score.central if cover else None,
            )
            if len(backups) == 1:
                only_cover.setdefault(backups[0].player_id, []).append(slot_depth.slot.key)

    first_team_ids = {player.id for player in players}
    assessments = []
    for player in (*players, *other_players):
        contract = player.contract
        risk = contract_risk(player, game_date, club_id, policy)
        end_date = contract.end_date if contract else None
        season = season_for(player)
        minutes, average = rating(player)
        if average is None or minutes < policy.min_minutes:
            form = FormBand.NO_EVIDENCE
        elif strong_from is None or poor_below is None:
            form = FormBand.SOLID
        elif average >= strong_from:
            form = FormBand.STRONG
        elif average < poor_below:
            form = FormBand.POOR
        else:
            form = FormBand.SOLID
        form_rank = (
            1 + sum(1 for value in rated if value > average)
            if form is not FormBand.NO_EVIDENCE else None
        )
        fit = position_fits.get(player.id)
        score = fit.position_adjusted_score.central if fit is not None else None
        if score is not None and score >= reference:
            level = PositionLevel.STARTER
        elif score is not None and score >= squad_bar:
            level = PositionLevel.SQUAD
        else:
            level = PositionLevel.BELOW
        slot = starters.get(player.id)
        if slot is not None:
            slot_key, starter_score, cover_name, cover_score = slot
            hard = slot_key in hard_slots
            drop = (
                1.0 if cover_score is None
                else max(0.0, 1.0 - cover_score / starter_score) if starter_score > 0
                else 0.0
            )
        else:
            slot_key = starter_score = cover_name = cover_score = None
            hard, drop = False, 0.0
        covers = tuple(only_cover.get(player.id, ()))

        value = classify_value(form, level, in_xi=slot is not None, hard_to_replace=hard)
        verdict = verdict_for(value, risk)
        if verdict in (Verdict.LET_GO, Verdict.LET_RUN_DOWN) and covers:
            verdict = Verdict.REPLACE_FIRST

        form_part = _rank_fraction(adjusted(player), first_team_adjusted, player.id in first_team_ids)
        position_part = _rank_fraction(score or 0.0, first_team_fits, player.id in first_team_ids)
        replace_part = min(1.0, drop / policy.full_marks_drop) if slot is not None else 0.0
        keep = 100 * (
            policy.form_weight * (form_part if form_part is not None else 0.5)
            + policy.position_weight * (position_part if position_part is not None else 0.0)
            + policy.replaceability_weight * replace_part
        )
        if player.age is not None and player.age <= policy.young_age:
            keep += policy.age_points
        elif player.age is not None and player.age >= policy.old_age:
            keep -= policy.age_points

        assessments.append(
            ContractAssessment(
                player_id=player.id,
                player_name=player.name,
                age=player.age,
                positions=tuple(player.positions),
                first_team=player.id in first_team_ids,
                contract_type=contract.contract_type if contract else None,
                end_date=end_date,
                joined_date=contract.joined_date if contract else None,
                squad_status=contract.squad_status if contract else None,
                contracted_club=(
                    contract.contracted_club.name if contract and contract.contracted_club else None
                ),
                months_left=months_between(game_date, end_date) if end_date else None,
                risk=risk,
                appearances=season.appearances if season else 0,
                starts=season.starts if season else 0,
                minutes=minutes,
                average_rating=average,
                recent_ratings=tuple(
                    item.rating for item in (season.ratings if season else ())
                )[-policy.sparkline_matches:],
                form=form,
                form_rank=form_rank,
                position_score=score,
                position_role=fit.role_name if fit is not None else None,
                position=fit.position if fit is not None else None,
                level=level,
                xi_slot=slot_key,
                starter_score=starter_score,
                cover_name=cover_name,
                cover_score=cover_score,
                replacement_drop=round(drop, 6),
                hard_to_replace=hard,
                only_cover_for=covers,
                value=value,
                verdict=verdict,
                keep_value=max(0, min(100, round(keep))),
                reasons=_reasons(
                    player, game_date, policy, form=form, form_rank=form_rank, rated=len(rated),
                    average=average, minutes=minutes, level=level, slot_key=slot_key,
                    starter_score=starter_score, cover_name=cover_name, cover_score=cover_score,
                    hard=hard, covers=covers,
                ),
            )
        )
    assessments.sort(
        key=lambda item: (
            VERDICT_ORDER.index(item.verdict),
            item.risk is not ContractRisk.ANY_DAY,
            -item.keep_value,
            item.player_name.casefold(),
        )
    )
    return ContractReview(
        game_date=game_date,
        policy=policy,
        tactic_key=weakness_report.tactic_key,
        tactic_name=tactic_name,
        reference_score=reference,
        squad_level_score=round(squad_bar, 6),
        rated_players=len(rated),
        strong_from=strong_from,
        poor_below=poor_below,
        history_note=history_note,
        assessments=tuple(assessments),
    )


def classify_value(form: FormBand, level: PositionLevel, *, in_xi: bool, hard_to_replace: bool) -> Value:
    if (
        (form is FormBand.STRONG and level is not PositionLevel.BELOW)
        or (level is PositionLevel.STARTER and form is FormBand.SOLID)
        or hard_to_replace
    ):
        return Value.CORE
    if form is FormBand.NO_EVIDENCE:
        return Value.UNPROVEN if level is PositionLevel.STARTER or in_xi else Value.MARGINAL
    if not in_xi and (
        form is FormBand.POOR or (level is PositionLevel.BELOW and form is not FormBand.STRONG)
    ):
        return Value.MARGINAL
    return Value.USEFUL


def verdict_for(value: Value, risk: ContractRisk) -> Verdict:
    if risk is ContractRisk.ON_LOAN:
        return Verdict.ON_LOAN
    if risk is ContractRisk.UNKNOWN:
        return Verdict.UNKNOWN
    if risk is ContractRisk.SETTLED:
        return Verdict.SURPLUS if value is Value.MARGINAL else Verdict.SETTLED
    return _VERDICTS[(value, risk in _URGENT)]


def _rank_fraction(value: float | None, population: Sequence[float], member: bool) -> float | None:
    """0 for the lowest in the squad, 1 for the highest; ties share a rank."""
    if value is None or not population:
        return None
    others = len(population) - 1 if member else len(population)
    if others <= 0:
        return 0.5
    return min(1.0, sum(1 for item in population if item < value) / others)


def ordinal_text(number: int) -> str:
    """1st, 2nd, 3rd, 4th ... 11th, 12th, 13th, 21st."""
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _reasons(
    player: Player, game_date: date, policy: ContractPolicy, *, form: FormBand,
    form_rank: int | None, rated: int, average: float | None, minutes: int,
    level: PositionLevel, slot_key: str | None, starter_score: float | None,
    cover_name: str | None, cover_score: float | None, hard: bool, covers: tuple[str, ...],
) -> tuple[Reason, ...]:
    reasons: list[Reason] = []
    if form is FormBand.NO_EVIDENCE:
        reasons.append(Reason(
            "No competitive minutes" if minutes == 0
            else f"Too few minutes to judge form ({minutes:,} of {policy.min_minutes:,})",
            "warn",
        ))
    else:
        rank = f", {ordinal_text(form_rank)} of {rated}" if form_rank is not None else ""
        tone = {FormBand.STRONG: "good", FormBand.SOLID: "neutral", FormBand.POOR: "bad"}[form]
        reasons.append(Reason(f"{form.value.title()} form: {average:.2f}{rank}", tone))
        if form is FormBand.STRONG and minutes < policy.small_sample_minutes:
            reasons.append(Reason(f"Small sample: {minutes:,} minutes", "warn"))
    reasons.append({
        PositionLevel.STARTER: Reason("Starter-level position score", "good"),
        PositionLevel.SQUAD: Reason("Squad-level position score", "neutral"),
        PositionLevel.BELOW: Reason("Position score below squad level", "bad"),
    }[level])
    if (form is FormBand.STRONG and level is PositionLevel.BELOW) or (
        form is FormBand.POOR and level is PositionLevel.STARTER
    ):
        reasons.append(Reason("Form and position score disagree", "warn"))
    if slot_key is not None:
        reasons.append(Reason(f"In your XI at {slot_key}", "good"))
        if hard:
            reasons.append(Reason(
                f"Hard to replace: no cover at {slot_key}" if cover_name is None
                else f"Hard to replace: {cover_name} {cover_score:.0f} vs his {starter_score:.0f}",
                "good",
            ))
    if covers:
        reasons.append(Reason("Only cover at " + ", ".join(covers), "warn"))
    if player.age is not None and player.age <= policy.young_age:
        reasons.append(Reason(f"{policy.young_age} or under", "good"))
    elif player.age is not None and player.age >= policy.old_age:
        reasons.append(Reason(f"{policy.old_age}+: one year at most", "warn"))
    joined = player.contract.joined_date if player.contract else None
    if joined is not None and 0 <= (game_date - joined).days <= policy.recent_join_days:
        reasons.append(Reason(f"Joined {(game_date - joined).days} days ago", "neutral"))
    return tuple(reasons)
