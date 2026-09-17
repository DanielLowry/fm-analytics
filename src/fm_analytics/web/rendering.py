"""Shared HTML rendering and request parsing helpers for the web view."""

from __future__ import annotations

import html
import subprocess
from pathlib import Path
from typing import Callable, Sequence

from fm_analytics.analytics import (
    ScoutingFilters,
    TacticDefinition,
    WeaknessKind,
    WeaknessReport,
)


_NAV: tuple[tuple[str, str], ...] = (
    ("/", "Dashboard"),
    ("/squad", "Squad"),
    ("/roles", "Roles"),
    ("/tactics", "Tactics"),
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
  .badge-scout { background: #fff2d6; color: #805400; }
  .badge-proven { background: #e3f3e1; color: #1e6b1e; }
  .badge-unlikely { background: #eee; color: #555; }
  .attribute-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.35rem; }
  .attribute-grid div { border: 1px solid #e5e5e5; padding: 0.35rem; border-radius: 0.25rem; }
  .attribute-grid b { display: block; font-size: 0.75rem; color: #667; }
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

    These fields (style/description/whyGood/keyRequirements/tags) are
    manager-facing commentary carried alongside the tactic in the catalogue
    data, not scoring input -- a tactic with none of them still renders
    correctly, since older catalogue entries may not define any.
    """
    if not any(
        (tactic.style, tactic.description, tactic.why_good, tactic.key_requirements, tactic.tags)
    ):
        return ""
    parts = []
    if tactic.style:
        parts.append(f"<p><b>{html.escape(tactic.style)}</b></p>")
    if tactic.description:
        parts.append(f"<p>{html.escape(tactic.description)}</p>")
    if tactic.why_good:
        parts.append(f"<p class='muted'><b>Why it works:</b> {html.escape(tactic.why_good)}</p>")
    if tactic.key_requirements:
        parts.append(
            "<p class='muted'><b>Needs:</b> "
            + ", ".join(html.escape(item) for item in tactic.key_requirements)
            + "</p>"
        )
    if tactic.tags:
        parts.append(
            "<p>"
            + " ".join(f"<span class='tag'>{html.escape(tag)}</span>" for tag in tactic.tags)
            + "</p>"
        )
    return "".join(parts)


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
        "term visibility gap. They can reveal secondary positions FM does not "
        f"currently show the manager ({raw_count} captured).</p>"
    )


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
        club_contains=_query_first(query, "club"), nationality=_query_first(query, "nationality"),
        footedness=_query_first(query, "footedness"),
        transfer_status=_query_first(query, "transferStatus"), availability=_query_first(query, "availability"),
        visibility=visibility, minimum_floor=_query_number(query, "minFloor"),
        minimum_ceiling=_query_number(query, "minCeiling"),
        include_unlikely=_query_first(query, "includeUnlikely") == "1",
        include_raw_external_positions=_query_first(query, "includeRawPositions") == "1",
        facts=facts,
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


def _scouting_refresh_command(path: Path) -> Callable[[], str]:
    """Build the bounded local command used by the Scouting-page refresh button."""
    project_root = Path(__file__).resolve().parents[3]
    capture_tool = project_root / "tools" / "fm20_scouting_feed.py"
    target = path.resolve()

    def refresh() -> str:
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
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown capture failure").strip()
            raise RuntimeError(f"Scouting refresh failed: {detail[-2_000:]}")
        return (result.stdout or "Scouting data refreshed.").strip()

    return refresh

