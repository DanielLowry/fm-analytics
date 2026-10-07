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

from fm_analytics.web.ui import ordered_positions, cell_details
from fm_analytics.analytics import (
    FamiliarityPolicy,
    PositionRanking,
    ScoutRecommendation,
    ScoutingAssessment,
    ScoutingAlerts,
    ScoutingCandidate,
    TacticScoutingAssessment,
    default_descending,
    score_role,
)
from fm_analytics.domain.models import Visibility
from fm_analytics.reporting import build_player_role_scores
from fm_analytics.web.rendering import (
    role_score_cells,
    _MAX_SCOUTING_ROWS,
    _label,
    _scouting_href,
    _scouting_knowledge_cell,
)
from fm_analytics.web.scouting_identity import (
    NOT_CURRENT_BADGE,
    _age,
    _contract_cell,
    _player_cell,
    _value_cell,
    _visible_observation_counts,
    last_seen_club,
    past_knowledge_cell,
)
from fm_analytics.web.scouting_tables import (
    _Column,
    _MAX_HINT,
    _MEDIAN_HINT,
    _MIN_HINT,
    _SCORE_EXPLANATION,
    _attribute_label,
    _results_view,
    _sortable_table,
    attribute_sheet,
    no_results,
    score_bar,
    scouting_player_link,
    squad_player_link,
    weakest_slots_panel,
)

from fm_analytics.web.attribute_export import ATTRIBUTE_GROUPS as _ATTRIBUTE_GROUPS


def scouting_alerts_panel(alerts: ScoutingAlerts) -> str:
    """Prepared alert collections; no rule is re-derived in HTML."""
    if not alerts.now_gettable and not alerts.rescout_due:
        return (
            "<section class='fm-workspace-panel fm-scouting-alerts'><h2>Scouting alerts</h2>"
            "<p class='muted'>No new gettable players or re-scout reminders.</p></section>"
        )

    def rows(items) -> str:
        return "".join(
            "<li>" + scouting_player_link_from_alert(item) + " — "
            + html.escape(item.reason)
            + (" <span class='muted'>(" + html.escape(", ".join(item.attributes)) + ")</span>"
               if item.attributes else "")
            + "</li>"
            for item in items
        ) or "<li class='muted'>None</li>"

    return (
        "<section class='fm-workspace-panel fm-scouting-alerts'><h2>Scouting alerts</h2>"
        "<div class='fm-decision-grid'><section><h3>Known and now gettable</h3><ul>"
        + rows(alerts.now_gettable)
        + "</ul></section><section><h3>Re-scout due</h3><ul>"
        + rows(alerts.rescout_due)
        + "</ul></section></div></section>"
    )


def scouting_player_link_from_alert(alert) -> str:
    return (
        f"<a href='/scouting/player/{quote(alert.player_id, safe='')}' class='player-link'>"
        f"{html.escape(alert.player_name)}</a>"
    )


def _positions_column(raw_positions: bool) -> _Column:
    def cell(_rank, item) -> str:
        candidate = item.candidate
        positions = candidate.positions_for(include_raw_external_positions=raw_positions)
        if not positions:
            return "<td><span class='muted'>Not yet captured</span></td>"
        return f"<td>{html.escape(', '.join(ordered_positions(positions)))}</td>"

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
        _Column("Range", "upside", lambda _r, i: (
            f"<td class='nw'>{i.maximum - i.minimum:.1f} {score_bar(i.minimum, i.median, i.maximum)}</td>"
        ), "Max − Min: how far scouting could still move his score. The bar spans Min to Max; "
           "the tick is the Median."),
    ]


def _attribute_report_link(candidate: ScoutingCandidate) -> str:
    known, ranged = _visible_observation_counts(candidate.attributes)
    historical = len(candidate.history.attributes) if candidate.history else 0
    label = f"Attributes ({known + ranged} shown" + (f", {historical} historical" if historical else "") + ")"
    note = ("<span class='warn'>Not captured from FM</span>" if not candidate.current_attributes_captured else
            "<span class='muted'>No attributes currently visible</span>" if not known + ranged else "")
    return (f"<a href='/scouting/player/{quote(candidate.id, safe='')}#player-attributes'>"
            + html.escape(label) + "</a>" + ("<br>" + note if note else ""))


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
        "where FM shows nothing today, and is marked historical in the player report.",
    ))
    columns.append(_Column(
        "Attributes", None, lambda _r, item: f"<td>{_attribute_report_link(item.candidate)}</td>"
    ))
    return columns


