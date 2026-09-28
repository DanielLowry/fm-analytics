"""HTML for the Scouting page's attribute sheets and position rankings.

Split out of ``handlers.py``. Nothing here computes a score: the numbers come
from ``fm_analytics.analytics`` (``rank_for_position`` / ``score_role``) and are
only laid out here, so a figure on this page is the same figure the analytics
layer produces everywhere else.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Callable, Sequence
from urllib.parse import quote

from fm_analytics.analytics import (
    FamiliarityPolicy,
    PositionRanking,
    ScoutRecommendation,
    ScoutingAssessment,
    ScoutingCandidate,
    TacticScoutingAssessment,
    contract_months_left,
    default_descending,
    is_free_agent,
    is_transfer_listed,
    score_role,
)
from fm_analytics.domain.models import Visibility
from fm_analytics.reporting import build_player_role_scores
from fm_analytics.web.rendering import (
    role_score_cells,
    _MAX_SCOUTING_ROWS,
    _label,
    _scouting_knowledge_cell,
)

# The order FM's own attribute screens use, so a sheet can be read against the
# game side by side. Goalkeeping attributes only appear when a player has them.
_ATTRIBUTE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Technical", (
        "corners", "crossing", "dribbling", "finishing", "firstTouch", "heading",
        "longShots", "marking", "passing", "tackling", "technique",
    )),
    ("Mental", (
        "aggression", "anticipation", "bravery", "composure", "concentration",
        "decisions", "determination", "flair", "offTheBall", "positioning",
        "teamwork", "vision", "workRate",
    )),
    ("Physical", (
        "acceleration", "agility", "balance", "jumpingReach", "naturalFitness",
        "pace", "stamina", "strength",
    )),
    ("Goalkeeping", (
        "aerialReach", "commandOfArea", "communication", "handling", "kicking",
        "oneOnOnes", "reflexes", "rushingOut", "throwing",
    )),
)


_LABELS = {
    "firstTouch": "First Touch", "longShots": "Long Shots", "offTheBall": "Off The Ball",
    "workRate": "Work Rate", "jumpingReach": "Jumping Reach", "naturalFitness": "Natural Fitness",
    "aerialReach": "Aerial Reach", "commandOfArea": "Command Of Area", "oneOnOnes": "One On Ones",
    "rushingOut": "Rushing Out",
}


def _attribute_label(key: str) -> str:
    return _LABELS.get(key) or _label(key)


def attribute_sheet(candidate: ScoutingCandidate) -> str:
    """Every attribute FM lets the manager see for this player, grouped like FM."""
    shown = 0
    groups: list[str] = []
    for title, keys in _ATTRIBUTE_GROUPS:
        rows: list[str] = []
        for key in keys:
            observation = candidate.attributes.get(key)
            if observation is None:
                continue
            visible = observation.visibility is not Visibility.UNKNOWN
            shown += visible
            value = html.escape(observation.display()) if visible else "-"
            css = "attr" if visible else "attr attr-hidden"
            reading = candidate.historical_reading(key)
            title = ""
            if reading is not None:
                css += " attr-historical"
                title = f" title='Historical: last seen {html.escape(reading.last_seen_on, quote=True)}'"
            rows.append(
                f"<div class='{css}'{title}><span>{html.escape(_attribute_label(key))}</span><b>{value}</b></div>"
            )
        if rows:
            groups.append(f"<div class='sheet-group'><h4>{title}</h4>{''.join(rows)}</div>")
    if not groups:
        if not candidate.current_attributes_captured:
            return "<span class='warn'>Not captured from FM</span>"
        return "<span class='muted'>No attributes currently visible</span>"
    historical = len(candidate.history.attributes) if candidate.history else 0
    return (
        f"<details class='sheet'><summary>Attributes ({shown} shown"
        + (f", {historical} historical" if historical else "") + ")</summary>"
        f"<div class='sheet-groups'>{''.join(groups)}</div></details>"
    )


def scouting_player_link(candidate: ScoutingCandidate) -> str:
    """A stable link to the player's full scouting report."""
    return (
        f"<a href='/scouting/player/{quote(candidate.id, safe='')}' "
        f"class='player-link'>{html.escape(candidate.name)}</a>"
    )


