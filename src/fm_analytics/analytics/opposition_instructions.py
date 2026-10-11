"""Suggested opposition instructions: FM's Opposition Instructions for their players, each with why.

Declared football rules of thumb applied to what FM shows (their matches, and
an attribute only when FM shows it for certain), never fitted to results. See
`suggest_instructions` for the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from fm_analytics.analytics.opponent_players import WIDE, PlayerLine
from fm_analytics.domain.models import Visibility

MAX_INSTRUCTIONS = 6


@dataclass(frozen=True)
class OppositionInstruction:
    """FM's opposition instructions for one of their players, with why."""

    player: str
    player_id: str | None
    position: str | None
    closing_down: str | None = None  # "More" or "Always"
    tackling: str | None = None  # "Ease off" or "Get stuck in"
    marking: str | None = None  # "Tight"
    show_onto: str | None = None  # "Weaker foot"
    reasons: tuple[str, ...] = ()

    @property
    def settings(self) -> tuple[tuple[str, str], ...]:
        """(FM's column, setting) for each instruction set, in FM's column order."""
        return tuple(
            (column, value) for column, value in (
                ("Closing down", self.closing_down), ("Tackling", self.tackling),
                ("Marking", self.marking), ("Show onto", self.show_onto),
            ) if value
        )


def _certain(player: PlayerLine, attribute: str) -> tuple[int, int] | None:
    """(lowest, highest) FM shows for an attribute: a known value is both; None when FM shows nothing."""
    seen = player.seen_attributes.get(attribute)
    if seen is None:
        return None
    if seen.visibility is Visibility.KNOWN and seen.value is not None:
        return seen.value, seen.value
    if seen.minimum is not None and seen.maximum is not None:
        return seen.minimum, seen.maximum
    return None


def _shown(player: PlayerLine, attribute: str, label: str) -> str:
    low, high = _certain(player, attribute) or (None, None)
    return f"{label} {low}" if low == high else f"{label} {low}-{high}"


def _foot_words(player: PlayerLine) -> str | None:
    """None when he has no weaker foot to show him onto, as far as FM shows."""
    if player.foot and player.foot.casefold() in ("either", "both"):
        return None
    if player.foot and player.foot.casefold() in ("left", "right"):
        weaker = "right" if player.foot.casefold() == "left" else "left"
        return f"He is {player.foot.casefold()}-footed: show him onto his {weaker}."
    return ""