def _ranking_columns(show_familiarity: bool, raw_positions: bool) -> list[_Column]:
    columns = _identity_columns(raw_positions)
    columns.append(_Column(
        "Best role", "role", lambda _r, item: f"<td>{html.escape(item.role_name)}</td>",
        "The role that suits him best on the median score.",
    ))
    columns += _score_columns()
    if show_familiarity:
        columns += _familiarity_columns()
    return columns + _tail_columns(_knowledge_cell)


def _familiarity_columns() -> list[_Column]:
    """Familiarity / in-position score, for any item with ``multiplier`` and the ``adjusted_*`` scores."""
    return [
        _Column(
            "Familiarity", "familiarity", lambda _r, item: _familiarity_cells(item)[0],
            "His rating out of 20 for the position (with none chosen, his best among the "
            "positions the role is played at), and the multiplier it implies.",
        ),
        _Column(
            "In-position role score", "adjusted", lambda _r, item: _familiarity_cells(item)[1],
            "Min–Max after the familiarity multiplier; the same discount Squad applies.",
        ),
    ]


_FAMILIARITY_EXPLANATION = (
    "<p class='muted'><b>Familiarity</b> is his rating (out of 20) for the position; "
    "<b>In-position role score</b> applies the same familiarity multiplier as Squad. "
    "It does not apply condition or match fitness, which Tactics adds to produce "
    "today’s selection score.</p>"
)


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
        + (_FAMILIARITY_EXPLANATION if show_familiarity else "")
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
        f"{cell_details('Scouting detail', [reason, 'Scout next: ' + ', '.join(item.scout_next)] if item.scout_next else reason)}</td>"
    )


def _assessment_known_cell(item: ScoutingAssessment) -> str:
    if not item.candidate.current_attributes_captured:
        return "<span class='warn'>Not captured from FM</span>"
    total = item.known_attributes + item.ranged_attributes + item.unknown_attributes
    return _known_summary(item.known_attributes, item.ranged_attributes, item.unknown_attributes, total)


