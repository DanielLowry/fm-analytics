# FM Analytics

Manager-visible analytics for Football Manager 2020: recommends tactics, XIs,
and recruitment targets using only information a human manager could see —
never hidden Current Ability, Potential Ability, or other internal values.

## Layout

```
src/fm_analytics/            CLI, the reporting path, the bridge contract
src/fm_analytics/analytics/  role/tactic scoring, catalogue, depth, weaknesses — see analytics/CLAUDE.md
src/fm_analytics/bridge/     HTTP boundary onto the game process — see bridge/CLAUDE.md
src/fm_analytics/domain/     Player/Squad/GameState and Visibility — the shared vocabulary
src/fm_analytics/api/        HTTP client for the bridge
src/fm_analytics/imports/    parses manager-visible FM20 HTML exports
src/fm_analytics/persistence/  SQLite capture store, versioned schema (see below)
src/fm_analytics/reporting.py  the ONE "compute a squad recommendation" path
src/fm_analytics/web/        read-only browser view over reporting.py
tools/                       low-level FM20 probe/monitor utilities (research-only)
tests/                       unittest-based tests, one module per source area
docs/                        architecture, delivery phases, contracts — see docs/README.md
data/                        local runtime captures — gitignored, absent on a fresh clone
```

## The one rule that matters most

`fm_analytics.reporting.build_recommendation_bundle` is the single full
recommendation computation used by the CLI (`fm-analytics --recommend`) and
the Tactics/Depth web views. `build_squad_role_matrix` is the deliberately
lighter shared computation for the Squad roster: it must not evaluate tactics.
**Never duplicate scoring logic into the CLI or web layers** — a number shown
on a page and a number printed by the CLI must be the same number, computed
the same way. Add or reuse a reporting helper rather than recomputing
analytics inside a handler.

## Running things

```bash
uv run python -m unittest discover -s tests -v      # full test suite
uv run fm-analytics --fixture src/fm_analytics/fixtures/sample-game.json --recommend
uv run fm-web --fixture src/fm_analytics/fixtures/sample-game.json        # http://127.0.0.1:8766
```

No third-party packages are required for the core path (`frida` is an
optional dependency for research tooling only). CI (`.github/workflows/ci.yml`)
also compiles every source file and runs a bridge fixture smoke test — worth
checking before assuming a change is done.

## Getting a squad worth testing against

`fixtures/sample-game.json` is three players. It exercises the code paths but
tells you nothing about cost or about how a recommendation reads, so don't
judge either from it. Everything realistic lives in `data/`, which is
gitignored and will not exist on a fresh clone: the scouting pages fall back
to no candidates at all when it's missing (`web/server.py:_default_scouting_path`
tries three filenames in order), and `--snapshot-db` raises a bare
`RuntimeError` if the local capture predates the current `SCHEMA_VERSION` —
there are no migrations, so an old capture is simply unreadable.

For performance work, generate a synthetic squad of the size you care about
rather than reaching for the fixture or a capture. Measure the full bundle
against the 25-tactic catalogue: it evaluates every permitted role version
and then solves the player assignment, so a change that does not improve that
end-to-end measurement has not improved the page load.

## Before editing

- `src/fm_analytics/web/` is split by concern: `server.py` (the caching
  HTTP server + CLI arg-parsing), `handlers.py` (one `_xxx_page` method per
  route; the Scouting routes live in `scouting_pages.py` as a mixin), `rendering.py` (shared HTML helpers), `providers.py` (data
  sources). Find the route you're changing in `handlers.py` first rather
  than starting from `server.py`.
- `src/fm_analytics/analytics/xi_selection.py` expands only the explicitly
  allowed role versions of a tactic, then uses an exact player-to-slot
  assignment. Read `analytics/CLAUDE.md` before changing either half: the
  separation is what makes the recommendation both fast and complete.
- Recruitment currently exists twice and the two halves have not been
  reconciled: `analytics/recruitment.py` turns weaknesses into briefs and
  shortlists them against `imports.VisibleExportPlayer` (CLI, `--candidate-html`),
  while `analytics/scouting.py` ranks `ScoutingCandidate` from a JSON feed
  (web, `/scouting`). `VisibleExportPlayer` is a strict field subset of
  `ScoutingCandidate`. Adding a feature to one side without collapsing the two
  models deepens the split — prefer unifying over mirroring.
- Scoring code is a transparent, reviewable POC, not a reproduction of FM's
  hidden match engine. It's fine to be wrong for football reasons; it must
  never be wrong because it read data a manager couldn't see.

For product/design rationale (why a feature exists, what's deliberately
deferred), see [docs/README.md](docs/README.md) rather than re-deriving it —
it's kept current and is more reliable than inferring intent from code.
