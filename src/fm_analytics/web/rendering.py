"""Shared HTML rendering and request parsing helpers for the web view."""

from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlencode

from fm_analytics.analytics import (
    ScoutingFilters,
    TacticDefinition,
    TacticSlot,
    WeaknessKind,
    WeaknessReport,
)


_NAV: tuple[tuple[str, str], ...] = (
    ("/", "Dashboard"),
    ("/squad", "Squad"),
    ("/roles", "Roles"),
    ("/tactics", "Tactics"),
    ("/set-pieces", "Set pieces"),
    ("/depth", "Depth"),
    ("/scouting", "Scouting"),
    ("/data", "Data"),
)

# Slot weaknesses that answer "if this starter is unavailable, are we
# covered": no backup at all, a backup that itself falls below the
# threshold, or a backup that is only first cover because it is shared
# across several simultaneous slots. Used to build the Tactics page's
# injury-risk column; see WeaknessKind for what each one means precisely.
_INJURY_RISK_KINDS = frozenset(
    {WeaknessKind.NO_BACKUP, WeaknessKind.WEAK_BACKUP, WeaknessKind.SHARED_COVER}
)
_MAX_SCOUTING_ROWS = 100

# Real-time re-filtering for the Scouting page. Server-side only: it fetches
# the same `_scouting_results_block` computation `/scouting` itself renders
# (see `SquadWebHandler._scouting_results_fragment`), just as a fragment, so
# typing never invents a lighter-weight client-side filter that could disagree
# with the page's own numbers. `form.filters`' fields already carry every
# active filter, including the position/role selects and dynamic `fact.*`
# selects, so serializing the whole form on each change keeps them all in
# sync without hand-listing field names here. A no-JS browser falls back to
# the form's ordinary GET submit, unaffected by this script.
#
# The role select is narrowed to the chosen position's eligible roles from
# `#position-roles-data` (see `_scouting_page`) -- a structural fact from the
# catalogue, not a score, so reading it here does not duplicate any analytics
# computation. With no position chosen the role select is blanked and
# disabled, since a role choice only means anything once eligibility can be
# checked against a position. A no-JS browser instead sees every role,
# unfiltered, exactly as before this existed.
_SCOUTING_LIVE_FILTER_SCRIPT = """
<script>
(function () {
  var form = document.querySelector('form.filters');
  var results = document.getElementById('scouting-results');
  if (!form || !results) return;

  var positionSelect = form.querySelector("select[name='position']");
  var roleSelect = form.querySelector("select[name='role']");
  var roleDataElement = document.getElementById('position-roles-data');
  var positionRoles = {};
  if (roleDataElement) {
    try { positionRoles = JSON.parse(roleDataElement.textContent); }
    catch (error) { positionRoles = {}; }
  }

  function refreshRoleOptions() {
    if (!positionSelect || !roleSelect) return;
    var position = positionSelect.value;
    var previousRole = roleSelect.value;
    var roles = position ? (positionRoles[position] || []) : [];
    roleSelect.innerHTML = '';
    var blank = document.createElement('option');
    blank.value = '';
    blank.textContent = position ? 'Choose a role' : 'Choose a position first';
    roleSelect.appendChild(blank);
    roleSelect.disabled = !position;
    var stillValid = false;
    roles.forEach(function (pair) {
      var option = document.createElement('option');
      option.value = pair[0];
      option.textContent = pair[1];
      if (pair[0] === previousRole) { option.selected = true; stillValid = true; }
      roleSelect.appendChild(option);
    });
    if (!stillValid) roleSelect.value = '';
  }

  var timer = null;
  function apply() {
    var params = new URLSearchParams(new FormData(form));
    fetch('/scouting/results?' + params.toString())
      .then(function (response) { return response.text(); })
      .then(function (text) { results.innerHTML = text; })
      .catch(function () { /* leave the last good results showing */ });
    history.replaceState(null, '', '/scouting?' + params.toString());
  }
  if (positionSelect) {
    // Runs on the target before the delegated 'change' below sees the event,
    // so a reset/narrowed role is what actually gets sent to the server.
    positionSelect.addEventListener('change', refreshRoleOptions);
  }
  refreshRoleOptions(); // narrow immediately on load, including on a fresh page
  form.addEventListener('input', function (event) {
    if (event.target.tagName === 'SELECT') return; // selects fire 'change' below
    clearTimeout(timer);
    timer = setTimeout(apply, 250);
  });
  form.addEventListener('change', function () {
    clearTimeout(timer);
    apply();
  });
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    clearTimeout(timer);
    apply();
  });
  // Column headers re-sort on the server, so the top of a long list is the
  // true top by that column rather than the top of what was on screen. The
  // hidden `dir` field carries the current direction; clicking the active
  // column flips it, clicking another starts from that column's natural one.
  var sortSelect = form.querySelector("select[name='sort']");
  var dirInput = form.querySelector("input[name='dir']");
  if (sortSelect && dirInput) {
    sortSelect.addEventListener('change', function () { dirInput.value = ''; });
    results.addEventListener('click', function (event) {
      var button = event.target.closest('button.sort-btn');
      if (!button) return;
      var key = button.getAttribute('data-sort');
      if (sortSelect.value === key) {
        dirInput.value = dirInput.value === 'desc' ? 'asc' : 'desc';
      } else {
        sortSelect.value = key;
        dirInput.value = button.getAttribute('data-default');
      }
      clearTimeout(timer);
      apply();
    });
  }
})();
</script>
"""