class _RoleRow:
    """A ``ScoutingAssessment`` under the names the shared score columns read."""

    __slots__ = (
        "assessment", "candidate", "minimum", "median", "maximum", "familiarity", "multiplier",
        "adjusted_minimum", "adjusted_median", "adjusted_maximum",
    )

    def __init__(self, assessment: ScoutingAssessment) -> None:
        self.assessment = assessment
        self.candidate = assessment.candidate
        self.minimum = assessment.role_score.score.lower
        self.median = assessment.role_score.median
        self.maximum = assessment.role_score.score.upper
        self.familiarity = assessment.familiarity
        self.multiplier = assessment.multiplier
        self.adjusted_minimum = assessment.adjusted_minimum
        self.adjusted_median = assessment.adjusted_median
        self.adjusted_maximum = assessment.adjusted_maximum


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
    show_familiarity = any(row.multiplier is not None for row in displayed)
    known, past, sheet = _tail_columns(lambda row: _assessment_known_cell(row.assessment))
    recommendation = _Column(
        "Recommendation", "priority", lambda _r, row: _recommendation_cell(row.assessment),
        "What scouting could still change, most decision-ready first.",
    )
    columns = (
        _identity_columns(raw_positions) + _score_columns()
        + (_familiarity_columns() if show_familiarity else [])
        + [known, recommendation, past, sheet]
    )
    explanation = (
        "<ul class='legend'>"
        "<li><b>Capture first</b>: the app has not read FM's current visible attributes.</li>"
        "<li><b>Scout first</b>: FM's captured answer has no relevant visible attributes.</li>"
        "<li><b>Scout to decide</b>: ranges or unknown values could still change the role fit.</li>"
        "<li><b>Proven fit</b>: every input to the role score is known.</li></ul>"
        + _SCORE_EXPLANATION
        + (_FAMILIARITY_EXPLANATION if show_familiarity else "")
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
        _Column("Trial priority", "trial_priority", lambda _r, item: (
            f"<td>{item.trial_priority:.1f}</td>"
            if item.trial_priority is not None else "<td>—</td>"
        ), "Median player fit in a weak slot. It orders who to look at, never whom to sign."),
        _Column("Median scenario", "player_median", lambda _r, item: (
            f"<td>{item.player_median:.1f}</td>"
        ), "A midpoint for ranges and unknowns; it is for choosing whom to look at, never whom to sign."),
        _Column("Trial outlook", None, lambda _r, item: f"<td>{_trial_outlook(item)}</td>"),
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


def _trial_outlook(item: TacticScoutingAssessment) -> str:
    flags = []
    if item.could_start:
        flags.append("Could start")
    if item.could_be_first_cover:
        flags.append("Could be first cover")
    return "<br>".join(flags) if flags else "No trial case yet"


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
    trial_priority: bool = False,
) -> str:
    """Render squad-relative candidate rankings for one selected tactic."""
    heading = f"Impact on {html.escape(tactic.name)}"
    if not assessments:
        return no_results(heading, pool_size=pool_size, scouted_only=scouted_only)
    scout_first = tuple(
        item for item in assessments
        if item.known_attributes + item.ranged_attributes == 0
    ) if trial_priority else ()
    scored = tuple(
        item for item in assessments
        if item.known_attributes + item.ranged_attributes > 0
    ) if trial_priority else assessments
    displayed = scored[:limit]
    explanation = (
        f"<p>Current score: <b>{baseline.score.central:.1f}</b>. Candidates are ranked by "
        "the change to the best XI after the whole line-up and permitted roles are "
        "re-optimised. A candidate who does not improve the XI shows +0.0.</p>"
        "<p class='muted'><b>Player fit</b> uses this tactic’s attribute emphasis, "
        "minimum-attribute tapers and position familiarity. Candidates are assumed "
        "available, fully fit and match fit; owned players retain today’s readiness. "
        "Floor / estimate / ceiling preserve scouting uncertainty, and the candidate "
        "may enter the XI only in the scenarios where he improves it.</p>"
        "<p class='muted'><b>Median scenario</b> is for choosing whom to look at, never whom to sign. "
        "Trial priority is shown only for a player with visible role attributes whose best job is a weak slot.</p>"
    )
    scout_first_block = _trial_scout_first(scout_first) if trial_priority else ""
    return _results_view(
        heading, total=len(assessments), shown=len(displayed), limit=limit,
        sort_label=sort_label, descending=descending,
        lead=(
            f"Current tactic score <b>{baseline.score.central:.1f}</b>."
            + (" Trial priority keeps your filters and additionally requires a current Player Search result "
               "with a visible interest or gettable-market signal." if trial_priority else "")
        ),
        explanation=explanation,
        table=(
            _sortable_table(_tactic_columns(raw_positions), displayed, sort=sort, descending=descending)
            if displayed else "<p class='muted'>No scored trial candidates match these filters.</p>"
        ) + scout_first_block,
    )


def _trial_scout_first(assessments: Sequence[TacticScoutingAssessment]) -> str:
    """Unscored candidates, grouped under the job the tactic can inspect first."""
    if not assessments:
        return ""
    groups: dict[str, list[TacticScoutingAssessment]] = {}
    for item in assessments:
        groups.setdefault(item.best_slot_key, []).append(item)
    blocks = []
    for slot_key, items in sorted(groups.items()):
        names = ", ".join(
            scouting_player_link(item.candidate)
            for item in sorted(items, key=lambda value: (value.candidate.name.casefold(), value.candidate.id))
        )
        blocks.append(f"<li><b>{html.escape(slot_key)}</b>: {names}</li>")
    return (
        "<section class='fm-scout-first'><h3>Scout first</h3>"
        "<p>These candidates have no visible role attributes, so no priority or score is claimed. "
        "They are grouped by the weakest job the tactic can inspect first.</p>"
        f"<ul>{''.join(blocks)}</ul></section>"
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


def _familiarity_cells(item: PositionRanking | _RoleRow) -> tuple[str, str]:
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