def squad_player_link(player) -> str:
    """A stable link to an owned player's full squad report."""
    return (
        f"<a href='/squad/player/{quote(player.id, safe='')}' class='player-link'>"
        f"{html.escape(player.name)}</a>"
    )


def score_bar(minimum: float, median: float, maximum: float) -> str:
    """A 0-100 bar: the shaded stretch is min..max, the tick is the median."""
    def pct(value: float) -> float:
        return max(0.0, min(100.0, value))

    left, right = pct(minimum), pct(maximum)
    return (
        "<span class='bar'>"
        f"<span class='bar-fill' style='left:{left:.1f}%;width:{max(right - left, 0.8):.1f}%'></span>"
        f"<span class='bar-mark' style='left:{pct(median):.1f}%'></span></span>"
    )


@dataclass(frozen=True)
class _Column:
    """One results column: its heading, the server-side sort it triggers, and its cell."""

    title: str
    sort: str | None
    cell: Callable[[int, Any], str]
    hint: str = ""


def _sortable_table(
    columns: Sequence[_Column], items: Sequence[Any], *, sort: str, descending: bool
) -> str:
    """The one results table every scouting view uses.

    A column with a ``sort`` key renders as a button the page's script turns
    into a server-side re-sort (so the top of a long list is the true top by
    that column, not the top of what was on screen); the active column is
    marked with an arrow and ``aria-sort``. Which columns exist is the caller's
    choice, which is why every view can offer the same behaviour.
    """
    cells = []
    for column in columns:
        title = f" title='{html.escape(column.hint, quote=True)}'" if column.hint else ""
        if column.sort is None:
            cells.append(f"<th{title}>{column.title}</th>")
            continue
        active = column.sort == sort
        arrow = (" ▼" if descending else " ▲") if active else ""
        aria = (" aria-sort='descending'" if descending else " aria-sort='ascending'") if active else ""
        default = "desc" if default_descending(column.sort) else "asc"
        cells.append(
            f"<th{aria}><button type='button' class='sort-btn'{title} data-sort='{column.sort}' "
            f"data-default='{default}'>{column.title}{arrow}</button></th>"
        )
    rows = "".join(
        "<tr>" + "".join(column.cell(rank, item) for column in columns) + "</tr>"
        for rank, item in enumerate(items, start=1)
    )
    return (
        "<div class='table-scroll'><table class='results'>"
        f"<tr>{''.join(cells)}</tr>{rows}</table></div>"
    )


def _results_view(
    heading: str,
    *,
    total: int,
    shown: int,
    limit: int,
    sort_label: str,
    descending: bool,
    lead: str,
    explanation: str,
    table: str,
) -> str:
    """The frame around every results table: heading, sort line, notes, table, more."""
    more = ""
    if total > shown:
        step = min(_SHOW_MORE_STEP, total - shown)
        more = (
            f"<p class='show-more'><button type='button' data-limit='{limit + _SHOW_MORE_STEP}'>"
            f"Show {step} more</button> <span class='muted'>Showing {shown} of {total}.</span></p>"
        )
    return (
        f"<h2>{heading} ({total})</h2>"
        f"<p class='results-summary'>Sorted by <b>{html.escape(sort_label)}</b> "
        f"({'high to low' if descending else 'low to high'}); click any column heading to "
        f"re-sort. {lead}</p>"
        f"<details class='explain'><summary>How to read these columns</summary>{explanation}</details>"
        + table + more
    )


