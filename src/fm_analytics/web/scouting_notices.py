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
    return ""


def _knowledge_notice(note: tuple[str, bool] | None) -> str:
    """Say whether the latest scouting capture was kept in player history."""
    if note is None:
        return ""
    message, recorded = note
    return f"<p class='{'muted' if recorded else 'warn'}'>{html.escape(message)}</p>"