_TACTICAL_DIMENSION_LABELS = {
    "aerialOutlet": "aerial outlet",
    "attack duties": "attacking duties",
    "ballProgression": "ball progression",
    "boxPresence": "presence in the box",
    "creativity": "creativity",
    "creators": "creative roles",
    "defensiveCover": "defensive cover",
    "penetration": "penetration",
    "pressing": "pressing",
    "restDefence": "defensive security after losing the ball",
    "runners": "forward runners",
    "width": "width",
}

_STYLE = """
<style>
  body { font-family: system-ui, sans-serif; margin: 0; color: #1a1a1a; background: #fafafa; }
  nav { background: #1a2b3c; padding: 0.75rem 1.5rem; }
  nav a { color: #cdd8e3; text-decoration: none; margin-right: 1.25rem; font-size: 0.95rem; }
  nav a.active, nav a:hover { color: #ffffff; font-weight: 600; }
  main { padding: 1.5rem 2rem; max-width: 1100px; margin: 0 auto; }
  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.25rem; }
  table { border-collapse: collapse; width: 100%; margin: 0.75rem 0 1.5rem; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid #e5e5e5; }
  th { background: #f0f2f5; }
  th.sort-header { cursor: pointer; user-select: none; }
  th.sort-header::after { content: ' \\2195'; color: #9aa5b1; }
  th[aria-sort=ascending]::after { content: ' \\25B2'; color: inherit; }
  th[aria-sort=descending]::after { content: ' \\25BC'; color: inherit; }
  .muted { color: #666; }
  .warn { color: #9a4a00; }
  .error { color: #a30000; font-weight: 600; }
  .badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 0.75rem; font-size: 0.8rem; }
  .badge-persistent { background: #fde2e2; color: #8a1f1f; }
  .badge-occasional { background: #fff2d6; color: #8a5a00; }
  .badge-ok { background: #e3f3e1; color: #1e6b1e; }
  .tag { display: inline-block; padding: 0.1rem 0.5rem; margin: 0 0.25rem 0.25rem 0; border-radius: 0.75rem; font-size: 0.75rem; background: #eef1f4; color: #445; }
  code { background: #eef1f4; padding: 0.05rem 0.3rem; border-radius: 0.25rem; }
  details { margin: 0.4rem 0; border: 1px solid #e5e5e5; border-radius: 0.3rem; padding: 0.3rem 0.6rem; }
  details summary { cursor: pointer; font-weight: 600; }
  details table { margin-top: 0.5rem; }
  ul.legend { color: #555; font-size: 0.85rem; margin: 0.25rem 0 0.75rem; padding-left: 1.2rem; }
  form.filters { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.65rem; padding: 1rem; background: #f0f2f5; border-radius: 0.4rem; }
  form.filters label { display: grid; gap: 0.2rem; font-size: 0.78rem; color: #455; }
  form.filters input, form.filters select { min-width: 0; padding: 0.35rem; border: 1px solid #bbc3cc; border-radius: 0.25rem; background: white; }
  form.filters .check { display: flex; align-items: end; gap: 0.35rem; color: #1a1a1a; }
  form.filters button { align-self: end; padding: 0.45rem 0.65rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  form.refresh { margin: 0.75rem 0; display: flex; align-items: center; gap: 0.65rem; }
  form.refresh button { padding: 0.45rem 0.65rem; border: 0; border-radius: 0.25rem; background: #1a2b3c; color: white; cursor: pointer; }
  form.refresh button.danger { background: #8a2b12; }
  nav.scouting-tabs { display: flex; gap: 0.5rem; margin: 0.5rem 0 1rem; }
  nav.scouting-tabs a { padding: 0.4rem 0.8rem; border-radius: 0.25rem; text-decoration: none; color: #1a2b3c; background: #e8ecef; }
  nav.scouting-tabs a.tab-active { background: #1a2b3c; color: white; }
  .dropped-warning { color: #8a2b12; font-weight: bold; }
  details.sheet summary { cursor: pointer; color: #1a2b3c; }
  .sheet-groups { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 0.4rem; }
  .sheet-group h4 { margin: 0 0 0.2rem; font-size: 0.8rem; text-transform: uppercase; color: #566; }
  .attr { display: flex; justify-content: space-between; gap: 0.8rem; min-width: 10rem; font-size: 0.85rem; }
  .attr-hidden { color: #9aa; }
  .bar { position: relative; display: inline-block; width: 110px; height: 0.8rem; background: #e8ecef; border-radius: 0.2rem; vertical-align: middle; }
  .bar-fill { position: absolute; top: 0; bottom: 0; background: #9fb6cf; border-radius: 0.2rem; }
  button.sort-btn { all: unset; cursor: pointer; font-weight: 600; white-space: nowrap; }
  button.sort-btn:hover { text-decoration: underline; }
  .bar-mark { position: absolute; top: -2px; bottom: -2px; width: 3px; margin-left: -1px; background: #1a2b3c; }
  .badge-scout { background: #fff2d6; color: #805400; }
  .badge-proven { background: #e3f3e1; color: #1e6b1e; }
  .badge-unlikely { background: #eee; color: #555; }
  .attribute-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.35rem; }
  .attribute-grid div { border: 1px solid #e5e5e5; padding: 0.35rem; border-radius: 0.25rem; }
  .attribute-grid b { display: block; font-size: 0.75rem; color: #667; }
  .tactic-hero { margin: 1rem 0 1.5rem; padding: 1rem 1.2rem; background: #eef3f7; border-left: 4px solid #1a2b3c; border-radius: 0.3rem; }
  .tactic-hero h2 { margin: 0.2rem 0; border: 0; padding: 0; font-size: 1.35rem; }
  .tactic-hero p { margin: 0.45rem 0; }
  .eyebrow { color: #566; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
  .button-link { display: inline-block; padding: 0.4rem 0.7rem; border-radius: 0.25rem; background: #1a2b3c; color: white; text-decoration: none; }
  .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 0.65rem; margin: 1rem 0; }
  .metric-grid div { display: grid; gap: 0.2rem; padding: 0.75rem; border: 1px solid #dfe3e7; border-radius: 0.3rem; background: white; }
  .metric-grid span { color: #667; font-size: 0.8rem; }
  .metric-grid b { font-size: 1.15rem; }
  tr.explanation-row td { padding: 0 0.6rem 0.55rem; background: #fcfcfc; }
  tr.explanation-row details { margin: 0; }
  .score-path { line-height: 1.8; }
  .tactic-link { white-space: nowrap; }
</style>
"""


