"""Manager-facing text helpers shared by the web page renderers."""

from __future__ import annotations

import html
import re
from typing import Sequence

from fm_analytics.analytics import MVP_CATALOGUE, TacticDefinition, TacticSlot

_NAV_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("Overview", (("/", "Command centre", "⌂"), ("/league", "League", "≋"))),
    ("Squad intelligence", (("/squad", "Squad", "◫"), ("/roles", "Roles", "◎"), ("/depth", "Depth", "↕"), ("/contracts", "Contracts", "✎"))),
    ("Matchday", (("/tactics", "Tactics", "⌁"), ("/tactic-checks", "Tactic checks", "✓"), ("/set-pieces", "Set pieces", "✦"), ("/matches", "Matches", "▤"),
                  ("/experiments", "Experiments", "⚗"))),
    ("Recruitment", (("/scouting", "Scouting", "⌕"),)),
    ("System", (("/data", "Data health", "◌"),)),
)

_TACTICAL_DIMENSION_LABELS = {
    "aerialOutlet": "aerial outlet",
    "attack duties": "attacking duties",
    "ballProgression": "moving the ball forward",
    "boxPresence": "players getting into the box",
    "creativity": "creative roles",
    "creators": "creative roles",
    "defensiveCover": "defensive cover",
    "penetration": "forward threat",
    "pressing": "players applying pressure",
    "restDefence": "cover when possession is lost",
    "runners": "players making forward runs",
    "width": "width",
}

def _navigation(active_path: str) -> tuple[dict[str, object], ...]:
    """Group the navigation around a manager's recurring decisions."""
    return tuple(
        {
            "label": group_label,
            "items": tuple(
                {
                    "path": path,
                    "label": label,
                    "icon": icon,
                    "active": _is_navigation_active(path, active_path),
                }
                for path, label, icon in items
            ),
        }
        for group_label, items in _NAV_GROUPS
    )


def _section_for(active_path: str) -> str:
    for group_label, items in _NAV_GROUPS:
        if any(_is_navigation_active(path, active_path) for path, _label, _icon in items):
            return group_label
    return "FM Analytics"


def _is_navigation_active(path: str, active_path: str) -> bool:
    """Keep a section selected while the manager is in one of its drill-downs."""
    return path == active_path or (path != "/" and active_path.startswith(path + "/"))


def _tactical_shortfalls(shortfalls: Sequence[str]) -> str:
    """Turn compact model diagnostics into short manager-facing phrases."""
    labels: list[str] = []
    for shortfall in shortfalls:
        dimension, _separator, _amounts = shortfall.rpartition(" ")
        labels.append(_TACTICAL_DIMENSION_LABELS.get(dimension, dimension))
    displayed = labels[:2]
    remainder = len(labels) - len(displayed)
    suffix = f" +{remainder} more" if remainder else ""
    return ", ".join(displayed) + suffix


def _tactic_notes(tactic: TacticDefinition) -> str:
    """Render the catalogue author's own explanation of a tactic, if given.

    These fields (style/description/whyGood/keyRequirements/tags and the
    shape/usage/instruction justifications) are manager-facing commentary
    carried alongside the tactic in the catalogue data, not scoring input --
    a tactic with none of them still renders correctly, since older catalogue
    entries may not define any.
    """
    if not any(
        (
            tactic.style, tactic.description, tactic.why_good, tactic.key_requirements,
            tactic.tags, tactic.why_this_shape, tactic.when_to_use, tactic.when_not_to_use,
            tactic.instruction_rationale, tactic.attribute_emphasis, tactic.attribute_taper,
        )
    ):
        return ""
    parts = []
    if tactic.style:
        parts.append(f"<p><b>{html.escape(tactic.style)}</b></p>")
    if tactic.description:
        parts.append(f"<p>{html.escape(tactic.description)}</p>")
    if tactic.why_this_shape:
        parts.append(f"<p><b>Why this shape:</b> {html.escape(tactic.why_this_shape)}</p>")
    if tactic.when_to_use:
        parts.append(f"<p><b>When to use it:</b> {html.escape(tactic.when_to_use)}</p>")
    if tactic.when_not_to_use:
        parts.append(f"<p><b>When to avoid it:</b> {html.escape(tactic.when_not_to_use)}</p>")
    if tactic.why_good:
        parts.append(f"<p class='muted'><b>Why it works:</b> {html.escape(tactic.why_good)}</p>")
    if tactic.key_requirements:
        parts.append(
            "<p class='muted'><b>Needs:</b> "
            + ", ".join(html.escape(item) for item in tactic.key_requirements)
            + "</p>"
        )
    if tactic.attribute_emphasis:
        scopes = []
        for block in sorted(
            tactic.attribute_emphasis, key=lambda b: bool(b.positions or b.roles)
        ):
            attributes = ", ".join(
                f"{html.escape(_readable_attribute(name))} {delta:+d}"
                + (" <span class='muted'>(new requirement)</span>"
                   if name in block.introduce_attributes else "")
                for name, delta in block.attributes.items()
            )
            where_parts = []
            if block.positions:
                where_parts.append(", ".join(block.positions))
            if block.roles:
                where_parts.append(
                    ", ".join(MVP_CATALOGUE.roles[key].name for key in block.roles)
                )
            if not where_parts:
                where_parts.append("whole team")
            where = html.escape("; ".join(where_parts))
            scopes.append(f"{attributes} <span class='muted'>({where})</span>")
        parts.append(
            f"<p class='muted'><b>Leans on:</b> {'; '.join(scopes)}. "
            "Role fit on this page is scored with these attributes weighted a little "
            "differently from the same role in another tactic.</p>"
        )
    if tactic.attribute_taper:
        def taper_scope(taper) -> str:
            parts = []
            if taper.positions:
                parts.append(", ".join(taper.positions))
            if taper.roles:
                parts.append(
                    ", ".join(
                        MVP_CATALOGUE.roles[role_key].name for role_key in taper.roles
                    )
                )
            if not parts:
                parts.append("whole team")
            return "; ".join(parts)

        levels = "; ".join(
            f"{html.escape(_readable_attribute(t.attribute))} {t.below}"
            f" <span class='muted'>({html.escape(taper_scope(t))})</span>"
            for t in tactic.attribute_taper
        )
        parts.append(
            f"<p class='muted'><b>Expects at least:</b> {levels}. This is a taper, not a "
            "cut-off: a player below a level loses fit gradually the further he falls "
            "short, and can still be selected if the rest of his game is strong.</p>"
        )
    if tactic.instruction_rationale:
        items = "".join(
            f"<li><b>{html.escape(instruction)}</b> — {html.escape(reason)}</li>"
            for instruction, reason in tactic.instruction_rationale.items()
        )
        parts.append(
            "<details><summary>Why these instructions</summary>"
            f"<ul>{items}</ul></details>"
        )
    if tactic.tags:
        parts.append(
            "<p>"
            + " ".join(f"<span class='tag'>{html.escape(tag)}</span>" for tag in tactic.tags)
            + "</p>"
        )
    return "<div class='tactic-rationale-grid'>" + "".join(parts) + "</div>"