def no_results(heading: str, *, pool_size: int, scouted_only: bool) -> str:
    """The one empty state, so every view says the same thing for the same reason."""
    if pool_size == 0:
        reason = (
            "No manager-visible scouting candidates have been loaded yet. Supply a "
            "verified scouting capture with <code>--scouting-json</code>."
        )
    else:
        reason = (
            "No candidates match these filters."
            + (
                " Only players you hold a scout report on -- FM's own Scouted list -- "
                "are listed on the Scouted tab; try <b>All players</b>, or tick "
                "<b>Everyone ever scouted</b> for players who have since dropped off it."
                if scouted_only else ""
            )
        )
    return f"<h2>{heading}</h2><p class='muted'>{reason}</p>"


_SHOW_MORE_STEP = 100

_MIN_HINT = "Every unknown attribute counts as 1 and every range at its low end."
_MEDIAN_HINT = "Every range at its midpoint and every unknown attribute mid-scale."
_MAX_HINT = "Every unknown attribute counts as 20 and every range at its top."
_SCORE_EXPLANATION = (
    "<p class='muted'><b>Min</b> counts every unknown attribute as 1 and every range at "
    "its low end; <b>Max</b> counts unknowns as 20 and ranges at their top; <b>Median</b> "
    "puts each range at its midpoint and each unknown mid-scale. A wide gap between min "
    "and max is where more scouting would change the picture. These are <b>attribute-based "
    "role scores</b>: they do not apply positional familiarity.</p>"
)


def _positions_column(raw_positions: bool) -> _Column:
    def cell(_rank, item) -> str:
        candidate = item.candidate
        positions = candidate.positions_for(include_raw_external_positions=raw_positions)
        if not positions:
            return "<td><span class='muted'>Not yet captured</span></td>"
        return f"<td>{html.escape(', '.join(positions))}</td>"

    return _Column(
        "Positions" + (" (raw external data)" if raw_positions else ""), None, cell
    )


def _identity_columns(raw_positions: bool) -> list[_Column]:
    """The columns every view starts with: who he is and how gettable he is."""
    return [
        _Column("#", None, lambda rank, item: f"<td>{rank}</td>"),
        _Column("Player", "name", lambda _r, item: f"<td>{_player_cell(item.candidate)}</td>"),
        _Column("Age", "age", lambda _r, item: f"<td class='nw'>{_age(item.candidate)}</td>"),
        _positions_column(raw_positions),
        _Column("Value", "value", lambda _r, item: f"<td class='nw'>{_value_cell(item.candidate)}</td>",
                "FM's own Value figure."),
        _Column("Contract", None, lambda _r, item: f"<td class='nw'>{_contract_cell(item.candidate)}</td>"),
        _Column("Scouted", "scouted", lambda _r, item: f"<td>{_scouting_knowledge_cell(item.candidate)}</td>",
                "How much of this player FM's scouts know."),
    ]


def _score_columns() -> list[_Column]:
    """Min / Median / Max / spread, for any item with ``minimum``/``median``/``maximum``."""
    return [
        _Column("Min", "minimum", lambda _r, i: f"<td class='nw'>{i.minimum:.1f}</td>", _MIN_HINT),
        _Column("Median", "median", lambda _r, i: f"<td class='nw'><b>{i.median:.1f}</b></td>", _MEDIAN_HINT),
        _Column("Max", "ceiling", lambda _r, i: f"<td class='nw'>{i.maximum:.1f}</td>", _MAX_HINT),
        _Column("Range", "upside", lambda _r, i: f"<td>{score_bar(i.minimum, i.median, i.maximum)}</td>",
                "The bar spans Min to Max; the tick is the Median. Sorts by how far Max is above Median."),
    ]


def _tail_columns(known_cell: Callable[[Any], str] | None = None) -> list[_Column]:
    columns = []
    if known_cell is not None:
        columns.append(_Column(
            "Role attributes known", "known", lambda _r, item: f"<td>{known_cell(item)}</td>",
            "How many of this role's attributes are exact or ranged, out of the role's total.",
        ))
    columns.append(_Column(
        "Past knowledge", None, lambda _r, item: f"<td>{past_knowledge_cell(item.candidate)}</td>",
        "Earlier, dated observations. A remembered value is used in the scores only "
        "where FM shows nothing today, and is marked historical in the attribute sheet.",
    ))
    columns.append(_Column(
        "Attributes", None, lambda _r, item: f"<td>{attribute_sheet(item.candidate)}</td>"
    ))
    return columns


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


