"""Identity, market facts, and dated knowledge cells shared by scouting views."""

from __future__ import annotations

import html

from fm_analytics.analytics import (
    ScoutingCandidate, contract_months_left, is_free_agent, is_transfer_listed,
)
from fm_analytics.domain import Visibility
from fm_analytics.web.scouting_tables import scouting_player_link


def _age(candidate: ScoutingCandidate) -> str:
    return str(candidate.age) if candidate.age is not None else "—"


def _interest_tags(candidate: ScoutingCandidate) -> str:
    """FM's own transfer/loan interest verdicts, "yes" and the relaxed-margin "maybe" both shown.

    Computed fresh from the manager's own current reputation every refresh
    (tools.fm20_sandbox_queries) -- never a stored fact, and never carried
    forward from an older capture. "maybe" only clears the product's
    deliberately relaxed margin below FM's own cut-off, not FM's cut-off
    itself; see docs/frida-discoverability.md for why that margin exists.
    """
    tags = []
    for label, value in (("transfer", candidate.transfer_interest), ("loan", candidate.loan_interest)):
        if value == "yes":
            tags.append(f"<span class='badge badge-ok'>Interested ({label})</span>")
        elif value == "maybe":
            tags.append(f"<span class='badge badge-scout'>Possibly interested ({label})</span>")
    return "".join(f" {tag}" for tag in tags)


def _player_cell(candidate: ScoutingCandidate) -> str:
    """Name (a link to his report) over club and nationality, flagged with FM's interest verdict.

    A player known only from the knowledge history is flagged instead, and his
    club is the one he was last seen at, dated.
    """
    if not candidate.in_current_feed:
        detail = " · ".join(
            html.escape(part) for part in (last_seen_club(candidate), candidate.nationality) if part
        )
        return (
            f"{scouting_player_link(candidate)} {NOT_CURRENT_BADGE}"
            f"<br><span class='muted'>{detail}</span>"
        )
    detail = " · ".join(
        html.escape(part) for part in (candidate.club or "No club", candidate.nationality) if part
    )
    return f"{scouting_player_link(candidate)}{_interest_tags(candidate)}<br><span class='muted'>{detail}</span>"


NOT_CURRENT_BADGE = (
    "<span class='badge badge-history' title='Not in the current scouting feed: "
    "known only from what you saw earlier'>Not currently realistic</span>"
)


def last_seen_club(candidate: ScoutingCandidate) -> str:
    """"Last seen at X, 2019-10-01" for a player known only from history."""
    history = candidate.history
    if history is None:
        return candidate.club or "No club"
    club = (history.profile or {}).get("club")
    seen = history.profile_last_seen_on or history.oldest_seen_on
    where = f"Last seen at {club}" if club else "Last seen"
    return f"{where}, {seen}" if seen else where


def _visible_observation_counts(attributes) -> tuple[int, int]:
    observations = tuple((attributes or {}).values())
    known = sum(item.visibility is Visibility.KNOWN for item in observations)
    ranged = sum(item.visibility is Visibility.RANGE for item in observations)
    return known, ranged


def past_knowledge_cell(candidate: ScoutingCandidate) -> str:
    """Summarise dated historical observations without implying they are current.

    Values the knowledge history filled in come first: they are in the scores,
    so their age matters most. Otherwise the feed's own last-known snapshot.
    """
    history = candidate.history
    if history is not None and history.attributes:
        oldest = history.oldest_seen_on
        age = (
            f"<span class='dropped-warning'>Out of date: oldest seen {html.escape(oldest or '')}</span>"
            if history.out_of_date
            else f"<span class='muted'>Oldest seen {html.escape(oldest or '')}</span>"
        )
        return f"<b>{len(history.attributes)} from history</b><br>{age}"
    known, ranged = _visible_observation_counts(candidate.last_known_attributes)
    if not known and not ranged:
        return "<span class='muted'>—</span>"
    parts = []
    if known:
        parts.append(f"{known} exact")
    if ranged:
        parts.append(f"{ranged} ranged")
    observed = html.escape(
        candidate.last_known_attributes_observed_at or "date not captured"
    )
    return (
        f"<b>{' &middot; '.join(parts)}</b><br>"
        f"<span class='muted'>Last visible {observed}</span>"
    )


def _value_cell(candidate: ScoutingCandidate) -> str:
    """FM's own Value figure. Also the best available proxy for whether he would
    join us: see ``docs/scouting-workspace.md`` on the interest estimate."""
    if candidate.value is None:
        return "<span class='muted'>—</span>"
    if candidate.value == 0:
        return "<span class='muted'>&pound;0</span>"
    return f"&pound;{candidate.value:,}"


def _contract_cell(candidate: ScoutingCandidate) -> str:
    """What a manager needs to know about getting him, in the order it matters."""
    notes: list[str] = []
    if is_free_agent(candidate):
        notes.append("<b>Free agent</b>")
    if is_transfer_listed(candidate):
        notes.append("<b>Transfer listed</b>")
    if candidate.contract_end:
        months = contract_months_left(candidate)
        left = f" ({months} mo)" if months is not None and months >= 0 else ""
        notes.append(f"Expires {html.escape(candidate.contract_end)}{left}")
    return "<br>".join(notes) or "<span class='muted'>—</span>"