def _nav_link(path: str, label: str, active_path: str) -> str:
    active_class = ' class="active"' if path == active_path else ""
    return f'<a href="{path}"{active_class}>{html.escape(label)}</a>'


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
            tactic.instruction_rationale, tactic.attribute_emphasis,
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
        leaned = ", ".join(
            f"{html.escape(_readable_attribute(name))} {delta:+d}"
            for name, delta in tactic.attribute_emphasis.items()
        )
        parts.append(
            f"<p class='muted'><b>Leans on:</b> {leaned}. "
            "Role fit on this page is scored with these attributes weighted a little "
            "differently from the same role in another tactic.</p>"
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
    return "".join(parts)


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


# Requested verbatim: a dropped player's last-known scouting facts are still
# shown (see fm20_scouting_feed.py's carry-forward), so this must read as a
# flag on data still worth trusting, not as an error hiding the player.
DROPPED_FROM_SCOUT_REPORTS_MESSAGE = (
    "This player used to be in the scouted pool but can't be found in the "
    "scout reports anymore."
)


def _scouting_knowledge_cell(candidate: object) -> str:
    knowledge = getattr(candidate, "scouting_knowledge", None)
    if knowledge is None:
        return "—"
    if getattr(candidate, "dropped_from_scout_reports", False):
        return (
            f"{knowledge}% <span class='muted'>(last known)</span><br>"
            f"<span class='dropped-warning'>{html.escape(DROPPED_FROM_SCOUT_REPORTS_MESSAGE)}</span>"
        )
    return f"{knowledge}%"


def _position_display(candidate, *, include_raw_external_positions: bool) -> str:
    positions = candidate.positions_for(
        include_raw_external_positions=include_raw_external_positions
    )
    return html.escape(", ".join(positions) or "Not yet captured")


def _layout(title: str, active_path: str, body: str) -> str:
    nav = "".join(_nav_link(path, label, active_path) for path, label in _NAV)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)} · FM Analytics</title>{_STYLE}</head>"
        f"<body><nav>{nav}</nav><main><h1>{html.escape(title)}</h1>{body}</main>"
        "</body></html>"
    )


