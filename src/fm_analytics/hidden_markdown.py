"""The League page's hidden view as one Markdown document: its "Copy the whole page" button. HIDDEN DATA.

Serialisation only: every figure comes from `analytics.hidden_strength`, the
same report the page shows, section by section and with both XIs of every
match, so it can be pasted whole into notes or a chat. Marks the page draws
with CSS (a nearest-shape *, a unit's rank) are written out here.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from fm_analytics.analytics.hidden_strength import (
    MATCHUPS,
    UNITS,
    HiddenStrength,
    OurMatch,
    XiStrength,
)
from fm_analytics.hidden_export import WARNING

_UNIT_HEAD = [name for _key, name, _positions in UNITS]


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(head: Sequence[str], rows: Iterable[Sequence], foot: Sequence | None = None) -> str:
    lines = ["| " + " | ".join(_cell(item) for item in head) + " |", "|" + " --- |" * len(head)]
    lines += ["| " + " | ".join(_cell(item) for item in row) + " |" for row in rows]
    if foot:
        lines.append("| " + " | ".join(f"**{_cell(item)}**" if item != "" else "" for item in foot) + " |")
    return "\n".join(lines)


def _score(value: float | None, places: int = 1) -> str:
    return "—" if value is None else f"{value:.{places}f}"


def _signed(value: float | None, places: int = 1) -> str:
    if value is None:
        return "—"
    text = f"{value:+.{places}f}"
    return text[1:] if float(text) == 0 else text


def _ordinal(rank: int | None) -> str:
    if rank is None:
        return "—"
    return f"{rank}" + ("th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th"))


def _xi(xi: XiStrength) -> str:
    """An XI's score with the page's marks spelled out: * nearest shape, † players out of position."""
    if xi.score is None:
        return "—"
    return f"{xi.score:.1f}" + ("*" if not xi.exact_shape else "") + ("†" if xi.out_of_position else "")


def _units(units, ranks) -> list[str]:
    return [f"{units[key]:.1f} ({_ordinal(ranks.get(key))})" if key in units else "—" for key, _name, _p in UNITS]


def _result(row: OurMatch) -> str:
    return ("W" if row.points == 3 else "D" if row.points == 1 else "L") + f" {row.goals_for}-{row.goals_against}"


def _verdict(report: HiddenStrength) -> list[str]:
    verdict = report.verdict
    if verdict is None:
        return ["Not enough league matches have both line-ups scored to say how strength turns into results yet."]
    reading = {"better": "better than the players explain, by more than the usual run of luck",
               "worse": "worse than the players explain, by more than the usual run of luck",
               "in line": "in line with the squad: within the usual run of luck"}[verdict.reading]
    tactic = report.tactic_names.get(verdict.best_tactic, "")
    lines = [f"- **Results are {reading}.** {verdict.points} points from {verdict.played} league matches "
             f"({_ordinal(verdict.points_rank)} of {verdict.clubs} on points) against {verdict.expected_points:.1f} "
             f"expected from the XIs fielded ({_signed(verdict.points_gap)}; usual run of luck ±{verdict.spread:.1f})."]
    if verdict.recent_played:
        lines.append(f"- Last {verdict.recent_played}: {verdict.recent_points} points against "
                     f"{verdict.recent_expected:.1f} expected (usual run of luck ±{verdict.recent_spread:.1f}).")
    lines.append(f"- XIs fielded: {_ordinal(verdict.fielded_rank)} of {verdict.clubs} by average XI score. Best XI"
                 + (f" in {tactic}" if tactic else "") + f": {_ordinal(verdict.best_rank)} of {verdict.clubs}.")
    if verdict.fielded_unit_ranks:
        lines.append("- By unit, XIs fielded: " + ", ".join(
            f"{name.lower()} {_ordinal(verdict.fielded_unit_ranks[key])}" for key, name, _p in UNITS
            if key in verdict.fielded_unit_ranks) + f" of {verdict.clubs}.")
    if verdict.best_unit_ranks:
        lines.append(f"- By unit, best XI{f' in {tactic}' if tactic else ''}: " + ", ".join(
            f"{name.lower()} {_ordinal(verdict.best_unit_ranks[key])}" for key, name, _p in UNITS
            if key in verdict.best_unit_ranks) + f" of {verdict.clubs}.")
    return lines


def _our_matches(report: HiddenStrength) -> str:
    rows = [[row.match.date.isoformat(), row.match.competition.label, row.opponent.name,
             "H" if row.side == "home" else "A", _result(row), row.points, _score(row.expected_points, 2),
             _signed(None if row.expected_points is None else row.points - row.expected_points, 2),
             _xi(row.ours), _xi(row.theirs), _signed(row.gap), row.our_formation, row.their_formation]
            for row in report.our_matches]
    totals = report.our_totals
    foot = None if totals is None else [
        f"League, {totals.matches} matches", "", "", "", "", totals.points, f"{totals.expected_points:.1f}",
        _signed(totals.points - totals.expected_points), f"{totals.our_xi:.1f}", f"{totals.their_xi:.1f}",
        _signed(totals.gap), "", ""]
    return _table(["Date", "Competition", "Opponent", "Venue", "Result", "Pts", "Expected pts", "Pts - expected",
                   "Our XI", "Their XI", "Gap", "Our formation", "Their formation"], rows, foot)


def _tactics(report: HiddenStrength) -> str:
    keys = report.compared_tactics
    if not keys:
        return "No match of ours this season has a known tactic."
    used, main = dict(report.our_tactics), keys[0]
    ours = next((row for row in report.by_tactic if row.ours), None)
    mine = ours.xis[main].score if ours else None
    ordered = sorted(report.by_tactic, key=lambda row: (row.xis[main].score is None, -(row.xis[main].score or 0),
                                                        row.club.name))
    rows = [[rank if row.xis[main].score is not None else "—", row.club.name + (" (you)" if row.ours else ""),
             *(_xi(row.xis[key]) for key in keys),
             "" if row.ours or mine is None or row.xis[main].score is None else _signed(mine - row.xis[main].score),
             row.squad_size] for rank, row in enumerate(ordered, 1)]
    head = ["Rank", "Club", *(f"{report.tactic_names[key]} ({used[key]} of our matches)" if key in used
                              else f"{report.tactic_names[key]} (picked)" for key in keys),
            f"You vs them in {report.tactic_names[main]}", "Squad"]
    return _table(head, rows)


def _formations(report: HiddenStrength) -> str:
    ours = next((row for row in report.by_formation if row.ours), None)
    mine = ours.best.score if ours and ours.best else None
    ordered = sorted(report.by_formation, key=lambda row: (row.best is None or row.best.score is None,
                                                           -(row.best.score or 0) if row.best else 0, row.club.name))
    rows = []
    for rank, row in enumerate(ordered, 1):
        score = row.best.score if row.best else None
        rows.append([rank if score is not None else "—", row.club.name + (" (you)" if row.ours else ""),
                     ", ".join(f"{use.name} x{use.matches}" + ("" if use.exact else "*") for use in row.formations) or "—",
                     _xi(row.best) if row.best else "—", (row.best.tactic_name or "—") if row.best else "—",
                     row.best_formation or "—", "" if row.ours or mine is None or score is None else _signed(mine - score)])
    return _table(["Rank", "Club", "Formations played (league matches)", "Best XI", "Scored in",
                   "From their formation", "You vs them"], rows)


def _results(report: HiddenStrength) -> str:
    model = report.model
    if model is None:
        return (f"Only {report.league_scored} league matches have both line-ups scored: too few to say how strength "
                "turns into results.")
    rows = [[position, row.club.name + (" (you)" if row.ours else ""), row.played, row.points,
             f"{row.expected_points:.1f}", _signed(row.points_gap), f"{row.goals_for}-{row.goals_against}",
             f"{row.expected_for:.1f}-{row.expected_against:.1f}",
             _signed(row.goals_for - row.goals_against - (row.expected_for - row.expected_against)),
             f"{row.average_xi:.1f}", f"{row.average_opponent_xi:.1f}"] for position, row in enumerate(report.clubs, 1)]
    return _table(["Rank", "Club", "P", "Pts", "Expected pts", "Pts - expected", "Goals", "Expected goals",
                   "GD - expected", "Average XI fielded", "Average opposition XI"], rows)


def _units_section(report: HiddenStrength) -> list[str]:
    parts = []
    if report.clubs:
        ordered = sorted(report.clubs, key=lambda row: (-row.average_xi, row.club.name))
        parts += ["### The XIs each club has fielded (league average; rank in brackets)", _table(
            ["Rank", "Club", *_UNIT_HEAD, "Whole XI"],
            [[rank, row.club.name + (" (you)" if row.ours else ""),
              *_units(row.average_units, report.fielded_unit_ranks.get(row.club.id, {})), f"{row.average_xi:.1f}"]
             for rank, row in enumerate(ordered, 1)])]
    if report.compared_tactics:
        main = report.compared_tactics[0]
        ordered = sorted(report.by_tactic, key=lambda row: (row.xis[main].score is None, -(row.xis[main].score or 0),
                                                            row.club.name))
        parts += [f"### Each club's best XI in {report.tactic_names[main]} (rank in brackets)", _table(
            ["Rank", "Club", *_UNIT_HEAD, "Whole XI"],
            [[rank if row.xis[main].score is not None else "—", row.club.name + (" (you)" if row.ours else ""),
              *_units(row.xis[main].units, report.best_unit_ranks.get(row.club.id, {})), _xi(row.xis[main])]
             for rank, row in enumerate(ordered, 1)])]
    totals = report.our_totals
    foot = None if totals is None else [
        f"League average, {totals.matches} matches", "", "", "",
        *(_signed(totals.unit_gaps.get(key)) for key, _name, _p in UNITS),
        *(_signed(totals.matchups.get(key)) for key, _mine, _theirs in MATCHUPS)]
    parts += ["### Our matches, unit against unit (ours minus theirs)", _table(
        ["Date", "Opponent", "Venue", "Result", *_UNIT_HEAD, "Our defence vs their attack", "Our attack vs their defence"],
        [[row.match.date.isoformat(), row.opponent.name, "H" if row.side == "home" else "A", _result(row),
          *(_signed(row.unit_gap(key)) for key, _name, _p in UNITS),
          *(_signed(row.matchups[key]) for key, _mine, _theirs in MATCHUPS)] for row in report.our_matches], foot)]
    return parts


def _line_up(row: OurMatch) -> str:
    def describe(xi: XiStrength, heading: str) -> str:
        if xi.score is None:
            return f"{heading}: not scored ({'; '.join(xi.missing) or 'not scored'})"
        return (f"{heading} {xi.score:.1f}, scored in {xi.tactic_name}"
                + ("" if xi.exact_shape else " (the nearest shape our tactics have)"))

    ours, theirs = row.ours.players, row.theirs.players
    rows = []
    for index in range(max(len(ours), len(theirs))):
        left = ours[index] if index < len(ours) else None
        right = theirs[index] if index < len(theirs) else None
        rows.append([*((left.position, left.name, left.role_name, f"{left.score:.1f}") if left else ("",) * 4),
                     *((right.position, right.name, right.role_name, f"{right.score:.1f}") if right else ("",) * 4)])
    heading = (f"### {row.match.date.isoformat()} · {row.opponent.name} ({'H' if row.side == 'home' else 'A'}) "
               f"{row.goals_for}-{row.goals_against}")
    body = f"{describe(row.ours, 'Our XI')} · {describe(row.theirs, 'Their XI')}"
    if rows:
        body += "\n\n" + _table(["Pos", "Our player", "Role", "Score", "Pos", "Their player", "Role", "Score"], rows)
    return heading + "\n\n" + body


def hidden_markdown(report: HiddenStrength) -> str:
    capture, model = report.capture, report.model
    season = f"{report.season}/{(report.season + 1) % 100:02d}"
    sections = [
        f"# Is it the squad, or is it us? {capture.club.name}, {capture.competition.name} {season}",
        f"> **{WARNING}**",
        f"Attributes read at game date {capture.game_date.isoformat()}; {report.league_scored} of "
        f"{report.league_matches} league matches with both line-ups scored. Every XI score is the team model's "
        "(0-100) from true attributes and position ratings, every player fully fit. In the tables, * marks an XI "
        "or formation scored in the nearest shape our tactics have, and † a squad picked with players out of position.",
    ]
    if model is not None:
        sections.append(f"Model: fitted on {model.matches} league matches, a 1-point XI-score advantage was worth "
                        f"{model.goals_per_point():.2f} goals a match; at equal strength the home side scored "
                        f"{model.outcome(0, 0).home_goals:.2f} to {model.outcome(0, 0).away_goals:.2f}.")
    sections += ["## Verdict", "\n".join(_verdict(report)),
                 "## 1 · The XIs in our matches", _our_matches(report),
                 "## 2 · Best XI in our tactics", _tactics(report),
                 "## 3 · Best XI in the formations they've played", _formations(report),
                 "## 4 · Results against strength, every club", _results(report),
                 "## 5 · Defence, midfield and attack",
                 "Units by where each player was placed: goalkeeper; defence (centre-backs, full-backs, wing-backs); "
                 "midfield (defensive and central midfielders, wide midfielders); attack (attacking midfielders, "
                 "wingers, strikers). A unit's score combines its players' scores as the XI's does, before the "
                 "tactic's balance factor.",
                 *_units_section(report),
                 "## Both XIs, match by match (latest first)",
                 *(_line_up(row) for row in reversed(report.our_matches))]
    if capture.notes:
        sections += ["## Notes on the read", "\n".join(f"- {note}" for note in capture.notes)]
    return "\n\n".join(sections) + "\n"