def suggest_instructions(players: Sequence[PlayerLine]) -> tuple[OppositionInstruction, ...]:
    """Suggested opposition instructions, from declared rules on what FM's matches and screens show.

    These are football rules of thumb applied to evidence, not fitted to
    results. Only players likely to play (`PlayerLine.likely`) get one, never
    their goalkeeper, and at most `MAX_INSTRUCTIONS`, in the order below:

    * **their goal threat** (at least 2 non-penalty goals and a fifth of the
      team's, or the top scorer with 3): tight marking. Mostly headers: the
      marking matters most at crosses. Mostly struck with the foot: show him
      onto his weaker foot, unless FM shows him as two-footed.
    * **a shooter** (3+ shots a match): tight marking, so he shoots under pressure.
    * **their supplier** (2+ assists and a fifth of the team's, or the team's
      most chances created with at least one a match): close him down, always
      when he plays centrally (a playmaker given time picks the pass); a wide
      supplier more, shown onto his weaker foot so the cross comes from it. A
      supplier whose assists were mostly crosses that may have been his corners
      is left out: closing him down does nothing at a corner.
    * **a dribbler** (the team's most dribbles, at least 3 a match): ease off
      tackles (diving in against him gives away fouls and penalties) and show
      him onto his weaker foot.
    * **what FM shows of him** (certain values only: a range's top or a known
      value): composure or first touch of 8 or less, close him down always and
      get stuck in, since he is uncomfortable under pressure. Given to a player
      already named above, and to at most two more, the lowest first. A
      striker is not closed down (it pulls a centre-back out of the line), and
      a dribbler keeps "ease off".
    """
    candidates = [line for line in players if line.likely and line.position != "GK"]
    non_penalty_total = sum(line.goals - line.penalties for line in players)
    assist_total = sum(line.assists for line in players)
    found: dict[int, dict] = {}

    def add(line: PlayerLine, reason: str, **settings: str) -> None:
        entry = found.setdefault(line.short_id, {"line": line, "reasons": [], "order": len(found)})
        for key, value in settings.items():
            current = entry.get(key)
            if key == "closing_down" and current == "Always":
                continue
            if key == "tackling" and current == "Ease off":
                continue
            entry[key] = value
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    top_scorer = max(candidates, key=lambda line: (line.goals - line.penalties, line.shots), default=None)
    for line in sorted(candidates, key=lambda line: -(line.goals - line.penalties)):
        open_goals = line.goals - line.penalties
        if open_goals >= 2 and (non_penalty_total and open_goals / non_penalty_total >= 0.2 or
                                line is top_scorer and open_goals >= 3):
            headers = line.headed_goals
            add(line, f"Scored {open_goals} of their {non_penalty_total} non-penalty goals in "
                      f"{line.minutes:,} minutes.", marking="Tight")
            if headers * 2 >= open_goals:
                add(line, f"{headers} of his {open_goals} were headers: the marking matters most at crosses and set pieces.")
            elif open_goals - headers >= 2:
                foot = _foot_words(line)
                if foot is not None:
                    add(line, f"{open_goals - headers} of his goals were struck with his foot. " + (foot or
                              "Showing him onto his weaker foot makes the shot harder."), show_onto="Weaker foot")
    for line in candidates:
        rate = line.per90(line.shots)
        if rate is not None and rate >= 3.0:
            add(line, f"Shoots {rate:.1f} times a match ({line.shots} shots, {line.shots_on_target} on target).",
                marking="Tight")
    creators = [line for line in candidates if line.per90(line.chances_created) is not None]
    top_creator = max(creators, key=lambda line: line.per90(line.chances_created) or 0, default=None)
    for line in candidates:
        supplies = line.assists >= 2 and assist_total and line.assists / assist_total >= 0.2
        creates = line is top_creator and (line.per90(line.chances_created) or 0) >= 1.0
        if not (supplies or creates):
            continue
        if supplies and not creates and line.assists_possibly_corners * 2 > line.assists:
            continue  # his assists were mostly crosses that may have been his corners
        evidence = (f"Set up {line.assists} of their {assist_total} assisted goals"
                    + (f", {line.assists_from_crosses} from crosses" if line.assists_from_crosses else "")
                    + f"; {line.chances_created} chances created in {line.minutes:,} minutes.")
        if line.position == "ST":
            add(line, evidence, marking="Tight")
        elif line.position in WIDE:
            foot = _foot_words(line)
            add(line, evidence, closing_down="More")
            if foot is not None:
                add(line, "A wide supplier: " + (foot or "showing him onto his weaker foot makes the cross harder."),
                    show_onto="Weaker foot")
        else:
            add(line, evidence + " Given time on the ball, a playmaker picks the pass.", closing_down="Always")
    dribblers = [line for line in candidates if (line.per90(line.dribbles) or 0) >= 3.0]
    if dribblers:
        line = max(dribblers, key=lambda item: item.per90(item.dribbles) or 0)
        reason = f"Dribbles {line.per90(line.dribbles):.1f} times a match: diving in gives away fouls near the box."
        if (_certain(line, "dribbling") or (0, 0))[0] >= 14:
            reason += f" FM shows {_shown(line, 'dribbling', 'dribbling')}."
        add(line, reason, tackling="Ease off")
        foot = _foot_words(line)
        if foot is not None and found[line.short_id].get("show_onto") is None:
            add(line, foot or "Showing him onto his weaker foot narrows where he can go.", show_onto="Weaker foot")
    pressured = []
    for line in candidates:
        weakest = min(
            ((seen[1], attribute, label) for attribute, label in (("composure", "composure"), ("firstTouch", "first touch"))
             if (seen := _certain(line, attribute)) is not None and seen[1] <= 8),
            default=None,
        )
        if weakest is not None:
            pressured.append((line.short_id not in found, weakest[0], -line.recent_starts, line, weakest))
    extra = 0
    for new, _top, _starts, line, (_value, attribute, label) in sorted(pressured, key=lambda item: item[:3]):
        if new:
            if extra >= 2:
                continue
            extra += 1
        reason = f"FM shows {_shown(line, attribute, label)}: he is uncomfortable when pressed."
        if line.position == "ST":
            add(line, reason, tackling="Get stuck in")
        else:
            add(line, reason, closing_down="Always", tackling="Get stuck in")
    entries = sorted(found.values(), key=lambda entry: entry["order"])[:MAX_INSTRUCTIONS]
    return tuple(
        OppositionInstruction(
            player=entry["line"].name,
            player_id=entry["line"].player_id,
            position=entry["line"].position,
            closing_down=entry.get("closing_down"),
            tackling=entry.get("tackling"),
            marking=entry.get("marking"),
            show_onto=entry.get("show_onto"),
            reasons=tuple(entry["reasons"]),
        )
        for entry in entries
    )