def _error_page(title: str, message: str, active_path: str = "/") -> str:
    return _layout(title, active_path, f"<p class='error'>{html.escape(message)}</p>")


def _band(value) -> str:
    """One number when attributes are fully known; low–expected–high otherwise."""
    if value.lower == value.upper:
        return f"{value.central:.1f}"
    return f"{value.central:.1f} ({value.lower:.1f}–{value.upper:.1f})"


def role_score_cells(scores) -> str:
    """The three best-role score cells, shared by the Squad roster and a player's page.

    Each cell carries ``data-sort`` (the central score, empty when there is no
    eligible role) so a ``table.sortable`` can order by the number, not the text.
    """
    def sort_attr(value) -> str:
        return f" data-sort='{value.central:.4f}'" if value is not None else ""

    best = scores.attribute_based
    if best is not None:
        attribute = f"{html.escape(best.role_name)} ({_band(best.role_score.score)})"
    else:
        attribute = "<span class='muted'>no eligible role</span>"
    in_position = scores.in_position
    if in_position is not None:
        familiarity = (
            f"{in_position.position} {in_position.familiarity_rating}/20"
            if in_position.familiarity_known
            else f"{in_position.position} unknown (assumed {in_position.familiarity_rating}/20)"
        )
        in_position_text = (
            f"{html.escape(in_position.role_name)} ({html.escape(familiarity)})<br>"
            f"<b>{_band(in_position.position_adjusted_score)}</b>"
        )
    else:
        in_position_text = "<span class='muted'>no eligible role</span>"
    selection = scores.selection
    if selection is not None:
        selection_text = (
            f"{html.escape(selection.role_name)} ({selection.position} {selection.familiarity_rating}/20)<br>"
            f"<b>{_band(selection.selection_score)}</b>"
        )
    else:
        selection_text = "<span class='muted'>not selectable today</span>"
    return (
        f"<td{sort_attr(best.role_score.score if best else None)}>{attribute}</td>"
        f"<td{sort_attr(in_position.position_adjusted_score if in_position else None)}>{in_position_text}</td>"
        f"<td{sort_attr(selection.selection_score if selection else None)}>{selection_text}</td>"
    )