def _ranking_columns(show_familiarity: bool, raw_positions: bool) -> list[_Column]:
    columns = _identity_columns(raw_positions)
    columns.append(_Column(
        "Best role", "role", lambda _r, item: f"<td>{html.escape(item.role_name)}</td>",
        "The role that suits him best on the median score.",
    ))
    columns += _score_columns()
    if show_familiarity:
        columns.append(_Column(
            "Familiarity", "familiarity", lambda _r, item: _familiarity_cells(item)[0],
            "His rating out of 20 for the position, and the multiplier it implies.",
        ))
        columns.append(_Column(
            "In-position role score", "adjusted", lambda _r, item: _familiarity_cells(item)[1],
            "Min–Max after the familiarity multiplier; the same discount Squad applies.",
        ))
    return columns + _tail_columns(_knowledge_cell)


def ranking_results(
    rankings: Sequence[PositionRanking],
    *,
    position: str | None,
    sort: str,
    sort_label: str,
    descending: bool,
    raw_positions: bool = False,
    limit: int = _MAX_SCOUTING_ROWS,
    pool_size: int = 0,
    scouted_only: bool = False,
) -> str:
    scope = f"Ranked for {html.escape(position)}" if position else "Ranked, all positions"
    if not rankings:
        return no_results(scope, pool_size=pool_size, scouted_only=scouted_only)
    displayed = rankings[:limit]
    show_familiarity = any(item.multiplier is not None for item in displayed)
    explanation = (
        "<p class='muted'>Each player is scored in whichever role suits him best"
        + (" at this position" if position else " (roles for his own positions where known, "
           "otherwise every role)")
        + ".</p>" + _SCORE_EXPLANATION
        + (
            "<p class='muted'>Position eligibility uses raw external data (the accepted "
            "visibility gap).</p>" if raw_positions else ""
        )
        + (
            "<p class='muted'><b>Familiarity</b> is his rating (out of 20) for the position; "
            "<b>In-position role score</b> applies the same familiarity multiplier as Squad. "
            "It does not apply condition or match fitness, which Tactics adds to produce "
            "today’s selection score.</p>"
            if show_familiarity else ""
        )
    )
    return _results_view(
        scope, total=len(rankings), shown=len(displayed), limit=limit,
        sort_label=sort_label, descending=descending, lead="", explanation=explanation,
        table=_sortable_table(
            _ranking_columns(show_familiarity, raw_positions), displayed,
            sort=sort, descending=descending,
        ),
    )


_RECOMMENDATION_LABELS = {
    ScoutRecommendation.PROVEN_FIT: ("Proven fit", "badge-proven", "All role inputs are known."),
    ScoutRecommendation.SCOUT_FIRST: ("Scout first", "badge-scout", "No role attributes are known yet."),
    ScoutRecommendation.SCOUT_TO_DECIDE: ("Scout to decide", "badge-scout", "Ranges or unknowns can still change this decision."),
    ScoutRecommendation.UNLIKELY: ("Unlikely", "badge-unlikely", "Even the visible ceiling misses your filter."),
}


def _recommendation_cell(item: ScoutingAssessment) -> str:
    label, badge, reason = _RECOMMENDATION_LABELS[item.recommendation]
    if not item.candidate.current_attributes_captured:
        label, badge, reason = (
            "Capture first", "badge-scout",
            "FM's current visible attributes have not been captured for this player.",
        )
    scout_next = (
        f"<br><span class='muted'><b>Scout next:</b> {html.escape(', '.join(item.scout_next))}</span>"
        if item.scout_next else ""
    )
    return (
        f"<td class='rec'><span class='badge {badge}'>{label}</span><br>"
        f"<span class='muted'>{html.escape(reason)}</span>{scout_next}</td>"
    )


