"""Shared HTML rendering and request parsing helpers for the web view."""

from __future__ import annotations

import html
import os
import re
import subprocess
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from fm_analytics.analytics import (
    MVP_CATALOGUE,
    ScoutingFilters,
    SORTS_BY_MODE,
    scouting_mode,
    sort_for_mode,
    TacticDefinition,
    TacticSlot,
    WeaknessKind,
    WeaknessReport,
)
from fm_analytics.web.rendering_content import (
    DROPPED_FROM_SCOUT_REPORTS_MESSAGE,
    _is_navigation_active,
    _navigation,
    _position_display,
    _raw_position_notice,
    _readable_attribute,
    _scouting_knowledge_cell,
    _section_for,
    _slot_reasoning,
    _tactical_shortfalls,
    _tactic_notes,
)
from fm_analytics.web.ui import cell_details
from fm_analytics.web.rendering_styles import _STYLE
from fm_analytics.web.scouting_notices import _knowledge_notice, _refresh_notice, _refresh_job_notice


_NAV_GROUPS: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("Overview", (("/", "Command centre", "⌂"), ("/league", "League", "≋"))),
    (
        "Squad intelligence",
        (
            ("/squad", "Squad", "◫"),
            ("/roles", "Roles", "◎"),
            ("/depth", "Depth", "↕"),
        ),
    ),
    (
        "Matchday",
        (
            ("/tactics", "Tactics", "⌁"),
            ("/tactic-checks", "Tactic checks", "✓"),
            ("/set-pieces", "Set pieces", "✦"),
            ("/matches", "Matches", "▤"),
        ),
    ),
    ("Recruitment", (("/scouting", "Scouting", "⌕"),)),
    ("System", (("/data", "Data health", "◌"),)),
)