_SORTABLE_TABLE_SCRIPT = """
<script>
(function () {
  // Client-side column sort for tables marked class="sortable". A cell's
  // data-sort attribute, when present, is the sort value (numbers compare
  // numerically); otherwise its text is used. Empty values always sort last.
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var headers = table.querySelectorAll('tr:first-child > th');
    headers.forEach(function (th, column) {
      th.classList.add('sort-header');
      th.tabIndex = 0;
      function sort() {
        var descending = th.getAttribute('aria-sort') === 'ascending';
        headers.forEach(function (other) { other.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', descending ? 'descending' : 'ascending');
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows).filter(function (row) {
          return row.querySelector('td');
        });
        function value(row) {
          var cell = row.cells[column];
          if (!cell) return '';
          return cell.hasAttribute('data-sort') ? cell.getAttribute('data-sort') : cell.textContent.trim();
        }
        function compare(a, b) {
          var x = value(a), y = value(b);
          if (x === '' && y === '') return 0;
          if (x === '') return 1;
          if (y === '') return -1;
          var nx = parseFloat(x), ny = parseFloat(y);
          var result = (!isNaN(nx) && !isNaN(ny) && /^[-+]?[0-9.]/.test(x) && /^[-+]?[0-9.]/.test(y))
            ? nx - ny : x.localeCompare(y, undefined, {sensitivity: 'base'});
          return descending ? -result : result;
        }
        var keyed = rows.map(function (row, index) { return [row, index]; });
        keyed.sort(function (a, b) { return compare(a[0], b[0]) || a[1] - b[1]; });
        keyed.forEach(function (pair) { body.appendChild(pair[0]); });
      }
      th.addEventListener('click', sort);
      th.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sort(); }
      });
    });
  });
})();
</script>
"""


def _injury_risk_count(report: WeaknessReport) -> int:
    return sum(1 for weakness in report.weaknesses if weakness.kind in _INJURY_RISK_KINDS)


def _query_first(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name, [])
    return values[0].strip() if values and values[0].strip() else None


def _query_number(query: dict[str, list[str]], name: str, *, integer: bool = False):
    raw = _query_first(query, name)
    if raw is None:
        return None
    try:
        value = int(raw) if integer else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _scouting_filters(query: dict[str, list[str]]) -> ScoutingFilters:
    visibility = _query_first(query, "visibility") or "any"
    if visibility not in {"any", "known", "partial", "unknown"}:
        raise ValueError("visibility filter is invalid")
    facts = {
        key.removeprefix("fact."): value[0]
        for key, value in query.items()
        if key.startswith("fact.") and value and value[0]
    }
    return ScoutingFilters(
        position=_query_first(query, "position"), role_key=_query_first(query, "role"),
        minimum_age=_query_number(query, "minAge", integer=True),
        maximum_age=_query_number(query, "maxAge", integer=True),
        name_contains=_query_first(query, "name"),
        club_contains=_query_first(query, "club"), nationality=_query_first(query, "nationality"),
        footedness=_query_first(query, "footedness"),
        transfer_status=_query_first(query, "transferStatus"), availability=_query_first(query, "availability"),
        visibility=visibility, minimum_floor=_query_number(query, "minFloor"),
        minimum_ceiling=_query_number(query, "minCeiling"),
        include_unlikely=_query_first(query, "includeUnlikely") == "1",
        include_raw_external_positions=_query_first(query, "includeRawPositions") == "1",
        scouted_only=_scouting_view(query) == "scouted",
        market=_query_first(query, "market") or "any",
        expiring_months=_query_number(query, "expiringMonths", integer=True) or 6,
        maximum_value=_query_number(query, "maxValue", integer=True),
        search_match=_query_first(query, "searchMatch") or "any",
        ranking_sort=_query_first(query, "sort") or "median",
        ranking_descending={"desc": True, "asc": False}.get(_query_first(query, "dir") or ""),
        facts=facts,
    )


def _scouting_view(query: dict[str, list[str]]) -> str:
    """Which Scouting sub-tab is active. Defaults to 'all' -- role/position
    browsing of an unscouted candidate is a real, existing use (assessing fit
    before scouting anyone), not something a new default should silently
    hide behind a tab switch."""
    view = _query_first(query, "view")
    return view if view in {"scouted", "all"} else "all"


def _scouting_tab_nav(query: dict[str, list[str]]) -> str:
    """Switch tabs while keeping every other filter in the URL intact."""
    active = _scouting_view(query)
    kept = {key: values for key, values in query.items() if key != "view" and values}

    def link(view: str, label: str) -> str:
        params = dict(kept)
        params["view"] = [view]
        query_string = urlencode([(key, value) for key, values in params.items() for value in values])
        css_class = "tab-active" if view == active else "tab"
        return f"<a class='{css_class}' href='/scouting?{query_string}'>{html.escape(label)}</a>"

    return (
        "<nav class='scouting-tabs'>"
        + link("scouted", "Scouted players")
        + link("all", "All players (Player Search)")
        + "</nav>"
    )


def _options(items, selected: str | None, blank: str) -> str:
    output = f"<option value=''>{html.escape(blank)}</option>" if blank else ""
    for value, label in items:
        selected_text = " selected" if value == selected else ""
        output += f"<option value='{html.escape(value, quote=True)}'{selected_text}>{html.escape(label)}</option>"
    return output


