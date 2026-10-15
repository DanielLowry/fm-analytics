"""Setup guidance and provenance for authored and published tactics."""

import html
from urllib.parse import quote

from fm_analytics.analytics.catalogue import TacticDefinition


def tactic_setup_section(tactic: TacticDefinition) -> str:
    if not tactic.setup_notes and tactic.source is None:
        return ""
    source = tactic.source
    published = ""
    if source is not None:
        published = (
            f"<p><a class='button-link' href='/tactics/{quote(tactic.key, safe='')}/download'>"
            "Download original FM tactic (.fmf)</a></p>"
            f"<p>By {html.escape(source.author)} · "
            f"<a href='{html.escape(source.url, quote=True)}'>Published setup</a></p>"
            f"<p>{html.escape(source.verification)}</p>"
        )
    notes = "".join(f"<li>{html.escape(note)}</li>" for note in tactic.setup_notes)
    rows = "".join(
        f"<tr><td>{html.escape(slot.key)}</td><td>"
        + html.escape("; ".join(slot.instructions) if slot.instructions else (
            "See original FM file" if source is not None else "Role and duty defaults"
        )) + "</td></tr>"
        for slot in tactic.slots
    )
    return (
        "<section class='fm-workspace-panel' id='tactic-setup'><h2>FM setup</h2>"
        + published + (f"<ul>{notes}</ul>" if notes else "")
        + "<details><summary>Additional player instructions</summary>"
        + ("<p>Only independently verified additions are listed here. Import the original file for "
           "the complete player instructions and set pieces.</p>" if source is not None else "")
        + "<table><tr><th>Slot</th><th>Instructions</th></tr>" + rows
        + "</table></details></section>"
    )