def _assessment_known_cell(item: ScoutingAssessment) -> str:
    if not item.candidate.current_attributes_captured:
        return "<span class='warn'>Not captured from FM</span>"
    total = item.known_attributes + item.ranged_attributes + item.unknown_attributes
    return _known_summary(item.known_attributes, item.ranged_attributes, item.unknown_attributes, total)


class _RoleRow:
    """A ``ScoutingAssessment`` under the names the shared score columns read."""

    __slots__ = ("assessment", "candidate", "minimum", "median", "maximum")

    def __init__(self, assessment: ScoutingAssessment) -> None:
        self.assessment = assessment
        self.candidate = assessment.candidate
        self.minimum = assessment.role_score.score.lower
        self.median = assessment.role_score.median
        self.maximum = assessment.role_score.score.upper


def role_results(
    assessments: Sequence[ScoutingAssessment],
    *,
    role_name: str,
    sort: str,
    sort_label: str,
    descending: bool,
    raw_positions: bool = False,
    limit: int = _MAX_SCOUTING_ROWS,
    pool_size: int = 0,
    scouted_only: bool = False,
) -> str:
    """One role's targets, in the same table (and with the same sorting) as the rankings."""
    heading = f"Targets for {html.escape(role_name)}"
    if not assessments:
        return no_results(heading, pool_size=pool_size, scouted_only=scouted_only)
    displayed = [_RoleRow(item) for item in assessments[:limit]]
    known, past, sheet = _tail_columns(lambda row: _assessment_known_cell(row.assessment))
    recommendation = _Column(
        "Recommendation", "priority", lambda _r, row: _recommendation_cell(row.assessment),
        "What scouting could still change, most decision-ready first.",
    )
    columns = (
        _identity_columns(raw_positions) + _score_columns()
        + [known, recommendation, past, sheet]
    )
    explanation = (
        "<ul class='legend'>"
        "<li><b>Capture first</b>: the app has not read FM's current visible attributes.</li>"
        "<li><b>Scout first</b>: FM's captured answer has no relevant visible attributes.</li>"
        "<li><b>Scout to decide</b>: ranges or unknown values could still change the role fit.</li>"
        "<li><b>Proven fit</b>: every input to the role score is known.</li></ul>"
        + _SCORE_EXPLANATION
    )
    return _results_view(
        heading, total=len(assessments), shown=len(displayed), limit=limit,
        sort_label=sort_label, descending=descending, lead="", explanation=explanation,
        table=_sortable_table(columns, displayed, sort=sort, descending=descending),
    )


def _tactic_columns(raw_positions: bool) -> list[_Column]:
    columns = _identity_columns(raw_positions)
    columns += [
        _Column("Best tactic job", "role", lambda _r, item: (
            f"<td><b>{html.escape(item.best_slot_key)}</b> · {html.escape(item.best_role_name)}</td>"
        )),
        _Column("Player fit", "tactic_fit", lambda _r, item: (
            f"<td>{_three_scores(item.player_fit.lower, item.player_fit.central, item.player_fit.upper)}</td>"
        ), "This tactic's attribute emphasis, minimum-attribute tapers and position familiarity."),
        _Column("Projected tactic score", "tactic_score", lambda _r, item: (
            f"<td>{_three_scores(item.projected_score.floor, item.projected_score.estimate, item.projected_score.ceiling)}</td>"
        )),
        _Column("XI gain", "tactic_gain", lambda _r, item: (
            f"<td>{_three_gains(item.score_gain.floor, item.score_gain.estimate, item.score_gain.ceiling)}</td>"
        ), "The change to the best XI once the whole line-up is re-optimised."),
        _Column("Outcome", None, lambda _r, item: f"<td>{_tactic_outcome(item)}</td>"),
    ]
    return columns + _tail_columns(_knowledge_cell)


def _tactic_outcome(item: TacticScoutingAssessment) -> str:
    if not item.starts_at_estimate:
        return "<span class='muted'>Depth at estimate</span>"
    return "Starts" + (
        "<br><span class='muted'>Replaces "
        + html.escape(", ".join(item.replaced_player_names)) + "</span>"
        if item.replaced_player_names else ""
    )