def _input_value(value: object) -> str:
    return "" if value is None else html.escape(str(value), quote=True)


def _label(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").capitalize()


class ScoutingPoolNotBuilt(RuntimeError):
    """FM has not built its Player Search pool, so a refresh needs a decision.

    The capture tool exits 3 for exactly this case and changes nothing, which
    lets the Scouting page offer the safe route (open Player Search in FM)
    alongside the one that runs FM's code inside the live save.
    """


POOL_NOT_BUILT_EXIT_CODE = 3


def _refresh_notice(refreshed: str | None) -> str:
    """Say which route produced the capture, so the risky one is never silent."""
    if refreshed == "1":
        return (
            "<p class='muted'>Scouting data refreshed by reading the list FM had "
            "already built. Nothing was written to FM.</p>"
        )
    if refreshed == "rebuilt":
        return (
            "<p class='warn'>Scouting data refreshed by asking FM to build its "
            "player list inside the running game. If this save later fails to "
            "load, this is the step to suspect.</p>"
        )
    return ""


def _pool_not_built_page() -> str:
    """Offer the safe route first, and state plainly what the other one does.

    Reached only when FM has not built its Player Search pool in this process
    and nothing has been written to FM. Opening Player Search in FM is listed
    first and styled as the primary action because it gets the same data with
    no native call at all.
    """
    body = (
        "<h2>FM has not built its player list yet</h2>"
        "<p>This app normally reads the list of players you are allowed to know "
        "about straight out of FM's memory, without touching the game. FM builds "
        "that list while you play, and it starts empty each time you launch FM. "
        "It is empty right now, so there is nothing to read.</p>"
        "<p class='muted'>Nothing has been sent to FM. Your save has not been "
        "touched.</p>"
        "<h3>Recommended: build it in FM yourself</h3>"
        "<p>Switch to FM, open <b>Scouting &rarr; Players &rarr; Player Search</b> "
        "once, then come back and refresh. FM builds the list as part of its "
        "normal work, and this app goes back to only reading. You need to do this "
        "once per FM session, not once per refresh.</p>"
        "<form class='refresh' method='post' action='/scouting/refresh'>"
        "<button type='submit'>I have opened Player Search &mdash; refresh</button>"
        "</form>"
        "<h3 class='warn'>Or: let this app ask FM to build it</h3>"
        "<p>This runs FM's own code inside your running game to build the list. "
        "It usually works, and it is how this page behaved until now. But it "
        "interrupts FM at a moment FM did not choose, and that is the step "
        "suspected of producing saves that write successfully and then fail to "
        "load.</p>"
        "<p><b>Only do this on a save you would not mind losing</b>, or after "
        "taking a copy of your save file.</p>"
        "<form class='refresh' method='post' action='/scouting/refresh'>"
        "<input type='hidden' name='allow_rebuild' value='1'>"
        "<button type='submit' class='danger'>Ask FM to build the list "
        "(risks this save)</button>"
        "</form>"
    )
    return _layout("Scouting", "/scouting", body)


def _scouting_refresh_command(path: Path) -> Callable[..., str]:
    """Build the bounded local command used by the Scouting-page refresh button."""
    project_root = Path(__file__).resolve().parents[3]
    capture_tool = project_root / "tools" / "fm20_scouting_feed.py"
    target = path.resolve()

    def refresh(*, allow_rebuild: bool = False) -> str:
        command = [
            "uv",
            "run",
            "--extra",
            "research",
            "python",
            str(capture_tool),
            "--output",
            str(target),
        ]
        if allow_rebuild:
            command.append("--allow-rebuild")
        if target.exists():
            command.extend(("--base-feed", str(target), "--replace"))
        try:
            result = subprocess.run(
                command,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Scouting refresh timed out after three minutes.") from exc
        if result.returncode == POOL_NOT_BUILT_EXIT_CODE:
            raise ScoutingPoolNotBuilt(
                (result.stderr or result.stdout or "").strip()[-2_000:]
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown capture failure").strip()
            raise RuntimeError(f"Scouting refresh failed: {detail[-2_000:]}")
        return (result.stdout or "Scouting data refreshed.").strip()

    return refresh