_TEMPLATE_ENVIRONMENT = Environment(
    loader=FileSystemLoader(Path(__file__).with_name("templates")),
    autoescape=select_autoescape(("html", "xml")),
    trim_blocks=True,
    lstrip_blocks=True,
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
# Limit mounted rows; the complete scouting snapshot is stored separately.
_SCOUTING_ROW_CEILING = 1000

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




def _asset_url(filename: str) -> str:
    """Return a content-versioned URL for a bundled shell asset.

    HTML responses are deliberately not cached, while the asset handler may
    cache a stylesheet for an hour.  A digest in the URL lets a normal page
    refresh pick up a newly built stylesheet without making every static
    response uncacheable.  Do not memoise this: local development rebuilds
    assets while the server is still running.
    """
    try:
        content = resources.files("fm_analytics.web").joinpath("static", filename).read_bytes()
    except FileNotFoundError:
        # Preserve the useful static-handler error when assets have not been
        # built yet instead of preventing the page itself from rendering.
        return f"/static/{filename}"
    digest = sha256(content).hexdigest()[:12]
    return f"/static/{filename}?v={digest}"


def _layout(title: str, active_path: str, body: str, *, wide: bool = False) -> str:
    """Render a shared shell while legacy page fragments migrate incrementally.

    Page renderers already escape their dynamic values.  Marking the resulting
    fragment safe here lets the new Jinja shell coexist with those established
    renderers without reimplementing the analytics or its presentation at once.
    """
    return _TEMPLATE_ENVIRONMENT.get_template("base.html").render(
        title=title,
        section=_section_for(active_path),
        breadcrumb=None if active_path == "/" else _section_for(active_path),
        wide=wide,
        navigation=_navigation(active_path),
        assets={"css": _asset_url("app.css"), "js": _asset_url("app.js")},
        body=Markup(body),
        legacy_style=Markup(_STYLE),
    )


def _error_page(title: str, message: str, active_path: str = "/") -> str:
    body = (
        "<section class='fm-error-state'><span class='eyebrow'>Action needed</span>"
        f"<h2>{html.escape(title)}</h2>"
        f"<p class='error'>{html.escape(message)}</p>"
        "<p class='muted'>Check the data source, then return to the section when it is available.</p>"
        "</section>"
    )
    return _layout(title, active_path, body)


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
        return f" data-sort='{value.central:.4f}'" if value is not None else " data-sort=''"

    def display(role_name, score, note=""):
        return "<b>" + _band(score) + "</b>" + cell_details(
            role_name.split(" (", 1)[0], [role_name, note]
        )

    best = scores.attribute_based
    if best is not None:
        attribute = display(best.role_name, best.role_score.score)
    else:
        attribute = "<span class='muted'>no eligible role</span>"
    in_position = scores.in_position
    if in_position is not None:
        familiarity = (
            f"{in_position.position} {in_position.familiarity_rating}/20"
            if in_position.familiarity_known
            else f"{in_position.position} unknown (assumed {in_position.familiarity_rating}/20)"
        )
        in_position_text = display(in_position.role_name, in_position.position_adjusted_score, familiarity)
        if not in_position.familiarity_known:
            in_position_text += "<span class='muted'>Familiarity unknown</span>"
    else:
        in_position_text = "<span class='muted'>no eligible role</span>"
    selection = scores.selection
    if selection is not None:
        selection_text = display(
            selection.role_name, selection.selection_score,
            f"{selection.position} {selection.familiarity_rating}/20",
        )
        if not selection.familiarity_known:
            selection_text += "<span class='muted'>Familiarity unknown</span>"
    else:
        selection_text = "<span class='muted'>not selectable today</span>"
    return (
        f"<td{sort_attr(best.role_score.score if best else None)}>{attribute}</td>"
        f"<td{sort_attr(in_position.position_adjusted_score if in_position else None)}>{in_position_text}</td>"
        f"<td{sort_attr(selection.selection_score if selection else None)}>{selection_text}</td>"
    )


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
    tactic_key = _query_first(query, "tactic")
    role_key = _query_first(query, "role")
    scout_more_only = _query_first(query, "scoutMore") == "1"
    # Which columns exist depends on which table is showing, so a sort that
    # belongs to another table (an XI-gain sort with no tactic chosen, say)
    # falls back to this table's default instead of silently doing nothing.
    mode = scouting_mode(tactic_key, role_key)
    requested_sort = _query_first(query, "sort")
    if scout_more_only and requested_sort not in SORTS_BY_MODE[mode]:
        requested_sort = "player_median" if tactic_key else "median"
    ranking_sort = sort_for_mode(requested_sort, mode)
    expiring_months = _query_number(query, "expiringMonths", integer=True)
    return ScoutingFilters(
        tactic_key=tactic_key,
        position=_query_first(query, "position"), role_key=role_key,
        minimum_age=_query_number(query, "minAge", integer=True),
        maximum_age=_query_number(query, "maxAge", integer=True),
        name_contains=_query_first(query, "name"),
        club_contains=_query_first(query, "club"), nationality=_query_first(query, "nationality"),
        footedness=_query_first(query, "footedness"),
        transfer_status=_query_first(query, "transferStatus"), availability=_query_first(query, "availability"),
        visibility=visibility, minimum_floor=_query_number(query, "minFloor"),
        minimum_ceiling=_query_number(query, "minCeiling"),
        maximum_range=_query_number(query, "maxRange"),
        minimum_known_attributes=_query_number(query, "minKnown", integer=True),
        scout_more_only=scout_more_only,
        include_unlikely=_query_first(query, "includeUnlikely") == "1",
        include_raw_external_positions=_query_first(query, "includeRawPositions") == "1",
        scouted_only=_scouting_view(query) == "scouted",
        include_former_scouted=_query_first(query, "everScouted") == "1",
        market=_query_first(query, "market") or "any",
        expiring_months=6 if expiring_months is None else expiring_months,
        maximum_value=_query_number(query, "maxValue", integer=True),
        transfer_interest=_query_first(query, "transferInterest") or "any",
        loan_interest=_query_first(query, "loanInterest") or "any",
        ranking_sort=ranking_sort,
        ranking_descending={"desc": True, "asc": False}.get(_query_first(query, "dir") or ""),
        facts=facts,
    )


def _scouting_limit(query: dict[str, list[str]]) -> int:
    """How many result rows to render: the default page, or what "Show more" asked for."""
    try:
        requested = int(_query_first(query, "limit") or 0)
    except ValueError:
        requested = 0
    return min(max(requested, _MAX_SCOUTING_ROWS), _SCOUTING_ROW_CEILING)


def _scouting_view(query: dict[str, list[str]]) -> str:
    """Which Scouting sub-tab is active. Defaults to 'all' -- role/position
    browsing of an unscouted candidate is a real, existing use (assessing fit
    before scouting anyone), not something a new default should silently
    hide behind a tab switch."""
    view = _query_first(query, "view")
    return view if view in {"scouted", "all"} else "all"


def _scouting_href(query: dict[str, list[str]], **updates: str | None) -> str:
    """A `/scouting` URL built from the filters already in the address bar.

    Every parameter the caller does not name is carried over untouched --
    market, knowledge, visibility, the active tab, the row limit and the
    multi-value ``fact.*`` filters alike -- so following a link never quietly
    discards the manager's other filters. Naming a parameter replaces it,
    which is how a link supplies the tactic, position or role it is about;
    naming it ``None`` or ``""`` drops it, which is how a link clears the
    filters it supersedes. Empty values are dropped either way.
    """
    params = {key: list(values) for key, values in query.items() if values}
    for key, value in updates.items():
        params.pop(key, None)
        if value not in (None, ""):
            params[key] = [str(value)]
    return "/scouting?" + urlencode(
        [(key, value) for key, values in params.items() for value in values]
    )


def _scouting_tab_nav(query: dict[str, list[str]]) -> str:
    """Switch tabs while keeping every other filter in the URL intact."""
    active = _scouting_view(query)

    def link(view: str, label: str) -> str:
        css_class = "tab-active" if view == active else "tab"
        href = _scouting_href(query, view=view)
        return f"<a class='{css_class}' href='{href}'>{html.escape(label)}</a>"

    return (
        "<nav class='scouting-tabs fm-scouting-tabs'>"
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


def _tactic_choices(items, pinned_keys: tuple[str, ...]) -> list[tuple[str, str]]:
    """`(key, name)` pairs with the manager's pinned tactics first, starred.

    Pins keep the order they were given in (primary first); every other tactic
    follows in the order `items` supplied. With no pins the list is unchanged.
    """
    pairs = list(items)
    if not pinned_keys:
        return pairs
    by_key = dict(pairs)
    pinned = [(key, "★ " + by_key[key]) for key in pinned_keys if key in by_key]
    rest = [(key, name) for key, name in pairs if key not in pinned_keys]
    return pinned + rest


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


def _pool_not_built_page() -> str:
    """Offer the safe route first, and state plainly what the other one does.

    Reached only when FM has not built its Player Search pool in this process
    and nothing has been written to FM. Opening Player Search in FM is listed
    first and styled as the primary action because it gets the same data with
    no native call at all.
    """
    return _layout("Scouting", "/scouting", _pool_not_built_body())


def _pool_not_built_body() -> str:
    """Recovery choices, also shown after a background refresh fails."""
    return (
        "<section class='fm-scouting-empty-hero'><span class='eyebrow'>Scouting data needed</span>"
        "<h2>FM has not built its player list yet</h2>"
        "<p>This app normally reads the list of players you are allowed to know "
        "about straight out of FM's memory, without touching the game. FM builds "
        "that list while you play, and it starts empty each time you launch FM. "
        "It is empty right now, so there is nothing to read.</p>"
        "<p>Nothing has been sent to FM. Your save has not been touched.</p></section>"
        "<section class='fm-workspace-panel fm-scouting-safe-refresh'><div class='fm-panel-heading'><div>"
        "<h2>Recommended: build it in FM yourself</h2>"
        "<p>Switch to FM, open <b>Scouting &rarr; Players &rarr; Player Search</b> "
        "once, then come back and refresh. FM builds the list as part of its "
        "normal work, and this app goes back to only reading. You need to do this "
        "once per FM session, not once per refresh.</p></div></div>"
        "<form class='refresh' method='post' action='/scouting/refresh'>"
        "<button type='submit'>I have opened Player Search &mdash; refresh</button>"
        "</form></section>"
        "<section class='fm-workspace-panel fm-scouting-risk-refresh'><div class='fm-panel-heading'><div>"
        "<h2>Or: let this app ask FM to build it</h2>"
        "<p>This runs FM's own code inside your running game to build the list. "
        "It usually works, and it is how this page behaved until now. But it "
        "interrupts FM at a moment FM did not choose, and that is the step "
        "suspected of producing saves that write successfully and then fail to "
        "load.</p>"
        "<p><b>Only do this on a save you would not mind losing</b>, or after taking a copy of your save file.</p>"
        "</div></div>"
        "<form class='refresh' method='post' action='/scouting/refresh'>"
        "<input type='hidden' name='allow_rebuild' value='1'>"
        "<button type='submit' class='danger'>Ask FM to build the list "
        "(risks this save)</button>"
        "</form></section>"
    )


def _scouting_refresh_command(path: Path) -> Callable[..., str]:
    """Build the bounded local command used by the Scouting-page refresh button."""
    project_root = Path(__file__).resolve().parents[3]
    capture_tool = project_root / "tools" / "fm20_scouting_feed.py"
    target = path.resolve()

    def refresh(*, allow_rebuild: bool = False) -> str:
        from fm_analytics.web.providers import scouting_json_provider

        temporary = target.with_suffix(target.suffix + ".tmp")
        command = [
            "uv",
            "run",
            "--extra",
            "research",
            "python",
            str(capture_tool),
            "--output",
            str(temporary),
        ]
        if allow_rebuild:
            command.append("--allow-rebuild")
        if target.exists():
            command.extend(("--base-feed", str(target)))
        try:
            temporary.unlink(missing_ok=True)
            try:
                result = subprocess.run(
                    command,
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=240,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("Scouting refresh timed out after four minutes.") from exc
            if result.returncode == POOL_NOT_BUILT_EXIT_CODE:
                raise ScoutingPoolNotBuilt(
                    (result.stderr or result.stdout or "").strip()[-2_000:]
                )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "unknown capture failure").strip()
                raise RuntimeError(f"Scouting refresh failed: {detail[-2_000:]}")
            # Validate the complete feed before promoting it to last-good data.
            scouting_json_provider(temporary)()
            os.replace(temporary, target)
            return (result.stdout or "Scouting data refreshed.").strip()
        finally:
            temporary.unlink(missing_ok=True)

    return refresh