def tactic_ranking_results(
    assessments: Sequence[TacticScoutingAssessment],
    *,
    tactic,
    baseline,
    sort: str,
    sort_label: str,
    descending: bool,
    raw_positions: bool = False,
    limit: int = _MAX_SCOUTING_ROWS,
    pool_size: int = 0,
    scouted_only: bool = False,
) -> str:
    """Render squad-relative candidate rankings for one selected tactic."""
    heading = f"Impact on {html.escape(tactic.name)}"
    if not assessments:
        return no_results(heading, pool_size=pool_size, scouted_only=scouted_only)
    displayed = assessments[:limit]
    explanation = (
        f"<p>Current score: <b>{baseline.score.central:.1f}</b>. Candidates are ranked by "
        "the change to the best XI after the whole line-up and permitted roles are "
        "re-optimised. A candidate who does not improve the XI shows +0.0.</p>"
        "<p class='muted'><b>Player fit</b> uses this tactic’s attribute emphasis, "
        "minimum-attribute tapers and position familiarity. Candidates are assumed "
        "available, fully fit and match fit; owned players retain today’s readiness. "
        "Floor / estimate / ceiling preserve scouting uncertainty, and the candidate "
        "may enter the XI only in the scenarios where he improves it.</p>"
    )
    return _results_view(
        heading, total=len(assessments), shown=len(displayed), limit=limit,
        sort_label=sort_label, descending=descending,
        lead=f"Current tactic score <b>{baseline.score.central:.1f}</b>.",
        explanation=explanation,
        table=_sortable_table(
            _tactic_columns(raw_positions), displayed, sort=sort, descending=descending
        ),
    )


def _three_scores(floor: float, estimate: float, ceiling: float) -> str:
    return (
        f"<b>{estimate:.1f}</b><br>"
        f"<span class='muted'>{floor:.1f} / {estimate:.1f} / {ceiling:.1f}</span>"
    )


def _three_gains(floor: float, estimate: float, ceiling: float) -> str:
    def value(item: float) -> str:
        return f"{item:+.1f}"

    return (
        f"<b>{value(estimate)}</b><br>"
        f"<span class='muted'>{value(floor)} / {value(estimate)} / {value(ceiling)}</span>"
    )


def _familiarity_cells(item: PositionRanking) -> tuple[str, str]:
    if item.multiplier is None:
        return "<td>—</td>", "<td>—</td>"
    return (
        f"<td>{item.familiarity}/20 <span class='muted'>(×{item.multiplier:.2f})</span></td>",
        f"<td><b>{item.adjusted_median:.1f}</b><br>"
        f"<span class='muted'>{item.adjusted_minimum:.1f}–{item.adjusted_maximum:.1f}</span></td>",
    )


def _known_summary(known: int, ranged: int, unknown: int, total: int) -> str:
    headline = f"{known} of {total} known"
    if not ranged and not unknown:
        return f"<b>{headline}</b>"
    parts = []
    if ranged:
        parts.append(f"{ranged} ranged")
    if unknown:
        parts.append(f"{unknown} unknown")
    return f"{headline}<br><span class='muted'>{' &middot; '.join(parts)}</span>"


def _knowledge_cell(item) -> str:
    """How much of *this role's* attribute list is known for him.

    The total is the number of attributes the role scores, not the 32 a player
    has: reading "11 / 0 / 0" as "only 11 of his attributes are known" was the
    obvious misreading, so the denominator is now shown. Works for a
    ``PositionRanking`` and a ``TacticScoutingAssessment`` alike.
    """
    if not item.candidate.current_attributes_captured:
        return "<span class='warn'>Not captured from FM</span>"
    total = item.known_attributes + item.ranged_attributes + item.unknown_attributes
    return _known_summary(item.known_attributes, item.ranged_attributes, item.unknown_attributes, total)


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
