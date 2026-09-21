#!/usr/bin/env python3
"""Seed each tactic's `attributeEmphasis` block from its instructions.

A one-off starting draft, deliberately soft. It runs once, its output is
committed as ordinary data in the tactic files, and from then on those blocks
are hand-owned -- re-running it would discard any tuning, so it refuses to
overwrite a tactic that already has a block unless asked.

The rules, and why (see docs/tactical-model-upgrade-plan.md 5.2):

* **Whole-team only.** One block with no `positions`, and never a slot-level
  block. Targeting positions or a single slot stays a purely human decision, so
  every such block in the tree is one somebody chose.
* **+2 on the 0-10 scale.** Measured: about one slot decision in twenty changes,
  each an improvement under that tactic's own priorities, while tactic ranking
  barely moves.
* **At most four attributes.** A tactic that emphasises everything emphasises
  nothing.
* Each instruction lists its attributes **most-defining first**, and a later one
  counts slightly less.
* An instruction counts for **more the rarer it is across the catalogue**. Half
  the tactics say "Regroup"; four say "Hit Early Crosses". Without this, every
  tactic's top four came out as the same handful of attributes that common
  instructions ask for, which is the opposite of the point: emphasis exists to
  capture what *this* tactic wants more than tactics in general. It is also
  what stopped an aerial crossing tactic emphasising positioning and first
  touch over heading and jumping reach.
* Attributes a role does not already weight are never introduced -- that is
  enforced by the scoring mechanism (`catalogue._emphasised`), not here.

Usage:  uv run python tools/seed_tactic_emphasis.py [--force] [--check]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

DELTA = 2
MAX_ATTRIBUTES = 4
TACTICS_DIR = (
    Path(__file__).resolve().parents[1]
    / "src" / "fm_analytics" / "analytics" / "data" / "tactics"
)

# What each instruction asks *of a player*, as opposed to what it asks of the
# eleven's shape (that is `tactical_system._INSTRUCTION_REQUIREMENTS`). These
# are declared football hypotheses and the seed's only input.
INSTRUCTION_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "Counter-Press": ("stamina", "workRate", "aggression"),
    "Much More Urgent Pressing": ("stamina", "workRate", "aggression"),
    "Prevent Short GK Distribution": ("workRate", "aggression"),
    "Much Higher Line of Engagement": ("stamina", "workRate", "anticipation"),
    "Higher Line of Engagement": ("stamina", "workRate", "anticipation"),
    "Higher Defensive Line": ("pace", "acceleration", "anticipation"),
    "Standard Line of Engagement": (),
    "Standard Defensive Line": (),
    "Lower Line of Engagement": ("positioning", "concentration"),
    "Drop Deeper Line of Engagement": ("positioning", "concentration"),
    "Much Lower Line of Engagement": ("positioning", "concentration", "marking"),
    "Drop Off More Defensive Line": ("positioning", "concentration"),
    "Much Deeper Defensive Line": ("positioning", "concentration", "marking"),
    "Regroup": ("positioning", "teamwork", "workRate"),
    "Hold Shape": ("positioning", "concentration", "teamwork"),
    "Play Out Of Defence": ("passing", "composure", "firstTouch", "technique"),
    "Shorter Passing": ("passing", "firstTouch", "technique"),
    "Slightly Shorter Passing": ("passing", "firstTouch"),
    "Slightly More Direct Passing": ("anticipation", "offTheBall"),
    "More Direct Passing": ("anticipation", "offTheBall"),
    "Much More Direct Passing": ("strength", "jumpingReach", "heading"),
    "Pass Into Space": ("offTheBall", "anticipation", "vision"),
    "Work Ball Into Box": ("composure", "decisions", "vision", "technique"),
    "Hit Early Crosses": ("crossing", "heading", "jumpingReach"),
    "Overlap Left": ("crossing", "stamina"),
    "Overlap Right": ("crossing", "stamina"),
    "Higher Tempo": ("firstTouch", "technique", "decisions", "agility"),
    "Lower Tempo": ("composure", "decisions"),
    "Slower Tempo": ("composure", "decisions"),
    "Counter": ("pace", "acceleration", "offTheBall"),
    "Fairly Wide": ("crossing", "pace"),
    "Fairly Narrow": ("teamwork", "firstTouch"),
    "Narrower": ("teamwork", "firstTouch"),
}


def instruction_rarity(documents: list[dict]) -> dict[str, float]:
    """How distinctive each instruction is: log(tactics / tactics using it)."""
    total = len(documents)
    uses: dict[str, int] = {}
    for document in documents:
        for instruction in set(document["instructions"]):
            uses[instruction] = uses.get(instruction, 0) + 1
    return {name: math.log(total / count) + 0.1 for name, count in uses.items()}


def emphasis_for(instructions: list[str], rarity: dict[str, float] | None = None) -> dict[str, int]:
    """The attributes this tactic's instructions ask for most, at +2 each.

    An attribute scores most where it leads the list of a *distinctive*
    instruction, less where it trails the list of a common one. Exact ties break
    on the name, so the seed is reproducible.
    """
    scores: dict[str, float] = {}
    for instruction in instructions:
        if instruction not in INSTRUCTION_ATTRIBUTES:
            raise SystemExit(
                f"instruction {instruction!r} has no attribute mapping; add one"
            )
        weight = 1.0 if rarity is None else rarity.get(instruction, 1.0)
        for position, attribute in enumerate(INSTRUCTION_ATTRIBUTES[instruction]):
            scores[attribute] = scores.get(attribute, 0.0) + weight * (1.0 - 0.1 * position)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return {name: DELTA for name, _ in ranked[:MAX_ATTRIBUTES]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing blocks, discarding any hand tuning")
    parser.add_argument("--check", action="store_true",
                        help="report what would change and exit non-zero if anything would")
    args = parser.parse_args(argv)

    paths = sorted(TACTICS_DIR.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in paths}
    rarity = instruction_rarity(list(documents.values()))

    stale = 0
    for path in paths:
        document = documents[path]
        seeded = emphasis_for(document["instructions"], rarity)
        existing = document.get("attributeEmphasis")
        if existing is not None and not args.force:
            if args.check and existing != [{"attributes": seeded}]:
                print(f"{path.stem}: hand-tuned ({existing}) differs from seed ({seeded})")
            continue
        if args.check:
            print(f"{path.stem}: would seed {seeded}")
            stale += 1
            continue
        out: dict[str, object] = {}
        for key, value in document.items():
            if key == "attributeEmphasis":
                continue
            out[key] = value
            if key == "instructionRationale":
                # One whole-team block: the seed never targets positions, so
                # every position-scoped block in the tree is one somebody chose.
                out["attributeEmphasis"] = [{"attributes": seeded}]
        assert "attributeEmphasis" in out, f"{path.stem} has no instructionRationale to anchor to"
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(f"{path.stem}: {seeded}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
