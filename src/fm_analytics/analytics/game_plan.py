"""Which game plan a tactic follows, worked out from its own settings and roles.

Labels for grouping and filtering, never scoring input: a tactic's fit score
answers "can this squad play it", and which plan to play against an opponent is
the manager's choice (docs/control-tactics-plan.md). They are derived here, in
one place, rather than typed into each tactic file, so they cannot drift from
the settings they describe.

A tactic can follow more than one plan (Counter-Press with a higher line and
Counter on winning the ball is both territorial and a counter-attack), so a
tactic carries every label that applies, each with the settings that earned it.
Chance control is the exception: it is the control plan that relies on the
side's structure rather than on the ball or on territory, so a tactic that is
already territorial, possession-based, counter-attacking or a low block is not
also labelled chance control.

Every rule reads the tactic's legacy instruction strings plus its structured
settings, so a tactic still in the legacy format is labelled from what it has.
"""

from __future__ import annotations

from dataclasses import dataclass

from fm_analytics.analytics.catalogue import FootballCatalogue, TacticDefinition
from fm_analytics.analytics.in_possession import in_possession_selected_instructions
from fm_analytics.analytics.in_transition import in_transition_selected_instructions
from fm_analytics.analytics.out_of_possession import out_of_possession_selected_instructions


@dataclass(frozen=True)
class GamePlan:
    key: str
    label: str
    summary: str


# In the order the pages list them.
GAME_PLANS: tuple[GamePlan, ...] = (
    GamePlan("possession", "Possession control", "Keeps the ball for long spells."),
    GamePlan("territorial", "Territorial control", "Plays in the opponent's half and wins the ball back quickly."),
    GamePlan("chance", "Chance control", "Attacks from a fixed rest defence, without countering or relying on the ball or territory."),
    GamePlan("direct", "Direct", "Plays the ball forward early without counter-attacking."),
    GamePlan("counter", "Counter-attack", "Breaks forward quickly when the ball is won."),
    GamePlan("low_block", "Low block", "Defends deep and lets the opponent come on."),
)
GAME_PLANS_BY_KEY = {plan.key: plan for plan in GAME_PLANS}

_SHORT_PASSING = ("Shorter Passing", "Much Shorter Passing")
_DIRECT_PASSING = ("Slightly More Direct Passing", "More Direct Passing", "Much More Direct Passing")
_PATIENCE = ("Lower Tempo", "Much Lower Tempo", "Slower Tempo", "Hold Shape", "Play Out Of Defence")
_HIGH = (
    "Higher Line of Engagement", "Much Higher Line of Engagement", "Higher Defensive Line",
    "Much Higher Defensive Line", "More Urgent Pressing", "Much More Urgent Pressing",
)
_DEEP = (
    "Lower Line of Engagement", "Drop Deeper Line of Engagement", "Much Lower Line of Engagement",
    "Drop Off More Defensive Line", "Much Deeper Defensive Line",
)
_DEEP_MENTALITIES = ("Very Defensive", "Defensive")
# A holder stays behind the ball: a midfield role that supplies rest defence
# without being sent to press (which rules out the ball-winners).
_HOLDER_POSITIONS = ("DM", "MC")
_HOLDER_MIN_REST_DEFENCE = 0.9
_HOLDER_MAX_PRESSING = 0.3


@dataclass(frozen=True)
class GamePlanLabel:
    plan: GamePlan
    # The settings (or roles) that earned the label, for the tactic page.
    reasons: tuple[str, ...]

    @property
    def key(self) -> str:
        return self.plan.key

    @property
    def label(self) -> str:
        return self.plan.label


def tactic_settings(tactic: TacticDefinition) -> tuple[str, ...]:
    """Every instruction the tactic selects, legacy and structured, by FM name."""
    selected = (
        tactic.instructions
        + in_possession_selected_instructions(tactic.in_possession)
        + in_transition_selected_instructions(tactic.in_transition)
        + out_of_possession_selected_instructions(tactic.out_of_possession)
    )
    return tuple(dict.fromkeys(selected))


def holders(tactic: TacticDefinition, catalogue: FootballCatalogue) -> tuple[str, ...]:
    """Names of the default roles that stay behind the ball in midfield."""
    names = []
    for slot in tactic.slots:
        role = catalogue.roles[slot.role_key]
        traits = role.system_traits
        if (
            slot.position in _HOLDER_POSITIONS
            and traits.get("restDefence", 0.0) >= _HOLDER_MIN_REST_DEFENCE
            and traits.get("pressing", 0.0) <= _HOLDER_MAX_PRESSING
        ):
            names.append(role.name)
    return tuple(names)


def game_plans(tactic: TacticDefinition, catalogue: FootballCatalogue) -> tuple[GamePlanLabel, ...]:
    """Every game plan the tactic follows, in `GAME_PLANS` order; may be empty."""
    settings = tactic_settings(tactic)

    def present(names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in settings if name in names)

    found: dict[str, tuple[str, ...]] = {}
    counter = "Counter" in settings
    if counter:
        found["counter"] = ("Counter when the ball is won",)
    deep = present(_DEEP)
    if deep or tactic.mentality in _DEEP_MENTALITIES:
        found["low_block"] = deep + ((f"{tactic.mentality} mentality",) if tactic.mentality in _DEEP_MENTALITIES else ())
    short, patience = present(_SHORT_PASSING), present(_PATIENCE)
    if short and patience:
        found["possession"] = short + patience
    high = present(_HIGH)
    if "Counter-Press" in settings and high:
        found["territorial"] = ("Counter-Press",) + high
    direct = present(_DIRECT_PASSING)
    if direct and not counter:
        found["direct"] = direct
    if not found.keys() & {"counter", "low_block", "possession", "territorial", "direct"}:
        holding = holders(tactic, catalogue)
        if holding and "Pass Into Space" not in settings:
            found["chance"] = tuple(f"{name} holds behind the ball" for name in dict.fromkeys(holding))
    return tuple(GamePlanLabel(plan, found[plan.key]) for plan in GAME_PLANS if plan.key in found)


def game_plan_keys(tactic: TacticDefinition, catalogue: FootballCatalogue) -> tuple[str, ...]:
    return tuple(label.key for label in game_plans(tactic, catalogue))
