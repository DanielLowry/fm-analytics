"""Full attribute schemas and manager-visible records for spreadsheet exports."""
from __future__ import annotations

import html
import json

from fm_analytics.analytics.scouting import _plays_in_goal
from fm_analytics.web.ui import ordered_positions


ATTRIBUTE_GROUPS = (
    ("Technical", (
        "corners", "crossing", "dribbling", "finishing", "firstTouch", "freeKickTaking",
        "heading", "longShots", "longThrows", "marking", "passing", "penaltyTaking", "tackling", "technique",
    )),
    ("Mental", (
        "aggression", "anticipation", "bravery", "composure", "concentration", "decisions",
        "determination", "flair", "leadership", "offTheBall", "positioning", "teamwork", "vision", "workRate",
    )),
    ("Physical", (
        "acceleration", "agility", "balance", "jumpingReach", "naturalFitness", "pace", "stamina", "strength",
    )),
    ("Goalkeeping", (
        "aerialReach", "commandOfArea", "communication", "eccentricity", "handling", "kicking",
        "oneOnOnes", "reflexes", "rushingOut", "tendencyToPunch", "throwing",
    )),
)
_LABELS = {
    "firstTouch": "First Touch", "freeKickTaking": "Free Kick Taking", "longShots": "Long Shots",
    "longThrows": "Long Throws", "penaltyTaking": "Penalty Taking", "offTheBall": "Off The Ball",
    "workRate": "Work Rate", "jumpingReach": "Jumping Reach", "naturalFitness": "Natural Fitness",
    "aerialReach": "Aerial Reach", "commandOfArea": "Command Of Area", "oneOnOnes": "One On Ones",
    "rushingOut": "Rushing Out", "tendencyToPunch": "Tendency To Punch",
}
FAMILIARITY_POSITIONS = ordered_positions((
    "GK", "SW", "DL", "DC", "DR", "WBL", "WBR", "DM", "ML", "MC", "MR", "AML", "AMC", "AMR", "ST",
))


def attribute_label(key):
    return _LABELS.get(key, key.capitalize())


def export_schema():
    groups = dict(ATTRIBUTE_GROUPS)
    outfield = groups["Technical"] + groups["Mental"] + groups["Physical"]
    goalkeeper = groups["Goalkeeping"] + (
        "firstTouch", "freeKickTaking", "passing", "penaltyTaking", "technique",
    ) + groups["Mental"] + groups["Physical"]
    return {
        "attributes": {family: [[key, attribute_label(key)] for key in keys]
                       for family, keys in (("outfield", outfield), ("goalkeeper", goalkeeper))},
        "positions": FAMILIARITY_POSITIONS,
    }


def player_export_record(name, age, attributes, positions, familiarity, *, club=None,
                         familiarity_source="Not captured", observed_on=None, readings=None):
    positions = ordered_positions(positions)
    if positions:
        families = (["goalkeeper"] if "GK" in positions else []) + (
            ["outfield"] if any(p != "GK" for p in positions) else []
        )
    else:
        keeper = _plays_in_goal(attributes)
        families = ["goalkeeper"] if keeper is True else ["outfield"] if keeper is False else ["outfield", "goalkeeper"]
    return {
        "name": name, "age": age, "club": club, "positions": list(positions), "families": families,
        "familiarity": dict(familiarity), "familiaritySource": familiarity_source,
        "observedOn": observed_on,
        "attributes": {key: observation.display() for key, observation in attributes.items()},
        "historical": {key: reading.last_seen_on for key, reading in (readings or {}).items()},
    }


def candidate_export_record(candidate, *, include_raw_positions=False):
    return player_export_record(
        candidate.name, candidate.age, candidate.attributes,
        candidate.positions_for(include_raw_external_positions=include_raw_positions),
        (candidate.raw_position_familiarity or {}) if include_raw_positions else {},
        club=candidate.club, observed_on=candidate.attributes_observed_at,
        familiarity_source="Raw scouting ratings (0–20)" if include_raw_positions else "Raw positions not enabled",
        readings=candidate.history.attributes if candidate.history else None,
    )


def player_copy_text(record):
    """A readable full-player profile using the same observations as exports."""
    lines = [f"{label}: {record[key] if record[key] is not None else '?'}"
             for label, key in (("Name", "name"), ("Age", "age"), ("Club", "club"))]
    lines.extend(("", "Positional Familiarity"))
    familiarity = record["familiarity"]
    positions = [position for position in ordered_positions(familiarity) if familiarity[position] != 1]
    lines.extend(f"{position}: {familiarity[position]}/20" for position in positions)
    if not positions:
        lines.append("None" if familiarity else "?")

    schema = export_schema()["attributes"]
    relevant = {key for family in record["families"] for key, _label in schema[family]}
    for title, keys in ATTRIBUTE_GROUPS:
        keys = [key for key in keys if key in relevant]
        if not keys:
            continue
        lines.extend(("", title))
        for key in keys:
            value = record["attributes"].get(key, "?")
            last_seen = record["historical"].get(key)
            if last_seen:
                value += f" (historical; last seen {last_seen})"
            lines.append(f"{attribute_label(key)}: {value}")
    return "\n".join(lines)


def player_copy_control(record):
    source = json.dumps(player_copy_text(record), ensure_ascii=True).replace("<", "\\u003c")
    return (
        "<div class='fm-table-toolbar' data-player-copy>"
        "<button type='button' class='fm-table-copy' disabled>Copy player to clipboard</button>"
        "<span class='fm-table-copy-status' role='status' aria-live='polite'></span>"
        "<script type='application/json' data-player-copy-text>" + source + "</script>"
        "<noscript>Enable JavaScript to copy the player.</noscript></div>"
    )


def export_controls(*, records=None):
    """Buttons use the live filtered list, or a report's fixed single record."""
    payload = {"schema": export_schema()}
    if records is not None:
        payload["rows"] = records
    source = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")
    buttons = "".join(
        f"<button type='button' class='fm-table-copy' data-export-family='{family}' "
        f"data-export-format='{fmt}' disabled>{html.escape(action)} {label} attributes</button>"
        for family, label in (("outfield", "outfield"), ("goalkeeper", "goalkeeper"))
        for fmt, action in (("tsv", "Copy"), ("csv", "Download CSV ·"))
    )
    return (
        "<section class='fm-workspace-panel fm-attribute-export' data-attribute-export>"
        "<h3>Export full player attributes</h3>"
        "<p class='muted'>Includes name, age, club, positions and captured familiarity. "
        + ("Exports every matching player in the current sort order, including those beyond Show more. "
           "Enable raw external positions above to include scouting familiarity. " if records is None else "")
        + "Ranges remain ranges; unknown values are ?. Remembered attributes are dated. "
        "Players whose outfield/goalkeeper type is unknown appear in both formats.</p>"
        "<div class='fm-table-toolbar'>" + buttons
        + "<span class='fm-table-copy-status' role='status' aria-live='polite'></span></div>"
        "<script type='application/json' data-export-schema>" + source + "</script>"
        "<noscript><p>Enable JavaScript to copy or download attributes.</p></noscript></section>"
    )