def _readable_attribute(name: str) -> str:
    """`offTheBall` -> `off the ball`, for manager-facing text."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).lower()


def _slot_reasoning(slot: TacticSlot, chosen_role_key: str, chosen_role_name: str) -> str:
    """Why this tactic has this role in this slot, if the catalogue says.

    The text is written for the slot's default role. When the optimiser picked
    an alternate instead, say so rather than presenting the default's
    reasoning as if it described the chosen role.
    """
    if not slot.why:
        return ""
    note = ""
    if chosen_role_key != slot.role_key:
        note = (
            f" <span class='muted'>(Your squad suits {html.escape(chosen_role_name)} here "
            "better than this slot's default role, so the reasoning above is for the "
            "default.)</span>"
        )
    return f"<p class='slot-why'><b>Why this role here:</b> {html.escape(slot.why)}{note}</p>"


def _raw_position_notice(candidates: Sequence[object]) -> str:
    raw_count = sum(bool(getattr(candidate, "raw_positions", ())) for candidate in candidates)
    if raw_count == 0:
        return (
            "<p class='warn'><b>Raw external positions enabled, but unavailable.</b> "
            "This capture has no raw position labels yet. Recapture the scouting feed "
            "and reload this page.</p>"
        )
    return (
        "<p class='warn'><b>Raw external positions enabled.</b> These labels are "
        "derived from non-owned players' raw position data under the accepted short-"
        "term visibility gap, and so are the players' individual position ratings "
        "used for the familiarity columns. They can reveal secondary positions and "
        "ratings FM does not currently show the manager "
        f"({raw_count} captured).</p>"
    )


# A dropped player remains listed, but only the knowledge percentage here is
# last-known. Attribute history is separated from current scoring/display by
# the scouting feed and labelled with its observation date on scouting pages.
DROPPED_FROM_SCOUT_REPORTS_MESSAGE = (
    "This player used to be in the scouted pool but can't be found in the "
    "scout reports anymore."
)


def _scouting_knowledge_cell(candidate: object) -> str:
    knowledge = getattr(candidate, "scouting_knowledge", None)
    if knowledge is None:
        return "—"
    if not getattr(candidate, "in_current_feed", True):
        return f"{knowledge}% <span class='muted'>(last known)</span>"
    if getattr(candidate, "dropped_from_scout_reports", False):
        return (
            f"{knowledge}% <span class='muted'>(last known)</span><br>"
            f"<span class='dropped-warning'>{html.escape(DROPPED_FROM_SCOUT_REPORTS_MESSAGE)}</span>"
        )
    if getattr(candidate, "has_scout_report", None) is False:
        # Known some other way -- a trial, a past opponent -- so not on FM's
        # Scouted list, though the attributes FM shows are just as real.
        return f"{knowledge}% <span class='muted'>(no report)</span>"
    return f"{knowledge}%"


def _position_display(candidate, *, include_raw_external_positions: bool) -> str:
    positions = candidate.positions_for(
        include_raw_external_positions=include_raw_external_positions
    )
    return html.escape(", ".join(positions) or "Not yet captured")
