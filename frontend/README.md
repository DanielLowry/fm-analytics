# FM Analytics frontend

This directory contains the source for the packaged web shell.  It takes a
small, purpose-built subset of TailAdmin's visual language; the application
does not vendor the upstream dashboard or its optional dependencies.

```sh
npm install
npm run build
```

The build writes `app.css` and `app.js` to `src/fm_analytics/web/static/`.
Those compiled assets are committed because the Python web server serves them
directly and has no Node runtime in production.

## UI review and remaining acceptance work

The [30 September 2026 review](../docs/ui-review-2026-09-30.md) records the
dark-theme, responsive-layout, navigation and consistency acceptance work.
The 2 October implementation record in that review documents the table,
filtering and progressive-disclosure changes; broad acceptance criteria remain
open where the full state matrix has not been verified. Follow the shared-component
direction there when changes are scheduled, and rebuild the committed assets
after editing these sources.

## Tables and filtering

`app.js` initialises `tables.js` on every page. Each data table gets a local
search, row count, reset control and keyboard-accessible column sorting.
Numeric `data-sort` values take precedence over display text. Starting-XI
explanations remain attached to their owning row. Tables scroll within their
own containers, including nested tables in player reports.

Every table also has a small Copy to clipboard button, provided by
`table-copy.js`. It copies headers and visible rows in their current order as
tab-separated text for spreadsheet pasting. Closed explanations and nested
tables are excluded from a cell's text; each nested table has its own button.
The legacy copy fallback supports pages served without the Clipboard API.

Player reports also have a Copy player to clipboard button beside the profile.
It copies name, age, club, captured positional familiarity except 1/20, and
the full relevant attribute groups as readable text. Goalkeepers use the
goalkeeping attribute set; scouting ranges, unknowns and historical dates
remain intact.

Squad and Scouting share `position-roles.js` and the catalogue choices from
`web/ui.py`. Position changes replace role choices immediately, preserve a
compatible selection and clear an incompatible one. Squad requires a position
before enabling roles; Scouting allows roles across any position. Compare
remains an explicit GET submission for the server's scored squad comparison.
When other club squads are captured, its Squad selector offers the first team,
each other squad and the whole club. Other-squad tables display the shared
best-role scores and link to full position reports with a return link to their
section of the Squad page. Tactic/XI inputs still come from the first team.

Scouting uses `scouting.js` and the pure display predicates in
`scouting-data.js`. The browser loads a complete snapshot for the selected
position, role, tactic and raw-position policy from `/scouting/results?snapshot=1`.
The server supplies scores, rendered cells and both sort orders through the
existing analytics helpers. Ordinary filtering, sorting and Show more then
operate locally across the full snapshot, including rows outside the visible
100. Changing the scoring context loads a new snapshot; four recent contexts
are retained for the current visit. The ordinary GET page and results endpoint
remain the fallback for browsers without JavaScript.

The canonical web position order lives in `web/ui.py`, with the same sequence
in `tables.js`. Keep both in agreement when adding a position. Detailed cell
copy uses `cell_details`: a concise summary and escaped bullet points, rather
than abbreviated football terms whose meaning would require guessing.
