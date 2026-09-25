"""Render the player-independent tactic checks page."""

from __future__ import annotations

import html

from fm_analytics.analytics import MVP_CATALOGUE, check_catalogue_structure


_STANDARD_LABELS = {
    "aerialOutlet": "Aerial target",
    "attack duties": "Players told to attack",
    "ballProgression": "Moving the ball forward",
    "boxPresence": "Players getting into the box",
    "creativity": "Creative roles",
    "creators": "Creative roles",
    "defensiveCover": "Defensive cover",
    "penetration": "Forward threat",
    "pressing": "Players applying pressure",
    "restDefence": "Cover when possession is lost",
    "runners": "Players making forward runs",
    "width": "Width",
}


def _standard_failure(shortfall: str) -> str:
    dimension, _separator, amounts = shortfall.rpartition(" ")
    actual, _slash, standard = amounts.partition("/")
    label = _STANDARD_LABELS.get(dimension, dimension)
    if dimension in {"attack duties", "creators"}:
        return f"{label}: {actual} selected; maximum {standard}"
    return f"{label}: roles provide {actual}; standard is {standard}"


def tactic_checks_body() -> str:
    checks = check_catalogue_structure(MVP_CATALOGUE)
    failures = sum(len(check.failures) for check in checks)
    combinations = sum(check.combination_count for check in checks)
    sections = []
    for check in checks:
        if not check.failures:
            continue
        items = []
        for index, failure in enumerate(check.failures, start=1):
            roles = "".join(
                f"<span><b>{html.escape(slot.key)}</b> "
                f"{html.escape(MVP_CATALOGUE.roles[role_key].name)}</span>"
                for slot, role_key in zip(check.tactic.slots, failure.role_keys)
            )
            problems = failure.balance.shortfalls + failure.instructions.shortfalls
            problem_items = "".join(
                f"<li>{html.escape(_standard_failure(problem))}</li>"
                for problem in problems
            )
            items.append(
                f"<details><summary>Failing combination {index}</summary>"
                f"<div class='role-combination'>{roles}</div>"
                "<b class='warn'>Does not meet the current standard</b>"
                f"<ul class='check-failures'>{problem_items}</ul></details>"
            )
        sections.append(
            f"<section id='{html.escape(check.tactic.key)}'><h2>"
            f"{html.escape(check.tactic.name)}</h2><p class='muted'>"
            f"{len(check.failures)} of {check.combination_count} permitted role "
            f"combinations fail.</p>{''.join(items)}</section>"
        )
    return (
        "<div class='advisory-banner'><b>Experimental, player-independent checks</b>"
        "Each role is assigned simple points for jobs such as providing width or "
        "making forward runs. These checks use hand-authored assumptions. They ignore player "
        "ability and do not predict match performance. Their sufficiency factor does "
        "affect tactic rankings."
        "</div><div class='check-summary'>"
        f"<span>{len(checks)} tactics</span><span>{combinations} permitted combinations</span>"
        f"<span>{failures} failing combinations</span></div>"
        + ("".join(sections) if sections else "<p>No combinations fail the current checks.</p>")
    )
