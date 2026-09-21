#!/usr/bin/env python3
"""Generate the one-page index of every tactic in the catalogue.

The index is *derived*, never hand-edited: the tactic files are the source of
truth and a second hand-maintained copy would drift from them within a week.
`tests/test_tactic_index.py` fails if the committed file is out of date, so
adding or editing a tactic means re-running this.

Usage:  uv run python tools/tactic_index.py [--check]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from fm_analytics.analytics.catalogue import MVP_CATALOGUE, TacticDefinition

OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "tactic-catalogue.md"

# Where each slot position belongs, for grouping eleven roles into four lines.
LINES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Goal", ("GK",)),
    ("Defence", ("DL", "DC", "DR", "WBL", "WBR")),
    ("Midfield", ("DM", "ML", "MC", "MR")),
    ("Attack", ("AML", "AMC", "AMR", "ST")),
)


def readable(attribute: str) -> str:
    """`offTheBall` -> `off the ball`."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", attribute).lower()


def roles_by_line(tactic: TacticDefinition) -> list[tuple[str, str]]:
    rows = []
    for line, positions in LINES:
        names: list[str] = []
        for slot in tactic.slots:
            if slot.position not in positions:
                continue
            name = MVP_CATALOGUE.roles[slot.role_key].name
            if slot.alternate_role_keys:
                name += " *"
            names.append(name)
        counted: list[str] = []
        for name in dict.fromkeys(names):
            total = names.count(name)
            counted.append(f"{name} ×{total}" if total > 1 else name)
        if counted:
            rows.append((line, ", ".join(counted)))
    return rows


def first_sentence(text: str) -> str:
    head = re.split(r"(?<=[.;])\s", text.strip(), maxsplit=1)[0]
    return head.rstrip(".;")


def render() -> str:
    tactics = sorted(MVP_CATALOGUE.tactics.values(), key=lambda t: (t.mentality, t.key))
    out: list[str] = [
        "# Tactic catalogue",
        "",
        "**Generated — do not edit.** Run `uv run python tools/tactic_index.py`",
        "after changing any tactic. Each tactic's full detail (per-slot reasoning,",
        "per-instruction rationale, balance requirements) lives in its own file under",
        "`src/fm_analytics/analytics/data/tactics/`.",
        "",
        f"{len(tactics)} tactics, {len(MVP_CATALOGUE.roles)} roles.",
        "",
        "## At a glance",
        "",
        "| Tactic | Shape | Mentality | Leans on | Use it when |",
        "| --- | --- | --- | --- | --- |",
    ]
    for tactic in tactics:
        leans = ", ".join(readable(a) for a in tactic.attribute_emphasis) or "—"
        out.append(
            f"| [{tactic.name}](#{tactic.key.replace('_', '-')}) | {tactic.formation} "
            f"| {tactic.mentality} | {leans} | {first_sentence(tactic.when_to_use)} |"
        )
    out += ["", "## Each tactic", ""]
    for tactic in tactics:
        out += [
            f"### {tactic.name}",
            "",
            f"`{tactic.key}` · {tactic.formation} · {tactic.mentality} · {tactic.style}",
            "",
            f"{tactic.description}",
            "",
        ]
        for line, names in roles_by_line(tactic):
            out.append(f"- **{line}:** {names}")
        out += [
            "",
            f"- **Leans on:** "
            + (", ".join(f"{readable(a)} {d:+d}" for a, d in tactic.attribute_emphasis.items()) or "—"),
            f"- **Needs:** " + ("; ".join(tactic.key_requirements) or "—"),
            f"- **Instructions:** " + ("; ".join(tactic.instructions) or "—"),
            f"- **Avoid when:** {first_sentence(tactic.when_not_to_use)}",
            "",
        ]
    out += [
        "`*` marks a slot whose role the optimiser may swap for a declared alternative.",
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit non-zero if out of date")
    args = parser.parse_args(argv)
    rendered = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(f"{OUTPUT.name} is out of date; run: uv run python tools/tactic_index.py")
            return 1
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(rendered.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
