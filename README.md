# FM Analytics

[![CI](https://github.com/DanielLowry/fm-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/DanielLowry/fm-analytics/actions/workflows/ci.yml)

An experimental analytics department for Football Manager 2020. The system is
intended to make recommendations from information visible to the human manager,
without using hidden Current Ability, Potential Ability, or other internal
values.

The repository contains a read-only Linux/Proton bridge for the controlled
first-team squad, plus a deterministic fixture path:

```text
FM20 -> read-only Linux probes -> Python bridge HTTP API -> Python analytics
fixture -----------------------> Python bridge HTTP API -> Python client
```

The current delivery target is an
[early-game decision-support MVP](docs/mvp.md): compare a small set of baseline
tactics and valid XIs for the current squad, explain weaknesses, and shortlist
only manager-discoverable recruitment candidates while preserving exact,
ranged, unknown, and stale knowledge. Opposition-specific tactical changes are
deliberately later work.

## Repository layout

```text
src/fm_analytics/          Python bridge, client, domain objects, and CLI
src/fm_analytics/analytics/ Role/tactic scoring, catalogue (data/catalogue.json), depth
src/fm_analytics/reporting.py Shared "compute a squad recommendation" path (CLI + web)
src/fm_analytics/web/      Read-only browser view over the same reporting path
tools/                     Low-level FM20 probe and monitor utilities
tests/                     Python contract, source, and client tests
docs/                      Architecture and delivery notes
```

## Tests and fixture mode

No third-party Python packages are required.

```bash
uv run fm-analytics --fixture src/fm_analytics/fixtures/sample-game.json
uv run python -m unittest discover -s tests -v
```

## Automated current-squad recommendation

With FM20 running and a save loaded, one command now reads the managed squad
and recommends a tactic, starting XI, substitutes, weaknesses, and recruitment
briefs. No HTML export, open player screen, or HTTP server is required:

```bash
uv run fm-analytics --direct-live --recommend \
  --snapshot-db data/fm-analytics.sqlite3
```

The existing bridge-server route remains available when an HTTP client needs
the same owned-squad data. Start the bridge and request a recommendation in
another terminal:

```bash
FM_BRIDGE_SOURCE=linux-proton uv run fm-bridge
```

```bash
uv run fm-analytics --recommend --snapshot-db data/fm-analytics.sqlite3
```

This path requires no HTML export or open player/table screen. The bridge
restricts attribute reads to the active manager's verified first-team roster,
requires all 41 allowlisted attributes per player, and rejects a mismatched
manager, club, date, or player set. It supplies exact owned-player attributes
alongside live readiness for tactic, XI, bench, weakness, and recruitment-brief
analysis. The CLI additionally rejects game/squad date or club mismatches. A
direct live run on the 24 June 2019 Hungerford save supplied all 32 role
inputs and selected a legal XI in the versioned narrow diamond; the three
wide templates could not fill a left-sided wide slot. The role weights remain
provisional football judgments. Weaknesses are judged relative to the squad
itself rather than against fixed scores (`weakness-v2`): a starter is a weak
link when well below the XI's median role fit, and cover is weak when it drops
off sharply from the starter it replaces. The same analysis therefore applies
to any club; comparison against rival squads needs other clubs' data and is
separate work. A fresh live run through the HTTP bridge is still
needed to validate that separate transport path against FM.

The tactic and role catalogue has since grown past what that run exercised: it
now covers 25 tactics and 28 roles (`fm20-expanded-tactics-v1`, defined as data in
`src/fm_analytics/analytics/data/catalogue.json` rather than Python literals),
so a fresh live run would compare more shapes than the four described above.

Each formation slot now has a small permissible family of role/duty choices.
The selector jointly chooses player, role, and slot, then reports three
separate components: **XI suitability** (65% mean selection score plus 35%
weakest slot), **tactical coherence** (width, defensive cover, progression,
runners, penetration, box presence, rest defence, and redundancy limits), and
**instruction suitability**. The overall score combines the active components
and penalizes its weakest one, so an individually strong but lopsided XI cannot
win merely on player fit. These system profiles and weights are transparent POC
hypotheses, not a reproduction of FM's hidden match engine. Team *tactic*
familiarity (fluency with a shape as a whole) and opponent suitability are not
yet included; each needs a trustworthy, separately sourced policy.

*Position* familiarity is included: the recommendation output now also shows
**training targets** -- tactics whose fit would improve materially once
players are no longer penalized for playing out of position, compared against
today's *effective* fit. This is a reporting split over the existing scoring,
not a new input the bridge lacks; it uses the same raw 1-20 position rating
the probe already read for eligibility, previously discarded after that
threshold check. It says nothing about tactic familiarity above.

`--recommend` also reports **squad depth across every evaluated tactic**, not
just the selected one: a position weak in every tactic considered is flagged
separately from one weak in only some, since the latter may just reflect a
shape you would not actually play.

External-player discovery and range/unknown queries are not yet automated or
production-ready. The passive render hook remains research evidence only; it
is not used by the bridge.

## Web view

A read-only browser view renders the same recommendation the CLI does, from
the same computation (`fm_analytics.reporting.build_recommendation_bundle`),
with pages for the squad roster, best player per role, tactic comparison and
training targets, and squad-wide depth, plus a data-coverage page that works
even when the rest can't score an incomplete squad:

```bash
uv run fm-web --fixture src/fm_analytics/fixtures/sample-game.json
```

Open `http://127.0.0.1:8766`. The default source is the bundled fixture; use
`--snapshot-db data/fm-analytics.sqlite3` (optionally `--capture-id`) to serve
a captured observation, `--direct-live` or `--base-url` for the running game
or its HTTP bridge, and `--fm-html squad-general.html ...` to overlay a manual
FM20 Squad HTML export onto any of those, exactly like the CLI's `--fm-html`
flag:

```bash
uv run fm-web --direct-live --fm-html squad-general.html squad-physical.html \
  --fm-html-player-count 17
```

These sources are composable functions in `fm_analytics.web.providers`
(`fixture_provider`, `snapshot_provider`, `live_provider`,
`html_overlay_provider`), not special cases baked into the server, so a manual
source and an automated one are interchangeable without changing the view.

## Research-only HTML verification

The legacy HTML importer remains available to compare manager-visible cells
with the read-only extraction research. It is not the product workflow. For
example, validate an unchanged-save squad export with:

```bash
uv run fm-analytics --fm-html squad-general.html squad-physical.html \
  --fm-html-player-count 17
```

Create the files from the relevant FM20 Squad view with `Ctrl+P` and Web
Page/HTML selected. Stock FM20 views split attributes by category, so
`--fm-html` accepts several General, Physical, Mental, Technical, and
Goalkeeping exports. It merges them by unique squad name before binding them to
the live bridge IDs; duplicate names fail closed. Supplying the count shown in
the unchanged FM view requires that exact number of unique players after
merging, so a missing or extra row fails the import.

The CLI reports how many of the catalogue's role-model inputs are present. A
partial export can exercise tests, but its football scores are labelled
provisional.

### Standalone live owned-squad proof

The cache-independent proof source reads the managed first team directly from
the running FM20 process; it needs neither an open FM screen nor an HTML export:

```bash
uv run python tools/fm20_owned_visible_source.py --team "Hungerford Town"
```

It can instead query one managed player and selected attributes:

```bash
uv run python tools/fm20_owned_visible_source.py \
  --player-name "Yan Klukowski" \
  --attribute acceleration --attribute pace
```

The command is intentionally limited to the active manager's first-team squad,
where attributes are visible exactly in FM. It rejects another team or a player
outside that squad. External exact/ranged/unknown queries remain behind the
Phase 03 visibility gate. The first live run returned 17 Hungerford players with
41 supported attributes each; all 136 Physical cells matched the previous FM
UI export exactly. The export was validation evidence only, not an input.

The same standalone tool exposes the explicitly unsafe comparison mode used by
the page:

```bash
uv run python tools/fm20_owned_visible_source.py \
  --visibility full --acknowledge-hidden-data \
  --team "Bath City" --player-name "Adam Mann"
```

Without `--visibility full`, in-game visibility remains the default. Full mode
will not run unless the acknowledgement flag is also present.

The legacy `--candidate-html` option also exists for parser research, but it
does not satisfy the automated external-player requirement. It requires an FM
visible count and stable UID, and it is not an approved production candidate
source.

To retain an immutable, idempotent squad observation for later recommendations:

```bash
uv run fm-analytics --fixture src/fm_analytics/fixtures/sample-game.json \
  --snapshot-db data/fm-analytics.sqlite3
```

CI runs the tests, builds the Python package, and smoke-tests the fixture bridge
on Python 3.11 and 3.14. Live Proton/FM20 probes are deliberately excluded
because hosted runners do not have the game process.

To exercise the full HTTP path, use two terminals:

```bash
uv run fm-bridge
uv run fm-analytics --base-url http://localhost:5072
```

Useful bridge endpoints are `GET /v1/health`, `GET /v1/game`, and
`GET /v1/squad`. The original unversioned paths remain temporary Phase 00
compatibility aliases.

## Run against FM20 on Linux/Proton

The live adapter is proven against FM20 Steam build `20.4.4-1442341` running
through Proton on x86-64 Linux. Start FM20, load the save, then run:

```bash
FM_BRIDGE_SOURCE=linux-proton uv run fm-bridge
```

In another terminal, either print the current squad or start the monitor:

```bash
uv run fm-analytics --base-url http://127.0.0.1:5072
python3 tools/fm20_monitor.py
```

Add `--snapshot-db data/fm-analytics.sqlite3` to the `fm-analytics` command to
capture the current live squad without advancing the save.

Open `http://127.0.0.1:8765` for the monitor. It refreshes every 30 seconds and
offers approved JSON downloads at `/api/status` and `/api/squad`.

For the standalone live attribute proof, run the monitor in direct diagnostic
mode and open `/attributes`:

```bash
uv run python tools/fm20_monitor.py --direct
```

The page defaults to in-game visibility and offers the managed team and player
selectors. Its separately acknowledged **Full visibility** mode can search
other loaded teams and deliberately exposes underlying exact values for
comparison. Full-mode responses are labelled as hidden-data diagnostics and do
not enter FMBridge, snapshots, or recommendation code.

To capture a compact baseline and later check an in-game date or squad change:

```bash
python3 tools/phase00_validate.py capture data/phase00-baseline.json
python3 tools/phase00_validate.py compare data/phase00-baseline.json \
  --expect-date-change --expect-squad-change
```

For a save reload that should not change either value, use
`--expect-date-stable --expect-squad-stable` instead.

`tools/fm20_linux_probe.py` remains available with `--json` as a direct
diagnostic. The monitor can also use it via `--direct`, but the Python bridge is
the normal application boundary. All process memory access is opened read-only.
The live contract deliberately omits hidden Current Ability, Potential
Ability, raw fitness precision, and any field whose manager-visible meaning has
not been established.

## Current boundary

The public contract exposes manager-visible attribute observations as one of:

- a known exact value;
- a scouted minimum/maximum range; or
- unknown.

The web scouting workspace can now consume a manager-visible JSON capture and
refresh it through the research tooling; the legacy HTML candidate import
remains available to the CLI for verification. These are still separate
recruitment paths and neither is a stable FMBridge resource yet. Reachability
in FM's internal player database is never treated as visibility.

Research tooling can now call FM's manager-visible attribute logic off-screen
and resolve the player-search source builder directly from the active manager,
without saved UI trace pointers. The manager-rooted builder returned the exact
4,953-player Senior-package *source* in the current process; this is not the
final 4,933-player search result or a bridge endpoint. The old guided
package/search workflow is historical evidence rather than an instruction to
run another operator-led experiment. New data-discovery work starts through
the single recipe controller, `tools/fm20_research.py`; its
[automation strategy](docs/research-automation.md) defines the next gate. See
the [Phase 03 status](docs/phases/03-information-visibility/README.md) for the
underlying visibility boundary.

Hidden FM values should never cross the HTTP boundary. See
[the architecture notes](docs/architecture.md) for the current boundaries and
[the application improvement review](docs/app-improvement-review.md) for the
integration backlog. The complete staged delivery plan starts at
[the phase roadmap](docs/phases/README.md).
For planned, deliberately deferred improvements to the player and tactical
models, see [the tactical-system roadmap](docs/tactical-system-roadmap.md).
