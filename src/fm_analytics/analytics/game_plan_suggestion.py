"""A suggested game plan against one opponent, from its own matches. A guess, and labelled as one.

FM gives us how much of the ball the opponent has, how many of its passes it
completes and how many headers its matches are contested with, each ranked
against every team in its league (`opponent_report.StyleFigure`). This reads
which game plan (`analytics.game_plan`) suits playing it, by the questions in
docs/control-tactics-plan.md ("Choosing between them"):

- above us in the table: the control plans assume you are the stronger side,
  so a counter-attack is suggested instead;
- keeps the ball and passes it well: press it where it builds (territorial);
- goes long (few passes completed, or many headers): hold a higher line and win
  the second balls (territorial, the squeeze or the siege);
- lets its opponents have the ball: keep it and create with movement and crosses
  (possession or chance control);
- nothing marked: chance control, the safe default.

"Marked" means the opponent is in the top or bottom third of its league for
that figure. Nothing here changes a score; it points at the tactics page's
game-plan filter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from fm_analytics.analytics.game_plan import GAME_PLANS_BY_KEY, GamePlan
from fm_analytics.analytics.match_strength import EARLY_SEASON_GAMES, TablePosition

# The fewest of their matches with full stats to read a style from, and the
# fewest league teams with enough matches to rank it against.
MIN_MATCHES = 3
MIN_LEAGUE_TEAMS = 6
PLAN_GUESS = (
    "A guess: read from their possession, pass completion and headers contested against the rest of their "
    "league. FM gives the figures; the plan is ours."
)


@dataclass(frozen=True)
class PlanSuggestion:
    plans: tuple[GamePlan, ...]
    style: str  # how they play, a clause that follows "They": "go long and fight for second balls"
    reasons: tuple[str, ...]  # the figures it rests on


def _ordinal(number: int) -> str:
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _describe(figure) -> str:
    value = f"{figure.value:.0f}{figure.unit}" if figure.unit == "%" else f"{figure.value:.0f}"
    place = f", {_ordinal(figure.rank)} of {figure.teams}" if figure.rank is not None else ""
    league = f"; the league {figure.league:.0f}{figure.unit}" if figure.league is not None else ""
    return f"{figure.label.lower()} {value}{place}{league}"


def suggest_plan(
    style: Sequence,  # opponent_report.StyleFigure, per match
    matches: int,
    their_position: TablePosition | None,
    our_position: TablePosition | None,
) -> PlanSuggestion | None:
    """The plan to suggest, or None with too few matches, theirs or the league's, to read a style from."""
    if matches < MIN_MATCHES or not style or max(figure.teams for figure in style) < MIN_LEAGUE_TEAMS:
        return None
    figures: Mapping[str, object] = {figure.key: figure for figure in style}

    def plans(*keys: str) -> tuple[GamePlan, ...]:
        return tuple(GAME_PLANS_BY_KEY[key] for key in keys)

    def marked(key: str, end: str) -> bool:
        figure = figures.get(key)
        if figure is None or figure.rank is None or figure.teams < 3:
            return False
        third = math.ceil(figure.teams / 3)
        return figure.rank <= third if end == "high" else figure.rank > figure.teams - third

    def why(*keys: str) -> tuple[str, ...]:
        return tuple(_describe(figures[key]) for key in keys if key in figures)

    if (
        their_position is not None and our_position is not None
        and min(their_position.played, our_position.played) >= EARLY_SEASON_GAMES
        and their_position.position < our_position.position
        and (our_position.position - their_position.position >= 3
             or their_position.position <= math.ceil(their_position.teams / 3) < our_position.position)
    ):
        return PlanSuggestion(
            plans("counter"), "are above you in the table",
            (f"they are {_ordinal(their_position.position)}, you are {_ordinal(our_position.position)}; the control "
             "plans assume you are the stronger side",),
        )
    if marked("possession", "high") and marked("pass_completion", "high"):
        return PlanSuggestion(
            plans("territorial"), "keep the ball and build from the back",
            why("possession", "pass_completion")
            + ("press them where they build, so the regains come high up the pitch",),
        )
    long = [key for key, end in (("pass_completion", "low"), ("headers_attempted", "high")) if marked(key, end)]
    if long:
        return PlanSuggestion(
            plans("territorial"), "go long and fight for second balls",
            why(*long) + ("hold a higher line with centre-backs who win headers and a holder for the knock-downs",),
        )
    if marked("possession", "low"):
        return PlanSuggestion(
            plans("possession", "chance"), "let their opponents have the ball",
            why("possession") + ("expect them to sit in: keep the ball and create with movement, crosses and cut-backs",),
        )
    return PlanSuggestion(
        plans("chance"), "show no clear pattern",
        why("possession", "pass_completion") + ("nothing marks out how they use the ball: chance control is the safe default",),
    )
