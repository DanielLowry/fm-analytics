"""Small, reusable notices for the scouting pages."""

from __future__ import annotations

import html


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
    if refreshed == "started":
        return (
            "<p class='muted'>Scouting refresh started in the background.</p>"
        )
    if refreshed == "running":
        return "<p class='warn'>A scouting refresh is already running.</p>"
    return ""


def _refresh_job_notice(job, capture_age: str | None, progress=None) -> str:
    """Render the latest background job without coupling HTML to its type."""
    age = f" Last good capture: {html.escape(capture_age)} old." if capture_age else ""
    progress = progress or {}
    label = progress.get("label", "Scouting refresh") if job.status == "running" else "Scouting results ready" if job.status == "succeeded" else "Scouting refresh failed"
    remaining = progress.get("remaining_seconds")
    detail = "Estimating time remaining…" if remaining is None else f"About {remaining}s remaining"
    if progress.get("total"):
        detail = f"{progress.get('completed', 0):,} / {progress['total']:,} players · {detail}"
    panel = (
        "<section id='scouting-refresh-progress' class='fm-refresh-progress fm-workspace-panel'"
        f" data-status='{html.escape(job.status)}' data-job-id='{progress.get('job_id', 0)}'"
        f" data-generation='{progress.get('generation', 0)}'"
        + (" hidden" if job.status == "idle" else "") + ">"
        "<strong data-refresh-label>" + html.escape(label) + "</strong>"
        f"<progress max='100' value='{progress.get('percent', 0)}' aria-label='Scouting refresh progress'></progress>"
        "<p data-refresh-detail role='status' aria-live='polite'>" + (html.escape(detail) if job.status == "running" else "") + "</p>"
        "<p class='muted' data-refresh-summary>"
    )
    if job.status == "idle":
        return panel + f"Refresh idle.{age}</p></section>"
    started = job.started_at.isoformat(timespec="seconds") if job.started_at else "unknown"
    route = (
        "<p class='warn'>This refresh asks FM to build its player list inside the "
        "running game. This carries the save risk described below.</p>"
        if job.allow_rebuild else "<p class='muted'>Nothing was written to FM.</p>"
    )
    reload = "<a href='' class='fm-text-link'>Reload to check refresh status</a>"
    if job.status == "running":
        return panel + f"Refresh running since {html.escape(started)}.{age} {reload}</p>{route}</section>"
    ended = job.ended_at.isoformat(timespec="seconds") if job.ended_at else "unknown"
    if job.status == "failed":
        return panel + f"Refresh failed at {html.escape(ended)}: {html.escape(job.error)}.{age}</p>{route}</section>"
    return panel + f"Refresh succeeded at {html.escape(ended)}: {html.escape(job.message)}.{age}</p>{route}</section>"


def _knowledge_notice(note: tuple[str, bool] | None) -> str:
    """Say whether the latest scouting capture was kept in player history."""
    if note is None:
        return ""
    message, recorded = note
    return f"<p class='{'muted' if recorded else 'warn'}'>{html.escape(message)}</p>"
